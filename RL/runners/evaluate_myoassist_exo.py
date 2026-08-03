"""Strict paired evaluation for the MyoAssist four-joint G-Exo route."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np
from stable_baselines3 import PPO

from RL.env.myoassist.baseline import MyoAssistBaseline
from RL.env.myoassist.gexo_leg_env import CONTROL_DT, GexoMyoAssistEnv
from RL.env.myoassist.policy_transfer import file_sha256
from RL.env.myoassist.sensor_adapter import JOINT_SPECS


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TCN = PROJECT_ROOT / "RL/outputs/tcn_runs/seed_43/best_model.pt"
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/outputs/myoassist_exo_evaluation.json"
CANONICAL_SPEEDS_M_S = (0.8, 1.0, 1.25)
CANONICAL_REFERENCE_INDICES = (0,)
SUPPORTED_MODES = ("baseline", "oracle", "policy")
TRACE_SCHEMA = "gexo_myoassist_paired_traces_v2"
REPORT_SCHEMA = "gexo_myoassist_paired_evaluation_v2"


def parse_csv(value: str, conversion) -> tuple:
    return tuple(conversion(item.strip()) for item in value.split(",") if item.strip())


def _finite_mean(values: list[float]) -> float | None:
    if not values:
        return None
    result = float(np.mean(values))
    return result if np.isfinite(result) else None


def _finite_min(values: list[float]) -> float | None:
    if not values:
        return None
    result = float(np.min(values))
    return result if np.isfinite(result) else None


def _finite_max_abs(values: list[float]) -> float | None:
    if not values:
        return None
    result = float(np.max(np.abs(values)))
    return result if np.isfinite(result) else None


def _oracle_action(
    snapshot,
    action_torque_scale_nm: np.ndarray,
    oracle_gain: float,
) -> np.ndarray:
    """Assist the net four-joint muscle torque at the current state."""

    force = snapshot.resolved_muscle_force_n()
    # Each row is one muscle's contribution to all four target joints.
    muscle_torque_nm = np.sum(snapshot.moment_arm_m * force[:, None], axis=0)
    return np.clip(
        oracle_gain * muscle_torque_nm / action_torque_scale_nm,
        -1.0,
        1.0,
    ).astype(np.float32)


def run_episode(
    *,
    mode: str,
    model: PPO | None,
    environment_options: dict[str, Any],
    seed: int,
    speed: float,
    reference_index: int,
    steps: int,
    render: bool,
    oracle_gain: float = 0.25,
) -> tuple[dict[str, object], dict[str, np.ndarray]]:
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported evaluation mode: {mode}.")
    if mode == "policy" and model is None:
        raise ValueError("Policy mode requires --model.")

    environment = GexoMyoAssistEnv(**environment_options)
    observation, _ = environment.reset(
        seed=seed,
        options={"target_speed": speed, "reference_index": reference_index},
    )
    rows: dict[str, list] = {
        "activation_cost": [],
        "human_torque_cost": [],
        "gross_cost": [],
        "applied_exo_torque_nm": [],
        "exo_joint_power_w": [],
        "forward_speed_m_s": [],
        "pelvis_height_m": [],
        "pelvis_pitch_rad": [],
        "joint_limit_excess": [],
    }
    total_return = 0.0
    reason = "evaluation_horizon"
    try:
        for step_index in range(steps):
            if mode == "baseline":
                action = np.zeros(4, dtype=np.float32)
            elif mode == "oracle":
                action = _oracle_action(
                    environment.muscle_adapter.snapshot(),
                    environment.action_torque_scale_nm,
                    oracle_gain,
                )
            else:
                action, _ = model.predict(observation, deterministic=True)

            observation, reward, terminated, truncated, info = environment.step(action)
            total_return += float(reward)
            rows["activation_cost"].append(float(info["reward/activation_cost"]))
            rows["human_torque_cost"].append(
                float(info["reward/human_torque_cost"])
            )
            rows["gross_cost"].append(float(info["reward/gross_cost"]))
            rows["applied_exo_torque_nm"].append(
                np.asarray(info["applied_exo_torque_nm"], dtype=np.float32)
            )
            rows["exo_joint_power_w"].append(
                np.asarray(info["exo_joint_power_w"], dtype=np.float32)
            )
            rows["forward_speed_m_s"].append(float(info["forward_speed_m_s"]))
            rows["pelvis_height_m"].append(float(info["pelvis_height_m"]))
            rows["pelvis_pitch_rad"].append(float(info["pelvis_pitch_rad"]))
            rows["joint_limit_excess"].append(float(info["joint_limit_excess"]))
            if render:
                environment.render()
            if terminated:
                reason = str(info.get("termination_reason", "terminated"))
                break
            if truncated:
                reason = (
                    "evaluation_horizon"
                    if step_index + 1 == steps
                    else "truncated"
                )
                break
    finally:
        environment.close()

    traces = {
        name: np.asarray(values, dtype=np.float32)
        for name, values in rows.items()
    }
    completed = int(traces["activation_cost"].shape[0])
    torque = traces["applied_exo_torque_nm"]
    power = traces["exo_joint_power_w"]
    summary: dict[str, object] = {
        "mode": mode,
        "seed": seed,
        "speed_m_s": speed,
        "reference_index": reference_index,
        "requested_steps": steps,
        "steps": completed,
        "success": completed == steps and reason == "evaluation_horizon",
        "reason": reason,
        "return": total_return,
        "activation_cost_integral": float(
            np.sum(traces["activation_cost"]) * CONTROL_DT
        ),
        "human_torque_cost_integral": float(
            np.sum(traces["human_torque_cost"]) * CONTROL_DT
        ),
        "gross_cost_integral": float(np.sum(traces["gross_cost"]) * CONTROL_DT),
        "mean_absolute_exo_torque_nm": (
            float(np.mean(np.abs(torque))) if torque.size else None
        ),
        "positive_exo_work_j": (
            float(np.sum(np.maximum(power, 0.0)) * CONTROL_DT)
            if power.size
            else None
        ),
        "negative_exo_work_j": (
            float(np.sum(np.minimum(power, 0.0)) * CONTROL_DT)
            if power.size
            else None
        ),
        "mean_forward_speed_m_s": _finite_mean(rows["forward_speed_m_s"]),
        "minimum_pelvis_height_m": _finite_min(rows["pelvis_height_m"]),
        "maximum_absolute_pelvis_pitch_rad": _finite_max_abs(
            rows["pelvis_pitch_rad"]
        ),
        "maximum_joint_limit_excess": (
            float(np.max(traces["joint_limit_excess"]))
            if traces["joint_limit_excess"].size
            else None
        ),
    }
    return summary, traces


def _saving(baseline_value: object, assisted_value: object) -> float:
    denominator = max(float(baseline_value), 1.0e-8)
    return (float(baseline_value) - float(assisted_value)) / denominator


def _run_protocol(
    run: dict[str, object],
    *,
    speed_tolerance_m_s: float,
    minimum_pelvis_height_m: float,
    maximum_pelvis_pitch_rad: float,
    maximum_joint_limit_excess: float,
) -> dict[str, bool]:
    speed = run["mean_forward_speed_m_s"]
    height = run["minimum_pelvis_height_m"]
    pitch = run["maximum_absolute_pelvis_pitch_rad"]
    joint_excess = run["maximum_joint_limit_excess"]
    checks = {
        "survival": bool(run["success"]),
        "speed": speed is not None
        and abs(float(speed) - float(run["speed_m_s"])) <= speed_tolerance_m_s,
        "pelvis_height": height is not None
        and float(height) >= minimum_pelvis_height_m,
        "pelvis_pitch": pitch is not None
        and float(pitch) <= maximum_pelvis_pitch_rad,
        "joint_limits": joint_excess is not None
        and float(joint_excess) <= maximum_joint_limit_excess,
    }
    checks["pass"] = all(checks.values())
    return checks


def finalize_pair(
    runs: dict[str, dict[str, object]],
    *,
    requested_modes: tuple[str, ...],
    requested_steps: int,
    protocol_thresholds: dict[str, float],
    nondegradation_tolerance: float,
    minimum_improvement: float,
    gross_degradation_tolerance: float,
) -> dict[str, object]:
    """Attach strict paired savings and explicit protocol/effectiveness checks."""

    horizons = [int(runs[mode]["steps"]) for mode in requested_modes]
    equal_horizon = len(set(horizons)) == 1
    complete_horizon = equal_horizon and horizons[0] == requested_steps
    all_completed = all(bool(runs[mode]["success"]) for mode in requested_modes)
    pair_valid = all_completed and complete_horizon

    run_protocol = {
        mode: _run_protocol(runs[mode], **protocol_thresholds)
        for mode in requested_modes
    }
    protocol_pass = pair_valid and all(
        bool(run_protocol[mode]["pass"]) for mode in requested_modes
    )
    pair: dict[str, object] = {
        **runs,
        "pair_valid": pair_valid,
        "equal_horizon": equal_horizon,
        "complete_horizon": complete_horizon,
        "protocol_by_mode": run_protocol,
        "protocol_pass": protocol_pass,
        "effectiveness_by_mode": {},
    }

    baseline = runs["baseline"]
    for mode in requested_modes:
        if mode == "baseline":
            continue
        values: dict[str, float | None] = {
            "activation_saving_fraction": None,
            "human_torque_saving_fraction": None,
            "gross_load_saving_fraction": None,
        }
        if pair_valid:
            values = {
                "activation_saving_fraction": _saving(
                    baseline["activation_cost_integral"],
                    runs[mode]["activation_cost_integral"],
                ),
                "human_torque_saving_fraction": _saving(
                    baseline["human_torque_cost_integral"],
                    runs[mode]["human_torque_cost_integral"],
                ),
                "gross_load_saving_fraction": _saving(
                    baseline["gross_cost_integral"],
                    runs[mode]["gross_cost_integral"],
                ),
            }
        for name, value in values.items():
            pair[f"{mode}_{name}"] = value

        if not pair_valid:
            effectiveness = {
                "activation_nondegradation": False,
                "human_torque_nondegradation": False,
                "at_least_one_improvement": False,
                "gross_within_tolerance": False,
                "pass": False,
                "excluded_reason": "incomplete_or_unequal_horizon",
            }
        else:
            activation = float(values["activation_saving_fraction"])
            human_torque = float(values["human_torque_saving_fraction"])
            gross = float(values["gross_load_saving_fraction"])
            effectiveness = {
                "activation_nondegradation": (
                    activation >= -nondegradation_tolerance
                ),
                "human_torque_nondegradation": (
                    human_torque >= -nondegradation_tolerance
                ),
                "at_least_one_improvement": (
                    max(activation, human_torque) > minimum_improvement
                ),
                "gross_within_tolerance": (
                    gross >= -gross_degradation_tolerance
                ),
            }
            effectiveness["pass"] = protocol_pass and all(
                effectiveness.values()
            )
            effectiveness["excluded_reason"] = None
        pair["effectiveness_by_mode"][mode] = effectiveness
    return pair


def _mean_valid(pairs: list[dict[str, object]], key: str) -> float | None:
    values = [float(row[key]) for row in pairs if row.get(key) is not None]
    return float(np.mean(values)) if values else None


def _artifact(path: Path) -> dict[str, str]:
    resolved = path.expanduser().resolve(strict=True)
    return {"path": str(resolved), "sha256": file_sha256(resolved)}


def _parse_modes(value: str) -> tuple[str, ...]:
    modes = parse_csv(value, str)
    if not modes or len(set(modes)) != len(modes):
        raise ValueError("--modes must contain unique evaluation modes.")
    unknown = set(modes) - set(SUPPORTED_MODES)
    if unknown:
        raise ValueError(f"Unsupported modes: {sorted(unknown)}.")
    if "baseline" not in modes:
        raise ValueError("Paired evaluation always requires baseline mode.")
    return modes


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--modes", default="baseline,oracle,policy")
    parser.add_argument("--model", type=Path)
    parser.add_argument("--human-checkpoint", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--tcn-checkpoint", type=Path, default=DEFAULT_TCN)
    parser.add_argument("--tcn-calibration", type=Path, required=True)
    parser.add_argument("--speeds", default="0.8,1.0,1.25")
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--reference-indices", default="0")
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--action-scale-nm", type=float, default=8.0)
    parser.add_argument("--oracle-gain", type=float, default=0.25)
    parser.add_argument("--nondegradation-tolerance", type=float, default=0.0)
    parser.add_argument("--minimum-improvement", type=float, default=0.0)
    parser.add_argument("--gross-degradation-tolerance", type=float, default=0.1)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--trace-output", type=Path)
    parser.add_argument(
        "--require-pass",
        action="store_true",
        help="Fail only on protocol/safety errors; suitable for PPO smoke tests.",
    )
    parser.add_argument(
        "--require-effective",
        action="store_true",
        help="Also require paired physiological improvement.",
    )
    args = parser.parse_args()

    modes = _parse_modes(args.modes)
    speeds = parse_csv(args.speeds, float)
    seeds = parse_csv(args.seeds, int)
    reference_indices = parse_csv(args.reference_indices, int)
    if reference_indices != CANONICAL_REFERENCE_INDICES:
        raise ValueError(
            "Formal MyoAssist evaluation requires reference index 0 only; "
            "nonzero indices do not have phase-consistent muscle state."
        )
    if not speeds or len(set(speeds)) != len(speeds) or not np.all(np.isfinite(speeds)):
        raise ValueError("--speeds must contain unique finite values.")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("--seeds must contain unique values.")
    if args.steps <= 0:
        raise ValueError("--steps must be positive.")
    for name in (
        "nondegradation_tolerance",
        "minimum_improvement",
        "gross_degradation_tolerance",
    ):
        if getattr(args, name) < 0.0:
            raise ValueError(f"--{name.replace('_', '-')} must be non-negative.")

    baseline_path = args.baseline.expanduser().resolve(strict=True)
    baseline_artifact = MyoAssistBaseline.load(baseline_path)
    if min(speeds) < baseline_artifact.speeds_m_s[0] or max(speeds) > baseline_artifact.speeds_m_s[-1]:
        raise ValueError("Evaluation speeds must stay inside the baseline range.")
    model_path = args.model.expanduser().resolve(strict=True) if args.model else None
    if "policy" in modes and model_path is None:
        raise ValueError("--model is required when policy mode is requested.")
    model = PPO.load(model_path, device=args.device) if model_path is not None else None

    human_checkpoint = args.human_checkpoint.expanduser().resolve(strict=True)
    tcn_checkpoint = args.tcn_checkpoint.expanduser().resolve(strict=True)
    tcn_calibration = args.tcn_calibration.expanduser().resolve(strict=True)
    protocol_thresholds = {
        "minimum_pelvis_height_m": float(
            baseline_artifact.minimum_pelvis_height_m
            - baseline_artifact.pelvis_height_transition_m
        ),
        "maximum_pelvis_pitch_rad": float(
            baseline_artifact.pelvis_pitch_free_rad
            + baseline_artifact.pelvis_pitch_transition_rad
        ),
        "maximum_joint_limit_excess": 1.0,
    }
    environment_options = {
        "human_checkpoint": str(human_checkpoint),
        "baseline_path": str(baseline_path),
        "tcn_checkpoint": str(tcn_checkpoint),
        "tcn_calibration": str(tcn_calibration),
        "max_episode_steps": args.steps,
        "min_speed_m_s": min(speeds),
        "max_speed_m_s": max(speeds),
        "action_torque_scale_nm": args.action_scale_nm,
        "human_device": "cpu",
        "tcn_device": "cpu",
        "render_mode": "human" if args.render else None,
    }
    pairs: list[dict[str, object]] = []
    trace_arrays: dict[str, np.ndarray] = {
        "schema": np.asarray(TRACE_SCHEMA),
        "control_dt_s": np.asarray(CONTROL_DT, dtype=np.float64),
    }
    render_mode = "policy" if "policy" in modes else modes[-1]
    for speed in speeds:
        speed_reference = baseline_artifact.at_speed(speed)
        pair_protocol_thresholds = {
            **protocol_thresholds,
            "speed_tolerance_m_s": float(
                speed_reference.speed_free_error_m_s
                + speed_reference.speed_transition_m_s
            ),
        }
        for seed in seeds:
            for reference_index in reference_indices:
                pair_index = len(pairs)
                runs: dict[str, dict[str, object]] = {}
                for mode in modes:
                    summary, traces = run_episode(
                        mode=mode,
                        model=model if mode == "policy" else None,
                        environment_options=environment_options,
                        seed=seed,
                        speed=speed,
                        reference_index=reference_index,
                        steps=args.steps,
                        render=args.render and mode == render_mode,
                        oracle_gain=args.oracle_gain,
                    )
                    runs[mode] = summary
                    for trace_name, values in traces.items():
                        trace_arrays[
                            f"pair_{pair_index:04d}_{mode}_{trace_name}"
                        ] = values
                pairs.append(
                    finalize_pair(
                        runs,
                        requested_modes=modes,
                        requested_steps=args.steps,
                        protocol_thresholds=pair_protocol_thresholds,
                        nondegradation_tolerance=args.nondegradation_tolerance,
                        minimum_improvement=args.minimum_improvement,
                        gross_degradation_tolerance=(
                            args.gross_degradation_tolerance
                        ),
                    )
                )

    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    trace_output = (
        args.trace_output.expanduser().resolve()
        if args.trace_output is not None
        else output.with_suffix(".npz")
    )
    trace_output.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(trace_output, **trace_arrays)

    assistance_modes = tuple(mode for mode in modes if mode != "baseline")
    effectiveness_by_mode: dict[str, object] = {}
    for mode in assistance_modes:
        mode_checks = [
            bool(row["effectiveness_by_mode"][mode]["pass"])
            for row in pairs
        ]
        effectiveness_by_mode[mode] = {
            "pass": bool(mode_checks) and all(mode_checks),
            "valid_pair_count": sum(
                row[f"{mode}_activation_saving_fraction"] is not None
                for row in pairs
            ),
            "mean_activation_saving_fraction": _mean_valid(
                pairs, f"{mode}_activation_saving_fraction"
            ),
            "mean_human_torque_saving_fraction": _mean_valid(
                pairs, f"{mode}_human_torque_saving_fraction"
            ),
            "mean_gross_load_saving_fraction": _mean_valid(
                pairs, f"{mode}_gross_load_saving_fraction"
            ),
        }
    effectiveness_target = (
        "policy" if "policy" in assistance_modes else (
            assistance_modes[0] if assistance_modes else None
        )
    )
    protocol_pass = bool(pairs) and all(bool(row["protocol_pass"]) for row in pairs)
    effectiveness_pass = (
        None
        if effectiveness_target is None
        else bool(effectiveness_by_mode[effectiveness_target]["pass"])
    )
    artifact_metadata = {
        "human_checkpoint": _artifact(human_checkpoint),
        "baseline": _artifact(baseline_path),
        "tcn_checkpoint": _artifact(tcn_checkpoint),
        "tcn_calibration": _artifact(tcn_calibration),
        "policy_model": _artifact(model_path) if model_path is not None else None,
        "physical_model_sha256": baseline_artifact.metadata.get("model_sha256"),
        "trace_npz": _artifact(trace_output),
    }
    report = {
        "schema": REPORT_SCHEMA,
        "protocol": {
            "modes": list(modes),
            "speeds_m_s": list(speeds),
            "seeds": list(seeds),
            "reference_indices": list(reference_indices),
            "steps": args.steps,
            "control_dt_s": CONTROL_DT,
            "joint_order": [spec.name for spec in JOINT_SPECS],
            "action_scale_nm": args.action_scale_nm,
            "oracle_gain": args.oracle_gain,
            "thresholds": {
                **protocol_thresholds,
                "speed_tolerance_m_s_by_speed": {
                    str(speed): float(
                        baseline_artifact.at_speed(speed).speed_free_error_m_s
                        + baseline_artifact.at_speed(speed).speed_transition_m_s
                    )
                    for speed in speeds
                },
            },
            "effectiveness_criteria": {
                "nondegradation_tolerance": args.nondegradation_tolerance,
                "minimum_improvement": args.minimum_improvement,
                "gross_degradation_tolerance": (
                    args.gross_degradation_tolerance
                ),
            },
            "urdf_enabled": False,
            "domain_randomization_enabled": False,
        },
        "artifacts": artifact_metadata,
        "pairs": pairs,
        "pair_count": len(pairs),
        "valid_pair_count": sum(bool(row["pair_valid"]) for row in pairs),
        "protocol_pass": protocol_pass,
        "effectiveness_target": effectiveness_target,
        "effectiveness_pass": effectiveness_pass,
        "effectiveness_by_mode": effectiveness_by_mode,
    }
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"valid pairs: {report['valid_pair_count']}/{report['pair_count']}")
    print(f"protocol pass: {report['protocol_pass']}")
    print(f"effectiveness pass ({effectiveness_target}): {effectiveness_pass}")
    for mode in assistance_modes:
        summary = effectiveness_by_mode[mode]
        print(
            f"{mode}: activation={summary['mean_activation_saving_fraction']} "
            f"human_torque={summary['mean_human_torque_saving_fraction']} "
            f"gross={summary['mean_gross_load_saving_fraction']}"
        )
    print(f"report: {output}")
    print(f"traces: {trace_output}")
    if args.require_pass and not protocol_pass:
        raise SystemExit(1)
    if args.require_effective and effectiveness_pass is not True:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
