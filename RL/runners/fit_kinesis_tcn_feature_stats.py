"""Fit fixed 16-D explicit TCN feature statistics on training motions."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.env.kinesis.baseline_reference import DEFAULT_PHYSICAL_BASELINE_DIR
from RL.env.kinesis.tcn_adapter import (
    TCN_DEPLOYMENT_HORIZON_STEPS,
    TCNInputAdapter,
)
from RL.runners.calibrate_kinesis_tcn import collect_kinesis_frames


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHECKPOINT = (
    PROJECT_ROOT / "RL/outputs/tcn_runs/seed_43/best_model.pt"
)
DEFAULT_CALIBRATION = (
    PROJECT_ROOT / "RL/assets/tcn/kinesis_phase12_calibration.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "RL/assets/tcn/kinesis_phase12_explicit_calibration.json"
)
DEFAULT_MOTIONS = (2, 8, 9, 11, 16, 38, 43, 52)


def parse_motion_ids(value: str) -> tuple[int, ...]:
    result = tuple(int(item) for item in value.split(",") if item.strip())
    if not result:
        raise ValueError("At least one motion id is required.")
    return result


def parse_seeds(value: str) -> tuple[int, ...]:
    result = tuple(int(item) for item in value.split(",") if item.strip())
    if not result:
        raise ValueError("At least one seed is required.")
    return result


def collect_raw_features(
    adapter: TCNInputAdapter,
    trajectories: list[np.ndarray],
) -> np.ndarray:
    """Run causal inference independently on each zero-assist trajectory."""

    features: list[np.ndarray] = []
    for trajectory in trajectories:
        adapter.reset()
        for frame in np.asarray(trajectory, dtype=np.float32):
            adapter.append(frame)
            if not adapter.ready:
                continue
            prediction = adapter.predict()
            features.append(
                adapter.raw_deployment_features(
                    prediction,
                    frame[:4],
                    frame[4:8],
                    horizon_steps=TCN_DEPLOYMENT_HORIZON_STEPS,
                )
            )
    if not features:
        raise RuntimeError("No complete 50-frame TCN window was collected.")
    return np.stack(features, axis=0)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument(
        "--calibration", type=Path, default=DEFAULT_CALIBRATION
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=DEFAULT_PHYSICAL_BASELINE_DIR,
    )
    parser.add_argument(
        "--motion-ids",
        default=",".join(str(value) for value in DEFAULT_MOTIONS),
    )
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    calibration_path = args.calibration.expanduser().resolve()
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    adapter = TCNInputAdapter(
        args.checkpoint,
        device=args.device,
        calibration=calibration_path,
        ignore_actor_feature_normalization=True,
    )
    motion_ids = parse_motion_ids(args.motion_ids)
    seeds = parse_seeds(args.seeds)
    trajectories: list[np.ndarray] = []
    for seed in seeds:
        trajectories.extend(
            collect_kinesis_frames(
                motion_ids,
                seed=seed,
                steps=args.steps,
                baseline_dir=args.baseline_dir,
            )
        )
    raw_features = collect_raw_features(adapter, trajectories)
    statistics = TCNInputAdapter.fit_actor_feature_normalization(
        raw_features,
        horizon_steps=TCN_DEPLOYMENT_HORIZON_STEPS,
    )
    statistics.update(
        {
            "source": "zero_assist_kinesis_training_motions",
            "motion_ids": list(motion_ids),
            "seeds": list(seeds),
        }
    )
    calibration["actor_feature_normalization"] = statistics

    print("samples:", raw_features.shape[0])
    print("feature dim:", raw_features.shape[1])
    print("minimum std:", min(statistics["std"]))
    print("maximum std:", max(statistics["std"]))
    if args.dry_run:
        print("dry run: calibration was not written")
        return

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_suffix(output.suffix + ".tmp")
    temporary.write_text(
        json.dumps(calibration, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    temporary.replace(output)
    print("calibration:", output)


if __name__ == "__main__":
    main()
