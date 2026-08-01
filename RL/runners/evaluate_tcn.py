from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader

from RL.data.tcn_dataset import TCNDataset, VARIABLE_SPEED_TARGETS
from RL.runners.predictors.tcn import MotionTCN


TARGET_NAMES = (
    "left_hip_angle",
    "left_knee_angle",
    "right_hip_angle",
    "right_knee_angle",
    "left_hip_velocity",
    "left_knee_velocity",
    "right_hip_velocity",
    "right_knee_velocity",
    "left_hip_moment",
    "left_knee_moment",
    "right_hip_moment",
    "right_knee_moment",
)
TARGET_GROUPS = {
    "angle_rad": slice(0, 4),
    "velocity_rad_s": slice(4, 8),
    "moment_nm_kg": slice(8, 12),
}


def new_accumulator(horizons: int, targets: int) -> dict[str, np.ndarray]:
    shape = (horizons, targets)
    return {
        "normalized_se": np.zeros(shape),
        "tcn_se": np.zeros(shape),
        "mean_se": np.zeros(shape),
        "persistence_se": np.zeros(shape),
        "constant_velocity_se": np.zeros(shape),
        "count": np.zeros(shape),
        "persistence_count": np.zeros(shape),
        "constant_velocity_count": np.zeros(shape),
    }


def update_accumulator(
    accumulator: dict[str, np.ndarray],
    normalized_error: np.ndarray,
    physical_error: np.ndarray,
    mean_error: np.ndarray,
    mask: np.ndarray,
    persistence_error: np.ndarray,
    persistence_mask: np.ndarray,
    constant_velocity_error: np.ndarray,
    constant_velocity_mask: np.ndarray,
) -> None:
    accumulator["normalized_se"] += np.where(
        mask, normalized_error**2, 0.0
    )
    accumulator["tcn_se"] += np.where(mask, physical_error**2, 0.0)
    accumulator["mean_se"] += np.where(mask, mean_error**2, 0.0)
    accumulator["persistence_se"] += np.where(
        persistence_mask, persistence_error**2, 0.0
    )
    accumulator["count"] += mask
    accumulator["persistence_count"] += persistence_mask
    accumulator["constant_velocity_se"] += np.where(
        constant_velocity_mask,
        constant_velocity_error**2,
        0.0,
    )
    accumulator["constant_velocity_count"] += constant_velocity_mask


def rmse(error_sum: np.ndarray, count: np.ndarray) -> float | None:
    total_count = float(count.sum())
    return None if total_count == 0.0 else float(np.sqrt(error_sum.sum() / total_count))


def summarize(
    accumulator: dict[str, np.ndarray],
    horizon_steps: tuple[int, ...],
) -> dict:
    count = accumulator["count"]
    result = {
        "normalized_mse": float(
            accumulator["normalized_se"].sum() / max(count.sum(), 1.0)
        ),
        "horizons": {},
    }

    for horizon_index, steps in enumerate(horizon_steps):
        horizon = {}

        for group_name, group_slice in TARGET_GROUPS.items():
            horizon[group_name] = {
                "tcn_rmse": rmse(
                    accumulator["tcn_se"][horizon_index, group_slice],
                    count[horizon_index, group_slice],
                ),
                "training_mean_rmse": rmse(
                    accumulator["mean_se"][horizon_index, group_slice],
                    count[horizon_index, group_slice],
                ),
                "persistence_rmse": rmse(
                    accumulator["persistence_se"][horizon_index, group_slice],
                    accumulator["persistence_count"][horizon_index, group_slice],
                ),
                "constant_velocity_rmse": rmse(
                    accumulator["constant_velocity_se"][horizon_index, group_slice],
                    accumulator["constant_velocity_count"][horizon_index, group_slice],
                ),
            }

        horizon["per_target"] = {
            name: {
                "tcn_rmse": rmse(
                    accumulator["tcn_se"][horizon_index, index : index + 1],
                    count[horizon_index, index : index + 1],
                ),
                "valid_labels": int(count[horizon_index, index]),
            }
            for index, name in enumerate(TARGET_NAMES)
        }
        result["horizons"][f"{steps * 20}_ms"] = horizon

    return result


