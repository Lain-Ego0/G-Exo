"""将Phase参考轨迹转换为MyoSuite的80维肌肉动作。"""

from __future__ import annotations

from typing import Any

import mujoco
import numpy as np
from scipy.optimize import lsq_linear

from RL.env.myosuite.phase_reference import JOINT_NAMES


# MyoSuite内部使用的非线性动作映射：
# excitation = sigmoid(5 * (action - 0.5))
EXCITATION_MIN = 1.0 / (1.0 + np.exp(7.5))
EXCITATION_MAX = 1.0 / (1.0 + np.exp(-2.5))


class MuscleController:
    """基于PD反馈和静态肌肉募集的人体控制器。"""

    def __init__(
        self,
        environment: Any,
        *,
        kp: float = 30.0,
        kd: float = 2.0,
        regularization: float = 1.0e-2,
        body_mass_kg: float | None = None,
    ) -> None:
        self.environment = environment.unwrapped
        self.model = self.environment.mj_model
        self.data = self.environment.mj_data

        self.kp = float(kp)
        self.kd = float(kd)
        self.regularization = float(regularization)

        # 默认使用MyoSuite模型本身的总质量。
        if body_mass_kg is None:
            body_mass_kg = float(
                np.sum(self.model.body_mass)
            )

        self.body_mass_kg = float(body_mass_kg)

        # 找到12个参考关节在qpos和qvel中的位置。
        joint_ids = np.asarray(
            [
                self.model.joint(name).id
                for name in JOINT_NAMES
            ],
            dtype=np.int32,
        )

        self.qpos_ids = self.model.jnt_qposadr[
            joint_ids
        ].astype(np.int32)

        self.dof_ids = self.model.jnt_dofadr[
            joint_ids
        ].astype(np.int32)

        self.number_of_muscles = int(self.model.nu)

        # 正则项矩阵只需建立一次。
        self.regularizer = (
            np.sqrt(self.regularization)
            * np.eye(
                self.number_of_muscles,
                dtype=np.float64,
            )
        )

        self.last_excitation = np.zeros(
            self.number_of_muscles,
            dtype=np.float32,
        )

        self.last_desired_torque = np.zeros(
            len(JOINT_NAMES),
            dtype=np.float32,
        )

    def reset(self) -> None:
        self.last_excitation.fill(0.0)
        self.last_desired_torque.fill(0.0)

    def compute(
        self,
        reference: dict[str, float | np.ndarray],
        exo_torque: np.ndarray | None = None,
        residual_torque: np.ndarray | None = None,
    ) -> np.ndarray:
        """计算当前时刻的80维MyoSuite归一化动作。"""

        q_reference = np.asarray(
            reference["q"],
            dtype=np.float64,
        )
        dq_reference = np.asarray(
            reference["dq"],
            dtype=np.float64,
        )
        moment_nm_kg = np.asarray(
            reference["moment_nm_kg"],
            dtype=np.float64,
        )
        moment_mask = np.asarray(
            reference["moment_mask"],
            dtype=bool,
        )

        expected_shape = (len(JOINT_NAMES),)

        for name, value in (
            ("q", q_reference),
            ("dq", dq_reference),
            ("moment", moment_nm_kg),
            ("moment_mask", moment_mask),
        ):
            if value.shape != expected_shape:
                raise ValueError(
                    f"{name} must have shape {expected_shape}, "
                    f"got {value.shape}."
                )

        if exo_torque is None:
            exo_torque = np.zeros(
                len(JOINT_NAMES),
                dtype=np.float64,
            )
        else:
            exo_torque = np.asarray(
                exo_torque,
                dtype=np.float64,
            )

        if exo_torque.shape != expected_shape:
            raise ValueError(
                f"exo_torque must have shape {expected_shape}."
            )

        if residual_torque is None:
            residual_torque = np.zeros(
                len(JOINT_NAMES),
                dtype=np.float64,
            )
        else:
            residual_torque = np.asarray(
                residual_torque,
                dtype=np.float64,
            )

        if residual_torque.shape != expected_shape:
            raise ValueError(
                f"residual_torque must have shape {expected_shape}."
            )

        q = self.data.qpos[self.qpos_ids]
        dq = self.data.qvel[self.dof_ids]

        # Phase生物力矩由Nm/kg转换为Nm。
        feedforward_torque = np.where(
            moment_mask,
            moment_nm_kg * self.body_mass_kg,
            0.0,
        )

        # PD项负责修正轨迹跟踪误差。
        feedback_torque = (
            self.kp * (q_reference - q)
            + self.kd * (dq_reference - dq)
        )

        # 外骨骼提供多少力矩，人体肌肉就少承担多少。
        desired_muscle_torque = (
            feedforward_torque
            + feedback_torque
            + residual_torque
            - exo_torque
        )

        excitation = self._recruit_muscles(
            desired_muscle_torque
        )

        self.last_excitation = excitation.astype(
            np.float32
        )
        self.last_desired_torque = (
            desired_muscle_torque.astype(np.float32)
        )

        return self._excitation_to_action(excitation)

    def _recruit_muscles(
        self,
        desired_torque: np.ndarray,
    ) -> np.ndarray:
        """求解产生目标关节力矩所需的肌肉激活。"""

        moment_arms = self._dense_moment_matrix()

        active_gain = self._active_muscle_gain()
        passive_force = self._passive_muscle_force()

        # 只截取当前关心的12个下肢自由度。
        selected_moment_arms = moment_arms[
            :,
            self.dof_ids,
        ]

        # 每条肌肉单位激活可以产生的关节力矩。
        torque_per_excitation = (
            selected_moment_arms.T
            * active_gain[np.newaxis, :]
        )

        passive_torque = (
            selected_moment_arms.T
            @ passive_force
        )

        active_target = (
            desired_torque - passive_torque
        )

        # 正则项抑制不必要的多肌肉同时收缩。
        matrix = np.vstack(
            (
                torque_per_excitation,
                self.regularizer,
            )
        )

        target = np.concatenate(
            (
                active_target,
                np.zeros(
                    self.number_of_muscles,
                    dtype=np.float64,
                ),
            )
        )

        result = lsq_linear(
            matrix,
            target,
            bounds=(
                EXCITATION_MIN,
                EXCITATION_MAX,
            ),
            # 当前问题是小型稠密有界最小二乘，BVLS比默认TRF稳定。
            method="bvls",
            tol=1.0e-6,
            max_iter=200,
        )

        if not result.success:
            raise RuntimeError(
                f"Muscle recruitment failed: {result.message}"
            )

        return result.x

    def _dense_moment_matrix(self) -> np.ndarray:
        """将MuJoCo稀疏肌肉力臂矩阵还原为二维矩阵。"""

        raw = np.asarray(
            self.data.actuator_moment,
            dtype=np.float64,
        )

        # 兼容旧版MuJoCo的稠密存储。
        if raw.size == self.model.nu * self.model.nv:
            return raw.reshape(
                self.model.nu,
                self.model.nv,
            )

        matrix = np.zeros(
            (self.model.nu, self.model.nv),
            dtype=np.float64,
        )

        # MuJoCo 3.6使用逐行稀疏存储。
        for row in range(self.model.nu):
            start = int(self.data.moment_rowadr[row])
            count = int(self.data.moment_rownnz[row])
            end = start + count

            columns = self.data.moment_colind[
                start:end
            ]

            matrix[row, columns] = raw[start:end]

        return matrix

    def _active_muscle_gain(self) -> np.ndarray:
        """计算当前长度和速度下每条肌肉的主动收缩力。"""

        return np.asarray(
            [
                mujoco.mju_muscleGain(
                    self.data.actuator_length[index],
                    self.data.actuator_velocity[index],
                    self.model.actuator_lengthrange[index],
                    self.model.actuator_acc0[index],
                    self.model.actuator_gainprm[
                        index,
                        :9,
                    ].copy(),
                )
                for index in range(self.model.nu)
            ],
            dtype=np.float64,
        )

    def _passive_muscle_force(self) -> np.ndarray:
        """计算即使不激活也会存在的被动肌肉力。"""

        return np.asarray(
            [
                mujoco.mju_muscleBias(
                    self.data.actuator_length[index],
                    self.model.actuator_lengthrange[index],
                    self.model.actuator_acc0[index],
                    self.model.actuator_biasprm[
                        index,
                        :9,
                    ].copy(),
                )
                for index in range(self.model.nu)
            ],
            dtype=np.float64,
        )

    @staticmethod
    def _excitation_to_action(
        excitation: np.ndarray,
    ) -> np.ndarray:
        """把0~1肌肉激励反算为MyoSuite的-1~1动作。"""

        excitation = np.clip(
            excitation,
            EXCITATION_MIN,
            EXCITATION_MAX,
        )

        action = (
            0.5
            + np.log(
                excitation / (1.0 - excitation)
            ) / 5.0
        )

        return np.clip(
            action,
            -1.0,
            1.0,
        ).astype(np.float32)
