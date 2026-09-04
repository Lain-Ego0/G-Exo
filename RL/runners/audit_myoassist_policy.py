"""Audit whether a MyoAssist assist policy uses TCN and torque timing."""

from __future__ import annotations

import argparse
from collections import deque
import json
from pathlib import Path
from typing import Any

import numpy as np
from stable_baselines3 import PPO

from RL.env.actor_observation import TCN_FEATURE_DIM
from RL.env.myoassist.baseline import MyoAssistBaseline
from RL.env.myoassist.gexo_leg_env import GexoMyoAssistEnv
from RL.env.myoassist.model_builder import (
    DEFAULT_PHYSICAL_OUTPUT_PATH,
    DEFAULT_URDF_DYNAMIC_OUTPUT_PATH,
)
from RL.env.myoassist.policy_transfer import FrozenHumanPolicy, file_sha256
from RL.runners.evaluate_myoassist_exo import (
    CONTROL_DT,
    _empty_rows,
    _joint_limit_excess,
    _summarize,
    attach_pairwise_movement,
    finalize_pair,
    parse_csv,
    run_naked_episode,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = (
    PROJECT_ROOT
    / "RL/outputs/myoassist_urdf_target_activation_scratch_1m"
    / "curriculum_s2_085_115_250k/best_model/best_model.zip"
)
DEFAULT_HUMAN = (
    PROJECT_ROOT
    / "RL/outputs/myoassist_human_joint_physics_imitation_100k"
    / "adapted_human_final.zip"
)
DEFAULT_BASELINE = PROJECT_ROOT / "RL/assets/myoassist/zero_assist_naked_v6.json"
DEFAULT_MOTION = (
    PROJECT_ROOT
    / "RL/assets/myoassist/urdf_zero_assist_motion_stiff_cuff_v1.json"
)
DEFAULT_TCN = PROJECT_ROOT / "RL/outputs/tcn_runs/seed_43/best_model.pt"
DEFAULT_CALIBRATION = (
    PROJECT_ROOT / "RL/assets/tcn/myoassist_urdf_dynamic_stiff_cuff_v5.json"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/outputs/myoassist_policy_audit/report.json"

AUDIT_SCHEMA = "gexo_myoassist_policy_dependence_audit_v2"
TRACE_SCHEMA = "gexo_myoassist_policy_dependence_traces_v2"
AUDIT_MODES = (
    "policy",
    "zero_tcn",
    "delayed_tcn",
    "constant_torque",
    "phase_shifted_torque",
)
JOINT_ORDER = ("left_hip", "left_knee", "right_hip", "right_knee")


class TcnObservationTransform:
    """Apply one deterministic intervention to the final 16 Actor inputs."""

    def __init__(self, mode: str, delay_steps: int) -> None:
        if mode not in ("policy", "zero_tcn", "delayed_tcn"):
            raise ValueError(f"Unsupported TCN intervention: {mode}.")
        if delay_steps < 1:
            raise ValueError("delay_steps must be positive.")
        self.mode = mode
        self.delay_steps = int(delay_steps)
        self._history: deque[np.ndarray] = deque(maxlen=self.delay_steps)

    def __call__(self, observation: np.ndarray) -> np.ndarray:
        result = np.asarray(observation, dtype=np.float32).copy()
        if result.ndim != 1 or result.size < TCN_FEATURE_DIM:
            raise ValueError("Actor observation is too short for the TCN feature bank.")
        if self.mode == "policy":
            return result

        current = result[-TCN_FEATURE_DIM:].copy()
        if self.mode == "zero_tcn":
            result[-TCN_FEATURE_DIM:] = 0.0
        elif len(self._history) >= self.delay_steps:
            result[-TCN_FEATURE_DIM:] = self._history[0]
        self._history.append(current)
        return result


def build_replay_torque(
    policy_torque_nm: np.ndarray,
    mode: str,
    phase_shift_steps: int,
) -> np.ndarray:
    """Build a constant or time-shifted open-loop torque intervention."""

    torque = np.asarray(policy_torque_nm, dtype=np.float32)
    if torque.ndim != 2 or torque.shape[1] != 4 or torque.shape[0] < 1:
        raise ValueError("policy_torque_nm must have shape [steps, 4].")
    if not np.all(np.isfinite(torque)):
        raise FloatingPointError("policy_torque_nm contains NaN or Inf.")
    if mode == "constant_torque":
        return np.broadcast_to(np.mean(torque, axis=0), torque.shape).copy()
    if mode == "phase_shifted_torque":
        if phase_shift_steps < 1:
            raise ValueError("phase_shift_steps must be positive.")
        return np.roll(torque, shift=int(phase_shift_steps), axis=0)
    raise ValueError(f"Unsupported torque replay mode: {mode}.")


def _record_step(rows: dict[str, list], info: dict[str, Any]) -> None:
    rows["activation_cost"].append(float(info["reward/activation_cost"]))
    rows["target_activation_cost"].append(
        np.asarray(
            [
                info["reward/target_activation_cost_left"],
                info["reward/target_activation_cost_right"],
            ],
            dtype=np.float32,
        )
    )
    rows["human_torque_cost"].append(float(info["reward/human_torque_cost"]))
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
    rows["joint_q_rad"].append(
        np.asarray(info["human_joint_q_rad"], dtype=np.float32)
    )
    rows.setdefault("gait_period_steps", []).append(
        float(info["gait_period_steps"])
    )


def _attach_torque_diagnostics(
    summary: dict[str, object],
    traces: dict[str, np.ndarray],
) -> None:
    torque = traces["applied_exo_torque_nm"]
    if not torque.size:
        return
    mean = np.mean(torque, axis=0)
    standard_deviation = np.std(torque, axis=0)
    mean_absolute = np.mean(np.abs(torque), axis=0)
    summary["mean_exo_torque_nm_by_joint"] = mean.tolist()
    summary["std_exo_torque_nm_by_joint"] = standard_deviation.tolist()
    summary["mean_absolute_exo_torque_nm_by_joint"] = mean_absolute.tolist()
    summary["dc_fraction"] = float(
        np.mean(np.abs(mean)) / max(float(np.mean(mean_absolute)), 1.0e-8)
    )
    summary["dynamic_fraction"] = float(
        np.mean(standard_deviation) / max(float(np.mean(mean_absolute)), 1.0e-8)
    )
    summary["rms_exo_torque_nm"] = float(np.sqrt(np.mean(np.square(torque))))


def run_audit_episode(
    *,
    mode: str,
    model: PPO,
    environment_options: dict[str, Any],
    seed: int,
    speed: float,
    reference_index: int,
    steps: int,
    tcn_delay_steps: int,
    replay_torque_nm: np.ndarray | None = None,
) -> tuple[dict[str, object], dict[str, np.ndarray]]:
    """Run one policy or intervention episode from an identical reset."""

    if mode not in AUDIT_MODES:
        raise ValueError(f"Unsupported audit mode: {mode}.")
    if mode in ("constant_torque", "phase_shifted_torque"):
        if replay_torque_nm is None or replay_torque_nm.shape != (steps, 4):
            raise ValueError("Torque replay modes require a [steps, 4] trace.")

    environment = GexoMyoAssistEnv(seed=seed, **environment_options)
    observation, _ = environment.reset(
        seed=seed,
        options={"target_speed": speed, "reference_index": reference_index},
    )
    transform = TcnObservationTransform(
        mode if mode in ("policy", "zero_tcn", "delayed_tcn") else "policy",
        tcn_delay_steps,
    )
    rows = _empty_rows()
    total_return = 0.0
    reason = "evaluation_horizon"
    try:
        for step_index in range(steps):
            if replay_torque_nm is None:
                actor_observation = transform(observation)
                action, _ = model.predict(actor_observation, deterministic=True)
            else:
                action = replay_torque_nm[step_index] / environment.action_torque_scale_nm
                action = np.clip(action, -1.0, 1.0).astype(np.float32)
            observation, reward, terminated, truncated, info = environment.step(action)
            total_return += float(reward)
            _record_step(rows, info)
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

    summary, traces = _summarize(
        mode=mode,
        seed=seed,
        speed=speed,
        reference_index=reference_index,
        steps=steps,
        reason=reason,
        total_return=total_return,
        rows=rows,
    )
    _attach_torque_diagnostics(summary, traces)
    gait_period = traces["gait_period_steps"]
    summary["median_gait_period_steps"] = (
        float(np.median(gait_period[np.isfinite(gait_period)]))
        if np.any(np.isfinite(gait_period))
        else None
    )
    return summary, traces


def _mean(pairs: list[dict[str, object]], mode: str, key: str) -> float | None:
    values = [
        float(pair[f"{mode}_{key}"])
        for pair in pairs
        if pair.get(f"{mode}_{key}") is not None
    ]
    return float(np.mean(values)) if values else None


def finalize_audit_pair(
    runs: dict[str, dict[str, object]],
    *,
    requested_steps: int,
    protocol_thresholds: dict[str, float],
) -> dict[str, object]:
    """Pair every intervention with baseline without cross-mode invalidation."""

    pair: dict[str, object] = {
        **runs,
        "pair_valid_by_mode": {},
        "equal_horizon_by_mode": {},
        "complete_horizon_by_mode": {},
        "protocol_by_mode": {},
        "protocol_pass_by_mode": {},
        "effectiveness_by_mode": {},
    }
    for mode in AUDIT_MODES:
        mode_pair = finalize_pair(
            {"baseline": runs["baseline"], mode: runs[mode]},
            requested_modes=("baseline", mode),
            requested_steps=requested_steps,
            protocol_thresholds=protocol_thresholds,
            nondegradation_tolerance=0.0,
            minimum_improvement=0.0,
            gross_degradation_tolerance=0.1,
            movement_rmse_tolerance_rad=0.15,
        )
        pair["pair_valid_by_mode"][mode] = mode_pair["pair_valid"]
        pair["equal_horizon_by_mode"][mode] = mode_pair["equal_horizon"]
        pair["complete_horizon_by_mode"][mode] = mode_pair["complete_horizon"]
        pair["protocol_pass_by_mode"][mode] = mode_pair["protocol_pass"]
        pair["protocol_by_mode"].setdefault(
            "baseline", mode_pair["protocol_by_mode"]["baseline"]
        )
        pair["protocol_by_mode"][mode] = mode_pair["protocol_by_mode"][mode]
        pair["effectiveness_by_mode"][mode] = mode_pair[
            "effectiveness_by_mode"
        ][mode]
        prefix = f"{mode}_"
        for key, value in mode_pair.items():
            if key.startswith(prefix):
                pair[key] = value

    pair["pair_valid"] = all(pair["pair_valid_by_mode"].values())
    pair["equal_horizon"] = all(pair["equal_horizon_by_mode"].values())
    pair["complete_horizon"] = all(pair["complete_horizon_by_mode"].values())
    pair["protocol_pass"] = all(pair["protocol_pass_by_mode"].values())
    return pair


def summarize_audit(
    pairs: list[dict[str, object]],
    *,
    strict_speed_delta_m_s: float,
) -> tuple[dict[str, dict[str, object]], dict[str, object]]:
    """Aggregate interventions and state conservative decision flags."""

    by_mode: dict[str, dict[str, object]] = {}
    for mode in AUDIT_MODES:
        valid_pairs = [
            pair
            for pair in pairs
            if bool(pair.get("pair_valid_by_mode", {}).get(mode, pair["pair_valid"]))
        ]
        mode_runs = [pair[mode] for pair in valid_pairs]
        speed_deltas = [
            abs(
                float(run["mean_forward_speed_m_s"])
                - float(pair["baseline"]["mean_forward_speed_m_s"])
            )
            for pair, run in zip(valid_pairs, mode_runs)
        ]
        activation = _mean(pairs, mode, "activation_saving_fraction")
        human_torque = _mean(pairs, mode, "human_torque_saving_fraction")
        by_mode[mode] = {
            "valid_pair_count": len(valid_pairs),
            "strict_speed_match_rate": (
                float(np.mean(np.asarray(speed_deltas) <= strict_speed_delta_m_s))
                if speed_deltas
                else None
            ),
            "mean_absolute_speed_delta_from_naked_m_s": (
                float(np.mean(speed_deltas)) if speed_deltas else None
            ),
            "mean_activation_saving_fraction": activation,
            "mean_target_activation_saving_left_fraction": _mean(
                pairs, mode, "target_activation_saving_left_fraction"
            ),
            "mean_target_activation_saving_right_fraction": _mean(
                pairs, mode, "target_activation_saving_right_fraction"
            ),
            "mean_human_torque_saving_fraction": human_torque,
            "mean_gross_load_saving_fraction": _mean(
                pairs, mode, "gross_load_saving_fraction"
            ),
            "mean_effort_proxy": (
                None
                if activation is None or human_torque is None
                else 0.6 * activation + 0.4 * human_torque
            ),
            "mean_absolute_exo_torque_nm": (
                float(np.mean([float(run["mean_absolute_exo_torque_nm"]) for run in mode_runs]))
                if mode_runs
                else None
            ),
            "mean_rms_exo_torque_nm": (
                float(np.mean([float(run["rms_exo_torque_nm"]) for run in mode_runs]))
                if mode_runs
                else None
            ),
            "mean_dc_fraction": (
                float(np.mean([float(run["dc_fraction"]) for run in mode_runs]))
                if mode_runs
                else None
            ),
            "mean_dynamic_fraction": (
                float(np.mean([float(run["dynamic_fraction"]) for run in mode_runs]))
                if mode_runs
                else None
            ),
        }

    policy_score = by_mode["policy"]["mean_effort_proxy"]
    score_delta = {
        mode: (
            None
            if policy_score is None or by_mode[mode]["mean_effort_proxy"] is None
            else float(policy_score) - float(by_mode[mode]["mean_effort_proxy"])
        )
        for mode in AUDIT_MODES
        if mode != "policy"
    }
    minimum_material_delta = 0.002
    speed_valid = {
        mode: (
            by_mode[mode]["valid_pair_count"] == len(pairs)
            and by_mode[mode]["strict_speed_match_rate"] == 1.0
        )
        for mode in AUDIT_MODES
    }
    raw_tcn_advantage = (
        score_delta["zero_tcn"] is not None
        and score_delta["delayed_tcn"] is not None
        and score_delta["zero_tcn"] > minimum_material_delta
        and score_delta["delayed_tcn"] > minimum_material_delta
    )
    raw_timing_advantage = (
        score_delta["constant_torque"] is not None
        and score_delta["phase_shifted_torque"] is not None
        and score_delta["constant_torque"] > minimum_material_delta
        and score_delta["phase_shifted_torque"] > minimum_material_delta
    )
    policy_mean_abs = by_mode["policy"]["mean_absolute_exo_torque_nm"]
    policy_rms = by_mode["policy"]["mean_rms_exo_torque_nm"]
    exposure_ratio: dict[str, dict[str, float] | None] = {}
    exposure_matched: dict[str, bool] = {}
    for mode in ("constant_torque", "phase_shifted_torque"):
        mode_mean_abs = by_mode[mode]["mean_absolute_exo_torque_nm"]
        mode_rms = by_mode[mode]["mean_rms_exo_torque_nm"]
        if None in (policy_mean_abs, policy_rms, mode_mean_abs, mode_rms):
            exposure_ratio[mode] = None
            exposure_matched[mode] = False
            continue
        ratios = {
            "mean_absolute": float(mode_mean_abs) / max(float(policy_mean_abs), 1.0e-8),
            "rms": float(mode_rms) / max(float(policy_rms), 1.0e-8),
        }
        exposure_ratio[mode] = ratios
        exposure_matched[mode] = all(0.9 <= value <= 1.1 for value in ratios.values())
    conclusions = {
        "strict_speed_delta_m_s": strict_speed_delta_m_s,
        "minimum_material_effort_delta": minimum_material_delta,
        "speed_valid_all_conditions_by_mode": speed_valid,
        "policy_speed_valid_all_conditions": speed_valid["policy"],
        "raw_tcn_effort_advantage": raw_tcn_advantage,
        "raw_torque_timing_effort_advantage": raw_timing_advantage,
        "torque_replay_exposure_ratio_vs_policy": exposure_ratio,
        "torque_replay_exposure_matched": exposure_matched,
        "tcn_benefit_supported": bool(
            raw_tcn_advantage
            and speed_valid["policy"]
            and speed_valid["zero_tcn"]
            and speed_valid["delayed_tcn"]
        ),
        "torque_timing_benefit_supported": bool(
            raw_timing_advantage
            and speed_valid["policy"]
            and speed_valid["constant_torque"]
            and speed_valid["phase_shifted_torque"]
            and exposure_matched["constant_torque"]
            and exposure_matched["phase_shifted_torque"]
        ),
        "policy_minus_ablation_effort_proxy": score_delta,
    }
    conclusions["ready_for_long_training"] = bool(
        conclusions["policy_speed_valid_all_conditions"]
        and conclusions["tcn_benefit_supported"]
        and conclusions["torque_timing_benefit_supported"]
    )
    return by_mode, conclusions


def _artifact(path: Path) -> dict[str, str]:
    resolved = path.expanduser().resolve(strict=True)
    return {"path": str(resolved), "sha256": file_sha256(resolved)}


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--human-checkpoint", type=Path, default=DEFAULT_HUMAN)
    parser.add_argument("--baseline", type=Path, default=DEFAULT_BASELINE)
    parser.add_argument("--motion-reference", type=Path, default=DEFAULT_MOTION)
    parser.add_argument("--tcn-checkpoint", type=Path, default=DEFAULT_TCN)
    parser.add_argument("--tcn-calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument(
        "--physical-model",
        type=Path,
        default=DEFAULT_URDF_DYNAMIC_OUTPUT_PATH,
    )
    parser.add_argument(
        "--reference-model",
        type=Path,
        default=DEFAULT_PHYSICAL_OUTPUT_PATH,
    )
    parser.add_argument("--speeds", default="0.85,1.0,1.15")
    parser.add_argument("--seeds", default="0")
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--tcn-delay-steps", type=int, default=27)
    parser.add_argument(
        "--phase-shift-steps",
        type=int,
        default=0,
        help="Fixed shift; 0 chooses half of the measured gait period per rollout.",
    )
    parser.add_argument("--strict-speed-delta", type=float, default=0.03)
    parser.add_argument("--action-scale-nm", type=float, default=8.0)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--trace-output", type=Path)
    args = parser.parse_args()

    speeds = parse_csv(args.speeds, float)
    seeds = parse_csv(args.seeds, int)
    if not speeds or not seeds or args.steps < 1:
        raise ValueError("speeds, seeds, and steps must be non-empty/positive.")
    if args.strict_speed_delta <= 0.0:
        raise ValueError("--strict-speed-delta must be positive.")
    if args.phase_shift_steps < 0:
        raise ValueError("--phase-shift-steps must be non-negative.")

    paths = {
        "model": args.model,
        "human_checkpoint": args.human_checkpoint,
        "baseline": args.baseline,
        "motion_reference": args.motion_reference,
        "tcn_checkpoint": args.tcn_checkpoint,
        "tcn_calibration": args.tcn_calibration,
        "physical_model": args.physical_model,
        "reference_model": args.reference_model,
    }
    paths = {name: path.expanduser().resolve(strict=True) for name, path in paths.items()}
    baseline = MyoAssistBaseline.load(paths["baseline"])
    if file_sha256(paths["reference_model"]) != baseline.metadata["reference_model_sha256"]:
        raise ValueError("The naked reference model does not match the baseline.")
    if min(speeds) < baseline.speeds_m_s[0] or max(speeds) > baseline.speeds_m_s[-1]:
        raise ValueError("Audit speeds must stay inside the baseline range.")

    model = PPO.load(paths["model"], device=args.device)
    human_policy = FrozenHumanPolicy(paths["human_checkpoint"], device="cpu")
    environment_options = {
        "human_checkpoint": str(paths["human_checkpoint"]),
        "baseline_path": str(paths["baseline"]),
        "motion_reference_path": str(paths["motion_reference"]),
        "tcn_checkpoint": str(paths["tcn_checkpoint"]),
        "tcn_calibration": str(paths["tcn_calibration"]),
        "max_episode_steps": args.steps,
        "min_speed_m_s": min(speeds),
        "max_speed_m_s": max(speeds),
        "action_torque_scale_nm": args.action_scale_nm,
        "human_device": "cpu",
        "tcn_device": "cpu",
        "model_path": str(paths["physical_model"]),
        "domain_randomization": False,
    }

    pairs: list[dict[str, object]] = []
    trace_arrays: dict[str, np.ndarray] = {
        "schema": np.asarray(TRACE_SCHEMA),
        "control_dt_s": np.asarray(CONTROL_DT, dtype=np.float64),
    }
    applied_phase_shifts: list[int] = []
    for speed in speeds:
        speed_reference = baseline.at_speed(speed)
        protocol_thresholds = {
            "speed_tolerance_m_s": float(
                speed_reference.speed_free_error_m_s
                + speed_reference.speed_transition_m_s
            ),
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
        for seed in seeds:
            pair_index = len(pairs)
            runs: dict[str, dict[str, object]] = {}
            traces: dict[str, dict[str, np.ndarray]] = {}
            runs["baseline"], traces["baseline"] = run_naked_episode(
                policy=human_policy,
                baseline=baseline,
                reference_model=paths["reference_model"],
                seed=seed,
                speed=speed,
                reference_index=0,
                steps=args.steps,
            )
            runs["policy"], traces["policy"] = run_audit_episode(
                mode="policy",
                model=model,
                environment_options=environment_options,
                seed=seed,
                speed=speed,
                reference_index=0,
                steps=args.steps,
                tcn_delay_steps=args.tcn_delay_steps,
            )
            policy_torque = traces["policy"]["applied_exo_torque_nm"]
            if policy_torque.shape != (args.steps, 4):
                raise RuntimeError("The policy did not complete the audit horizon.")
            gait_period_steps = runs["policy"]["median_gait_period_steps"]
            if gait_period_steps is None:
                raise RuntimeError("The policy rollout did not report a gait period.")
            phase_shift_steps = (
                args.phase_shift_steps
                if args.phase_shift_steps > 0
                else max(1, int(round(0.5 * float(gait_period_steps))))
            )
            applied_phase_shifts.append(phase_shift_steps)

            for mode in AUDIT_MODES[1:]:
                replay = None
                if mode in ("constant_torque", "phase_shifted_torque"):
                    replay = build_replay_torque(
                        policy_torque,
                        mode,
                        phase_shift_steps,
                    )
                runs[mode], traces[mode] = run_audit_episode(
                    mode=mode,
                    model=model,
                    environment_options=environment_options,
                    seed=seed,
                    speed=speed,
                    reference_index=0,
                    steps=args.steps,
                    tcn_delay_steps=args.tcn_delay_steps,
                    replay_torque_nm=replay,
                )

            modes = ("baseline", *AUDIT_MODES)
            attach_pairwise_movement(runs, traces, modes)
            pair = finalize_audit_pair(
                runs,
                requested_steps=args.steps,
                protocol_thresholds=protocol_thresholds,
            )
            pairs.append(pair)
            for mode, mode_traces in traces.items():
                for name, values in mode_traces.items():
                    trace_arrays[f"pair_{pair_index:04d}_{mode}_{name}"] = values

    by_mode, conclusions = summarize_audit(
        pairs,
        strict_speed_delta_m_s=args.strict_speed_delta,
    )
    output = args.output.expanduser().resolve()
    trace_output = (
        args.trace_output.expanduser().resolve()
        if args.trace_output is not None
        else output.with_suffix(".npz")
    )
    report = {
        "schema": AUDIT_SCHEMA,
        "artifacts": {name: _artifact(path) for name, path in paths.items()},
        "protocol": {
            "modes": list(AUDIT_MODES),
            "speeds_m_s": list(speeds),
            "seeds": list(seeds),
            "steps": args.steps,
            "joint_order": list(JOINT_ORDER),
            "tcn_feature_slice": [-TCN_FEATURE_DIM, None],
            "tcn_delay_steps": args.tcn_delay_steps,
            "phase_shift_steps": args.phase_shift_steps,
            "requested_phase_shift_steps": args.phase_shift_steps,
            "phase_shift_mode": (
                "fixed" if args.phase_shift_steps > 0 else "measured_half_cycle"
            ),
            "applied_phase_shift_steps_by_pair": applied_phase_shifts,
            "strict_speed_delta_m_s": args.strict_speed_delta,
        },
        "by_mode": by_mode,
        "conclusions": conclusions,
        "pairs": pairs,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    trace_output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2), encoding="utf-8")
    np.savez_compressed(trace_output, **trace_arrays)

    print(f"pairs: {len(pairs)}")
    def percent(value: object) -> str:
        return "n/a" if value is None else f"{100.0 * float(value):+.3f}%"

    def decimal(value: object) -> str:
        return "n/a" if value is None else f"{float(value):.3f}"

    for mode in AUDIT_MODES:
        row = by_mode[mode]
        print(
            f"{mode:22s} speed_match={decimal(row['strict_speed_match_rate'])} "
            f"activation={percent(row['mean_activation_saving_fraction'])} "
            f"torque={percent(row['mean_human_torque_saving_fraction'])} "
            f"effort={percent(row['mean_effort_proxy'])}"
        )
    print("conclusions:", json.dumps(conclusions, sort_keys=True))
    print("report:", output)
    print("traces:", trace_output)


if __name__ == "__main__":
    main()
