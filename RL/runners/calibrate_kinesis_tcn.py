"""Fit a reproducible Phase 1/2 to Kinesis TCN calibration."""

from __future__ import annotations

import argparse
from itertools import permutations, product
import json
import os
from pathlib import Path

import numpy as np

from RL.env.kinesis.baseline_reference import DEFAULT_PHYSICAL_BASELINE_DIR
from RL.env.kinesis.exo_env import KinesisExoEnv
from RL.env.kinesis.tcn_adapter import TCNInputAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHECKPOINT = (
    PROJECT_ROOT / "RL/outputs/tcn_runs/seed_43/best_model.pt"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "RL/assets/tcn/kinesis_phase12_calibration.json"
)
CALIBRATION_MOTIONS = (2, 8, 9, 11, 16, 38, 43, 52)
HOLDOUT_MOTIONS = (64, 82, 99)
ROTATION_ACCEPTANCE_RATIO = 0.8


def load_phase_data(
    root: Path,
) -> tuple[np.ndarray, list[tuple[np.ndarray, np.ndarray]]]:
    """Load valid training inputs and angle/encoder pairs per joint."""

    paths = sorted(root.glob("*/*.npz"))
    if not paths:
        raise FileNotFoundError(f"No Phase 1/2 training NPZ files in {root}")

    valid_inputs: list[np.ndarray] = []
    pairs: list[list[tuple[np.ndarray, np.ndarray]]] = [
        [] for _ in range(4)
    ]
    for path in paths:
        with np.load(path) as data:
            inputs = data["input"].astype(np.float64)
            targets = data["target"].astype(np.float64)
            input_valid = data["input_valid"].astype(bool)
            target_mask = data["target_mask"].astype(bool)
            valid_inputs.append(inputs[input_valid])

            for joint in range(4):
                valid = input_valid & target_mask[:, joint]
                pairs[joint].append(
                    (targets[valid, joint], inputs[valid, joint])
                )

    joined_pairs = [
        (
            np.concatenate([pair[0] for pair in joint_pairs]),
            np.concatenate([pair[1] for pair in joint_pairs]),
        )
        for joint_pairs in pairs
    ]
    return np.concatenate(valid_inputs), joined_pairs


def collect_kinesis_frames(
    motion_ids: tuple[int, ...],
    *,
    seed: int,
    steps: int,
    baseline_dir: Path,
) -> list[np.ndarray]:
    """Collect zero-assist deployable sensor frames from calibration motions."""

    trajectories: list[np.ndarray] = []
    for motion_id in motion_ids:
        frames: list[np.ndarray] = []
        env = KinesisExoEnv(
            motion_id=motion_id,
            baseline_dir=baseline_dir,
            warmup_steps=50,
            max_episode_steps=steps,
        )
        try:
            env.reset(seed=seed)
            frames.extend(env.raw_sensor_history)
            for _ in range(steps):
                _, _, terminated, truncated, _ = env.step(
                    np.zeros(4, dtype=np.float32)
                )
                frames.append(env.latest_raw_sensor_frame)
                if terminated or truncated:
                    break
        finally:
            env.close()
        trajectories.append(np.stack(frames).astype(np.float64))

    return trajectories


def environment_to_dataset_order(frames: np.ndarray) -> np.ndarray:
    """Reorder raw Kinesis sensors without applying calibration."""

    gyro = frames[:, 8:20].reshape(-1, 4, 3)
    specific_force = frames[:, 20:32].reshape(-1, 4, 3)
    imu = np.concatenate((gyro, specific_force), axis=2).reshape(-1, 24)
    return np.concatenate((frames[:, :8], imu), axis=1)


def proper_axis_rotations() -> list[np.ndarray]:
    """Return the 24 right-handed signed permutation rotations."""

    rotations: list[np.ndarray] = []
    for order in permutations(range(3)):
        for signs in product((-1.0, 1.0), repeat=3):
            matrix = np.zeros((3, 3), dtype=np.float64)
            for row, column in enumerate(order):
                matrix[row, column] = signs[row]
            if np.isclose(np.linalg.det(matrix), 1.0):
                rotations.append(matrix)
    return rotations


