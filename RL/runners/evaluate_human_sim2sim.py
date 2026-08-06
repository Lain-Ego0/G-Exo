"""评估平地人体策略，并做MyoSuite参数迁移测试。"""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

from RL.env.myosuite.human_balance_env import (
    DEFAULT_MANIFEST,
    HumanBalanceEnv,
)


RL_ROOT = Path(__file__).resolve().parents[1]


def _ratio(value: float, baseline: float) -> float:
    if baseline <= 0.0:
        return 0.0
    return float(value / baseline)


def play_episode(
    policy: PPO | None,
    *,
    manifest: Path,
    seed: int,
    condition: str,
    mode: str,
    max_steps: int,
    show_muscles: bool,
) -> None:
    """实时播放策略或零残差基线。"""

    if mode == "policy" and policy is None:
        raise ValueError("Policy playback needs --model.")

    shifted = condition == "shifted"
    environment = HumanBalanceEnv(
        manifest_path=manifest,
        split="validation",
        max_episode_steps=max_steps,
        support_range=(0.35, 0.35) if shifted else (0.5, 0.5),
        mass_scale=1.05 if shifted else 1.0,
        damping_scale=1.10 if shifted else 1.0,
        friction_scale=0.90 if shifted else 1.0,
    )

    try:
        import mujoco
        import mujoco.viewer

        observation, info = environment.reset(seed=seed)
        model = environment.base.mj_model
        data = environment.base.mj_data
        pelvis_id = int(model.body("pelvis").id)

        print(
            f"playing mode={mode}, condition={condition}, "
            f"subject={info['subject']}, trial={info['trial']}"
        )

        with mujoco.viewer.launch_passive(model, data) as viewer:
            viewer.opt.flags[
                mujoco.mjtVisFlag.mjVIS_TENDON
            ] = show_muscles
            viewer.cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
            viewer.cam.trackbodyid = pelvis_id
            viewer.cam.distance = 3.0
            viewer.cam.azimuth = 145.0
            viewer.cam.elevation = -12.0

            for step_index in range(max_steps):
                if not viewer.is_running():
                    break

                wall_start = time.perf_counter()
                if mode == "zero":
                    action = np.zeros(
                        environment.action_space.shape,
                        dtype=np.float32,
                    )
                else:
                    action, _policy_state = policy.predict(
                        observation,
                        deterministic=True,
                    )

                (
                    observation,
                    reward,
                    terminated,
                    truncated,
                    step_info,
                ) = environment.step(action)

                if step_index % 50 == 0:
                    print(
                        f"step={step_index:04d} "
                        f"reward={reward:7.3f} "
                        f"q_rmse={step_info['q_rmse_rad']:.3f} "
                        f"support={step_info['support_scale']:.2f}"
                    )

                viewer.sync()
                elapsed = time.perf_counter() - wall_start
                time.sleep(max(0.0, float(environment.base.dt) - elapsed))

                if terminated or truncated:
                    print(
                        f"episode ended at step {step_index + 1}: "
                        f"{step_info['termination_reason']}"
                    )
                    break
    finally:
        environment.close()


