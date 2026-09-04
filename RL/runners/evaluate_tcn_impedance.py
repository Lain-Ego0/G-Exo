"""Paired MyoAssist evaluation for TCN trajectory impedance control."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from RL.controllers.delayed_prediction_audit import DelayedPredictionAudit
from RL.controllers.tcn_impedance import TCNImpedanceController
from RL.env.myoassist.baseline import MyoAssistBaseline
from RL.env.myoassist.gexo_leg_env import CONTROL_DT
from RL.env.myoassist.policy_transfer import file_sha256
from RL.env.myoassist.sensor_adapter import JOINT_SPECS
from RL.runners.evaluate_myoassist_exo import finalize_pair, run_episode


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_HUMAN = (
    PROJECT_ROOT
    / "RL/outputs/myoassist_human_adaptation_low_speed_100k"
    / "adapted_human_final.zip"
)
DEFAULT_BASELINE = (
    PROJECT_ROOT
    / "RL/assets/myoassist/zero_assist_baseline_preroll150.json"
)
DEFAULT_TCN = PROJECT_ROOT / "RL/outputs/tcn_runs/seed_43/best_model.pt"
DEFAULT_CALIBRATION = (
    PROJECT_ROOT
    / "RL/assets/tcn/myoassist_phase12_calibration_preroll150.json"
)
DEFAULT_OUTPUT = (
    PROJECT_ROOT / "RL/outputs/tcn_impedance/evaluation.json"
)
CANONICAL_REFERENCE_INDICES = (0,)
MODES = ("baseline", "tcn_pd")
TRACE_SCHEMA = "gexo_tcn_impedance_traces_v1"
REPORT_SCHEMA = "gexo_tcn_impedance_evaluation_v1"


class TCNImpedancePolicy:
    """Adapt the controller to the Stable-Baselines ``predict`` protocol."""

    def __init__(self, controller: TCNImpedanceController) -> None:
        self.controller = controller
        self.reset()

    def reset(self) -> None:
        self.prediction_audit = DelayedPredictionAudit(
            self.controller.selected_horizon_steps
        )
        self.rows: dict[str, list[Any]] = {
            "controller_action": [],
            "controller_target_torque_nm": [],
            "controller_delta_q_rad": [],
            "controller_delta_dq_rad_s": [],
            "controller_control_delta_q_rad": [],
            "controller_control_delta_dq_rad_s": [],
            "controller_reference_q_rad": [],
            "controller_reference_dq_rad_s": [],
            "controller_confidence": [],
            "controller_feature_ood_ratio": [],
            "controller_sensor_ood_ratio": [],
            "controller_feature_saturated": [],
            "controller_sensor_saturated": [],
            "controller_error_limited": [],
            "controller_action_saturated": [],
            "tcn_q_error_rad": [],
            "tcn_dq_error_rad_s": [],
        }

    def predict(
        self,
        observation: np.ndarray,
        deterministic: bool = True,
    ) -> tuple[np.ndarray, None]:
        del deterministic
        command = self.controller.compute(observation)
        q_error, dq_error = self.prediction_audit.update(
            current_q=command.current_q_rad,
            current_dq=command.current_dq_rad_s,
            predicted_q=command.predicted_q_rad,
            predicted_dq=command.predicted_dq_rad_s,
            prediction_valid=not command.feature_saturated,
        )
        self.rows["controller_action"].append(command.action.copy())
        self.rows["controller_target_torque_nm"].append(
            command.target_torque_nm.copy()
        )
        self.rows["controller_delta_q_rad"].append(
            command.delta_q_rad.copy()
        )
        self.rows["controller_delta_dq_rad_s"].append(
            command.delta_dq_rad_s.copy()
        )
        self.rows["controller_control_delta_q_rad"].append(
            command.control_delta_q_rad.copy()
        )
        self.rows["controller_control_delta_dq_rad_s"].append(
            command.control_delta_dq_rad_s.copy()
        )
        self.rows["controller_reference_q_rad"].append(
            command.reference_q_rad.copy()
        )
        self.rows["controller_reference_dq_rad_s"].append(
            command.reference_dq_rad_s.copy()
        )
        self.rows["controller_confidence"].append(command.confidence)
        self.rows["controller_feature_ood_ratio"].append(
            command.feature_ood_ratio
        )
        self.rows["controller_sensor_ood_ratio"].append(
            command.sensor_ood_ratio
        )
        self.rows["controller_feature_saturated"].append(
            command.feature_saturated
        )
        self.rows["controller_sensor_saturated"].append(
            command.sensor_saturated
        )
        self.rows["controller_error_limited"].append(command.error_limited)
        self.rows["controller_action_saturated"].append(
            command.action_saturated
        )
        self.rows["tcn_q_error_rad"].append(q_error)
        self.rows["tcn_dq_error_rad_s"].append(dq_error)
        return command.action.copy(), None

    def traces(self) -> dict[str, np.ndarray]:
        return {
            name: np.asarray(values)
            for name, values in self.rows.items()
        }

    def summary(self) -> dict[str, float | None]:
        traces = self.traces()
        target_torque = traces["controller_target_torque_nm"]
        q_error = traces["tcn_q_error_rad"]
        dq_error = traces["tcn_dq_error_rad_s"]
        return {
            "mean_absolute_target_torque_nm": _mean_absolute(target_torque),
            "controller_confidence_mean": _finite_mean(
                traces["controller_confidence"]
            ),
            "feature_ood_ratio_max": _finite_max(
                traces["controller_feature_ood_ratio"]
            ),
            "sensor_ood_ratio_max": _finite_max(
                traces["controller_sensor_ood_ratio"]
            ),
            "feature_saturation_ratio": _finite_mean(
                traces["controller_feature_saturated"]
            ),
            "sensor_saturation_ratio": _finite_mean(
                traces["controller_sensor_saturated"]
            ),
            "error_limit_ratio": _finite_mean(
                traces["controller_error_limited"]
            ),
            "action_saturation_ratio": _finite_mean(
                traces["controller_action_saturated"]
            ),
            "closed_loop_tcn_q_rmse_rad": _finite_rmse(q_error),
            "closed_loop_tcn_dq_rmse_rad_s": _finite_rmse(dq_error),
        }


def parse_csv(value: str, conversion) -> tuple:
    return tuple(
        conversion(item.strip())
        for item in value.split(",")
        if item.strip()
    )


def parse_joint_values(value: str, name: str) -> np.ndarray:
    values = parse_csv(value, float)
    if len(values) == 1:
        values = values * 4
    array = np.asarray(values, dtype=np.float32)
    if array.shape != (4,) or not np.all(np.isfinite(array)):
        raise ValueError(f"--{name} requires one or four finite values.")
    if np.any(array < 0.0):
        raise ValueError(f"--{name} must be non-negative.")
    return array


def artifact(path: Path) -> dict[str, str]:
    resolved = path.expanduser().resolve(strict=True)
    return {"path": str(resolved), "sha256": file_sha256(resolved)}


def _finite_mean(values: np.ndarray) -> float | None:
    array = np.asarray(values, dtype=np.float64)
    finite = array[np.isfinite(array)]
    return float(np.mean(finite)) if finite.size else None


def _finite_rmse(values: np.ndarray) -> float | None:
    array = np.asarray(values, dtype=np.float64)
    finite = array[np.isfinite(array)]
    return float(np.sqrt(np.mean(np.square(finite)))) if finite.size else None


def _finite_max(values: np.ndarray) -> float | None:
    array = np.asarray(values, dtype=np.float64)
    finite = array[np.isfinite(array)]
    return float(np.max(finite)) if finite.size else None


def _mean_absolute(values: np.ndarray) -> float | None:
    array = np.asarray(values, dtype=np.float64)
    finite = array[np.isfinite(array)]
    return float(np.mean(np.abs(finite))) if finite.size else None


def _mean_pair_value(
    pairs: list[dict[str, object]],
    key: str,
) -> float | None:
    values = [float(pair[key]) for pair in pairs if pair.get(key) is not None]
    return float(np.mean(values)) if values else None


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--human-checkpoint", type=Path, default=DEFAULT_HUMAN)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--tcn-checkpoint", type=Path, default=DEFAULT_TCN)
    parser.add_argument(
        "--tcn-calibration",
        type=Path,
        default=DEFAULT_CALIBRATION,
    )
    parser.add_argument("--speeds", default="0.8,1.0,1.25")
    parser.add_argument("--seeds", default="0")
    parser.add_argument("--reference-indices", default="0")
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--kp", default="4.0")
    parser.add_argument("--kd", default="0.2")
    parser.add_argument("--horizon-steps", type=int, choices=(5, 10), default=5)
    parser.add_argument("--prediction-fraction", type=float)
    parser.add_argument("--action-scale-nm", type=float, default=2.0)
    parser.add_argument("--ood-soft-ratio", type=float, default=0.6)
    parser.add_argument("--prediction-position-delta-limit-rad", default="1.0")
    parser.add_argument("--prediction-velocity-delta-limit-rad-s", default="10.0")
    parser.add_argument("--nondegradation-tolerance", type=float, default=0.0)
    parser.add_argument(
        "--minimum-improvement",
        type=float,
        default=0.01,
        help="Required improvement in activation or human torque (default 1%%).",
    )
    parser.add_argument("--gross-degradation-tolerance", type=float, default=0.1)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--trace-output", type=Path)
    parser.add_argument("--require-pass", action="store_true")
    parser.add_argument("--require-effective", action="store_true")
    args = parser.parse_args()

    speeds = parse_csv(args.speeds, float)
    seeds = parse_csv(args.seeds, int)
    reference_indices = parse_csv(args.reference_indices, int)
    kp = parse_joint_values(args.kp, "kp")
    kd = parse_joint_values(args.kd, "kd")
    position_delta_limit = parse_joint_values(
        args.prediction_position_delta_limit_rad,
        "prediction-position-delta-limit-rad",
    )
    velocity_delta_limit = parse_joint_values(
        args.prediction_velocity_delta_limit_rad_s,
        "prediction-velocity-delta-limit-rad-s",
    )
    if not speeds or len(set(speeds)) != len(speeds):
        raise ValueError("--speeds must contain unique values.")
    if not np.all(np.isfinite(speeds)):
        raise ValueError("--speeds must be finite.")
    if not seeds or len(set(seeds)) != len(seeds):
        raise ValueError("--seeds must contain unique values.")
    if reference_indices != CANONICAL_REFERENCE_INDICES:
        raise ValueError("Formal evaluation requires reference index 0.")
    if args.steps <= 0:
        raise ValueError("--steps must be positive.")
    if not np.isfinite(args.action_scale_nm) or args.action_scale_nm <= 0.0:
        raise ValueError("--action-scale-nm must be positive and finite.")
    if not np.isfinite(args.ood_soft_ratio) or not (
        0.0 <= args.ood_soft_ratio < 1.0
    ):
        raise ValueError("--ood-soft-ratio must be in [0, 1).")
    for name in (
        "nondegradation_tolerance",
        "minimum_improvement",
        "gross_degradation_tolerance",
    ):
        value = getattr(args, name)
        if not np.isfinite(value) or value < 0.0:
            raise ValueError(f"--{name.replace('_', '-')} must be non-negative.")

    human_checkpoint = args.human_checkpoint.expanduser().resolve(strict=True)
    baseline_path = args.baseline.expanduser().resolve(strict=True)
    tcn_checkpoint = args.tcn_checkpoint.expanduser().resolve(strict=True)
    tcn_calibration = args.tcn_calibration.expanduser().resolve(strict=True)
    baseline = MyoAssistBaseline.load(baseline_path)
    if min(speeds) < baseline.speeds_m_s[0] or max(speeds) > baseline.speeds_m_s[-1]:
        raise ValueError("Evaluation speeds exceed the calibrated baseline range.")

    controller = TCNImpedanceController.from_calibration(
        tcn_calibration,
        selected_horizon_steps=args.horizon_steps,
        kp_nm_per_rad=kp,
        kd_nm_s_per_rad=kd,
        action_scale_nm=args.action_scale_nm,
        prediction_fraction=args.prediction_fraction,
        ood_soft_ratio=args.ood_soft_ratio,
        position_delta_limit_rad=position_delta_limit,
        velocity_delta_limit_rad_s=velocity_delta_limit,
        expected_tcn_checkpoint_sha256=file_sha256(tcn_checkpoint),
    )
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
        "tcn_device": args.device,
        "render_mode": "human" if args.render else None,
    }
    fixed_protocol_thresholds = {
        "minimum_pelvis_height_m": float(
            baseline.minimum_pelvis_height_m
            - baseline.pelvis_height_transition_m
        ),
        "maximum_pelvis_pitch_rad": float(
            baseline.pelvis_pitch_free_rad
            + baseline.pelvis_pitch_transition_rad
        ),
        "maximum_joint_limit_excess": 1.0,
    }
    pairs: list[dict[str, object]] = []
    trace_arrays: dict[str, np.ndarray] = {
        "schema": np.asarray(TRACE_SCHEMA),
        "control_dt_s": np.asarray(CONTROL_DT, dtype=np.float64),
    }

    for speed in speeds:
        speed_reference = baseline.at_speed(speed)
        protocol_thresholds = {
            **fixed_protocol_thresholds,
            "speed_tolerance_m_s": float(
                speed_reference.speed_free_error_m_s
                + speed_reference.speed_transition_m_s
            ),
        }
        for seed in seeds:
            for reference_index in reference_indices:
                pair_index = len(pairs)
                baseline_summary, baseline_traces = run_episode(
                    mode="baseline",
                    model=None,
                    environment_options=environment_options,
                    seed=seed,
                    speed=speed,
                    reference_index=reference_index,
                    steps=args.steps,
                    render=False,
                )
                policy = TCNImpedancePolicy(controller)
                assisted_summary, assisted_traces = run_episode(
                    mode="policy",
                    model=policy,
                    environment_options=environment_options,
                    seed=seed,
                    speed=speed,
                    reference_index=reference_index,
                    steps=args.steps,
                    render=args.render,
                )
                assisted_summary["mode"] = "tcn_pd"
                assisted_summary.update(policy.summary())
                assisted_traces.update(policy.traces())
                runs = {
                    "baseline": baseline_summary,
                    "tcn_pd": assisted_summary,
                }
                pair = finalize_pair(
                    runs,
                    requested_modes=MODES,
                    requested_steps=args.steps,
                    protocol_thresholds=protocol_thresholds,
                    nondegradation_tolerance=args.nondegradation_tolerance,
                    minimum_improvement=args.minimum_improvement,
                    gross_degradation_tolerance=(
                        args.gross_degradation_tolerance
                    ),
                )
                pairs.append(pair)
                for mode, traces in (
                    ("baseline", baseline_traces),
                    ("tcn_pd", assisted_traces),
                ):
                    for name, values in traces.items():
                        trace_arrays[
                            f"pair_{pair_index:04d}_{mode}_{name}"
                        ] = np.asarray(values)
                print(
                    f"speed={speed:.2f} seed={seed:03d} "
                    f"activation={pair['tcn_pd_activation_saving_fraction']} "
                    f"human_torque={pair['tcn_pd_human_torque_saving_fraction']} "
                    f"gross={pair['tcn_pd_gross_load_saving_fraction']} "
                    f"q_rmse={assisted_summary['closed_loop_tcn_q_rmse_rad']}"
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

    protocol_pass = bool(pairs) and all(
        bool(pair["protocol_pass"]) for pair in pairs
    )
    effectiveness_checks = [
        bool(pair["effectiveness_by_mode"]["tcn_pd"]["pass"])
        for pair in pairs
    ]
    effectiveness_pass = bool(effectiveness_checks) and all(
        effectiveness_checks
    )
    summary = {
        "mean_activation_saving_fraction": _mean_pair_value(
            pairs,
            "tcn_pd_activation_saving_fraction",
        ),
        "mean_human_torque_saving_fraction": _mean_pair_value(
            pairs,
            "tcn_pd_human_torque_saving_fraction",
        ),
        "mean_gross_load_saving_fraction": _mean_pair_value(
            pairs,
            "tcn_pd_gross_load_saving_fraction",
        ),
        "mean_closed_loop_tcn_q_rmse_rad": _finite_mean(
            np.asarray(
                [pair["tcn_pd"]["closed_loop_tcn_q_rmse_rad"] for pair in pairs]
            )
        ),
        "mean_closed_loop_tcn_dq_rmse_rad_s": _finite_mean(
            np.asarray(
                [
                    pair["tcn_pd"]["closed_loop_tcn_dq_rmse_rad_s"]
                    for pair in pairs
                ]
            )
        ),
    }
    report = {
        "schema": REPORT_SCHEMA,
        "protocol": {
            "modes": list(MODES),
            "speeds_m_s": list(speeds),
            "seeds": list(seeds),
            "reference_indices": list(reference_indices),
            "steps": args.steps,
            "control_dt_s": CONTROL_DT,
            "joint_order": [spec.name for spec in JOINT_SPECS],
            "controller": controller.metadata(),
            "urdf_enabled": False,
            "domain_randomization_enabled": False,
            "effectiveness_criteria": {
                "nondegradation_tolerance": args.nondegradation_tolerance,
                "minimum_improvement": args.minimum_improvement,
                "gross_degradation_tolerance": (
                    args.gross_degradation_tolerance
                ),
            },
        },
        "artifacts": {
            "human_checkpoint": artifact(human_checkpoint),
            "baseline": artifact(baseline_path),
            "tcn_checkpoint": artifact(tcn_checkpoint),
            "tcn_calibration": artifact(tcn_calibration),
            "trace_npz": artifact(trace_output),
        },
        "pairs": pairs,
        "pair_count": len(pairs),
        "independent_condition_count": len(speeds) * len(reference_indices),
        "seed_repetitions_are_independent": False,
        "valid_pair_count": sum(bool(pair["pair_valid"]) for pair in pairs),
        "protocol_pass": protocol_pass,
        "effectiveness_pass": effectiveness_pass,
        "summary": summary,
    }
    output.write_text(
        json.dumps(report, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"valid pairs: {report['valid_pair_count']}/{report['pair_count']}")
    print(f"protocol pass: {protocol_pass}")
    print(f"effectiveness pass: {effectiveness_pass}")
    print(f"summary: {json.dumps(summary, sort_keys=True)}")
    print(f"report: {output}")
    print(f"traces: {trace_output}")
    if args.require_pass and not protocol_pass:
        raise SystemExit(1)
    if args.require_effective and not effectiveness_pass:
        raise SystemExit(2)


if __name__ == "__main__":
    main()
