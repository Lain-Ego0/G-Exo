"""Adapt deployable Kinesis sensor frames to the frozen motion TCN.

The PPO environment stores sensors as motor state, all gyroscopes, then all
accelerometers.  The Phase 1/2 dataset instead interleaves gyro and
accelerometer channels for each limb segment.  This module owns that boundary,
the 50-frame history, checkpoint normalization, and inverse target scaling.
"""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import json
from pathlib import Path

import numpy as np
import torch

from RL.env.sensors import SENSOR_DIM
from RL.runners.predictors.tcn import MotionTCN


IMU_COUNT = 4
AXES_PER_IMU = 3
TCN_INPUT_DIM = 32
TCN_LATENT_DIM = 64
DEPLOYMENT_MOTION_DIM = 8
TCN_DEPLOYMENT_HORIZON_STEPS = (5, 10)
TCN_DEPLOYMENT_FEATURE_DIM = (
    len(TCN_DEPLOYMENT_HORIZON_STEPS) * DEPLOYMENT_MOTION_DIM
)


@dataclass(frozen=True)
class TCNPrediction:
    """One frozen-TCN inference result in physical target units."""

    prediction: np.ndarray
    joint_prediction: np.ndarray
    latent: np.ndarray
    normalized_prediction: np.ndarray

    @property
    def actor_features(self) -> np.ndarray:
        """Return explicit two-horizon motion predictions, excluding moments."""

        return self.joint_prediction.reshape(-1).astype(
            np.float32,
            copy=False,
        )


