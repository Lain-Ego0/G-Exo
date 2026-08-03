"""Backend-neutral calibration helpers for the frozen Phase 1/2 TCN."""

from __future__ import annotations

from itertools import permutations, product

import numpy as np

from RL.env.actor_observation import (
    TCN_FEATURE_DIM,
    runtime32_to_phase12_interleaved,
)
from RL.runners.predictors.tcn_runtime import FrozenTCNRuntime


ROTATION_ACCEPTANCE_RATIO = 0.8


def runtime32_to_interleaved_batch(frames: np.ndarray) -> np.ndarray:
    values = _matrix(frames, "frames", 32)
    return np.stack(
        [runtime32_to_phase12_interleaved(frame) for frame in values]
    )


def proper_axis_rotations() -> tuple[np.ndarray, ...]:
    """Return the 24 right-handed signed axis permutations."""

    rotations: list[np.ndarray] = []
    for order in permutations(range(3)):
        for signs in product((-1.0, 1.0), repeat=3):
            matrix = np.zeros((3, 3), dtype=np.float64)
            for row, column in enumerate(order):
                matrix[row, column] = signs[row]
            if np.isclose(np.linalg.det(matrix), 1.0):
                rotations.append(matrix)
    return tuple(rotations)


def fit_motor_input_calibration(
    phase_inputs: np.ndarray,
    runtime_frames: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Fit only joint sign and encoder zero; radians keep unit gain."""

    phase = _matrix(phase_inputs, "phase_inputs", 32)
    runtime = _matrix(runtime_frames, "runtime_frames", 32)
    phase_mean = phase[:, :4].mean(axis=0)
    runtime_mean = runtime[:, :4].mean(axis=0)
    scale = np.where(
        np.abs(-runtime_mean - phase_mean)
        < np.abs(runtime_mean - phase_mean),
        -1.0,
        1.0,
    )
    offset = phase_mean - scale * runtime_mean
    return scale, offset, scale.copy()


def fit_imu_rotations(
    phase_inputs: np.ndarray,
    runtime_frames: np.ndarray,
) -> tuple[np.ndarray, list[dict[str, float | bool]]]:
    """Select a physical axis rotation by distribution moments only."""

    phase = _matrix(phase_inputs, "phase_inputs", 32)
    runtime = runtime32_to_interleaved_batch(runtime_frames)
    rotations = proper_axis_rotations()
    selected: list[np.ndarray] = []
    diagnostics: list[dict[str, float | bool]] = []
    identity_index = next(
        index
        for index, rotation in enumerate(rotations)
        if np.array_equal(rotation, np.eye(3))
    )

    for imu_index in range(4):
        start = 8 + imu_index * 6
        phase_gyro = phase[:, start : start + 3]
        phase_force = phase[:, start + 3 : start + 6]
        runtime_gyro = runtime[:, start : start + 3]
        runtime_force = runtime[:, start + 3 : start + 6]
        costs = np.asarray(
            [
                _moment_cost(phase_gyro, runtime_gyro @ rotation.T)
                + 2.0 * _moment_cost(
                    phase_force,
                    runtime_force @ rotation.T,
                )
                for rotation in rotations
            ]
        )
        best_index = int(np.argmin(costs))
        accepted_index = (
            best_index
            if costs[best_index]
            < ROTATION_ACCEPTANCE_RATIO * costs[identity_index]
            else identity_index
        )
        selected.append(rotations[accepted_index])
        diagnostics.append(
            {
                "best_candidate_cost": float(costs[best_index]),
                "selected_cost": float(costs[accepted_index]),
                "identity_cost": float(costs[identity_index]),
                "non_identity_accepted": accepted_index != identity_index,
            }
        )
    return np.stack(selected), diagnostics


def fit_output_calibration(
    trajectories: list[np.ndarray],
    runtime: FrozenTCNRuntime,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, float]]]:
    """Fit frozen-TCN q/dq outputs to future backend joint states."""

    predictions: list[np.ndarray] = []
    actuals: list[np.ndarray] = []
    maximum_horizon = max(runtime.horizons)
    for trajectory in trajectories:
        values = _matrix(trajectory, "trajectory", 32)
        if len(values) < runtime.history_length + maximum_horizon:
            continue
        runtime.reset()
        runtime.extend(values[: runtime.history_length])
        for current in range(
            runtime.history_length - 1,
            len(values) - maximum_horizon,
        ):
            result = runtime.predict(values[current, :4], values[current, 4:8])
            for horizon_index, horizon in enumerate(runtime.horizons):
                predictions.append(result.prediction[horizon_index, :8])
                actuals.append(values[current + horizon, :8])
            next_index = current + 1
            if next_index < len(values):
                runtime.append(values[next_index])

    predicted = np.asarray(predictions, dtype=np.float64)
    actual = np.asarray(actuals, dtype=np.float64)
    if predicted.shape != actual.shape or predicted.ndim != 2 or predicted.shape[1] != 8:
        raise RuntimeError("No valid TCN/backend output calibration pairs.")

    position_scale = np.empty(4, dtype=np.float64)
    position_offset = np.empty(4, dtype=np.float64)
    diagnostics: list[dict[str, float]] = []
    for joint in range(4):
        q_scale, q_offset = np.polyfit(predicted[:, joint], actual[:, joint], 1)
        q_estimate = q_scale * predicted[:, joint] + q_offset
        dq_estimate = q_scale * predicted[:, 4 + joint]
        position_scale[joint] = q_scale
        position_offset[joint] = q_offset
        diagnostics.append(
            {
                "position_scale": float(q_scale),
                "position_offset": float(q_offset),
                "position_rmse_rad": _rmse(q_estimate, actual[:, joint]),
                "velocity_rmse_rad_s": _rmse(
                    dq_estimate,
                    actual[:, 4 + joint],
                ),
                "position_correlation": _correlation(
                    predicted[:, joint],
                    actual[:, joint],
                ),
                "velocity_correlation": _correlation(
                    predicted[:, 4 + joint],
                    actual[:, 4 + joint],
                ),
            }
        )
    return position_scale, position_offset, position_scale.copy(), diagnostics


def collect_raw_delta_features(
    trajectories: list[np.ndarray],
    runtime: FrozenTCNRuntime,
) -> np.ndarray:
    features: list[np.ndarray] = []
    for trajectory in trajectories:
        values = _matrix(trajectory, "trajectory", 32)
        if len(values) < runtime.history_length:
            continue
        runtime.reset()
        runtime.extend(values[: runtime.history_length])
        for current in range(runtime.history_length - 1, len(values)):
            result = runtime.predict(values[current, :4], values[current, 4:8])
            features.append(result.raw_delta16)
            if current + 1 < len(values):
                runtime.append(values[current + 1])
    result = np.asarray(features, dtype=np.float64)
    if result.ndim != 2 or result.shape[1] != TCN_FEATURE_DIM or len(result) < 2:
        raise RuntimeError("No valid TCN delta features were collected.")
    return result


def fit_feature_normalization(
    raw_features: np.ndarray,
    *,
    clip: float = 5.0,
    minimum_std: float = 1.0e-4,
) -> dict[str, object]:
    values = _matrix(raw_features, "raw_features", TCN_FEATURE_DIM)
    if len(values) < 2 or clip <= 0.0 or minimum_std <= 0.0:
        raise ValueError("Feature fit needs two samples and positive settings.")
    return {
        "horizon_steps": [5, 10],
        "mean": values.mean(axis=0).tolist(),
        "std": np.maximum(values.std(axis=0), minimum_std).tolist(),
        "clip": float(clip),
        "minimum_std": float(minimum_std),
        "samples": int(len(values)),
    }


def distribution_metrics(values: np.ndarray) -> dict[str, float]:
    array = np.asarray(values, dtype=np.float64)
    if array.size < 1 or not np.all(np.isfinite(array)):
        raise ValueError("values must be finite and non-empty.")
    absolute = np.abs(array)
    return {
        "mean_absolute_z": float(np.mean(absolute)),
        "p95_absolute_z": float(np.percentile(absolute, 95.0)),
        "fraction_above_3_sigma": float(np.mean(absolute > 3.0)),
        "fraction_above_5_sigma": float(np.mean(absolute > 5.0)),
    }


def _moment_cost(reference: np.ndarray, candidate: np.ndarray) -> float:
    reference_std = np.maximum(reference.std(axis=0), 0.1)
    candidate_std = np.maximum(candidate.std(axis=0), 0.1)
    mean_cost = np.mean(
        np.square((candidate.mean(axis=0) - reference.mean(axis=0)) / reference_std)
    )
    scale_cost = np.mean(np.square(np.log(candidate_std / reference_std)))
    return float(mean_cost + 0.25 * scale_cost)


def _matrix(value: np.ndarray, name: str, columns: int) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 2 or array.shape[1] != columns or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite with shape [sample, {columns}].")
    return array


def _rmse(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.sqrt(np.mean(np.square(left - right))))


def _correlation(left: np.ndarray, right: np.ndarray) -> float:
    if np.std(left) <= 1.0e-12 or np.std(right) <= 1.0e-12:
        return 0.0
    return float(np.corrcoef(left, right)[0, 1])


__all__ = [
    "collect_raw_delta_features",
    "distribution_metrics",
    "fit_feature_normalization",
    "fit_imu_rotations",
    "fit_motor_input_calibration",
    "fit_output_calibration",
    "proper_axis_rotations",
    "runtime32_to_interleaved_batch",
]
