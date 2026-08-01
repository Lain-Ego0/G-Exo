"""批量筛选进入 PPO 前可用的外骨骼助力比例。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.runners.kinesis_assist_evaluate import run_condition
from RL.env.kinesis.teacher import KinesisPolicy, make_agent


GEXO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    GEXO_ROOT
    / "RL/outputs/kinesis_assist/sweep.json"
)


def parse_numbers(text: str, value_type) -> list:
    """把逗号分隔的命令行参数转换成数值列表。"""

    return [
        value_type(item.strip())
        for item in text.split(",")
        if item.strip()
    ]


def aggregate(rows: list[dict], gains: list[float]) -> list[dict]:
    """按助力比例汇总配对的基准组和助力组。"""

    summaries = []

    for gain in gains:
        pairs = [
            row
            for row in rows
            if np.isclose(row["assist_gain"], gain)
        ]

        if not pairs:
            continue

        assisted = [row["assisted"] for row in pairs]

        mpjpe_changes = np.asarray(
            [
                row["assisted"]["mpjpe_mm"]
                - row["baseline"]["mpjpe_mm"]
                for row in pairs
            ],
            dtype=np.float64,
        )
        muscle_changes = np.asarray(
            [
                100.0
                * (
                    row["assisted"][
                        "mean_absolute_muscle_torque_nm"
                    ]
                    / row["baseline"][
                        "mean_absolute_muscle_torque_nm"
                    ]
                    - 1.0
                )
                for row in pairs
            ],
            dtype=np.float64,
        )
        excitation_changes = np.asarray(
            [
                100.0
                * (
                    row["assisted"][
                        "mean_squared_excitation"
                    ]
                    / row["baseline"][
                        "mean_squared_excitation"
                    ]
                    - 1.0
                )
                for row in pairs
            ],
            dtype=np.float64,
        )
        balance_ratios = np.asarray(
            [
                result["mean_absolute_balance_error_nm"]
                / max(
                    result["mean_absolute_exo_torque_nm"],
                    1e-8,
                )
                for result in assisted
            ],
            dtype=np.float64,
        )

        summary = {
            "assist_gain": gain,
            "runs": len(pairs),
            "baseline_success_rate": float(
                np.mean(
                    [
                        row["baseline"]["success"]
                        for row in pairs
                    ]
                )
            ),
            "success_rate": float(
                np.mean([result["success"] for result in assisted])
            ),
            "mean_mpjpe_change_mm": float(
                np.mean(mpjpe_changes)
            ),
            "max_absolute_mpjpe_change_mm": float(
                np.max(np.abs(mpjpe_changes))
            ),
            "maximum_mpjpe_increase_mm": float(
                np.max(mpjpe_changes)
            ),
            "mean_muscle_torque_change_percent": float(
                np.mean(muscle_changes)
            ),
            "mean_squared_excitation_change_percent": float(
                np.mean(excitation_changes)
            ),
            "mean_exo_torque_nm": float(
                np.mean(
                    [
                        result["mean_absolute_exo_torque_nm"]
                        for result in assisted
                    ]
                )
            ),
            "mean_saturation_ratio": float(
                np.mean(
                    [
                        result["rated_torque_saturation_ratio"]
                        for result in assisted
                    ]
                )
            ),
            "maximum_saturation_ratio": float(
                np.max(
                    [
                        result["rated_torque_saturation_ratio"]
                        for result in assisted
                    ]
                )
            ),
            "mean_balance_error_nm": float(
                np.mean(
                    [
                        result["mean_absolute_balance_error_nm"]
                        for result in assisted
                    ]
                )
            ),
            "mean_balance_error_ratio": float(
                np.mean(balance_ratios)
            ),
        }

        # 这是进入 PPO 前的工程门槛，不是生理学结论。
        summary["screening_passed"] = bool(
            summary["baseline_success_rate"] == 1.0
            and
            summary["success_rate"] == 1.0
            and summary["maximum_mpjpe_increase_mm"] < 3.0
            and summary["mean_muscle_torque_change_percent"] < 0.0
            # 固定比例 oracle 只要求不显著增加兴奋度；
            # PPO 再把 excitation^2 作为需要继续压低的奖励项。
            and summary[
                "mean_squared_excitation_change_percent"
            ] < 0.5
            and summary["mean_saturation_ratio"] < 0.01
            and summary["mean_balance_error_ratio"] < 0.8
        )
        summaries.append(summary)

    return summaries


def save_report(
    output: Path,
    motion_ids: list[int],
    seeds: list[int],
    gains: list[float],
    rows: list[dict],
    torque_limit_nm: float,
) -> None:
    """保存原始配对结果和汇总，长测试中断时也保留进度。"""

    report = {
        "motion_ids": motion_ids,
        "seeds": seeds,
        "assist_gains": gains,
        "torque_limit_nm": torque_limit_nm,
        "completed_pairs": len(rows),
        "rows": rows,
        "summary": aggregate(rows, gains) if rows else [],
    }
    output.parent.mkdir(parents=True, exist_ok=True)

    with output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-ids", default="2,8,9,52")
    parser.add_argument("--seeds", default="0,1")
    parser.add_argument("--gains", default="0.025,0.05,0.075,0.1")
    parser.add_argument("--warmup-steps", type=int, default=25)
    parser.add_argument("--max-steps", type=int, default=600)
    parser.add_argument("--torque-limit", type=float, default=6.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    motion_ids = parse_numbers(args.motion_ids, int)
    seeds = parse_numbers(args.seeds, int)
    gains = parse_numbers(args.gains, float)
    rows = []

    for motion_id in motion_ids:
        agent = make_agent(motion_id)
        policy = KinesisPolicy(agent)

        try:
            for seed in seeds:
                baseline = run_condition(
                    agent,
                    policy,
                    {
                        "name": "baseline",
                        "human_strength": 1.0,
                        "assist_gain": 0.0,
                    },
                    seed=seed,
                    warmup_steps=args.warmup_steps,
                    max_steps=args.max_steps,
                    torque_limit_nm=args.torque_limit,
                )

                for gain in gains:
                    assisted = run_condition(
                        agent,
                        policy,
                        {
                            "name": f"assist_{gain:.3f}",
                            "human_strength": 1.0,
                            "assist_gain": gain,
                        },
                        seed=seed,
                        warmup_steps=args.warmup_steps,
                        max_steps=args.max_steps,
                        torque_limit_nm=args.torque_limit,
                    )
                    rows.append(
                        {
                            "motion_id": motion_id,
                            "seed": seed,
                            "assist_gain": gain,
                            "baseline": baseline,
                            "assisted": assisted,
                        }
                    )
                    save_report(
                        args.output,
                        motion_ids,
                        seeds,
                        gains,
                        rows,
                        args.torque_limit,
                    )

                    print(
                        f"motion={motion_id:03d} seed={seed:02d} "
                        f"gain={gain:.3f} "
                        f"success={assisted['success']} "
                        f"mpjpe_delta="
                        f"{assisted['mpjpe_mm'] - baseline['mpjpe_mm']:+.2f} mm "
                        f"saturation="
                        f"{assisted['rated_torque_saturation_ratio']:.3f}",
                        flush=True,
                    )
        finally:
            agent.env.close()

    summaries = aggregate(rows, gains)
    print("\nSweep summary")

    for summary in summaries:
        print(
            f"gain={summary['assist_gain']:.3f} "
            f"success={summary['success_rate']:.3f} "
            f"muscle={summary['mean_muscle_torque_change_percent']:+.2f}% "
            f"excitation="
            f"{summary['mean_squared_excitation_change_percent']:+.2f}% "
            f"saturation={summary['mean_saturation_ratio']:.3f} "
            f"balance_ratio={summary['mean_balance_error_ratio']:.3f} "
            f"passed={summary['screening_passed']}"
        )

    print(f"report: {args.output}")


if __name__ == "__main__":
    main()