class TCNInputAdapter:
    """Run a Phase 1/2 TCN from causal deployable sensor history.

    Calibration defaults to identity so that data-flow tests can run now.  It
    must be replaced by measured encoder zero/sign and IMU mounting rotations
    before predictions are used by an Actor.
    """

    def __init__(
        self,
        checkpoint: str | Path,
        *,
        device: str = "cpu",
        calibration: str | Path | None = None,
        motor_position_scale: np.ndarray | None = None,
        motor_position_offset: np.ndarray | None = None,
        motor_velocity_scale: np.ndarray | None = None,
        imu_rotation: np.ndarray | None = None,
        target_position_scale: np.ndarray | None = None,
        target_position_offset: np.ndarray | None = None,
        target_velocity_scale: np.ndarray | None = None,
        ignore_actor_feature_normalization: bool = False,
    ) -> None:
        self.checkpoint_path = Path(checkpoint).expanduser().resolve()
        checkpoint_data = self._load_checkpoint(
            self.checkpoint_path,
            device,
        )

        self.device = torch.device(device)
        self.history_length = int(checkpoint_data["history"])
        self.horizons = tuple(
            int(value) for value in checkpoint_data["horizons"]
        )
        self.input_mean = self._vector(
            checkpoint_data["statistics"]["input_mean"],
            "input_mean",
            TCN_INPUT_DIM,
        )
        self.input_std = self._positive_vector(
            checkpoint_data["statistics"]["input_std"],
            "input_std",
            TCN_INPUT_DIM,
        )
        self.target_mean = self._vector(
            checkpoint_data["statistics"]["target_mean"],
            "target_mean",
            int(checkpoint_data["target_dim"]),
        )
        self.target_std = self._positive_vector(
            checkpoint_data["statistics"]["target_std"],
            "target_std",
            int(checkpoint_data["target_dim"]),
        )

        calibration_data = self._load_calibration(calibration)
        input_calibration = calibration_data.get("input", {})
        output_calibration = calibration_data.get("output", {})
        feature_normalization = (
            None
            if ignore_actor_feature_normalization
            else calibration_data.get("actor_feature_normalization")
        )

        self.calibration_path = (
            None
            if calibration is None
            else Path(calibration).expanduser().resolve()
        )
        self.motor_position_scale = self._calibration_vector(
            motor_position_scale
            if motor_position_scale is not None
            else input_calibration.get("motor_position_scale"),
            "motor_position_scale",
            default=1.0,
        )
        self.motor_position_offset = self._calibration_vector(
            motor_position_offset
            if motor_position_offset is not None
            else input_calibration.get("motor_position_offset"),
            "motor_position_offset",
            default=0.0,
        )
        self.motor_velocity_scale = self._calibration_vector(
            motor_velocity_scale
            if motor_velocity_scale is not None
            else input_calibration.get("motor_velocity_scale"),
            "motor_velocity_scale",
            default=1.0,
        )
        self.imu_rotation = self._imu_rotation(
            imu_rotation
            if imu_rotation is not None
            else input_calibration.get("imu_rotation")
        )
        self.target_position_scale = self._calibration_vector(
            target_position_scale
            if target_position_scale is not None
            else output_calibration.get("target_position_scale"),
            "target_position_scale",
            default=1.0,
        )
        self.target_position_offset = self._calibration_vector(
            target_position_offset
            if target_position_offset is not None
            else output_calibration.get("target_position_offset"),
            "target_position_offset",
            default=0.0,
        )
        self.target_velocity_scale = self._calibration_vector(
            target_velocity_scale
            if target_velocity_scale is not None
            else output_calibration.get("target_velocity_scale"),
            "target_velocity_scale",
            default=1.0,
        )
        (
            self.actor_feature_horizon_steps,
            self.actor_feature_mean,
            self.actor_feature_std,
            self.actor_feature_clip,
        ) = self._actor_feature_normalization(feature_normalization)
        missing_actor_horizons = set(
            self.actor_feature_horizon_steps
        ) - set(self.horizons)
        if self.has_actor_feature_normalization and missing_actor_horizons:
            raise ValueError(
                "Actor feature horizons are not present in the TCN checkpoint: "
                f"{sorted(missing_actor_horizons)}."
            )

        self.model = MotionTCN(
            input_dim=int(checkpoint_data["input_dim"]),
            hidden_dim=int(checkpoint_data["hidden_dim"]),
            target_dim=int(checkpoint_data["target_dim"]),
            horizon_count=len(self.horizons),
            dropout=float(checkpoint_data["dropout"]),
            auxiliary_dim=int(checkpoint_data.get("auxiliary_dim", 0)),
        ).to(self.device)
        self.model.load_state_dict(checkpoint_data["model_state_dict"])
        self.model.eval()
        self.model.requires_grad_(False)

        self._history: deque[np.ndarray] = deque(
            maxlen=self.history_length
        )

    @property
    def ready(self) -> bool:
        return len(self._history) == self.history_length

    @property
    def history_size(self) -> int:
        return len(self._history)

    @property
    def latest_normalized_frame(self) -> np.ndarray:
        if not self._history:
            raise RuntimeError("TCN history is empty.")
        return self._history[-1].copy()

    def reset(self) -> None:
        self._history.clear()

    def append(self, sensor_frame: np.ndarray) -> None:
        """Calibrate, reorder, normalize, and append one raw 32-D frame."""

        tcn_frame = self.to_tcn_order(sensor_frame)
        normalized = (
            (tcn_frame - self.input_mean) / self.input_std
        ).astype(np.float32)

        if not np.all(np.isfinite(normalized)):
            raise FloatingPointError("Normalized TCN frame contains NaN or Inf.")
        self._history.append(normalized)

    def extend(self, sensor_history: np.ndarray) -> None:
        history = np.asarray(sensor_history, dtype=np.float32)
        if history.ndim != 2 or history.shape[1] != SENSOR_DIM:
            raise ValueError(
                "sensor_history must have shape [time, 32], got "
                f"{history.shape}."
            )
        for frame in history:
            self.append(frame)

    def to_tcn_order(self, sensor_frame: np.ndarray) -> np.ndarray:
        """Convert environment channel order to Phase 1/2 dataset order."""

        frame = self._vector(
            sensor_frame,
            "sensor_frame",
            SENSOR_DIM,
        )
        motor_q = (
            frame[:4] * self.motor_position_scale
            + self.motor_position_offset
        )
        motor_dq = frame[4:8] * self.motor_velocity_scale

        gyro = frame[8:20].reshape(IMU_COUNT, AXES_PER_IMU)
        specific_force = frame[20:32].reshape(
            IMU_COUNT,
            AXES_PER_IMU,
        )
        gyro = np.einsum("nij,nj->ni", self.imu_rotation, gyro)
        specific_force = np.einsum(
            "nij,nj->ni",
            self.imu_rotation,
            specific_force,
        )

        # Dataset order: thigh-L gyro/accel, shank-L gyro/accel, then right.
        interleaved_imu = np.concatenate(
            (gyro, specific_force),
            axis=1,
        ).reshape(-1)
        result = np.concatenate(
            (motor_q, motor_dq, interleaved_imu)
        ).astype(np.float32)

        if result.shape != (TCN_INPUT_DIM,):
            raise RuntimeError("Unexpected TCN frame shape.")
        return result

    def predict(self) -> TCNPrediction:
        """Return future targets and latent from the latest causal history."""

        if not self.ready:
            raise RuntimeError(
                f"TCN needs {self.history_length} frames, "
                f"but only {len(self._history)} are available."
            )

        history = np.stack(tuple(self._history), axis=0)
        inputs = torch.from_numpy(history.T.copy()).unsqueeze(0)
        inputs = inputs.to(self.device)

        with torch.inference_mode():
            latent = self.model.encode(inputs)
            normalized_prediction = self.model.prediction_head(latent)
            normalized_prediction = normalized_prediction.reshape(
                1,
                len(self.horizons),
                self.target_mean.size,
            )

        normalized_np = normalized_prediction[0].cpu().numpy()
        prediction = (
            normalized_np * self.target_std[None, :]
            + self.target_mean[None, :]
        )
        joint_prediction = np.concatenate(
            (
                prediction[:, :4] * self.target_position_scale
                + self.target_position_offset,
                prediction[:, 4:8] * self.target_velocity_scale,
            ),
            axis=1,
        )
        return TCNPrediction(
            prediction=prediction.astype(np.float32),
            joint_prediction=joint_prediction.astype(np.float32),
            latent=latent[0].cpu().numpy().astype(np.float32),
            normalized_prediction=normalized_np.astype(np.float32),
        )

    @property
    def has_actor_feature_normalization(self) -> bool:
        """Whether fixed deployment feature statistics were calibrated."""

        return (
            self.actor_feature_mean is not None
            and self.actor_feature_std is not None
        )

    def raw_deployment_features(
        self,
        prediction: TCNPrediction,
        current_joint_position: np.ndarray,
        current_joint_velocity: np.ndarray,
        *,
        horizon_steps: tuple[int, ...] | None = None,
    ) -> np.ndarray:
        """Return two-horizon future motion deltas before normalization."""

        selected_horizons = (
            self.actor_feature_horizon_steps
            if horizon_steps is None
            else tuple(int(value) for value in horizon_steps)
        )
        missing_horizons = set(selected_horizons) - set(self.horizons)
        if missing_horizons:
            raise ValueError(
                f"TCN has horizons {self.horizons}, not "
                f"{sorted(missing_horizons)}."
            )
        if len(selected_horizons) * DEPLOYMENT_MOTION_DIM != (
            TCN_DEPLOYMENT_FEATURE_DIM
        ):
            raise ValueError(
                "Actor deployment requires exactly two prediction horizons."
            )
        current_q = self._vector(
            current_joint_position,
            "current_joint_position",
            4,
        )
        current_dq = self._vector(
            current_joint_velocity,
            "current_joint_velocity",
            4,
        )
        deltas = []
        for horizon in selected_horizons:
            horizon_index = self.horizons.index(horizon)
            future = np.asarray(
                prediction.joint_prediction[horizon_index],
                dtype=np.float32,
            )
            if future.shape != (DEPLOYMENT_MOTION_DIM,):
                raise ValueError("TCN joint prediction must contain q and dq.")
            deltas.extend((future[:4] - current_q, future[4:8] - current_dq))
        raw = np.concatenate(deltas).astype(np.float32)
        if raw.shape != (TCN_DEPLOYMENT_FEATURE_DIM,):
            raise RuntimeError("Unexpected deployment TCN feature shape.")
        return raw

    def deployment_features(
        self,
        prediction: TCNPrediction,
        current_joint_position: np.ndarray,
        current_joint_velocity: np.ndarray,
    ) -> np.ndarray:
        """Return the fixed-normalized 16-D feature vector used by PPO."""

        if not self.has_actor_feature_normalization:
            path = self.calibration_path or "the calibration JSON"
            raise RuntimeError(
                f"{path} has no actor_feature_normalization. "
                "Fit fixed statistics before enabling TCN observations; "
                "online normalization is intentionally unsupported."
            )
        raw = self.raw_deployment_features(
            prediction,
            current_joint_position,
            current_joint_velocity,
        )
        normalized = (raw - self.actor_feature_mean) / self.actor_feature_std
        normalized = np.clip(
            normalized,
            -self.actor_feature_clip,
            self.actor_feature_clip,
        ).astype(np.float32)
        if not np.all(np.isfinite(normalized)):
            raise FloatingPointError("Deployment TCN features contain NaN or Inf.")
        return normalized

    @staticmethod
    def fit_actor_feature_normalization(
        raw_features: np.ndarray,
        *,
        horizon_steps: tuple[int, ...] = TCN_DEPLOYMENT_HORIZON_STEPS,
        clip: float = 5.0,
        minimum_std: float = 1.0e-4,
    ) -> dict[str, object]:
        """Fit reproducible statistics for storage in calibration JSON."""

        features = np.asarray(raw_features, dtype=np.float64)
        if (
            features.ndim != 2
            or features.shape[1] != TCN_DEPLOYMENT_FEATURE_DIM
            or features.shape[0] < 2
        ):
            raise ValueError(
                "raw_features must have shape "
                f"[sample, {TCN_DEPLOYMENT_FEATURE_DIM}] with at least two "
                f"samples, got {features.shape}."
            )
        if not np.all(np.isfinite(features)):
            raise FloatingPointError("raw_features contains NaN or Inf.")
        selected_horizons = tuple(int(value) for value in horizon_steps)
        if (
            len(selected_horizons) * DEPLOYMENT_MOTION_DIM
            != TCN_DEPLOYMENT_FEATURE_DIM
            or min(selected_horizons, default=0) < 1
            or clip <= 0.0
            or minimum_std <= 0.0
        ):
            raise ValueError("Normalization settings must be positive.")
        standard_deviation = np.maximum(
            np.std(features, axis=0),
            float(minimum_std),
        )
        return {
            "horizon_steps": list(selected_horizons),
            "mean": np.mean(features, axis=0).tolist(),
            "std": standard_deviation.tolist(),
            "clip": float(clip),
            "minimum_std": float(minimum_std),
            "samples": int(features.shape[0]),
        }

    @staticmethod
    def _load_calibration(calibration: str | Path | None) -> dict:
        if calibration is None:
            return {}
        path = Path(calibration).expanduser().resolve()
        if not path.is_file():
            raise FileNotFoundError(f"TCN calibration does not exist: {path}")
        value = json.loads(path.read_text(encoding="utf-8"))
        if int(value.get("schema_version", -1)) != 1:
            raise ValueError("Unsupported TCN calibration schema.")
        return value

    @classmethod
    def _actor_feature_normalization(
        cls,
        value: dict | None,
    ) -> tuple[
        tuple[int, ...],
        np.ndarray | None,
        np.ndarray | None,
        float,
    ]:
        """Load statistics and reject stale latent-based feature formats."""

        if value is None:
            return TCN_DEPLOYMENT_HORIZON_STEPS, None, None, 5.0
        if not isinstance(value, dict):
            raise ValueError("actor_feature_normalization must be an object.")
        raw_horizons = value.get(
            "horizon_steps",
            TCN_DEPLOYMENT_HORIZON_STEPS,
        )
        horizons = (
            (int(raw_horizons),)
            if isinstance(raw_horizons, (int, float))
            else tuple(int(item) for item in raw_horizons)
        )
        clip = float(value.get("clip", 5.0))
        if (
            len(horizons) * DEPLOYMENT_MOTION_DIM
            != TCN_DEPLOYMENT_FEATURE_DIM
            or min(horizons, default=0) < 1
            or clip <= 0.0
        ):
            raise ValueError(
                "Actor feature normalization is not the 16-D two-horizon "
                "format. Re-run RL.runners.fit_kinesis_tcn_feature_stats."
            )
        mean = cls._vector(
            value.get("mean"),
            "actor_feature_mean",
            TCN_DEPLOYMENT_FEATURE_DIM,
        )
        std = cls._positive_vector(
            value.get("std"),
            "actor_feature_std",
            TCN_DEPLOYMENT_FEATURE_DIM,
        )
        return horizons, mean, std, clip

    @staticmethod
    def _load_checkpoint(path: Path, device: str) -> dict:
        if not path.is_file():
            raise FileNotFoundError(f"TCN checkpoint does not exist: {path}")
        try:
            checkpoint = torch.load(
                path,
                map_location=device,
                weights_only=False,
            )
        except TypeError:
            # Torch 1.13 in the Kinesis environment has no weights_only flag.
            checkpoint = torch.load(path, map_location=device)

        required = {
            "model_state_dict",
            "input_dim",
            "hidden_dim",
            "target_dim",
            "dropout",
            "history",
            "horizons",
            "statistics",
        }
        missing = required - set(checkpoint)
        if missing:
            raise ValueError(
                f"TCN checkpoint is missing keys: {sorted(missing)}"
            )
        if int(checkpoint["input_dim"]) != TCN_INPUT_DIM:
            raise ValueError("Only the 32-channel Phase 1/2 TCN is supported.")
        if int(checkpoint["hidden_dim"]) != TCN_LATENT_DIM:
            raise ValueError(
                f"Deployment expects a {TCN_LATENT_DIM}-D TCN latent."
            )
        return checkpoint

    @staticmethod
    def _vector(value: np.ndarray, name: str, size: int) -> np.ndarray:
        array = np.asarray(value, dtype=np.float32)
        if array.shape != (size,):
            raise ValueError(f"{name} must have shape ({size},), got {array.shape}.")
        if not np.all(np.isfinite(array)):
            raise FloatingPointError(f"{name} contains NaN or Inf.")
        return array.copy()

    @classmethod
    def _positive_vector(
        cls,
        value: np.ndarray,
        name: str,
        size: int,
    ) -> np.ndarray:
        array = cls._vector(value, name, size)
        if np.any(array <= 0.0):
            raise ValueError(f"{name} must be strictly positive.")
        return array

    @staticmethod
    def _calibration_vector(
        value: np.ndarray | None,
        name: str,
        *,
        default: float,
    ) -> np.ndarray:
        if value is None:
            return np.full(4, default, dtype=np.float32)
        array = np.asarray(value, dtype=np.float32)
        if array.shape != (4,):
            raise ValueError(f"{name} must have shape (4,), got {array.shape}.")
        if not np.all(np.isfinite(array)):
            raise FloatingPointError(f"{name} contains NaN or Inf.")
        return array.copy()

    @staticmethod
    def _imu_rotation(value: np.ndarray | None) -> np.ndarray:
        if value is None:
            return np.repeat(
                np.eye(3, dtype=np.float32)[None, :, :],
                IMU_COUNT,
                axis=0,
            )
        rotation = np.asarray(value, dtype=np.float32)
        if rotation.shape != (IMU_COUNT, 3, 3):
            raise ValueError(
                "imu_rotation must have shape (4, 3, 3), got "
                f"{rotation.shape}."
            )
        if not np.all(np.isfinite(rotation)):
            raise FloatingPointError("imu_rotation contains NaN or Inf.")
        identity = np.eye(3, dtype=np.float32)
        for matrix in rotation:
            if not np.allclose(matrix @ matrix.T, identity, atol=1.0e-4):
                raise ValueError("Each IMU rotation must be orthonormal.")
            if not np.isclose(np.linalg.det(matrix), 1.0, atol=1.0e-4):
                raise ValueError("Each IMU rotation must have determinant +1.")
        return rotation.copy()
