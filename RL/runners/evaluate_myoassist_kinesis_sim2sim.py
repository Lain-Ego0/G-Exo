"""Audit a MyoAssist-trained G-Exo Actor on the Kinesis dynamic backend."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import sys
from typing import Any

import numpy as np

from RL.env.actor_observation import (
    ACTION_DIM,
    ACTOR_OBSERVATION_DIM,
    ACTOR_OBSERVATION_PROTOCOL,
    JOINT_ORDER,
    RESET_PROTOCOL,
)
from RL.runners.policy_load_compat import (
    load_ppo_for_inference,
    saved_space_shapes,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = (
    PROJECT_ROOT
    / "RL/outputs/myoassist_urdf_target_activation_scratch_1m"
    / "stage1_300k/best_model/best_model.zip"
)
DEFAULT_TCN = PROJECT_ROOT / "RL/outputs/tcn_runs/seed_43/best_model.pt"
DEFAULT_KINESIS_CALIBRATION = (
    PROJECT_ROOT / "RL/assets/tcn/kinesis_phase12_explicit_calibration.json"
)
DEFAULT_BASELINE = PROJECT_ROOT / "RL/outputs/kinesis_physical_baseline_v2"
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/outputs/sim2sim/myoassist_to_kinesis.json"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def find_source_protocol(model_path: Path) -> tuple[Path, dict[str, Any]]:
    directory = model_path.resolve().parent
    for _ in range(5):
        candidate = directory / "config.json"
        if candidate.is_file():
            value = json.loads(candidate.read_text(encoding="utf-8"))
            protocol = value.get("immutable_protocol")
            if isinstance(protocol, dict):
                return candidate, protocol
        directory = directory.parent
    raise FileNotFoundError(f"No immutable config.json found beside {model_path}.")


def validate_source_contract(
    model_path: Path,
    tcn_checkpoint: Path,
    target_calibration: Path,
    device: str,
) -> dict[str, Any]:
    """Reject observation, joint-order and actuator mismatches before MuJoCo."""

    config_path, protocol = find_source_protocol(model_path)
    observation = protocol.get("observation", {})
    action = protocol.get("action_and_safety", {})
    reset = protocol.get("reset", {})
    if protocol.get("backend") != "myoassist":
        raise ValueError("Source policy is not a MyoAssist policy.")
    if (
        observation.get("dimension") != ACTOR_OBSERVATION_DIM
        or observation.get("protocol") != ACTOR_OBSERVATION_PROTOCOL
    ):
        raise ValueError("Source policy does not use the shared 160-D protocol.")
    if (
        action.get("dimension") != ACTION_DIM
        or tuple(action.get("joint_order", ())) != JOINT_ORDER
    ):
        raise ValueError("Source four-joint action contract is incompatible.")
    if reset.get("protocol") != RESET_PROTOCOL:
        raise ValueError("Source reset/warmup protocol is incompatible.")

    expected_tcn_hash = protocol.get("artifacts", {}).get(
        "tcn_checkpoint", {}
    ).get("sha256")
    actual_tcn_hash = file_sha256(tcn_checkpoint)
    if expected_tcn_hash != actual_tcn_hash:
        raise ValueError("The target run is not using the source policy's frozen TCN.")
    calibration = json.loads(target_calibration.read_text(encoding="utf-8"))
    if not isinstance(calibration.get("actor_feature_normalization"), dict):
        raise ValueError("Kinesis calibration has no Actor feature normalization.")

    observation_shape, action_shape = saved_space_shapes(model_path)
    if observation_shape != (ACTOR_OBSERVATION_DIM,):
        raise ValueError("Saved policy observation shape is not (160,).")
    if action_shape != (ACTION_DIM,):
        raise ValueError("Saved policy action shape is not (4,).")
    # Loading here catches parameter or SB3 incompatibilities before Kinesis
    # creates its expensive MuJoCo agent.
    load_ppo_for_inference(model_path, device=device)

    hard_limits = np.asarray(action.get("hard_torque_limit_nm"), dtype=np.float64)
    rate_limits = np.asarray(action.get("torque_rate_limit_nm_s"), dtype=np.float64)
    if hard_limits.shape != (4,) or not np.allclose(hard_limits, hard_limits[0]):
        raise ValueError("Kinesis audit currently requires one shared torque limit.")
    if rate_limits.shape != (4,) or not np.allclose(rate_limits, rate_limits[0]):
        raise ValueError("Kinesis audit currently requires one shared torque-rate limit.")
    return {
        "source_config": str(config_path),
        "source_protocol_sha256": protocol.get("sha256"),
        "source_model_sha256": file_sha256(model_path),
        "tcn_checkpoint_sha256": actual_tcn_hash,
        "target_calibration_sha256": file_sha256(target_calibration),
        "observation_dimension": ACTOR_OBSERVATION_DIM,
        "action_dimension": ACTION_DIM,
        "joint_order": list(JOINT_ORDER),
        "action_scale_nm": float(action["action_scale_nm"]),
        "torque_limit_nm": float(hard_limits[0]),
        "torque_rate_limit_nm_s": float(rate_limits[0]),
        "warmup_steps": int(reset["warmup_steps"]),
    }


def build_transfer_audit(
    report: dict[str, Any],
    *,
    mpjpe_margin_mm: float,
    cuff_error_margin_mm: float = 5.0,
    action_saturation_limit: float = 0.05,
) -> dict[str, Any]:
    """Pair baseline and policy by motion/seed and apply target-domain gates."""

    by_key: dict[tuple[int, int], dict[str, dict[str, Any]]] = {}
    for row in report["rows"]:
        key = (int(row["motion_id"]), int(row["seed"]))
        by_key.setdefault(key, {})[str(row["mode"])] = row

    pairs = []
    for (motion_id, seed), modes in sorted(by_key.items()):
        if "baseline" not in modes or "policy" not in modes:
            continue
        baseline = modes["baseline"]
        policy = modes["policy"]
        delta_mpjpe = float(policy["mean_mpjpe_mm"] - baseline["mean_mpjpe_mm"])
        cuff_error_delta = float(
            policy["cuff_error_p95_mm"] - baseline["cuff_error_p95_mm"]
        )
        finite = bool(
            np.all(
                np.isfinite(
                    (
                        delta_mpjpe,
                        policy["mean_absolute_exo_torque_nm"],
                        policy["cuff_force_p95_n"],
                        policy["cuff_error_p95_mm"],
                    )
                )
            )
        )
        passed = bool(
            baseline["success"]
            and policy["success"]
            and finite
            and delta_mpjpe <= mpjpe_margin_mm
            and cuff_error_delta <= cuff_error_margin_mm
            and policy["action_saturation_ratio"] <= action_saturation_limit
        )
        pairs.append(
            {
                "motion_id": motion_id,
                "seed": seed,
                "baseline_success": bool(baseline["success"]),
                "policy_success": bool(policy["success"]),
                "baseline_mpjpe_mm": float(baseline["mean_mpjpe_mm"]),
                "policy_mpjpe_mm": float(policy["mean_mpjpe_mm"]),
                "mpjpe_delta_mm": delta_mpjpe,
                "mean_absolute_exo_torque_nm": float(
                    policy["mean_absolute_exo_torque_nm"]
                ),
                "action_saturation_ratio": float(
                    policy["action_saturation_ratio"]
                ),
                "cuff_force_p95_n": float(policy["cuff_force_p95_n"]),
                "baseline_cuff_error_p95_mm": float(
                    baseline["cuff_error_p95_mm"]
                ),
                "cuff_error_p95_mm": float(policy["cuff_error_p95_mm"]),
                "cuff_error_delta_mm": cuff_error_delta,
                "passed": passed,
            }
        )
    if not pairs:
        raise ValueError("The Kinesis report contains no paired baseline/policy rows.")
    return {
        "passed": bool(all(pair["passed"] for pair in pairs)),
        "pair_count": len(pairs),
        "pass_rate": float(np.mean([pair["passed"] for pair in pairs])),
        "mean_mpjpe_delta_mm": float(
            np.mean([pair["mpjpe_delta_mm"] for pair in pairs])
        ),
        "mpjpe_margin_mm": float(mpjpe_margin_mm),
        "cuff_error_margin_mm": float(cuff_error_margin_mm),
        "action_saturation_limit": float(action_saturation_limit),
        "pairs": pairs,
        "physiology_interpretation": (
            "Kinesis activation and muscle-torque changes are diagnostics only; "
            "the frozen target human controller can compensate for assistance."
        ),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--tcn-checkpoint", type=Path, default=DEFAULT_TCN)
    parser.add_argument(
        "--target-tcn-calibration",
        type=Path,
        default=DEFAULT_KINESIS_CALIBRATION,
    )
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--motion-ids", default="2,43,82")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--max-episode-steps", type=int, default=500)
    parser.add_argument("--mpjpe-margin-mm", type=float, default=15.0)
    parser.add_argument("--cuff-error-margin-mm", type=float, default=5.0)
    parser.add_argument("--device", choices=("cpu", "cuda", "auto"), default="cpu")
    parser.add_argument("--tcn-device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--contract-only", action="store_true")
    parser.add_argument(
        "--raw-report",
        type=Path,
        help="Re-audit an existing Kinesis raw report without rerunning MuJoCo.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model = args.model.expanduser().resolve(strict=True)
    tcn = args.tcn_checkpoint.expanduser().resolve(strict=True)
    calibration = args.target_tcn_calibration.expanduser().resolve(strict=True)
    baseline = args.baseline_dir.expanduser().resolve(strict=True)
    contract = validate_source_contract(model, tcn, calibration, args.device)
    print(json.dumps(contract, indent=2, ensure_ascii=False))
    if args.contract_only:
        return

    raw_output = (
        args.raw_report.expanduser().resolve(strict=True)
        if args.raw_report is not None
        else args.output.with_name(f"{args.output.stem}.kinesis_raw.json")
    )
    command = [
        sys.executable,
        "-m",
        "RL.runners.evaluate_kinesis_exo",
        "--motion-ids",
        args.motion_ids,
        "--modes",
        "baseline,policy",
        "--episodes",
        str(args.episodes),
        "--first-seed",
        str(args.first_seed),
        "--model",
        str(model),
        "--baseline-dir",
        str(baseline),
        "--action-scale-nm",
        str(contract["action_scale_nm"]),
        "--torque-limit-nm",
        str(contract["torque_limit_nm"]),
        "--torque-rate-limit-nm-s",
        str(contract["torque_rate_limit_nm_s"]),
        "--warmup-steps",
        str(contract["warmup_steps"]),
        "--max-episode-steps",
        str(args.max_episode_steps),
        "--use-tcn",
        "--tcn-checkpoint",
        str(tcn),
        "--tcn-calibration",
        str(calibration),
        "--tcn-device",
        args.tcn_device,
        "--device",
        args.device,
        "--output",
        str(raw_output),
    ]
    if args.raw_report is None:
        if args.render:
            command.append("--render")
        subprocess.run(command, check=True)
    report = json.loads(raw_output.read_text(encoding="utf-8"))
    result = {
        "schema": "gexo_myoassist_to_kinesis_sim2sim_v1",
        "source_contract": contract,
        "target_report": str(raw_output),
        "audit": build_transfer_audit(
            report,
            mpjpe_margin_mm=args.mpjpe_margin_mm,
            cuff_error_margin_mm=args.cuff_error_margin_mm,
        ),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(result, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print("sim2sim passed:", result["audit"]["passed"])
    print("report:", args.output)


if __name__ == "__main__":
    main()
