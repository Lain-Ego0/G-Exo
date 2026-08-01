"""Phase参考驱动的平地人体平衡PPO环境。"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path

import gymnasium as gym
import mujoco
import numpy as np
from gymnasium import spaces

sys.modules.setdefault("gym", gym)

import myosuite  # noqa: F401  注册MyoSuite环境。

from RL.env.myosuite.muscle_controller import MuscleController
from RL.env.myosuite.phase_reference import JOINT_NAMES, PhaseReference


RL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = RL_ROOT / "assets/datasets/phase12_manifest.json"
VALIDATION_SUBJECTS = {"BT11", "BT12"}

RESIDUAL_TORQUE_LIMITS = np.asarray(
    (
        45.0, 25.0, 20.0, 55.0, 35.0, 20.0,
        45.0, 25.0, 20.0, 55.0, 35.0, 20.0,
    ),
    dtype=np.float32,
)


def _trial_speed(trial_name: str) -> float | None:
    match = re.search(
        r"_(0-6|1-2|1-8|2-0|2-5)_(?:on|off)$",
        trial_name,
    )
    if match is None:
        return None
    return float(match.group(1).replace("-", "."))


class HumanBalanceEnv(gym.Env[np.ndarray, np.ndarray]):
    """学习12维关节残差，BVLS负责转换为80维肌肉动作。"""

    metadata = {"render_modes": []}

    def __init__(
        self,
        *,
        manifest_path: str | Path = DEFAULT_MANIFEST,
        split: str = "train",
        speeds: tuple[float, ...] = (0.6, 1.2),
        max_episode_steps: int = 500,
        support_range: tuple[float, float] = (0.5, 1.0),
        model_path: str | Path | None = None,
        mass_scale: float = 1.0,
        damping_scale: float = 1.0,
        friction_scale: float = 1.0,
    ) -> None:
        super().__init__()

        if split not in ("train", "validation"):
            raise ValueError("split must be 'train' or 'validation'.")

        self.split = split
        self.max_episode_steps = int(max_episode_steps)
        self.support_range = tuple(float(x) for x in support_range)

        environment_kwargs = {"reset_type": "init"}
        if model_path is not None:
            environment_kwargs["model_path"] = str(
                Path(model_path).expanduser().resolve()
            )

        self.native_env = gym.make(
            "myoLegWalk-v0",
            **environment_kwargs,
        )
        self.base = self.native_env.unwrapped

        self._scale_model(
            mass_scale=mass_scale,
            damping_scale=damping_scale,
            friction_scale=friction_scale,
        )

        self.controller = MuscleController(self.native_env)
        self.references = self._load_references(
            Path(manifest_path),
            speeds,
        )

        self.action_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(len(JOINT_NAMES),),
            dtype=np.float32,
        )
        self.observation_space = spaces.Box(
            low=-np.inf,
            high=np.inf,
            shape=(74,),
            dtype=np.float32,
        )

        self._reference: PhaseReference | None = None
        self._reference_start_time = 0.0
        self._target_height = 0.0
        self._target_root_quaternion = np.zeros(4)
        self._target_gravity = np.zeros(3)
        self._target_root_speed = 0.0
        self._speed = 0.0
        self._support_scale = 1.0
        self._episode_steps = 0
        self._last_action = np.zeros(
            len(JOINT_NAMES),
            dtype=np.float32,
        )
        self._exo_torque = np.zeros(
            len(JOINT_NAMES),
            dtype=np.float64,
        )

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict | None = None,
    ) -> tuple[np.ndarray, dict]:
        super().reset(seed=seed)
        self.native_env.reset(seed=seed)
        self.controller.reset()

        reference_index = int(
            self.np_random.integers(len(self.references))
        )
        self._reference, subject, trial, self._speed = (
            self.references[reference_index]
        )

        episode_duration = (
            self.max_episode_steps * float(self.base.dt)
        )
        latest_start = max(
            self._reference.duration_s - episode_duration - self.base.dt,
            0.0,
        )
        self._reference_start_time = float(
            self.np_random.uniform(0.0, latest_start)
        )

        reference = self._reference.sample(
            self._reference_start_time
        )
        data = self.base.mj_data
        data.qpos[self.controller.qpos_ids] = reference["q"]
        data.qvel[self.controller.dof_ids] = reference["dq"]
        data.qvel[1] = -self._speed
        data.time = 0.0
        mujoco.mj_forward(self.base.mj_model, data)

        foot_height = min(
            data.body("talus_l").xpos[2],
            data.body("talus_r").xpos[2],
        )
        data.qpos[2] += 0.03 - foot_height
        mujoco.mj_forward(self.base.mj_model, data)

        # MyoSuite用base.mj_data生成观测，但Robot.step()实际积分
        # robot.mj_data。定制Phase初态后必须同步到积分侧。
        self.base.robot.sync_sims(
            self.base.mj_model,
            data,
            self.base.robot.mj_model,
            self.base.robot.mj_data,
            model=False,
        )

        self._target_height = float(data.qpos[2])
        self._target_root_quaternion = data.qpos[3:7].copy()
        self._target_gravity = self._gravity_vector()
        self._target_root_speed = float(data.qvel[1])
        self._support_scale = float(
            self.np_random.uniform(*self.support_range)
        )
        self._episode_steps = 0
        self._last_action.fill(0.0)
        self._exo_torque.fill(0.0)

        observation = self._observation(reference)
        info = {
            "subject": subject,
            "trial": trial,
            "speed_mps": self._speed,
            "support_scale": self._support_scale,
        }
        return observation, info

    def step(
        self,
        action: np.ndarray,
    ) -> tuple[np.ndarray, float, bool, bool, dict]:
        if self._reference is None:
            raise RuntimeError("Call reset() before step().")

        action = np.clip(
            np.asarray(action, dtype=np.float32),
            -1.0,
            1.0,
        )
        if action.shape != self.action_space.shape:
            raise ValueError(
                f"action must have shape {self.action_space.shape}."
            )

        reference = self._reference.sample(
            self._reference_start_time
            + float(self.base.mj_data.time)
        )
        residual_torque = action * RESIDUAL_TORQUE_LIMITS

        self._apply_root_support()
        self.base.robot.mj_data.qfrc_applied[
            self.controller.dof_ids
        ] += self._exo_torque
        muscle_action = self.controller.compute(
            reference,
            exo_torque=self._exo_torque,
            residual_torque=residual_torque,
        )

        result = self.native_env.step(muscle_action)
        if len(result) == 5:
            _, _, terminated, native_truncated, _ = result
        else:
            _, _, terminated, _ = result
            native_truncated = False

        self._episode_steps += 1
        self._last_action = action.copy()

        next_reference = self._reference.sample(
            self._reference_start_time
            + float(self.base.mj_data.time)
        )
        reward, reward_terms = self._reward(
            next_reference,
            action,
        )

        truncated = bool(
            native_truncated
            or self._episode_steps >= self.max_episode_steps
        )
        terminated = bool(terminated)
        if terminated:
            reward -= 10.0
            reward_terms["termination"] = -10.0

        observation = self._observation(next_reference)
        q_error = (
            self.base.mj_data.qpos[self.controller.qpos_ids]
            - next_reference["q"]
        )

        info = {
            "reward_terms": reward_terms,
            "human_torque": self.controller.last_desired_torque.copy(),
            "muscle_activation": self.base.mj_data.act.copy(),
            "residual_torque": residual_torque.copy(),
            "exo_torque": self._exo_torque.copy(),
            "q_rmse_rad": float(np.sqrt(np.mean(np.square(q_error)))),
            "muscle_saturation_ratio": float(
                np.mean(self.base.mj_data.act > 0.9)
            ),
            "support_scale": self._support_scale,
            "termination_reason": (
                "native_termination"
                if terminated
                else "time_limit" if truncated else ""
            ),
        }
        return observation, float(reward), terminated, truncated, info

    def reference_now(self) -> dict[str, float | np.ndarray]:
        """返回当前相位参考，供非学习型播放和外骨骼脚本使用。"""

        if self._reference is None:
            raise RuntimeError("Call reset() before reading the reference.")
        return self._reference.sample(
            self._reference_start_time + float(self.base.mj_data.time)
        )

    def set_exo_torque(self, torque: np.ndarray) -> None:
        """设置下一步施加到人体四肢/外骨骼接口的12维关节力矩。"""

        torque = np.asarray(torque, dtype=np.float64)
        if torque.shape != (len(JOINT_NAMES),):
            raise ValueError(
                f"exo torque must have shape {(len(JOINT_NAMES),)}."
            )
        if not np.all(np.isfinite(torque)):
            raise ValueError("exo torque must be finite.")
        self._exo_torque = torque.copy()

    def _observation(
        self,
        reference: dict[str, float | np.ndarray],
    ) -> np.ndarray:
        data = self.base.mj_data
        q = data.qpos[self.controller.qpos_ids]
        dq = data.qvel[self.controller.dof_ids]
        phase = float(reference["phase"])

        observation = np.concatenate(
            (
                self._gravity_vector(),
                data.qvel[:6],
                np.asarray([data.qpos[2]], dtype=np.float64),
                q,
                dq,
                np.asarray(reference["q"]) - q,
                np.asarray(reference["dq"]) - dq,
                np.asarray(
                    [np.sin(2.0 * np.pi * phase),
                     np.cos(2.0 * np.pi * phase)],
                ),
                self._last_action,
                np.asarray(
                    [self._support_scale, self._speed],
                ),
            )
        ).astype(np.float32)

        return observation

    def _reward(
        self,
        reference: dict[str, float | np.ndarray],
        action: np.ndarray,
    ) -> tuple[float, dict[str, float]]:
        data = self.base.mj_data
        q_error = (
            data.qpos[self.controller.qpos_ids]
            - np.asarray(reference["q"])
        )
        dq_error = (
            data.qvel[self.controller.dof_ids]
            - np.asarray(reference["dq"])
        )
        gravity_error = self._gravity_vector() - self._target_gravity

        pose = 2.0 * np.exp(-2.0 * np.mean(np.square(q_error)))
        velocity = 0.5 * np.exp(
            -0.05 * np.mean(np.square(dq_error))
        )
        upright = 1.5 * np.exp(
            -5.0 * np.mean(np.square(gravity_error))
        )
        height = np.exp(
            -20.0 * np.square(data.qpos[2] - self._target_height)
        )
        speed = 0.5 * np.exp(
            -np.square(data.qvel[1] - self._target_root_speed)
        )
        effort = -0.1 * float(np.mean(np.square(data.act)))
        residual = -0.02 * float(np.mean(np.square(action)))

        terms = {
            "pose": float(pose),
            "velocity": float(velocity),
            "upright": float(upright),
            "height": float(height),
            "speed": float(speed),
            "muscle_effort": effort,
            "residual": residual,
        }
        return float(sum(terms.values())), terms

    def _gravity_vector(self) -> np.ndarray:
        rotation = self.base.mj_data.body("pelvis").xmat.reshape(3, 3)
        return rotation.T @ np.asarray((0.0, 0.0, -1.0))

    def _apply_root_support(self) -> None:
        observed_data = self.base.mj_data
        simulation_data = self.base.robot.mj_data
        simulation_data.qfrc_applied.fill(0.0)

        force = np.zeros(6, dtype=np.float64)
        force[0] = (
            -250.0 * observed_data.qpos[0]
            - 60.0 * observed_data.qvel[0]
        )
        force[1] = 250.0 * (
            self._target_root_speed - observed_data.qvel[1]
        )
        force[2] = (
            self.controller.body_mass_kg
            * abs(float(self.base.mj_model.opt.gravity[2]))
            + 1200.0 * (
                self._target_height - observed_data.qpos[2]
            )
            - 180.0 * observed_data.qvel[2]
        )

        rotation_error = np.zeros(3, dtype=np.float64)
        mujoco.mju_subQuat(
            rotation_error,
            self._target_root_quaternion,
            observed_data.qpos[3:7],
        )
        force[3:6] = (
            350.0 * rotation_error
            - 45.0 * observed_data.qvel[3:6]
        )
        simulation_data.qfrc_applied[:6] = (
            self._support_scale * force
        )

    def _load_references(
        self,
        manifest_path: Path,
        speeds: tuple[float, ...],
    ) -> list[tuple[PhaseReference, str, str, float]]:
        manifest = json.loads(
            manifest_path.read_text(encoding="utf-8")
        )
        dataset_root = Path(manifest["dataset_root"])
        references = []

        for trial in manifest["trials"]:
            subject = trial["subject"]
            is_validation = subject in VALIDATION_SUBJECTS

            if trial["condition"] != "off":
                continue
            if self.split == "train" and is_validation:
                continue
            if self.split == "validation" and not is_validation:
                continue

            speed = _trial_speed(trial["trial"])
            if speed is None or speed not in speeds:
                continue

            trial_dir = (
                dataset_root / trial["files"]["angle"]
            ).parent
            reference = PhaseReference(trial_dir)
            if not np.all(reference.moment_mask):
                continue

            references.append(
                (reference, subject, trial["trial"], speed)
            )

        if not references:
            raise RuntimeError(
                f"No usable {self.split} Phase references were found."
            )
        return references

    def _scale_model(
        self,
        *,
        mass_scale: float,
        damping_scale: float,
        friction_scale: float,
    ) -> None:
        model = self.base.mj_model
        model.body_mass[:] *= mass_scale
        model.body_inertia[:] *= mass_scale
        model.dof_damping[:] *= damping_scale
        model.geom_friction[:, 0] *= friction_scale

        mujoco.mj_setConst(model, self.base.mj_data)
        mujoco.mj_forward(model, self.base.mj_data)
        mujoco.mj_forward(model, self.base.robot.mj_data)

    def close(self) -> None:
        self.native_env.close()
