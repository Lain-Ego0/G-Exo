"""Frozen, backend-neutral runtime for the Phase 1/2 motion TCN."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import hashlib
import json
from pathlib import Path

import numpy as np
import torch

from RL.env.actor_observation import (
    JOINT_ORDER,
    RUNTIME_SENSOR_DIM,
    TCN_FEATURE_DIM,
    TCN_HISTORY_LENGTH,
    TCN_SENSOR_PROTOCOL,
    build_tcn_delta16,
    normalize_tcn_delta16,
    runtime32_to_phase12_interleaved,
)
from RL.runners.predictors.tcn import MotionTCN


TCN_HORIZON_STEPS = (5, 10)
CONTROL_FREQUENCY_HZ = 50.0
JOINT_PREDICTION_DIM = 8


@dataclass(frozen=True)
class TCNRuntimeOutput:
    """One explicit frozen-TCN result in deployment coordinates."""

    prediction: np.ndarray
    normalized_prediction: np.ndarray
    joint_prediction: np.ndarray
    raw_delta16: np.ndarray
    feature16: np.ndarray


class FrozenTCNRuntime:
    """Consume 50 causal runtime32 frames and emit explicit delta16."""

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
        feature_mean: np.ndarray | None = None,
        feature_std: np.ndarray | None = None,
        feature_clip: float | np.ndarray | None = None,
        allow_legacy_checkpoint: bool = False,
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
        self.target_dim = int(checkpoint_data["target_dim"])
        self.legacy_checkpoint = self._validate_protocol(
            checkpoint_data,
            allow_legacy_checkpoint=allow_legacy_checkpoint,
        )

        statistics = checkpoint_data["statistics"]
        self.input_mean = self._vector(
            statistics["input_mean"],
            "input_mean",
            RUNTIME_SENSOR_DIM,
        )
        self.input_std = self._positive_vector(
            statistics["input_std"],
            "input_std",
            RUNTIME_SENSOR_DIM,
        )
        self.target_mean = self._vector(
            statistics["target_mean"],
            "target_mean",
            self.target_dim,
        )
        self.target_std = self._positive_vector(
            statistics["target_std"],
            "target_std",
            self.target_dim,
        )

        calibration_data = self._load_calibration(calibration)
        input_calibration = calibration_data.get("input", {})
        output = calibration_data.get("output", {})
        normalization = calibration_data.get(
            "actor_feature_normalization",
            {},
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
            else output.get("target_position_scale"),
            "target_position_scale",
            default=1.0,
        )
        self.target_position_offset = self._calibration_vector(
            target_position_offset
            if target_position_offset is not None
            else output.get("target_position_offset"),
            "target_position_offset",
            default=0.0,
        )
        self.target_velocity_scale = self._calibration_vector(
            target_velocity_scale
            if target_velocity_scale is not None
            else output.get("target_velocity_scale"),
            "target_velocity_scale",
            default=1.0,
        )
        self.feature_mean = self._vector(
            feature_mean
            if feature_mean is not None
            else normalization.get("mean"),
            "feature_mean",
            TCN_FEATURE_DIM,
        )
        self.feature_std = self._positive_vector(
            feature_std
            if feature_std is not None
            else normalization.get("std"),
            "feature_std",
            TCN_FEATURE_DIM,
        )
        selected_clip = (
            feature_clip
            if feature_clip is not None
            else normalization.get("clip")
        )
        if selected_clip is None:
            raise ValueError("Fixed actor feature clip is required.")
        self.feature_clip = self._positive_clip(selected_clip)
        feature_horizons = tuple(
            int(value)
            for value in normalization.get(
                "horizon_steps",
                TCN_HORIZON_STEPS,
            )
        )
        if feature_horizons != TCN_HORIZON_STEPS:
            raise ValueError(
                "actor_feature_normalization must use horizons (5, 10)."
            )

        self.model = MotionTCN(
            input_dim=int(checkpoint_data["input_dim"]),
            hidden_dim=int(checkpoint_data["hidden_dim"]),
            target_dim=self.target_dim,
            horizon_count=len(self.horizons),
            dropout=float(checkpoint_data.get("dropout", 0.0)),
            auxiliary_dim=int(checkpoint_data.get("auxiliary_dim", 0)),
        ).to(self.device)
        self.model.load_state_dict(checkpoint_data["model_state_dict"])
        self.model.eval()
        self.model.requires_grad_(False)

        self.calibration_path = (
            None
            if calibration is None
            else Path(calibration).expanduser().resolve()
        )
        self.checkpoint_sha256 = _sha256(self.checkpoint_path)
        self.calibration_sha256 = (
            None
            if self.calibration_path is None
            else _sha256(self.calibration_path)
        )
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

    def append(self, runtime_sensor32: np.ndarray) -> None:
        """Reorder, normalize and append one calibrated runtime frame."""

        tcn_frame = self.to_tcn_order(runtime_sensor32)
        normalized = (
            (tcn_frame - self.input_mean) / self.input_std
        ).astype(np.float32)
        if not np.all(np.isfinite(normalized)):
            raise FloatingPointError("Normalized TCN frame contains NaN or Inf.")
        self._history.append(normalized)

    def extend(self, runtime_history: np.ndarray) -> None:
        history = np.asarray(runtime_history, dtype=np.float32)
        if history.ndim != 2 or history.shape[1] != RUNTIME_SENSOR_DIM:
            raise ValueError(
                "runtime_history must have shape [time, 32], got "
                f"{history.shape}."
            )
        if not np.all(np.isfinite(history)):
            raise FloatingPointError("runtime_history contains NaN or Inf.")
        for frame in history:
            self.append(frame)

    def to_tcn_order(self, runtime_sensor32: np.ndarray) -> np.ndarray:
        """Apply backend calibration and convert to Phase 1/2 channel order."""

        frame = self._vector(
            runtime_sensor32,
            "runtime_sensor32",
            RUNTIME_SENSOR_DIM,
        )
        calibrated = frame.copy()
        calibrated[:4] = (
            frame[:4] * self.motor_position_scale
            + self.motor_position_offset
        )
        calibrated[4:8] = frame[4:8] * self.motor_velocity_scale
        gyro = frame[8:20].reshape(4, 3)
        specific_force = frame[20:32].reshape(4, 3)
        calibrated[8:20] = np.einsum(
            "nij,nj->ni",
            self.imu_rotation,
            gyro,
        ).reshape(-1)
        calibrated[20:32] = np.einsum(
            "nij,nj->ni",
            self.imu_rotation,
            specific_force,
        ).reshape(-1)
        return runtime32_to_phase12_interleaved(calibrated)

    def predict(
        self,
        current_joint_position: np.ndarray,
        current_joint_velocity: np.ndarray,
    ) -> TCNRuntimeOutput:
        """Predict +5/+10 q/dq and return fixed-normalized delta16."""

        if not self.ready:
            raise RuntimeError(
                f"TCN needs {self.history_length} frames, "
                f"but only {len(self._history)} are available."
            )
        history = np.stack(tuple(self._history), axis=0)
        inputs = torch.from_numpy(history.T.copy()).unsqueeze(0)
        inputs = inputs.to(self.device)
        with torch.inference_mode():
            normalized = self.model(inputs)[0]
        normalized_np = normalized.cpu().numpy().astype(np.float32)
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
        ).astype(np.float32)
        raw_delta16 = build_tcn_delta16(
            joint_prediction,
            current_joint_position,
            current_joint_velocity,
        )
        feature16 = normalize_tcn_delta16(
            raw_delta16,
            self.feature_mean,
            self.feature_std,
            self.feature_clip,
        )
        return TCNRuntimeOutput(
            prediction=prediction.astype(np.float32),
            normalized_prediction=normalized_np,
            joint_prediction=joint_prediction,
            raw_delta16=raw_delta16,
            feature16=feature16,
        )

    def metadata(self) -> dict[str, object]:
        """Return the protocol-critical metadata required by Actor checkpoints."""

        return {
            "sensor_protocol": TCN_SENSOR_PROTOCOL,
            "joint_order": list(JOINT_ORDER),
            "control_frequency_hz": CONTROL_FREQUENCY_HZ,
            "history": self.history_length,
            "horizons": list(self.horizons),
            "feature_order": [
                "delta_q(+5)",
                "delta_dq(+5)",
                "delta_q(+10)",
                "delta_dq(+10)",
            ],
            "feature_mean": self.feature_mean.tolist(),
            "feature_std": self.feature_std.tolist(),
            "feature_clip": self.feature_clip.tolist(),
            "input_calibration": {
                "motor_position_scale": self.motor_position_scale.tolist(),
                "motor_position_offset": self.motor_position_offset.tolist(),
                "motor_velocity_scale": self.motor_velocity_scale.tolist(),
                "imu_rotation": self.imu_rotation.tolist(),
            },
            "checkpoint": str(self.checkpoint_path),
            "checkpoint_sha256": self.checkpoint_sha256,
            "calibration": (
                None
                if self.calibration_path is None
                else str(self.calibration_path)
            ),
            "calibration_sha256": self.calibration_sha256,
            "legacy_checkpoint": self.legacy_checkpoint,
        }

    def _validate_protocol(
        self,
        checkpoint: dict,
        *,
        allow_legacy_checkpoint: bool,
    ) -> bool:
        if int(checkpoint["input_dim"]) != RUNTIME_SENSOR_DIM:
            raise ValueError("TCN checkpoint must use 32 input channels.")
        if self.target_dim < JOINT_PREDICTION_DIM:
            raise ValueError("TCN target must contain four q and four dq values.")
        if self.history_length != TCN_HISTORY_LENGTH:
            raise ValueError("Deployment TCN history must be exactly 50 frames.")
        if self.horizons != TCN_HORIZON_STEPS:
            raise ValueError("Deployment TCN horizons must be exactly (5, 10).")
        metadata_keys = {
            "sensor_protocol",
            "joint_order",
            "control_frequency_hz",
        }
        missing_metadata = metadata_keys - set(checkpoint)
        if missing_metadata and not allow_legacy_checkpoint:
            raise ValueError(
                "Checkpoint lacks deployment metadata "
                f"{sorted(missing_metadata)}; load it only through "
                "allow_legacy_checkpoint=True."
            )
        declared_protocol = checkpoint.get("sensor_protocol")
        if (
            declared_protocol is not None
            and declared_protocol != TCN_SENSOR_PROTOCOL
        ):
            raise ValueError(
                f"Unsupported checkpoint sensor_protocol: {declared_protocol}."
            )
        declared_joint_order = checkpoint.get("joint_order")
        if (
            declared_joint_order is not None
            and tuple(declared_joint_order) != JOINT_ORDER
        ):
            raise ValueError("TCN checkpoint joint_order is incompatible.")
        declared_frequency = checkpoint.get("control_frequency_hz")
        if (
            declared_frequency is not None
            and not np.isclose(
                float(declared_frequency),
                CONTROL_FREQUENCY_HZ,
                rtol=0.0,
                atol=1.0e-9,
            )
        ):
            raise ValueError("TCN checkpoint control frequency must be 50 Hz.")
        return bool(missing_metadata)

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
            checkpoint = torch.load(path, map_location=device)
        required = {
            "model_state_dict",
            "input_dim",
            "hidden_dim",
            "target_dim",
            "history",
            "horizons",
            "statistics",
        }
        missing = required - set(checkpoint)
        if missing:
            raise ValueError(
                f"TCN checkpoint is missing keys: {sorted(missing)}"
            )
        statistics = checkpoint["statistics"]
        required_statistics = {
            "input_mean",
            "input_std",
            "target_mean",
            "target_std",
        }
        missing_statistics = required_statistics - set(statistics)
        if missing_statistics:
            raise ValueError(
                "TCN statistics are missing keys: "
                f"{sorted(missing_statistics)}"
            )
        return checkpoint

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

    @classmethod
    def _calibration_vector(
        cls,
        value: np.ndarray | None,
        name: str,
        *,
        default: float,
    ) -> np.ndarray:
        if value is None:
            return np.full(4, default, dtype=np.float32)
        return cls._vector(value, name, 4)

    @staticmethod
    def _positive_clip(value: float | np.ndarray) -> np.ndarray:
        clip = np.asarray(value, dtype=np.float32)
        if clip.ndim == 0:
            clip = np.full(TCN_FEATURE_DIM, float(clip), dtype=np.float32)
        if (
            clip.shape != (TCN_FEATURE_DIM,)
            or not np.all(np.isfinite(clip))
            or np.any(clip <= 0.0)
        ):
            raise ValueError("feature_clip must be positive and scalar or (16,).")
        return clip.copy()

    @staticmethod
    def _imu_rotation(value: np.ndarray | None) -> np.ndarray:
        if value is None:
            return np.repeat(np.eye(3, dtype=np.float32)[None, :, :], 4, axis=0)
        rotation = np.asarray(value, dtype=np.float32)
        if rotation.shape != (4, 3, 3) or not np.all(np.isfinite(rotation)):
            raise ValueError("imu_rotation must be finite with shape (4, 3, 3).")
        identity = np.eye(3, dtype=np.float32)
        for matrix in rotation:
            if not np.allclose(matrix @ matrix.T, identity, atol=1.0e-5):
                raise ValueError("Every imu_rotation matrix must be orthonormal.")
            if not np.isclose(np.linalg.det(matrix), 1.0, atol=1.0e-5):
                raise ValueError("Every imu_rotation matrix must be a proper rotation.")
        return rotation.copy()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as file:
        for chunk in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


__all__ = [
    "CONTROL_FREQUENCY_HZ",
    "FrozenTCNRuntime",
    "JOINT_PREDICTION_DIM",
    "TCN_HORIZON_STEPS",
    "TCNRuntimeOutput",
]
