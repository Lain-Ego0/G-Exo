"""Collect successful zero-assistance rollouts for physical Reward V3."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

from RL.env.kinesis.assist_backend import AssistBackend
from RL.env.kinesis.baseline_reference import (
    DEFAULT_PHYSICAL_BASELINE_DIR,
    baseline_path,
    tracking_metrics,
)
from RL.env.kinesis.exo_env import CONTROL_DT
from RL.env.kinesis.physical_exo import DynamicExoSystem
from RL.env.kinesis.teacher import KinesisPolicy, make_agent


DEFAULT_MOTIONS = "2,8,9,11,16,38,43,52,64,82,99"


def parse_motion_ids(text: str) -> tuple[int, ...]:
    return tuple(
        int(item.strip())
        for item in text.split(",")
        if item.strip()
    )


def collect_rollout(
    backend: AssistBackend,
    policy: KinesisPolicy,
    *,
    seed: int,
    warmup_steps: int,
    max_steps: int,
) -> dict[str, np.ndarray | int | bool]:
    """Run one zero-torque episode with the same warmup as PPO."""

    policy.reset(seed)
    backend.reset(seed=seed)
    zero_torque = np.zeros(4, dtype=np.float32)

    state = None
    for _ in range(warmup_steps):
        state = backend.step(zero_torque, policy)
        if state["terminated"] or state["truncated"]:
            return {"valid": False, "seed": seed}

    assert state is not None
    time_s: list[float] = []
    activation_cost: list[float] = []
    muscle_effort_torque_cost: list[float] = []
    human_torque: list[np.ndarray] = []
    torque_cost: list[float] = []
    tracking_mse: list[float] = []
    mpjpe_mm: list[float] = []

    for _ in range(max_steps):
        state = backend.step(zero_torque, policy)
        raw_activation_cost = float(state["target_activation_cost"])
        raw_muscle_effort = float(
            state["muscle_effort_torque_cost"]
        )
        current_human_torque = np.asarray(
            state["muscle_torque"],
            dtype = np.float64,
        )
        raw_torque_cost = float(
            np.mean(np.abs(current_human_torque))
        )
        mse, mpjpe_m = tracking_metrics(
            backend.env,
            float(state["time"]),
        )

        time_s.append(float(state["time"]))
        activation_cost.append(raw_activation_cost)
        muscle_effort_torque_cost.append(raw_muscle_effort)
        human_torque.append(current_human_torque.copy())
        torque_cost.append(raw_torque_cost)
        tracking_mse.append(mse)
        mpjpe_mm.append(1000.0 * mpjpe_m)

        if state["terminated"] or state["truncated"]:
            break

    valid = bool(state["truncated"] and not state["terminated"])
    return {
        "seed": seed,
        "valid": valid,
        "time_s": np.asarray(
            time_s,
            dtype=np.float64,
        ),
        "activation_cost": np.asarray(
            activation_cost,
            dtype=np.float64,
        ),
        "muscle_effort_torque_cost": np.asarray(
            muscle_effort_torque_cost,
            dtype=np.float64,
        ),
        "human_torque": np.asarray(
            human_torque,
            dtype=np.float64,
        ),
        "torque_cost": np.asarray(
            torque_cost,
            dtype=np.float64,
        ),
        "tracking_mse": np.asarray(
            tracking_mse,
            dtype=np.float64,
        ),
        "mpjpe_mm": np.asarray(
            mpjpe_mm,
            dtype=np.float64,
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-ids", default=DEFAULT_MOTIONS)
    parser.add_argument(
        "--output", type=Path, default=DEFAULT_PHYSICAL_BASELINE_DIR
    )
    parser.add_argument(
        "--ideal",
        action="store_true",
        help="Collect the legacy massless/direct-torque baseline.",
    )
    parser.add_argument("--rollouts-per-motion", type=int, default=4)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--max-attempts", type=int, default=32)
    parser.add_argument("--warmup-steps", type=int, default=25)
    parser.add_argument("--max-steps", type=int, default=500)
    args = parser.parse_args()

    if args.rollouts_per_motion < 1 or args.max_attempts < 1:
        raise ValueError("Rollout and attempt counts must be positive.")

    args.output.mkdir(parents=True, exist_ok=True)
    motion_ids = parse_motion_ids(args.motion_ids)

    # Kinesis owns process-global motion and RNG caches. Isolating each motion
    # prevents a previously loaded agent from changing a later baseline.
    if len(motion_ids) > 1:
        for motion_id in motion_ids:
            command = [
                    sys.executable,
                    "-m",
                    "RL.runners.collect_kinesis_baseline",
                    "--motion-ids",
                    str(motion_id),
                    "--output",
                    str(args.output),
                    "--rollouts-per-motion",
                    str(args.rollouts_per_motion),
                    "--first-seed",
                    str(args.first_seed),
                    "--max-attempts",
                    str(args.max_attempts),
                    "--warmup-steps",
                    str(args.warmup_steps),
                    "--max-steps",
                    str(args.max_steps),
                ]
            if args.ideal:
                command.append("--ideal")
            subprocess.run(command, check=True)
        print("baseline directory:", args.output.resolve())
        return

    for motion_id in motion_ids:
        agent = make_agent(motion_id, render=False)
        policy = KinesisPolicy(agent)
        physical_exo = (
            None if args.ideal else DynamicExoSystem(agent.env)
        )
        backend = AssistBackend(
            agent.env,
            exo_control_dt=CONTROL_DT,
            torque_limit_nm=17.0,
            torque_rate_limit_nm_s=50.0,
            load_sharing=True,
            physical_exo=physical_exo,
        )
        accepted = 0

        try:
            for attempt in range(args.max_attempts):
                seed = args.first_seed + attempt
                rollout = collect_rollout(
                    backend,
                    policy,
                    seed=seed,
                    warmup_steps=args.warmup_steps,
                    max_steps=args.max_steps,
                )
                if not bool(rollout["valid"]):
                    print(
                        f"rejected motion={motion_id:03d} seed={seed:06d}"
                    )
                    continue

                output_path = baseline_path(
                    args.output,
                    motion_id,
                    seed,
                )
                np.savez_compressed(output_path, **rollout)
                accepted += 1
                print(
                    f"accepted motion={motion_id:03d} seed={seed:06d} "
                    f"frames={len(rollout['time_s'])}"
                )
                if accepted >= args.rollouts_per_motion:
                    break
        finally:
            backend.close()

        if accepted < args.rollouts_per_motion:
            raise RuntimeError(
                f"Motion {motion_id} produced only {accepted}/"
                f"{args.rollouts_per_motion} successful baselines."
            )

    print("baseline directory:", args.output.resolve())


if __name__ == "__main__":
    main()
