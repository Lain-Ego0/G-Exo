from __future__ import annotations

from typing import Any

import numpy as np

from RL.env.actor_observation import (
    ACTOR_FRAME_DIM,
    RUNTIME_SENSOR_DIM,
    build_actor_frame,
)


SENSOR_DIM = RUNTIME_SENSOR_DIM
FRAME_DIM = ACTOR_FRAME_DIM

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
        """Return the legacy raw 36-D frame for existing callers."""

        arrays = self._read_state_arrays(state)
        action = self._read_array(
            previous_action,
            name="previous_action",
            shape=(4,),
        )
        runtime32 = self._assemble_runtime32(*arrays)
        return build_actor_frame(runtime32, action)

    def read_runtime32(
        self,
        *,
        state: dict[str, Any],
    ) -> np.ndarray:
        """Read one raw frame in ``gexo_sensor32_runtime_v1`` order."""

        return self._assemble_runtime32(*self._read_state_arrays(state))

    def _read_state_arrays(
        self,
        state: dict[str, Any],
    ) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
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

        return motor_q, motor_dq, gyro, specific_force

    def _assemble_runtime32(
        self,
        motor_q: np.ndarray,
        motor_dq: np.ndarray,
        gyro: np.ndarray,
        specific_force: np.ndarray,
    ) -> np.ndarray:

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
            )
        ).astype(np.float32)

        if frame.shape != (SENSOR_DIM,):
            raise RuntimeError(
                f"Sensor frame must have shape "
                f"({SENSOR_DIM},), got {frame.shape}."
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
