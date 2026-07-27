from __future__ import annotations

from copy import deepcopy
from pathlib import Path
from typing import Callable

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

DEFAULT_PPO_PARAMETERS = {
    "learning_rate": 1.0e-4,
    "n_steps": 1024,
    "batch_size": 128,
    "n_epochs": 10,
    "gamma": 0.99,
    "gae_lambda": 0.99,#这是什么
    "clip_range": 0.2,
    "ent_coef": 0.001,#这是什么
    "vf_coef": 0.5,#这是什么
    "max_grad_norm": 0.5,#这是什么
    "normalize_advantage": True,

    # 论文外骨骼策略采用128、64两个隐藏层。
    # Actor和Critic使用相同尺寸，但参数彼此独立。
    "policy_kwargs": {
        "activation_fn": nn.ReLU,
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
            reward_terms = info.get("reward_terms",{})
            
            for name , value in reward_terms.items():
                self.logger.record_mean(
                    f"reward/{name}",
                    float(value),
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
                
        return True
    
def make_vector_env(
    env_factory: EnvFactory,
    *,
    num_envs:int,
    seed:int,
) -> VecEnv:
    
    if num_envs == 1:
        vector_env:VecEnv = DummyVecEnv(workers)
    else:
        vector_env = SubprocVecEnv(
            workers,
            smart_method = "spawn",
        )
        
    vector_env.seed(seed)
    
    return VecMonitor(vector_env)

def train(
    env_factory:EnvFactory,
    *,
    output_dir:str | Path,
    total_timesteps:int = 2_000_000,
    num_envs:int = 1,
    seed:int = 42,
    checkpoint_interval:int = 100_000,
    evaluation_interval:int = 50_000,
    evaluation_episodes:int = 5,
    ppo_parameters:dict | None = None,
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
    
    eval_env = make_vector_env(
        env_factory,
        num_envs=1,
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
    
    model = PPO(
        policy = "MlpPolicy",
        env = train_env,
        seed = seed,
        verbose = 1,
        tensorboard_log = str(tensorboard_path),
        **parameters,
    )
    
    try:
        model.learn(
            total_timesteps = total_timesteps,
            callback = callbacks,
            tb_log_name = "ppo_baseline",
            reset_num_timesteps = True,
        )
        
        final_model_path = output_path / "final_model"
        model.save(final_model_path)
        
    finally:
        train_env.close()
        eval_env.close()
        
    return Path(f"{final_model_path}.zip")

