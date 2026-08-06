from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import torch

from RL.data.tcn_dataset import TCNDataset, VARIABLE_SPEED_TARGETS
from RL.runners.predictors.tcn import MotionTCN, masked_mse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MANIFEST = PROJECT_ROOT / "RL/assets/datasets/phase12_manifest.json"
DEFAULT_REPORT = PROJECT_ROOT / "RL/outputs/tcn_pipeline_check.json"


def check(name: str, function) -> dict:
    try:
        details = function()
        return {"name": name, "status": "passed", "details": details}
    except Exception as error:
        return {
            "name": name,
            "status": "failed",
            "error": f"{type(error).__name__}: {error}",
        }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--manifest", type=Path, default=DEFAULT_MANIFEST)
    parser.add_argument("--processed-root", type=Path)
    parser.add_argument("--checkpoint", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    external_root = os.environ.get("GEXO_DATA_ROOT")
    manifest = json.loads(args.manifest.read_text(encoding="utf-8"))
    variable_speed = bool(manifest.get("variable_speed", False))

    if args.processed_root is None:
        if not external_root:
            raise RuntimeError("Set GEXO_DATA_ROOT or pass --processed-root.")

        args.processed_root = Path(external_root) / "processed" / (
            "tcn50_variable_speed"
            if variable_speed
            else "tcn50"
        )
    state: dict[str, object] = {}

    def check_manifest() -> dict:
        train_subjects = {
            item["subject"] for item in manifest["trials"] if item["split"] == "train"
        }
        validation_subjects = {
            item["subject"]
            for item in manifest["trials"]
            if item["split"] == "validation"
        }
        test_subjects = {
            item["subject"] for item in manifest["trials"] if item["split"] == "test"
        }

        if (
            train_subjects & validation_subjects
            or train_subjects & test_subjects
            or validation_subjects & test_subjects
        ):
            raise ValueError("Train, validation and test subjects overlap.")

        if len(manifest["input_columns"]) != 32:
            raise ValueError("Manifest input dimension is not 32.")

        activities = sorted({
            item.get("activity", "fixed_speed_walk")
            for item in manifest["trials"]
        })

        if variable_speed and "start_stop" not in activities:
            raise ValueError("Variable-speed manifest has no start_stop trial.")

        return {
            "trials": len(manifest["trials"]),
            "train_subjects": sorted(train_subjects),
            "validation_subjects": sorted(validation_subjects),
            "test_subjects": sorted(test_subjects),
            "activities": activities,
        }

    def check_npz() -> dict:
        files = sorted(args.processed_root.glob("*/*/*.npz"))

        if len(files) != len(manifest["trials"]):
            raise ValueError(
                f"Expected {len(manifest['trials'])} NPZ files, found {len(files)}."
            )

        mask_sum = np.zeros(12, dtype=np.float64)
        frame_count = 0
        valid_input_frame_count = 0
        time_steps = []

        for path in files:
            with np.load(path) as data:
                length = len(data["time"])
                expected = {
                    "input": (length, 32),
                    "target": (length, 12),
                    "input_valid": (length,),
                    "target_mask": (length, 12),
                }

                if variable_speed:
                    expected.update({
                        "motion_rate": (length,),
                        "motion_rate_mask": (length,),
                    })

                for key, shape in expected.items():
                    if data[key].shape != shape:
                        raise ValueError(f"{path}: {key} has shape {data[key].shape}.")

                if not np.isfinite(data["input"]).all():
                    raise ValueError(f"{path}: input contains NaN or Inf.")

                if not np.isfinite(data["target"]).all():
                    raise ValueError(f"{path}: target contains NaN or Inf.")

                if not variable_speed and not data["input_valid"].all():
                    raise ValueError(f"{path}: invalid input frame exists.")

                time_steps.append(float(np.median(np.diff(data["time"]))))
                mask_sum += data["target_mask"].sum(axis=0)
                frame_count += length
                valid_input_frame_count += int(data["input_valid"].sum())

        if not np.allclose(time_steps, 0.02, atol=1e-4):
            raise ValueError("Processed data is not uniformly 50 Hz.")

        return {
            "files": len(files),
            "frames": frame_count,
            "dt_min": min(time_steps),
            "dt_max": max(time_steps),
            "target_valid_ratio": (mask_sum / frame_count).tolist(),
            "input_valid_ratio": valid_input_frame_count / frame_count,
            "invalid_input_frames": frame_count - valid_input_frame_count,
        }

    def check_dataset() -> dict:
        train = TCNDataset(
            args.processed_root,
            "train",
            include_auxiliary=variable_speed,
        )
        validation = TCNDataset(
            args.processed_root,
            "validation",
            statistics=train.statistics,
            include_auxiliary=variable_speed,
        )
        sample = train[0]
        inputs, targets, mask = sample[:3]

        if inputs.shape != (32, 50) or targets.shape != (2, 12):
            raise ValueError("Dataset sample shape is incorrect.")

        if not torch.isfinite(inputs).all() or not torch.isfinite(targets).all():
            raise ValueError("Dataset sample contains NaN or Inf.")

        state["train_dataset"] = train
        details = {
            "train_samples": len(train),
            "validation_samples": len(validation),
            "sample_mask_valid": int(mask.sum()),
        }

        if variable_speed:
            auxiliary, auxiliary_mask = sample[3:]

            if auxiliary.shape != (2, len(VARIABLE_SPEED_TARGETS)):
                raise ValueError("Auxiliary sample shape is incorrect.")

            weights = train.balanced_sample_weights()
            details.update({
                "auxiliary_shape": list(auxiliary.shape),
                "auxiliary_mask_valid": int(auxiliary_mask.sum()),
                "sample_weight_min": float(weights.min()),
                "sample_weight_max": float(weights.max()),
                "sample_weight_mean": float(weights.mean()),
            })

        return details

    def check_model() -> dict:
        train = state["train_dataset"]
        model = MotionTCN(
            dropout=0.0,
            auxiliary_dim=(
                len(VARIABLE_SPEED_TARGETS)
                if variable_speed
                else 0
            ),
        )
        sample = train[0]
        inputs, targets, mask = sample[:3]

        if variable_speed:
            prediction, auxiliary_prediction = model.forward_with_auxiliary(
                inputs.unsqueeze(0)
            )
            auxiliary, auxiliary_mask = sample[3:]
            auxiliary_loss = masked_mse(
                auxiliary_prediction,
                auxiliary.unsqueeze(0),
                auxiliary_mask.unsqueeze(0),
            )
        else:
            prediction = model(inputs.unsqueeze(0))
            auxiliary_loss = 0.0

        loss = masked_mse(prediction, targets.unsqueeze(0), mask.unsqueeze(0))
        (loss + auxiliary_loss).backward()

        if prediction.shape != (1, 2, 12):
            raise ValueError("Model prediction shape is incorrect.")

        if not all(
            parameter.grad is not None and torch.isfinite(parameter.grad).all()
            for parameter in model.parameters()
        ):
            raise ValueError("A model gradient is missing or non-finite.")

        parameter_count = sum(parameter.numel() for parameter in model.parameters())
        return {"parameters": parameter_count, "loss": float(loss.detach())}

    def check_causality() -> dict:
        torch.manual_seed(0)
        model = MotionTCN(dropout=0.0).eval()
        original = torch.randn(1, 32, 50)
        changed = original.clone()
        cutoff = 24
        changed[:, :, cutoff + 1 :] = torch.randn_like(changed[:, :, cutoff + 1 :])

        with torch.no_grad():
            original_features = model.encoder(original)
            changed_features = model.encoder(changed)

        difference = float(
            (original_features[:, :, : cutoff + 1]
             - changed_features[:, :, : cutoff + 1]).abs().max()
        )

        if difference > 1e-6:
            raise ValueError(f"Future input changed past features by {difference}.")

        return {"maximum_past_difference": difference, "cutoff_frame": cutoff}

    def check_checkpoint() -> dict:
        if args.checkpoint is None:
            return {"status": "not_requested"}

        if (args.checkpoint.parent / "INVALID.md").exists():
            raise ValueError("Checkpoint directory is marked INVALID.")

        checkpoint = torch.load(args.checkpoint, map_location="cpu", weights_only=False)

        if not checkpoint.get("validation_read_only", False):
            raise ValueError("Checkpoint lacks clean-validation provenance.")

        model = MotionTCN(
            input_dim=int(checkpoint["input_dim"]),
            hidden_dim=int(checkpoint["hidden_dim"]),
            target_dim=int(checkpoint["target_dim"]),
            horizon_count=len(checkpoint["horizons"]),
            dropout=float(checkpoint.get("dropout", 0.0)),
            auxiliary_dim=int(checkpoint.get("auxiliary_dim", 0)),
        )
        model.load_state_dict(checkpoint["model_state_dict"])
        return {
            "epoch": int(checkpoint["epoch"]),
            "validation_loss": float(checkpoint["validation_loss"]),
            "seed": int(checkpoint.get("seed", -1)),
        }

    tests = [
        check("manifest", check_manifest),
        check("processed_npz", check_npz),
        check("dataset", check_dataset),
        check("model_forward_backward", check_model),
        check("model_causality", check_causality),
        check("checkpoint", check_checkpoint),
    ]
    report = {
        "passed": all(test["status"] == "passed" for test in tests),
        "tests": tests,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print("report:", args.output.resolve())

    if not report["passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
