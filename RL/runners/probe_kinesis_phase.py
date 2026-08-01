"""Test whether deployable observations already encode gait phase."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
from scipy.signal import find_peaks

from RL.env.kinesis.baseline_reference import DEFAULT_BASELINE_DIR
from RL.env.kinesis.exo_env import FRAME_DIM, KinesisExoEnv


RL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = RL_ROOT / "outputs/kinesis_phase_probe/report.json"
TRAIN_MOTIONS = (2, 8, 9, 11, 16, 38, 43, 52)
VALIDATION_MOTIONS = (64, 82, 99)


def parse_ints(text: str) -> tuple[int, ...]:
    return tuple(int(value) for value in text.split(",") if value)


def phase_targets(
    signal: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    """Define phase from consecutive peaks of the left hip trajectory."""

    prominence = max(0.05, 0.15 * float(np.ptp(signal)))
    candidates = []
    for candidate in (signal, -signal):
        peaks, _ = find_peaks(
            candidate,
            distance=25,
            prominence=prominence,
        )
        candidates.append(peaks)
    peaks = max(candidates, key=len)
    if len(peaks) < 2:
        raise RuntimeError("Could not detect two gait-cycle peaks.")

    phase = np.full(len(signal), np.nan, dtype=np.float64)
    for start, stop in zip(peaks[:-1], peaks[1:]):
        phase[start:stop] = np.arange(stop - start) / (stop - start)

    valid = np.isfinite(phase)
    angle = 2.0 * np.pi * phase[valid]
    target = np.column_stack((np.sin(angle), np.cos(angle)))
    return valid, target.astype(np.float32), np.diff(peaks).tolist()


def collect_motion(
    motion_id: int,
    seeds: tuple[int, ...],
    baseline_dir: Path,
) -> tuple[np.ndarray, np.ndarray, list[int]]:
    env = KinesisExoEnv(
        motion_id=motion_id,
        baseline_dir=baseline_dir,
    )
    observations = []
    targets = []
    periods = []

    try:
        for seed in seeds:
            observation, _ = env.reset(seed=seed)
            episode_observations = []
            left_hip = []

            while True:
                observation, _, terminated, truncated, _ = env.step(
                    np.zeros(4, dtype=np.float32)
                )
                episode_observations.append(observation.copy())
                left_hip.append(
                    float(env._last_state["joint_position"][0])
                )
                if terminated or truncated:
                    break

            signal = np.asarray(left_hip, dtype=np.float64)
            valid, target, detected_periods = phase_targets(signal)
            periods.extend(detected_periods)
            observations.append(
                np.asarray(episode_observations, dtype=np.float32)[valid]
            )
            targets.append(target)
    finally:
        env.close()

    return np.concatenate(observations), np.concatenate(targets), periods


def fit_ridge(
    train_x: np.ndarray,
    train_y: np.ndarray,
    validation_x: np.ndarray,
    regularization: float,
) -> np.ndarray:
    mean = train_x.mean(axis=0)
    scale = train_x.std(axis=0)
    scale[scale < 1.0e-6] = 1.0
    train = (train_x - mean) / scale
    validation = (validation_x - mean) / scale
    train = np.column_stack((train, np.ones(len(train))))
    validation = np.column_stack((validation, np.ones(len(validation))))
    identity = np.eye(train.shape[1], dtype=np.float64)
    identity[-1, -1] = 0.0
    weights = np.linalg.solve(
        train.T @ train + regularization * identity,
        train.T @ train_y,
    )
    return validation @ weights


def metrics(prediction: np.ndarray, target: np.ndarray) -> dict[str, float]:
    predicted_angle = np.arctan2(prediction[:, 0], prediction[:, 1])
    target_angle = np.arctan2(target[:, 0], target[:, 1])
    error = np.angle(np.exp(1j * (predicted_angle - target_angle)))
    absolute = np.abs(error)
    mse = float(np.mean(np.square(prediction - target)))
    variance = float(np.mean(np.square(target - target.mean(axis=0))))
    return {
        "circular_mae_degrees": float(np.degrees(absolute.mean())),
        "circular_median_degrees": float(np.degrees(np.median(absolute))),
        "within_30_degrees": float(np.mean(absolute <= np.pi / 6.0)),
        "within_45_degrees": float(np.mean(absolute <= np.pi / 4.0)),
        "sincos_mse": mse,
        "sincos_r2": 1.0 - mse / max(variance, 1.0e-8),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--train-motions", default=",".join(map(str, TRAIN_MOTIONS)))
    parser.add_argument(
        "--validation-motions",
        default=",".join(map(str, VALIDATION_MOTIONS)),
    )
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--regularization", type=float, default=1.0)
    parser.add_argument("--worker-motion", type=int)
    parser.add_argument("--worker-output", type=Path)
    args = parser.parse_args()

    seeds = parse_ints(args.seeds)
    if args.worker_motion is not None:
        observations, targets, periods = collect_motion(
            args.worker_motion, seeds, args.baseline_dir
        )
        args.worker_output.parent.mkdir(parents=True, exist_ok=True)
        np.savez_compressed(
            args.worker_output,
            observations=observations,
            targets=targets,
            periods=np.asarray(periods, dtype=np.int32),
        )
        return

    train_motions = parse_ints(args.train_motions)
    validation_motions = parse_ints(args.validation_motions)
    part_dir = args.output.parent / "rollouts"
    part_dir.mkdir(parents=True, exist_ok=True)

    split_data = {}
    for split, motions in (
        ("train", train_motions),
        ("validation", validation_motions),
    ):
        observations = []
        targets = []
        periods = []
        for motion_id in motions:
            part = part_dir / f"{split}_motion_{motion_id:03d}.npz"
            subprocess.run(
                [
                    sys.executable,
                    "-m",
                    "RL.runners.probe_kinesis_phase",
                    "--worker-motion",
                    str(motion_id),
                    "--worker-output",
                    str(part),
                    "--seeds",
                    args.seeds,
                    "--baseline-dir",
                    str(args.baseline_dir),
                ],
                check=True,
            )
            with np.load(part) as data:
                observations.append(data["observations"])
                targets.append(data["targets"])
                periods.extend(data["periods"].tolist())
        split_data[split] = (
            np.concatenate(observations),
            np.concatenate(targets),
            periods,
        )

    train_x, train_y, train_periods = split_data["train"]
    validation_x, validation_y, validation_periods = split_data["validation"]
    feature_sets = {
        "joint_position_only": slice(-FRAME_DIM, -FRAME_DIM + 4),
        "current_frame": slice(-FRAME_DIM, None),
        "four_frame_history": slice(None),
    }
    results = {}
    for name, columns in feature_sets.items():
        prediction = fit_ridge(
            train_x[:, columns],
            train_y,
            validation_x[:, columns],
            args.regularization,
        )
        results[name] = metrics(prediction, validation_y)

    report = {
        "phase_definition": "peak-to-peak left hip gait cycle",
        "train_motions": list(train_motions),
        "validation_motions": list(validation_motions),
        "seeds": list(seeds),
        "train_samples": len(train_x),
        "validation_samples": len(validation_x),
        "median_train_period_steps": float(np.median(train_periods)),
        "median_validation_period_steps": float(np.median(validation_periods)),
        "probe": results,
        "acceptance": {
            "maximum_circular_mae_degrees": 30.0,
            "passed": results["four_frame_history"]["circular_mae_degrees"] < 30.0,
        },
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    print(json.dumps(report, indent=2))
    print("report:", args.output)


if __name__ == "__main__":
    main()
