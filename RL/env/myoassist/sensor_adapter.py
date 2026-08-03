"""Read MyoAssist state in the four-joint G-Exo sensor convention."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

import numpy as np


@dataclass(frozen=True)
class JointSensorSpec:
    """Map one MyoAssist coordinate to the deployment joint convention."""

    name: str
    sign: float


# Deployment order: left hip, left knee, right hip, right knee.
# MyoAssist knee flexion is negative; G-Exo knee flexion is positive.
JOINT_SPECS = (
    JointSensorSpec("hip_flexion_l", 1.0),
    JointSensorSpec("knee_angle_l", -1.0),
    JointSensorSpec("hip_flexion_r", 1.0),
    JointSensorSpec("knee_angle_r", -1.0),
)

IMU_NAMES = (
    "left_thigh",
    "left_shank",
    "right_thigh",
    "right_shank",
)


class MyoAssistSensorAdapter:
    """Extract backend state without owning shared frame construction."""

    def read_state(self, environment: Any) -> dict[str, np.ndarray]:
        sim = environment.sim
        motor_q = np.asarray(
            [
                spec.sign * float(sim.data.joint(spec.name).qpos[0])
                for spec in JOINT_SPECS
            ],
            dtype=np.float32,
        )
        motor_dq = np.asarray(
            [
                spec.sign * float(sim.data.joint(spec.name).qvel[0])
                for spec in JOINT_SPECS
            ],
            dtype=np.float32,
        )
        angular_velocity = np.stack(
            [
                sim.data.sensor(f"gexo_imu_{name}_gyro").data.copy()
                for name in IMU_NAMES
            ]
        ).astype(np.float32)
        specific_force = np.stack(
            [
                sim.data.sensor(f"gexo_imu_{name}_accelerometer").data.copy()
                for name in IMU_NAMES
            ]
        ).astype(np.float32)

        state = {
            "motor_q": motor_q,
            "motor_dq": motor_dq,
            "imu_angular_velocity": angular_velocity,
            "imu_specific_force": specific_force,
        }
        if not all(np.all(np.isfinite(value)) for value in state.values()):
            raise FloatingPointError("MyoAssist sensor state contains NaN or Inf.")
        return state
