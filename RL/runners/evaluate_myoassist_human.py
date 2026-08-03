"""Evaluate an adapted 22-muscle checkpoint on the physical zero-assist model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.env.myoassist.human_adaptation import make_human_adaptation_env
from RL.env.myoassist.model_builder import DEFAULT_PHYSICAL_OUTPUT_PATH, build_model
from RL.env.myoassist.policy_transfer import FrozenHumanPolicy, file_sha256


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "RL" / "outputs" / "myoassist_human_evaluation.json"


def run_episode(
    policy: FrozenHumanPolicy,
    *,
    seed: int,
    speed_m_s: float,
    steps: int,
    model_path: Path = DEFAULT_PHYSICAL_OUTPUT_PATH,
) -> dict[str, float | int | bool | str]:
    environment = make_human_adaptation_env(
        seed=seed,
        max_episode_steps=steps,
        evaluate=True,
        model_path=model_path,
    )
    observation, reset_info = environment.reset(
        seed=seed,
        options={"target_speed": speed_m_s},
    )
    forward_speeds: list[float] = []
    pelvis_heights: list[float] = []
    pelvis_pitches: list[float] = []
    activation_costs: list[float] = []
    maximum_exo_torque = 0.0
    maximum_exo_actuator_force = 0.0
    maximum_exo_generalized_force = 0.0
    reason = "time_limit"
    simulation = environment.unwrapped.sim

    try:
        for step in range(steps):
            muscle_action = policy(observation)
            observation, _, terminated, truncated, _ = environment.step(
                muscle_action
            )
            forward_speeds.append(
                float(simulation.data.joint("pelvis_tx").qvel[0])
            )
            pelvis_heights.append(
                float(simulation.data.joint("pelvis_ty").qpos[0])
            )
            pelvis_pitches.append(
                float(simulation.data.joint("pelvis_tilt").qpos[0])
            )
            activation_costs.append(
                float(np.mean(np.square(simulation.data.act)))
            )
            maximum_exo_torque = max(
                maximum_exo_torque,
                float(np.max(np.abs(environment.last_exo_ctrl))),
            )
            maximum_exo_actuator_force = max(
                maximum_exo_actuator_force,
                float(np.max(np.abs(environment.last_exo_actuator_force))),
            )
            maximum_exo_generalized_force = max(
                maximum_exo_generalized_force,
                float(np.max(np.abs(environment.last_exo_generalized_force))),
            )
            if terminated:
                reason = "terminated"
                break
            if truncated:
                reason = "time_limit" if step + 1 == steps else "truncated"
                break
    finally:
        environment.close()

    completed_steps = len(forward_speeds)
    return {
        "seed": seed,
        "target_speed_m_s": speed_m_s,
        "reference_index": int(reset_info["reference_index"]),
        "steps": completed_steps,
        "success": completed_steps == steps and reason == "time_limit",
        "reason": reason,
        "mean_forward_speed_m_s": float(np.mean(forward_speeds)),
        "minimum_pelvis_height_m": float(np.min(pelvis_heights)),
        "maximum_absolute_pelvis_pitch_rad": float(
            np.max(np.abs(pelvis_pitches))
        ),
        "mean_activation_squared": float(np.mean(activation_costs)),
        "maximum_absolute_exo_torque_nm": maximum_exo_torque,
        "maximum_absolute_exo_actuator_force": maximum_exo_actuator_force,
        "maximum_absolute_exo_generalized_force_nm": (
            maximum_exo_generalized_force
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--speeds", default="0.8,1.0,1.25,1.5")
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()

    physical_model = build_model()
    checkpoint = args.checkpoint.expanduser().resolve(strict=True)
    policy = FrozenHumanPolicy(checkpoint, device=args.device)
    speeds = [float(value) for value in args.speeds.split(",")]
    seeds = [int(value) for value in args.seeds.split(",")]
    episodes = [
        run_episode(
            policy,
            seed=seed,
            speed_m_s=speed,
            steps=args.steps,
            model_path=physical_model,
        )
        for speed in speeds
        for seed in seeds
    ]
    report = {
        "schema": "gexo_myoassist_human_evaluation_v1",
        "checkpoint": str(checkpoint),
        "checkpoint_sha256": file_sha256(checkpoint),
        "physical_model": str(physical_model),
        "physical_model_sha256": file_sha256(physical_model),
        "control_hz": 50,
        "physics_hz": 1200,
        "exo_torque_nm": [0.0, 0.0, 0.0, 0.0],
        "episodes": episodes,
        "all_passed": all(bool(row["success"]) for row in episodes),
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")

    for row in episodes:
        print(
            f"speed={row['target_speed_m_s']:.2f} seed={row['seed']:03d} "
            f"phase={row['reference_index']:03d} steps={row['steps']:4d} "
            f"success={row['success']} mean_speed={row['mean_forward_speed_m_s']:.3f} "
            f"min_height={row['minimum_pelvis_height_m']:.3f}"
        )
    print(f"all passed: {report['all_passed']}")
    print(f"report: {output}")
    if args.require_pass and not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