def evaluate(
    model: PPO | None,
    *,
    manifest: Path,
    seed: int,
    episodes: int,
    mass_scale: float,
    damping_scale: float,
    friction_scale: float,
    support_scale: float,
) -> dict[str, float]:
    environment = HumanBalanceEnv(
        manifest_path=manifest,
        split="validation",
        max_episode_steps=1000,
        support_range=(support_scale, support_scale),
        mass_scale=mass_scale,
        damping_scale=damping_scale,
        friction_scale=friction_scale,
    )

    returns = []
    lengths = []
    rmses = []
    saturation_ratios = []
    successes = []

    try:
        for episode in range(episodes):
            observation, _ = environment.reset(
                seed=seed + episode
            )
            episode_return = 0.0
            episode_rmses = []
            episode_saturation_ratios = []
            terminated = False

            for step_index in range(
                environment.max_episode_steps
            ):
                if model is None:
                    action = np.zeros(
                        environment.action_space.shape,
                        dtype=np.float32,
                    )
                else:
                    action, _policy_state = model.predict(
                        observation,
                        deterministic=True,
                    )

                (
                    observation,
                    reward,
                    terminated,
                    truncated,
                    info,
                ) = environment.step(action)

                episode_return += float(reward)
                episode_rmses.append(
                    float(info["q_rmse_rad"])
                )
                episode_saturation_ratios.append(
                    float(info["muscle_saturation_ratio"])
                )

                if terminated or truncated:
                    break

            returns.append(episode_return)
            lengths.append(step_index + 1)
            rmses.append(float(np.mean(episode_rmses)))
            saturation_ratios.append(
                float(np.mean(episode_saturation_ratios))
            )
            successes.append(
                float(not terminated)
            )
    finally:
        environment.close()

    return {
        "mean_return": float(np.mean(returns)),
        "mean_length": float(np.mean(lengths)),
        "success_rate": float(np.mean(successes)),
        "mean_q_rmse_rad": float(np.mean(rmses)),
        "mean_muscle_saturation_ratio": float(
            np.mean(saturation_ratios)
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--model",
        type=Path,
        default=None,
        help="PPO zip path; omit to evaluate zero residual.",
    )
    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    parser.add_argument(
        "--episodes",
        type=int,
        default=10,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=1000,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=RL_ROOT / "outputs/human_balance/sim2sim_report.json",
    )
    parser.add_argument(
        "--require-pass",
        action="store_true",
    )
    parser.add_argument(
        "--play",
        choices=("nominal", "shifted"),
        default=None,
    )
    parser.add_argument(
        "--play-mode",
        choices=("policy", "zero", "both"),
        default="policy",
    )
    parser.add_argument(
        "--play-steps",
        type=int,
        default=1000,
    )
    parser.add_argument(
        "--show-muscles",
        action="store_true",
    )
    arguments = parser.parse_args()

    model = None
    if arguments.model is not None:
        model = PPO.load(
            arguments.model,
            device="cpu",
        )
    if (
        arguments.play is not None
        and arguments.play_mode in ("policy", "both")
        and model is None
    ):
        parser.error("--play-mode policy/both requires --model.")

    nominal = evaluate(
        model,
        manifest=arguments.manifest,
        seed=arguments.seed,
        episodes=arguments.episodes,
        mass_scale=1.0,
        damping_scale=1.0,
        friction_scale=1.0,
        support_scale=0.5,
    )
    shifted = evaluate(
        model,
        manifest=arguments.manifest,
        seed=arguments.seed + 100,
        episodes=arguments.episodes,
        mass_scale=1.05,
        damping_scale=1.10,
        friction_scale=0.90,
        support_scale=0.35,
    )

    report = {
        "model": str(arguments.model) if arguments.model else "zero_residual",
        "trained_timesteps": (
            int(model.num_timesteps) if model is not None else 0
        ),
        "nominal": nominal,
        "parameter_shifted": shifted,
        "parameter_shift": {
            "mass_scale": 1.05,
            "damping_scale": 1.10,
            "friction_scale": 0.90,
            "support_scale": 0.35,
        },
    }

    if model is not None:
        zero_nominal = evaluate(
            None,
            manifest=arguments.manifest,
            seed=arguments.seed,
            episodes=arguments.episodes,
            mass_scale=1.0,
            damping_scale=1.0,
            friction_scale=1.0,
            support_scale=0.5,
        )
        zero_shifted = evaluate(
            None,
            manifest=arguments.manifest,
            seed=arguments.seed + 100,
            episodes=arguments.episodes,
            mass_scale=1.05,
            damping_scale=1.10,
            friction_scale=0.90,
            support_scale=0.35,
        )
        report["zero_residual"] = {
            "nominal": zero_nominal,
            "parameter_shifted": zero_shifted,
        }
        report["improvement"] = {
            "nominal_length_ratio": _ratio(
                nominal["mean_length"],
                zero_nominal["mean_length"],
            ),
            "shifted_length_ratio": _ratio(
                shifted["mean_length"],
                zero_shifted["mean_length"],
            ),
            "success_retention_ratio": _ratio(
                shifted["success_rate"],
                nominal["success_rate"],
            ),
        }
        improvement = report["improvement"]
        gate = {
            "nominal_success": nominal["success_rate"] >= 0.8,
            "success_retention": improvement[
                "success_retention_ratio"
            ] >= 0.7,
            "baseline_improvement": improvement[
                "nominal_length_ratio"
            ] >= 1.25,
            "tracking_rmse": nominal["mean_q_rmse_rad"] < 0.30,
            "muscle_saturation": nominal[
                "mean_muscle_saturation_ratio"
            ] < 0.10,
        }
        gate["passed"] = all(gate.values())
        report["gate"] = gate

    output = arguments.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2),
        encoding="utf-8",
    )

    print(json.dumps(report, indent=2))
    print("saved:", output)

    if arguments.play is not None:
        modes = (
            ("zero", "policy")
            if arguments.play_mode == "both"
            else (arguments.play_mode,)
        )
        for mode in modes:
            play_episode(
                model,
                manifest=arguments.manifest,
                seed=(
                    arguments.seed + 100
                    if arguments.play == "shifted"
                    else arguments.seed
                ),
                condition=arguments.play,
                mode=mode,
                max_steps=arguments.play_steps,
                show_muscles=arguments.show_muscles,
            )

    if arguments.require_pass:
        if not report.get("gate", {}).get("passed", False):
            raise SystemExit("sim2sim-lite gate failed")


if __name__ == "__main__":
    main()
