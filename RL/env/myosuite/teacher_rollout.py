from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np

# 导入 myosuite 会完成环境注册。
import myosuite
from myosuite.utils import gym

from RL.env.myosuite.teacher_controller import (
    DepRLTeacherController,
)


def collect_teacher_rollouts(
    output_path: Path,
    number_of_rollouts: int,
    first_seed: int,
    max_attempts: int,
) -> Path:
    """
    采集 DEPRL 成功步态 rollout。

    只保存完整运行 1000 步且未触发终止条件的轨迹。
    早期跌倒的随机初态只记录 seed，不进入监督数据。
    """

    if number_of_rollouts <= 0:
        raise ValueError("number_of_rollouts must be positive.")

    if max_attempts < number_of_rollouts:
        raise ValueError(
            "max_attempts must be at least number_of_rollouts."
        )

    if output_path.suffix != ".npz":
        raise ValueError("output_path must end with '.npz'.")

    if output_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing file: {output_path}"
        )
        
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    environment = gym.make(
        "myoLegWalk-v0",
        reset_type="random",
    )

    base_environment = environment.unwrapped
    teacher = DepRLTeacherController(environment)

    max_steps = int(environment.spec.max_episode_steps)

    trajectories = {
        "teacher_observation": [],
        "teacher_action": [],
        "excitation": [],
        "post_activation": [],
        "post_force": [],
        "post_power": [],
        "post_com_height": [],
        "post_forward_velocity": [],
    }

    accepted_seeds: list[int] = []
    rejected_seeds: list[int] = []

    try:
        for attempt_index in range(max_attempts):
            if len(accepted_seeds) >= number_of_rollouts:
                break

            episode_seed = first_seed + attempt_index

            # WalkEnvV0 在生成随机初态前需要显式设置自身随机数生成器。
            base_environment.seed(episode_seed)

            observation, _ = environment.reset(
                seed=episode_seed,
            )

            teacher.reset()

            episode_samples = {
                name: []
                for name in trajectories
            }

            terminated = False
            truncated = False
            current_episode_steps = 0

            for _ in range(max_steps):
                # observation[t] 与 teacher_action[t] 在积分前记录。
                teacher_observation = np.asarray(
                    observation,
                    dtype=np.float32,
                ).copy()

                teacher_action = teacher.compute(
                    teacher_observation,
                )

                (
                    next_observation,
                    _,
                    terminated,
                    truncated,
                    info,
                ) = environment.step(teacher_action)

                data = base_environment.mj_data

                # last_ctrl 是本步真实施加给肌肉的 excitation。
                excitation = np.asarray(
                    base_environment.last_ctrl,
                    dtype=np.float32,
                ).copy()

                # 以下信号均为执行当前动作并完成积分后的状态。
                post_activation = np.asarray(
                    data.act,
                    dtype=np.float32,
                ).copy()

                post_force = np.asarray(
                    data.actuator_force,
                    dtype=np.float32,
                ).copy()

                post_velocity = np.asarray(
                    data.actuator_velocity,
                    dtype=np.float32,
                ).copy()

                post_power = post_force * post_velocity

                post_com_height = float(
                    np.asarray(
                        info["obs_dict"]["height"],
                        dtype=np.float32,
                    ).reshape(-1)[0]
                )

                post_com_velocity = np.asarray(
                    info["obs_dict"]["com_vel"],
                    dtype=np.float32,
                ).reshape(-1)

                # myoLegWalk 的前进方向固定为 y 轴。
                post_forward_velocity = float(
                    post_com_velocity[1]
                )

                episode_samples[
                    "teacher_observation"
                ].append(teacher_observation)

                episode_samples[
                    "teacher_action"
                ].append(teacher_action)

                episode_samples[
                    "excitation"
                ].append(excitation)

                episode_samples[
                    "post_activation"
                ].append(post_activation)

                episode_samples[
                    "post_force"
                ].append(post_force)

                episode_samples[
                    "post_power"
                ].append(post_power.astype(np.float32))

                episode_samples[
                    "post_com_height"
                ].append(post_com_height)

                episode_samples[
                    "post_forward_velocity"
                ].append(post_forward_velocity)

                observation = next_observation
                current_episode_steps += 1

                if terminated or truncated:
                    break

            # TimeLimit 导致 truncated 是正常完成；
            # terminated 才表示骨盆过低或躯干姿态失稳。
            is_success = (
                not terminated
                and current_episode_steps == max_steps
            )

            if is_success:
                for name, samples in episode_samples.items():
                    trajectories[name].append(
                        np.asarray(
                            samples,
                            dtype=np.float32,
                        )
                    )

                accepted_seeds.append(episode_seed)

                print(
                    f"accepted seed={episode_seed:04d}, "
                    f"steps={current_episode_steps}"
                )
            else:
                rejected_seeds.append(episode_seed)

                print(
                    f"rejected seed={episode_seed:04d}, "
                    f"steps={current_episode_steps}"
                )

    finally:
        environment.close()

    if len(accepted_seeds) < number_of_rollouts:
        raise RuntimeError(
            "Not enough successful rollouts. "
            f"accepted={len(accepted_seeds)}, "
            f"requested={number_of_rollouts}, "
            f"attempts={max_attempts}."
        )



    # 所有成功轨迹长度相同，因此保存为规则数组：
    # [number_of_rollouts, 1000, feature_dimension]。
    np.savez_compressed(
        output_path,
        teacher_observation=np.stack(
            trajectories["teacher_observation"],
            axis=0,
        ),
        teacher_action=np.stack(
            trajectories["teacher_action"],
            axis=0,
        ),
        excitation=np.stack(
            trajectories["excitation"],
            axis=0,
        ),
        post_activation=np.stack(
            trajectories["post_activation"],
            axis=0,
        ),
        post_force=np.stack(
            trajectories["post_force"],
            axis=0,
        ),
        post_power=np.stack(
            trajectories["post_power"],
            axis=0,
        ),
        post_com_height=np.stack(
            trajectories["post_com_height"],
            axis=0,
        ),
        post_forward_velocity=np.stack(
            trajectories["post_forward_velocity"],
            axis=0,
        ),
        accepted_seed=np.asarray(
            accepted_seeds,
            dtype=np.int64,
        ),
        rejected_seed=np.asarray(
            rejected_seeds,
            dtype=np.int64,
        ),
        control_dt=np.asarray(
            [base_environment.dt],
            dtype=np.float32,
        ),
        max_steps=np.asarray(
            [max_steps],
            dtype=np.int32,
        ),
    )

    print(
        f"\nsaved {len(accepted_seeds)} successful rollouts "
        f"to {output_path}"
    )

    print(
        f"saved frames: {len(accepted_seeds) * max_steps}"
    )

    print(
        f"rejected candidates: {len(rejected_seeds)}"
    )

    return output_path


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--output",
        type=Path,
        required=True,
    )

    parser.add_argument(
        "--rollouts",
        type=int,
        default=32,
    )

    parser.add_argument(
        "--first-seed",
        type=int,
        default=0,
    )

    parser.add_argument(
        "--max-attempts",
        type=int,
        default=128,
    )

    arguments = parser.parse_args()

    collect_teacher_rollouts(
        output_path=arguments.output,
        number_of_rollouts=arguments.rollouts,
        first_seed=arguments.first_seed,
        max_attempts=arguments.max_attempts,
    )


if __name__ == "__main__":
    main()