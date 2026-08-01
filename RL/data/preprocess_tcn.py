from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import pandas as pd


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MANIFEST = (
    PROJECT_ROOT
    / "RL/assets/datasets/phase12_manifest.json"
)

DOWNSAMPLE_FACTOR = 4
MOTION_RATE_WINDOW = 25


def block_average(
    values: np.ndarray,
    factor: int,
) -> tuple[np.ndarray, np.ndarray]:
    """每factor帧做一次因果块平均，并返回有效样本数。"""

    length = len(values) // factor * factor

    if length == 0:
        raise ValueError("Trial is shorter than one block.")

    blocks = values[:length].reshape(
        -1,
        factor,
        values.shape[1],
    )

    finite = np.isfinite(blocks)
    counts = finite.sum(axis=1)

    averages = (
        np.where(finite, blocks, 0.0).sum(axis=1)
        / np.maximum(counts, 1)
    )

    return averages.astype(np.float32), counts


def causal_motion_rate(
    joint_velocity: np.ndarray,
    valid: np.ndarray,
    window: int = MOTION_RATE_WINDOW,
) -> tuple[np.ndarray, np.ndarray]:
    """计算四关节速度的因果 RMS 包络，作为步态速率代理。"""

    if joint_velocity.shape[1] != 4 or valid.shape != joint_velocity.shape:
        raise ValueError("Motion-rate input must contain four joint velocities.")

    frame_valid = valid.all(axis=1)
    squared_rate = np.mean(joint_velocity**2, axis=1)
    squared_rate = np.where(frame_valid, squared_rate, 0.0)
    cumulative = np.concatenate(([0.0], np.cumsum(squared_rate)))
    valid_cumulative = np.concatenate((
        [0],
        np.cumsum(frame_valid.astype(np.int64)),
    ))
    rate = np.zeros(len(joint_velocity), dtype=np.float32)
    rate_valid = np.zeros(len(joint_velocity), dtype=bool)

    if len(joint_velocity) >= window:
        sums = cumulative[window:] - cumulative[:-window]
        counts = valid_cumulative[window:] - valid_cumulative[:-window]
        rate[window - 1:] = np.sqrt(
            np.maximum(sums / window, 0.0)
        ).astype(np.float32)
        rate_valid[window - 1:] = counts == window

    return rate, rate_valid


