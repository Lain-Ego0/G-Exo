from __future__ import annotations

import argparse
import csv
import json
import os
import re
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_OUTPUT = (
    PROJECT_ROOT
    / "RL/assets/datasets/phase12_manifest.json"
)
DEFAULT_VARIABLE_SPEED_OUTPUT = (
    PROJECT_ROOT
    / "RL/assets/datasets/phase12_variable_speed_manifest.json"
)

EXO_JOINTS = (
    "hip_angle_l",
    "knee_angle_l",
    "hip_angle_r",
    "knee_angle_r",
)

# 人体生物力学标签中的四个关节。
BIO_JOINTS = (
    "hip_flexion_l",
    "knee_angle_l",
    "hip_flexion_r",
    "knee_angle_r",
)

ENCODER_COLUMNS = (
    EXO_JOINTS
    + tuple(
        f"{joint}_velocity_filt"
        for joint in EXO_JOINTS
    )
)

IMU_COLUMNS = tuple(
    f"{segment}_imu_{side}_{signal}_{axis}"
    for side in ("l", "r")
    for segment in ("thigh", "shank")
    for signal in ("gyro", "accel")
    for axis in ("x", "y", "z")
)

INPUT_COLUMNS = ENCODER_COLUMNS + IMU_COLUMNS

ANGLE_COLUMNS = BIO_JOINTS

VELOCITY_COLUMNS = tuple(
    f"{joint}_velocity"
    for joint in BIO_JOINTS
)

MOMENT_COLUMNS = tuple(
    f"{joint}_moment"
    for joint in BIO_JOINTS
)

FILE_SUFFIXES = {
    "exo": "exo.csv",
    "angle": "angle_filt.csv",
    "velocity": "velocity.csv",
    "moment": "moment_filt_bio.csv",
}

REQUIRED_COLUMNS = {
    "exo": ("time",) + INPUT_COLUMNS,
    "angle": ("time",) + ANGLE_COLUMNS,
    "velocity": ("time",) + VELOCITY_COLUMNS,
    "moment": ("time",) + MOMENT_COLUMNS,
}

def read_header(path: Path) -> set[str]:
    """只读取CSV表头，不加载整段轨迹。"""

    with path.open(
        "r",
        encoding="utf-8-sig",
        newline="",
    ) as file:
        return set(next(csv.reader(file)))

