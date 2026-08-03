"""Deterministic 50 Hz MyoAssist human runtime for the G-Exo route."""

from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Any

import numpy as np
from myosuite.envs import env_base
from rl_train.envs.environment_handler import EnvironmentHandler
from rl_train.envs.myoassist_leg_base import MyoAssistLegBase
from rl_train.envs.myoassist_leg_imitation import MyoAssistLegImitation
from rl_train.train.train_configs.config_imiatation_exo import (
    ExoImitationTrainSessionConfig,
)

from RL.env.myoassist.model_builder import DEFAULT_OUTPUT_PATH, build_model


PROJECT_ROOT = Path(__file__).resolve().parents[3]
WORKSPACE_ROOT = PROJECT_ROOT.parent
MYOASSIST_ROOT = WORKSPACE_ROOT / "third_party" / "myoassist"
DEFAULT_CONFIG_PATH = (
    MYOASSIST_ROOT
    / "rl_train"
    / "train"
    / "train_configs"
    / "imitation_tutorial_22_separated_net_speed_control.json"
)
DEFAULT_REFERENCE_PATH = (
    MYOASSIST_ROOT
    / "rl_train"
    / "reference_data"
    / "short_reference_gait.npz"
)

CONTROL_HZ = 50
PHYSICS_HZ = 1200
CONTROL_DT = 1.0 / CONTROL_HZ
HUMAN_OBSERVATION_DIM = 44
HUMAN_ACTION_DIM = 22
EXO_ACTION_DIM = 4


def load_reference_data(
    path: str | Path = DEFAULT_REFERENCE_PATH,
    *,
    sample_rate_hz: int = CONTROL_HZ,
) -> dict[str, Any]:
    """Load and resample a private copy of the MyoAssist gait reference."""

    source = Path(path).expanduser().resolve(strict=True)
    with np.load(source, allow_pickle=True) as archive:
        loaded = {
            key: archive[key].item()
            for key in archive.files
        }

    reference = deepcopy(loaded)
    series = reference["series_data"]
    metadata = reference["metadata"]
    source_rate_hz = float(metadata["sample_rate"])

    lengths = {len(np.asarray(values)) for values in series.values()}
    if len(lengths) != 1:
        raise ValueError("All reference channels must have the same length.")

    source_length = lengths.pop()
    target_length = int(source_length * sample_rate_hz / source_rate_hz)
    if target_length < 2:
        raise ValueError("Resampled reference must contain at least two frames.")

    source_x = np.linspace(0.0, source_length - 1, source_length)
    target_x = np.linspace(0.0, source_length - 1, target_length)
    reference["series_data"] = {
        key: np.interp(target_x, source_x, np.asarray(values, dtype=np.float64))
        for key, values in series.items()
    }
    metadata["resampled_data_length"] = target_length
    metadata["resampled_sample_rate"] = int(sample_rate_hz)
    return reference


def load_runtime_config(
    *,
    seed: int,
    max_episode_steps: int,
    random_reference_index: bool = False,
    model_path: str | Path = DEFAULT_OUTPUT_PATH,
) -> ExoImitationTrainSessionConfig:
    """Load upstream settings, then apply route-B runtime-only overrides."""

    config = EnvironmentHandler.get_session_config_from_path(
        str(DEFAULT_CONFIG_PATH),
        ExoImitationTrainSessionConfig,
    )
    config.env_params.seed = int(seed)
    config.env_params.model_path = str(Path(model_path).resolve(strict=True))
    config.env_params.reference_data_path = str(
        DEFAULT_REFERENCE_PATH.resolve(strict=True)
    )
    config.env_params.control_framerate = CONTROL_HZ
    config.env_params.physics_sim_framerate = PHYSICS_HZ
    config.env_params.custom_max_episode_steps = int(max_episode_steps)
    config.env_params.flag_random_ref_index = bool(random_reference_index)
    config.env_params.num_envs = 1
    config.env_params.terrain_type = "flat"
    return config


