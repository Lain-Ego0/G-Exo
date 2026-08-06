"""Backend-neutral G-Exo deployment observation contracts."""

from __future__ import annotations

from collections import deque

import numpy as np


JOINT_COUNT = 4
JOINT_ORDER = (
    "left_hip",
    "left_knee",
    "right_hip",
    "right_knee",
)
IMU_COUNT = 4
IMU_AXIS_COUNT = 3

RUNTIME_SENSOR_DIM = 32
ACTION_DIM = 4
ACTOR_FRAME_DIM = 36
ACTOR_HISTORY_LENGTH = 4
ACTOR_HISTORY_DIM = 144
TCN_HISTORY_LENGTH = 50
TCN_FEATURE_DIM = 16
ACTOR_OBSERVATION_DIM = 160

RUNTIME_SENSOR_PROTOCOL = "gexo_sensor32_runtime_v1"
TCN_SENSOR_PROTOCOL = "phase12_tcn32_interleaved_v1"
ACTOR_OBSERVATION_PROTOCOL = "gexo_actor160_explicit_tcn_v1"
RESET_PROTOCOL = "gexo_zero_assist_preroll150_v1"
RESET_WARMUP_STEPS = 150

GRAVITY_M_S2 = 9.80665
DEFAULT_ACTOR_FRAME_SCALE = np.asarray(
    [np.pi] * 4
    + [20.0] * 4
    + [20.0] * 12
    + [4.0 * GRAVITY_M_S2] * 12
    + [1.0] * 4,
    dtype=np.float32,
)


def build_actor_frame(
    runtime_sensor32: np.ndarray,
    previous_applied_action: np.ndarray,
) -> np.ndarray:
    """Build one raw 36-D frame without maintaining temporal state."""

    sensor = _finite_vector(
        runtime_sensor32,
        "runtime_sensor32",
        RUNTIME_SENSOR_DIM,
    )
    previous_action = _finite_vector(
        previous_applied_action,
        "previous_applied_action",
        ACTION_DIM,
    )
    return np.concatenate((sensor, previous_action)).astype(np.float32)


def runtime32_to_phase12_interleaved(
    runtime_sensor32: np.ndarray,
) -> np.ndarray:
    """Convert runtime IMU banks to the Phase 1/2 TCN channel order."""

    frame = _finite_vector(
        runtime_sensor32,
        "runtime_sensor32",
        RUNTIME_SENSOR_DIM,
    )
    gyro = frame[8:20].reshape(IMU_COUNT, IMU_AXIS_COUNT)
    specific_force = frame[20:32].reshape(
        IMU_COUNT,
        IMU_AXIS_COUNT,
    )
    interleaved_imu = np.concatenate(
        (gyro, specific_force),
        axis=1,
    ).reshape(-1)
    return np.concatenate((frame[:8], interleaved_imu)).astype(np.float32)


def build_tcn_delta16(
    joint_prediction: np.ndarray,
    current_joint_position: np.ndarray,
    current_joint_velocity: np.ndarray,
) -> np.ndarray:
    """Build q/dq deltas for the +5 horizon followed by the +10 horizon."""

    prediction = np.asarray(joint_prediction, dtype=np.float32)
    if prediction.shape != (2, 8):
        raise ValueError(
            "joint_prediction must have shape (2, 8), got "
            f"{prediction.shape}."
        )
    if not np.all(np.isfinite(prediction)):
        raise FloatingPointError("joint_prediction contains NaN or Inf.")
    current_q = _finite_vector(
        current_joint_position,
        "current_joint_position",
        JOINT_COUNT,
    )
    current_dq = _finite_vector(
        current_joint_velocity,
        "current_joint_velocity",
        JOINT_COUNT,
    )
    deltas = []
    for future in prediction:
        deltas.extend((future[:4] - current_q, future[4:8] - current_dq))
    return np.concatenate(deltas).astype(np.float32)


