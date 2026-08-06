"""Train cross-fitted causal gait-phase TCNs from zero-assist traces."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.env.kinesis.causal_phase import (
    DEFAULT_HISTORY,
    circular_phase_error,
    fit_phase_tcn,
    predict_phase,
    save_phase_checkpoint,
    trace_oracle_phase,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRACES = PROJECT_ROOT / "RL/outputs/kinesis_cycle_baseline_c"
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/outputs/kinesis_cycle_phase_tcn"


def load_baselines(directory: Path) -> dict[tuple[int, int], dict]:
    """Load successful baseline traces and reject the old sensor-less schema."""

    baselines = {}
    for path in sorted(directory.glob("*.npz")):
        with np.load(path, allow_pickle=False) as data:
            if "kind" in data and str(data["kind"].item()) != "baseline":
                continue
            trace = {name: data[name].copy() for name in data.files}
        valid_key = "success" if "success" in trace else "valid"
        if not bool(np.asarray(trace[valid_key]).item()):
            continue
        if "sensor_frame" not in trace:
            raise ValueError(
                f"{path} has no sensor_frame; re-run the oracle collector."
            )
        seed = int(np.asarray(trace["seed"]).item())
        motion_id = (
            int(np.asarray(trace["motion_id"]).item())
            if "motion_id" in trace
            else int(path.name.split("_")[1])
        )
        trace["path"] = str(path.resolve())
        baselines[(motion_id, seed)] = trace
    unique_seeds = {seed for _, seed in baselines}
    if len(unique_seeds) < 3:
        raise ValueError("Cross-fitted phase audit needs at least three seeds.")
    return baselines


def evaluate_model(model, statistics: dict, trace: dict, *, device: str) -> dict:
    oracle = trace_oracle_phase(trace)
    prediction = predict_phase(
        model,
        statistics,
        trace["sensor_frame"],
        device=device,
    )
    valid = oracle.valid & prediction.valid
    if not np.any(valid):
        raise ValueError("Held-out trace has no valid causal phase samples.")
    phase_error = circular_phase_error(
        prediction.phase[valid],
        oracle.phase[valid],
    )
    rate_error = np.abs(
        prediction.phase_rate_hz[valid] - oracle.phase_rate_hz[valid]
    )
    return {
        "samples": int(np.sum(valid)),
        "phase_mae_cycle": float(np.mean(phase_error)),
        "phase_p95_cycle": float(np.quantile(phase_error, 0.95)),
        "phase_max_cycle": float(np.max(phase_error)),
        "rate_mae_hz": float(np.mean(rate_error)),
        "mean_confidence": float(np.mean(prediction.confidence[valid])),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=Path, default=DEFAULT_TRACES)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--history", type=int, default=DEFAULT_HISTORY)
    parser.add_argument("--hidden-dim", type=int, default=32)
    parser.add_argument("--epochs", type=int, default=300)
    parser.add_argument("--learning-rate", type=float, default=3.0e-3)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--seed", type=int, default=2026)
    args = parser.parse_args()

    baselines = load_baselines(args.traces)
    args.output.mkdir(parents=True, exist_ok=True)
    folds = {}
    unique_seeds = sorted({seed for _, seed in baselines})
    for held_out_seed in unique_seeds:
        held_out_traces = [
            trace
            for (_, seed), trace in baselines.items()
            if seed == held_out_seed
        ]
        training = [
            trace
            for (_, seed), trace in baselines.items()
            if seed != held_out_seed
        ]
        model, statistics = fit_phase_tcn(
            training,
            history=args.history,
            hidden_dim=args.hidden_dim,
            epochs=args.epochs,
            learning_rate=args.learning_rate,
            seed=args.seed + held_out_seed,
            device=args.device,
        )
        checkpoint = args.output / f"held_out_seed_{held_out_seed:06d}.pt"
        save_phase_checkpoint(
            checkpoint,
            model,
            statistics,
            held_out_seed=held_out_seed,
        )
        held_out_metrics = [
            evaluate_model(model, statistics, trace, device=args.device)
            for trace in held_out_traces
        ]
        metrics = {
            "samples": int(sum(row["samples"] for row in held_out_metrics)),
            "phase_mae_cycle": float(
                np.mean([row["phase_mae_cycle"] for row in held_out_metrics])
            ),
            "phase_p95_cycle": float(
                np.max([row["phase_p95_cycle"] for row in held_out_metrics])
            ),
            "phase_max_cycle": float(
                np.max([row["phase_max_cycle"] for row in held_out_metrics])
            ),
            "rate_mae_hz": float(
                np.mean([row["rate_mae_hz"] for row in held_out_metrics])
            ),
            "mean_confidence": float(
                np.mean([row["mean_confidence"] for row in held_out_metrics])
            ),
            "motion_count": len(held_out_traces),
        }
        folds[str(held_out_seed)] = {
            **metrics,
            "checkpoint": str(checkpoint.resolve()),
            "training_samples": statistics["training_samples"],
        }
        print(
            f"held-out seed={held_out_seed:06d} "
            f"phase_mae={metrics['phase_mae_cycle']:.4f} "
            f"p95={metrics['phase_p95_cycle']:.4f}"
        )

    deployment_model, deployment_statistics = fit_phase_tcn(
        list(baselines.values()),
        history=args.history,
        hidden_dim=args.hidden_dim,
        epochs=args.epochs,
        learning_rate=args.learning_rate,
        seed=args.seed,
        device=args.device,
    )
    deployment_checkpoint = args.output / "all_baselines.pt"
    save_phase_checkpoint(
        deployment_checkpoint,
        deployment_model,
        deployment_statistics,
        held_out_seed=None,
    )

    phase_mae = np.asarray(
        [fold["phase_mae_cycle"] for fold in folds.values()],
        dtype=np.float64,
    )
    phase_p95 = np.asarray(
        [fold["phase_p95_cycle"] for fold in folds.values()],
        dtype=np.float64,
    )
    report = {
        "schema_version": 1,
        "trace_directory": str(args.traces.resolve()),
        "history": args.history,
        "input_channels": 32,
        "causal": True,
        "touch_used_for_inference": False,
        "folds": folds,
        "mean_phase_mae_cycle": float(np.mean(phase_mae)),
        "maximum_fold_phase_p95_cycle": float(np.max(phase_p95)),
        "phase_accuracy_passed": bool(
            np.mean(phase_mae) <= 0.08 and np.max(phase_p95) <= 0.20
        ),
        "deployment_checkpoint": str(deployment_checkpoint.resolve()),
    }
    report_path = args.output / "report.json"
    report_path.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("phase accuracy passed:", report["phase_accuracy_passed"])
    print("report:", report_path.resolve())


if __name__ == "__main__":
    main()
