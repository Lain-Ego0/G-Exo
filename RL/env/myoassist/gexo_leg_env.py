"""Gymnasium environment for frozen-human, four-joint G-Exo training."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import gymnasium as gym
import numpy as np

from RL.env.actor_observation import (
    ActorObservationBuilder,
    RESET_PROTOCOL,
    RESET_WARMUP_STEPS,
)
from RL.env.myoassist.baseline import (
    NAKED_REFERENCE_CONDITION,
    SPEED_WINDOW_STEPS,
    TRAINING_SPEED_SCHEDULE,
    ForwardSpeedWindow,
    MyoAssistBaseline,
    validate_calibrated_speed_range,
)
from RL.env.myoassist.domain_randomization import (
    DeploymentRandomizationConfig,
    DeploymentRandomizer,
)
from RL.env.myoassist.gait_phase import CausalGaitPhase, left_foot_force
from RL.env.myoassist.human_runtime import make_human_runtime
from RL.env.myoassist.muscle_adapter import MyoAssistMuscleAdapter
from RL.env.myoassist.model_builder import DEFAULT_PHYSICAL_OUTPUT_PATH
from RL.env.myoassist.motion_reference import (
    URDF_ZERO_ASSIST_CONDITION,
    MyoAssistMotionReference,
)
from RL.env.myoassist.policy_transfer import FrozenHumanPolicy, file_sha256
from RL.env.myoassist.reward import MyoAssistReward, RewardConfig
from RL.env.myoassist.sensor_adapter import JOINT_SPECS, MyoAssistSensorAdapter
from RL.env.myoassist.speed_curriculum import (
    SPEED_BAND_IDS,
    SpeedCurriculumConfig,
    StratifiedSpeedSampler,
)
from RL.env.myoassist.urdf_attachment import model_has_gexo_urdf
from RL.env.sensors import SensorReader
from RL.env.torque import TorqueActuator
from RL.runners.predictors.tcn_runtime import FrozenTCNRuntime


CONTROL_DT = 0.02
PLANT_TORQUE_SCALE_NM = np.full(4, 17.0, dtype=np.float32)
TORQUE_LIMIT_NM = np.full(4, 8.0, dtype=np.float32)
TORQUE_RATE_LIMIT_NM_S = np.full(4, 20.0, dtype=np.float32)
TORQUE_SOFT_THRESHOLD_NM = 6.5
TORQUE_TERMINATION_THRESHOLD_NM = 8.0


class GexoMyoAssistEnv(gym.Env):
    metadata = {"render_modes": ["human"]}

    def __init__(
        self,
        *,
        human_checkpoint: str | Path,
        baseline_path: str | Path,
        motion_reference_path: str | Path,
        tcn_checkpoint: str | Path,
        tcn_calibration: str | Path,
        seed: int = 0,
        max_episode_steps: int = 1000,
        min_speed_m_s: float = 0.8,
        max_speed_m_s: float = 1.25,
        anchor_min_speed_m_s: float | None = None,
        anchor_max_speed_m_s: float | None = None,
        lower_speed_probability: float = 0.25,
        anchor_speed_probability: float = 0.50,
        upper_speed_probability: float = 0.25,
        action_torque_scale_nm: float = 8.0,
        tcn_device: str = "cpu",
        human_device: str = "cpu",
        model_path: str | Path | None = None,
        warmup_steps: int = RESET_WARMUP_STEPS,
        domain_randomization: bool = False,
        render_mode: str | None = None,
    ) -> None:
        super().__init__()
        if warmup_steps != RESET_WARMUP_STEPS:
            raise ValueError(
                "Deployment protocol requires exactly "
                f"{RESET_WARMUP_STEPS} warmup steps."
            )
        self.baseline = MyoAssistBaseline.load(baseline_path)
        self.motion_reference = MyoAssistMotionReference.load(
            motion_reference_path
        )
        calibration_path = Path(tcn_calibration).expanduser().resolve(strict=True)
        calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
        self._validate_speed_range(
            min_speed_m_s,
            max_speed_m_s,
            calibration,
        )
        runtime_options: dict[str, Any] = {
            "seed": seed,
            "max_episode_steps": max_episode_steps + warmup_steps,
            "evaluate": False,
            "min_target_speed_m_s": min_speed_m_s,
            "max_target_speed_m_s": max_speed_m_s,
        }
        if model_path is not None:
            runtime_options["model_path"] = model_path
        self.human_environment = make_human_runtime(**runtime_options)
        self.human_policy = FrozenHumanPolicy(
            human_checkpoint,
            device=human_device,
        )
        self.tcn = FrozenTCNRuntime(
            tcn_checkpoint,
            calibration=calibration_path,
            device=tcn_device,
            allow_legacy_checkpoint=True,
        )
        self.sensor_adapter = MyoAssistSensorAdapter()
        self.sensor_reader = SensorReader()
        physical_model_path = Path(
            DEFAULT_PHYSICAL_OUTPUT_PATH if model_path is None else model_path
        ).expanduser().resolve(strict=True)
        self.muscle_adapter = MyoAssistMuscleAdapter(
            self.human_environment.sim.model.ptr,
            self.human_environment.sim.data.ptr,
            model_hash=file_sha256(physical_model_path),
        )
        action_scale = np.full(4, action_torque_scale_nm, dtype=np.float32)
        self.actuator = TorqueActuator(
            torque_limit_nm=TORQUE_LIMIT_NM,
            torque_rate_limit_nm_s=TORQUE_RATE_LIMIT_NM_S,
            action_torque_scale_nm=action_scale,
            control_dt=CONTROL_DT,
            filter_time_constant_s=0.0,
        )
        self.domain_randomizer = DeploymentRandomizer(
            DeploymentRandomizationConfig(enabled=domain_randomization),
            torque_limit_nm=TORQUE_LIMIT_NM,
            torque_rate_limit_nm_s=TORQUE_RATE_LIMIT_NM_S,
            control_dt=CONTROL_DT,
            model=self.human_environment.sim.model.ptr,
            data=self.human_environment.sim.data.ptr,
        )
        self.gait_phase = CausalGaitPhase()
        self.observation_builder = ActorObservationBuilder()
        self.reward_model = MyoAssistReward(
            self.baseline,
            self.motion_reference,
            RewardConfig(
                torque_limit_nm=TORQUE_LIMIT_NM,
                jerk_scale_nm=TORQUE_RATE_LIMIT_NM_S * CONTROL_DT,
                torque_soft_threshold_nm=TORQUE_SOFT_THRESHOLD_NM,
                torque_termination_threshold_nm=TORQUE_TERMINATION_THRESHOLD_NM,
            ),
        )
        self.action_torque_scale_nm = action_scale
        self.min_speed_m_s = float(min_speed_m_s)
        self.max_speed_m_s = float(max_speed_m_s)
        self.speed_curriculum = SpeedCurriculumConfig(
            minimum_m_s=self.min_speed_m_s,
            maximum_m_s=self.max_speed_m_s,
            anchor_minimum_m_s=float(
                self.min_speed_m_s
                if anchor_min_speed_m_s is None
                else anchor_min_speed_m_s
            ),
            anchor_maximum_m_s=float(
                self.max_speed_m_s
                if anchor_max_speed_m_s is None
                else anchor_max_speed_m_s
            ),
            lower_probability=lower_speed_probability,
            anchor_probability=anchor_speed_probability,
            upper_probability=upper_speed_probability,
        )
        self.speed_sampler = StratifiedSpeedSampler(self.speed_curriculum)
        self.warmup_steps = warmup_steps
        self.max_episode_steps = int(max_episode_steps)
        self.render_mode = render_mode
        self.action_space = gym.spaces.Box(-1.0, 1.0, shape=(4,), dtype=np.float32)
        self.observation_space = gym.spaces.Box(
            -np.inf,
            np.inf,
            shape=(160,),
            dtype=np.float32,
        )
        self._human_observation: np.ndarray | None = None
        self._latest_sensor32: np.ndarray | None = None
        self._forward_speed_window = ForwardSpeedWindow(
            self.baseline.speed_window_steps
        )
        self._target_speed_window = ForwardSpeedWindow(
            self.baseline.speed_window_steps
        )
        self._episode_step = 0
        self._speed_curriculum_band = "fixed"
        self._speed_curriculum_band_id = SPEED_BAND_IDS["fixed"]
        self._validate_artifacts(calibration)

    def _validate_speed_range(
        self,
        min_speed_m_s: float,
        max_speed_m_s: float,
        calibration: dict[str, Any],
    ) -> None:
        if self.baseline.speed_window_steps != SPEED_WINDOW_STEPS:
            raise ValueError("Baseline uses an incompatible forward-speed window.")
        validate_calibrated_speed_range(
            self.baseline,
            minimum_m_s=min_speed_m_s,
            maximum_m_s=max_speed_m_s,
            verified_speed_m_s=calibration.get("verified_speed_set_m_s", ()),
        )
        lower = float(self.motion_reference.speeds_m_s[0])
        upper = float(self.motion_reference.speeds_m_s[-1])
        if min_speed_m_s < lower - 1.0e-9 or max_speed_m_s > upper + 1.0e-9:
            raise ValueError(
                "Configured speed range is outside the URDF motion-reference "
                f"range [{lower}, {upper}]."
            )

    def _validate_artifacts(self, calibration: dict[str, Any]) -> None:
        checkpoint_hash = self.human_policy.checkpoint_sha256
        baseline_metadata = self.baseline.metadata
        motion_metadata = self.motion_reference.metadata
        calibration_fit = calibration.get("fit", {})
        if (
            baseline_metadata.get("warmup_protocol") != RESET_PROTOCOL
            or int(baseline_metadata.get("warmup_steps", -1))
            != RESET_WARMUP_STEPS
        ):
            raise ValueError("Baseline reset/warmup protocol is incompatible.")
        if (
            calibration_fit.get("warmup_protocol") != RESET_PROTOCOL
            or int(calibration_fit.get("warmup_steps", -1))
            != RESET_WARMUP_STEPS
        ):
            raise ValueError("TCN calibration reset/warmup protocol is incompatible.")
        if baseline_metadata.get("human_checkpoint_sha256") != checkpoint_hash:
            raise ValueError("Baseline was not collected with this human checkpoint.")
        if motion_metadata.get("human_checkpoint_sha256") != checkpoint_hash:
            raise ValueError(
                "Motion reference was not collected with this human checkpoint."
            )
        if baseline_metadata.get("reference_condition") != NAKED_REFERENCE_CONDITION:
            raise ValueError("Reward baseline is not the naked-human reference.")
        if baseline_metadata.get("urdf_enabled") is not False:
            raise ValueError("Reward baseline must not contain an exoskeleton URDF.")
        if motion_metadata.get("reference_condition") != URDF_ZERO_ASSIST_CONDITION:
            raise ValueError("Motion reference is not the worn-URDF zero-assist case.")
        if motion_metadata.get("urdf_enabled") is not True:
            raise ValueError("Motion reference must contain the exoskeleton URDF.")
        if (
            motion_metadata.get("warmup_protocol") != RESET_PROTOCOL
            or int(motion_metadata.get("warmup_steps", -1))
            != RESET_WARMUP_STEPS
        ):
            raise ValueError("Motion-reference reset/warmup protocol is incompatible.")
        if (
            baseline_metadata.get("physiology_signature")
            != self.muscle_adapter.physiology_signature
        ):
            raise ValueError(
                "Naked reference and assisted plant use different physiology."
            )
        if calibration.get("human_checkpoint_sha256") != checkpoint_hash:
            raise ValueError("TCN calibration was not fitted with this human checkpoint.")
        if calibration.get("physical_model_sha256") != self.muscle_adapter.model_hash:
            raise ValueError("TCN calibration belongs to a different MyoAssist model.")
        if motion_metadata.get("physical_model_sha256") != self.muscle_adapter.model_hash:
            raise ValueError("Motion reference belongs to a different MyoAssist model.")
        if calibration.get("tcn_checkpoint_sha256") != self.tcn.checkpoint_sha256:
            raise ValueError("TCN calibration checkpoint hash mismatch.")
        if (
            calibration.get("physiology_signature")
            != self.muscle_adapter.physiology_signature
        ):
            raise ValueError("TCN calibration physiology signature mismatch.")
        model_urdf_enabled = model_has_gexo_urdf(self.muscle_adapter.model)
        if calibration.get("urdf_enabled") is not model_urdf_enabled:
            raise ValueError(
                "TCN calibration URDF flag does not match the physical model."
            )
        if calibration.get("domain_randomization_enabled") is not False:
            raise ValueError("MVP calibration must explicitly disable domain randomization.")

    def _runtime_sensor32(self) -> np.ndarray:
        state = self.sensor_adapter.read_state(self.human_environment)
        state = self.domain_randomizer.randomize_state(state)
        return self.sensor_reader.read_runtime32(state=state)

    def _combined_step(
        self,
        exo_torque_nm: np.ndarray,
    ) -> tuple[np.ndarray, bool, bool, dict[str, Any]]:
        if self._human_observation is None:
            raise RuntimeError("Environment must be reset before step().")
        human_action = self.human_policy(self._human_observation)
        exo_action = exo_torque_nm / PLANT_TORQUE_SCALE_NM
        combined = np.concatenate((human_action, exo_action)).astype(np.float32)
        observation, _, terminated, truncated, info = self.human_environment.step(
            combined
        )
        actual_ctrl = np.asarray(
            self.human_environment.sim.data.ctrl[-4:],
            dtype=np.float64,
        )
        if not np.allclose(actual_ctrl, exo_torque_nm, atol=1.0e-6, rtol=0.0):
            raise RuntimeError("MyoAssist did not apply the requested physical torque.")
        self._human_observation = np.asarray(observation, dtype=np.float32)
        return self._human_observation, bool(terminated), bool(truncated), dict(info)

    def _build_observation(self, previous_action: np.ndarray) -> np.ndarray:
        self._latest_sensor32 = self._runtime_sensor32()
        self.tcn.append(self._latest_sensor32)
        self.observation_builder.append(self._latest_sensor32, previous_action)
        prediction = self.tcn.predict(
            self._latest_sensor32[:4],
            self._latest_sensor32[4:8],
        )
        return self.observation_builder.build(prediction.feature16)

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)
        self.actuator.reset()
        self.reward_model.reset()
        self.tcn.reset()
        self.observation_builder.reset()
        self.sensor_reader.reset(seed=seed)
        self.domain_randomizer.reset(self.np_random)
        self.gait_phase.reset()
        self._forward_speed_window.reset()
        self._target_speed_window.reset()
        self._episode_step = 0
        selected_options = {} if options is None else dict(options)
        if "target_speed" in selected_options:
            self._speed_curriculum_band = "fixed"
            self._speed_curriculum_band_id = SPEED_BAND_IDS["fixed"]
        else:
            speed, band, band_id = self.speed_sampler.sample(self.np_random)
            selected_options["target_speed"] = speed
            self._speed_curriculum_band = band
            self._speed_curriculum_band_id = band_id
        self._human_observation, reset_info = self.human_environment.reset(
            seed=seed,
            options=selected_options,
        )
        zero = np.zeros(4, dtype=np.float32)
        for _ in range(self.warmup_steps):
            _, terminated, truncated, _ = self._combined_step(zero)
            if terminated or truncated:
                raise RuntimeError("Frozen human failed during zero-assist preroll.")
            self._forward_speed_window.append(
                self.human_environment.sim.data.joint("pelvis_tx").qvel[0]
            )
            self._target_speed_window.append(
                self.human_environment._target_velocity
            )
            self.gait_phase.update(left_foot_force(self.human_environment))
            self.reward_model.prime(
                self.muscle_adapter.snapshot(),
                self.gait_phase.period_steps,
            )
            self._latest_sensor32 = self._runtime_sensor32()
            self.tcn.append(self._latest_sensor32)
            self.observation_builder.append(self._latest_sensor32, zero)
        self.human_environment.finish_preroll()
        if (
            not self._forward_speed_window.full
            or not self._target_speed_window.full
        ):
            raise RuntimeError(
                "Actual/target speed preroll did not fill both filter windows."
            )
        if not self.gait_phase.ready:
            raise RuntimeError("Gait phase was not calibrated during preroll.")
        observation = self.observation_builder.build(
            self.tcn.predict(
                self._latest_sensor32[:4],
                self._latest_sensor32[4:8],
            ).feature16
        )
        info = {
            **dict(reset_info),
            "warmup_steps": self.warmup_steps,
            "speed_window_steps": self.baseline.speed_window_steps,
            "forward_speed_raw_m_s": float(
                self.human_environment.sim.data.joint("pelvis_tx").qvel[0]
            ),
            "forward_speed_filtered_m_s": self._forward_speed_window.mean,
            "target_speed_raw_m_s": float(
                self.human_environment._target_velocity
            ),
            "target_speed_filtered_m_s": self._target_speed_window.mean,
            "human_checkpoint_sha256": self.human_policy.checkpoint_sha256,
            "motion_reference_condition": URDF_ZERO_ASSIST_CONDITION,
            "tcn_checkpoint_sha256": self.tcn.checkpoint_sha256,
            "speed_schedule": TRAINING_SPEED_SCHEDULE,
            "speed_curriculum_band": self._speed_curriculum_band,
            "speed_curriculum_band_id": self._speed_curriculum_band_id,
            "gait_phase": self.gait_phase.phase,
            "gait_period_steps": self.gait_phase.period_steps,
            "domain_randomization": self.domain_randomizer.diagnostics(),
        }
        return observation, info

    def step(
        self,
        action: np.ndarray,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        commanded_torque = self.actuator.process(action)
        applied_torque = self.domain_randomizer.apply_torque(commanded_torque)
        _, terminated, truncated, inner_info = self._combined_step(applied_torque)
        gait_phase = self.gait_phase.update(
            left_foot_force(self.human_environment)
        )
        max_absolute_torque = float(np.max(np.abs(applied_torque)))
        torque_overload = max_absolute_torque >= TORQUE_TERMINATION_THRESHOLD_NM
        if torque_overload:
            terminated = True
            inner_info["termination_reason"] = "exo_torque_overload"
        previous_action = applied_torque / self.action_torque_scale_nm
        observation = self._build_observation(previous_action)
        snapshot = self.muscle_adapter.snapshot()
        simulation = self.human_environment.sim
        human_joint_q = np.asarray(
            [
                spec.sign * float(simulation.data.joint(spec.name).qpos[0])
                for spec in JOINT_SPECS
            ],
            dtype=np.float32,
        )
        raw_forward_speed = float(
            simulation.data.joint("pelvis_tx").qvel[0]
        )
        filtered_forward_speed = self._forward_speed_window.append(
            raw_forward_speed
        )
        raw_target_speed = float(self.human_environment._target_velocity)
        filtered_target_speed = self._target_speed_window.append(
            raw_target_speed
        )
        self._episode_step += 1
        if self._episode_step >= self.max_episode_steps:
            truncated = True
        reward, diagnostics = self.reward_model.compute(
            snapshot=snapshot,
            gait_phase=gait_phase,
            gait_period_steps=self.gait_phase.period_steps,
            filtered_target_speed_m_s=filtered_target_speed,
            filtered_forward_speed_m_s=filtered_forward_speed,
            pelvis_height_m=float(simulation.data.joint("pelvis_ty").qpos[0]),
            pelvis_pitch_rad=float(simulation.data.joint("pelvis_tilt").qpos[0]),
            joint_q_rad=human_joint_q,
            joint_dq_rad_s=self._latest_sensor32[4:8],
            exo_torque_nm=applied_torque,
            terminated=terminated,
            remaining_steps=max(self.max_episode_steps - self._episode_step, 0),
        )
        info = {
            **inner_info,
            **{f"reward/{key}": value for key, value in diagnostics.items()},
            "reward_terms": {
                key: diagnostics[key]
                for key in (
                    "effort",
                    "alive",
                    "speed_penalty",
                    "upright_penalty",
                    "movement_penalty",
                    "gross_penalty",
                    "torque_usage_penalty",
                    "torque_overload_penalty",
                    "jerk_penalty",
                    "power_penalty",
                    "termination_penalty",
                    "total",
                )
            },
            "reward_metrics": diagnostics,
            "applied_exo_torque_nm": applied_torque.copy(),
            "commanded_exo_torque_nm": commanded_torque.copy(),
            "exo_torque": applied_torque.copy(),
            "max_absolute_exo_torque_nm": max_absolute_torque,
            "torque_overload": torque_overload,
            "muscle_activation": snapshot.activation.copy(),
            "target_speed_m_s": filtered_target_speed,
            "target_speed_raw_m_s": raw_target_speed,
            "target_speed_filtered_m_s": filtered_target_speed,
            "speed_curriculum_band": self._speed_curriculum_band,
            "speed_curriculum_band_id": self._speed_curriculum_band_id,
            "forward_speed_m_s": filtered_forward_speed,
            "forward_speed_raw_m_s": raw_forward_speed,
            "forward_speed_filtered_m_s": filtered_forward_speed,
            "pelvis_height_m": float(
                simulation.data.joint("pelvis_ty").qpos[0]
            ),
            "pelvis_pitch_rad": float(
                simulation.data.joint("pelvis_tilt").qpos[0]
            ),
            "joint_q_rad": self._latest_sensor32[:4].copy(),
            "joint_dq_rad_s": self._latest_sensor32[4:8].copy(),
            "human_joint_q_rad": human_joint_q,
            "joint_limit_excess": diagnostics["joint_limit_excess"],
            "gross_load_cost": diagnostics["gross_load_cost"],
            "mean_absolute_human_torque_nm": diagnostics[
                "mean_absolute_human_torque_nm"
            ],
            "exo_jerk_cost": diagnostics["jerk_cost"],
            "exo_joint_power_w": (
                applied_torque * self._latest_sensor32[4:8]
            ).copy(),
            "episode_step": self._episode_step,
            "gait_phase": gait_phase,
            "gait_period_steps": self.gait_phase.period_steps,
            "domain_randomization": self.domain_randomizer.diagnostics(),
        }
        return observation, reward, terminated, truncated, info

    def render(self) -> None:
        if self.render_mode == "human":
            self.human_environment.mj_render()

    def close(self) -> None:
        renderer = self.human_environment.sim.renderer
        window = getattr(renderer, "_window", None)
        if window is not None:
            window.close()
            renderer._window = None
        self.human_environment.close()


__all__ = ["GexoMyoAssistEnv"]
