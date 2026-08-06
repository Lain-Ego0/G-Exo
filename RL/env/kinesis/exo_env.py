"""Minimal Gymnasium environment for Kinesis exoskeleton assistance.

The frozen Kinesis policy drives the human muscles.  PPO observes only signals
that can later be reproduced by encoders and IMUs, and outputs four normalized
hip/knee assistance commands.
"""

from __future__ import annotations

from collections import deque
from pathlib import Path
from typing import Any

import gymnasium as gym
import mujoco
import numpy as np
from gymnasium import spaces

from RL.env.kinesis.assist_backend import AssistBackend
from RL.env.kinesis.baseline_reference import (
    DEFAULT_PHYSICAL_BASELINE_DIR,
    BaselineCycle,
    BaselineReference,
    BaselineSample,
    cycle_duration_cost,
    relative_rate_saving,
    tracking_metrics,
)
from RL.env.kinesis.causal_phase import CausalPhaseAdapter
from RL.env.kinesis.oracle_phase import CausalContactCycleTracker
from RL.env.kinesis.physical_exo import DynamicExoSystem
from RL.env.kinesis.tcn_adapter import (
    TCN_DEPLOYMENT_FEATURE_DIM,
    TCNInputAdapter,
)
from RL.env.kinesis.teacher import (
    KinesisPolicy,
    make_agent,
)
from RL.env.sensors import FRAME_DIM, SENSOR_DIM, SensorReader


CONTROL_DT = 0.02
HISTORY_LENGTH = 4
BASE_OBSERVATION_DIM = FRAME_DIM * HISTORY_LENGTH
OBSERVATION_DIM = BASE_OBSERVATION_DIM
TCN_OBSERVATION_DIM = BASE_OBSERVATION_DIM + TCN_DEPLOYMENT_FEATURE_DIM
PHASE_TCN_FEATURE_DIM = CausalPhaseAdapter.FEATURE_DIM
SCHEME_C_OBSERVATION_DIM = TCN_OBSERVATION_DIM + PHASE_TCN_FEATURE_DIM
GRAVITY = 9.80665
IMU_BODY_NAMES = (
    "femur_l",
    "tibia_l",
    "femur_r",
    "tibia_r",
)
RL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TCN_CHECKPOINT = (
    RL_ROOT / "outputs/tcn_runs/seed_43/best_model.pt"
)
DEFAULT_TCN_CALIBRATION = (
    RL_ROOT / "assets/tcn/kinesis_phase12_explicit_calibration.json"
)
DEFAULT_PHASE_TCN_CHECKPOINT = (
    RL_ROOT / "outputs/kinesis_cycle_phase_tcn/all_baselines.pt"
)

# Raw 36-dimensional frame scales.  These constants are deployable and do not
# depend on privileged simulation statistics.
FRAME_SCALE = np.asarray(
    [np.pi] * 4
    + [20.0] * 4
    + [20.0] * 12
    + [4.0 * GRAVITY] * 12
    + [1.0] * 4,
    dtype=np.float32,
)

# Reward tuning is intentionally centralized here.  Limits remain hard
# constraints in AssistBackend and must not be moved into this dictionary.
REWARD_WEIGHTS = {
    "effort": 2.0,
    "torque_deterioration": 0.1,
    "tracking_cost": 0.5,
    "balance_cost": 0.1,
    "upright_cost": 0.05,
    "alive": 0.005,
    "torque_cost": 0.02,
    "jerk_cost": 0.02,
    "positive_power_cost": 0.01,
    "termination": 10.0,
}

CYCLE_REWARD_WEIGHTS = {
    "effort": 10.0,
    "torque_deterioration": 1.0,
    "duration_cost": 0.5,
    "tracking_cost": 0.5,
    "balance_cost": 0.1,
    "upright_cost": 0.05,
    "alive": 0.001,
    "torque_cost": 0.02,
    "jerk_cost": 0.02,
    "positive_power_cost": 0.01,
    "termination": 10.0,
}

RATED_TORQUE_NM = 6.0
REWARD_WINDOW_STEPS = 15
TRACKING_THRESHOLD_RATIO = 1.5
TRACKING_MSE_MARGIN = 1.0e-4
TRACKING_MSE_FLOOR = 1.0e-4
TRACKING_COST_CAP = 4.0
BALANCE_GATE_LIMIT = 0.25
BALANCE_COST_FREE_RATIO = 0.05
BALANCE_COST_SCALE = 0.20
BALANCE_COST_CAP = 4.0
BALANCE_TORQUE_FLOOR_NM = 0.5
ACTIVATION_COST_FLOOR = 1.0e-4
MUSCLE_TORQUE_COST_FLOOR_NM = 0.5
TORQUE_DETERIORATION_TOLERANCE = 0.01
TORQUE_DETERIORATION_SCALE = 0.05
TORQUE_DETERIORATION_CAP = 4.0
CYCLE_DURATION_FREE_RATIO = 0.05
CYCLE_DURATION_SCALE_RATIO = 0.10
CYCLE_DURATION_COST_CAP = 4.0
POSITIVE_POWER_FREE_W = 20.0
POSITIVE_POWER_SCALE_W = 20.0
UPRIGHT_REWARD_FLOOR = 0.2
MIN_PELVIS_HEIGHT_M = 0.65
MAX_TORSO_TILT_RAD = 1.0
EPSILON = 1.0e-6

REWARD_SETTINGS = {
    "effort_reference": "same_state_no_assist",
    "offline_baseline_in_dense_effort_reward": False,
    "rated_torque_nm": RATED_TORQUE_NM,
    "tracking_threshold_ratio": TRACKING_THRESHOLD_RATIO,
    "tracking_mse_margin": TRACKING_MSE_MARGIN,
    "balance_gate_limit": BALANCE_GATE_LIMIT,
    "balance_cost_free_ratio": BALANCE_COST_FREE_RATIO,
    "balance_cost_scale": BALANCE_COST_SCALE,
    "reward_window_steps": REWARD_WINDOW_STEPS,
    "reward_window_seconds": REWARD_WINDOW_STEPS * CONTROL_DT,
    "torque_deterioration_tolerance": (
        TORQUE_DETERIORATION_TOLERANCE
    ),
    "torque_deterioration_scale": TORQUE_DETERIORATION_SCALE,
    "torque_deterioration_cap": TORQUE_DETERIORATION_CAP,
    "positive_power_free_w": POSITIVE_POWER_FREE_W,
    "positive_power_scale_w": POSITIVE_POWER_SCALE_W,
    "upright_reward_floor": UPRIGHT_REWARD_FLOOR,
    "minimum_pelvis_height_m": MIN_PELVIS_HEIGHT_M,
    "maximum_torso_tilt_rad": MAX_TORSO_TILT_RAD,
}

