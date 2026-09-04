"""Human-only adaptation wrapper for the physical four-joint MyoAssist model."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np

from RL.env.myoassist.human_runtime import (
    EXO_ACTION_DIM,
    HUMAN_ACTION_DIM,
    GexoHumanRuntime,
    make_human_runtime,
)
from RL.env.myoassist.model_builder import (
    DEFAULT_PHYSICAL_OUTPUT_PATH,
    EXO_ACTUATORS,
)


class HumanAdaptationEnv(gym.Wrapper):
    """Expose only muscle actions while enforcing exactly zero G-Exo torque."""

    def __init__(
        self,
        environment: GexoHumanRuntime,
        *,
        default_target_speed_m_s: float | None = None,
    ) -> None:
        super().__init__(environment)
        if environment.action_space.shape != (
            HUMAN_ACTION_DIM + EXO_ACTION_DIM,
        ):
            raise ValueError("Human adaptation requires a 26-action plant.")
        self.action_space = gym.spaces.Box(
            low=np.asarray(
                environment.action_space.low[:HUMAN_ACTION_DIM],
                dtype=np.float32,
            ),
            high=np.asarray(
                environment.action_space.high[:HUMAN_ACTION_DIM],
                dtype=np.float32,
            ),
            dtype=np.float32,
        )
        if default_target_speed_m_s is not None and (
            not np.isfinite(default_target_speed_m_s)
            or default_target_speed_m_s <= 0.0
        ):
            raise ValueError(
                "default_target_speed_m_s must be positive and finite."
            )
        self.default_target_speed_m_s = default_target_speed_m_s
        self._exo_actuator_ids = self._resolve_exo_actuator_ids()
        self.last_combined_action = np.zeros(
            HUMAN_ACTION_DIM + EXO_ACTION_DIM,
            dtype=np.float32,
        )
        self.last_exo_ctrl = np.zeros(EXO_ACTION_DIM, dtype=np.float64)
        self.last_exo_actuator_force = np.zeros(
            EXO_ACTION_DIM,
            dtype=np.float64,
        )
        self.last_exo_generalized_force = np.zeros(
            environment.sim.model.nv,
            dtype=np.float64,
        )

    def _resolve_exo_actuator_ids(self) -> np.ndarray:
        model = self.unwrapped.sim.model
        actuator_ids = np.asarray(
            [model.actuator(spec.name).id for spec in EXO_ACTUATORS],
            dtype=np.int32,
        )
        expected_ids = np.arange(
            model.nu - EXO_ACTION_DIM,
            model.nu,
            dtype=np.int32,
        )
        if not np.array_equal(actuator_ids, expected_ids):
            raise ValueError(
                "G-Exo actuators must be the final four actuators in protocol "
                f"order; found {actuator_ids.tolist()}."
            )
        return actuator_ids

    def _exo_generalized_force(self) -> np.ndarray:
        data = self.unwrapped.sim.data
        generalized_force = np.zeros(
            self.unwrapped.sim.model.nv,
            dtype=np.float64,
        )
        for actuator_id in self._exo_actuator_ids:
            start = int(data.moment_rowadr[actuator_id])
            stop = start + int(data.moment_rownnz[actuator_id])
            columns = data.moment_colind[start:stop]
            generalized_force[columns] += (
                data.actuator_moment[start:stop]
                * data.actuator_force[actuator_id]
            )
        return generalized_force

    def _capture_zero_exo_state(self) -> None:
        data = self.unwrapped.sim.data
        self.last_exo_ctrl = np.asarray(
            data.ctrl[self._exo_actuator_ids],
            dtype=np.float64,
        ).copy()
        self.last_exo_actuator_force = np.asarray(
            data.actuator_force[self._exo_actuator_ids],
            dtype=np.float64,
        ).copy()
        self.last_exo_generalized_force = self._exo_generalized_force()
        if (
            np.count_nonzero(self.last_exo_ctrl)
            or np.count_nonzero(self.last_exo_actuator_force)
            or np.count_nonzero(self.last_exo_generalized_force)
        ):
            raise RuntimeError(
                "Human adaptation produced nonzero G-Exo control or force."
            )

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        selected_options = {} if options is None else dict(options)
        if self.default_target_speed_m_s is not None:
            selected_options.setdefault(
                "target_speed",
                self.default_target_speed_m_s,
            )
        observation, info = self.env.reset(
            seed=seed,
            options=selected_options,
        )
        self.last_combined_action.fill(0.0)
        self._capture_zero_exo_state()
        info = dict(info)
        info["adaptation_exo_torque_nm"] = self.last_exo_ctrl.astype(
            np.float32
        )
        return observation, info

    def step(
        self,
        action: np.ndarray,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        muscle_action = np.asarray(action, dtype=np.float32)
        if muscle_action.shape != (HUMAN_ACTION_DIM,):
            raise ValueError(
                f"Human action must have shape ({HUMAN_ACTION_DIM},), "
                f"got {muscle_action.shape}."
            )
        if not np.all(np.isfinite(muscle_action)):
            raise FloatingPointError("Human action contains NaN or Inf.")

        if not self.action_space.contains(muscle_action):
            raise ValueError("Human action is outside the normalized action space.")

        self.last_combined_action[:HUMAN_ACTION_DIM] = muscle_action
        self.last_combined_action[HUMAN_ACTION_DIM:] = 0.0
        result = self.env.step(self.last_combined_action)
        observation, reward, terminated, truncated, info = result

        self._capture_zero_exo_state()
        info = dict(info)
        info["adaptation_exo_torque_nm"] = self.last_exo_ctrl.astype(
            np.float32
        )
        return observation, float(reward), terminated, truncated, info


def make_human_adaptation_env(
    *,
    seed: int = 0,
    max_episode_steps: int = 1000,
    evaluate: bool = False,
    min_target_speed_m_s: float = 0.8,
    max_target_speed_m_s: float = 1.5,
    default_target_speed_m_s: float | None = None,
    random_reference_index: bool = False,
    model_path: str | Path = DEFAULT_PHYSICAL_OUTPUT_PATH,
    qpos_imitation_weight: float = 0.0,
    qvel_imitation_weight: float = 0.0,
) -> HumanAdaptationEnv:
    """Create the physical-model human environment with no exoskeleton authority."""

    runtime = make_human_runtime(
        seed=seed,
        max_episode_steps=max_episode_steps,
        evaluate=evaluate,
        model_path=model_path,
        min_target_speed_m_s=min_target_speed_m_s,
        max_target_speed_m_s=max_target_speed_m_s,
        random_reference_index=random_reference_index,
        qpos_imitation_weight=qpos_imitation_weight,
        qvel_imitation_weight=qvel_imitation_weight,
    )
    return HumanAdaptationEnv(
        runtime,
        default_target_speed_m_s=default_target_speed_m_s,
    )
