from __future__ import annotations

from typing import Any

import numpy as np

class HumanTrackingController:
    def __init__(
        self,
        kp:np.ndarray,
        kd:np.ndarray,
        torque_limit_nm:np.ndarray,
    ) -> None:
        self.kp = self._as_four_vector(
            kp,
            name = "kp"
        )#为什么要这么脱裤子放屁？
        
        self.kd = self._as_four_vector(
            kd,
            name="kd",
        )

        self.torque_limit_nm = self._as_four_vector(
            torque_limit_nm,
            name="torque_limit_nm",
        )
        
    def reset(self) -> None:
        pass
    
    def compute(
        self,
        state:dict[str, Any],
        reference:dict[str, Any],
    ) -> np.ndarray:
        q = np.asarray(
            state["tracking_q"],
            dtype=np.float32,
        )
        
        dq = np.asarray(
            state["tracking_dq"],
            dtype=np.float32,
        )

        q_ref = np.asarray(
            reference["q"],
            dtype=np.float32,
        )

        dq_ref = np.asarray(
            reference["dq"],
            dtype=np.float32,
        )
        
        feedforward_torque = np.asarray(
            reference.get(
                "human_control",
                np.zeros(4, dtype=np.float32),
            ),
            dtype=np.float32,
        )
        
        for name ,value in (
            ("tracking_q",q),
            ("tracking_dq",dq),
            ("reference q",q_ref),
            ("reference dq",dq_ref),
            ("human_control",feedforward_torque),
        ):
            if value.shape != (4,):
                raise ValueError(
                    f"{name} must have shape (4,), "
                    f"got {value.shape}."
                )
        
        human_torque = (
            feedforward_torque
            + self.kp * (q_ref - q)
            + self.kd * (dq_ref - dq)
        )
        
        return np.clip(
            human_torque,
            -self.torque_limit_nm,
            self.torque_limit_nm,
        ).astype(np.float32)
        
        
    @staticmethod
    def _as_four_vector(
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

        return array.copy()

