"""Kinesis muscle adaptation and physical G-Exo control backend.

Four action values use anatomical signs: hip flexion and knee flexion are
positive.  In physical mode motors act on the articulated exoskeleton and
loads reach the human through thigh/shank cuffs.  Muscle adaptation only uses
the cuff-transmitted generalized force that can be balanced by reachable
muscle activation; it never converts a requested motor torque directly into a
claimed saving.
"""

from __future__ import annotations

from typing import Callable, Dict

import mujoco
import numpy as np
from scipy.optimize import lsq_linear

from RL.env.kinesis.physical_exo import DynamicExoSystem
from RL.env.kinesis.physiology_metrics import compute_physiology_metrics
from RL.env.torque import TorqueActuator


HumanPolicy = Callable[[np.ndarray], np.ndarray]
JOINT_NAMES = (
    "hip_flexion_l",
    "knee_angle_l",
    "hip_flexion_r",
    "knee_angle_r",
)


class MuscleLoadSharing:
    """Compute reachable muscle relaxation under measured external support.

    The optimization variables are next-step muscle activation and the part
    of measured assistance that the human can actually accept without moving
    away from the nominal whole-body generalized force.  Assistance may be
    reduced to zero by the solve; the unapportioned physical interaction then
    remains in the dynamics and can change the trajectory.
    """

    def __init__(
        self,
        model: mujoco.MjModel,
        dof_addresses: np.ndarray,
        *,
        human_actuator_ids: np.ndarray | None = None,
        target_dof_weight: float = 5.0,
        nominal_regularization: float = 0.05,
        assistance_regularization: float = 0.5,
        force_scale_n: float = 100.0,
        torque_scale_nm: float = 10.0,
        assistance_limit_nm: float = 17.0,
    ) -> None:
        self.model = model
        self.dof_addresses = np.asarray(dof_addresses, dtype=np.int32)
        self.human_actuator_ids = (
            np.flatnonzero(model.actuator_actadr >= 0).astype(np.int32)
            if human_actuator_ids is None
            else np.asarray(human_actuator_ids, dtype=np.int32)
        )
        self.activation_addresses = model.actuator_actadr[
            self.human_actuator_ids
        ].astype(np.int32)
        if (
            len(self.human_actuator_ids) != model.na
            or not np.array_equal(
                np.sort(self.activation_addresses), np.arange(model.na)
            )
        ):
            raise ValueError(
                "Each human muscle must own exactly one activation state."
            )
        if min(
            target_dof_weight,
            nominal_regularization,
            assistance_regularization,
            force_scale_n,
            torque_scale_nm,
            assistance_limit_nm,
        ) <= 0.0:
            raise ValueError("Load-sharing scales must be positive.")
        self.target_dof_weight = float(target_dof_weight)
        self.nominal_regularization = float(nominal_regularization)
        self.assistance_regularization = float(assistance_regularization)
        self.force_scale_n = float(force_scale_n)
        self.torque_scale_nm = float(torque_scale_nm)
        self.assistance_limit_nm = float(assistance_limit_nm)

        self.exo_embedding = np.zeros(
            (model.nv, len(self.dof_addresses)), dtype=np.float64
        )
        self.exo_embedding[
            self.dof_addresses, np.arange(len(self.dof_addresses))
        ] = 1.0
        self.dof_weights = self._make_dof_weights()

        self.shadow_activation = np.zeros(model.na, dtype=np.float64)
        # One-step no-assist activation from the same physical state.  Unlike
        # shadow_activation, this reference cannot accumulate integration drift.
        self.nominal_activation = np.zeros(model.na, dtype=np.float64)
        self.desired_activation = np.zeros(model.na, dtype=np.float64)
        self.target_muscle_mask = np.ones(
            len(self.human_actuator_ids), dtype=bool
        )
        self.requested_assistance = np.zeros(4, dtype=np.float64)
        self.supported_assistance = np.zeros(4, dtype=np.float64)
        self.predicted_balance_error = np.zeros(model.nv, dtype=np.float64)
        self.solve_failed = False
        self.solve_failure_reason = ""

    def reset(self, data: mujoco.MjData) -> None:
        self.shadow_activation[:] = data.act
        self.nominal_activation[:] = data.act
        self.desired_activation[:] = data.act
        self.requested_assistance.fill(0.0)
        self.supported_assistance.fill(0.0)
        self.predicted_balance_error.fill(0.0)
        moment = np.asarray(data.actuator_moment, dtype=np.float64)[
            self.human_actuator_ids
        ]
        self.target_muscle_mask = self._target_muscle_mask(moment)
        self.solve_failed = False
        self.solve_failure_reason = ""

    def compute_excitation(
        self,
        data: mujoco.MjData,
        nominal_excitation: np.ndarray,
        exo_torque: np.ndarray,
    ) -> np.ndarray:
        """Solve reachable next activation and accepted support together."""

        nominal_excitation = np.clip(
            np.asarray(nominal_excitation, dtype=np.float64), 0.0, 1.0
        )
        if nominal_excitation.shape != (len(self.human_actuator_ids),):
            raise ValueError("Nominal excitation has the wrong muscle count.")
        requested = np.clip(
            np.asarray(exo_torque, dtype=np.float64),
            -self.assistance_limit_nm,
            self.assistance_limit_nm,
        )
        if requested.shape != (4,):
            raise ValueError("Assistance torque must have shape (4,).")
        self.requested_assistance[:] = requested
        self.solve_failed = False
        self.solve_failure_reason = ""

        nominal_next = self._next_activation(data, nominal_excitation)
        self.nominal_activation[:] = nominal_next
        if np.allclose(requested, 0.0, atol=1.0e-12):
            self.desired_activation[:] = nominal_next
            self.supported_assistance.fill(0.0)
            self.predicted_balance_error.fill(0.0)
            return nominal_excitation.astype(np.float32)

        bias, gain = self._force_terms(data)
        moment = np.asarray(data.actuator_moment, dtype=np.float64)[
            self.human_actuator_ids
        ]
        self.target_muscle_mask = self._target_muscle_mask(moment)
        activation_matrix = moment.T * gain
        passive_torque = moment.T @ bias
        nominal_torque = passive_torque + activation_matrix @ nominal_next
        lower, upper = self._reachable_activation_bounds(data)

        variable = (
            np.any(
                np.abs(moment[:, self.dof_addresses]) > 1.0e-8,
                axis=1,
            )
            & (np.abs(gain) > 1.0e-8)
            & (upper - lower > 1.0e-8)
        )
        if not np.any(variable):
            return self._fallback(nominal_excitation, "no reachable muscles")

        variable_matrix = activation_matrix[:, variable]
        fixed_torque = activation_matrix[:, ~variable] @ nominal_next[
            ~variable
        ]
        target = nominal_torque - passive_torque - fixed_torque
        variable_count = int(np.sum(variable))
        total_count = variable_count + 4

        dynamics_matrix = np.zeros(
            (self.model.nv, total_count), dtype=np.float64
        )
        dynamics_matrix[:, :variable_count] = variable_matrix
        dynamics_matrix[:, variable_count:] = self.exo_embedding
        system_blocks = [self.dof_weights[:, None] * dynamics_matrix]
        target_blocks = [self.dof_weights * target]

        nominal_block = np.zeros(
            (variable_count, total_count), dtype=np.float64
        )
        nominal_block[:, :variable_count] = (
            np.sqrt(self.nominal_regularization)
            * np.eye(variable_count)
        )
        nominal_target = np.clip(
            nominal_next[variable], lower[variable], upper[variable]
        )
        system_blocks.append(nominal_block)
        target_blocks.append(
            np.sqrt(self.nominal_regularization) * nominal_target
        )

        assistance_block = np.zeros((4, total_count), dtype=np.float64)
        assistance_block[:, variable_count:] = (
            np.sqrt(self.assistance_regularization)
            / self.torque_scale_nm
            * np.eye(4)
        )
        system_blocks.append(assistance_block)
        target_blocks.append(
            np.sqrt(self.assistance_regularization)
            / self.torque_scale_nm
            * requested
        )

        tau_lower = np.minimum(requested, 0.0)
        tau_upper = np.maximum(requested, 0.0)
        bounds_lower = np.concatenate((lower[variable], tau_lower))
        bounds_upper = np.concatenate((upper[variable], tau_upper))
        matrix = np.vstack(system_blocks)
        right_hand_side = np.concatenate(target_blocks)
        if not (
            np.all(np.isfinite(matrix))
            and np.all(np.isfinite(right_hand_side))
        ):
            return self._fallback(nominal_excitation, "non-finite solver input")

        try:
            result = lsq_linear(
                matrix,
                right_hand_side,
                bounds=(bounds_lower, bounds_upper),
                method="bvls",
                tol=1.0e-7,
                max_iter=200,
            )
        except (np.linalg.LinAlgError, ValueError) as error:
            return self._fallback(nominal_excitation, str(error))
        if not result.success or not np.all(np.isfinite(result.x)):
            return self._fallback(nominal_excitation, str(result.message))

        self.desired_activation[:] = nominal_next
        self.desired_activation[variable] = result.x[:variable_count]
        self.supported_assistance[:] = result.x[variable_count:]
        predicted_torque = (
            passive_torque
            + activation_matrix @ self.desired_activation
            + self.exo_embedding @ self.supported_assistance
        )
        self.predicted_balance_error[:] = predicted_torque - nominal_torque
        return self._activation_to_excitation(data)

    def advance_shadow(
        self, nominal_excitation: np.ndarray, dt: float
    ) -> None:
        for local_id, actuator_id in enumerate(self.human_actuator_ids):
            activation_id = self.activation_addresses[local_id]
            derivative = mujoco.mju_muscleDynamics(
                float(nominal_excitation[local_id]),
                float(self.shadow_activation[activation_id]),
                self.model.actuator_dynprm[actuator_id, :3],
            )
            self.shadow_activation[activation_id] = np.clip(
                self.shadow_activation[activation_id] + dt * derivative,
                0.0,
                1.0,
            )

    def diagnostics(
        self, data: mujoco.MjData, exo_torque: np.ndarray
    ) -> Dict[str, np.ndarray | float]:
        bias, gain = self._force_terms(data)
        moment = np.asarray(data.actuator_moment, dtype=np.float64)[
            self.human_actuator_ids
        ]
        # Preserve the legacy shadow scalars used by Reward.  The new local
        # physiology diagnostics use the one-step same-state reference below.
        baseline_force = bias + gain * self.shadow_activation
        baseline_torque = moment.T @ baseline_force
        physiology_baseline_force = bias + gain * self.nominal_activation
        actual_force = np.asarray(data.actuator_force, dtype=np.float64)[
            self.human_actuator_ids
        ]
        actual_torque = moment.T @ actual_force
        target_mask = self._target_muscle_mask(moment)
        self.target_muscle_mask = target_mask
        target_moment = moment[:, self.dof_addresses]
        actual_effort = np.sum(
            np.abs(target_moment * actual_force[:, None]), axis=1
        )
        baseline_effort = np.sum(
            np.abs(target_moment * baseline_force[:, None]), axis=1
        )
        target_activation_addresses = self.activation_addresses[target_mask]
        actual_activation_cost = float(
            np.mean(np.square(data.act[target_activation_addresses]))
        )
        baseline_activation_cost = float(
            np.mean(
                np.square(
                    self.shadow_activation[target_activation_addresses]
                )
            )
        )
        physiology = compute_physiology_metrics(
            activation=np.asarray(data.act, dtype=np.float64)[
                self.activation_addresses
            ],
            baseline_activation=self.nominal_activation[
                self.activation_addresses
            ],
            muscle_force_n=actual_force,
            baseline_muscle_force_n=physiology_baseline_force,
            target_moment_arm_m=target_moment,
            target_mask=target_mask,
        )
        # Actual balance uses the measured post-step cuff assistance.  The
        # solver's pre-step accepted value remains a separate diagnostic.
        measured_assistance = np.asarray(exo_torque, dtype=np.float64)
        accepted = self.exo_embedding @ measured_assistance
        balance = actual_torque + accepted - baseline_torque
        rotational_mask = ~self._translation_mask()
        other_rotational = rotational_mask.copy()
        other_rotational[self.dof_addresses] = False
        translation = self._translation_mask()
        return {
            "baseline_muscle_torque": baseline_torque[
                self.dof_addresses
            ].copy(),
            "target_muscle_mask": target_mask.copy(),
            "target_muscle_count": float(np.sum(target_mask)),
            "target_muscle_activation": physiology.target_activation,
            "baseline_target_muscle_activation": (
                physiology.baseline_target_activation
            ),
            "target_muscle_force_n": physiology.target_muscle_force_n,
            "baseline_target_muscle_force_n": (
                physiology.baseline_target_muscle_force_n
            ),
            "target_joint_torque_contribution_nm": (
                physiology.target_joint_torque_contribution_nm
            ),
            "baseline_target_joint_torque_contribution_nm": (
                physiology.baseline_target_joint_torque_contribution_nm
            ),
            "target_muscle_effort_nm": physiology.muscle_effort_nm,
            "baseline_target_muscle_effort_nm": (
                physiology.baseline_muscle_effort_nm
            ),
            "target_activation_cost": actual_activation_cost,
            "baseline_target_activation_cost": baseline_activation_cost,
            "muscle_effort_torque_cost": float(
                np.mean(actual_effort[target_mask])
            ),
            "baseline_muscle_effort_torque_cost": float(
                np.mean(baseline_effort[target_mask])
            ),
            "co_contraction_abs_nm": physiology.co_contraction_abs_nm,
            "baseline_co_contraction_abs_nm": (
                physiology.baseline_co_contraction_abs_nm
            ),
            "co_contraction_index": physiology.co_contraction_index,
            "baseline_co_contraction_index": (
                physiology.baseline_co_contraction_index
            ),
            "co_contraction_excess": physiology.co_contraction_excess,
            "activation_overload": physiology.activation_overload,
            "activation_overload_topk": (
                physiology.activation_overload_topk
            ),
            "net_joint_torque_cost": float(
                np.mean(np.abs(actual_torque[self.dof_addresses]))
            ),
            "baseline_net_joint_torque_cost": float(
                np.mean(np.abs(baseline_torque[self.dof_addresses]))
            ),
            "torque_balance_error": balance[self.dof_addresses].copy(),
            "predicted_balance_error": self.predicted_balance_error[
                self.dof_addresses
            ].copy(),
            "supported_assistance_torque": self.supported_assistance.copy(),
            "unsupported_assistance_torque": (
                np.asarray(exo_torque, dtype=np.float64)
                - self.supported_assistance
            ),
            "full_balance_rms": float(
                np.sqrt(np.mean(np.square(self.dof_weights * balance)))
            ),
            "predicted_full_balance_rms": float(
                np.sqrt(
                    np.mean(
                        np.square(
                            self.dof_weights
                            * self.predicted_balance_error
                        )
                    )
                )
            ),
            "other_rotational_residual_nm": float(
                np.max(np.abs(balance[other_rotational]), initial=0.0)
            ),
            "translation_residual_n": float(
                np.max(np.abs(balance[translation]), initial=0.0)
            ),
        }

    def _target_muscle_mask(self, moment: np.ndarray) -> np.ndarray:
        """Select muscles with a non-zero moment arm at target joints."""

        mask = np.any(
            np.abs(moment[:, self.dof_addresses]) > 1.0e-8,
            axis=1,
        )
        if not np.any(mask):
            raise RuntimeError(
                "No human muscle crosses the four target joints."
            )
        return mask

    def _fallback(
        self, nominal_excitation: np.ndarray, reason: str
    ) -> np.ndarray:
        self.solve_failed = True
        self.solve_failure_reason = reason
        self.supported_assistance.fill(0.0)
        self.predicted_balance_error.fill(0.0)
        return nominal_excitation.astype(np.float32)

    def _force_terms(
        self, data: mujoco.MjData
    ) -> tuple[np.ndarray, np.ndarray]:
        count = len(self.human_actuator_ids)
        bias = np.empty(count, dtype=np.float64)
        gain = np.empty(count, dtype=np.float64)
        for local_id, actuator_id in enumerate(self.human_actuator_ids):
            length = data.actuator_length[actuator_id]
            length_range = self.model.actuator_lengthrange[actuator_id]
            acceleration = self.model.actuator_acc0[actuator_id]
            bias[local_id] = mujoco.mju_muscleBias(
                length,
                length_range,
                acceleration,
                self.model.actuator_biasprm[actuator_id, :9],
            )
            gain[local_id] = mujoco.mju_muscleGain(
                length,
                data.actuator_velocity[actuator_id],
                length_range,
                acceleration,
                self.model.actuator_gainprm[actuator_id, :9],
            )
        return bias, gain

    def _next_activation(
        self, data: mujoco.MjData, excitation: np.ndarray
    ) -> np.ndarray:
        result = np.asarray(data.act, dtype=np.float64).copy()
        dt = float(self.model.opt.timestep)
        for local_id, actuator_id in enumerate(self.human_actuator_ids):
            activation_id = self.activation_addresses[local_id]
            derivative = mujoco.mju_muscleDynamics(
                float(excitation[local_id]),
                float(data.act[activation_id]),
                self.model.actuator_dynprm[actuator_id, :3],
            )
            result[activation_id] += dt * derivative
        return np.clip(result, 0.0, 1.0)

    def _reachable_activation_bounds(
        self, data: mujoco.MjData
    ) -> tuple[np.ndarray, np.ndarray]:
        count = len(self.human_actuator_ids)
        at_zero = self._next_activation(data, np.zeros(count))
        at_full = self._next_activation(data, np.ones(count))
        return np.minimum(at_zero, at_full), np.maximum(at_zero, at_full)

    def _activation_to_excitation(
        self, data: mujoco.MjData
    ) -> np.ndarray:
        excitation = np.empty(
            len(self.human_actuator_ids), dtype=np.float32
        )
        dt = float(self.model.opt.timestep)
        for local_id, actuator_id in enumerate(self.human_actuator_ids):
            activation_id = self.activation_addresses[local_id]
            current = float(data.act[activation_id])
            target = float(self.desired_activation[activation_id])
            parameters = self.model.actuator_dynprm[actuator_id, :3]

            def next_activation(control: float) -> float:
                return current + dt * mujoco.mju_muscleDynamics(
                    control, current, parameters
                )

            low, high = 0.0, 1.0
            low_value = next_activation(low)
            high_value = next_activation(high)
            if target <= low_value:
                excitation[local_id] = low
                continue
            if target >= high_value:
                excitation[local_id] = high
                continue
            for _ in range(14):
                middle = 0.5 * (low + high)
                if next_activation(middle) < target:
                    low = middle
                else:
                    high = middle
            excitation[local_id] = 0.5 * (low + high)
        return excitation

    def _translation_mask(self) -> np.ndarray:
        mask = np.zeros(self.model.nv, dtype=bool)
        for dof_id in range(self.model.nv):
            joint_id = int(self.model.dof_jntid[dof_id])
            joint_type = int(self.model.jnt_type[joint_id])
            if joint_type == int(mujoco.mjtJoint.mjJNT_SLIDE):
                mask[dof_id] = True
            elif joint_type == int(mujoco.mjtJoint.mjJNT_FREE):
                mask[dof_id] = (
                    dof_id - int(self.model.jnt_dofadr[joint_id]) < 3
                )
        return mask

    def _make_dof_weights(self) -> np.ndarray:
        translation = self._translation_mask()
        weights = np.where(
            translation,
            1.0 / self.force_scale_n,
            1.0 / self.torque_scale_nm,
        )
        weights[self.dof_addresses] *= self.target_dof_weight
        return weights