CYCLE_REWARD_SETTINGS = {
    **REWARD_SETTINGS,
    "effort_reference": "matched_zero_assist_cycle",
    "same_state_reference_role": "diagnostics_only",
    "cycle_boundary_source": "privileged_left_foot_contact",
    "cycle_effort_metric": "duration_normalized_load_rate",
    "cycle_duration_free_ratio": CYCLE_DURATION_FREE_RATIO,
    "cycle_duration_scale_ratio": CYCLE_DURATION_SCALE_RATIO,
    "cycle_duration_cost_cap": CYCLE_DURATION_COST_CAP,
    "phase_tcn_used_in_reward": False,
}


class KinesisExoEnv(gym.Env[np.ndarray, np.ndarray]):
    """Train a four-joint exoskeleton around a frozen Kinesis human."""

    metadata = {
        "render_modes": ["human"],
        "render_fps": 50,
    }

    def __init__(
        self,
        *,
        motion_id: int = 8,
        render_mode: str | None = None,
        baseline_dir: str | Path = DEFAULT_PHYSICAL_BASELINE_DIR,
        torque_limit_nm: float = 17.0,
        action_torque_scale_nm: float | None = None,
        torque_rate_limit_nm_s: float = 50.0,
        warmup_steps: int = 25,
        max_episode_steps: int = 500,
        strict_baseline_seed: bool = False,
        gyro_noise_std_rad_s: float = 0.0,
        specific_force_noise_std_m_s2: float = 0.0,
        gyro_bias_std_rad_s: float = 0.0,
        specific_force_bias_std_m_s2: float = 0.0,
        use_tcn: bool = False,
        tcn_checkpoint: str | Path = DEFAULT_TCN_CHECKPOINT,
        tcn_calibration: str | Path = DEFAULT_TCN_CALIBRATION,
        tcn_device: str = "cpu",
        use_phase_tcn: bool = False,
        phase_tcn_checkpoint: str | Path = DEFAULT_PHASE_TCN_CHECKPOINT,
        reward_mode: str = "same_state",
    ) -> None:
        super().__init__()

        if render_mode not in (None, "human"):
            raise ValueError("render_mode must be None or 'human'.")
        if warmup_steps < HISTORY_LENGTH:
            raise ValueError(
                f"warmup_steps must be at least {HISTORY_LENGTH}."
            )
        if max_episode_steps < 1:
            raise ValueError("max_episode_steps must be positive.")

        self.motion_id = int(motion_id)
        self.render_mode = render_mode
        self.warmup_steps = int(warmup_steps)
        self.max_episode_steps = int(max_episode_steps)
        self.strict_baseline_seed = bool(strict_baseline_seed)
        if reward_mode not in ("same_state", "cycle_c"):
            raise ValueError("reward_mode must be 'same_state' or 'cycle_c'.")
        if use_phase_tcn and not use_tcn:
            raise ValueError("Phase-TCN requires the motion TCN observation.")
        self.reward_mode = reward_mode
        if action_torque_scale_nm is None:
            action_torque_scale_nm = torque_limit_nm
        if not 0.0 < action_torque_scale_nm <= torque_limit_nm:
            raise ValueError(
                "action_torque_scale_nm must be in (0, torque_limit_nm]."
            )
        self.action_torque_scale_nm = float(action_torque_scale_nm)
        self.baseline = BaselineReference(baseline_dir, self.motion_id)
        if self.reward_mode == "cycle_c" and not self.baseline.supports_exact_cycles:
            raise RuntimeError(
                "cycle_c requires baselines from "
                "RL.runners.collect_kinesis_cycle_baseline."
            )
        self.reward_weights = (
            CYCLE_REWARD_WEIGHTS
            if self.reward_mode == "cycle_c"
            else REWARD_WEIGHTS
        )
        self.tcn_adapter: TCNInputAdapter | None = None
        if use_tcn:
            self.tcn_adapter = TCNInputAdapter(
                tcn_checkpoint,
                device=tcn_device,
                calibration=tcn_calibration,
            )
            if not self.tcn_adapter.has_actor_feature_normalization:
                raise RuntimeError(
                    "TCN calibration lacks fixed actor feature statistics. "
                    "Run RL.runners.fit_kinesis_tcn_feature_stats first."
                )
            self.warmup_steps = max(
                self.warmup_steps,
                self.tcn_adapter.history_length,
            )
        self.phase_tcn_adapter = (
            CausalPhaseAdapter(phase_tcn_checkpoint, device=tcn_device)
            if use_phase_tcn
            else None
        )
        if self.phase_tcn_adapter is not None:
            self.warmup_steps = max(
                self.warmup_steps,
                self.phase_tcn_adapter.history_length,
            )
        if self.phase_tcn_adapter is not None:
            self.observation_dim = SCHEME_C_OBSERVATION_DIM
        elif self.tcn_adapter is not None:
            self.observation_dim = TCN_OBSERVATION_DIM
        else:
            self.observation_dim = BASE_OBSERVATION_DIM

        # One frozen human and one MuJoCo model live for the whole worker.
        self.agent = make_agent(
            self.motion_id,
            # Kinesis stays headless; DynamicExoSystem replaces its MuJoCo
            # model with the coupled human-plus-URDF model below.
            render=False,
        )
        self.human_policy = KinesisPolicy(self.agent)
        self.physical_exo = DynamicExoSystem(self.agent.env)
        self.backend = AssistBackend(
            self.agent.env,
            exo_control_dt=CONTROL_DT,
            torque_limit_nm=torque_limit_nm,
            torque_rate_limit_nm_s=torque_rate_limit_nm_s,
            human_strength=1.0,
            load_sharing=True,
            physical_exo=self.physical_exo,
        )

        self.sensor_reader = SensorReader(
            gyro_noise_std_rad_s=gyro_noise_std_rad_s,
            specific_force_noise_std_m_s2=(
                specific_force_noise_std_m_s2
            ),
            gyro_bias_std_rad_s=gyro_bias_std_rad_s,
            specific_force_bias_std_m_s2=(
                specific_force_bias_std_m_s2
            ),
        )

        self.action_space = spaces.Box(
            low=-1.0,
            high=1.0,
            shape=(4,),
            dtype=np.float32,
        )
        self.observation_space = spaces.Box(
            low=-5.0,
            high=5.0,
            shape=(self.observation_dim,),
            dtype=np.float32,
        )

        self._history: deque[np.ndarray] = deque(
            maxlen=HISTORY_LENGTH
        )
        # Raw 32-D deployable frames are kept separately for the frozen TCN.
        # They are not scaled by FRAME_SCALE and do not include PPO actions.
        self._raw_sensor_history: deque[np.ndarray] = deque(maxlen=50)
        self._latest_tcn_features = np.zeros(
            TCN_DEPLOYMENT_FEATURE_DIM,
            dtype=np.float32,
        )
        self._latest_tcn_raw_features = np.zeros(
            TCN_DEPLOYMENT_FEATURE_DIM,
            dtype=np.float32,
        )
        self._latest_tcn_prediction_delta = np.zeros(
            TCN_DEPLOYMENT_FEATURE_DIM,
            dtype=np.float32,
        )
        self._latest_phase_tcn_features = np.zeros(
            PHASE_TCN_FEATURE_DIM,
            dtype=np.float32,
        )
        self._body_ids = np.asarray(
            [self._body_id(name) for name in IMU_BODY_NAMES],
            dtype=np.int32,
        )
        self._pelvis_body_id = self._body_id("pelvis")
        self._linear_sensor_ids = np.asarray(
            [self._sensor_id(f"{name}_vel") for name in IMU_BODY_NAMES],
            dtype=np.int32,
        )
        self._angular_sensor_ids = np.asarray(
            [
                self._sensor_id(f"{name}_angvel")
                for name in IMU_BODY_NAMES
            ],
            dtype=np.int32,
        )

        self._previous_linear_velocity = np.zeros(
            (4, 3), dtype=np.float64
        )
        self._previous_exo_torque = np.zeros(4, dtype=np.float32)
        self._penultimate_exo_torque = np.zeros(4, dtype=np.float32)
        self._actual_activation_window: deque[float] = deque(
            maxlen=REWARD_WINDOW_STEPS
        )
        self._baseline_activation_window: deque[float] = deque(
            maxlen=REWARD_WINDOW_STEPS
        )
        self._actual_torque_window: deque[float] = deque(
            maxlen=REWARD_WINDOW_STEPS
        )
        self._baseline_torque_window: deque[float] = deque(
            maxlen=REWARD_WINDOW_STEPS
        )
        self._offline_baseline_activation_window: deque[float] = deque(
            maxlen=REWARD_WINDOW_STEPS
        )
        self._offline_baseline_torque_window: deque[float] = deque(
            maxlen=REWARD_WINDOW_STEPS
        )
        self._episode_seed = self.baseline.seeds[0]
        self._last_state: dict[str, Any] | None = None
        self._episode_steps = 0
        self._cycle_tracker: CausalContactCycleTracker | None = None
        self._cycle_reference: BaselineCycle | None = None
        self._cycle_actual_activation_energy = 0.0
        self._cycle_actual_torque_impulse = 0.0
        self._cycle_actual_steps = 0

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        super().reset(seed=seed)

        requested_seed = (
            int(seed)
            if seed is not None
            else int(self.np_random.integers(0, 2**31 - 1))
        )
        episode_seed = self.baseline.resolve_seed(
            requested_seed,
            strict=self.strict_baseline_seed,
        )
        self._episode_seed = episode_seed
        self.human_policy.reset(episode_seed)
        self.sensor_reader.reset(episode_seed)

        self.backend.reset(seed=episode_seed, options=options)
        self._previous_linear_velocity = (
            self._read_linear_velocity_world()
        )
        self._previous_exo_torque.fill(0.0)
        self._penultimate_exo_torque.fill(0.0)
        self._episode_steps = 0
        self._history.clear()
        self._raw_sensor_history.clear()
        self._latest_tcn_features.fill(0.0)
        self._latest_tcn_raw_features.fill(0.0)
        self._latest_tcn_prediction_delta.fill(0.0)
        if self.tcn_adapter is not None:
            self.tcn_adapter.reset()
        self._latest_phase_tcn_features.fill(0.0)
        if self.phase_tcn_adapter is not None:
            self.phase_tcn_adapter.reset()
        if self.reward_mode == "cycle_c":
            on_threshold, off_threshold = self.baseline.contact_thresholds(
                episode_seed
            )
            self._cycle_tracker = CausalContactCycleTracker(
                on_threshold=on_threshold,
                off_threshold=off_threshold,
            )
        else:
            self._cycle_tracker = None
        self._cycle_reference = None
        self._cycle_actual_activation_energy = 0.0
        self._cycle_actual_torque_impulse = 0.0
        self._cycle_actual_steps = 0
        self._actual_activation_window.clear()
        self._baseline_activation_window.clear()
        self._actual_torque_window.clear()
        self._baseline_torque_window.clear()
        self._offline_baseline_activation_window.clear()
        self._offline_baseline_torque_window.clear()

        zero_torque = np.zeros(4, dtype=np.float32)
        zero_action = np.zeros(4, dtype=np.float32)

        # Warm up the frozen human and fill the real history window before PPO
        # receives its first observation.
        for _ in range(self.warmup_steps):
            state = self.backend.step(
                zero_torque,
                self.human_policy,
            )
            frame = self._read_frame(state, zero_action)
            self._history.append(frame)
            self._prime_cycle_tracker()
            baseline = self.baseline.sample(
                episode_seed,
                float(state["time"]),
            )
            self._append_reward_sample(state, baseline)

            if state["terminated"] or state["truncated"]:
                raise RuntimeError(
                    "Kinesis motion ended during environment warmup."
                )

        self._last_state = state
        tracking_mse, mpjpe_m = self._tracking_error(
            float(state["time"])
        )
        baseline = self.baseline.sample(
            episode_seed,
            float(state["time"]),
        )
        observation = self._observation()
        info = {
            "motion_id": self.motion_id,
            "episode_seed": episode_seed,
            "action_torque_scale_nm": self.action_torque_scale_nm,
            "time_s": float(state["time"]),
            "episode_steps": 0,
            "joint_position": np.asarray(
                state["joint_position"], dtype=np.float32
            ),
            "joint_velocity": np.asarray(
                state["joint_velocity"], dtype=np.float32
            ),
            "tracking_mse": tracking_mse,
            "baseline_tracking_mse": baseline.tracking_mse,
            "baseline_activation_cost": baseline.activation_cost,
            "baseline_muscle_torque_cost": baseline.torque_cost,
            "mpjpe_mm": 1000.0 * mpjpe_m,
            **self._physiology_info(state),
            **self._tcn_info(),
        }
        return observation, info

    def step(
        self,
        action: np.ndarray,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        requested_action = self._validate_action(action)
        target_torque = (
            requested_action * self.action_torque_scale_nm
        )

        state = self.backend.step(
            target_torque,
            self.human_policy,
        )
        self._episode_steps += 1

        if bool(state.get("load_sharing_failed", False)):
            reward = -self.reward_weights["termination"]
            info = {
                "motion_id": self.motion_id,
                "episode_seed": self._episode_seed,
                "time_s": float(state["time"]),
                "episode_steps": self._episode_steps,
                "reward_terms": {
                    "termination_penalty": reward,
                    "total": reward,
                },
                "muscle_solver_failed": 1.0,
                "termination_reason": "muscle_solver_failure",
                "solver_failure_reason": state.get(
                    "load_sharing_failure_reason", "unknown"
                ),
            }
            return self._observation(), reward, True, False, info

        if not self._state_is_finite(state):
            reward = -self.reward_weights["termination"]
            info = {
                "motion_id": self.motion_id,
                "episode_seed": self._episode_seed,
                "time_s": float(state["time"]),
                "episode_steps": self._episode_steps,
                "reward_terms": {
                    "termination_penalty": reward,
                    "total": reward,
                },
                "muscle_solver_failed": 0.0,
                "termination_reason": "invalid_state",
            }
            return self._observation(), reward, True, False, info

        # History stores the torque that was actually applied after the rate
        # limiter, not the unachievable request from the policy.
        applied_action = (
            np.asarray(state["exo_torque"], dtype=np.float32)
            / self.action_torque_scale_nm
        )
        self._history.append(
            self._read_frame(state, applied_action)
        )

        reason = self._abnormal_termination_reason(state)
        terminated = reason is not None
        truncated = bool(state["truncated"])
        if self._episode_steps >= self.max_episode_steps:
            truncated = True

        baseline = self.baseline.sample(
            self._episode_seed,
            float(state["time"]),
        )
        (
            reward,
            reward_terms,
            reward_metrics,
            tracking_mse,
            mpjpe_m,
        ) = (
            self._compute_reward(
                state,
                baseline,
                terminated=terminated,
            )
        )

        if bool(state["truncated"]):
            reason = "motion_complete"
        elif truncated:
            reason = "time_limit"
        elif reason is None:
            reason = "running"

        info = {
            "motion_id": self.motion_id,
            "episode_seed": self._episode_seed,
            "action_torque_scale_nm": self.action_torque_scale_nm,
            "time_s": float(state["time"]),
            "episode_steps": self._episode_steps,
            "reward_terms": reward_terms,
            "reward_metrics": reward_metrics,
            "joint_position": np.asarray(
                state["joint_position"], dtype=np.float32
            ),
            "joint_velocity": np.asarray(
                state["joint_velocity"], dtype=np.float32
            ),
            "human_torque": np.asarray(
                state["muscle_torque"], dtype=np.float32
            ),
            "baseline_human_torque": np.asarray(
                baseline.human_torque,
                dtype=np.float32,
            ),
            "exo_torque": np.asarray(
                state["exo_torque"], dtype=np.float32
            ),
            "motor_assistance_torque": np.asarray(
                state["motor_assistance_torque"], dtype=np.float32
            ),
            "interaction_torque": np.asarray(
                state["interaction_torque"], dtype=np.float32
            ),
            "cuff_force_n": np.asarray(
                state["cuff_force_n"], dtype=np.float32
            ),
            "cuff_error_m": np.asarray(
                state["cuff_error_m"], dtype=np.float32
            ),
            "cuff_constraint_error_m": float(
                state["cuff_constraint_error_m"]
            ),
            "torque_balance_error": np.asarray(
                state["torque_balance_error"],
                dtype=np.float32,
            ),
            "predicted_balance_error": np.asarray(
                state["predicted_balance_error"], dtype=np.float32
            ),
            "muscle_activation": np.asarray(
                state["muscle_activation"], dtype=np.float32
            ),
            "target_muscle_mask": np.asarray(
                state["target_muscle_mask"], dtype=bool
            ),
            "target_activation_cost": float(
                state["target_activation_cost"]
            ),
            "baseline_target_activation_cost": float(
                state["baseline_target_activation_cost"]
            ),
            "muscle_effort_torque_cost": float(
                state["muscle_effort_torque_cost"]
            ),
            "baseline_muscle_effort_torque_cost": float(
                state["baseline_muscle_effort_torque_cost"]
            ),
            "shadow_activation": np.asarray(
                state["shadow_activation"], dtype=np.float32
            ),
            "tracking_mse": tracking_mse,
            "baseline_tracking_mse": baseline.tracking_mse,
            "mpjpe_mm": 1000.0 * mpjpe_m,
            "exo_power_w": float(state["exo_power"]),
            "exo_joint_power_w": np.asarray(
                state["exo_joint_power"], dtype=np.float32
            ),
            "baseline_activation_cost": reward_metrics[
                "baseline_activation_cost"
            ],
            "baseline_muscle_torque_cost": reward_metrics[
                "baseline_muscle_torque_cost"
            ],
            "muscle_solver_failed": 0.0,
            "termination_reason": reason,
            **self._physiology_info(state),
            **self._tcn_info(),
        }

        self._penultimate_exo_torque = (
            self._previous_exo_torque.copy()
        )
        self._previous_exo_torque = np.asarray(
            state["exo_torque"], dtype=np.float32
        ).copy()
        self._last_state = state

        if self.render_mode == "human":
            self.render()

        return (
            self._observation(),
            reward,
            terminated,
            truncated,
            info,
        )

    def _compute_reward(
        self,
        state: dict[str, Any],
        baseline: BaselineSample,
        *,
        terminated: bool,
    ) -> tuple[
        float,
        dict[str, float],
        dict[str, float],
        float,
        float,
    ]:
        """Compute causal same-state unloading with offline diagnostics."""

        tracking_mse, mpjpe_m = self._tracking_error(
            float(state["time"])
        )
        upright = float(self.agent.env.compute_upright_reward())
        upright_cost = (
            max(UPRIGHT_REWARD_FLOOR - upright, 0.0)
            / UPRIGHT_REWARD_FLOOR
        ) ** 2

        tracking_threshold = max(
            TRACKING_THRESHOLD_RATIO * baseline.tracking_mse,
            baseline.tracking_mse + TRACKING_MSE_MARGIN,
        )
        tracking_excess_ratio = max(
            0.0,
            (tracking_mse - tracking_threshold)
            / max(tracking_threshold, TRACKING_MSE_FLOOR),
        )
        tracking_cost = min(
            tracking_excess_ratio**2,
            TRACKING_COST_CAP,
        )
        tracking_gate = float(
            np.clip(1.0 - tracking_excess_ratio, 0.0, 1.0)
        )

        # Use the one-step same-state physiology reference for dense causal
        # feedback.  The offline rollout remains a diagnostic and tracking
        # reference; assistance can shift gait timing away from wall-clock
        # alignment even when it locally unloads the human.
        self._append_reward_sample(state, baseline)
        mean_actual_activation = float(
            np.mean(self._actual_activation_window)
        )
        mean_same_state_activation = float(
            np.mean(self._baseline_activation_window)
        )
        mean_offline_activation = float(
            np.mean(self._offline_baseline_activation_window)
        )

        activation_saving = float(
            np.clip(
                (
                    mean_same_state_activation
                    - mean_actual_activation
                )
                / max(
                    mean_same_state_activation,
                    ACTIVATION_COST_FLOOR,
                ),
                -1.0,
                1.0,
            )
        )
        offline_activation_saving = float(
            np.clip(
                (
                    mean_offline_activation
                    - mean_actual_activation
                )
                / max(
                    mean_offline_activation,
                    ACTIVATION_COST_FLOOR,
                ),
                -1.0,
                1.0,
            )
        )

        mean_actual_torque = float(
            np.mean(self._actual_torque_window)
        )
        mean_same_state_torque = float(
            np.mean(self._baseline_torque_window)
        )
        mean_offline_torque = float(
            np.mean(self._offline_baseline_torque_window)
        )

        muscle_torque_saving = float(
            np.clip(
                (
                    mean_same_state_torque
                    - mean_actual_torque
                )
                / max(
                    mean_same_state_torque,
                    MUSCLE_TORQUE_COST_FLOOR_NM,
                ),
                -1.0,
                1.0,
            )
        )
        offline_muscle_torque_saving = float(
            np.clip(
                (
                    mean_offline_torque
                    - mean_actual_torque
                )
                / max(
                    mean_offline_torque,
                    MUSCLE_TORQUE_COST_FLOOR_NM,
                ),
                -1.0,
                1.0,
            )
        )

        cycle_metrics = self._update_cycle_reward(state)
        if self.reward_mode == "cycle_c":
            effort_raw = cycle_metrics["cycle_activation_rate_saving"]
            selected_torque_saving = cycle_metrics[
                "cycle_torque_rate_saving"
            ]
        else:
            effort_raw = activation_saving
            selected_torque_saving = muscle_torque_saving

        # Activation is the objective.  Muscle effort is a one-sided
        # constraint: improvement is not double-counted, while deterioration
        # outside the calibrated zero-assist noise band is penalized.
        torque_deterioration_excess = max(
            -selected_torque_saving
            - TORQUE_DETERIORATION_TOLERANCE,
            0.0,
        )
        torque_deterioration_cost = min(
            (
                torque_deterioration_excess
                / TORQUE_DETERIORATION_SCALE
            )
            ** 2,
            TORQUE_DETERIORATION_CAP,
        )

        exo_torque = np.asarray(
            state["exo_torque"],
            dtype=np.float64,
        )
        actual_joint_torque = np.sum(
            np.asarray(
                state["target_joint_torque_contribution_nm"],
                dtype=np.float64,
            ),
            axis=0,
        )
        same_state_baseline_torque = np.sum(
            np.asarray(
                state["baseline_target_joint_torque_contribution_nm"],
                dtype=np.float64,
            ),
            axis=0,
        )
        measured_assistance_torque = np.asarray(
            state["motor_assistance_torque"],
            dtype=np.float64,
        )
        actual_balance_error = (
            actual_joint_torque
            + measured_assistance_torque
            - same_state_baseline_torque
        )
        legacy_balance_error = np.asarray(
            state["torque_balance_error"],
            dtype=np.float64,
        )
        predicted_balance_error = np.asarray(
            state["predicted_balance_error"],
            dtype=np.float64,
        )
        balance_reference = max(
            float(np.mean(np.abs(same_state_baseline_torque))),
            BALANCE_TORQUE_FLOOR_NM,
        )
        balance_ratio = float(
            np.mean(np.abs(predicted_balance_error))
            / balance_reference
        )
        actual_balance_ratio = float(
            np.mean(np.abs(actual_balance_error))
            / balance_reference
        )
        legacy_actual_balance_ratio = float(
            np.mean(np.abs(legacy_balance_error))
            / balance_reference
        )
        balance_gate = float(
            np.clip(
                1.0
                - actual_balance_ratio
                / BALANCE_GATE_LIMIT,
                0.0,
                1.0,
            )
        )
        # Reset warmup pre-fills this short window.  Keep the ratio for tests
        # and unusual early truncations, but apply safety gates symmetrically
        # so zero-mean physiology noise cannot acquire a negative bias.
        reward_window_fill_ratio = (
            cycle_metrics["cycle_completed"]
            if self.reward_mode == "cycle_c"
            else len(self._actual_activation_window) / REWARD_WINDOW_STEPS
        )
        safety_gate = tracking_gate * balance_gate
        validity = safety_gate * reward_window_fill_ratio
        valid_effort = effort_raw * validity
        valid_muscle_torque_saving = (
            selected_torque_saving * validity
        )
        valid_torque_deterioration_cost = (
            torque_deterioration_cost * reward_window_fill_ratio
        )
        balance_excess = max(
            actual_balance_ratio - BALANCE_COST_FREE_RATIO,
            0.0,
        )
        balance_cost = min(
            (balance_excess / BALANCE_COST_SCALE) ** 2,
            BALANCE_COST_CAP,
        )

        torque_cost = float(
            np.mean(np.square(exo_torque / RATED_TORQUE_NM))
        )
        second_difference = (
            exo_torque
            - 2.0 * self._previous_exo_torque
            + self._penultimate_exo_torque
        )
        jerk_cost = float(
            np.mean(
                np.square(second_difference / RATED_TORQUE_NM)
            )
        )
        joint_power = np.asarray(
            state["exo_joint_power"], dtype=np.float64
        )
        positive_power = np.maximum(joint_power, 0.0)
        positive_power_excess = np.maximum(
            positive_power - POSITIVE_POWER_FREE_W,
            0.0,
        )
        positive_power_cost = float(
            np.mean(
                np.square(
                    positive_power_excess / POSITIVE_POWER_SCALE_W
                )
            )
        )

        terms = {
            "effort": self.reward_weights["effort"] * valid_effort,
            "torque_deterioration_penalty": (
                -self.reward_weights["torque_deterioration"]
                * valid_torque_deterioration_cost
            ),
            "duration_penalty": (
                -self.reward_weights.get("duration_cost", 0.0)
                * cycle_metrics["cycle_duration_cost"]
            ),
            "tracking_penalty": (
                -self.reward_weights["tracking_cost"] * tracking_cost
            ),
            "balance_penalty": (
                -self.reward_weights["balance_cost"] * balance_cost
            ),
            "upright_penalty": (
                -self.reward_weights["upright_cost"] * upright_cost
            ),
            "alive": self.reward_weights["alive"],
            "torque_penalty": (
                -self.reward_weights["torque_cost"] * torque_cost
            ),
            "jerk_penalty": (
                -self.reward_weights["jerk_cost"] * jerk_cost
            ),
            "positive_power_penalty": (
                -self.reward_weights["positive_power_cost"]
                * positive_power_cost
            ),
            "termination_penalty": (
                -self.reward_weights["termination"]
                if terminated
                else 0.0
            ),
        }
        reward = float(sum(terms.values()))
        terms["total"] = reward

        metrics = {
            "effort_raw": effort_raw,
            "same_state_activation_saving": activation_saving,
            "same_state_muscle_torque_saving": muscle_torque_saving,
            "activation_saving": effort_raw,
            "muscle_torque_saving": selected_torque_saving,
            "offline_activation_saving": offline_activation_saving,
            "offline_muscle_torque_saving": (
                offline_muscle_torque_saving
            ),
            "valid_effort": valid_effort,
            "valid_muscle_torque_saving": (
                valid_muscle_torque_saving
            ),
            "reward_window_fill_ratio": reward_window_fill_ratio,
            "activation_saving_window": activation_saving,
            "muscle_torque_saving_window": muscle_torque_saving,
            "offline_activation_saving_window": (
                offline_activation_saving
            ),
            "offline_muscle_torque_saving_window": (
                offline_muscle_torque_saving
            ),
            "torque_deterioration_excess": (
                torque_deterioration_excess
            ),
            "torque_deterioration_cost": (
                torque_deterioration_cost
            ),
            "activation_cost": mean_actual_activation,
            "same_state_baseline_activation_cost": (
                mean_same_state_activation
            ),
            "baseline_activation_cost": mean_offline_activation,
            "muscle_torque_cost": mean_actual_torque,
            "same_state_baseline_muscle_torque_cost": (
                mean_same_state_torque
            ),
            "baseline_muscle_torque_cost": mean_offline_torque,
            "net_joint_torque_cost": float(
                state["net_joint_torque_cost"]
            ),
            "baseline_net_joint_torque_cost": float(
                state["baseline_net_joint_torque_cost"]
            ),
            "target_activation_count": float(
                state["target_muscle_count"]
            ),
            # Diagnostic-only physiology metrics.  They do not contribute to
            # reward until their baseline response has been validated.
            "co_contraction_index_mean": float(
                np.mean(state["co_contraction_index"])
            ),
            "baseline_co_contraction_index_mean": float(
                np.mean(state["baseline_co_contraction_index"])
            ),
            "co_contraction_excess_mean": float(
                np.mean(state["co_contraction_excess"])
            ),
            "co_contraction_excess_max": float(
                np.max(state["co_contraction_excess"])
            ),
            "activation_overload_topk": float(
                state["activation_overload_topk"]
            ),
            "tracking_mse": tracking_mse,
            "baseline_tracking_mse": baseline.tracking_mse,
            "tracking_excess_ratio": tracking_excess_ratio,
            "tracking_gate": tracking_gate,
            "balance_ratio": balance_ratio,
            "actual_balance_ratio": actual_balance_ratio,
            "legacy_actual_balance_ratio": legacy_actual_balance_ratio,
            "balance_gate": balance_gate,
            "balance_cost": balance_cost,
            "upright": upright,
            "torque_cost": torque_cost,
            "jerk_cost": jerk_cost,
            "positive_power_cost": positive_power_cost,
            "positive_power_max_w": float(np.max(positive_power)),
            "rated_torque_exceed_ratio": float(
                np.mean(np.abs(exo_torque) > RATED_TORQUE_NM)
            ),
            "mpjpe_mm": 1000.0 * mpjpe_m,
            **cycle_metrics,
        }

        if not np.isfinite(reward):
            raise FloatingPointError("Reward contains NaN or Inf.")

        return reward, terms, metrics, tracking_mse, mpjpe_m

    def _append_reward_sample(
        self,
        state: dict[str, Any],
        baseline: BaselineSample,
    ) -> None:
        """Append causal same-state samples and offline diagnostics."""

        actual_activation = np.asarray(
            state["target_muscle_activation"],
            dtype=np.float64,
        )
        same_state_activation = np.asarray(
            state["baseline_target_muscle_activation"],
            dtype=np.float64,
        )
        actual_torque = np.asarray(
            state["target_muscle_effort_nm"],
            dtype=np.float64,
        )
        same_state_torque = np.asarray(
            state["baseline_target_muscle_effort_nm"],
            dtype=np.float64,
        )

        self._actual_activation_window.append(
            float(np.mean(np.square(actual_activation)))
        )
        self._baseline_activation_window.append(
            float(np.mean(np.square(same_state_activation)))
        )
        self._actual_torque_window.append(float(np.mean(actual_torque)))
        self._baseline_torque_window.append(
            float(np.mean(same_state_torque))
        )

        # The offline rollout is intentionally excluded from dense reward.
        # It remains useful for final paired evaluation and drift diagnosis.
        self._offline_baseline_activation_window.append(
            float(baseline.activation_cost)
        )
        self._offline_baseline_torque_window.append(
            float(baseline.muscle_effort_torque_cost)
        )

    def _prime_cycle_tracker(self) -> None:
        """Synchronize contact state during warmup without starting a cycle."""

        if self._cycle_tracker is None:
            return
        touch = np.asarray(self.agent.env.get_touch(), dtype=np.float64)
        if touch.size < 4:
            raise RuntimeError("Kinesis returned fewer than four touch sensors.")
        self._cycle_tracker.update(float(np.sum(touch[2:4])))

    def _update_cycle_reward(self, state: dict[str, Any]) -> dict[str, float]:
        """Emit one strictly paired physiology result at a complete stride."""

        metrics = {
            "cycle_completed": 0.0,
            "cycle_activation_saving": 0.0,
            "cycle_torque_saving": 0.0,
            "cycle_activation_rate_saving": 0.0,
            "cycle_torque_rate_saving": 0.0,
            "cycle_actual_activation_energy": 0.0,
            "cycle_baseline_activation_energy": 0.0,
            "cycle_actual_torque_impulse": 0.0,
            "cycle_baseline_torque_impulse": 0.0,
            "cycle_actual_duration_s": 0.0,
            "cycle_baseline_duration_s": 0.0,
            "cycle_duration_ratio": 0.0,
            "cycle_duration_cost": 0.0,
        }
        if self._cycle_tracker is None:
            return metrics

        touch = np.asarray(self.agent.env.get_touch(), dtype=np.float64)
        if touch.size < 4:
            raise RuntimeError("Kinesis returned fewer than four touch sensors.")
        new_cycle = self._cycle_tracker.update(float(np.sum(touch[2:4])))

        if new_cycle:
            reference = self._cycle_reference
            if reference is not None and self._cycle_actual_steps > 0:
                actual_activation = self._cycle_actual_activation_energy
                actual_torque = self._cycle_actual_torque_impulse
                actual_duration = self._cycle_actual_steps * CONTROL_DT
                duration_ratio = actual_duration / max(
                    reference.duration_s,
                    EPSILON,
                )
                metrics.update(
                    {
                        "cycle_completed": 1.0,
                        "cycle_activation_saving": float(
                            np.clip(
                                (reference.activation_energy - actual_activation)
                                / max(reference.activation_energy, EPSILON),
                                -1.0,
                                1.0,
                            )
                        ),
                        "cycle_torque_saving": float(
                            np.clip(
                                (reference.torque_impulse - actual_torque)
                                / max(reference.torque_impulse, EPSILON),
                                -1.0,
                                1.0,
                            )
                        ),
                        "cycle_activation_rate_saving": (
                            relative_rate_saving(
                                actual_activation,
                                actual_duration,
                                reference.activation_energy,
                                reference.duration_s,
                            )
                        ),
                        "cycle_torque_rate_saving": relative_rate_saving(
                            actual_torque,
                            actual_duration,
                            reference.torque_impulse,
                            reference.duration_s,
                        ),
                        "cycle_actual_activation_energy": actual_activation,
                        "cycle_baseline_activation_energy": (
                            reference.activation_energy
                        ),
                        "cycle_actual_torque_impulse": actual_torque,
                        "cycle_baseline_torque_impulse": (
                            reference.torque_impulse
                        ),
                        "cycle_actual_duration_s": actual_duration,
                        "cycle_baseline_duration_s": reference.duration_s,
                        "cycle_duration_ratio": duration_ratio,
                        "cycle_duration_cost": cycle_duration_cost(
                            actual_duration,
                            reference.duration_s,
                            free_ratio=CYCLE_DURATION_FREE_RATIO,
                            scale_ratio=CYCLE_DURATION_SCALE_RATIO,
                            cap=CYCLE_DURATION_COST_CAP,
                        ),
                    }
                )

            self._cycle_reference = self.baseline.cycle_at_time(
                self._episode_seed,
                float(state["time"]),
            )
            self._cycle_actual_activation_energy = 0.0
            self._cycle_actual_torque_impulse = 0.0
            self._cycle_actual_steps = 0

        if self._cycle_reference is not None:
            self._cycle_actual_activation_energy += (
                float(state["target_activation_cost"]) * CONTROL_DT
            )
            self._cycle_actual_torque_impulse += (
                float(state["muscle_effort_torque_cost"]) * CONTROL_DT
            )
            self._cycle_actual_steps += 1

        return metrics

    def _tracking_error(
        self,
        simulation_time: float,
    ) -> tuple[float, float]:
        """Return current reference position MSE and MPJPE."""

        return tracking_metrics(
            self.agent.env,
            simulation_time,
        )

    @staticmethod
    def _state_is_finite(state: dict[str, Any]) -> bool:
        """Reject numerical failures before they enter observation history."""

        names = (
            "joint_position",
            "joint_velocity",
            "muscle_activation",
            "muscle_torque",
            "target_activation_cost",
            "muscle_effort_torque_cost",
            "target_joint_torque_contribution_nm",
            "co_contraction_index",
            "activation_overload",
            "exo_torque",
            "exo_joint_power",
        )
        return all(
            np.all(np.isfinite(np.asarray(state[name])))
            for name in names
        )

    def _abnormal_termination_reason(
        self,
        state: dict[str, Any],
    ) -> str | None:
        """Separate physical/simulation failures from normal truncation."""

        if bool(state["terminated"]):
            return "tracking_failure"

        pelvis_height = float(
            self.backend.data.xpos[self._pelvis_body_id, 2]
        )
        if pelvis_height < MIN_PELVIS_HEIGHT_M:
            return "low_pelvis"

        upright_trigs = np.asarray(
            self.agent.env.proprioception["root_tilt"],
            dtype=np.float64,
        )
        forward = float(
            np.angle(upright_trigs[0] + 1j * upright_trigs[1])
        )
        sideways = float(
            np.angle(upright_trigs[2] + 1j * upright_trigs[3])
        )
        if max(abs(forward), abs(sideways)) > MAX_TORSO_TILT_RAD:
            return "excessive_torso_tilt"

        return None

    def _read_frame(
        self,
        state: dict[str, Any],
        previous_action: np.ndarray,
    ) -> np.ndarray:
        angular_velocity_world = self._read_sensor_bank(
            self._angular_sensor_ids
        )
        linear_velocity_world = self._read_linear_velocity_world()
        linear_acceleration_world = (
            linear_velocity_world
            - self._previous_linear_velocity
        ) / CONTROL_DT
        self._previous_linear_velocity = linear_velocity_world.copy()

        gyro_local = np.empty((4, 3), dtype=np.float32)
        specific_force_local = np.empty((4, 3), dtype=np.float32)
        gravity_world = np.asarray(
            self.backend.model.opt.gravity,
            dtype=np.float64,
        )

        for index, body_id in enumerate(self._body_ids):
            rotation_world_from_body = self.backend.data.xmat[
                body_id
            ].reshape(3, 3)
            rotation_body_from_world = rotation_world_from_body.T

            gyro_local[index] = rotation_body_from_world @ (
                angular_velocity_world[index]
            )
            specific_force_local[index] = rotation_body_from_world @ (
                linear_acceleration_world[index] - gravity_world
            )

        raw_frame = self.sensor_reader.read(
            state={
                "motor_q": state["joint_position"],
                "motor_dq": state["joint_velocity"],
                "imu_angular_velocity": gyro_local,
                "imu_specific_force": specific_force_local,
            },
            previous_action=previous_action,
        )
        raw_sensor_frame = raw_frame[:SENSOR_DIM].copy()
        self._raw_sensor_history.append(raw_sensor_frame)
        if self.phase_tcn_adapter is not None:
            self.phase_tcn_adapter.append(raw_sensor_frame)
            if self.phase_tcn_adapter.ready:
                self._latest_phase_tcn_features = (
                    self.phase_tcn_adapter.features
                )
        if self.tcn_adapter is not None:
            self.tcn_adapter.append(raw_sensor_frame)
            if self.tcn_adapter.ready:
                prediction = self.tcn_adapter.predict()
                current_q = np.asarray(
                    state["joint_position"], dtype=np.float32
                )
                current_dq = np.asarray(
                    state["joint_velocity"], dtype=np.float32
                )
                self._latest_tcn_raw_features = (
                    self.tcn_adapter.raw_deployment_features(
                        prediction,
                        current_q,
                        current_dq,
                    )
                )
                self._latest_tcn_features = (
                    self.tcn_adapter.deployment_features(
                        prediction,
                        current_q,
                        current_dq,
                    )
                )
                self._latest_tcn_prediction_delta = (
                    self._latest_tcn_raw_features.copy()
                )
        normalized = np.clip(
            raw_frame / FRAME_SCALE,
            -5.0,
            5.0,
        ).astype(np.float32)
        return normalized

    @property
    def raw_sensor_history(self) -> np.ndarray:
        """Return a copy of causal raw frames for TCN diagnostics/inference."""

        if not self._raw_sensor_history:
            return np.empty((0, SENSOR_DIM), dtype=np.float32)
        return np.stack(tuple(self._raw_sensor_history), axis=0)

    @property
    def latest_raw_sensor_frame(self) -> np.ndarray:
        """Return the latest raw frame without exposing mutable environment state."""

        if not self._raw_sensor_history:
            raise RuntimeError("Raw sensor history is empty.")
        return self._raw_sensor_history[-1].copy()

    def _read_linear_velocity_world(self) -> np.ndarray:
        return self._read_sensor_bank(self._linear_sensor_ids)

    def _read_sensor_bank(
        self,
        sensor_ids: np.ndarray,
    ) -> np.ndarray:
        values = np.empty((len(sensor_ids), 3), dtype=np.float64)

        for index, sensor_id in enumerate(sensor_ids):
            address = int(self.backend.model.sensor_adr[sensor_id])
            dimension = int(self.backend.model.sensor_dim[sensor_id])
            if dimension != 3:
                raise ValueError("Expected a three-axis MuJoCo sensor.")
            values[index] = self.backend.data.sensordata[
                address : address + dimension
            ]

        return values

    def _observation(self) -> np.ndarray:
        if len(self._history) != HISTORY_LENGTH:
            raise RuntimeError("Observation history is incomplete.")

        base_observation = np.concatenate(tuple(self._history)).astype(
            np.float32,
            copy=False,
        )
        if base_observation.shape != (BASE_OBSERVATION_DIM,):
            raise RuntimeError("Unexpected base observation shape.")
        parts = [base_observation]
        if self.tcn_adapter is not None:
            parts.append(self._latest_tcn_features)
        if self.phase_tcn_adapter is not None:
            parts.append(self._latest_phase_tcn_features)
        observation = np.concatenate(parts).astype(np.float32, copy=False)
        if observation.shape != (self.observation_dim,):
            raise RuntimeError("Unexpected observation shape.")
        if not np.all(np.isfinite(observation)):
            raise FloatingPointError("Observation contains NaN or Inf.")
        return observation

    def _tcn_info(self) -> dict[str, Any]:
        if self.tcn_adapter is None:
            return {"tcn_enabled": False}
        info = {
            "tcn_enabled": True,
            "tcn_history_size": self.tcn_adapter.history_size,
            "tcn_feature_abs_max": float(
                np.max(np.abs(self._latest_tcn_features))
            ),
            "tcn_feature_rms": float(
                np.sqrt(np.mean(np.square(self._latest_tcn_features)))
            ),
            "tcn_100ms_delta_q": (
                self._latest_tcn_prediction_delta[:4].copy()
            ),
            "tcn_100ms_delta_dq": (
                self._latest_tcn_prediction_delta[4:8].copy()
            ),
            "tcn_200ms_delta_q": (
                self._latest_tcn_prediction_delta[8:12].copy()
            ),
            "tcn_200ms_delta_dq": (
                self._latest_tcn_prediction_delta[12:16].copy()
            ),
        }
        if self.phase_tcn_adapter is not None:
            info.update(
                {
                    "phase_tcn_enabled": True,
                    "phase_tcn_sin": float(
                        self._latest_phase_tcn_features[0]
                    ),
                    "phase_tcn_cos": float(
                        self._latest_phase_tcn_features[1]
                    ),
                    "phase_tcn_rate_hz": float(
                        self._latest_phase_tcn_features[2]
                    ),
                    "phase_tcn_confidence": (
                        self.phase_tcn_adapter.confidence
                    ),
                }
            )
        else:
            info["phase_tcn_enabled"] = False
        return info

    @staticmethod
    def _physiology_info(state: dict[str, Any]) -> dict[str, Any]:
        names = (
            "target_muscle_activation",
            "baseline_target_muscle_activation",
            "target_muscle_force_n",
            "baseline_target_muscle_force_n",
            "target_joint_torque_contribution_nm",
            "baseline_target_joint_torque_contribution_nm",
            "target_muscle_effort_nm",
            "baseline_target_muscle_effort_nm",
            "co_contraction_abs_nm",
            "baseline_co_contraction_abs_nm",
            "co_contraction_index",
            "baseline_co_contraction_index",
            "co_contraction_excess",
            "activation_overload",
        )
        result = {
            name: np.asarray(state[name], dtype=np.float32).copy()
            for name in names
        }
        result["activation_overload_topk"] = float(
            state["activation_overload_topk"]
        )
        return result

    def _body_id(self, name: str) -> int:
        body_id = mujoco.mj_name2id(
            self.backend.model,
            mujoco.mjtObj.mjOBJ_BODY,
            name,
        )
        if body_id < 0:
            raise ValueError(f"Missing Kinesis body: {name}")
        return int(body_id)

    def _sensor_id(self, name: str) -> int:
        sensor_id = mujoco.mj_name2id(
            self.backend.model,
            mujoco.mjtObj.mjOBJ_SENSOR,
            name,
        )
        if sensor_id < 0:
            raise ValueError(f"Missing Kinesis sensor: {name}")
        return int(sensor_id)

    @staticmethod
    def _validate_action(action: np.ndarray) -> np.ndarray:
        array = np.asarray(action, dtype=np.float32)
        if array.shape != (4,):
            raise ValueError(
                f"Action must have shape (4,), got {array.shape}."
            )
        if not np.all(np.isfinite(array)):
            raise FloatingPointError("Action contains NaN or Inf.")
        return np.clip(array, -1.0, 1.0)

    def render(self) -> None:
        if self.render_mode == "human":
            self.physical_exo.render()

    def close(self) -> None:
        self.backend.close()
