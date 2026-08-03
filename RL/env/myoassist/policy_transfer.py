"""Load and transfer released MyoAssist human-controller weights."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

import numpy as np
import torch
from stable_baselines3 import PPO
from stable_baselines3.common.vec_env import VecEnv

from rl_train.train.policies.rl_agent_human import HumanActorCriticPolicy

from RL.env.myoassist.human_runtime import (
    HUMAN_ACTION_DIM,
    HUMAN_OBSERVATION_DIM,
    MYOASSIST_ROOT,
)


DEFAULT_HUMAN_CHECKPOINT = (
    MYOASSIST_ROOT
    / "docs"
    / "assets"
    / "tutorial_rl_models"
    / "train_session_20250804-235817_speed_control"
    / "trained_models"
    / "model_119832576.zip"
)
EXPECTED_CHECKPOINT_SHA256 = (
    "6bf9df3e93e72578068cf18f2b2ce49c47e59a9025d15a32b1a54d1ee7da1381"
)
HUMAN_NET_ARCH = (64, 64)
HUMAN_LOG_STD_INIT = -2.0


def file_sha256(path: str | Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


class FrozenHumanPolicy:
    """Deterministic 22-muscle adapter for released or adapted PPO policies."""

    def __init__(
        self,
        checkpoint_path: str | Path = DEFAULT_HUMAN_CHECKPOINT,
        *,
        device: str = "cpu",
        verify_hash: bool = True,
        expected_hash: str | None = None,
    ) -> None:
        self.checkpoint_path = Path(checkpoint_path).resolve(strict=True)
        self.checkpoint_sha256 = file_sha256(self.checkpoint_path)
        if expected_hash is None and self.checkpoint_path == DEFAULT_HUMAN_CHECKPOINT:
            expected_hash = EXPECTED_CHECKPOINT_SHA256
        if (
            verify_hash
            and expected_hash is not None
            and self.checkpoint_sha256 != expected_hash
        ):
            raise ValueError(
                "Human checkpoint hash mismatch: "
                f"expected {expected_hash}, "
                f"got {self.checkpoint_sha256}."
            )

        self.model = PPO.load(str(self.checkpoint_path), device=device)
        if self.model.observation_space.shape != (HUMAN_OBSERVATION_DIM,):
            raise ValueError(
                "Human checkpoint observation shape changed: "
                f"{self.model.observation_space.shape}."
            )
        if self.model.action_space.shape not in ((HUMAN_ACTION_DIM,), (24,)):
            raise ValueError(
                "Human checkpoint action shape must be 22 or 24, got "
                f"{self.model.action_space.shape}."
            )
        self.source_action_dim = int(self.model.action_space.shape[0])

        for parameter in self.model.policy.parameters():
            parameter.requires_grad_(False)
        self.model.policy.set_training_mode(False)

    def __call__(self, observation: np.ndarray) -> np.ndarray:
        observation_array = np.asarray(observation, dtype=np.float32)
        if observation_array.shape != (HUMAN_OBSERVATION_DIM,):
            raise ValueError(
                "Human observation must have shape "
                f"({HUMAN_OBSERVATION_DIM},), got {observation_array.shape}."
            )
        if not np.all(np.isfinite(observation_array)):
            raise FloatingPointError("Human observation contains NaN or Inf.")

        action, _ = self.model.predict(
            observation_array,
            deterministic=True,
        )
        muscle_action = np.asarray(
            action[:HUMAN_ACTION_DIM],
            dtype=np.float32,
        )
        if not np.all(np.isfinite(muscle_action)):
            raise FloatingPointError("Human policy returned NaN or Inf.")
        return np.clip(muscle_action, -1.0, 1.0)


def make_human_ppo(
    environment: Any,
    *,
    device: str = "cpu",
    seed: int = 0,
    learning_rate: float = 3e-5,
    n_steps: int = 512,
    batch_size: int = 512,
    n_epochs: int = 10,
    tensorboard_log: str | None = None,
    verbose: int = 1,
) -> PPO:
    """Create the 44-to-22 human-only PPO used for physical-model adaptation."""

    if environment.observation_space.shape != (HUMAN_OBSERVATION_DIM,):
        raise ValueError("Human adaptation observation space must have shape (44,).")
    if environment.action_space.shape != (HUMAN_ACTION_DIM,):
        raise ValueError("Human adaptation action space must have shape (22,).")
    num_envs = environment.num_envs if isinstance(environment, VecEnv) else 1
    if batch_size > n_steps * num_envs:
        raise ValueError("batch_size cannot exceed the rollout buffer size.")

    return PPO(
        policy=HumanActorCriticPolicy,
        env=environment,
        learning_rate=learning_rate,
        n_steps=n_steps,
        batch_size=batch_size,
        n_epochs=n_epochs,
        gamma=0.99,
        gae_lambda=0.95,
        clip_range=0.2,
        ent_coef=0.001,
        vf_coef=0.5,
        max_grad_norm=0.5,
        target_kl=0.02,
        seed=seed,
        device=device,
        tensorboard_log=tensorboard_log,
        verbose=verbose,
        policy_kwargs={
            "custom_policy_params": {
                "net_arch": {
                    "human_actor": list(HUMAN_NET_ARCH),
                    "common_critic": list(HUMAN_NET_ARCH),
                },
                "log_std_init": HUMAN_LOG_STD_INIT,
            }
        },
    )


def transfer_released_human_weights(
    target: PPO,
    source_checkpoint: str | Path = DEFAULT_HUMAN_CHECKPOINT,
    *,
    device: str = "cpu",
) -> dict[str, float | int | str]:
    """Copy only the released human actor into a fresh-critic PPO."""

    if target.action_space.shape != (HUMAN_ACTION_DIM,):
        raise ValueError("Target PPO must expose exactly 22 muscle actions.")
    source_path = Path(source_checkpoint).resolve(strict=True)
    source = PPO.load(str(source_path), device=device)
    if source.observation_space.shape != (HUMAN_OBSERVATION_DIM,):
        raise ValueError("Source human observation space must have shape (44,).")
    if source.action_space.shape != (24,):
        raise ValueError("Released source checkpoint must expose 24 actions.")

    source_actor = source.policy.policy_network.human_policy_net
    target_actor = target.policy.policy_network.policy_net
    target_critic = target.policy.policy_network.value_net

    critic_before = {
        name: value.detach().clone()
        for name, value in target_critic.state_dict().items()
    }
    target_actor.load_state_dict(source_actor.state_dict(), strict=True)
    with torch.no_grad():
        target.policy.log_std.fill_(HUMAN_LOG_STD_INIT)

    source_actor_state = source_actor.state_dict()
    target_actor_state = target_actor.state_dict()
    actor_error = max(
        (
            float(
                torch.max(
                    torch.abs(
                        source_actor_state[name].detach().cpu()
                        - target_actor_state[name].detach().cpu()
                    )
                )
            )
            for name in source_actor_state
        ),
        default=0.0,
    )
    critic_change = max(
        (
            float(
                torch.max(
                    torch.abs(
                        critic_before[name].detach().cpu()
                        - value.detach().cpu()
                    )
                )
            )
            for name, value in target_critic.state_dict().items()
        ),
        default=0.0,
    )
    if actor_error != 0.0:
        raise RuntimeError("Human actor transfer was not bit-exact.")
    if critic_change != 0.0:
        raise RuntimeError("Human actor transfer unexpectedly changed the critic.")
    if not torch.all(target.policy.log_std == HUMAN_LOG_STD_INIT):
        raise RuntimeError("Human exploration log standard deviation is not -2.")

    return {
        "source_checkpoint": str(source_path),
        "source_sha256": file_sha256(source_path),
        "actor_max_abs_error": actor_error,
        "actor_parameter_tensors": len(source_actor_state),
        "actor_parameters": sum(
            value.numel() for value in source_actor_state.values()
        ),
        "critic_max_abs_change": critic_change,
        "log_std_init": HUMAN_LOG_STD_INIT,
    }