class GexoHumanRuntime(MyoAssistLegImitation):
    """MyoAssist imitation environment with reproducible episode resets."""

    def __init__(
        self,
        *args: Any,
        enforce_imitation_termination: bool = False,
        **kwargs: Any,
    ) -> None:
        self._construction_complete = False
        self.enforce_imitation_termination = bool(
            enforce_imitation_termination
        )
        super().__init__(*args, **kwargs)
        self._construction_complete = True

    def _change_mode_and_target_velocity_randomly(self) -> None:
        modes = tuple(MyoAssistLegBase.VelocityMode)
        mode = modes[int(self.np_random.integers(0, len(modes)))]
        phase = float(self.np_random.uniform(0.0, 2.0 * np.pi))
        period = float(
            self.np_random.uniform(
                self._min_target_velocity_period,
                self._max_target_velocity_period,
            )
        )
        initial_speed = float(
            self.np_random.uniform(
                self._min_target_velocity,
                self._max_target_velocity,
            )
        )
        self.set_target_velocity_mode_manually(
            mode=mode,
            starting_phase=phase,
            initial_target_velocity=initial_speed,
            min_target_velocity=self._min_target_velocity,
            max_target_velocity=self._max_target_velocity,
            target_velocity_period=period,
        )
        if mode == MyoAssistLegBase.VelocityMode.SINUSOIDAL:
            self._target_velocity = self._calc_sinusoidal_target_velocity(
                phase,
                period,
                self._min_target_velocity,
                self._max_target_velocity,
            )

    def _modulate_target_velocity(self) -> None:
        if self._velocity_mode_for_this_episode == self.VelocityMode.UNIFORM:
            return
        if self._velocity_mode_for_this_episode == self.VelocityMode.SINUSOIDAL:
            self._target_velocity = self._calc_sinusoidal_target_velocity(
                self._starting_phase,
                self._target_velocity_period,
                self._min_target_velocity,
                self._max_target_velocity,
            )
            return
        if (
            self.sim.data.time - self._prev_step_changed_time
            >= self._target_velocity_period
        ):
            self._target_velocity = float(
                self.np_random.uniform(
                    self._min_target_velocity,
                    self._max_target_velocity,
                )
            )
            self._prev_step_changed_time = float(self.sim.data.time)

    def _set_uniform_target_speed(self, speed_m_s: float) -> None:
        speed = float(speed_m_s)
        if not np.isfinite(speed) or speed <= 0.0:
            raise ValueError("target_speed must be finite and positive.")
        self.set_target_velocity_mode_manually(
            mode=self.VelocityMode.UNIFORM,
            starting_phase=0.0,
            initial_target_velocity=speed,
            min_target_velocity=speed,
            max_target_velocity=speed,
            target_velocity_period=1.0,
        )

    def _reference_reset_state(
        self,
        reference_index: int,
    ) -> tuple[np.ndarray, np.ndarray]:
        if not 0 <= reference_index < self._reference_data_length:
            raise ValueError(
                f"reference_index must be in [0, {self._reference_data_length})."
            )

        qpos = self.init_qpos.copy()
        qvel = self.init_qvel.copy()
        series = self._reference_data["series_data"]
        reference_speed = float(series["dq_pelvis_tx"][reference_index])
        if abs(reference_speed) < 1e-6:
            raise ValueError("Reference pelvis speed is too small for scaling.")
        speed_ratio = float(self._target_velocity) / reference_speed

        for joint_name in self.reference_data_keys:
            joint_id = self.sim.model.joint(joint_name).id
            qpos_address = int(self.sim.model.jnt_qposadr[joint_id])
            dof_address = int(self.sim.model.jnt_dofadr[joint_id])
            qpos[qpos_address] = float(series[f"q_{joint_name}"][reference_index])
            qvel[dof_address] = (
                float(series[f"dq_{joint_name}"][reference_index])
                * speed_ratio
            )

        pelvis_tx_id = self.sim.model.joint("pelvis_tx").id
        qpos[int(self.sim.model.jnt_qposadr[pelvis_tx_id])] = 0.0
        return qpos, qvel

    def reset(
        self,
        *,
        seed: int | None = None,
        options: dict[str, Any] | None = None,
    ) -> tuple[np.ndarray, dict[str, Any]]:
        if seed is not None:
            self.seed(seed)
        options = {} if options is None else dict(options)

        target_speed = options.get("target_speed")
        if target_speed is None and not self.is_evaluate_mode:
            self._change_mode_and_target_velocity_randomly()
        elif target_speed is not None:
            self._set_uniform_target_speed(float(target_speed))

        reference_index = options.get("reference_index")
        if reference_index is None:
            if self._flag_random_ref_index:
                reference_index = int(
                    self.np_random.integers(0, self._reference_data_length)
                )
            else:
                reference_index = 0
        self._imitation_index = int(reference_index)

        qpos, qvel = self._reference_reset_state(self._imitation_index)
        result = env_base.MujocoEnv.reset(
            self,
            reset_qpos=qpos,
            reset_qvel=qvel,
            seed=seed,
        )
        observation = result[0] if isinstance(result, tuple) else result

        self._step_count_per_episode = 0
        self._prev_muscle_activations_for_reward = None
        self._reset_heel_strike_buffer()
        self._reset_reward_per_step()
        self._reset_properties_per_step()
        self._prev_step_changed_time = float(self.sim.data.time)

        info = {
            "reference_index": self._imitation_index,
            "target_speed": float(self._target_velocity),
        }
        return np.asarray(observation, dtype=np.float32), info

    def step(
        self,
        action: np.ndarray,
        **kwargs: Any,
    ) -> tuple[np.ndarray, float, bool, bool, dict[str, Any]]:
        """Advance physics while making imitation termination explicit."""

        if self._imitation_index is None:
            if self._construction_complete:
                raise RuntimeError("reset() must be called before step().")
            observation, _, terminated, _, info = MyoAssistLegBase.step(
                self,
                action,
                **kwargs,
            )
            return observation, 0.0, bool(terminated), True, info
        self._imitation_index += 1
        if self._imitation_index >= self._reference_data_length:
            if not self._loop_reference_data:
                raise RuntimeError("The non-looping reference was exhausted.")
            self._imitation_index = 0

        result = MyoAssistLegBase.step(self, action, **kwargs)
        observation, reward, terminated, truncated, info = result
        if self.enforce_imitation_termination:
            position_error = self._get_qpos_diff_nparray()
            terminated = bool(
                terminated
                or np.any(
                    np.abs(position_error)
                    > self._out_of_trajectory_threshold
                )
            )
        return observation, float(reward), bool(terminated), bool(truncated), info

    def finish_preroll(self) -> None:
        """Start episode accounting after a zero-assist stabilization window."""

        self._step_count_per_episode = 0
        self._prev_muscle_activations_for_reward = None
        self._reset_heel_strike_buffer()
        self._reset_reward_per_step()
        self._reset_properties_per_step()
        self._prev_step_changed_time = float(self.sim.data.time)


