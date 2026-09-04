"""Decode public TCN features and apply low-gain joint impedance control."""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

import numpy as np

from RL.env.actor_observation import (
    ACTOR_FRAME_DIM,
    ACTOR_HISTORY_DIM,
    ACTOR_OBSERVATION_DIM,
    DEFAULT_ACTOR_FRAME_SCALE,
    RESET_PROTOCOL,
    RESET_WARMUP_STEPS,
    TCN_FEATURE_DIM,
)


JOINT_COUNT = 4
DEFAULT_ACTOR_FRAME_CLIP = 5.0
CALIBRATION_PROTOCOL = "gexo_myoassist_phase12_tcn_calibration_v1"
CALIBRATION_SCHEMA_VERSION = 1
CALIBRATION_HORIZONS = (5, 10)
RESET_STATE_CONTRACT = "canonical_full_state_v1"
DEFAULT_OOD_SOFT_RATIO = 0.6
DEFAULT_POSITION_DELTA_LIMIT_RAD = 1.0
DEFAULT_VELOCITY_DELTA_LIMIT_RAD_S = 10.0


@dataclass(frozen=True)
class TCNImpedanceCommand:
    """One controller result in physical and normalized units."""

    action: np.ndarray
    target_torque_nm: np.ndarray
    current_q_rad: np.ndarray
    current_dq_rad_s: np.ndarray
    predicted_q_rad: np.ndarray
    predicted_dq_rad_s: np.ndarray
    reference_q_rad: np.ndarray
    reference_dq_rad_s: np.ndarray
    delta_q_rad: np.ndarray
    delta_dq_rad_s: np.ndarray
    control_delta_q_rad: np.ndarray
    control_delta_dq_rad_s: np.ndarray
    confidence: float
    feature_ood_ratio: float
    sensor_ood_ratio: float
    feature_saturated: bool
    sensor_saturated: bool
    error_limited: bool
    action_saturated: bool


