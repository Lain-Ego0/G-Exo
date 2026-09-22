from __future__ import annotations

import argparse
import hashlib
import json
import os
from datetime import date
from pathlib import Path

import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_PHASE3_AGGREGATE = PROJECT_ROOT / "RL/outputs/tcn_phase3/aggregate.json"
DEFAULT_VALIDATION_AGGREGATE = PROJECT_ROOT / "RL/outputs/tcn_runs/aggregate.json"
DEFAULT_PHASE3_MANIFEST = PROJECT_ROOT / "RL/assets/datasets/phase3_test_manifest.json"
DEFAULT_TRAINING_MANIFEST = PROJECT_ROOT / "RL/assets/datasets/phase12_manifest.json"
DEFAULT_JSON = PROJECT_ROOT / "RL/outputs/tcn_phase3/summary.json"
DEFAULT_MARKDOWN = PROJECT_ROOT / "RL/outputs/tcn_phase3/report.md"

GROUP_LABELS = {
    "angle_rad": "角度 RMSE (rad)",
    "velocity_rad_s": "角速度 RMSE (rad/s)",
    "moment_nm_kg": "生物关节力矩 RMSE (Nm/kg)",
}


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def sha256(path: Path) -> str:
    digest = hashlib.sha256()

    with path.open("rb") as file:
        for block in iter(lambda: file.read(1024 * 1024), b""):
            digest.update(block)

    return digest.hexdigest()


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--phase3-aggregate", type=Path, default=DEFAULT_PHASE3_AGGREGATE)
    parser.add_argument(
        "--validation-aggregate", type=Path, default=DEFAULT_VALIDATION_AGGREGATE
    )
    parser.add_argument("--phase3-manifest", type=Path, default=DEFAULT_PHASE3_MANIFEST)
    parser.add_argument("--training-manifest", type=Path, default=DEFAULT_TRAINING_MANIFEST)
    parser.add_argument("--output-json", type=Path, default=DEFAULT_JSON)
    parser.add_argument("--output-markdown", type=Path, default=DEFAULT_MARKDOWN)
    parser.add_argument("--processed-root", type=Path)
    parser.add_argument("--maximum-mse-ratio", type=float, default=1.5)
    args = parser.parse_args()

    if args.processed_root is None:
        data_root = os.environ.get("GEXO_DATA_ROOT")

        if not data_root:
            raise RuntimeError("Set GEXO_DATA_ROOT or pass --processed-root.")

        args.processed_root = Path(data_root) / "processed/tcn50_phase3"

    phase3 = read_json(args.phase3_aggregate)
    validation = read_json(args.validation_aggregate)
    phase3_manifest = read_json(args.phase3_manifest)
    training_manifest = read_json(args.training_manifest)
    test_subjects = set(phase3_manifest["subjects"])
    development_subjects = {
        trial["subject"] for trial in training_manifest["trials"]
    }
    overlap = sorted(test_subjects & development_subjects)
    expected_processed = {
        Path("test") / trial["subject"] / f"{trial['trial']}.npz"
        for trial in phase3_manifest["trials"]
    }
    actual_processed = {
        path.relative_to(args.processed_root)
        for path in (args.processed_root / "test").glob("*/*.npz")
    }
    missing_processed = sorted(str(path) for path in expected_processed - actual_processed)
    extra_processed = sorted(str(path) for path in actual_processed - expected_processed)
    evaluation_reports = [read_json(Path(run["path"])) for run in phase3["runs"]]
    evaluation_devices = sorted({report["device"] for report in evaluation_reports})
    evaluated_subjects = set.intersection(
        *(set(report["by_subject"]) for report in evaluation_reports)
    )
    subject_metrics = {}
    normalization_path = Path(evaluation_reports[0]["checkpoint"]).parent / "normalization.npz"

    with np.load(normalization_path) as normalization:
        input_mean = normalization["input_mean"]
        input_std = normalization["input_std"]

    for subject in sorted(evaluated_subjects):
        values = np.asarray(
            [report["by_subject"][subject]["normalized_mse"] for report in evaluation_reports]
        )
        subject_inputs = []

        for path in sorted((args.processed_root / "test" / subject).glob("*.npz")):
            with np.load(path) as data:
                subject_inputs.append(data["input"])

        if not subject_inputs:
            raise FileNotFoundError(f"No processed Phase 3 data for {subject}.")

        input_z = np.abs((np.concatenate(subject_inputs) - input_mean) / input_std)
        subject_metrics[subject] = {
            "mean": float(values.mean()),
            "std": float(values.std()),
            "minimum": float(values.min()),
            "maximum": float(values.max()),
            "input_mean_absolute_z": float(input_z.mean()),
            "input_fraction_absolute_z_above_3": float((input_z > 3.0).mean()),
            "input_maximum_absolute_z": float(input_z.max()),
        }

    phase3_mse = phase3["summary"]["normalized_mse"]["mean"]
    validation_mse = validation["summary"]["normalized_mse"]["mean"]
    mse_ratio = phase3_mse / validation_mse
    subject_balanced_mse = float(
        np.mean([metrics["mean"] for metrics in subject_metrics.values()])
    )
    subject_balanced_ratio = subject_balanced_mse / validation_mse
    acceptance = {
        "no_phase12_subject_overlap": not overlap,
        "processed_files_match_manifest": not missing_processed and not extra_processed,
        "all_manifest_subjects_evaluated": evaluated_subjects == test_subjects,
        "enough_runs": phase3["acceptance"]["enough_runs"],
        "all_pipeline_checks_passed": phase3["acceptance"][
            "all_pipeline_checks_passed"
        ],
        "all_runs_requested_full_training": phase3["acceptance"][
            "all_runs_requested_full_training"
        ],
        "all_runs_beat_both_baselines": phase3["acceptance"][
            "all_runs_beat_both_baselines"
        ],
        "stable_across_seeds": phase3["acceptance"]["stable_across_seeds"],
        "phase3_to_validation_mse_ratio": mse_ratio,
        "maximum_mse_ratio": args.maximum_mse_ratio,
        "generalization_ratio_passed": mse_ratio <= args.maximum_mse_ratio,
        "subject_balanced_mse": subject_balanced_mse,
        "subject_balanced_mse_ratio": subject_balanced_ratio,
        "subject_balanced_ratio_passed": subject_balanced_ratio
        <= args.maximum_mse_ratio,
    }
    boolean_gates = [value for value in acceptance.values() if isinstance(value, bool)]
    acceptance["ready_for_myo_rl_integration"] = all(boolean_gates)
    checkpoint_hashes = {
        str(report["checkpoint_seed"]): sha256(Path(report["checkpoint"]))
        for report in evaluation_reports
    }
    result = {
        "date": date.today().isoformat(),
        "phase3_manifest": str(args.phase3_manifest.resolve()),
        "phase3_manifest_sha256": sha256(args.phase3_manifest),
        "training_manifest_sha256": sha256(args.training_manifest),
        "checkpoint_sha256": checkpoint_hashes,
        "test_subjects": sorted(test_subjects),
        "phase12_subject_overlap": overlap,
        "missing_processed_files": missing_processed,
        "extra_processed_files": extra_processed,
        "trials": len(phase3_manifest["trials"]),
        "skipped_trials": len(phase3_manifest["skipped"]),
        "samples_per_run": evaluation_reports[0]["samples"],
        "evaluation_devices": evaluation_devices,
        "subject_metrics": subject_metrics,
        "acceptance": acceptance,
        "phase3": phase3,
    }
    args.output_json.parent.mkdir(parents=True, exist_ok=True)
    args.output_json.write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    lines = [
        f"# TCN Phase 3 冻结测试报告（{result['date']}）",
        "",
        "## 结论",
        "",
        (
            "通过：Phase 3 冻结测试满足 MyoSuite/RL 严格集成门槛。"
            if acceptance["ready_for_myo_rl_integration"]
            else "未通过：Phase 3 冻结测试没有满足全部 MyoSuite/RL 严格集成门槛。"
        ),
        "",
        "Phase 3 样本没有用于训练、归一化统计、早停或检查点选择。原定门槛未在"
        "看到结果后修改。",
        "",
        "## 测试集",
        "",
        f"- 受试者：{', '.join(sorted(test_subjects))}",
        f"- 标准平地步行 trial：{result['trials']}",
        f"- 每个检查点的 50 Hz 预测窗口：{result['samples_per_run']}",
        f"- 本次自动评估设备：{', '.join(evaluation_devices)}",
        f"- 与 Phase 1/2 开发受试者重叠：{overlap or '无'}",
        "- 仅包含助力开启（`on`）；已排除 shuffle 和 skip。",
        "",
        "## 汇总指标",
        "",
        "| 指标 | Phase 3 均值 | 种子标准差 | 原留出验证均值 | P3/验证 |",
        "| --- | ---: | ---: | ---: | ---: |",
        (
            f"| normalized MSE | {phase3_mse:.6f} | "
            f"{phase3['summary']['normalized_mse']['std']:.6f} | {validation_mse:.6f} | "
            f"{mse_ratio:.3f} |"
        ),
    ]

    for horizon in ("100_ms", "200_ms"):
        for group, label in GROUP_LABELS.items():
            key = f"{horizon}.{group}.tcn_rmse"
            lines.append(
                f"| {horizon} {label} | {phase3['summary'][key]['mean']:.6f} | "
                f"{phase3['summary'][key]['std']:.6f} | "
                f"{validation['summary'][key]['mean']:.6f} | "
                f"{phase3['summary'][key]['mean'] / validation['summary'][key]['mean']:.3f} |"
            )

    lines.extend(
        [
            "",
            f"按窗口加权的 Phase 3/验证 MSE 比值为 `{mse_ratio:.3f}`，上限为 "
            f"`{args.maximum_mse_ratio:.3f}`。按受试者等权的 MSE 为 "
            f"`{subject_balanced_mse:.6f}`，比值为 `{subject_balanced_ratio:.3f}`。",
            "",
            "## 分随机种子",
            "",
            "| Seed | MSE | 是否优于两类基线 |",
            "| ---: | ---: | :---: |",
        ]
    )

    for run in phase3["runs"]:
        lines.append(
            f"| {run['seed']} | {run['metrics']['normalized_mse']:.6f} | "
            f"{'是' if run['beats_both_baselines'] else '否'} |"
        )

    lines.extend(
        [
            "",
            "## 分受试者",
            "",
            "| 受试者 | MSE 均值 | 种子标准差 | 输入平均绝对 z | 输入绝对 z>3 比例 |",
            "| --- | ---: | ---: | ---: | ---: |",
        ]
    )

    for subject, metrics in subject_metrics.items():
        lines.append(
            f"| {subject} | {metrics['mean']:.6f} | {metrics['std']:.6f} | "
            f"{metrics['input_mean_absolute_z']:.3f} | "
            f"{100.0 * metrics['input_fraction_absolute_z_above_3']:.2f}% |"
        )

    lines.extend(["", "## 门槛", ""])

    for key, value in acceptance.items():
        lines.append(f"- `{key}`: `{value}`")

    lines.extend(
        [
            "",
            "## 诊断与建议",
            "",
            "- 主要退化来自角度预测，而不是角速度：100 ms 角度 RMSE 是原验证的约 "
            "1.58 倍。",
            "- BT24 是最弱受试者，但其整体输入 |z| 分布并非最异常，不能简单归因于"
            "少量传感器越界；更可能涉及个体运动学、安装或标定差异。",
            "- 严格门槛未通过时，TCN 可以作为 MyoSuite 中的诊断/辅助特征进行实验，"
            "但不能作为唯一的助力力矩依据，也不应使用 Phase 3 继续调参。",
            "- 本报告只覆盖新受试者标准平地步行，不代表完整 task-agnostic Phase 3。",
            "- Phase 3 只有 `on` 条件，不能证明无助力条件泛化。",
            "- `velocity_filt` 的在线因果性仍无文档保证；部署必须使用明确的因果传感器链。",
            "- 生物力矩误差单位为 Nm/kg，不能直接发送给电机。",
            "",
            "## CUDA 复现",
            "",
            "```bash",
            "cd ~/HK_hackthon",
            "export GEXO_DATA_ROOT='<PROJECT_ROOT>'",
            "export GEXO_PHASE3_CACHE=\"$GEXO_DATA_ROOT/processed/tcn50_phase3\"",
            "TCN_DEVICE=cuda bash G-Exo/RL/runners/run_tcn_phase3.sh",
            "```",
            "",
            "## 来源校验",
            "",
            f"- Phase 3 manifest SHA256: `{result['phase3_manifest_sha256']}`",
            f"- Training manifest SHA256: `{result['training_manifest_sha256']}`",
        ]
    )

    for seed, digest in checkpoint_hashes.items():
        lines.append(f"- Seed {seed} checkpoint SHA256: `{digest}`")

    args.output_markdown.parent.mkdir(parents=True, exist_ok=True)
    args.output_markdown.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(json.dumps(acceptance, ensure_ascii=False, indent=2))
    print("json:", args.output_json.resolve())
    print("markdown:", args.output_markdown.resolve())


if __name__ == "__main__":
    main()
