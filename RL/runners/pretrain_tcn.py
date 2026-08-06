from __future__ import annotations

import argparse
import json
import os
import random
from pathlib import Path

import numpy as np
import torch
from torch.utils.data import DataLoader, WeightedRandomSampler
from torch.utils.tensorboard import SummaryWriter

from RL.data.tcn_dataset import TCNDataset, VARIABLE_SPEED_TARGETS
from RL.runners.predictors.tcn import MotionTCN, masked_mse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT_ROOT = PROJECT_ROOT / "RL/outputs/tcn_runs"
DEFAULT_VARIABLE_SPEED_OUTPUT_ROOT = (
    PROJECT_ROOT / "RL/outputs/tcn_variable_speed_runs"
)


def set_seed(seed: int) -> None:
    """Fix random generators used by this training process."""

    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)

    if torch.cuda.is_available():
        torch.cuda.manual_seed_all(seed)


def run_epoch(
    model: MotionTCN,
    loader: DataLoader,
    device: torch.device,
    optimizer: torch.optim.Optimizer | None = None,
    auxiliary_loss_weight: float = 0.0,
) -> dict[str, float]:
    """Run one epoch and return separately auditable motion/auxiliary losses."""

    training = optimizer is not None
    model.train(training)
    squared_error_sum = 0.0
    valid_label_count = 0
    auxiliary_squared_error_sum = 0.0
    auxiliary_valid_count = 0

    for batch in loader:
        inputs, targets, mask = batch[:3]
        auxiliary_target = batch[3] if len(batch) == 5 else None
        auxiliary_mask = batch[4] if len(batch) == 5 else None
        inputs = inputs.to(device, non_blocking=True)
        targets = targets.to(device, non_blocking=True)
        mask = mask.to(device, non_blocking=True)

        if auxiliary_target is not None:
            auxiliary_target = auxiliary_target.to(device, non_blocking=True)
            auxiliary_mask = auxiliary_mask.to(device, non_blocking=True)

        if training:
            optimizer.zero_grad(set_to_none=True)

        with torch.set_grad_enabled(training):
            if auxiliary_target is None:
                prediction = model(inputs)
                auxiliary_loss = None
            else:
                prediction, auxiliary_prediction = model.forward_with_auxiliary(
                    inputs
                )
                auxiliary_loss = masked_mse(
                    auxiliary_prediction,
                    auxiliary_target,
                    auxiliary_mask,
                )

            motion_loss = masked_mse(prediction, targets, mask)
            loss = motion_loss

            if auxiliary_loss is not None:
                loss = loss + auxiliary_loss_weight * auxiliary_loss

            if training:
                loss.backward()
                optimizer.step()

        valid = int(mask.sum().item())
        squared_error_sum += float(motion_loss.detach()) * valid
        valid_label_count += valid

        if auxiliary_loss is not None:
            auxiliary_valid = int(auxiliary_mask.sum().item())
            auxiliary_squared_error_sum += (
                float(auxiliary_loss.detach()) * auxiliary_valid
            )
            auxiliary_valid_count += auxiliary_valid

    if valid_label_count == 0:
        raise RuntimeError("Epoch contains no valid labels.")

    motion_mse = squared_error_sum / valid_label_count
    auxiliary_mse = (
        auxiliary_squared_error_sum / auxiliary_valid_count
        if auxiliary_valid_count > 0
        else 0.0
    )
    return {
        "motion_mse": motion_mse,
        "auxiliary_mse": auxiliary_mse,
        "total": motion_mse + auxiliary_loss_weight * auxiliary_mse,
    }


def resolve_device(name: str) -> torch.device:
    if name == "cuda" and not torch.cuda.is_available():
        raise RuntimeError("CUDA was requested but is not available.")

    if name == "auto":
        name = "cuda" if torch.cuda.is_available() else "cpu"

    return torch.device(name)


