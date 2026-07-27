from __future__ import annotations

import numpy as np

import myosuite
from myosuite.utils import gym

from RL.env.myosuite.teacher_controller import (
    DepRLTeacherController,
)

def evaluate_teacher(
    number_of_episodes: int = 20,
    max_steps:int = 1000,
    seed:int = 0,
) -> dict[str,float]:
    if number_of_episodes <= 0:
        raise ValueError("number_of_episodes must be positive.")
    
    if max_steps <= 0:
        raise ValueError("max_steps must be positive.")

    environment = gym.make(
        "myoLegWalk-v0",
        reset_type="random",
    )
    
    teacher = DepRLTeacherController(environment)
    base_environment = environment.unwrapped

    episode_returns: list[float] = []
    episode_steps: list[int] = []

    terminated_episodes = 0

    saturated_action_count = 0
    action_value_count = 0

    excitation_sum = 0.0
    excitation_min = np.inf
    excitation_max = -np.inf###为什么max是-inf？
    
    activation_sum = 0.0
    activation_max = -np.inf

    muscle_force_abs_sum = 0.0
    muscle_power_abs_sum = 0.0
    muscle_value_count = 0

    forward_speed_sum = 0.0
    com_height_min = np.inf
    state_sample_count = 0

    right_contact_steps = 0
    left_contact_steps = 0
    
    try:
        for episode in range(number_of_episodes):
            episode_seed = seed + episode
            
            base_environment.seed(episode_seed)  # 设置环境的随机种子
            
            observation,_ = environment.reset(
                seed = seed + episode,
            )
            
            teacher.reset()
            
            episode_return = 0.0
            current_episode_steps = 0
            termination_reason = "manual_step_limit"
            
            for _ in range(max_steps):
                action = teacher.compute(observation)
                
                (
                    observation,
                    reward,
                    terminated,
                    truncated,
                    info,
                ) = environment.step(action)
                
                episode_return += float(reward)
                current_episode_steps += 1
                
                data = base_environment.mj_data
                
                excitation = np.asarray(
                    base_environment.last_ctrl,
                    dtype=np.float64,
                )
                
                activation = np.asarray(
                    data.act,
                    dtype=np.float64,
                )
                
                muscle_force = np.asarray(
                    data.actuator_force,
                    dtype=np.float64,
                )
                
                muscle_velocity = np.asarray(
                    data.actuator_velocity,
                    dtype=np.float64,
                )
                
                muscle_power = muscle_force * muscle_velocity
                
                saturated_action_count += int(
                    np.count_nonzero(np.abs(action) >= 0.99)
                )
                action_value_count += int(action.size)
                
                excitation_sum += float(np.sum(excitation))
                excitation_min = min(
                    excitation_min,
                    float(np.min(excitation)),
                )
                excitation_max = max(
                    excitation_max,
                    float(np.max(excitation)),
                )

                activation_sum += float(np.sum(activation))
                activation_max = max(
                    activation_max,
                    float(np.max(activation)),
                )

                muscle_force_abs_sum += float(
                    np.sum(np.abs(muscle_force))
                )
                muscle_power_abs_sum += float(
                    np.sum(np.abs(muscle_power))
                )
                muscle_value_count += int(muscle_force.size)
                
                com_velocity = np.asarray(
                    info["obs_dict"]["com_vel"],
                    dtype=np.float64,
                ).reshape(-1) #reshape(-1)是什么意思
                
                forward_speed_sum += float(com_velocity[1])
                
                com_height = float(
                    np.asarray(
                        info["obs_dict"]["height"],
                        dtype=np.float64,
                    ).reshape(-1)[0]
                )

                com_height_min = min(
                    com_height_min,
                    com_height,
                )
                
                right_contact = (
                    np.linalg.norm(
                        np.asarray(data.sensor("r_foot").data)
                    )
                    > 1e-6
                    or np.linalg.norm(
                        np.asarray(data.sensor("r_toes").data)
                    )
                    > 1e-6
                )
                
                left_contact = (
                    np.linalg.norm(
                        np.asarray(data.sensor("l_foot").data)
                    )
                    > 1e-6
                    or np.linalg.norm(
                        np.asarray(data.sensor("l_toes").data)
                    )
                    > 1e-6
                )

                right_contact_steps += int(right_contact)
                left_contact_steps += int(left_contact)
                state_sample_count += 1
                
                if terminated or truncated:
                    if terminated:
                        current_height = float(
                            np.asarray(
                                info["obs_dict"]["height"]
                            ).reshape(-1)[0]
                        )

                        if current_height < float(
                            base_environment.min_height
                        ):
                            termination_reason = "low_com_height"
                        else:
                            termination_reason = "root_rotation"

                        terminated_episodes += 1
                    else:
                        termination_reason = "time_limit"

                    break
                
            episode_returns.append(episode_return)
            episode_steps.append(current_episode_steps)
            
            print(
                f"episode {episode:02d}: ",
                f"(seed={episode_seed:03d}): "
                f"steps={current_episode_steps:4d}, "
                f"return={episode_return:9.3f}, "
                f"reason={termination_reason}"
            )
            
    finally:
        environment.close()
        
    muscle_value_count = max(muscle_value_count, 1)
    action_value_count = max(action_value_count, 1)
    state_sample_count = max(state_sample_count, 1)

    summary = {
        "mean_episode_return": float(
            np.mean(episode_returns)
        ),
        "std_episode_return": float(
            np.std(episode_returns)
        ),
        "mean_episode_steps": float(
            np.mean(episode_steps)
        ),
        "termination_rate": (
            terminated_episodes / number_of_episodes
        ),
        "action_saturation_ratio": (
            saturated_action_count / action_value_count
        ),
        "mean_excitation": (
            excitation_sum / muscle_value_count
        ),
        "minimum_excitation": float(excitation_min),
        "maximum_excitation": float(excitation_max),
        "mean_activation": (
            activation_sum / muscle_value_count
        ),
        "maximum_activation": float(activation_max),
        "mean_absolute_muscle_force": (
            muscle_force_abs_sum / muscle_value_count
        ),
        "mean_absolute_muscle_power": (
            muscle_power_abs_sum / muscle_value_count
        ),
        "mean_forward_speed": (
            forward_speed_sum / state_sample_count
        ),
        "minimum_com_height": float(
            com_height_min
        ),
        "right_contact_ratio": (
            right_contact_steps / state_sample_count
        ),
        "left_contact_ratio": (
            left_contact_steps / state_sample_count
        ),
    }

    return summary

def main() -> None:
    summary = evaluate_teacher(
        number_of_episodes=20,
        max_steps=1000,
        seed=0,
    )

    print("\nTeacher evaluation summary")

    for name, value in summary.items():
        print(f"{name}: {value:.6f}")


if __name__ == "__main__":
    main()