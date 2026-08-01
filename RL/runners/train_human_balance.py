"""训练Phase参考驱动的平地人体平衡残差策略。"""

from __future__ import annotations

import argparse
from functools import partial
from pathlib import Path

from RL.env.myosuite.human_balance_env import (
    DEFAULT_MANIFEST,
    HumanBalanceEnv,
)
from RL.train import train


RL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = RL_ROOT / "outputs/human_balance"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--resume",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--total-timesteps",
        type=int,
        default=10_000_000,
    )
    parser.add_argument(
        "--num-envs",
        type=int,
        default=8,
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="cpu",
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=42,
    )
    arguments = parser.parse_args()

    train_factory = partial(
        HumanBalanceEnv,
        manifest_path=arguments.manifest,
        split="train",
        max_episode_steps=500,
        support_range=(0.5, 1.0),
    )
    validation_factory = partial(
        HumanBalanceEnv,
        manifest_path=arguments.manifest,
        split="validation",
        max_episode_steps=1000,
        support_range=(0.5, 0.5),
    )

    model_path = train(
        train_factory,
        eval_env_factory=validation_factory,
        output_dir=arguments.output,
        resume_from=arguments.resume,
        total_timesteps=arguments.total_timesteps,
        num_envs=arguments.num_envs,
        seed=arguments.seed,
        checkpoint_interval=500_000,
        evaluation_interval=100_000,
        evaluation_episodes=5,
        device=arguments.device,
        ppo_parameters={
            "learning_rate": 3.0e-4,
            "n_steps": 512,
            "batch_size": 256,
            "n_epochs": 5,
            "gae_lambda": 0.95,
        },
    )

    print("human balance training finished")
    print("model:", model_path)


if __name__ == "__main__":
    main()