class AssistBackend:
    """Advance one frozen Kinesis human with an optional physical G-Exo."""

    def __init__(
        self,
        environment,
        *,
        exo_control_dt: float = 0.02,
        torque_limit_nm: float = 17.0,
        torque_rate_limit_nm_s: float = 50.0,
        human_strength: float = 1.0,
        load_sharing: bool = True,
        physical_exo: DynamicExoSystem | None = None,
    ) -> None:
        self.env = environment
        self.physical_exo = physical_exo
        self.model = (
            physical_exo.model if physical_exo is not None else environment.mj_model
        )
        self.data = (
            physical_exo.data if physical_exo is not None else environment.mj_data
        )
        self.human_nu = (
            physical_exo.human_nu if physical_exo is not None else self.model.nu
        )
        self.human_actuator_ids = np.arange(self.human_nu, dtype=np.int32)
        self.human_control_mode = environment.control_mode
        if self.human_control_mode not in ("direct", "PD"):
            raise ValueError("Kinesis control mode must be direct or PD.")
        if physical_exo is not None and self.human_control_mode != "direct":
            raise ValueError("Physical G-Exo currently requires direct muscle control.")
        if not 0.0 < human_strength <= 1.0:
            raise ValueError("human_strength must be in (0, 1].")

        self.human_strength = float(human_strength)
        self.sim_dt = float(self.model.opt.timestep)
        self.human_substeps = self._integer_ratio(
            float(environment.dt), self.sim_dt, "human control period"
        )
        self.exo_substeps = self._integer_ratio(
            float(exo_control_dt), self.sim_dt, "exo control period"
        )
        self.qpos_addresses = np.empty(4, dtype=np.int32)
        self.dof_addresses = np.empty(4, dtype=np.int32)
        for index, name in enumerate(JOINT_NAMES):
            joint_id = mujoco.mj_name2id(
                self.model, mujoco.mjtObj.mjOBJ_JOINT, name
            )
            if joint_id < 0:
                raise ValueError(f"Missing Kinesis joint: {name}")
            self.qpos_addresses[index] = self.model.jnt_qposadr[joint_id]
            self.dof_addresses[index] = self.model.jnt_dofadr[joint_id]

        self.torque_limit_nm = np.full(4, torque_limit_nm, dtype=np.float32)
        self.actuator = TorqueActuator(
            torque_limit_nm=self.torque_limit_nm,
            torque_rate_limit_nm_s=np.full(
                4, torque_rate_limit_nm_s, dtype=np.float32
            ),
            control_dt=exo_control_dt,
        )
        self.load_sharing_enabled = bool(load_sharing)
        self.load_sharing = MuscleLoadSharing(
            self.model,
            self.dof_addresses,
            human_actuator_ids=self.human_actuator_ids,
            assistance_limit_nm=torque_limit_nm,
        )
        self.observation = None
        self.human_action = np.zeros(self.human_nu, dtype=np.float32)
        self.nominal_excitation = np.zeros(self.human_nu, dtype=np.float32)
        self.exo_torque = np.zeros(4, dtype=np.float32)
        self.interaction_torque = np.zeros(4, dtype=np.float64)
        self.motor_assistance_torque = np.zeros(4, dtype=np.float64)
        self.physics_tick = 0
        self.need_human_action = True
        self.energy_rewards: list[float] = []
        self.done = False
        self._reset_primed = False

    def reset(self, *, seed: int = 0, options=None) -> np.ndarray:
        # Kinesis' first reset after construction leaves a one-off internal
        # state.  Prime it once so baseline, evaluation and PPO all start from
        # the reproducible reset path used by subsequent episodes.
        if not self._reset_primed:
            self._reset_simulation(seed, options)
            self._reset_primed = True
        observation = self._reset_simulation(seed, options)
        self.actuator.reset()
        self.data.qfrc_applied.fill(0.0)
        self.observation = np.asarray(observation, dtype=np.float32)
        self.human_action.fill(0.0)
        self.nominal_excitation.fill(0.0)
        self.exo_torque.fill(0.0)
        self.interaction_torque.fill(0.0)
        self.motor_assistance_torque.fill(0.0)
        self.load_sharing.reset(self.data)
        self.physics_tick = 0
        self.need_human_action = True
        self.energy_rewards.clear()
        self.done = False
        return self.observation.copy()

    def _reset_simulation(self, seed: int, options) -> np.ndarray:
        if self.physical_exo is None:
            mujoco.mj_resetData(self.model, self.data)
            observation, _ = self.env.reset(seed=seed, options=options)
        else:
            observation = self.physical_exo.reset(seed=seed, options=options)
            self.model = self.physical_exo.model
            self.data = self.physical_exo.data
        return np.asarray(observation, dtype=np.float32)

    def step(
        self,
        target_exo_torque_nm: np.ndarray,
        human_policy: HumanPolicy,
    ) -> Dict[str, object]:
        if self.done:
            raise RuntimeError("Episode ended; call reset() before step().")
        target = self._vector(target_exo_torque_nm, 4, "target torque")
        command = self.actuator.process(target / self.torque_limit_nm)
        reward = 0.0
        terminated = False
        truncated = False
        failure_reason = ""

        for _ in range(self.exo_substeps):
            if self.need_human_action:
                action = human_policy(self.observation.copy())
                self.human_action = np.clip(
                    self._vector(action, self.human_nu, "human action"),
                    -1.0,
                    1.0,
                )
                self.need_human_action = False

            nominal = np.clip(
                0.5 * (self.human_action + 1.0) * self.human_strength,
                0.0,
                1.0,
            )
            self.nominal_excitation[:] = nominal
            self.load_sharing.advance_shadow(nominal, self.sim_dt)

            if self.physical_exo is not None:
                self.motor_assistance_torque[:] = (
                    self.physical_exo.motor_induced_interaction_torque(
                        command
                    )
                )
                adaptation_input = self.motor_assistance_torque
            else:
                adaptation_input = command

            excitation = (
                self.load_sharing.compute_excitation(
                    self.data, nominal, adaptation_input
                )
                if self.load_sharing_enabled
                else nominal.astype(np.float32)
            )
            if self.load_sharing.solve_failed:
                failure_reason = self.load_sharing.solve_failure_reason
                terminated = True
                self.done = True
                break

            self.data.ctrl[self.human_actuator_ids] = excitation
            self.data.qfrc_applied[self.dof_addresses] = 0.0
            if self.physical_exo is not None:
                self.physical_exo.set_motor_torque(command)
            else:
                self.data.qfrc_applied[self.dof_addresses] = (
                    self.load_sharing.supported_assistance
                    if self.load_sharing_enabled
                    else command
                )

            mujoco.mj_step(self.model, self.data)
            mujoco.mj_forward(self.model, self.data)
            self.energy_rewards.append(
                float(self.env.compute_energy_reward(excitation))
            )
            self.physics_tick += 1
            if self.physics_tick % self.human_substeps == 0:
                self.env.cur_t += 1
                self.observation = np.asarray(
                    self.env.compute_observations(), dtype=np.float32
                )
                self.env.curr_power_usage = self.energy_rewards
                reward = float(self.env.compute_reward(self.human_action))
                self.energy_rewards = []
                terminated, truncated = self.env.compute_reset()
                self.need_human_action = True
                self.done = bool(terminated or truncated)
                if self.done:
                    break

        if self.physical_exo is not None:
            self.exo_torque[:] = self.physical_exo.measured_motor_torque()
            self.motor_assistance_torque[:] = (
                self.physical_exo.motor_induced_interaction_torque(
                    self.exo_torque
                )
            )
            self.interaction_torque[:] = (
                self.physical_exo.measured_interaction_torque()
            )
            joint_position = self.data.qpos[
                self.physical_exo.exo_qpos_addresses
            ].copy()
            joint_velocity = self.data.qvel[
                self.physical_exo.exo_dof_addresses
            ].copy()
            cuff_force = self.physical_exo.cuff_force_norms()
            cuff_error = self.physical_exo.cuff_error_norms()
            constraint_error = self.physical_exo.constraint_error_norm()
        else:
            self.exo_torque[:] = (
                self.load_sharing.supported_assistance
                if self.load_sharing_enabled
                else command
            )
            self.interaction_torque[:] = self.exo_torque
            self.motor_assistance_torque[:] = self.exo_torque
            joint_position = self.data.qpos[self.qpos_addresses].copy()
            joint_velocity = self.data.qvel[self.dof_addresses].copy()
            cuff_force = np.zeros(4)
            cuff_error = np.zeros(4)
            constraint_error = 0.0

        moment = np.asarray(self.data.actuator_moment)[
            self.human_actuator_ids
        ]
        muscle_generalized = moment.T @ np.asarray(
            self.data.actuator_force
        )[self.human_actuator_ids]
        muscle_torque = muscle_generalized[self.dof_addresses].copy()
        diagnostics = self.load_sharing.diagnostics(
            self.data, self.motor_assistance_torque
        )
        joint_power = self.exo_torque * joint_velocity
        return {
            "time": float(self.data.time),
            "observation": self.observation.copy(),
            "joint_position": joint_position,
            "joint_velocity": joint_velocity,
            "muscle_activation": self.data.act.copy(),
            "shadow_activation": self.load_sharing.shadow_activation.copy(),
            "muscle_torque": muscle_torque,
            "exo_torque": self.exo_torque.copy(),
            "interaction_torque": self.interaction_torque.copy(),
            "motor_assistance_torque": (
                self.motor_assistance_torque.copy()
            ),
            "exo_power": float(np.sum(joint_power)),
            "exo_joint_power": joint_power.copy(),
            "cuff_force_n": cuff_force,
            "cuff_error_m": cuff_error,
            "cuff_constraint_error_m": float(constraint_error),
            "mean_excitation": float(np.mean(self.data.ctrl[: self.human_nu])),
            "nominal_excitation": self.nominal_excitation.copy(),
            **diagnostics,
            "reward": reward,
            "terminated": bool(terminated),
            "truncated": bool(truncated),
            "load_sharing_failed": bool(failure_reason),
            "load_sharing_failure_reason": failure_reason,
        }

    def baseline_muscle_torque(self) -> np.ndarray:
        return np.asarray(
            self.load_sharing.diagnostics(
                self.data, np.zeros(4, dtype=np.float32)
            )["baseline_muscle_torque"]
        )

    def close(self) -> None:
        self.data.qfrc_applied.fill(0.0)
        if self.physical_exo is not None:
            self.physical_exo.close()
        self.env.close()

    @staticmethod
    def _integer_ratio(period: float, sim_dt: float, name: str) -> int:
        ratio = period / sim_dt
        rounded = int(round(ratio))
        if rounded < 1 or not np.isclose(ratio, rounded, atol=1.0e-8):
            raise ValueError(f"{name} must be an integer multiple of sim dt.")
        return rounded

    @staticmethod
    def _vector(value, size: int, name: str) -> np.ndarray:
        array = np.asarray(value, dtype=np.float32)
        if array.shape != (size,) or not np.all(np.isfinite(array)):
            raise ValueError(f"{name} must be a finite vector of shape ({size},).")
        return array


__all__ = ["AssistBackend", "JOINT_NAMES", "MuscleLoadSharing"]