def normalize_tcn_delta16(
    raw_delta16: np.ndarray,
    mean: np.ndarray,
    standard_deviation: np.ndarray,
    clip: float | np.ndarray,
) -> np.ndarray:
    """Apply frozen training statistics to explicit TCN predictions."""

    raw = _finite_vector(raw_delta16, "raw_delta16", TCN_FEATURE_DIM)
    feature_mean = _finite_vector(mean, "mean", TCN_FEATURE_DIM)
    feature_std = _positive_vector(
        standard_deviation,
        "standard_deviation",
        TCN_FEATURE_DIM,
    )
    clip_value = np.asarray(clip, dtype=np.float32)
    if clip_value.ndim == 0:
        clip_value = np.full(
            TCN_FEATURE_DIM,
            float(clip_value),
            dtype=np.float32,
        )
    if (
        clip_value.shape != (TCN_FEATURE_DIM,)
        or not np.all(np.isfinite(clip_value))
        or np.any(clip_value <= 0.0)
    ):
        raise ValueError("clip must be positive and scalar or shape (16,).")
    normalized = (raw - feature_mean) / feature_std
    return np.clip(normalized, -clip_value, clip_value).astype(np.float32)


class ActorObservationBuilder:
    """Maintain the four real frames that form a 160-D Actor input."""

    def __init__(
        self,
        *,
        frame_scale: np.ndarray = DEFAULT_ACTOR_FRAME_SCALE,
        clip: float = 5.0,
    ) -> None:
        self.frame_scale = _positive_vector(
            frame_scale,
            "frame_scale",
            ACTOR_FRAME_DIM,
        )
        if not np.isfinite(clip) or clip <= 0.0:
            raise ValueError("clip must be positive and finite.")
        self.clip = float(clip)
        self._history: deque[np.ndarray] = deque(
            maxlen=ACTOR_HISTORY_LENGTH
        )

    @property
    def ready(self) -> bool:
        return len(self._history) == ACTOR_HISTORY_LENGTH

    @property
    def history_size(self) -> int:
        return len(self._history)

    def reset(self) -> None:
        """Clear history; callers must refill it with real simulation frames."""

        self._history.clear()

    def append(
        self,
        runtime_sensor32: np.ndarray,
        previous_applied_action: np.ndarray,
    ) -> np.ndarray:
        """Normalize and append one real frame, returning a defensive copy."""

        frame = build_actor_frame(
            runtime_sensor32,
            previous_applied_action,
        )
        normalized = np.clip(
            frame / self.frame_scale,
            -self.clip,
            self.clip,
        ).astype(np.float32)
        self._history.append(normalized)
        return normalized.copy()

    def history144(self) -> np.ndarray:
        if not self.ready:
            raise RuntimeError(
                "Actor history requires four real frames; "
                f"only {len(self._history)} are available."
            )
        history = np.stack(tuple(self._history), axis=0).reshape(-1)
        if history.shape != (ACTOR_HISTORY_DIM,):
            raise RuntimeError("Unexpected Actor history shape.")
        return history.astype(np.float32, copy=False)

    def build(self, tcn_feature16: np.ndarray) -> np.ndarray:
        """Concatenate the 144-D history and normalized 16-D TCN feature."""

        tcn_feature = _finite_vector(
            tcn_feature16,
            "tcn_feature16",
            TCN_FEATURE_DIM,
        )
        observation = np.concatenate(
            (self.history144(), tcn_feature)
        ).astype(np.float32)
        if observation.shape != (ACTOR_OBSERVATION_DIM,):
            raise RuntimeError("Unexpected Actor observation shape.")
        return observation


def _finite_vector(value: np.ndarray, name: str, size: int) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},), got {array.shape}.")
    if not np.all(np.isfinite(array)):
        raise FloatingPointError(f"{name} contains NaN or Inf.")
    return array.copy()


def _positive_vector(value: np.ndarray, name: str, size: int) -> np.ndarray:
    array = _finite_vector(value, name, size)
    if np.any(array <= 0.0):
        raise ValueError(f"{name} must be strictly positive.")
    return array


__all__ = [
    "ACTION_DIM",
    "ACTOR_FRAME_DIM",
    "ACTOR_HISTORY_DIM",
    "ACTOR_HISTORY_LENGTH",
    "ACTOR_OBSERVATION_DIM",
    "ACTOR_OBSERVATION_PROTOCOL",
    "ActorObservationBuilder",
    "DEFAULT_ACTOR_FRAME_SCALE",
    "JOINT_ORDER",
    "RESET_PROTOCOL",
    "RESET_WARMUP_STEPS",
    "RUNTIME_SENSOR_DIM",
    "RUNTIME_SENSOR_PROTOCOL",
    "TCN_FEATURE_DIM",
    "TCN_HISTORY_LENGTH",
    "TCN_SENSOR_PROTOCOL",
    "build_actor_frame",
    "build_tcn_delta16",
    "normalize_tcn_delta16",
    "runtime32_to_phase12_interleaved",
]
