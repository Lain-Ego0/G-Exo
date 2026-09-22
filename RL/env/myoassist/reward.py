"""Reward V1 for four-joint assistance on the MyoAssist physical plant."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np

from RL.env.myoassist.baseline import MyoAssistBaseline
from RL.env.myoassist.motion_reference import MyoAssistMotionReference
from RL.env.myoassist.muscle_adapter import target_activation_costs
from RL.optimization.contracts import MuscleSnapshot


def physiology_costs(
    snapshot: MuscleSnapshot,
    baseline: MyoAssistBaseline,
) -> dict[str, np.ndarray | float]:
    """Compute the shared naked/assisted physiological accounting terms."""

    force = snapshot.resolved_muscle_force_n()
    contribution = snapshot.moment_arm_m * force[:, None]
    human_joint_torque = np.sum(contribution, axis=0)
    gross_joint_load = np.sum(np.abs(contribution), axis=0)
    return {
        "activation_cost": float(np.mean(np.square(snapshot.activation))),
        "target_activation_cost": target_activation_costs(snapshot),
        "human_torque_cost": float(
            np.mean(
                np.square(human_joint_torque / baseline.human_joint_scale_nm)
            )
        ),
        "gross_cost": float(
            np.mean(gross_joint_load / baseline.gross_joint_scale_nm)
        ),
        "human_joint_torque_nm": human_joint_torque,
        "gross_joint_load_nm": gross_joint_load,
    }


@dataclass(frozen=True)
class RewardConfig:
    physiology_reference_mode: str = "speed_cycle_target_side_v2"
    motion_alignment_mode: str = "nearest_cycle_state_v1"
    effort_weight: float = 1.0
    speed_weight: float = 1.0
    upright_weight: float = 1.0
    movement_weight: float = 0.5
    gross_weight: float = 0.25
    torque_usage_weight: float = 0.01
    torque_weight: float = 1.0
    jerk_weight: float = 0.002
    power_weight: float = 0.01
    fall_weight: float = 1.0
    alive_reward: float = 0.005
    activation_weight: float = 0.6
    activation_side_degradation_weight: float = 1.0
    saving_clip: float = 5.0
    gross_tolerance: float = 0.1
    termination_absorbing_cost: float = 0.05
    termination_discount: float = 0.99
    positive_power_free_w: float = 20.0
    positive_power_scale_w: float = 50.0
    torque_soft_threshold_nm: float = 6.5
    torque_termination_threshold_nm: float = 8.0
    torque_limit_nm: np.ndarray = field(
        default_factory=lambda: np.full(4, 8.0, dtype=np.float64)
    )
    jerk_scale_nm: np.ndarray = field(
        default_factory=lambda: np.full(4, 4.0, dtype=np.float64)
    )


class MyoAssistReward:
    def __init__(
        self,
        baseline: MyoAssistBaseline,
        motion_reference: MyoAssistMotionReference,
        config: RewardConfig = RewardConfig(),
    ) -> None:
        self.baseline = baseline
        self.motion_reference = motion_reference
        self.config = config
        self.torque_limit = _positive_vector(config.torque_limit_nm, "torque_limit_nm")
        self.jerk_scale = _positive_vector(config.jerk_scale_nm, "jerk_scale_nm")
        self.torque_soft_threshold_nm = float(config.torque_soft_threshold_nm)
        self.torque_termination_threshold_nm = float(
            config.torque_termination_threshold_nm
        )
        if not (
            0.0
            < self.torque_soft_threshold_nm
            < self.torque_termination_threshold_nm
            <= float(np.min(self.torque_limit))
        ):
            raise ValueError(
                "Torque thresholds must satisfy 0 < soft < termination <= hard limit."
            )
        if not 0.0 <= config.activation_weight <= 1.0:
            raise ValueError("activation_weight must be in [0, 1].")
        if config.activation_side_degradation_weight < 0.0:
            raise ValueError(
                "activation_side_degradation_weight must be non-negative."
            )
        if config.termination_absorbing_cost < 0.0:
            raise ValueError("termination_absorbing_cost must be non-negative.")
        if not 0.0 < config.termination_discount <= 1.0:
            raise ValueError("termination_discount must be in (0, 1].")
        self.reset()

    def reset(self) -> None:
        self.previous_torque = np.zeros(4, dtype=np.float64)
        self.penultimate_torque = np.zeros(4, dtype=np.float64)
        self._physiology_window = _CausalCycleWindow()

    def prime(
        self,
        snapshot: MuscleSnapshot,
        gait_period_steps: float,
    ) -> None:
        """Seed the causal cycle window during zero-assist preroll."""

        self._validate_snapshot(snapshot)
        self._update_cycle_costs(
            physiology_costs(snapshot, self.baseline),
            gait_period_steps,
        )

    def compute(
        self,
        *,
        snapshot: MuscleSnapshot,
        gait_phase: float,
        gait_period_steps: float,
        filtered_target_speed_m_s: float,
        filtered_forward_speed_m_s: float,
        pelvis_height_m: float,
        pelvis_pitch_rad: float,
        joint_q_rad: np.ndarray,
        joint_dq_rad_s: np.ndarray,
        exo_torque_nm: np.ndarray,
        terminated: bool,
        remaining_steps: int = 0,
    ) -> tuple[float, dict[str, float]]:
        self._validate_snapshot(snapshot)
        q = _vector(joint_q_rad, "joint_q_rad")
        dq = _vector(joint_dq_rad_s, "joint_dq_rad_s")
        torque = _vector(exo_torque_nm, "exo_torque_nm")
        costs = physiology_costs(snapshot, self.baseline)
        human_joint_torque = np.asarray(costs["human_joint_torque_nm"])
        activation_cost = float(costs["activation_cost"])
        target_activation_cost = np.asarray(costs["target_activation_cost"])
        human_torque_cost = float(costs["human_torque_cost"])
        gross_cost = float(costs["gross_cost"])
        cycle_costs = self._update_cycle_costs(costs, gait_period_steps)
        reference = self.baseline.cycle_average_at_speed(
            filtered_target_speed_m_s,
        )
        motion = self.motion_reference.nearest_at_speed(
            filtered_target_speed_m_s,
            q,
        )
        global_activation_saving = np.clip(
            (reference.activation_mean - cycle_costs["activation"])
            / max(abs(reference.activation_mean), 1.0e-6),
            -self.config.saving_clip,
            self.config.saving_clip,
        )
        activation_saving_by_side = np.clip(
            (
                reference.target_activation_mean
                - cycle_costs["target_activation"]
            )
            / np.maximum(np.abs(reference.target_activation_mean), 1.0e-6),
            -self.config.saving_clip,
            self.config.saving_clip,
        )
        activation_saving_mean = float(np.mean(activation_saving_by_side))
        activation_side_degradation = float(
            np.mean(np.maximum(-activation_saving_by_side, 0.0))
        )
        activation_saving = (
            activation_saving_mean
            - self.config.activation_side_degradation_weight
            * activation_side_degradation
        )
        torque_saving = np.clip(
            (reference.human_torque_mean - cycle_costs["human_torque"])
            / max(abs(reference.human_torque_mean), 1.0e-6),
            -self.config.saving_clip,
            self.config.saving_clip,
        )
        saving = (
            self.config.activation_weight * activation_saving
            + (1.0 - self.config.activation_weight) * torque_saving
        )

        speed_excess = max(
            0.0,
            abs(
                float(filtered_forward_speed_m_s)
                - float(filtered_target_speed_m_s)
            )
            - reference.speed_free_error_m_s,
        ) / reference.speed_transition_m_s
        height_excess = max(
            0.0,
            self.baseline.minimum_pelvis_height_m - float(pelvis_height_m),
        ) / self.baseline.pelvis_height_transition_m
        pitch_excess = max(
            0.0,
            abs(float(pelvis_pitch_rad)) - self.baseline.pelvis_pitch_free_rad,
        ) / self.baseline.pelvis_pitch_transition_rad
        free_lower = (
            self.baseline.joint_lower_rad
            + self.baseline.joint_limit_margin_rad
        )
        free_upper = (
            self.baseline.joint_upper_rad
            - self.baseline.joint_limit_margin_rad
        )
        joint_excess = float(
            np.max(
                np.maximum(
                    np.maximum(free_lower - q, q - free_upper),
                    0.0,
                )
                / self.baseline.joint_limit_transition_rad
            )
        )
        upright_excess = max(height_excess, pitch_excess, joint_excess)
        movement_rmse = float(
            np.sqrt(np.mean(np.square(q - motion.joint_q_mean)))
        )
        movement_z_rms = float(
            np.sqrt(
                np.mean(
                    np.square((q - motion.joint_q_mean) / motion.joint_q_scale)
                )
            )
        )
        movement_excess = max(
            0.0,
            movement_z_rms - motion.movement_free_z,
        ) / motion.movement_transition_z
        gate = (
            np.clip(1.0 - speed_excess, 0.0, 1.0)
            * np.clip(1.0 - upright_excess, 0.0, 1.0)
            * np.clip(1.0 - movement_excess, 0.0, 1.0)
        )
        effort = float(gate * max(saving, 0.0) + min(saving, 0.0))

        gross_threshold = reference.gross_median * (
            1.0 + self.config.gross_tolerance
        )
        gross_excess = max(
            0.0,
            (gross_cost - gross_threshold) / reference.gross_scale,
        )
        max_absolute_torque = float(np.max(np.abs(torque)))
        torque_usage_cost = float(
            np.mean(np.square(torque / self.torque_soft_threshold_nm))
        )
        torque_overload = max(
            0.0,
            (max_absolute_torque - self.torque_soft_threshold_nm)
            / (
                self.torque_termination_threshold_nm
                - self.torque_soft_threshold_nm
            ),
        )
        torque_cost = float(torque_overload**2)
        second_difference = (
            torque - 2.0 * self.previous_torque + self.penultimate_torque
        )
        jerk_cost = float(np.mean(np.square(second_difference / self.jerk_scale)))
        positive_power = float(np.sum(np.maximum(torque * dq, 0.0)))
        power_excess = max(
            0.0,
            positive_power - self.config.positive_power_free_w,
        ) / self.config.positive_power_scale_w

        termination_penalty = 0.0
        if terminated:
            remaining = max(int(remaining_steps), 0)
            discount = self.config.termination_discount
            if discount == 1.0:
                absorbing_tail = self.config.termination_absorbing_cost * remaining
            else:
                absorbing_tail = self.config.termination_absorbing_cost * (
                    1.0 - discount**remaining
                ) / (1.0 - discount)
            termination_penalty = -self.config.fall_weight - absorbing_tail

        components = {
            "effort": self.config.effort_weight * effort,
            "alive": self.config.alive_reward,
            "speed_penalty": -self.config.speed_weight * speed_excess**2,
            "upright_penalty": -self.config.upright_weight * upright_excess**2,
            "movement_penalty": (
                -self.config.movement_weight * movement_excess**2
            ),
            "gross_penalty": -self.config.gross_weight * gross_excess**2,
            "torque_usage_penalty": (
                -self.config.torque_usage_weight * torque_usage_cost
            ),
            "torque_overload_penalty": -self.config.torque_weight * torque_cost,
            "jerk_penalty": -self.config.jerk_weight * jerk_cost,
            "power_penalty": -self.config.power_weight * power_excess**2,
            "termination_penalty": termination_penalty,
        }
        total = float(sum(components.values()))
        diagnostics = {
            **components,
            "total": total,
            "gait_phase": float(gait_phase % 1.0),
            "activation_cost": activation_cost,
            "target_activation_cost_left": float(target_activation_cost[0]),
            "target_activation_cost_right": float(target_activation_cost[1]),
            "human_torque_cost": human_torque_cost,
            "muscle_torque_cost": human_torque_cost,
            "net_joint_torque_cost": human_torque_cost,
            "gross_cost": gross_cost,
            "gross_load_cost": gross_cost,
            "activation_saving_ratio": float(activation_saving),
            "global_activation_saving_ratio": float(global_activation_saving),
            "activation_saving_mean_ratio": activation_saving_mean,
            "activation_saving_left_ratio": float(activation_saving_by_side[0]),
            "activation_saving_right_ratio": float(activation_saving_by_side[1]),
            "activation_side_degradation_ratio": activation_side_degradation,
            "human_torque_saving_ratio": float(torque_saving),
            "activation_residual_z": float(
                (reference.activation_mean - cycle_costs["activation"])
                / reference.activation_std
            ),
            "human_torque_residual_z": float(
                (reference.human_torque_mean - cycle_costs["human_torque"])
                / reference.human_torque_std
            ),
            "activation_cost_cycle": float(cycle_costs["activation"]),
            "target_activation_cost_cycle_left": float(
                cycle_costs["target_activation"][0]
            ),
            "target_activation_cost_cycle_right": float(
                cycle_costs["target_activation"][1]
            ),
            "human_torque_cost_cycle": float(cycle_costs["human_torque"]),
            "physiology_window_steps": float(self._physiology_window.sample_count),
            "physiology_window_target_steps": float(
                self._physiology_window.window_steps
            ),
            "physiology_window_fill_ratio": self._physiology_window.fill_ratio,
            "saving_raw": float(saving),
            "safety_gate": float(gate),
            "speed_excess": float(speed_excess),
            "upright_excess": float(upright_excess),
            "movement_rmse_rad": movement_rmse,
            "movement_z_rms": movement_z_rms,
            "movement_free_z": motion.movement_free_z,
            "movement_transition_z": motion.movement_transition_z,
            "movement_excess": float(movement_excess),
            "termination_remaining_steps": float(max(int(remaining_steps), 0)),
            "joint_limit_excess": float(joint_excess),
            "upright": float(np.clip(1.0 - upright_excess, 0.0, 1.0)),
            "torque_usage_cost": torque_usage_cost,
            "torque_cost": torque_cost,
            "torque_overload": float(torque_overload),
            "max_absolute_exo_torque_nm": max_absolute_torque,
            "jerk_cost": jerk_cost,
            "positive_power_cost": float(power_excess**2),
            "positive_power_w": positive_power,
            "mean_absolute_human_torque_nm": float(
                np.mean(np.abs(human_joint_torque))
            ),
            "mean_absolute_exo_torque_nm": float(np.mean(np.abs(torque))),
        }
        self.penultimate_torque = self.previous_torque.copy()
        self.previous_torque = torque.copy()
        return total, diagnostics

    def _update_cycle_costs(
        self,
        costs: dict[str, np.ndarray | float],
        gait_period_steps: float,
    ) -> dict[str, np.ndarray | float]:
        values = np.asarray(
            [
                float(costs["activation_cost"]),
                *np.asarray(costs["target_activation_cost"], dtype=np.float64),
                float(costs["human_torque_cost"]),
            ],
            dtype=np.float64,
        )
        mean = self._physiology_window.append(values, gait_period_steps)
        return {
            "activation": float(mean[0]),
            "target_activation": mean[1:3],
            "human_torque": float(mean[3]),
        }

    def _validate_snapshot(self, snapshot: MuscleSnapshot) -> None:
        expected_signature = self.baseline.metadata.get("physiology_signature")
        actual_signature = snapshot.metadata.get("physiology_signature")
        if not snapshot.valid:
            raise ValueError(
                "Cannot reward an invalid muscle snapshot: "
                f"{snapshot.validity_reason}."
            )
        if expected_signature != actual_signature:
            raise ValueError(
                "Muscle snapshot and naked baseline physiology signatures differ."
            )
        if snapshot.muscle_count != 22 or not np.all(snapshot.target_mask):
            raise ValueError(
                "MyoAssist reward requires all 22 muscles in the target mask."
            )


class _CausalCycleWindow:
    """Trailing physical costs over the currently estimated gait period."""

    def __init__(self) -> None:
        self._values: deque[np.ndarray] = deque()
        self.window_steps = 1

    def append(self, value: np.ndarray, gait_period_steps: float) -> np.ndarray:
        period = float(gait_period_steps)
        if not np.isfinite(period) or not 20.0 <= period <= 100.0:
            raise ValueError("gait_period_steps must be finite and in [20, 100].")
        array = np.asarray(value, dtype=np.float64)
        if array.shape != (4,) or not np.all(np.isfinite(array)):
            raise ValueError("Cycle physiology value must have shape (4,).")
        self.window_steps = int(np.clip(round(period), 20, 100))
        self._values.append(array.copy())
        while len(self._values) > self.window_steps:
            self._values.popleft()
        return np.mean(np.asarray(self._values), axis=0)

    @property
    def sample_count(self) -> int:
        return len(self._values)

    @property
    def fill_ratio(self) -> float:
        return min(self.sample_count / self.window_steps, 1.0)


def _vector(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (4,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite with shape (4,).")
    return array


def _positive_vector(value: np.ndarray, name: str) -> np.ndarray:
    array = _vector(value, name)
    if np.any(array <= 0.0):
        raise ValueError(f"{name} must be positive.")
    return array.copy()


__all__ = ["MyoAssistReward", "RewardConfig", "physiology_costs"]
