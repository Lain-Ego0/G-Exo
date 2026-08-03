"""Frozen zero-assist statistics used by the MyoAssist G-Exo reward."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np


BASELINE_SCHEMA = "gexo_myoassist_zero_assist_baseline_v3"
SPEED_WINDOW_STEPS = 50
TRAINING_SPEED_SCHEDULE = "uniform_per_episode_v1"
EPSILON = 1.0e-6


class ForwardSpeedWindow:
    """Causal rolling mean shared by baseline collection and PPO runtime."""

    def __init__(self, window_steps: int = SPEED_WINDOW_STEPS) -> None:
        self.window_steps = int(window_steps)
        if self.window_steps < 1:
            raise ValueError("window_steps must be positive.")
        self._values: deque[float] = deque(maxlen=self.window_steps)

    def reset(self) -> None:
        self._values.clear()

    def append(self, speed_m_s: float) -> float:
        value = float(speed_m_s)
        if not np.isfinite(value):
            raise ValueError("Forward speed must be finite.")
        self._values.append(value)
        return self.mean

    @property
    def mean(self) -> float:
        if not self._values:
            raise RuntimeError("Forward-speed window is empty.")
        return float(np.mean(self._values))

    @property
    def sample_count(self) -> int:
        return len(self._values)

    @property
    def full(self) -> bool:
        return self.sample_count == self.window_steps


@dataclass(frozen=True)
class BaselineAtSpeed:
    activation_mean: float
    activation_std: float
    human_torque_mean: float
    human_torque_std: float
    gross_median: float
    gross_scale: float
    speed_free_error_m_s: float
    speed_transition_m_s: float


@dataclass(frozen=True)
class MyoAssistBaseline:
    speeds_m_s: np.ndarray
    activation_mean: np.ndarray
    activation_std: np.ndarray
    human_torque_mean: np.ndarray
    human_torque_std: np.ndarray
    gross_median: np.ndarray
    gross_scale: np.ndarray
    human_joint_scale_nm: np.ndarray
    gross_joint_scale_nm: np.ndarray
    speed_window_steps: int
    speed_free_error_m_s: np.ndarray
    speed_transition_m_s: np.ndarray
    minimum_pelvis_height_m: float
    pelvis_height_transition_m: float
    pelvis_pitch_free_rad: float
    pelvis_pitch_transition_rad: float
    joint_lower_rad: np.ndarray
    joint_upper_rad: np.ndarray
    joint_limit_margin_rad: np.ndarray
    joint_limit_transition_rad: np.ndarray
    metadata: dict[str, Any]
    schema: str = BASELINE_SCHEMA

    def __post_init__(self) -> None:
        speeds = _vector(self.speeds_m_s, "speeds_m_s")
        if len(speeds) < 1 or np.any(speeds <= 0.0) or np.any(np.diff(speeds) <= 0.0):
            raise ValueError("speeds_m_s must be positive and strictly increasing.")
        count = len(speeds)
        fields = (
            "activation_mean",
            "activation_std",
            "human_torque_mean",
            "human_torque_std",
            "gross_median",
            "gross_scale",
            "speed_free_error_m_s",
            "speed_transition_m_s",
        )
        for name in fields:
            value = _vector(getattr(self, name), name, count)
            if name.endswith(("std", "scale", "transition_m_s")) and np.any(
                value <= 0.0
            ):
                raise ValueError(f"{name} must be positive.")
            if name == "speed_free_error_m_s" and np.any(value < 0.0):
                raise ValueError(f"{name} must be non-negative.")
            object.__setattr__(self, name, _readonly(value))

        for name in (
            "human_joint_scale_nm",
            "gross_joint_scale_nm",
            "joint_limit_transition_rad",
        ):
            value = _vector(getattr(self, name), name, 4)
            if np.any(value <= 0.0):
                raise ValueError(f"{name} must be positive.")
            object.__setattr__(self, name, _readonly(value))
        lower = _vector(self.joint_lower_rad, "joint_lower_rad", 4)
        upper = _vector(self.joint_upper_rad, "joint_upper_rad", 4)
        margin = _vector(self.joint_limit_margin_rad, "joint_limit_margin_rad", 4)
        if np.any(lower >= upper) or np.any(margin < 0.0):
            raise ValueError("Joint bounds or margins are invalid.")
        if np.any(lower + margin >= upper - margin):
            raise ValueError("Joint limit margins leave no free interval.")
        object.__setattr__(self, "speeds_m_s", _readonly(speeds))
        object.__setattr__(self, "joint_lower_rad", _readonly(lower))
        object.__setattr__(self, "joint_upper_rad", _readonly(upper))
        object.__setattr__(self, "joint_limit_margin_rad", _readonly(margin))

        speed_window_steps = int(self.speed_window_steps)
        if speed_window_steps != SPEED_WINDOW_STEPS:
            raise ValueError(
                "Formal MyoAssist baseline requires exactly "
                f"{SPEED_WINDOW_STEPS} forward-speed window steps."
            )
        object.__setattr__(self, "speed_window_steps", speed_window_steps)

        for name in (
            "minimum_pelvis_height_m",
            "pelvis_height_transition_m",
            "pelvis_pitch_free_rad",
            "pelvis_pitch_transition_rad",
        ):
            value = float(getattr(self, name))
            if not np.isfinite(value):
                raise ValueError(f"{name} must be finite.")
            if name.endswith(("transition_m_s", "transition_m", "transition_rad")):
                if value <= 0.0:
                    raise ValueError(f"{name} must be positive.")
            elif name != "minimum_pelvis_height_m" and value < 0.0:
                raise ValueError(f"{name} must be non-negative.")
            object.__setattr__(self, name, value)
        if self.schema != BASELINE_SCHEMA:
            raise ValueError(f"Unsupported baseline schema: {self.schema}")
        object.__setattr__(self, "metadata", dict(self.metadata))

    def at_speed(self, speed_m_s: float) -> BaselineAtSpeed:
        speed = float(speed_m_s)
        if not np.isfinite(speed):
            raise ValueError("speed_m_s must be finite.")
        lower = float(self.speeds_m_s[0])
        upper = float(self.speeds_m_s[-1])
        tolerance = 64.0 * np.finfo(np.float64).eps * max(1.0, abs(lower), abs(upper))
        if speed < lower - tolerance or speed > upper + tolerance:
            raise ValueError(
                f"Speed {speed} is outside calibrated range "
                f"[{lower}, {upper}]."
            )
        speed = float(np.clip(speed, lower, upper))

        def interpolate(values: np.ndarray) -> float:
            return float(np.interp(speed, self.speeds_m_s, values))

        return BaselineAtSpeed(
            activation_mean=interpolate(self.activation_mean),
            activation_std=interpolate(self.activation_std),
            human_torque_mean=interpolate(self.human_torque_mean),
            human_torque_std=interpolate(self.human_torque_std),
            gross_median=interpolate(self.gross_median),
            gross_scale=interpolate(self.gross_scale),
            speed_free_error_m_s=interpolate(self.speed_free_error_m_s),
            speed_transition_m_s=interpolate(self.speed_transition_m_s),
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
    def load(cls, path: str | Path) -> "MyoAssistBaseline":
        source = Path(path).expanduser().resolve(strict=True)
        value = json.loads(source.read_text(encoding="utf-8"))
        return cls(**value)


def validate_calibrated_speed_range(
    baseline: MyoAssistBaseline,
    *,
    minimum_m_s: float,
    maximum_m_s: float,
    verified_speed_m_s: np.ndarray,
) -> tuple[float, float]:
    """Reject runtime speeds outside the baseline/TCN calibrated intersection."""

    minimum = float(minimum_m_s)
    maximum = float(maximum_m_s)
    if (
        not np.isfinite([minimum, maximum]).all()
        or not 0.0 < minimum <= maximum
    ):
        raise ValueError("Speed bounds must be finite and satisfy 0 < min <= max.")
    verified = np.asarray(verified_speed_m_s, dtype=np.float64)
    if (
        verified.ndim != 1
        or verified.size < 1
        or not np.all(np.isfinite(verified))
    ):
        raise ValueError("TCN calibration has no valid verified speed range.")
    lower = max(float(baseline.speeds_m_s[0]), float(np.min(verified)))
    upper = min(float(baseline.speeds_m_s[-1]), float(np.max(verified)))
    tolerance = 1.0e-9
    if lower > upper or minimum < lower - tolerance or maximum > upper + tolerance:
        raise ValueError(
            f"Configured speed range [{minimum}, {maximum}] is outside "
            f"the baseline/TCN calibrated intersection [{lower}, {upper}]."
        )
    return lower, upper


def fit_baseline(
    *,
    speed_m_s: np.ndarray,
    activation_cost: np.ndarray,
    human_joint_torque_nm: np.ndarray,
    gross_joint_load_nm: np.ndarray,
    forward_speed_filtered_m_s: np.ndarray,
    pelvis_height_m: np.ndarray,
    pelvis_pitch_rad: np.ndarray,
    joint_q_rad: np.ndarray,
    joint_lower_rad: np.ndarray,
    joint_upper_rad: np.ndarray,
    metadata: dict[str, Any],
) -> MyoAssistBaseline:
    """Fit only zero-assist training rollouts; callers own the split."""

    speed = _vector(speed_m_s, "speed_m_s")
    count = len(speed)
    activation = _vector(activation_cost, "activation_cost", count)
    human_torque = _matrix(
        human_joint_torque_nm,
        "human_joint_torque_nm",
        count,
        4,
    )
    gross = _matrix(gross_joint_load_nm, "gross_joint_load_nm", count, 4)
    forward = _vector(
        forward_speed_filtered_m_s,
        "forward_speed_filtered_m_s",
        count,
    )
    height = _vector(pelvis_height_m, "pelvis_height_m", count)
    pitch = _vector(pelvis_pitch_rad, "pelvis_pitch_rad", count)
    joint_q = _matrix(joint_q_rad, "joint_q_rad", count, 4)
    if np.any(activation < 0.0) or np.any(gross < 0.0):
        raise ValueError("Activation and gross load costs must be non-negative.")

    human_scale = np.maximum(np.median(np.abs(human_torque), axis=0), 1.0)
    gross_joint_scale = np.maximum(np.median(gross, axis=0), 1.0)
    human_cost = np.mean(np.square(human_torque / human_scale), axis=1)
    gross_cost = np.mean(gross / gross_joint_scale, axis=1)
    bins = np.unique(speed)
    activation_mean: list[float] = []
    activation_std: list[float] = []
    human_mean: list[float] = []
    human_std: list[float] = []
    gross_median: list[float] = []
    gross_scale: list[float] = []
    speed_free_error: list[float] = []
    speed_transition: list[float] = []

    for value in bins:
        mask = np.isclose(speed, value, rtol=0.0, atol=1.0e-9)
        if np.count_nonzero(mask) < 2:
            raise ValueError(f"Speed bin {value} needs at least two frames.")
        activation_values = activation[mask]
        human_values = human_cost[mask]
        gross_values = gross_cost[mask]
        speed_error_values = np.abs(forward[mask] - speed[mask])
        activation_center = float(np.mean(activation_values))
        human_center = float(np.mean(human_values))
        gross_center = float(np.median(gross_values))
        activation_mean.append(activation_center)
        activation_std.append(
            max(float(np.std(activation_values)), 0.05 * activation_center, EPSILON)
        )
        human_mean.append(human_center)
        human_std.append(
            max(float(np.std(human_values)), 0.05 * human_center, EPSILON)
        )
        gross_median.append(gross_center)
        gross_scale.append(
            max(
                float(np.median(np.abs(gross_values - gross_center))),
                0.05 * gross_center,
                EPSILON,
            )
        )
        speed_free_error.append(
            float(np.percentile(speed_error_values, 95.0))
        )
        speed_transition.append(max(float(np.std(speed_error_values)), 0.1))

    _vector(joint_lower_rad, "joint_lower_rad", 4)
    _vector(joint_upper_rad, "joint_upper_rad", 4)
    observed_lower = np.percentile(joint_q, 0.1, axis=0) - 0.05
    observed_upper = np.percentile(joint_q, 99.9, axis=0) + 0.05
    observed_range = observed_upper - observed_lower
    return MyoAssistBaseline(
        speeds_m_s=bins,
        activation_mean=np.asarray(activation_mean),
        activation_std=np.asarray(activation_std),
        human_torque_mean=np.asarray(human_mean),
        human_torque_std=np.asarray(human_std),
        gross_median=np.asarray(gross_median),
        gross_scale=np.asarray(gross_scale),
        human_joint_scale_nm=human_scale,
        gross_joint_scale_nm=gross_joint_scale,
        speed_window_steps=SPEED_WINDOW_STEPS,
        speed_free_error_m_s=np.asarray(speed_free_error),
        speed_transition_m_s=np.asarray(speed_transition),
        minimum_pelvis_height_m=float(np.percentile(height, 1.0) - 0.02),
        pelvis_height_transition_m=0.05,
        pelvis_pitch_free_rad=float(np.percentile(np.abs(pitch), 99.0) + 0.02),
        pelvis_pitch_transition_rad=np.deg2rad(10.0),
        joint_lower_rad=observed_lower,
        joint_upper_rad=observed_upper,
        joint_limit_margin_rad=np.zeros(4, dtype=np.float64),
        joint_limit_transition_rad=np.maximum(0.1 * observed_range, 0.05),
        metadata=dict(metadata),
    )


def _vector(value: np.ndarray, name: str, size: int | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 1 or (size is not None and len(array) != size):
        raise ValueError(f"{name} must have shape ({size or 'sample'},).")
    if len(array) < 1 or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite and non-empty.")
    return array.copy()


def _matrix(
    value: np.ndarray,
    name: str,
    rows: int,
    columns: int,
) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (rows, columns) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must have shape ({rows}, {columns}) and be finite.")
    return array.copy()


def _readonly(value: np.ndarray) -> np.ndarray:
    result = value.copy()
    result.flags.writeable = False
    return result


__all__ = [
    "BASELINE_SCHEMA",
    "SPEED_WINDOW_STEPS",
    "BaselineAtSpeed",
    "ForwardSpeedWindow",
    "MyoAssistBaseline",
    "fit_baseline",
    "validate_calibrated_speed_range",
]
