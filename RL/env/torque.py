#将归一化数值转化为电机输出力矩
#同时对电机做一定规范和限制
from __future__ import annotations

import numpy as np


class TorqueActuator:
    """
    Convert a normalized four-joint action into safe torque commands.

    Processing order:
        normalized action
        -> peak torque limit
        -> torque rate limit
        -> first-order low-pass filter
        -> final torque limit
    """

    def __init__(
        self,
        torque_limit_nm: np.ndarray,
        torque_rate_limit_nm_s: np.ndarray,
        *,
        control_dt: float = 0.02,
        filter_time_constant_s: float = 0.0,
    ) -> None:
        self.torque_limit_nm = self._validate_parameter(
            torque_limit_nm,
            name="torque_limit_nm",
        )

        self.torque_rate_limit_nm_s = self._validate_parameter(
            torque_rate_limit_nm_s,
            name="torque_rate_limit_nm_s",
        )

        if control_dt <= 0.0:
            raise ValueError("control_dt must be positive.")

        if filter_time_constant_s < 0.0:
            raise ValueError(
                "filter_time_constant_s must be non-negative."
            )

        self.control_dt = float(control_dt)
        self.filter_time_constant_s = float(
            filter_time_constant_s
        )

        self._rate_limited_torque = np.zeros(
            4,
            dtype=np.float32,
        )

        self._filtered_torque = np.zeros(
            4,
            dtype=np.float32,
        )

    def reset(self) -> None:
        """Reset actuator memory at the beginning of an episode."""

        self._rate_limited_torque.fill(0.0)
        self._filtered_torque.fill(0.0)

    def process(self, normalized_action: np.ndarray) -> np.ndarray:
        """
        Convert an action in [-1, 1] to four physical torques.

        Joint order:
            [left_hip, left_knee, right_hip, right_knee]
        """

        action = np.asarray(
            normalized_action,
            dtype=np.float32,
        )

        if action.shape != (4,):
            raise ValueError(
                f"Action must have shape (4,), got {action.shape}."
            )

        if not np.all(np.isfinite(action)):
            raise FloatingPointError(
                "Action contains NaN or Inf."
            )

        action = np.clip(action, -1.0, 1.0)

        target_torque = action * self.torque_limit_nm

        rate_limited_torque = self._apply_rate_limit(
            target_torque
        )

        filtered_torque = self._apply_low_pass_filter(
            rate_limited_torque
        )

        final_torque = np.clip(
            filtered_torque,
            -self.torque_limit_nm,
            self.torque_limit_nm,
        ).astype(np.float32)

        self._rate_limited_torque = (
            rate_limited_torque.copy()
        )
        self._filtered_torque = final_torque.copy()

        return final_torque.copy()

    def _apply_rate_limit(
        self,
        target_torque: np.ndarray,
    ) -> np.ndarray:
        max_delta = (
            self.torque_rate_limit_nm_s
            * self.control_dt
        )

        requested_delta = (
            target_torque
            - self._rate_limited_torque
        )

        limited_delta = np.clip(
            requested_delta,
            -max_delta,
            max_delta,
        )

        return (
            self._rate_limited_torque
            + limited_delta
        )

    def _apply_low_pass_filter(
        self,
        input_torque: np.ndarray,
    ) -> np.ndarray:
        if self.filter_time_constant_s == 0.0:
            return input_torque.copy()

        alpha = self.control_dt / (
            self.filter_time_constant_s
            + self.control_dt
        )

        return (
            self._filtered_torque
            + alpha
            * (input_torque - self._filtered_torque)
        )

    @staticmethod
    def _validate_parameter(
        value: np.ndarray,
        *,
        name: str,
    ) -> np.ndarray:
        array = np.asarray(
            value,
            dtype=np.float32,
        )

        if array.shape != (4,):
            raise ValueError(
                f"{name} must have shape (4,), "
                f"got {array.shape}."
            )

        if not np.all(np.isfinite(array)):
            raise ValueError(
                f"{name} contains NaN or Inf."
            )

        if np.any(array <= 0.0):
            raise ValueError(
                f"Every value in {name} must be positive."
            )

        return array.copy()