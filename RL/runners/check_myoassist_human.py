"""Archive deterministic-reset and zero-assist human-runtime evidence."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.env.myoassist.human_runtime import (
    CONTROL_DT,
    EXO_ACTION_DIM,
    make_human_runtime,
)
from RL.env.myoassist.policy_transfer import FrozenHumanPolicy


DEFAULT_OUTPUT = Path("RL/outputs/myoassist_human_check/report.json")


def _state_snapshot(environment) -> dict[str, np.ndarray | float | int]:
    return {
        "qpos": environment.sim.data.qpos.copy(),
        "qvel": environment.sim.data.qvel.copy(),
        "act": environment.sim.data.act.copy(),
        "time": float(environment.sim.data.time),
        "reference_index": int(environment._imitation_index),
        "target_speed": float(environment._target_velocity),
    }


def check_repeated_reset(*, seed: int, speed_m_s: float) -> dict[str, float]:
    environment = make_human_runtime(seed=seed, max_episode_steps=1000)
    options = {"reference_index": 0, "target_speed": speed_m_s}
    try:
        observation, _ = environment.reset(seed=seed, options=options)
        baseline = _state_snapshot(environment)
        baseline_observation = observation.copy()
        maximum_qpos_error = 0.0
        maximum_qvel_error = 0.0
        maximum_observation_error = 0.0

        for _ in range(10):
            observation, _ = environment.reset(seed=seed, options=options)
            current = _state_snapshot(environment)
            maximum_qpos_error = max(
                maximum_qpos_error,
                float(np.max(np.abs(current["qpos"] - baseline["qpos"]))),
            )
            maximum_qvel_error = max(
                maximum_qvel_error,
                float(np.max(np.abs(current["qvel"] - baseline["qvel"]))),
            )
            maximum_observation_error = max(
                maximum_observation_error,
                float(np.max(np.abs(observation - baseline_observation))),
            )
            if current["time"] != baseline["time"]:
                raise RuntimeError("Repeated reset did not restore simulation time.")
    finally:
        environment.close()

    return {
        "max_qpos_error": maximum_qpos_error,
        "max_qvel_error": maximum_qvel_error,
        "max_observation_error": maximum_observation_error,
    }


def run_zero_assist_rollout(
    *,
    policy: FrozenHumanPolicy,
    seed: int,
    speed_m_s: float,
    steps: int,
) -> dict[str, float | int | bool | str]:
    environment = make_human_runtime(seed=seed, max_episode_steps=steps)
    observation, _ = environment.reset(
        seed=seed,
        options={"reference_index": 0, "target_speed": speed_m_s},
    )
    pelvis_heights: list[float] = []
    forward_speeds: list[float] = []
    activation_costs: list[float] = []
    reason = "time_limit"

    try:
        for step in range(steps):
            human_action = policy(observation)
            combined_action = np.concatenate(
                (human_action, np.zeros(EXO_ACTION_DIM, dtype=np.float32))
            )
            observation, _, terminated, truncated, _ = environment.step(
                combined_action
            )
            pelvis_heights.append(
                float(environment.sim.data.joint("pelvis_ty").qpos[0])
            )
            forward_speeds.append(
                float(environment.sim.data.joint("pelvis_tx").qvel[0])
            )
            activation_costs.append(
                float(np.mean(np.square(environment.sim.data.act)))
            )
            if terminated:
                reason = "terminated"
                break
            if truncated:
                reason = "time_limit" if step + 1 == steps else "truncated"
                break
    finally:
        environment.close()

    completed_steps = len(pelvis_heights)
    return {
        "seed": seed,
        "target_speed_m_s": speed_m_s,
        "steps": completed_steps,
        "success": completed_steps == steps and reason == "time_limit",
        "reason": reason,
        "mean_forward_speed_m_s": float(np.mean(forward_speeds)),
        "minimum_pelvis_height_m": float(np.min(pelvis_heights)),
        "mean_activation_squared": float(np.mean(activation_costs)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speeds", default="0.8,1.25")
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    speeds = [float(value) for value in args.speeds.split(",")]
    seeds = [int(value) for value in args.seeds.split(",")]
    policy = FrozenHumanPolicy(device="cpu")
    reset_result = check_repeated_reset(seed=seeds[0], speed_m_s=speeds[0])
    rollouts = [
        run_zero_assist_rollout(
            policy=policy,
            seed=seed,
            speed_m_s=speed,
            steps=args.steps,
        )
        for speed in speeds
        for seed in seeds
    ]

    report = {
        "schema": "gexo_myoassist_human_check_v1",
        "control_dt_s": CONTROL_DT,
        "checkpoint_sha256": policy.checkpoint_sha256,
        "reset": reset_result,
        "rollouts": rollouts,
        "all_passed": (
            max(reset_result.values()) == 0.0
            and all(bool(row["success"]) for row in rollouts)
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )

    for row in rollouts:
        print(
            f"speed={row['target_speed_m_s']:.2f} seed={row['seed']:03d} "
            f"steps={row['steps']:4d} success={row['success']} "
            f"mean_speed={row['mean_forward_speed_m_s']:.3f} "
            f"min_height={row['minimum_pelvis_height_m']:.3f}"
        )
    print(f"reset: {reset_result}")
    print(f"report: {args.output}")
    if not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
