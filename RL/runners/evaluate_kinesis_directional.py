"""Evaluate Kinesis target-goal walking before exoskeleton integration."""

from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np
from scipy.spatial.transform import Rotation

from RL.env.kinesis.directional_teacher import (
    make_directional_agent,
    make_directional_policy,
    missing_directional_assets,
)


DEFAULT_OUTPUT = Path(
    "RL/outputs/kinesis_directional/baseline.json"
)


def set_command(environment, direction_rad: float, speed_m_s: float) -> None:
    """Set the moving local goal used by MyoLegsDirectional."""

    environment.stop = False
    environment.direction = float(direction_rad)
    environment.speed = np.asarray(
        [-abs(speed_m_s), 0.0, 0.0],
        dtype=np.float64,
    )
    root = environment.get_body_xpos()[0]
    environment.goal_pos = root + Rotation.from_euler(
        "z", environment.direction
    ).apply(environment.speed)
    environment.previous_tracking_distance = (
        environment.compute_tracking_distance()
    )


def run_episode(
    agent,
    policy,
    *,
    seed: int,
    steps: int,
    direction_rad: float,
    speed_m_s: float,
    render: bool,
) -> dict[str, object]:
    """Run one commanded walk and collect physical metrics."""

    environment = agent.env
    policy.reset(seed)
    observation, _ = environment.reset(seed=seed)
    set_command(environment, direction_rad, speed_m_s)
    observation = environment.compute_observations()

    root_start = environment.get_body_xpos()[0].copy()
    previous_root = root_start.copy()
    direction = Rotation.from_euler("z", direction_rad).apply(
        np.asarray([-1.0, 0.0, 0.0])
    )

    heights = []
    activations = []
    speeds = []
    returns = 0.0
    terminated = False
    truncated = False

    for step in range(steps):
        started = time.monotonic()
        action = policy(np.asarray(observation, dtype=np.float32))
        observation, reward, terminated, truncated, _ = environment.step(
            action
        )

        current_root = environment.get_body_xpos()[0].copy()
        root_velocity = (current_root - previous_root) / environment.dt
        previous_root = current_root
        heights.append(float(current_root[2]))
        activations.append(
            float(np.mean(np.square(environment.mj_data.act)))
        )
        speeds.append(float(np.dot(root_velocity, direction)))
        returns += float(reward)

        if render:
            remaining = environment.dt - (time.monotonic() - started)
            if remaining > 0.0:
                time.sleep(remaining)
        if terminated or truncated:
            break

    displacement = environment.get_body_xpos()[0] - root_start
    return {
        "seed": seed,
        "steps": step + 1,
        "completed_requested_steps": bool(step + 1 == steps),
        "terminated": bool(terminated),
        "truncated": bool(truncated),
        "episode_return": returns,
        "forward_displacement_m": float(np.dot(displacement, direction)),
        "lateral_displacement_m": float(
            np.linalg.norm(displacement[:2] - np.dot(displacement, direction) * direction[:2])
        ),
        "mean_forward_speed_m_s": float(np.mean(speeds)),
        "minimum_root_height_m": float(np.min(heights)),
        "mean_activation_squared": float(np.mean(activations)),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--direction-deg", type=float, default=0.0)
    parser.add_argument("--speed-m-s", type=float, default=1.0)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    missing = missing_directional_assets()
    if missing:
        print("Directional model is not ready. Missing:")
        for path in missing:
            print(" -", path)
        raise SystemExit(2)

    agent = make_directional_agent(render=args.render)
    policy = make_directional_policy(agent)
    rows = []
    try:
        for episode in range(args.episodes):
            row = run_episode(
                agent,
                policy,
                seed=args.first_seed + episode,
                steps=args.steps,
                direction_rad=np.deg2rad(args.direction_deg),
                speed_m_s=args.speed_m_s,
                render=args.render,
            )
            rows.append(row)
            print(
                f"seed={row['seed']:03d} steps={row['steps']:4d} "
                f"speed={row['mean_forward_speed_m_s']:+.3f} m/s "
                f"height={row['minimum_root_height_m']:.3f} m "
                f"activation={row['mean_activation_squared']:.4f}"
            )
    finally:
        agent.env.close()

    report = {
        "direction_deg": args.direction_deg,
        "commanded_speed_m_s": args.speed_m_s,
        "rows": rows,
        "summary": {
            "completion_rate": float(
                np.mean([row["completed_requested_steps"] for row in rows])
            ),
            "mean_forward_speed_m_s": float(
                np.mean([row["mean_forward_speed_m_s"] for row in rows])
            ),
            "minimum_root_height_m": float(
                np.min([row["minimum_root_height_m"] for row in rows])
            ),
            "mean_activation_squared": float(
                np.mean([row["mean_activation_squared"] for row in rows])
            ),
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)
    print("report:", args.output)


if __name__ == "__main__":
    main()