def resolve_device(name: str) -> torch.device:
    if name == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available.")

    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "cpu"

    return torch.device(name)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--checkpoint", type=Path, required=True)
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--split", default="validation")
    parser.add_argument("--batch-size", type=int, default=512)
    parser.add_argument("--num-workers", type=int, default=0)
    parser.add_argument(
        "--device", choices=("auto", "cpu", "cuda"), default="auto"
    )
    args = parser.parse_args()

    if (args.checkpoint.parent / "INVALID.md").exists():
        raise RuntimeError(f"Checkpoint is explicitly invalid: {args.checkpoint}")

    checkpoint = torch.load(
        args.checkpoint,
        map_location="cpu",
        weights_only=False,
    )

    if not checkpoint.get("validation_read_only", False):
        raise RuntimeError("Checkpoint lacks clean-validation provenance.")

    variable_speed = bool(checkpoint.get("variable_speed", False))
    data_root = args.data_root

    if data_root is None:
        external_root = os.environ.get("GEXO_DATA_ROOT")

        if not external_root:
            raise RuntimeError("Set GEXO_DATA_ROOT or pass --data-root.")

        data_root = Path(external_root) / "processed" / (
            "tcn50_variable_speed"
            if variable_speed
            else "tcn50"
        )
    dataset = TCNDataset(
        data_root,
        args.split,
        history=int(checkpoint["history"]),
        horizons=tuple(checkpoint["horizons"]),
        statistics=checkpoint["statistics"],
        include_auxiliary=variable_speed,
    )
    loader = DataLoader(
        dataset,
        batch_size=args.batch_size,
        shuffle=False,
        num_workers=args.num_workers,
    )
    device = resolve_device(args.device)
    model = MotionTCN(
        input_dim=int(checkpoint["input_dim"]),
        hidden_dim=int(checkpoint["hidden_dim"]),
        target_dim=int(checkpoint["target_dim"]),
        horizon_count=len(checkpoint["horizons"]),
        dropout=float(checkpoint.get("dropout", 0.0)),
        auxiliary_dim=int(checkpoint.get("auxiliary_dim", 0)),
    ).to(device)
    model.load_state_dict(checkpoint["model_state_dict"])
    model.eval()
    target_std = np.asarray(checkpoint["statistics"]["target_std"])
    accumulators = {
        "overall": new_accumulator(len(dataset.horizons), 12),
        "by_subject": {},
        "by_condition": {},
        "by_activity": {},
        "by_speed": {},
        "by_transition": {},
    }
    auxiliary_squared_error = np.zeros(
        (len(dataset.horizons), len(VARIABLE_SPEED_TARGETS)),
        dtype=np.float64,
    )
    auxiliary_count = np.zeros_like(auxiliary_squared_error)
    cursor = 0

    with torch.no_grad():
        for batch in loader:
            inputs, targets, mask = batch[:3]

            if variable_speed:
                auxiliary_target = batch[3]
                auxiliary_mask = batch[4]
                prediction_tensor, auxiliary_prediction_tensor = (
                    model.forward_with_auxiliary(inputs.to(device))
                )
                predictions = prediction_tensor.cpu().numpy()
                auxiliary_prediction = auxiliary_prediction_tensor.cpu().numpy()
                auxiliary_target_np = auxiliary_target.numpy()
                auxiliary_mask_np = auxiliary_mask.numpy()
                auxiliary_physical_error = (
                    auxiliary_prediction - auxiliary_target_np
                ) * np.asarray(checkpoint["statistics"]["auxiliary_std"])
                auxiliary_squared_error += np.where(
                    auxiliary_mask_np,
                    auxiliary_physical_error**2,
                    0.0,
                ).sum(axis=0)
                auxiliary_count += auxiliary_mask_np.sum(axis=0)
            else:
                predictions = model(inputs.to(device)).cpu().numpy()
            targets_np = targets.numpy()
            mask_np = mask.numpy()
            normalized_error = predictions - targets_np
            physical_error = normalized_error * target_std
            mean_error = -targets_np * target_std

            for batch_index in range(len(inputs)):
                trial_index, end = dataset.samples[cursor + batch_index]
                trial = dataset.trials[trial_index]
                current = trial["target"][end]
                current_mask = trial["target_mask"][end]
                persistence_error = np.zeros_like(targets_np[batch_index])
                persistence_mask = np.zeros_like(mask_np[batch_index])
                constant_velocity_error = np.zeros_like(targets_np[batch_index])
                constant_velocity_mask = np.zeros_like(mask_np[batch_index])

                for horizon_index, steps in enumerate(dataset.horizons):
                    future_index = end + steps
                    future = trial["target"][future_index]
                    future_mask = trial["target_mask"][future_index]
                    persistence_error[horizon_index] = current - future
                    persistence_mask[horizon_index] = current_mask & future_mask
                    constant_velocity = current.copy()
                    constant_velocity[:4] = (
                        current[:4]
                        + steps * 0.02 * current[4:8]
                    )
                    constant_velocity_error[horizon_index] = (
                        constant_velocity - future
                    )
                    constant_velocity_mask[horizon_index] = (
                        current_mask & future_mask
                    )

                transition = dataset.transition_label(trial_index, end) if variable_speed else "fixed_speed"
                speed = trial["nominal_speed_m_s"]
                speed_key = (
                    f"{speed:.1f}"
                    if np.isfinite(speed)
                    else "unknown"
                )

                keys = (
                    ("overall", "overall"),
                    ("by_subject", trial["subject"]),
                    ("by_condition", trial["condition"]),
                    ("by_activity", trial["activity"]),
                    ("by_speed", speed_key),
                    ("by_transition", transition),
                )

                for group, key in keys:
                    if group == "overall":
                        accumulator = accumulators["overall"]
                    else:
                        accumulator = accumulators[group].setdefault(
                            key, new_accumulator(len(dataset.horizons), 12)
                        )

                    update_accumulator(
                        accumulator,
                        normalized_error[batch_index],
                        physical_error[batch_index],
                        mean_error[batch_index],
                        mask_np[batch_index],
                        persistence_error,
                        persistence_mask,
                        constant_velocity_error,
                        constant_velocity_mask,
                    )

            cursor += len(inputs)

    report = {
        "checkpoint": str(args.checkpoint.resolve()),
        "checkpoint_epoch": int(checkpoint["epoch"]),
        "checkpoint_seed": int(checkpoint["seed"]),
        "checkpoint_validation_loss": float(checkpoint["validation_loss"]),
        "device": str(device),
        "data_root": str(data_root.expanduser().resolve()),
        "split": args.split,
        "samples": len(dataset),
        "validation_samples": len(dataset),
        "moment_unit": "Nm/kg",
        "input_realtime_note": (
            "The dataset does not document whether exo velocity_filt is causal. "
            "Replace or reproduce it with an online filter before deployment."
        ),
        "target_processing_note": (
            "Filtered angle/moment labels and central-difference velocity labels "
            "are offline supervision targets; they are not policy observations."
        ),
        "overall": summarize(accumulators["overall"], dataset.horizons),
        "by_subject": {
            key: summarize(value, dataset.horizons)
            for key, value in accumulators["by_subject"].items()
        },
        "by_condition": {
            key: summarize(value, dataset.horizons)
            for key, value in accumulators["by_condition"].items()
        },
        "by_activity": {
            key: summarize(value, dataset.horizons)
            for key, value in accumulators["by_activity"].items()
        },
        "by_speed": {
            key: summarize(value, dataset.horizons)
            for key, value in accumulators["by_speed"].items()
        },
        "by_transition": {
            key: summarize(value, dataset.horizons)
            for key, value in accumulators["by_transition"].items()
        },
    }

    if variable_speed:
        report["auxiliary"] = {
            f"{steps * 20}_ms": {
                name: {
                    "rmse": rmse(
                        auxiliary_squared_error[horizon_index, index:index + 1],
                        auxiliary_count[horizon_index, index:index + 1],
                    ),
                    "valid_labels": int(
                        auxiliary_count[horizon_index, index]
                    ),
                }
                for index, name in enumerate(VARIABLE_SPEED_TARGETS)
            }
            for horizon_index, steps in enumerate(dataset.horizons)
        }
    default_name = (
        "evaluation.json"
        if args.split == "validation"
        else f"{args.split}_evaluation.json"
    )
    output = args.output or args.checkpoint.parent / default_name
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    print(json.dumps(report["overall"], ensure_ascii=False, indent=2))
    print("report:", output.resolve())


if __name__ == "__main__":
    main()
