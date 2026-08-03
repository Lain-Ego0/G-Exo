from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from time import monotonic
from typing import Callable, Sequence, Union

import gymnasium as gym
import numpy as np
import torch.nn as nn
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import (
    BaseCallback,
    CheckpointCallback,
    EvalCallback,
)
from stable_baselines3.common.utils import set_random_seed
from stable_baselines3.common.vec_env import (
    DummyVecEnv,
    SubprocVecEnv,
    VecEnv,
    VecMonitor,
)

#
#构造环境
#

EnvFactory = Callable[[], gym.Env]
EnvFactories = Union[EnvFactory, Sequence[EnvFactory]]

DEFAULT_PPO_PARAMETERS = {
    "learning_rate": 1.0e-3,
    "n_steps": 1024,
    "batch_size": 128,
    "n_epochs": 10,
    "gamma": 0.99,
    "gae_lambda": 0.99,
    "clip_range": 0.2,
    "ent_coef": 1.0e-3,
    "vf_coef": 0.5,
    "max_grad_norm": 0.5,
    "normalize_advantage": True,

    # 论文外骨骼策略采用128、64两个隐藏层。
    # Actor和Critic使用相同尺寸，但参数彼此独立。
    "policy_kwargs": {
        "activation_fn": nn.ReLU,
        # 从小幅探索开始，避免初始随机力矩破坏基线步态。
        "log_std_init": -2.0,
        "net_arch": {
            "pi": [128, 64],
            "vf": [128, 64],
        },
    },

}