def moment_cost(reference: np.ndarray, candidate: np.ndarray) -> float:
    """Compare axis means and standard deviations without fitting gains."""

    reference_mean = reference.mean(axis=0)
    reference_std = np.maximum(reference.std(axis=0), 0.1)
    candidate_mean = candidate.mean(axis=0)
    candidate_std = np.maximum(candidate.std(axis=0), 0.1)

    mean_cost = np.mean(
        np.square((candidate_mean - reference_mean) / reference_std)
    )
    scale_cost = np.mean(
        np.square(np.log(candidate_std / reference_std))
    )
    return float(mean_cost + 0.25 * scale_cost)


def fit_imu_rotations(
    phase_inputs: np.ndarray,
    kinesis_ordered: np.ndarray,
) -> tuple[np.ndarray, list[dict[str, float]]]:
    rotations = proper_axis_rotations()
    selected: list[np.ndarray] = []
    diagnostics: list[dict[str, float]] = []

    for imu_index in range(4):
        start = 8 + imu_index * 6
        phase_gyro = phase_inputs[:, start : start + 3]
        phase_accel = phase_inputs[:, start + 3 : start + 6]
        kinesis_gyro = kinesis_ordered[:, start : start + 3]
        kinesis_accel = kinesis_ordered[:, start + 3 : start + 6]

        costs = []
        for rotation in rotations:
            rotated_gyro = kinesis_gyro @ rotation.T
            rotated_accel = kinesis_accel @ rotation.T
            costs.append(
                moment_cost(phase_gyro, rotated_gyro)
                + 2.0 * moment_cost(phase_accel, rotated_accel)
            )

        best_index = int(np.argmin(costs))
        identity_index = next(
            index
            for index, rotation in enumerate(rotations)
            if np.array_equal(rotation, np.eye(3))
        )
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
                "non_identity_accepted": bool(
                    accepted_index != identity_index
                ),
            }
        )

    return np.stack(selected), diagnostics


def distribution_metrics(values: np.ndarray) -> dict[str, float]:
    absolute = np.abs(values)
    return {
        "mean_absolute_z": float(np.mean(absolute)),
        "p95_absolute_z": float(np.percentile(absolute, 95.0)),
        "fraction_above_3_sigma": float(np.mean(absolute > 3.0)),
        "fraction_above_5_sigma": float(np.mean(absolute > 5.0)),
    }


