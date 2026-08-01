"""Scan directional-human pulse responses across joints and gait times."""

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
DEFAULT_WARMUP_STEPS = (40, 70, 100, 130)
DEFAULT_OUTPUT = Path(
    "RL/outputs/kinesis_directional_assist/dynamic_scan.json"
)


def aggregate(rows: list[dict[str, object]]) -> dict[str, float]:
    """Summarize physical response metrics without creating a reward."""

    return {
        "cases": len(rows),
        "unloading_ratio_mean": float(
            np.mean([row["instant_unloading_ratio_first"] for row in rows])
        ),
        "unloading_ratio_max_error": float(
            np.max(
                [
                    abs(row["instant_unloading_ratio_first"] - 1.0)
                    for row in rows
                ]
            )
        ),
        "activation_change_mean_percent": float(
            np.mean(
                [row["activation_change_during_pulse_percent"] for row in rows]
            )
        ),
        "position_difference_mean_rad": float(
            np.mean(
                [row["recovery_peak_position_difference_rad"] for row in rows]
            )
        ),
        "position_difference_max_rad": float(
            np.max(
                [row["recovery_peak_position_difference_rad"] for row in rows]
            )
        ),
        "nominal_excitation_change_mean": float(
            np.mean(
                [row["recovery_nominal_excitation_rms_change"] for row in rows]
            )
        ),
        "nominal_excitation_change_max": float(
            np.max(
                [row["recovery_nominal_excitation_rms_change"] for row in rows]
            )
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pulse-nm", type=float, default=0.2)
    parser.add_argument("--pulse-steps", type=int, default=5)
    parser.add_argument("--recovery-steps", type=int, default=25)
    parser.add_argument("--direction-deg", type=float, default=0.0)
    parser.add_argument("--speed-m-s", type=float, default=1.0)
    parser.add_argument(
        "--warmup-steps",
        default=",".join(str(value) for value in DEFAULT_WARMUP_STEPS),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    warmup_steps = tuple(
        int(value) for value in args.warmup_steps.split(",")
    )
    direction_rad = float(np.deg2rad(args.direction_deg))

    agent = make_directional_agent(render=False)
    policy = make_directional_policy(agent)
    backend = AssistBackend(agent.env, load_sharing=True)

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

    rows = []
    try:
        for warmup in warmup_steps:
            backend.load_sharing_enabled = True
            baseline = run_rollout(
                backend,
                policy,
                seed=args.seed,
                joint_index=None,
                pulse_nm=0.0,
                warmup_steps=warmup,
                pulse_steps=args.pulse_steps,
                recovery_steps=args.recovery_steps,
                after_reset=configure,
            )

            for load_sharing in (False, True):
                backend.load_sharing_enabled = load_sharing
                for joint_index, joint in enumerate(JOINT_NAMES):
                    for sign in (-1.0, 1.0):
                        pulse_nm = sign * abs(args.pulse_nm)
                        pulse = run_rollout(
                            backend,
                            policy,
                            seed=args.seed,
                            joint_index=joint_index,
                            pulse_nm=pulse_nm,
                            warmup_steps=warmup,
                            pulse_steps=args.pulse_steps,
                            recovery_steps=args.recovery_steps,
                            after_reset=configure,
                        )
                        summary, _ = analyze(
                            baseline,
                            pulse,
                            joint_index=joint_index,
                            warmup_steps=warmup,
                            pulse_steps=args.pulse_steps,
                        )
                        summary.update(
                            {
                                "load_sharing": load_sharing,
                                "warmup_steps": warmup,
                                "pulse_time_s": warmup * CONTROL_DT,
                                "pulse_nm": pulse_nm,
                            }
                        )
                        rows.append(summary)
                        print(
                            f"t={warmup * CONTROL_DT:4.2f}s "
                            f"sharing={int(load_sharing)} "
                            f"{joint:18s} tau={pulse_nm:+.1f} "
                            f"eta={summary['instant_unloading_ratio_first']:+.2f} "
                            f"dq={summary['recovery_peak_position_difference_rad']:.4f}"
                        )
    finally:
        backend.close()

    without_sharing = [row for row in rows if not row["load_sharing"]]
    with_sharing = [row for row in rows if row["load_sharing"]]
    report = {
        "seed": args.seed,
        "pulse_nm_absolute": abs(args.pulse_nm),
        "pulse_seconds": args.pulse_steps * CONTROL_DT,
        "recovery_seconds": args.recovery_steps * CONTROL_DT,
        "warmup_steps": list(warmup_steps),
        "summary": {
            "without_load_sharing": aggregate(without_sharing),
            "with_load_sharing": aggregate(with_sharing),
        },
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)
    print("report:", args.output)


if __name__ == "__main__":
    main()