class TrainingMetricsCallback(BaseCallback):
    def _on_step(self) -> bool:
        infos = self.locals.get("infos", [])
        
        for info in infos:
            self.logger.record_mean(
                "system/muscle_solver_failure_rate",
                float(info.get("muscle_solver_failed", 0.0)),
            )

            reward_terms = info.get("reward_terms",{})
            
            for name , value in reward_terms.items():
                self.logger.record_mean(
                    f"reward/{name}",
                    float(value),
                )

            # Keep raw diagnostics separate from weighted terms so
            # TensorBoard shows both the optimizer signal and its physical cause.
            reward_metrics = info.get("reward_metrics", {})
            metric_names = {
                "effort_raw": "effort/raw",
                "activation_saving": "effort/activation_saving",
                "muscle_torque_saving": "effort/muscle_torque_saving",
                "same_state_activation_saving": (
                    "diagnostic_same_state/activation_saving"
                ),
                "same_state_muscle_torque_saving": (
                    "diagnostic_same_state/muscle_torque_saving"
                ),
                "offline_activation_saving": (
                    "offline/activation_saving"
                ),
                "offline_muscle_torque_saving": (
                    "offline/muscle_torque_saving"
                ),
                "activation_saving_window": (
                    "effort/activation_saving_window"
                ),
                "muscle_torque_saving_window": (
                    "effort/muscle_torque_saving_window"
                ),
                "valid_effort": "effort/valid",
                "valid_muscle_torque_saving": (
                    "effort/valid_muscle_torque_saving"
                ),
                "reward_window_fill_ratio": (
                    "system/reward_window_fill_ratio"
                ),
                "activation_cost": "human/activation_squared",
                "same_state_baseline_activation_cost": (
                    "baseline_same_state/activation_squared"
                ),
                "baseline_activation_cost": (
                    "baseline/activation_squared"
                ),
                "muscle_torque_cost": "human/muscle_torque_cost",
                "same_state_baseline_muscle_torque_cost": (
                    "baseline_same_state/muscle_torque_cost"
                ),
                "baseline_muscle_torque_cost": (
                    "baseline/muscle_torque_cost"
                ),
                "torque_deterioration_excess": (
                    "cost/torque_deterioration_excess"
                ),
                "torque_deterioration_cost": (
                    "cost/torque_deterioration"
                ),
                "net_joint_torque_cost": "human/net_joint_torque_cost",
                "baseline_net_joint_torque_cost": (
                    "baseline/net_joint_torque_cost"
                ),
                "target_activation_count": "system/target_muscle_count",
                "tracking_mse": "tracking/mse",
                "baseline_tracking_mse": "baseline/tracking_mse",
                "tracking_excess_ratio": "tracking/excess_ratio",
                "tracking_gate": "gate/tracking",
                "balance_ratio": (
                    "control/predicted_balance_residual_ratio"
                ),
                "actual_balance_ratio": (
                    "control/actual_balance_residual_ratio"
                ),
                "legacy_actual_balance_ratio": (
                    "control/legacy_shadow_balance_residual_ratio"
                ),
                "balance_gate": "gate/balance",
                "balance_cost": "cost/balance",
                "upright": "human/upright",
                "torque_cost": "cost/torque",
                "jerk_cost": "cost/jerk",
                "positive_power_cost": "cost/positive_power",
                "positive_power_max_w": "control/positive_power_max_w",
                "rated_torque_exceed_ratio": (
                    "control/rated_torque_exceed_ratio"
                ),
                "co_contraction_index_mean": (
                    "physiology/co_contraction_index_mean"
                ),
                "baseline_co_contraction_index_mean": (
                    "baseline/co_contraction_index_mean"
                ),
                "co_contraction_excess_mean": (
                    "physiology/co_contraction_excess_mean"
                ),
                "co_contraction_excess_max": (
                    "physiology/co_contraction_excess_max"
                ),
                "activation_overload_topk": (
                    "physiology/activation_overload_topk"
                ),
                "cycle_completed": "cycle/completion_per_step",
            }
            for source, destination in metric_names.items():
                if source in reward_metrics:
                    self.logger.record_mean(
                        destination,
                        float(reward_metrics[source]),
                    )

            if reward_metrics.get("cycle_completed", 0.0) > 0.5:
                for source, destination in (
                    ("cycle_activation_saving", "cycle/activation_energy_saving"),
                    ("cycle_torque_saving", "cycle/muscle_torque_energy_saving"),
                    ("cycle_activation_rate_saving", "cycle/activation_rate_saving"),
                    ("cycle_torque_rate_saving", "cycle/muscle_torque_rate_saving"),
                    ("cycle_actual_activation_energy", "cycle/actual_activation_energy"),
                    ("cycle_baseline_activation_energy", "cycle/baseline_activation_energy"),
                    ("cycle_actual_torque_impulse", "cycle/actual_torque_impulse"),
                    ("cycle_baseline_torque_impulse", "cycle/baseline_torque_impulse"),
                    ("cycle_duration_ratio", "cycle/duration_ratio"),
                    ("cycle_duration_cost", "cycle/duration_cost"),
                ):
                    self.logger.record_mean(
                        destination,
                        float(reward_metrics[source]),
                    )
                
            human_torque = info.get("human_torque")
            if human_torque is not None:
                self.logger.record_mean(
                    "control/mean_abs_human_torque",
                    float(np.mean(np.abs(human_torque))),
                )
                
                
            exo_torque = info.get("exo_torque")
            if exo_torque is not None:
                self.logger.record_mean(
                    "control/mean_abs_exo_torque",
                    float(np.mean(np.abs(exo_torque))),
                )

            muscle_activation = info.get("muscle_activation")
            if muscle_activation is not None:
                self.logger.record_mean(
                    "human/mean_muscle_activation",
                    float(np.mean(muscle_activation)),
                )

            mpjpe_mm = info.get("mpjpe_mm")
            if mpjpe_mm is not None:
                self.logger.record_mean(
                    "tracking/mpjpe_mm",
                    float(mpjpe_mm),
                )

            exo_power_w = info.get("exo_power_w")
            if exo_power_w is not None:
                self.logger.record_mean(
                    "control/exo_power_w",
                    float(exo_power_w),
                )

            joint_power = info.get("exo_joint_power_w")
            if joint_power is not None:
                joint_power = np.asarray(joint_power, dtype=np.float64)
                self.logger.record_mean(
                    "control/positive_power_mean_w",
                    float(np.mean(np.maximum(joint_power, 0.0))),
                )

            cuff_force = info.get("cuff_force_n")
            if cuff_force is not None:
                self.logger.record_mean(
                    "physical/mean_cuff_force_n",
                    float(np.mean(np.asarray(cuff_force))),
                )
            cuff_error = info.get("cuff_constraint_error_m")
            if cuff_error is not None:
                self.logger.record_mean(
                    "physical/cuff_constraint_error_m",
                    float(cuff_error),
                )

            for source, destination in (
                ("tcn_feature_abs_max", "tcn/feature_abs_max"),
                ("tcn_feature_rms", "tcn/feature_rms"),
                ("phase_tcn_sin", "phase_tcn/sin"),
                ("phase_tcn_cos", "phase_tcn/cos"),
                ("phase_tcn_rate_hz", "phase_tcn/rate_hz"),
                ("phase_tcn_confidence", "phase_tcn/confidence"),
            ):
                if source in info:
                    self.logger.record_mean(
                        destination,
                        float(info[source]),
                    )

            # Aggregate curves can hide a policy that improves one motion and
            # harms another.  Keep a compact per-motion panel for diagnosis.
            motion_id = info.get("motion_id")
            if motion_id is not None:
                motion_prefix = f"motion_{int(motion_id):03d}"
                for name in (
                    "activation_saving_window",
                    "muscle_torque_saving_window",
                    "offline_activation_saving_window",
                    "offline_muscle_torque_saving_window",
                    "tracking_mse",
                    "actual_balance_ratio",
                    "cycle_completed",
                ):
                    if name in reward_metrics:
                        self.logger.record_mean(
                            f"{motion_prefix}/{name}",
                            float(reward_metrics[name]),
                        )
                if "total" in reward_terms:
                    self.logger.record_mean(
                        f"{motion_prefix}/reward_total",
                        float(reward_terms["total"]),
                    )
                if reward_metrics.get("cycle_completed", 0.0) > 0.5:
                    for name in (
                        "cycle_activation_saving",
                        "cycle_torque_saving",
                        "cycle_activation_rate_saving",
                        "cycle_torque_rate_saving",
                        "cycle_duration_ratio",
                        "cycle_duration_cost",
                    ):
                        self.logger.record_mean(
                            f"{motion_prefix}/{name}",
                            float(reward_metrics[name]),
                        )
                
        return True


