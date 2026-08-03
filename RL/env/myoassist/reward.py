"""Reward V1 for four-joint assistance on the MyoAssist physical plant."""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from RL.env.myoassist.baseline import MyoAssistBaseline
from RL.optimization.contracts import MuscleSnapshot


@dataclass(frozen=True)
class RewardConfig:
    effort_weight: float = 1.0
    speed_weight: float = 1.0
    upright_weight: float = 1.0
    gross_weight: float = 0.25
    torque_usage_weight: float = 0.01
    torque_weight: float = 1.0
    jerk_weight: float = 0.02
    power_weight: float = 0.01
    fall_weight: float = 1.0
    alive_reward: float = 0.005
    activation_weight: float = 0.6
    saving_clip: float = 5.0
    gross_tolerance: float = 0.1
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
        config: RewardConfig = RewardConfig(),
    ) -> None:
        self.baseline = baseline
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
        self.reset()

    def reset(self) -> None:
        self.previous_torque = np.zeros(4, dtype=np.float64)
        self.penultimate_torque = np.zeros(4, dtype=np.float64)

    def compute(
        self,
        *,
        snapshot: MuscleSnapshot,
        filtered_target_speed_m_s: float,
        filtered_forward_speed_m_s: float,
        pelvis_height_m: float,
        pelvis_pitch_rad: float,
        joint_q_rad: np.ndarray,
        joint_dq_rad_s: np.ndarray,
        exo_torque_nm: np.ndarray,
        terminated: bool,
    ) -> tuple[float, dict[str, float]]:
        self._validate_snapshot(snapshot)
        q = _vector(joint_q_rad, "joint_q_rad")
        dq = _vector(joint_dq_rad_s, "joint_dq_rad_s")
        torque = _vector(exo_torque_nm, "exo_torque_nm")
        force = snapshot.resolved_muscle_force_n()
        contribution = snapshot.moment_arm_m * force[:, None]
        human_joint_torque = np.sum(contribution, axis=0)
        gross_joint_load = np.sum(np.abs(contribution), axis=0)
        activation_cost = float(np.mean(np.square(snapshot.activation)))
        human_torque_cost = float(
            np.mean(
                np.square(
                    human_joint_torque / self.baseline.human_joint_scale_nm
                )
            )
        )
        gross_cost = float(
            np.mean(gross_joint_load / self.baseline.gross_joint_scale_nm)
        )
        reference = self.baseline.at_speed(filtered_target_speed_m_s)
        activation_saving = np.clip(
            (reference.activation_mean - activation_cost) / reference.activation_std,
            -self.config.saving_clip,
            self.config.saving_clip,
        )
        torque_saving = np.clip(
            (reference.human_torque_mean - human_torque_cost)
            / reference.human_torque_std,
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
        gate = np.clip(1.0 - speed_excess, 0.0, 1.0) * np.clip(
            1.0 - upright_excess,
            0.0,
            1.0,
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

        components = {
            "effort": self.config.effort_weight * effort,
            "alive": self.config.alive_reward,
            "speed_penalty": -self.config.speed_weight * speed_excess**2,
            "upright_penalty": -self.config.upright_weight * upright_excess**2,
            "gross_penalty": -self.config.gross_weight * gross_excess**2,
            "torque_usage_penalty": (
                -self.config.torque_usage_weight * torque_usage_cost
            ),
            "torque_overload_penalty": -self.config.torque_weight * torque_cost,
            "jerk_penalty": -self.config.jerk_weight * jerk_cost,
            "power_penalty": -self.config.power_weight * power_excess**2,
            "termination_penalty": -self.config.fall_weight if terminated else 0.0,
        }
        total = float(sum(components.values()))
        diagnostics = {
            **components,
            "total": total,
            "activation_cost": activation_cost,
            "human_torque_cost": human_torque_cost,
            "muscle_torque_cost": human_torque_cost,
            "net_joint_torque_cost": human_torque_cost,
            "gross_cost": gross_cost,
            "gross_load_cost": gross_cost,
            "activation_saving_z": float(activation_saving),
            "human_torque_saving_z": float(torque_saving),
            "saving_raw": float(saving),
            "safety_gate": float(gate),
            "speed_excess": float(speed_excess),
            "upright_excess": float(upright_excess),
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

    def _validate_snapshot(self, snapshot: MuscleSnapshot) -> None:
        expected_hash = self.baseline.metadata.get("model_sha256")
        if not snapshot.valid:
            raise ValueError(
                "Cannot reward an invalid muscle snapshot: "
                f"{snapshot.validity_reason}."
            )
        if expected_hash != snapshot.model_hash:
            raise ValueError("Muscle snapshot and baseline model hashes differ.")
        if snapshot.muscle_count != 22 or not np.all(snapshot.target_mask):
            raise ValueError(
                "MyoAssist reward requires all 22 muscles in the target mask."
            )


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


__all__ = ["MyoAssistReward", "RewardConfig"]