class TCNImpedanceController:
    """Turn the explicit TCN delta in observation160 into four actions.

    The final 16 observation channels follow
    ``gexo_actor160_explicit_tcn_v1``. They contain normalized and clipped
    q/dq deltas for the +5 and +10 control-step horizons. The affine
    normalization is reversible while the feature is inside its clip range.
    Assistance fades out before a selected feature or public sensor channel
    is clipped, because values close to the calibration boundary are less
    trustworthy. Unsaturated TCN deltas remain available for prediction
    auditing; a saturated prediction is censored because clipping has already
    destroyed its original magnitude. Only deltas entering the impedance law
    receive physical safety caps.
    """

    def __init__(
        self,
        *,
        feature_mean: np.ndarray,
        feature_std: np.ndarray,
        feature_clip: float | np.ndarray,
        horizon_steps: tuple[int, ...],
        selected_horizon_steps: int,
        kp_nm_per_rad: float | np.ndarray,
        kd_nm_s_per_rad: float | np.ndarray,
        action_scale_nm: float | np.ndarray,
        prediction_fraction: float | None = None,
        actor_frame_clip: float = DEFAULT_ACTOR_FRAME_CLIP,
        disable_on_saturation: bool = True,
        ood_soft_ratio: float = DEFAULT_OOD_SOFT_RATIO,
        position_delta_limit_rad: float | np.ndarray = (
            DEFAULT_POSITION_DELTA_LIMIT_RAD
        ),
        velocity_delta_limit_rad_s: float | np.ndarray = (
            DEFAULT_VELOCITY_DELTA_LIMIT_RAD_S
        ),
    ) -> None:
        self.feature_mean = _vector(
            feature_mean,
            TCN_FEATURE_DIM,
            "feature_mean",
        )
        self.feature_std = _positive_vector(
            feature_std,
            TCN_FEATURE_DIM,
            "feature_std",
        )
        self.feature_clip = _positive_clip(feature_clip)
        self.horizon_steps = tuple(int(value) for value in horizon_steps)
        if self.horizon_steps != CALIBRATION_HORIZONS:
            raise ValueError(
                f"horizon_steps must be exactly {CALIBRATION_HORIZONS}."
            )
        if selected_horizon_steps not in self.horizon_steps:
            raise ValueError(
                "selected_horizon_steps must occur in horizon_steps."
            )
        self.selected_horizon_steps = int(selected_horizon_steps)
        self.horizon_index = self.horizon_steps.index(
            self.selected_horizon_steps
        )
        self.kp_nm_per_rad = _nonnegative_joint_vector(
            kp_nm_per_rad,
            "kp_nm_per_rad",
        )
        self.kd_nm_s_per_rad = _nonnegative_joint_vector(
            kd_nm_s_per_rad,
            "kd_nm_s_per_rad",
        )
        self.action_scale_nm = _positive_joint_vector(
            action_scale_nm,
            "action_scale_nm",
        )
        if prediction_fraction is None:
            prediction_fraction = 1.0 / self.selected_horizon_steps
        if not np.isfinite(prediction_fraction) or not (
            0.0 < prediction_fraction <= 1.0
        ):
            raise ValueError("prediction_fraction must be in (0, 1].")
        if not np.isfinite(actor_frame_clip) or actor_frame_clip <= 0.0:
            raise ValueError("actor_frame_clip must be positive and finite.")
        if not np.isfinite(ood_soft_ratio) or not 0.0 <= ood_soft_ratio < 1.0:
            raise ValueError("ood_soft_ratio must be in [0, 1).")
        self.prediction_fraction = float(prediction_fraction)
        self.actor_frame_clip = float(actor_frame_clip)
        self.disable_on_saturation = bool(disable_on_saturation)
        self.ood_soft_ratio = float(ood_soft_ratio)
        self.position_delta_limit_rad = _positive_joint_vector(
            position_delta_limit_rad,
            "position_delta_limit_rad",
        )
        self.velocity_delta_limit_rad_s = _positive_joint_vector(
            velocity_delta_limit_rad_s,
            "velocity_delta_limit_rad_s",
        )

    @classmethod
    def from_calibration(
        cls,
        calibration_path: str | Path,
        *,
        selected_horizon_steps: int = 5,
        kp_nm_per_rad: float | np.ndarray = 4.0,
        kd_nm_s_per_rad: float | np.ndarray = 0.2,
        action_scale_nm: float | np.ndarray = 2.0,
        prediction_fraction: float | None = None,
        disable_on_saturation: bool = True,
        ood_soft_ratio: float = DEFAULT_OOD_SOFT_RATIO,
        position_delta_limit_rad: float | np.ndarray = (
            DEFAULT_POSITION_DELTA_LIMIT_RAD
        ),
        velocity_delta_limit_rad_s: float | np.ndarray = (
            DEFAULT_VELOCITY_DELTA_LIMIT_RAD_S
        ),
        expected_tcn_checkpoint_sha256: str | None = None,
    ) -> "TCNImpedanceController":
        path = Path(calibration_path).expanduser().resolve(strict=True)
        calibration = json.loads(path.read_text(encoding="utf-8"))
        _validate_calibration_protocol(
            calibration,
            expected_tcn_checkpoint_sha256=expected_tcn_checkpoint_sha256,
        )
        normalization = calibration.get("actor_feature_normalization")
        if not isinstance(normalization, dict):
            raise ValueError(
                "Calibration lacks actor_feature_normalization."
            )
        return cls(
            feature_mean=normalization.get("mean"),
            feature_std=normalization.get("std"),
            feature_clip=normalization.get("clip"),
            horizon_steps=tuple(normalization.get("horizon_steps", ())),
            selected_horizon_steps=selected_horizon_steps,
            kp_nm_per_rad=kp_nm_per_rad,
            kd_nm_s_per_rad=kd_nm_s_per_rad,
            action_scale_nm=action_scale_nm,
            prediction_fraction=prediction_fraction,
            disable_on_saturation=disable_on_saturation,
            ood_soft_ratio=ood_soft_ratio,
            position_delta_limit_rad=position_delta_limit_rad,
            velocity_delta_limit_rad_s=velocity_delta_limit_rad_s,
        )

    def compute(self, observation160: np.ndarray) -> TCNImpedanceCommand:
        """Compute one action from a public 160-D environment observation."""

        observation = _vector(
            observation160,
            ACTOR_OBSERVATION_DIM,
            "observation160",
        )

        # The last 36-D history frame contains current q4, dq4, IMUs, action4.
        frame_start = ACTOR_HISTORY_DIM - ACTOR_FRAME_DIM
        normalized_frame = observation[frame_start:ACTOR_HISTORY_DIM]
        if np.any(
            np.abs(normalized_frame) > self.actor_frame_clip + 1.0e-6
        ):
            raise ValueError("Actor history exceeds its declared clip range.")
        physical_frame = normalized_frame * DEFAULT_ACTOR_FRAME_SCALE
        current_q = physical_frame[:JOINT_COUNT]
        current_dq = physical_frame[JOINT_COUNT : 2 * JOINT_COUNT]
        # All 32 public sensor channels participate in the safety gate. The
        # final four action-history channels are excluded.
        normalized_sensor = normalized_frame[: ACTOR_FRAME_DIM - JOINT_COUNT]
        sensor_saturated = bool(
            np.any(
                np.abs(normalized_sensor)
                >= self.actor_frame_clip - 1.0e-6
            )
        )
        sensor_ood_ratio = float(
            np.max(np.abs(normalized_sensor)) / self.actor_frame_clip
        )

        normalized_delta = observation[-TCN_FEATURE_DIM:]
        if np.any(
            np.abs(normalized_delta) > self.feature_clip + 1.0e-6
        ):
            raise ValueError("TCN feature exceeds its declared clip range.")
        raw_delta = (
            normalized_delta * self.feature_std + self.feature_mean
        ).astype(np.float32)

        start = self.horizon_index * 2 * JOINT_COUNT
        stop = start + 2 * JOINT_COUNT
        selected_normalized = normalized_delta[start:stop]
        selected_clip = self.feature_clip[start:stop]
        feature_saturated = bool(
            np.any(
                np.abs(selected_normalized) >= selected_clip - 1.0e-6
            )
        )
        feature_ood_ratio = float(
            np.max(np.abs(selected_normalized) / selected_clip)
        )
        delta_q = raw_delta[start : start + JOINT_COUNT]
        delta_dq = raw_delta[start + JOINT_COUNT : stop]

        control_delta_q = np.clip(
            delta_q,
            -self.position_delta_limit_rad,
            self.position_delta_limit_rad,
        )
        control_delta_dq = np.clip(
            delta_dq,
            -self.velocity_delta_limit_rad_s,
            self.velocity_delta_limit_rad_s,
        )
        error_limited = bool(
            np.any(control_delta_q != delta_q)
            or np.any(control_delta_dq != delta_dq)
        )

        prediction_fraction = self.prediction_fraction
        reference_q = current_q + prediction_fraction * control_delta_q
        reference_dq = current_dq + prediction_fraction * control_delta_dq
        predicted_q = current_q + delta_q
        predicted_dq = current_dq + delta_dq

        confidence = 1.0
        if self.disable_on_saturation:
            confidence = min(
                _soft_ood_confidence(
                    feature_ood_ratio,
                    self.ood_soft_ratio,
                ),
                _soft_ood_confidence(
                    sensor_ood_ratio,
                    self.ood_soft_ratio,
                ),
            )
        target_torque = confidence * (
            self.kp_nm_per_rad * (reference_q - current_q)
            + self.kd_nm_s_per_rad * (reference_dq - current_dq)
        )
        unbounded_action = target_torque / self.action_scale_nm
        action_saturated = bool(
            np.any(np.abs(unbounded_action) >= 1.0 - 1.0e-6)
        )
        action = np.clip(unbounded_action, -1.0, 1.0).astype(np.float32)

        return TCNImpedanceCommand(
            action=action,
            target_torque_nm=target_torque.astype(np.float32),
            current_q_rad=current_q.astype(np.float32),
            current_dq_rad_s=current_dq.astype(np.float32),
            predicted_q_rad=predicted_q.astype(np.float32),
            predicted_dq_rad_s=predicted_dq.astype(np.float32),
            reference_q_rad=reference_q.astype(np.float32),
            reference_dq_rad_s=reference_dq.astype(np.float32),
            delta_q_rad=delta_q.astype(np.float32),
            delta_dq_rad_s=delta_dq.astype(np.float32),
            control_delta_q_rad=control_delta_q.astype(np.float32),
            control_delta_dq_rad_s=control_delta_dq.astype(np.float32),
            confidence=confidence,
            feature_ood_ratio=feature_ood_ratio,
            sensor_ood_ratio=sensor_ood_ratio,
            feature_saturated=feature_saturated,
            sensor_saturated=sensor_saturated,
            error_limited=error_limited,
            action_saturated=action_saturated,
        )

    def metadata(self) -> dict[str, Any]:
        return {
            "horizon_steps": list(self.horizon_steps),
            "selected_horizon_steps": self.selected_horizon_steps,
            "prediction_fraction": self.prediction_fraction,
            "kp_nm_per_rad": self.kp_nm_per_rad.tolist(),
            "kd_nm_s_per_rad": self.kd_nm_s_per_rad.tolist(),
            "action_scale_nm": self.action_scale_nm.tolist(),
            "disable_on_saturation": self.disable_on_saturation,
            "ood_soft_ratio": self.ood_soft_ratio,
            "position_delta_limit_rad": (
                self.position_delta_limit_rad.tolist()
            ),
            "velocity_delta_limit_rad_s": (
                self.velocity_delta_limit_rad_s.tolist()
            ),
        }