def make_human_runtime(
    *,
    seed: int = 0,
    max_episode_steps: int = 1000,
    evaluate: bool = True,
    random_reference_index: bool = False,
    model_path: str | Path = DEFAULT_OUTPUT_PATH,
    min_target_speed_m_s: float = 0.8,
    max_target_speed_m_s: float = 1.5,
    enforce_imitation_termination: bool = False,
) -> GexoHumanRuntime:
    """Create the private MyoAssist runtime without editing third-party code."""

    model = Path(model_path).expanduser().resolve()
    if model == DEFAULT_OUTPUT_PATH.resolve() and not model.is_file():
        build_model()
    else:
        model = model.resolve(strict=True)
    if not 0.0 < min_target_speed_m_s <= max_target_speed_m_s:
        raise ValueError("Target speed bounds must satisfy 0 < min <= max.")
    config = load_runtime_config(
        seed=seed,
        max_episode_steps=max_episode_steps,
        random_reference_index=random_reference_index,
        model_path=model,
    )
    config.env_params.min_target_velocity = float(min_target_speed_m_s)
    config.env_params.max_target_velocity = float(max_target_speed_m_s)
    reference = load_reference_data(sample_rate_hz=CONTROL_HZ)
    environment = GexoHumanRuntime(
        model_path=config.env_params.model_path,
        seed=seed,
        env_params=config.env_params,
        reference_data=reference,
        loop_reference_data=True,
        is_evaluate_mode=evaluate,
        enforce_imitation_termination=enforce_imitation_termination,
    )

    if environment.observation_space.shape != (HUMAN_OBSERVATION_DIM,):
        environment.close()
        raise RuntimeError(
            "Human observation contract changed: expected "
            f"({HUMAN_OBSERVATION_DIM},), got "
            f"{environment.observation_space.shape}."
        )
    if environment.action_space.shape != (
        HUMAN_ACTION_DIM + EXO_ACTION_DIM,
    ):
        environment.close()
        raise RuntimeError(
            "Combined action contract changed: expected (26,), got "
            f"{environment.action_space.shape}."
        )
    if not np.isclose(environment.dt, CONTROL_DT):
        environment.close()
        raise RuntimeError(
            f"Expected control dt {CONTROL_DT}, got {environment.dt}."
        )
    return environment
