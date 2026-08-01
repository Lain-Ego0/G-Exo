"""Check frozen-TCN inputs and predictions on a zero-assist Kinesis rollout."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from RL.env.kinesis.baseline_reference import DEFAULT_PHYSICAL_BASELINE_DIR
from RL.env.kinesis.exo_env import KinesisExoEnv
from RL.env.kinesis.tcn_adapter import TCNInputAdapter


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_CHECKPOINT = (
    PROJECT_ROOT / "RL/outputs/tcn_runs/seed_43/best_model.pt"
)
DEFAULT_CALIBRATION = (
    PROJECT_ROOT
    / "RL/assets/tcn/kinesis_phase12_explicit_calibration.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "RL/outputs/kinesis_tcn_adapter/report.json"
)


def distribution_metrics(values: np.ndarray) -> dict[str, float]:
    absolute = np.abs(np.asarray(values, dtype=np.float64))
    return {
        "mean_absolute_z": float(np.mean(absolute)),
        "p95_absolute_z": float(np.percentile(absolute, 95.0)),
        "fraction_above_3_sigma": float(np.mean(absolute > 3.0)),
        "fraction_above_5_sigma": float(np.mean(absolute > 5.0)),
    }


def error_metrics(errors: list[np.ndarray]) -> dict[str, object]:
    if not errors:
        return {"samples": 0}
    array = np.stack(errors, axis=0)
    return {
        "samples": int(array.shape[0]),
        "angle_rmse_rad": np.sqrt(np.mean(array[:, :4] ** 2, axis=0)).tolist(),
        "angle_rmse_mean_rad": float(np.sqrt(np.mean(array[:, :4] ** 2))),
        "velocity_rmse_rad_s": np.sqrt(
            np.mean(array[:, 4:8] ** 2, axis=0)
        ).tolist(),
        "velocity_rmse_mean_rad_s": float(
            np.sqrt(np.mean(array[:, 4:8] ** 2))
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, default=DEFAULT_CHECKPOINT)
    parser.add_argument(
        "--calibration",
        type=Path,
        default=DEFAULT_CALIBRATION,
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=DEFAULT_PHYSICAL_BASELINE_DIR,
    )
    parser.add_argument("--motion-id", type=int, default=82)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    adapter = TCNInputAdapter(
        args.checkpoint,
        device=args.device,
        calibration=args.calibration,
    )
    env = KinesisExoEnv(
        motion_id=args.motion_id,
        render_mode="human" if args.render else None,
        baseline_dir=args.baseline_dir,
        warmup_steps=adapter.history_length,
        max_episode_steps=args.steps,
    )

    pending: dict[
        int,
        list[tuple[int, np.ndarray, np.ndarray, np.ndarray]],
    ] = defaultdict(list)
    tcn_errors: dict[int, list[np.ndarray]] = {
        horizon: [] for horizon in adapter.horizons
    }
    hold_errors: dict[int, list[np.ndarray]] = {
        horizon: [] for horizon in adapter.horizons
    }
    constant_velocity_errors: dict[int, list[np.ndarray]] = {
        horizon: [] for horizon in adapter.horizons
    }
    z_frames: list[np.ndarray] = []
    completed_steps = 0
    termination_reason = "time_limit"

    try:
        _, current_info = env.reset(seed=args.seed)
        adapter.extend(env.raw_sensor_history)

        for step in range(args.steps + 1):
            if step > 0:
                _, _, terminated, truncated, info = env.step(
                    np.zeros(4, dtype=np.float32)
                )
                completed_steps = step
                adapter.append(env.latest_raw_sensor_frame)
                current_info = info

                if "joint_position" not in info:
                    termination_reason = str(info["termination_reason"])
                    break

                actual = np.concatenate(
                    (
                        np.asarray(info["joint_position"], dtype=np.float32),
                        np.asarray(info["joint_velocity"], dtype=np.float32),
                    )
                )
                for (
                    horizon,
                    prediction,
                    hold_prediction,
                    constant_velocity_prediction,
                ) in pending.pop(step, []):
                    tcn_errors[horizon].append(prediction - actual)
                    hold_errors[horizon].append(hold_prediction - actual)
                    constant_velocity_errors[horizon].append(
                        constant_velocity_prediction - actual
                    )

                if terminated or truncated:
                    termination_reason = str(info["termination_reason"])
                    break

            result = adapter.predict()
            z_frames.append(adapter.latest_normalized_frame)
            current = np.concatenate(
                (
                    np.asarray(
                        current_info["joint_position"], dtype=np.float32
                    ),
                    np.asarray(
                        current_info["joint_velocity"], dtype=np.float32
                    ),
                )
            )
            for index, horizon in enumerate(adapter.horizons):
                hold_prediction = current.copy()
                constant_velocity_prediction = current.copy()
                constant_velocity_prediction[:4] += (
                    current[4:8] * horizon * 0.02
                )
                pending[step + horizon].append(
                    (
                        horizon,
                        result.joint_prediction[index].copy(),
                        hold_prediction,
                        constant_velocity_prediction,
                    )
                )
    finally:
        env.close()

    z = np.stack(z_frames, axis=0)
    deployment_features = adapter.deployment_features(
        result,
        np.asarray(current_info["joint_position"], dtype=np.float32),
        np.asarray(current_info["joint_velocity"], dtype=np.float32),
    )
    report = {
        "checkpoint": str(args.checkpoint.expanduser().resolve()),
        "calibration": str(args.calibration.expanduser().resolve()),
        "motion_id": args.motion_id,
        "seed": args.seed,
        "completed_steps": completed_steps,
        "termination_reason": termination_reason,
        "history_length": adapter.history_length,
        "horizons_steps": list(adapter.horizons),
        "identity_calibration": False,
        "prediction_error_is_calibrated_cross_model_proxy": True,
        "input_distribution": {
            "all": distribution_metrics(z),
            "motor_position": distribution_metrics(z[:, :4]),
            "motor_velocity": distribution_metrics(z[:, 4:8]),
            "imu": distribution_metrics(z[:, 8:]),
        },
        "prediction_error": {
            str(horizon): {
                "tcn": error_metrics(tcn_errors[horizon]),
                "hold": error_metrics(hold_errors[horizon]),
                "constant_velocity": error_metrics(
                    constant_velocity_errors[horizon]
                ),
            }
            for horizon in adapter.horizons
        },
        "explicit_prediction_dim": int(result.actor_features.size),
        "actor_feature_horizons_steps": list(
            adapter.actor_feature_horizon_steps
        ),
        "actor_feature_dim": int(deployment_features.size),
        "actor_feature_abs_max": float(
            np.max(np.abs(deployment_features))
        ),
        "finite": bool(
            np.all(np.isfinite(z))
            and np.all(np.isfinite(result.prediction))
            and np.all(np.isfinite(result.joint_prediction))
            and np.all(np.isfinite(result.latent))
            and np.all(np.isfinite(deployment_features))
        ),
        "interpretation": (
            "Connect TCN features to PPO only if holdout TCN error is "
            "consistently lower than hold and constant-velocity baselines."
        ),
    }

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print(json.dumps(report, indent=2, ensure_ascii=False))
    print("report:", output)


if __name__ == "__main__":
    main()