def write_json(path: Path, value: object) -> None:
    path.write_text(
        json.dumps(value, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-root", type=Path)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--epochs", type=int, default=30)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--learning-rate", type=float, default=1e-3)
    parser.add_argument("--hidden-dim", type=int, default=64)
    parser.add_argument("--dropout", type=float, default=0.1)
    parser.add_argument("--patience", type=int, default=5)
    parser.add_argument("--num-workers", type=int, default=4)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="auto",
    )
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--variable-speed", action="store_true")
    parser.add_argument("--auxiliary-loss-weight", type=float, default=0.2)
    parser.add_argument("--initialize-from", type=Path)
    args = parser.parse_args()

    set_seed(args.seed)
    data_root = args.data_root

    if data_root is None:
        external_root = os.environ.get("GEXO_DATA_ROOT")

        if not external_root:
            raise RuntimeError("Set GEXO_DATA_ROOT or pass --data-root.")

        data_root = Path(external_root) / "processed" / (
            "tcn50_variable_speed"
            if args.variable_speed
            else "tcn50"
        )

    output = (
        args.output
        if args.output is not None
        else (
            DEFAULT_VARIABLE_SPEED_OUTPUT_ROOT
            if args.variable_speed
            else DEFAULT_OUTPUT_ROOT
        ) / f"seed_{args.seed}"
    ).expanduser().resolve()
    checkpoint_path = output / "best_model.pt"

    if checkpoint_path.exists() and not args.overwrite:
        raise FileExistsError(
            f"Run already exists: {checkpoint_path}. Use --overwrite explicitly."
        )

    output.mkdir(parents=True, exist_ok=True)
    device = resolve_device(args.device)
    train_dataset = TCNDataset(
        data_root,
        "train",
        include_auxiliary=args.variable_speed,
    )
    validation_dataset = TCNDataset(
        data_root,
        "validation",
        statistics=train_dataset.statistics,
        include_auxiliary=args.variable_speed,
    )
    use_cuda = device.type == "cuda"
    loader_options = {
        "batch_size": args.batch_size,
        "num_workers": args.num_workers,
        "pin_memory": use_cuda,
        "persistent_workers": args.num_workers > 0,
    }
    sampler = (
        WeightedRandomSampler(
            train_dataset.balanced_sample_weights(),
            num_samples=len(train_dataset),
            replacement=True,
        )
        if args.variable_speed
        else None
    )
    train_loader = DataLoader(
        train_dataset,
        shuffle=sampler is None,
        sampler=sampler,
        **loader_options,
    )
    validation_loader = DataLoader(
        validation_dataset,
        shuffle=False,
        **loader_options,
    )
    model = MotionTCN(
        input_dim=32,
        hidden_dim=args.hidden_dim,
        target_dim=12,
        horizon_count=len(train_dataset.horizons),
        dropout=args.dropout,
        auxiliary_dim=(
            len(VARIABLE_SPEED_TARGETS)
            if args.variable_speed
            else 0
        ),
    ).to(device)

    if args.initialize_from is not None:
        initial = torch.load(
            args.initialize_from,
            map_location="cpu",
            weights_only=False,
        )
        missing, unexpected = model.load_state_dict(
            initial["model_state_dict"],
            strict=False,
        )
        allowed_missing = {
            "auxiliary_head.weight",
            "auxiliary_head.bias",
        }

        if set(missing) - allowed_missing or unexpected:
            raise RuntimeError(
                f"Incompatible initialization: missing={missing}, "
                f"unexpected={unexpected}"
            )
    optimizer = torch.optim.Adam(model.parameters(), lr=args.learning_rate)
    writer = SummaryWriter(log_dir=str(output / "tensorboard"))
    config = {
        "pipeline_version": 2 if args.variable_speed else 1,
        "validation_read_only": True,
        "data_root": str(data_root.expanduser().resolve()),
        "seed": args.seed,
        "device": str(device),
        "epochs": args.epochs,
        "batch_size": args.batch_size,
        "learning_rate": args.learning_rate,
        "hidden_dim": args.hidden_dim,
        "dropout": args.dropout,
        "patience": args.patience,
        "history": train_dataset.history,
        "horizons": list(train_dataset.horizons),
        "train_samples": len(train_dataset),
        "validation_samples": len(validation_dataset),
        "parameters": sum(p.numel() for p in model.parameters()),
        "variable_speed": args.variable_speed,
        "auxiliary_dim": model.auxiliary_dim,
        "auxiliary_targets": list(VARIABLE_SPEED_TARGETS) if args.variable_speed else [],
        "auxiliary_loss_weight": (
            args.auxiliary_loss_weight if args.variable_speed else 0.0
        ),
        "balanced_sampling": args.variable_speed,
        "initialize_from": (
            str(args.initialize_from.expanduser().resolve())
            if args.initialize_from is not None
            else None
        ),
    }
    write_json(output / "config.json", config)
    np.savez(output / "normalization.npz", **train_dataset.statistics)
    history: list[dict[str, float | int]] = []
    best_loss = float("inf")
    best_epoch = 0
    stale_epochs = 0

    print("device:", device)
    print("train samples:", len(train_dataset))
    print("validation samples:", len(validation_dataset))
    print("parameters:", config["parameters"])

    try:
        for epoch in range(1, args.epochs + 1):
            auxiliary_weight = (
                args.auxiliary_loss_weight
                if args.variable_speed
                else 0.0
            )
            train_metrics = run_epoch(
                model,
                train_loader,
                device,
                optimizer,
                auxiliary_weight,
            )

            # No optimizer is passed here: validation cannot update the model.
            validation_metrics = run_epoch(
                model,
                validation_loader,
                device,
                auxiliary_loss_weight=auxiliary_weight,
            )
            train_loss = train_metrics["total"]
            validation_loss = validation_metrics["total"]
            record = {
                "epoch": epoch,
                "train_loss": train_loss,
                "validation_loss": validation_loss,
                "train_motion_mse": train_metrics["motion_mse"],
                "validation_motion_mse": validation_metrics["motion_mse"],
                "train_auxiliary_mse": train_metrics["auxiliary_mse"],
                "validation_auxiliary_mse": validation_metrics["auxiliary_mse"],
            }
            history.append(record)
            write_json(output / "history.json", history)
            writer.add_scalar("loss/train", train_loss, epoch)
            writer.add_scalar("loss/validation", validation_loss, epoch)
            writer.add_scalar(
                "loss_motion/train",
                train_metrics["motion_mse"],
                epoch,
            )
            writer.add_scalar(
                "loss_motion/validation",
                validation_metrics["motion_mse"],
                epoch,
            )

            if args.variable_speed:
                writer.add_scalar(
                    "loss_auxiliary/train",
                    train_metrics["auxiliary_mse"],
                    epoch,
                )
                writer.add_scalar(
                    "loss_auxiliary/validation",
                    validation_metrics["auxiliary_mse"],
                    epoch,
                )
            print(
                f"epoch {epoch:03d}: train={train_loss:.6f}, "
                f"validation={validation_loss:.6f}"
            )

            if validation_loss < best_loss:
                best_loss = validation_loss
                best_epoch = epoch
                stale_epochs = 0
                torch.save(
                    {
                        "pipeline_version": 2 if args.variable_speed else 1,
                        "validation_read_only": True,
                        "model_state_dict": model.state_dict(),
                        "epoch": epoch,
                        "validation_loss": validation_loss,
                        "input_dim": 32,
                        "hidden_dim": args.hidden_dim,
                        "target_dim": 12,
                        "dropout": args.dropout,
                        "history": train_dataset.history,
                        "horizons": train_dataset.horizons,
                        "statistics": train_dataset.statistics,
                        "seed": args.seed,
                        "variable_speed": args.variable_speed,
                        "auxiliary_dim": model.auxiliary_dim,
                        "auxiliary_targets": (
                            list(VARIABLE_SPEED_TARGETS)
                            if args.variable_speed
                            else []
                        ),
                        "auxiliary_loss_weight": auxiliary_weight,
                    },
                    checkpoint_path,
                )
                print("  saved best model")
            else:
                stale_epochs += 1

            if stale_epochs >= args.patience:
                print(f"early stopping after {args.patience} stale epochs")
                break
    finally:
        writer.close()

    summary = {
        "best_epoch": best_epoch,
        "best_validation_loss": best_loss,
        "checkpoint": str(checkpoint_path),
    }
    write_json(output / "summary.json", summary)
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