def _validate_calibration_protocol(
    calibration: dict[str, Any],
    *,
    expected_tcn_checkpoint_sha256: str | None,
) -> None:
    if calibration.get("protocol") != CALIBRATION_PROTOCOL:
        raise ValueError("Unsupported TCN impedance calibration protocol.")
    if calibration.get("schema_version") != CALIBRATION_SCHEMA_VERSION:
        raise ValueError("Unsupported TCN impedance calibration schema.")
    fit = calibration.get("fit")
    if not isinstance(fit, dict):
        raise ValueError("Calibration lacks fit metadata.")
    if (
        fit.get("warmup_protocol") != RESET_PROTOCOL
        or fit.get("warmup_steps") != RESET_WARMUP_STEPS
    ):
        raise ValueError("Calibration reset/warmup protocol is incompatible.")
    if fit.get("reset_state_contract") != RESET_STATE_CONTRACT:
        raise ValueError("Calibration reset-state contract is incompatible.")
    if calibration.get("domain_randomization_enabled") is not False:
        raise ValueError("Calibration must disable domain randomization.")
    if expected_tcn_checkpoint_sha256 is not None:
        actual = calibration.get("tcn_checkpoint_sha256")
        if actual != expected_tcn_checkpoint_sha256:
            raise ValueError("Calibration TCN checkpoint hash mismatch.")


