"""Pulse-test exoskeleton unloading on Kinesis directional walking."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.env.kinesis.assist_backend import AssistBackend, JOINT_NAMES
from RL.env.kinesis.directional_teacher import (
    make_directional_agent,
    make_directional_policy,
)
from RL.runners.diagnose_kinesis_compensation import analyze, run_rollout
from RL.runners.evaluate_kinesis_directional import set_command


CONTROL_DT = 0.02
DEFAULT_OUTPUT = Path(
    "RL/outputs/kinesis_directional_assist/report.json"
)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--joint", choices=JOINT_NAMES, default=JOINT_NAMES[0])
    parser.add_argument("--pulse-nm", type=float, default=1.0)
    parser.add_argument("--warmup-steps", type=int, default=100)
    parser.add_argument("--pulse-steps", type=int, default=5)
    parser.add_argument("--recovery-steps", type=int, default=25)
    parser.add_argument("--direction-deg", type=float, default=0.0)
    parser.add_argument("--speed-m-s", type=float, default=1.0)
    parser.add_argument("--no-load-sharing", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    joint_index = JOINT_NAMES.index(args.joint)
    direction_rad = float(np.deg2rad(args.direction_deg))

    agent = make_directional_agent(render=False)
    policy = make_directional_policy(agent)
    backend = AssistBackend(
        agent.env,
        exo_control_dt=CONTROL_DT,
        torque_rate_limit_nm_s=50.0,
        load_sharing=not args.no_load_sharing,
    )

    def configure(current_backend: AssistBackend) -> None:
        set_command(
            current_backend.env,
            direction_rad,
            args.speed_m_s,
        )
        current_backend.observation = np.asarray(
            current_backend.env.compute_observations(),
            dtype=np.float32,
        )

    common = {
        "seed": args.seed,
        "warmup_steps": args.warmup_steps,
        "pulse_steps": args.pulse_steps,
        "recovery_steps": args.recovery_steps,
        "after_reset": configure,
    }

    try:
        baseline = run_rollout(
            backend,
            policy,
            joint_index=None,
            pulse_nm=0.0,
            **common,
        )
        pulse = run_rollout(
            backend,
            policy,
            joint_index=joint_index,
            pulse_nm=args.pulse_nm,
            **common,
        )
    finally:
        backend.close()

    summary, paired = analyze(
        baseline,
        pulse,
        joint_index=joint_index,
        warmup_steps=args.warmup_steps,
        pulse_steps=args.pulse_steps,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    npz_path = args.output.with_suffix(".npz")
    np.savez_compressed(
        npz_path,
        **{f"baseline_{key}": value for key, value in baseline.items()},
        **{f"pulse_{key}": value for key, value in pulse.items()},
        **paired,
    )
    report = {
        "controller": "kinesis_directional",
        "load_sharing": not args.no_load_sharing,
        "seed": args.seed,
        "direction_deg": args.direction_deg,
        "speed_m_s": args.speed_m_s,
        "pulse_nm": args.pulse_nm,
        "pulse_seconds": args.pulse_steps * CONTROL_DT,
        "recovery_seconds": args.recovery_steps * CONTROL_DT,
        "summary": summary,
        "timeseries": str(npz_path),
    }
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("report:", args.output)
    print("timeseries:", npz_path)


if __name__ == "__main__":
    main()
