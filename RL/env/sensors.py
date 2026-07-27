from __future__ import annotations

from typing import Any

import numpy as np


SENSOR_DIM = 32
FRAME_DIM = 36

class SensorReader:
    def __init__(
        self,
        *,
        gyro_limit_rad_s: float = np.deg2rad(2000.0),
        specific_force_limit_m_s2: float = 16.0 * 9.80665,
        gyro_noise_std_rad_s: float = 0.0,
        specific_force_noise_std_m_s2: float = 0.0,
        gyro_bias_std_rad_s: float = 0.0,
        specific_force_bias_std_m_s2: float = 0.0,
    ) -> None:
        self.gyro_limit_rad_s = float(
            gyro_limit_rad_s
        )

        self.specific_force_limit_m_s2 = float(
            specific_force_limit_m_s2
        )

        self.gyro_noise_std_rad_s = float(
            gyro_noise_std_rad_s
        )

        self.specific_force_noise_std_m_s2 = float(
            specific_force_noise_std_m_s2
        )

        self.gyro_bias_std_rad_s = float(
            gyro_bias_std_rad_s
        )

        self.specific_force_bias_std_m_s2 = float(
            specific_force_bias_std_m_s2
        )

        self._rng = np.random.default_rng()

        self._gyro_bias = np.zeros(
            (4, 3),
            dtype=np.float32,
        )

        self._specific_force_bias = np.zeros(
            (4, 3),
            dtype=np.float32,
        )
        
    def reset(
        self,
        seed: int | None = None,
    ) -> None:
        self._rng = np.random.default_rng(seed)

        self._gyro_bias = self._sample_noise(
            self.gyro_bias_std_rad_s,
            shape=(4, 3),
        )

        self._specific_force_bias = self._sample_noise(
            self.specific_force_bias_std_m_s2,
            shape=(4, 3),
        )
        
    def read(
        self,
        *,
        state: dict[str, Any],
        previous_action: np.ndarray,
    ) -> np.ndarray:
        motor_q = self._read_array(
            state["motor_q"],
            name="motor_q",
            shape=(4,),
        )

        motor_dq = self._read_array(
            state["motor_dq"],
            name="motor_dq",
            shape=(4,),
        )

        gyro = self._read_array(
            state["imu_angular_velocity"],
            name="imu_angular_velocity",
            shape=(4, 3),
        )

        specific_force = self._read_array(
            state["imu_specific_force"],
            name="imu_specific_force",
            shape=(4, 3),
        )

        action = self._read_array(
            previous_action,
            name="previous_action",
            shape=(4,),
        )

        gyro = (
            gyro
            + self._gyro_bias
            + self._sample_noise(
                self.gyro_noise_std_rad_s,
                shape=(4, 3),
            )
        )

        specific_force = (
            specific_force
            + self._specific_force_bias
            + self._sample_noise(
                self.specific_force_noise_std_m_s2,
                shape=(4, 3),
            )
        )

        gyro = np.clip(
            gyro,
            -self.gyro_limit_rad_s,
            self.gyro_limit_rad_s,
        )

        specific_force = np.clip(
            specific_force,
            -self.specific_force_limit_m_s2,
            self.specific_force_limit_m_s2,
        )

        frame = np.concatenate(
            (
                motor_q,
                motor_dq,
                gyro.reshape(-1),
                specific_force.reshape(-1),
                action,
            )
        ).astype(np.float32)

        if frame.shape != (FRAME_DIM,):
            raise RuntimeError(
                f"Sensor frame must have shape "
                f"({FRAME_DIM},), got {frame.shape}."
            )

        return frame

    def _sample_noise(
        self,
        standard_deviation: float,
        *,
        shape: tuple[int, ...],
    ) -> np.ndarray:
        if standard_deviation == 0.0:
            return np.zeros(
                shape,
                dtype=np.float32,
            )

        return self._rng.normal(
            loc=0.0,
            scale=standard_deviation,
            size=shape,
        ).astype(np.float32)

    @staticmethod
    def _read_array(
        value: Any,
        *,
        name: str,
        shape: tuple[int, ...],
    ) -> np.ndarray:
        array = np.asarray(
            value,
            dtype=np.float32,
        )

        if array.shape != shape:
            raise ValueError(
                f"{name} must have shape {shape}, "
                f"got {array.shape}."
            )

        if not np.all(np.isfinite(array)):
            raise FloatingPointError(
                f"{name} contains NaN or Inf."
            )

        return array