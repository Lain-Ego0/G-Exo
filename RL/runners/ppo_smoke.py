"""不依赖MyoSuite，验证PPO训练流水线和多进程环境。"""

from pathlib import Path

import gymnasium as gym

from RL.train import train


def make_environment() -> gym.Env:
    """每次调用都创建一个全新的连续动作环境。"""

    return gym.make("Pendulum-v1")


def main() -> None:
    output_dir = Path(__file__).parents[1] / "outputs" / "ppo_smoke"

    model_path = train(
        env_factory=make_environment,
        output_dir=output_dir,
        total_timesteps=4096,
        num_envs=2,
        checkpoint_interval=2048,
        evaluation_interval=2048,
        evaluation_episodes=2,

        # 仅用于快速检查，不是正式训练参数。
        ppo_parameters={
            "n_steps": 256,
            "batch_size": 128,
            "n_epochs": 2,
        },
    )

    print("PPO smoke test passed.")
    print("model:", model_path)


if __name__ == "__main__":
    main()