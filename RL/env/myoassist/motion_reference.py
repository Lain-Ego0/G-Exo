"""Phase-conditioned zero-assist motion reference for the worn G-Exo plant."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np

from RL.env.myoassist.baseline import PHASE_BIN_COUNT


MOTION_REFERENCE_SCHEMA = "gexo_myoassist_urdf_motion_reference_v1"
URDF_ZERO_ASSIST_CONDITION = "urdf_worn_zero_external_torque_v1"
MINIMUM_JOINT_SCALE_RAD = np.deg2rad(1.0)


@dataclass(frozen=True)
class MotionAtSpeed:
    joint_q_mean: np.ndarray
    joint_q_scale: np.ndarray
    movement_free_z: float
    movement_transition_z: float


@dataclass(frozen=True)
class MyoAssistMotionReference:
    """Normal worn-URDF kinematics, independent from naked physiology."""

    speeds_m_s: np.ndarray
    joint_q_mean: np.ndarray
    joint_q_scale: np.ndarray
    movement_free_z: np.ndarray
    movement_transition_z: np.ndarray
    phase_bin_count: int
    metadata: dict[str, Any]
    schema: str = MOTION_REFERENCE_SCHEMA

    def __post_init__(self) -> None:
        speeds = _vector(self.speeds_m_s, "speeds_m_s")
        if np.any(speeds <= 0.0) or np.any(np.diff(speeds) <= 0.0):
            raise ValueError("speeds_m_s must be positive and strictly increasing.")
        count = len(speeds)
        if int(self.phase_bin_count) != PHASE_BIN_COUNT:
            raise ValueError(
                f"Motion reference requires {PHASE_BIN_COUNT} phase bins."
            )
        expected = (count, PHASE_BIN_COUNT, 4)
        for name in ("joint_q_mean", "joint_q_scale"):
            value = np.asarray(getattr(self, name), dtype=np.float64)
            if value.shape != expected or not np.all(np.isfinite(value)):
                raise ValueError(f"{name} must have shape {expected} and be finite.")
            if name.endswith("scale") and np.any(value <= 0.0):
                raise ValueError(f"{name} must be positive.")
            object.__setattr__(self, name, _readonly(value))
        for name in ("movement_free_z", "movement_transition_z"):
            value = _vector(getattr(self, name), name, count)
            if np.any(value <= 0.0):
                raise ValueError(f"{name} must be positive.")
            object.__setattr__(self, name, _readonly(value))
        if self.schema != MOTION_REFERENCE_SCHEMA:
            raise ValueError(f"Unsupported motion-reference schema: {self.schema}")
        metadata = dict(self.metadata)
        if metadata.get("reference_condition") != URDF_ZERO_ASSIST_CONDITION:
            raise ValueError("Motion reference must use worn-URDF zero assistance.")
        if metadata.get("urdf_enabled") is not True:
            raise ValueError("Motion reference must be collected with the URDF enabled.")
        for name in ("physical_model_sha256", "human_checkpoint_sha256"):
            if not isinstance(metadata.get(name), str) or not metadata[name]:
                raise ValueError(f"Motion-reference metadata requires {name}.")
        object.__setattr__(self, "speeds_m_s", _readonly(speeds))
        object.__setattr__(self, "phase_bin_count", int(self.phase_bin_count))
        object.__setattr__(self, "metadata", metadata)

    def at_speed(self, speed_m_s: float, gait_phase: float) -> MotionAtSpeed:
        speed = float(speed_m_s)
        phase = float(gait_phase)
        if not np.isfinite([speed, phase]).all():
            raise ValueError("speed_m_s and gait_phase must be finite.")
        lower = float(self.speeds_m_s[0])
        upper = float(self.speeds_m_s[-1])
        tolerance = 1.0e-9
        if speed < lower - tolerance or speed > upper + tolerance:
            raise ValueError(
                f"Speed {speed} is outside motion-reference range [{lower}, {upper}]."
            )
        speed = float(np.clip(speed, lower, upper))
        position = (phase % 1.0) * self.phase_bin_count - 0.5
        phase_lower = int(np.floor(position)) % self.phase_bin_count
        phase_upper = (phase_lower + 1) % self.phase_bin_count
        fraction = position - np.floor(position)

        def phase_speed(values: np.ndarray) -> np.ndarray:
            phase_values = (
                (1.0 - fraction) * values[:, phase_lower]
                + fraction * values[:, phase_upper]
            )
            if phase_values.ndim == 1:
                return np.asarray(
                    np.interp(speed, self.speeds_m_s, phase_values)
                )
            return np.asarray(
                [
                    np.interp(speed, self.speeds_m_s, phase_values[:, joint])
                    for joint in range(phase_values.shape[1])
                ],
                dtype=np.float64,
            )

        return MotionAtSpeed(
            joint_q_mean=phase_speed(self.joint_q_mean),
            joint_q_scale=phase_speed(self.joint_q_scale),
            movement_free_z=float(
                np.interp(speed, self.speeds_m_s, self.movement_free_z)
            ),
            movement_transition_z=float(
                np.interp(speed, self.speeds_m_s, self.movement_transition_z)
            ),
        )

    def nearest_at_speed(
        self,
        speed_m_s: float,
        joint_q_rad: np.ndarray,
    ) -> MotionAtSpeed:
        """Match kinematics to the nearest cycle state without an external phase."""

        speed = float(speed_m_s)
        q = np.asarray(joint_q_rad, dtype=np.float64)
        if not np.isfinite(speed) or q.shape != (4,) or not np.all(np.isfinite(q)):
            raise ValueError("speed_m_s must be finite and joint_q_rad shape (4,).")
        lower = float(self.speeds_m_s[0])
        upper = float(self.speeds_m_s[-1])
        if speed < lower - 1.0e-9 or speed > upper + 1.0e-9:
            raise ValueError(
                f"Speed {speed} is outside motion-reference range [{lower}, {upper}]."
            )
        speed = float(np.clip(speed, lower, upper))

        means = np.empty((self.phase_bin_count, 4), dtype=np.float64)
        scales = np.empty_like(means)
        for phase_index in range(self.phase_bin_count):
            for joint in range(4):
                means[phase_index, joint] = np.interp(
                    speed,
                    self.speeds_m_s,
                    self.joint_q_mean[:, phase_index, joint],
                )
                scales[phase_index, joint] = np.interp(
                    speed,
                    self.speeds_m_s,
                    self.joint_q_scale[:, phase_index, joint],
                )
        standardized_error = np.sqrt(
            np.mean(np.square((q[None, :] - means) / scales), axis=1)
        )
        nearest = int(np.argmin(standardized_error))
        return MotionAtSpeed(
            joint_q_mean=means[nearest],
            joint_q_scale=scales[nearest],
            movement_free_z=float(
                np.interp(speed, self.speeds_m_s, self.movement_free_z)
            ),
            movement_transition_z=float(
                np.interp(speed, self.speeds_m_s, self.movement_transition_z)
            ),
        )

    def to_dict(self) -> dict[str, Any]:
        result: dict[str, Any] = {"schema": self.schema, "metadata": self.metadata}
        for name in self.__dataclass_fields__:
            if name in ("schema", "metadata"):
                continue
            value = getattr(self, name)
            result[name] = value.tolist() if isinstance(value, np.ndarray) else value
        return result

    def save(self, path: str | Path) -> Path:
        output = Path(path).expanduser().resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True),
            encoding="utf-8",
        )
        return output

    @classmethod
    def load(cls, path: str | Path) -> "MyoAssistMotionReference":
        source = Path(path).expanduser().resolve(strict=True)
        return cls(**json.loads(source.read_text(encoding="utf-8")))


def fit_motion_reference(
    *,
    speed_m_s: np.ndarray,
    gait_phase: np.ndarray,
    joint_q_rad: np.ndarray,
    metadata: dict[str, Any],
) -> MyoAssistMotionReference:
    """Fit phase-wise kinematics and a data-derived standardized hinge."""

    speed = _vector(speed_m_s, "speed_m_s")
    phase = _vector(gait_phase, "gait_phase", len(speed)) % 1.0
    joint_q = np.asarray(joint_q_rad, dtype=np.float64)
    if joint_q.shape != (len(speed), 4) or not np.all(np.isfinite(joint_q)):
        raise ValueError("joint_q_rad must have shape (frames, 4) and be finite.")
    bins = np.unique(speed)
    means = np.empty((len(bins), PHASE_BIN_COUNT, 4), dtype=np.float64)
    scales = np.empty_like(means)
    phase_indices = np.floor(phase * PHASE_BIN_COUNT).astype(int) % PHASE_BIN_COUNT
    for speed_index, value in enumerate(bins):
        speed_mask = np.isclose(speed, value, rtol=0.0, atol=1.0e-9)
        for phase_index in range(PHASE_BIN_COUNT):
            values = joint_q[speed_mask & (phase_indices == phase_index)]
            if len(values) < 2:
                raise ValueError(
                    f"Speed {value}, phase bin {phase_index} needs two frames."
                )
            center = np.mean(values, axis=0)
            means[speed_index, phase_index] = center
            scales[speed_index, phase_index] = np.asarray(
                [_robust_scale(values[:, joint]) for joint in range(4)]
            )

    free_z = np.empty(len(bins), dtype=np.float64)
    transition_z = np.empty(len(bins), dtype=np.float64)
    provisional = MyoAssistMotionReference(
        speeds_m_s=bins,
        joint_q_mean=means,
        joint_q_scale=scales,
        movement_free_z=np.ones(len(bins)),
        movement_transition_z=np.ones(len(bins)),
        phase_bin_count=PHASE_BIN_COUNT,
        metadata=metadata,
    )
    for speed_index, value in enumerate(bins):
        mask = np.isclose(speed, value, rtol=0.0, atol=1.0e-9)
        residuals = []
        for sample_q, sample_phase in zip(joint_q[mask], phase[mask]):
            reference = provisional.at_speed(value, sample_phase)
            residuals.append(
                np.sqrt(
                    np.mean(
                        np.square(
                            (sample_q - reference.joint_q_mean)
                            / reference.joint_q_scale
                        )
                    )
                )
            )
        residuals = np.asarray(residuals)
        free_z[speed_index] = max(float(np.percentile(residuals, 99.0)), 0.5)
        transition_z[speed_index] = max(float(np.std(residuals)), 1.0)

    return MyoAssistMotionReference(
        speeds_m_s=bins,
        joint_q_mean=means,
        joint_q_scale=scales,
        movement_free_z=free_z,
        movement_transition_z=transition_z,
        phase_bin_count=PHASE_BIN_COUNT,
        metadata=metadata,
    )


def _robust_scale(values: np.ndarray) -> float:
    median = float(np.median(values))
    mad = 1.4826 * float(np.median(np.abs(values - median)))
    return max(float(np.std(values)), mad, MINIMUM_JOINT_SCALE_RAD)


def _vector(value: np.ndarray, name: str, size: int | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 1 or (size is not None and len(array) != size):
        raise ValueError(f"{name} must have shape ({size or 'frames'},).")
    if len(array) < 1 or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite and non-empty.")
    return array.copy()


def _readonly(value: np.ndarray) -> np.ndarray:
    result = np.asarray(value, dtype=np.float64).copy()
    result.flags.writeable = False
    return result


__all__ = [
    "MOTION_REFERENCE_SCHEMA",
    "URDF_ZERO_ASSIST_CONDITION",
    "MotionAtSpeed",
    "MyoAssistMotionReference",
    "fit_motion_reference",
]