def load_trial(
    dataset_root: Path,
    trial: dict,
    input_columns: list[str],
    target_columns: dict[str, list[str]],
) -> dict[str, np.ndarray]:
    """读取一个trial并转换为50 Hz数组。"""

    files = {
        name: dataset_root / relative_path
        for name, relative_path in trial["files"].items()
    }

    columns = {
        "exo": input_columns,
        "angle": target_columns["angle"],
        "velocity": target_columns["velocity"],
        "moment": target_columns["moment"],
    }

    tables = {
        name: pd.read_csv(
            files[name],
            usecols=["time", *required_columns],
        )
        for name, required_columns in columns.items()
    }

    # 四个CSV必须逐帧对齐。
    time = tables["exo"]["time"].to_numpy(
        dtype=np.float64
    )

    for name, table in tables.items():
        other_time = table["time"].to_numpy(
            dtype=np.float64
        )

        if (
            time.shape != other_time.shape
            or not np.allclose(
                time,
                other_time,
                atol=1e-6,
                rtol=0.0,
            )
        ):
            raise ValueError(
                f"Time mismatch in {trial['trial']}: {name}"
            )

    source_dt = float(np.median(np.diff(time)))

    if not np.isclose(
        source_dt,
        0.005,
        atol=1e-5,
    ):
        raise ValueError(
            f"Expected 200 Hz data, got dt={source_dt}."
        )

    inputs = tables["exo"][
        input_columns
    ].to_numpy(dtype=np.float64)

    targets = np.concatenate(
        [
            tables["angle"][
                target_columns["angle"]
            ].to_numpy(dtype=np.float64),
            tables["velocity"][
                target_columns["velocity"]
            ].to_numpy(dtype=np.float64),
            tables["moment"][
                target_columns["moment"]
            ].to_numpy(dtype=np.float64),
        ],
        axis=1,
    )

    # 编码器角度、角速度和IMU角速度由degree转为rad。
    input_scale = np.ones(
        len(input_columns),
        dtype=np.float64,
    )

    for index, column in enumerate(input_columns):
        if (
            index < 8
            or "_gyro_" in column
        ):
            input_scale[index] = np.pi / 180.0

    # 前4维角度、随后4维角速度转为SI单位。
    target_scale = np.ones(
        targets.shape[1],
        dtype=np.float64,
    )
    target_scale[:8] = np.pi / 180.0

    inputs *= input_scale
    targets *= target_scale

    inputs, input_counts = block_average(
        inputs,
        DOWNSAMPLE_FACTOR,
    )

    targets, target_counts = block_average(
        targets,
        DOWNSAMPLE_FACTOR,
    )

    length = len(time) // DOWNSAMPLE_FACTOR
    time = time[:length * DOWNSAMPLE_FACTOR].reshape(
        length,
        DOWNSAMPLE_FACTOR,
    )[:, -1]

    # 输入必须在整个20 ms块内均有效。
    input_valid = np.all(
        input_counts == DOWNSAMPLE_FACTOR,
        axis=1,
    )

    # 每个标签独立决定是否参与损失。
    target_mask = target_counts > 0
    angle_count = len(target_columns["angle"])
    velocity_count = len(target_columns["velocity"])
    velocity_slice = slice(
        angle_count,
        angle_count + velocity_count,
    )
    motion_rate, motion_rate_mask = causal_motion_rate(
        targets[:, velocity_slice],
        target_mask[:, velocity_slice],
    )

    return {
        "time": time.astype(np.float32),
        "input": inputs,
        "target": targets,
        "input_valid": input_valid,
        "target_mask": target_mask,
        "motion_rate": motion_rate,
        "motion_rate_mask": motion_rate_mask,
    }


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    parser.add_argument(
        "--output-root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--overwrite",
        action="store_true",
    )
    parser.add_argument(
        "--remove-stale",
        action="store_true",
        help="Remove generated NPZ files not present in the current manifest.",
    )

    arguments = parser.parse_args()

    manifest = json.loads(
        arguments.manifest.read_text(
            encoding="utf-8"
        )
    )

    dataset_root = Path(manifest["dataset_root"])

    if arguments.output_root is None:
        data_root = os.environ.get("GEXO_DATA_ROOT")

        if not data_root:
            raise RuntimeError(
                "Set GEXO_DATA_ROOT or pass --output-root."
            )

        output_root = (
            Path(data_root)
            / "processed"
            / (
                "tcn50_variable_speed"
                if manifest.get("variable_speed", False)
                else "tcn50"
            )
        )
    else:
        output_root = arguments.output_root

    if arguments.remove_stale:
        expected = {
            (
                output_root
                / trial["split"]
                / trial["subject"]
                / f"{trial['trial']}.npz"
            ).resolve()
            for trial in manifest["trials"]
        }
        splits = {trial["split"] for trial in manifest["trials"]}
        stale = [
            path
            for split in splits
            for path in (output_root / split).glob("*/*.npz")
            if path.resolve() not in expected
        ]

        for path in stale:
            path.unlink()

        if stale:
            print(f"removed stale: {len(stale)}")

    saved = 0
    skipped = 0

    for trial in manifest["trials"]:
        output_path = (
            output_root
            / trial["split"]
            / trial["subject"]
            / f"{trial['trial']}.npz"
        )

        if output_path.exists() and not arguments.overwrite:
            skipped += 1
            continue

        data = load_trial(
            dataset_root,
            trial,
            manifest["input_columns"],
            manifest["target_columns"],
        )

        output_path.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        np.savez_compressed(
            output_path,
            **data,
            subject=trial["subject"],
            trial=trial["trial"],
            condition=trial["condition"],
            assist_condition=trial.get(
                "assist_condition",
                trial["condition"],
            ),
            activity=trial.get("activity", "fixed_speed_walk"),
            nominal_speed_m_s=(
                np.nan
                if trial.get("nominal_speed_m_s") is None
                else float(trial["nominal_speed_m_s"])
            ),
            transition_capable=bool(
                trial.get("transition_capable", False)
            ),
        )

        saved += 1
        print(
            f"[{saved:03d}] "
            f"{trial['split']}/{trial['subject']}/"
            f"{trial['trial']}"
        )

    print(f"saved: {saved}")
    print(f"existing skipped: {skipped}")
    print(f"output root: {output_root.resolve()}")


if __name__ == "__main__":
    main()
