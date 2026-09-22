"""Episode-wise deployment randomization for the MyoAssist G-Exo plant."""

from __future__ import annotations

from collections import deque
from dataclasses import asdict, dataclass
from typing import Any

import numpy as np

import mujoco


URDF_BODY_PREFIX = "gexo_dynamic_"
URDF_JOINT_PREFIX = "gexo_dynamic_"
CUFF_EQUALITY_PREFIX = "gexo_cuff_"


@dataclass(frozen=True)
class DeploymentRandomizationConfig:
    enabled: bool = False
    torque_gain_fraction: float = 0.05
    max_action_delay_steps: int = 1
    motor_position_bias_rad: float = np.deg2rad(0.5)
    motor_velocity_scale_fraction: float = 0.02
    imu_orientation_error_rad: float = np.deg2rad(1.0)
    specific_force_scale_fraction: float = 0.02
    urdf_inertial_fraction: float = 0.05
    urdf_joint_dynamics_fraction: float = 0.10
    cuff_time_constant_fraction: float = 0.10

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class DeploymentRandomizer:
    """Sample fixed episode calibration errors and a bounded action delay."""

    def __init__(
        self,
        config: DeploymentRandomizationConfig,
        *,
        torque_limit_nm: np.ndarray,
        torque_rate_limit_nm_s: np.ndarray | None = None,
        control_dt: float = 0.02,
        model: mujoco.MjModel | None = None,
        data: mujoco.MjData | None = None,
    ) -> None:
        self.config = config
        self.torque_limit_nm = _vector4(torque_limit_nm, "torque_limit_nm")
        if np.any(self.torque_limit_nm <= 0.0):
            raise ValueError("torque_limit_nm must be positive.")
        self.torque_rate_limit_nm_s = (
            np.full(4, np.inf)
            if torque_rate_limit_nm_s is None
            else _vector4(torque_rate_limit_nm_s, "torque_rate_limit_nm_s")
        )
        if np.any(self.torque_rate_limit_nm_s <= 0.0) or control_dt <= 0.0:
            raise ValueError("Torque rate limits and control_dt must be positive.")
        self.control_dt = float(control_dt)
        if not 0.0 <= config.torque_gain_fraction < 1.0:
            raise ValueError("torque_gain_fraction must be in [0, 1).")
        if config.max_action_delay_steps not in (0, 1):
            raise ValueError("MVP action delay must be zero or one step.")
        for name in (
            "urdf_inertial_fraction",
            "urdf_joint_dynamics_fraction",
            "cuff_time_constant_fraction",
        ):
            value = float(getattr(config, name))
            if not 0.0 <= value < 1.0:
                raise ValueError(f"{name} must be in [0, 1).")
        if (model is None) != (data is None):
            raise ValueError("model and data must be supplied together.")
        self.model = model
        self.data = data
        self._capture_urdf_parameters()
        self.reset(np.random.default_rng(0))

    def reset(self, rng: np.random.Generator) -> None:
        self._rng = rng
        self._restore_urdf_parameters()
        if self.config.enabled:
            self.torque_gain = self._uniform_fraction(
                self.config.torque_gain_fraction, (4,)
            )
            self.action_delay_steps = int(
                rng.integers(0, self.config.max_action_delay_steps + 1)
            )
            self.motor_position_bias = rng.uniform(
                -self.config.motor_position_bias_rad,
                self.config.motor_position_bias_rad,
                size=4,
            )
            self.motor_velocity_scale = self._uniform_fraction(
                self.config.motor_velocity_scale_fraction, (4,)
            )
            self.imu_rotation = np.stack(
                [self._sample_rotation() for _ in range(4)]
            )
            self.specific_force_scale = self._uniform_fraction(
                self.config.specific_force_scale_fraction, (4, 1)
            )
            self._randomize_urdf_parameters()
        else:
            self.torque_gain = np.ones(4)
            self.action_delay_steps = 0
            self.motor_position_bias = np.zeros(4)
            self.motor_velocity_scale = np.ones(4)
            self.imu_rotation = np.repeat(np.eye(3)[None, :, :], 4, axis=0)
            self.specific_force_scale = np.ones((4, 1))
            self.urdf_inertial_scale = np.ones(len(self._urdf_body_ids))
            self.urdf_joint_dynamics_scale = np.ones(len(self._urdf_dof_ids))
            self.cuff_time_constant_scale = np.ones(len(self._cuff_eq_ids))
        self._torque_queue: deque[np.ndarray] = deque(
            [np.zeros(4, dtype=np.float64) for _ in range(self.action_delay_steps + 1)],
            maxlen=self.action_delay_steps + 1,
        )
        self._previous_applied_torque = np.zeros(4, dtype=np.float64)

    def apply_torque(self, commanded_torque_nm: np.ndarray) -> np.ndarray:
        command = _vector4(commanded_torque_nm, "commanded_torque_nm")
        self._torque_queue.append(command.copy())
        delayed = self._torque_queue[0]
        target = np.clip(
            delayed * self.torque_gain,
            -self.torque_limit_nm,
            self.torque_limit_nm,
        )
        if self.config.enabled:
            maximum_delta = self.torque_rate_limit_nm_s * self.control_dt
            target = self._previous_applied_torque + np.clip(
                target - self._previous_applied_torque,
                -maximum_delta,
                maximum_delta,
            )
        self._previous_applied_torque = target.copy()
        return target.astype(np.float32)

    def randomize_state(self, state: dict[str, Any]) -> dict[str, np.ndarray]:
        motor_q = _vector4(state["motor_q"], "motor_q")
        motor_dq = _vector4(state["motor_dq"], "motor_dq")
        gyro = _matrix43(state["imu_angular_velocity"], "imu_angular_velocity")
        force = _matrix43(state["imu_specific_force"], "imu_specific_force")
        return {
            "motor_q": (motor_q + self.motor_position_bias).astype(np.float32),
            "motor_dq": (motor_dq * self.motor_velocity_scale).astype(np.float32),
            "imu_angular_velocity": np.einsum(
                "nij,nj->ni", self.imu_rotation, gyro
            ).astype(np.float32),
            "imu_specific_force": (
                np.einsum("nij,nj->ni", self.imu_rotation, force)
                * self.specific_force_scale
            ).astype(np.float32),
        }

    def diagnostics(self) -> dict[str, float]:
        return {
            "enabled": float(self.config.enabled),
            "action_delay_steps": float(self.action_delay_steps),
            "mean_torque_gain": float(np.mean(self.torque_gain)),
            "max_abs_motor_position_bias_rad": float(
                np.max(np.abs(self.motor_position_bias))
            ),
            "urdf_randomized": float(
                self.config.enabled and self._urdf_body_ids.size > 0
            ),
            "mean_urdf_inertial_scale": _mean_or_one(
                self.urdf_inertial_scale
            ),
            "mean_urdf_joint_dynamics_scale": _mean_or_one(
                self.urdf_joint_dynamics_scale
            ),
            "mean_cuff_time_constant_scale": _mean_or_one(
                self.cuff_time_constant_scale
            ),
        }

    def _capture_urdf_parameters(self) -> None:
        if self.model is None:
            self._urdf_body_ids = np.empty(0, dtype=np.int32)
            self._urdf_dof_ids = np.empty(0, dtype=np.int32)
            self._cuff_eq_ids = np.empty(0, dtype=np.int32)
            self._nominal_body_mass = np.empty(0)
            self._nominal_body_inertia = np.empty((0, 3))
            self._nominal_dof_damping = np.empty(0)
            self._nominal_dof_frictionloss = np.empty(0)
            self._nominal_dof_armature = np.empty(0)
            self._nominal_cuff_solref = np.empty((0, 2))
            return

        self._urdf_body_ids = np.asarray(
            [
                body_id
                for body_id in range(1, self.model.nbody)
                if _object_name(
                    self.model,
                    mujoco.mjtObj.mjOBJ_BODY,
                    body_id,
                ).startswith(URDF_BODY_PREFIX)
            ],
            dtype=np.int32,
        )
        joint_ids = [
            joint_id
            for joint_id in range(self.model.njnt)
            if _object_name(
                self.model,
                mujoco.mjtObj.mjOBJ_JOINT,
                joint_id,
            ).startswith(URDF_JOINT_PREFIX)
        ]
        self._urdf_dof_ids = np.asarray(
            [int(self.model.jnt_dofadr[joint_id]) for joint_id in joint_ids],
            dtype=np.int32,
        )
        self._cuff_eq_ids = np.asarray(
            [
                equality_id
                for equality_id in range(self.model.neq)
                if _object_name(
                    self.model,
                    mujoco.mjtObj.mjOBJ_EQUALITY,
                    equality_id,
                ).startswith(CUFF_EQUALITY_PREFIX)
            ],
            dtype=np.int32,
        )
        self._nominal_body_mass = self.model.body_mass[
            self._urdf_body_ids
        ].copy()
        self._nominal_body_inertia = self.model.body_inertia[
            self._urdf_body_ids
        ].copy()
        self._nominal_dof_damping = self.model.dof_damping[
            self._urdf_dof_ids
        ].copy()
        self._nominal_dof_frictionloss = self.model.dof_frictionloss[
            self._urdf_dof_ids
        ].copy()
        self._nominal_dof_armature = self.model.dof_armature[
            self._urdf_dof_ids
        ].copy()
        self._nominal_cuff_solref = self.model.eq_solref[
            self._cuff_eq_ids
        ].copy()

    def _restore_urdf_parameters(self) -> None:
        if self.model is None:
            return
        self.model.body_mass[self._urdf_body_ids] = self._nominal_body_mass
        self.model.body_inertia[self._urdf_body_ids] = self._nominal_body_inertia
        self.model.dof_damping[self._urdf_dof_ids] = self._nominal_dof_damping
        self.model.dof_frictionloss[
            self._urdf_dof_ids
        ] = self._nominal_dof_frictionloss
        self.model.dof_armature[self._urdf_dof_ids] = self._nominal_dof_armature
        self.model.eq_solref[self._cuff_eq_ids] = self._nominal_cuff_solref
        mujoco.mj_setConst(self.model, self.data)

    def _randomize_urdf_parameters(self) -> None:
        self.urdf_inertial_scale = self._uniform_fraction(
            self.config.urdf_inertial_fraction,
            (len(self._urdf_body_ids),),
        )
        self.urdf_joint_dynamics_scale = self._uniform_fraction(
            self.config.urdf_joint_dynamics_fraction,
            (len(self._urdf_dof_ids),),
        )
        self.cuff_time_constant_scale = self._uniform_fraction(
            self.config.cuff_time_constant_fraction,
            (len(self._cuff_eq_ids),),
        )
        if self.model is None:
            return
        inertial = self.urdf_inertial_scale
        dynamics = self.urdf_joint_dynamics_scale
        self.model.body_mass[self._urdf_body_ids] = (
            self._nominal_body_mass * inertial
        )
        self.model.body_inertia[self._urdf_body_ids] = (
            self._nominal_body_inertia * inertial[:, None]
        )
        self.model.dof_damping[self._urdf_dof_ids] = (
            self._nominal_dof_damping * dynamics
        )
        self.model.dof_frictionloss[self._urdf_dof_ids] = (
            self._nominal_dof_frictionloss * dynamics
        )
        self.model.dof_armature[self._urdf_dof_ids] = (
            self._nominal_dof_armature * dynamics
        )
        self.model.eq_solref[self._cuff_eq_ids, 0] = (
            self._nominal_cuff_solref[:, 0] * self.cuff_time_constant_scale
        )
        mujoco.mj_setConst(self.model, self.data)

    def _uniform_fraction(self, fraction: float, shape: tuple[int, ...]) -> np.ndarray:
        return self._rng.uniform(1.0 - fraction, 1.0 + fraction, size=shape)

    def _sample_rotation(self) -> np.ndarray:
        axis = self._rng.normal(size=3)
        norm = float(np.linalg.norm(axis))
        axis = np.asarray([1.0, 0.0, 0.0]) if norm < 1.0e-12 else axis / norm
        angle = self._rng.uniform(
            -self.config.imu_orientation_error_rad,
            self.config.imu_orientation_error_rad,
        )
        cross = np.asarray(
            [
                [0.0, -axis[2], axis[1]],
                [axis[2], 0.0, -axis[0]],
                [-axis[1], axis[0], 0.0],
            ]
        )
        return np.eye(3) + np.sin(angle) * cross + (1.0 - np.cos(angle)) * (cross @ cross)


def _vector4(value: Any, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (4,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must have shape (4,) and be finite.")
    return array.copy()


def _matrix43(value: Any, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (4, 3) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must have shape (4, 3) and be finite.")
    return array.copy()


def _object_name(
    model: mujoco.MjModel,
    object_type: mujoco.mjtObj,
    object_id: int,
) -> str:
    name = mujoco.mj_id2name(model, object_type, object_id)
    return "" if name is None else name


def _mean_or_one(value: np.ndarray) -> float:
    return 1.0 if value.size == 0 else float(np.mean(value))


__all__ = ["DeploymentRandomizationConfig", "DeploymentRandomizer"]