class WallClockStopCallback(BaseCallback):
    """Stop learning cleanly after a requested wall-clock duration."""

    def __init__(self, max_hours: float) -> None:
        super().__init__()
        if max_hours <= 0.0:
            raise ValueError("max_hours must be positive.")
        self.max_seconds = float(max_hours) * 3600.0
        self.started_at = 0.0

    def _on_training_start(self) -> None:
        self.started_at = monotonic()

    def _on_step(self) -> bool:
        elapsed_seconds = monotonic() - self.started_at
        self.logger.record(
            "time/wall_hours",
            elapsed_seconds / 3600.0,
        )
        return elapsed_seconds < self.max_seconds
    
def make_vector_env(
    env_factory: EnvFactories,
    *,
    num_envs:int,
    seed:int,
) -> VecEnv:
    
    if callable(env_factory):
        workers = [env_factory for _ in range(num_envs)]
    else:
        workers = list(env_factory)
        if len(workers) != num_envs:
            raise ValueError(
                "The number of environment factories must match "
                f"num_envs ({len(workers)} != {num_envs})."
            )

    if num_envs == 1:
        vector_env:VecEnv = DummyVecEnv(workers)
    else:
        vector_env = SubprocVecEnv(
            workers,
            start_method = "spawn",
        )
        
    vector_env.seed(seed)
    
    return VecMonitor(vector_env)

