"""Measure paired muscle response to increasing physical exoskeleton assist."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

from RL.env.kinesis.baseline_reference import DEFAULT_PHYSICAL_BASELINE_DIR
from RL.env.kinesis.exo_env import KinesisExoEnv
from RL.runners.evaluate_kinesis_exo import parse_csv, run_episode


DEFAULT_OUTPUT = Path("RL/outputs/kinesis_dose_response/report.json")


def paired_row(baseline: dict, assisted: dict, level_nm: float) -> dict:
    """Compare one assisted rollout with its exact motion/seed baseline."""

    baseline_activation = baseline["activation_cost_integral_s"]
    baseline_torque = baseline["absolute_muscle_torque_integral_nms"]
    complete = bool(assisted["success"])
    return {
        "motion_id": assisted["motion_id"],
        "seed": assisted["seed"],
        "level_nm": level_nm,
        "success": assisted["success"],
        "termination_reason": assisted["termination_reason"],
        "steps": assisted["steps"],
        "activation_saving_percent": (
            100.0
            * (baseline_activation - assisted["activation_cost_integral_s"])
            / max(baseline_activation, 1.0e-8)
            if complete
            else None
        ),
        "muscle_torque_saving_percent": (
            100.0
            * (
                baseline_torque
                - assisted["absolute_muscle_torque_integral_nms"]
            )
            / max(baseline_torque, 1.0e-8)
            if complete
            else None
        ),
        "mpjpe_change_mm": (
            assisted["mean_mpjpe_mm"] - baseline["mean_mpjpe_mm"]
            if complete
            else None
        ),
        "mean_abs_exo_torque_nm": assisted[
            "mean_absolute_exo_torque_nm"
        ],
        "actual_balance_residual_ratio": assisted[
            "mean_actual_balance_residual_ratio"
        ],
        "mean_jerk_cost": assisted["mean_jerk_cost"],
        "positive_exo_work_j": assisted["positive_exo_work_j"],
        "negative_exo_work_j": assisted["negative_exo_work_j"],
    }


def summarize(rows: list[dict]) -> list[dict]:
    result = []
    for level in sorted({row["level_nm"] for row in rows}):
        selected = [row for row in rows if row["level_nm"] == level]
        successful = [row for row in selected if row["success"]]
        result.append(
            {
                "level_nm": level,
                "episodes": len(selected),
                "successful_episodes": len(successful),
                "success_rate": float(
                    np.mean([row["success"] for row in selected])
                ),
                "activation_saving_percent": (
                    float(
                        np.mean(
                            [
                                row["activation_saving_percent"]
                                for row in successful
                            ]
                        )
                    )
                    if successful
                    else None
                ),
                "muscle_torque_saving_percent": (
                    float(
                        np.mean(
                            [
                                row["muscle_torque_saving_percent"]
                                for row in successful
                            ]
                        )
                    )
                    if successful
                    else None
                ),
                "mpjpe_change_mm": (
                    float(
                        np.mean(
                            [row["mpjpe_change_mm"] for row in successful]
                        )
                    )
                    if successful
                    else None
                ),
                "mean_abs_exo_torque_nm": float(
                    np.mean(
                        [row["mean_abs_exo_torque_nm"] for row in selected]
                    )
                ),
                "actual_balance_residual_ratio": (
                    float(
                        np.mean(
                            [
                                row["actual_balance_residual_ratio"]
                                for row in successful
                            ]
                        )
                    )
                    if successful
                    else None
                ),
            }
        )
    return result


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-ids", default="82")
    parser.add_argument("--levels-nm", default="0,1,2,4")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument(
        "--baseline-dir", type=Path, default=DEFAULT_PHYSICAL_BASELINE_DIR
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    motion_ids = parse_csv(args.motion_ids, int)
    levels = parse_csv(args.levels_nm, float)
    if not levels or min(levels) < 0.0:
        raise ValueError("--levels-nm must contain non-negative values.")
    if args.episodes < 1:
        raise ValueError("--episodes must be positive.")

    if len(motion_ids) > 1:
        rows = []
        for motion_id in motion_ids:
            part = args.output.with_name(
                f"{args.output.stem}.motion_{motion_id:03d}.json"
            )
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "RL.runners.validate_kinesis_dose_response",
                    "--motion-ids",
                    str(motion_id),
                    "--levels-nm",
                    ",".join(str(level) for level in levels),
                    "--episodes",
                    str(args.episodes),
                    "--first-seed",
                    str(args.first_seed),
                    "--baseline-dir",
                    str(args.baseline_dir),
                    "--output",
                    str(part),
                ],
                check=True,
            )
            with part.open("r", encoding="utf-8") as file:
                rows.extend(json.load(file)["rows"])
            part.unlink()
        report = {"rows": rows, "summary": summarize(rows)}
    else:
        motion_id = motion_ids[0]
        env = KinesisExoEnv(
            motion_id=motion_id,
            baseline_dir=args.baseline_dir,
            strict_baseline_seed=True,
        )
        rows = []
        try:
            for episode in range(args.episodes):
                seed = args.first_seed + episode
                baseline = run_episode(
                    env,
                    mode="baseline",
                    seed=seed,
                    model=None,
                    oracle_gain=0.0,
                    test_torque_nm=0.0,
                    real_time=False,
                )
                for level in levels:
                    assisted = (
                        baseline
                        if level == 0.0
                        else run_episode(
                            env,
                            mode="velocity_assist",
                            seed=seed,
                            model=None,
                            oracle_gain=0.0,
                            test_torque_nm=level,
                            real_time=False,
                        )
                    )
                    row = paired_row(baseline, assisted, level)
                    rows.append(row)
                    activation = row["activation_saving_percent"]
                    torque = row["muscle_torque_saving_percent"]
                    mpjpe = row["mpjpe_change_mm"]
                    print(
                        f"motion={motion_id:03d} seed={seed:03d} "
                        f"level={level:.1f} Nm success={row['success']} "
                        f"activation={activation if activation is not None else 'invalid'} "
                        f"muscle={torque if torque is not None else 'invalid'} "
                        f"mpjpe={mpjpe if mpjpe is not None else 'invalid'}"
                    )
        finally:
            env.close()
        report = {"rows": rows, "summary": summarize(rows)}

    report.update(
        {
            "motion_ids": motion_ids,
            "levels_nm": levels,
            "episodes_per_motion": args.episodes,
            "first_seed": args.first_seed,
            "baseline_dir": str(args.baseline_dir.resolve()),
            "assist_law": "tau * tanh(joint_velocity / 0.5)",
        }
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)
    print("report:", args.output.resolve())


if __name__ == "__main__":
    main()