def _soft_ood_confidence(ratio: float, soft_ratio: float) -> float:
    """Return one below the soft boundary and fade linearly to zero."""

    if ratio <= soft_ratio:
        return 1.0
    if ratio >= 1.0:
        return 0.0
    return float((1.0 - ratio) / (1.0 - soft_ratio))


def _vector(value: Any, size: int, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.shape != (size,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite with shape ({size},).")
    return array.copy()


def _positive_vector(value: Any, size: int, name: str) -> np.ndarray:
    array = _vector(value, size, name)
    if np.any(array <= 0.0):
        raise ValueError(f"{name} must be strictly positive.")
    return array


def _joint_vector(value: Any, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim == 0:
        array = np.full(JOINT_COUNT, float(array), dtype=np.float32)
    if array.shape != (JOINT_COUNT,) or not np.all(np.isfinite(array)):
        raise ValueError(
            f"{name} must be finite and scalar or shape ({JOINT_COUNT},)."
        )
    return array


def _nonnegative_joint_vector(value: Any, name: str) -> np.ndarray:
    array = _joint_vector(value, name)
    if np.any(array < 0.0):
        raise ValueError(f"{name} must be non-negative.")
    return array


def _positive_joint_vector(value: Any, name: str) -> np.ndarray:
    array = _joint_vector(value, name)
    if np.any(array <= 0.0):
        raise ValueError(f"{name} must be strictly positive.")
    return array


def _positive_clip(value: Any) -> np.ndarray:
    array = np.asarray(value, dtype=np.float32)
    if array.ndim == 0:
        array = np.full(TCN_FEATURE_DIM, float(array), dtype=np.float32)
    if (
        array.shape != (TCN_FEATURE_DIM,)
        or not np.all(np.isfinite(array))
        or np.any(array <= 0.0)
    ):
        raise ValueError(
            "feature_clip must be positive and scalar or shape (16,)."
        )
    return array


__all__ = ["TCNImpedanceCommand", "TCNImpedanceController"]