def train(
    env_factory:EnvFactories,
    *,
    eval_env_factory:EnvFactories | None = None,
    output_dir:str | Path,
    resume_from:str | Path | None = None,
    total_timesteps:int = 2_000_000,
    num_envs:int = 1,
    seed:int = 42,
    checkpoint_interval:int = 100_000,
    evaluation_interval:int = 50_000,
    evaluation_episodes:int = 5,
    device:str = "auto",
    ppo_parameters:dict | None = None,
    max_hours:float | None = None,
    additional_callbacks:Sequence[BaseCallback] | None = None,
) -> Path:
    output_path = Path(output_dir)
    checkpoint_path = output_path / "checkpoints"
    best_model_path = output_path / "best_model"
    evaluation_path = output_path / "evaluation"
    tensorboard_path = output_path / "tensorboard"

    checkpoint_path.mkdir(parents=True, exist_ok=True)
    best_model_path.mkdir(parents=True, exist_ok=True)
    evaluation_path.mkdir(parents=True, exist_ok=True)
    tensorboard_path.mkdir(parents=True, exist_ok=True)

    set_random_seed(seed)
    
    train_env = make_vector_env(
        env_factory,
        num_envs=num_envs,
        seed=seed,
    )
    
    if eval_env_factory is None and not callable(env_factory):
        selected_eval_factory: EnvFactories = env_factory[0]
    else:
        selected_eval_factory = eval_env_factory or env_factory

    eval_num_envs = (
        1
        if callable(selected_eval_factory)
        else len(selected_eval_factory)
    )
    eval_env = make_vector_env(
        selected_eval_factory,
        num_envs=eval_num_envs,
        seed=seed + 10_000,
    )#为什么要用确定性动作评估？为什么要这么写来做确定性评估？
    
    parameters = deepcopy(DEFAULT_PPO_PARAMETERS)
    
    if ppo_parameters is not None:
        parameters.update(ppo_parameters)
        
    checkpoint_frequency = max(
        checkpoint_interval // num_envs,
        1,
    )
    evaluation_frequency = max(
        evaluation_interval //num_envs,
        1,
    )
    
    callbacks = [
        TrainingMetricsCallback(),
        
        CheckpointCallback(
            save_freq = checkpoint_frequency,
            save_path = str(checkpoint_path),
            name_prefix = "gexo_ppo",
        ),
        
        EvalCallback(
          eval_env = eval_env,
          best_model_save_path = str(best_model_path),
          log_path = str(evaluation_path),
          eval_freq = evaluation_frequency,
          n_eval_episodes = evaluation_episodes,
          deterministic = True,
          render = False,
        )
    ]

    if additional_callbacks is not None:
        for callback in additional_callbacks:
            if not isinstance(callback, BaseCallback):
                raise TypeError(
                    "Every additional callback must inherit BaseCallback."
                )
            callbacks.append(callback)

    if max_hours is not None:
        callbacks.append(WallClockStopCallback(max_hours))
    
    if resume_from is None:
        model = PPO(
            policy = "MlpPolicy",
            env = train_env,
            seed = seed,
            device = device,
            verbose = 1,
            tensorboard_log = str(tensorboard_path),
            **parameters,
        )
    else:
        resume_path = Path(resume_from)
        if not resume_path.is_file():
            raise FileNotFoundError(resume_path)
        model = PPO.load(
            resume_path,
            env=train_env,
            device=device,
            tensorboard_log=str(tensorboard_path),
        )
    
    try:
        model.learn(
            total_timesteps = total_timesteps,
            callback = callbacks,
            tb_log_name = "ppo_baseline",
            reset_num_timesteps = resume_from is None,
        )
        
        final_model_path = output_path / "final_model"
        model.save(final_model_path)
        
    finally:
        train_env.close()
        eval_env.close()
        
    return Path(f"{final_model_path}.zip")
