from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_RUNS_ROOT = PROJECT_ROOT / "RL/outputs/tcn_runs"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--runs-root", type=Path, default=DEFAULT_RUNS_ROOT)
    parser.add_argument("--pattern", default="seed_*")
    parser.add_argument("--evaluation-name", default="evaluation.json")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--minimum-runs", type=int, default=3)
    parser.add_argument("--minimum-requested-epochs", type=int, default=30)
    parser.add_argument("--maximum-normalized-mse-cv", type=float, default=0.10)
    args = parser.parse_args()
    files = sorted(
        args.runs_root.glob(f"{args.pattern}/{args.evaluation_name}")
    )

    if not files:
        raise FileNotFoundError("No evaluation.json files matched.")

    runs = []

    for path in files:
        report = json.loads(path.read_text(encoding="utf-8"))
        config_path = path.parent / "config.json"
        check_path = path.parent / "pipeline_check.json"
        config = json.loads(config_path.read_text(encoding="utf-8"))
        pipeline_check = json.loads(check_path.read_text(encoding="utf-8"))
        overall = report["overall"]
        metrics = {"normalized_mse": overall["normalized_mse"]}
        comparisons = {}

        for horizon, horizon_metrics in overall["horizons"].items():
            for group in ("angle_rad", "velocity_rad_s", "moment_nm_kg"):
                group_metrics = horizon_metrics[group]

                for metric in (
                    "tcn_rmse",
                    "training_mean_rmse",
                    "persistence_rmse",
                ):
                    metrics[f"{horizon}.{group}.{metric}"] = group_metrics[metric]

                comparisons[f"{horizon}.{group}"] = (
                    group_metrics["tcn_rmse"] < group_metrics["training_mean_rmse"]
                    and group_metrics["tcn_rmse"]
                    < group_metrics["persistence_rmse"]
                )

        runs.append(
            {
                "seed": report["checkpoint_seed"],
                "path": str(path.resolve()),
                "requested_epochs": int(config["epochs"]),
                "pipeline_check_passed": bool(pipeline_check["passed"]),
                "beats_both_baselines": all(comparisons.values()),
                "baseline_comparisons": comparisons,
                "metrics": metrics,
            }
        )

    names = runs[0]["metrics"].keys()
    summary = {}

    for name in names:
        values = np.asarray([run["metrics"][name] for run in runs], dtype=float)
        summary[name] = {
            "mean": float(values.mean()),
            "std": float(values.std()),
            "minimum": float(values.min()),
            "maximum": float(values.max()),
        }

    normalized = summary["normalized_mse"]
    normalized_cv = (
        normalized["std"] / normalized["mean"]
        if normalized["mean"] > 0.0
        else float("inf")
    )
    acceptance = {
        "minimum_runs": args.minimum_runs,
        "minimum_requested_epochs": args.minimum_requested_epochs,
        "maximum_normalized_mse_cv": args.maximum_normalized_mse_cv,
        "normalized_mse_cv": normalized_cv,
        "enough_runs": len(runs) >= args.minimum_runs,
        "all_pipeline_checks_passed": all(
            run["pipeline_check_passed"] for run in runs
        ),
        "all_runs_requested_full_training": all(
            run["requested_epochs"] >= args.minimum_requested_epochs for run in runs
        ),
        "all_runs_beat_both_baselines": all(
            run["beats_both_baselines"] for run in runs
        ),
        "stable_across_seeds": normalized_cv <= args.maximum_normalized_mse_cv,
    }
    acceptance["ready_for_myo_rl_prototype"] = all(
        value
        for key, value in acceptance.items()
        if key
        in {
            "enough_runs",
            "all_pipeline_checks_passed",
            "all_runs_requested_full_training",
            "all_runs_beat_both_baselines",
            "stable_across_seeds",
        }
    )
    result = {
        "run_count": len(runs),
        "acceptance": acceptance,
        "runs": runs,
        "summary": summary,
    }
    output = args.output or args.runs_root / "aggregate.json"
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(result, ensure_ascii=False, indent=2))
    print("aggregate:", output.resolve())


if __name__ == "__main__":
    main()