def fit_direct_output_calibration(
    trajectories: list[np.ndarray],
    adapter: TCNInputAdapter,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, list[dict[str, float]]]:
    """Fit frozen TCN targets directly to future Kinesis joint states."""

    predictions: list[np.ndarray] = []
    actuals: list[np.ndarray] = []
    maximum_horizon = max(adapter.horizons)

    for trajectory in trajectories:
        if len(trajectory) < adapter.history_length + maximum_horizon:
            continue
        adapter.reset()
        adapter.extend(trajectory[: adapter.history_length])

        for current in range(
            adapter.history_length - 1,
            len(trajectory) - maximum_horizon,
        ):
            result = adapter.predict()
            for horizon_index, horizon in enumerate(adapter.horizons):
                predictions.append(result.prediction[horizon_index, :8])
                actuals.append(trajectory[current + horizon, :8])

            next_index = current + 1
            if next_index < len(trajectory):
                adapter.append(trajectory[next_index])

    predicted = np.asarray(predictions, dtype=np.float64)
    actual = np.asarray(actuals, dtype=np.float64)
    if predicted.shape != actual.shape or predicted.shape[1] != 8:
        raise RuntimeError("Invalid direct output calibration pairs.")

    position_scale = np.empty(4, dtype=np.float64)
    position_offset = np.empty(4, dtype=np.float64)
    velocity_scale = np.empty(4, dtype=np.float64)
    diagnostics: list[dict[str, float]] = []

    for joint in range(4):
        q_scale, q_offset = np.polyfit(
            predicted[:, joint],
            actual[:, joint],
            1,
        )
        predicted_velocity = predicted[:, 4 + joint]
        actual_velocity = actual[:, 4 + joint]
        denominator = float(np.dot(predicted_velocity, predicted_velocity))
        if denominator <= 1.0e-12:
            raise RuntimeError("TCN velocity prediction has zero variance.")
        dq_scale = float(
            np.dot(predicted_velocity, actual_velocity) / denominator
        )

        q_residual = q_scale * predicted[:, joint] + q_offset - actual[:, joint]
        dq_residual = dq_scale * predicted_velocity - actual_velocity
        position_scale[joint] = q_scale
        position_offset[joint] = q_offset
        velocity_scale[joint] = dq_scale
        diagnostics.append(
            {
                "position_scale": float(q_scale),
                "position_offset": float(q_offset),
                "velocity_scale": float(dq_scale),
                "position_rmse_rad": float(
                    np.sqrt(np.mean(np.square(q_residual)))
                ),
                "velocity_rmse_rad_s": float(
                    np.sqrt(np.mean(np.square(dq_residual)))
                ),
                "position_correlation": float(
                    np.corrcoef(predicted[:, joint], actual[:, joint])[0, 1]
                ),
                "velocity_correlation": float(
                    np.corrcoef(predicted_velocity, actual_velocity)[0, 1]
                ),
            }
        )

    return position_scale, position_offset, velocity_scale, diagnostics


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase-root", type=Path)
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=DEFAULT_PHYSICAL_BASELINE_DIR,
    )
    parser.add_argument(
        "--motion-ids",
        type=int,
        nargs="+",
        default=CALIBRATION_MOTIONS,
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    phase_root = args.phase_root
    if phase_root is None:
        data_root = os.environ.get("GEXO_DATA_ROOT")
        if not data_root:
            raise RuntimeError("Set GEXO_DATA_ROOT or pass --phase-root.")
        phase_root = Path(data_root) / "processed/tcn50/train"

    calibration_motions = tuple(args.motion_ids)
    overlap = set(calibration_motions) & set(HOLDOUT_MOTIONS)
    if overlap:
        raise ValueError(
            f"Holdout motions cannot be used for calibration: {sorted(overlap)}"
        )

    phase_inputs, joint_pairs = load_phase_data(phase_root)
    kinesis_trajectories = collect_kinesis_frames(
        calibration_motions,
        seed=args.seed,
        steps=args.steps,
        baseline_dir=args.baseline_dir,
    )
    kinesis_frames = np.concatenate(kinesis_trajectories)
    kinesis_ordered = environment_to_dataset_order(kinesis_frames)

    phase_q_mean = phase_inputs[:, :4].mean(axis=0)
    phase_q_std = phase_inputs[:, :4].std(axis=0)
    kinesis_q_mean = kinesis_ordered[:, :4].mean(axis=0)

    motor_scale = np.ones(4, dtype=np.float64)
    for joint in range(4):
        positive_error = abs(kinesis_q_mean[joint] - phase_q_mean[joint])
        negative_error = abs(-kinesis_q_mean[joint] - phase_q_mean[joint])
        motor_scale[joint] = -1.0 if negative_error < positive_error else 1.0

    # Radians share the same physical gain.  Only sign and zero are calibrated.
    motor_offset = phase_q_mean - motor_scale * kinesis_q_mean
    imu_rotation, imu_diagnostics = fit_imu_rotations(
        phase_inputs,
        kinesis_ordered,
    )

    encoder_from_bio_scale = np.empty(4, dtype=np.float64)
    encoder_from_bio_offset = np.empty(4, dtype=np.float64)
    regression_diagnostics = []
    for joint, (bio_angle, encoder_angle) in enumerate(joint_pairs):
        slope, intercept = np.polyfit(bio_angle, encoder_angle, 1)
        residual = slope * bio_angle + intercept - encoder_angle
        encoder_from_bio_scale[joint] = slope
        encoder_from_bio_offset[joint] = intercept
        regression_diagnostics.append(
            {
                "slope": float(slope),
                "offset": float(intercept),
                "rmse_rad": float(np.sqrt(np.mean(np.square(residual)))),
                "correlation": float(
                    np.corrcoef(bio_angle, encoder_angle)[0, 1]
                ),
                "samples": int(bio_angle.size),
            }
        )

    # This anatomical mapping is retained as a diagnostic.  The final output
    # calibration below is fitted directly from frozen-TCN predictions.
    anatomical_position_scale = encoder_from_bio_scale / motor_scale
    anatomical_position_offset = (
        encoder_from_bio_offset - motor_offset
    ) / motor_scale

    input_adapter = TCNInputAdapter(
        args.checkpoint,
        motor_position_scale=motor_scale,
        motor_position_offset=motor_offset,
        motor_velocity_scale=motor_scale,
        imu_rotation=imu_rotation,
    )
    (
        target_position_scale,
        target_position_offset,
        direct_velocity_scale,
        direct_output_diagnostics,
    ) = fit_direct_output_calibration(
        kinesis_trajectories,
        input_adapter,
    )
    # A separately fitted velocity gain can collapse predictions toward zero.
    # Use the derivative-consistent angle gain for deployment instead.
    target_velocity_scale = target_position_scale.copy()

    calibration = {
        "schema_version": 1,
        "method": "phase12_input_moments_and_direct_kinesis_output_affine",
        "checkpoint": str(args.checkpoint.expanduser().resolve()),
        "phase_root": str(phase_root.expanduser().resolve()),
        "calibration_motion_ids": list(calibration_motions),
        "holdout_motion_ids": list(HOLDOUT_MOTIONS),
        "input": {
            "motor_position_scale": motor_scale.tolist(),
            "motor_position_offset": motor_offset.tolist(),
            "motor_velocity_scale": motor_scale.tolist(),
            "imu_rotation": imu_rotation.tolist(),
        },
        "output": {
            "target_position_scale": target_position_scale.tolist(),
            "target_position_offset": target_position_offset.tolist(),
            "target_velocity_scale": target_velocity_scale.tolist(),
        },
        "fit": {
            "phase_frames": int(phase_inputs.shape[0]),
            "kinesis_frames": int(kinesis_frames.shape[0]),
            "phase_motor_position_mean": phase_q_mean.tolist(),
            "phase_motor_position_std": phase_q_std.tolist(),
            "kinesis_motor_position_mean": kinesis_q_mean.tolist(),
            "target_to_encoder_regression": regression_diagnostics,
            "anatomical_position_scale": anatomical_position_scale.tolist(),
            "anatomical_position_offset": anatomical_position_offset.tolist(),
            "direct_tcn_to_kinesis_regression": direct_output_diagnostics,
            "direct_velocity_scale_rejected": direct_velocity_scale.tolist(),
            "imu_rotation_cost": imu_diagnostics,
        },
    }

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(calibration, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    adapter = TCNInputAdapter(
        args.checkpoint,
        calibration=output,
    )
    calibrated = np.stack(
        [adapter.to_tcn_order(frame) for frame in kinesis_frames]
    )
    z = (calibrated - adapter.input_mean) / adapter.input_std
    calibration["fit"]["calibrated_input_distribution"] = (
        distribution_metrics(z)
    )
    output.write_text(
        json.dumps(calibration, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("motor scale:", motor_scale)
    print("motor offset:", np.round(motor_offset, 6))
    print("target position scale:", np.round(target_position_scale, 6))
    print("target position offset:", np.round(target_position_offset, 6))
    print("target velocity scale:", np.round(target_velocity_scale, 6))
    print("input distribution:", distribution_metrics(z))
    print("calibration:", output)


if __name__ == "__main__":
    main()