def scan_dataset(
    dataset_root: Path,
    validation_subjects: set[str],
    *,
    include_subjects: set[str] | None = None,
    fixed_split: str | None = None,
    test_subjects: set[str] | None = None,
    include_start_stop: bool = False,
) -> dict:
    """扫描固定速度/启停行走 trial 并生成可复现的数据清单。"""

    if fixed_split not in (None, "train", "validation", "test"):
        raise ValueError(f"Unsupported fixed split: {fixed_split}")

    dataset_root = dataset_root.expanduser().resolve()
    test_subjects = test_subjects or set()

    if validation_subjects & test_subjects:
        raise ValueError("Validation and test subjects overlap.")

    if not dataset_root.is_dir():
        raise FileNotFoundError(
            f"Dataset directory does not exist: {dataset_root}"
        )

    trials = []
    skipped = []

    for subject_dir in sorted(dataset_root.glob("BT*")):
        if not subject_dir.is_dir():
            continue

        subject = subject_dir.name

        if include_subjects is not None and subject not in include_subjects:
            continue

        patterns = ["normal_walk*"]

        if include_start_stop:
            patterns.append("start_stop*")

        trial_dirs = sorted({
            path
            for pattern in patterns
            for path in subject_dir.glob(pattern)
        })

        for trial_dir in trial_dirs:
            trial = trial_dir.name
            fixed_speed_match = re.search(
                r"_(\d+)-(\d+)_(on|off)$",
                trial,
            )
            is_fixed_speed = (
                trial.startswith("normal_walk")
                and fixed_speed_match is not None
                and "shuffle" not in trial
                and "skip" not in trial
                and "hilo" not in trial
            )
            is_start_stop = (
                include_start_stop
                and trial.startswith("start_stop")
                and trial.endswith(("_on", "_off"))
            )

            if not (is_fixed_speed or is_start_stop):
                skipped.append({
                    "subject": subject,
                    "trial": trial,
                    "reason": "unsupported_normal_walk_variant",
                })
                continue

            prefix = f"{subject}_{trial}_"

            files = {
                name: trial_dir / f"{prefix}{suffix}"
                for name, suffix in FILE_SUFFIXES.items()
            }

            missing_files = [
                name
                for name, path in files.items()
                if not path.is_file()
            ]

            if missing_files:
                skipped.append({
                    "subject": subject,
                    "trial": trial,
                    "reason": f"missing_files:{missing_files}",
                })
                continue

            invalid_columns = {}

            for name, path in files.items():
                header = read_header(path)

                missing_columns = [
                    column
                    for column in REQUIRED_COLUMNS[name]
                    if column not in header
                ]

                if missing_columns:
                    invalid_columns[name] = missing_columns

            if invalid_columns:
                skipped.append({
                    "subject": subject,
                    "trial": trial,
                    "reason": f"missing_columns:{invalid_columns}",
                })
                continue

            if fixed_split is not None:
                split = fixed_split
            elif subject in test_subjects:
                split = "test"
            elif subject in validation_subjects:
                split = "validation"
            else:
                split = "train"

            nominal_speed = None

            if fixed_speed_match is not None:
                nominal_speed = float(
                    f"{fixed_speed_match.group(1)}."
                    f"{fixed_speed_match.group(2)}"
                )

            assist_condition = (
                "on" if trial.endswith("_on") else "off"
            )
            activity = (
                "fixed_speed_walk" if is_fixed_speed else "start_stop"
            )
            trials.append({
                "subject": subject,
                "trial": trial,
                # condition 保留给旧代码；assist_condition 是明确的新名称。
                "condition": assist_condition,
                "assist_condition": assist_condition,
                "activity": activity,
                "nominal_speed_m_s": nominal_speed,
                "transition_capable": is_start_stop,
                "split": split,
                "files": {
                    name: str(path.relative_to(dataset_root))
                    for name, path in files.items()
                },
            })

    subjects = sorted({
        trial["subject"]
        for trial in trials
    })

    requested_subjects = (
        include_subjects
        if include_subjects is not None
        else validation_subjects | test_subjects
    )
    unknown_requested_subjects = requested_subjects - set(subjects)

    if unknown_requested_subjects:
        raise ValueError(
            "Requested subjects have no usable trials: "
            f"{sorted(unknown_requested_subjects)}"
        )

    return {
        "dataset_root": str(dataset_root),
        "input_columns": list(INPUT_COLUMNS),
        "target_columns": {
            "angle": list(ANGLE_COLUMNS),
            "velocity": list(VELOCITY_COLUMNS),
            "moment": list(MOMENT_COLUMNS),
        },
        "subjects": subjects,
        "validation_subjects": (
            [] if fixed_split is not None else sorted(validation_subjects)
        ),
        "test_subjects": (
            [] if fixed_split is not None else sorted(test_subjects)
        ),
        "requested_subjects": (
            sorted(include_subjects) if include_subjects is not None else None
        ),
        "fixed_split": fixed_split,
        "variable_speed": include_start_stop,
        "trials": trials,
        "skipped": skipped,
        "summary": {
            "subjects": len(subjects),
            "train_trials": sum(
                trial["split"] == "train"
                for trial in trials
            ),
            "validation_trials": sum(
                trial["split"] == "validation"
                for trial in trials
            ),
            "test_trials": sum(
                trial["split"] == "test"
                for trial in trials
            ),
            "skipped_trials": len(skipped),
            "fixed_speed_trials": sum(
                trial["activity"] == "fixed_speed_walk"
                for trial in trials
            ),
            "start_stop_trials": sum(
                trial["activity"] == "start_stop"
                for trial in trials
            ),
        },
    }

def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--dataset-root",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=None,
    )
    parser.add_argument(
        "--validation-subjects",
        nargs="+",
        default=None,
    )
    parser.add_argument(
        "--include-subjects",
        nargs="+",
        default=None,
    )
    parser.add_argument(
        "--fixed-split",
        choices=("train", "validation", "test"),
        default=None,
    )
    parser.add_argument(
        "--test-subjects",
        nargs="+",
        default=None,
    )
    parser.add_argument(
        "--variable-speed",
        action="store_true",
        help=(
            "Include start_stop trials and use a separate variable-speed "
            "manifest by default."
        ),
    )

    arguments = parser.parse_args()

    if arguments.dataset_root is None:
        data_root = os.environ.get("GEXO_DATA_ROOT")

        if not data_root:
            raise RuntimeError(
                "Set GEXO_DATA_ROOT or pass --dataset-root."
            )

        dataset_root = (
            Path(data_root)
            / "Phase1And2_Parsed"
            / "Parsed"
        )
    else:
        dataset_root = arguments.dataset_root

    validation_subjects = set(
        arguments.validation_subjects
        or (
            ("BT11", "BT15", "BT16")
            if arguments.variable_speed
            else ("BT15", "BT16", "BT17")
        )
    )
    test_subjects = set(
        arguments.test_subjects
        or (("BT12", "BT17") if arguments.variable_speed else ())
    )

    manifest = scan_dataset(
        dataset_root,
        validation_subjects,
        include_subjects=(
            set(arguments.include_subjects)
            if arguments.include_subjects is not None
            else None
        ),
        fixed_split=arguments.fixed_split,
        test_subjects=test_subjects,
        include_start_stop=arguments.variable_speed,
    )

    output_path = (
        arguments.output
        or (
            DEFAULT_VARIABLE_SPEED_OUTPUT
            if arguments.variable_speed
            else DEFAULT_OUTPUT
        )
    ).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    with output_path.open(
        "w",
        encoding="utf-8",
    ) as file:
        json.dump(
            manifest,
            file,
            ensure_ascii=False,
            indent=2,
        )

    print(json.dumps(
        manifest["summary"],
        ensure_ascii=False,
        indent=2,
    ))
    print(f"manifest: {output_path}")


if __name__ == "__main__":
    main()
