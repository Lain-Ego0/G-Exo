"""Collect exact-cycle baselines for privileged C-scheme training rewards."""

from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path

import numpy as np

from RL.env.kinesis.baseline_reference import (
    DEFAULT_PHYSICAL_BASELINE_DIR,
    BaselineReference,
    baseline_path,
)
from RL.env.kinesis.oracle_phase import extract_oracle_phase


RL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = RL_ROOT / "outputs/kinesis_cycle_baseline_c"
DEFAULT_MOTIONS = "2,8,9,11,16,38,43,52,64,82,99"
CONTROL_DT = 0.02


def parse_motion_ids(text: str) -> tuple[int, ...]:
    return tuple(int(item.strip()) for item in text.split(",") if item.strip())


def collect(environment, *, seed: int) -> dict:
    """Run one paired zero-assist episode through the actual Gym environment."""

    _, reset_info = environment.reset(seed=seed)
    records = {
        "time_s": [],
        "touch": [],
        "sensor_frame": [],
        "activation_cost": [],
        "muscle_effort_torque_cost": [],
        "human_torque": [],
        "torque_cost": [],
        "tracking_mse": [],
        "mpjpe_mm": [],
    }
    terminated = False
    truncated = False
    for _ in range(environment.max_episode_steps):
        _, _, terminated, truncated, info = environment.step(
            np.zeros(4, dtype=np.float32)
        )
        touch = np.asarray(environment.agent.env.get_touch(), dtype=np.float64)
        if touch.size < 4:
            raise RuntimeError("Kinesis returned fewer than four touch sensors.")
        human_torque = np.asarray(info["human_torque"], dtype=np.float64)
        records["time_s"].append(float(info["time_s"]))
        records["touch"].append(touch[:4].copy())
        records["sensor_frame"].append(environment.latest_raw_sensor_frame)
        records["activation_cost"].append(
            float(info["target_activation_cost"])
        )
        records["muscle_effort_torque_cost"].append(
            float(info["muscle_effort_torque_cost"])
        )
        records["human_torque"].append(human_torque.copy())
        records["torque_cost"].append(float(np.mean(np.abs(human_torque))))
        records["tracking_mse"].append(float(info["tracking_mse"]))
        records["mpjpe_mm"].append(float(info["mpjpe_mm"]))
        if terminated or truncated:
            break

    trace = {
        name: np.asarray(values, dtype=np.float64)
        for name, values in records.items()
    }
    trace["sensor_frame"] = trace["sensor_frame"].astype(np.float32)
    phase = extract_oracle_phase(trace["touch"], dt=CONTROL_DT)
    cycle_count = len(np.unique(phase.cycle_id[phase.valid]))
    if cycle_count < 1:
        return {
            "valid": False,
            "seed": seed,
            "rejection_reason": "no_complete_cycle",
            "cycle_count": cycle_count,
            "terminated": terminated,
            "truncated": truncated,
        }
    # The offline oracle backfills a debounced contact to the first threshold
    # crossing.  Online reward can only confirm it one frame later, so keep a
    # separate cycle index with exactly the same causal boundaries as training.
    reward_cycle_id = np.full(len(phase.cycle_id), -1, dtype=np.int64)
    for cycle_id in np.unique(phase.cycle_id[phase.valid]):
        oracle_indices = np.flatnonzero(phase.cycle_id == cycle_id)
        start = int(oracle_indices[0]) + 1
        stop = int(oracle_indices[-1]) + 2
        if stop <= len(reward_cycle_id):
            reward_cycle_id[start:stop] = int(cycle_id)
    return {
        **trace,
        "motion_id": int(environment.motion_id),
        "seed": int(reset_info["episode_seed"]),
        "valid": bool(truncated and not terminated),
        "rejection_reason": (
            "none" if truncated and not terminated else "episode_terminated"
        ),
        "kind": "baseline",
        "control_dt": CONTROL_DT,
        "phase": phase.phase,
        "phase_rate_hz": phase.phase_rate_hz,
        "cycle_id": phase.cycle_id,
        "reward_cycle_id": reward_cycle_id,
        "phase_valid": phase.valid,
        "contact_on_threshold": phase.contact_on_threshold,
        "contact_off_threshold": phase.contact_off_threshold,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-ids", default=DEFAULT_MOTIONS)
    parser.add_argument("--source-baseline-dir", type=Path, default=DEFAULT_PHYSICAL_BASELINE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--warmup-steps", type=int, default=50)
    parser.add_argument("--max-steps", type=int, default=500)
    args = parser.parse_args()
    motions = parse_motion_ids(args.motion_ids)
    args.output.mkdir(parents=True, exist_ok=True)

    if len(motions) > 1:
        for motion_id in motions:
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "RL.runners.collect_kinesis_cycle_baseline",
                    "--motion-ids",
                    str(motion_id),
                    "--source-baseline-dir",
                    str(args.source_baseline_dir),
                    "--output",
                    str(args.output),
                    "--warmup-steps",
                    str(args.warmup_steps),
                    "--max-steps",
                    str(args.max_steps),
                ],
                check=True,
            )
        print("cycle baseline directory:", args.output.resolve())
        return

    # Delayed import keeps this module inspectable outside the Kinesis env.
    from RL.env.kinesis.exo_env import KinesisExoEnv

    for motion_id in motions:
        source = BaselineReference(args.source_baseline_dir, motion_id)
        environment = KinesisExoEnv(
            motion_id=motion_id,
            baseline_dir=args.source_baseline_dir,
            warmup_steps=args.warmup_steps,
            max_episode_steps=args.max_steps,
            strict_baseline_seed=True,
            use_tcn=False,
        )
        try:
            for seed in source.seeds:
                rollout = collect(environment, seed=seed)
                if not bool(rollout["valid"]):
                    print(
                        f"rejected motion={motion_id:03d} seed={seed:06d} "
                        f"reason={rollout['rejection_reason']} "
                        f"cycles={rollout.get('cycle_count', 'unknown')}"
                    )
                    continue
                path = baseline_path(args.output, motion_id, seed)
                np.savez_compressed(path, **rollout)
                cycles = len(np.unique(rollout["cycle_id"][rollout["phase_valid"]]))
                print(
                    f"accepted motion={motion_id:03d} seed={seed:06d} "
                    f"frames={len(rollout['time_s'])} cycles={cycles}"
                )
        finally:
            environment.close()


if __name__ == "__main__":
    main()
