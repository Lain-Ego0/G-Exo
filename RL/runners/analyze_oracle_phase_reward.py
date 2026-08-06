"""Audit phase-aligned reward consistency, causality, and learnability."""

from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path

import numpy as np

from RL.env.kinesis.oracle_phase import (
    OraclePhase,
    PhaseCostProfile,
    build_phase_cost_profile,
    cycle_energy,
    extract_oracle_phase,
    merge_phase_cost_profiles,
    phase_aligned_score,
)
from RL.env.kinesis.causal_phase import (
    circular_phase_error,
    load_phase_checkpoint,
    predict_phase,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TRACE_DIR = PROJECT_ROOT / "RL/outputs/oracle_phase_audit/traces"
DEFAULT_REPORT = PROJECT_ROOT / "RL/outputs/oracle_phase_audit/report.json"
DEFAULT_PHASE_MODEL_DIR = PROJECT_ROOT / "RL/outputs/oracle_phase_audit/phase_tcn"
EPSILON = 1.0e-12


def load_trace(path: Path) -> dict:
    with np.load(path, allow_pickle=False) as data:
        trace = {
            name: data[name].copy()
            for name in data.files
        }
    trace["path"] = str(path.resolve())
    return trace


def scalar(trace: dict, name: str, converter=float):
    if name not in trace:
        raise KeyError(f"Trace lacks {name}: {trace['path']}")
    return converter(np.asarray(trace[name]).item())


def trace_phase(trace: dict):
    return extract_oracle_phase(
        trace["touch"],
        dt=scalar(trace, "control_dt"),
        on_threshold=scalar(trace, "contact_on_threshold"),
        off_threshold=scalar(trace, "contact_off_threshold"),
    )


def scoring_phase(trace: dict, prediction=None) -> OraclePhase:
    """Use causal phase values with oracle cycle masks only for offline scoring."""

    oracle = trace_phase(trace)
    if prediction is None:
        return oracle
    valid = oracle.valid & prediction.valid
    cycle_id = np.where(valid, oracle.cycle_id, -1)
    return OraclePhase(
        phase=np.where(valid, prediction.phase, np.nan),
        phase_rate_hz=np.where(valid, prediction.phase_rate_hz, np.nan),
        cycle_id=cycle_id,
        valid=valid,
        event_indices=oracle.event_indices,
        right_contact=oracle.right_contact,
        left_contact=oracle.left_contact,
        contact_on_threshold=oracle.contact_on_threshold,
        contact_off_threshold=oracle.contact_off_threshold,
    )


def time_aligned_score(
    baseline: dict,
    assisted: dict,
    *,
    selected: np.ndarray,
    denominator: float,
) -> float:
    """Score one assisted cycle against baseline values at wall-clock time."""

    expected = np.interp(
        assisted["time_s"][selected],
        baseline["time_s"],
        baseline["activation_cost"],
    )
    actual = assisted["activation_cost"][selected]
    dt = scalar(assisted, "control_dt")
    return float(np.sum(expected - actual) * dt / max(denominator, EPSILON))


def analyze_intervention(
    baseline: dict,
    assisted: dict,
    *,
    activation_profile,
    context_profile,
    exact_context_profile=None,
    causal_prediction=None,
) -> dict:
    baseline_phase = trace_phase(baseline)
    assisted_phase = trace_phase(assisted)
    causal_assisted_phase = scoring_phase(assisted, causal_prediction)

    pulse_step = scalar(assisted, "pulse_start_step", int)
    if not 0 <= pulse_step < assisted_phase.phase.size:
        raise ValueError("Pulse step is outside the assisted trace.")
    actual_cycle_id = int(assisted_phase.cycle_id[pulse_step])
    if actual_cycle_id < 0:
        raise ValueError("Pulse is not inside a complete assisted gait cycle.")
    baseline_cycle_id = int(baseline_phase.cycle_id[pulse_step])
    if baseline_cycle_id < 0:
        raise ValueError("Pulse is not inside a complete baseline gait cycle.")
    selected = assisted_phase.cycle_id == actual_cycle_id

    baseline_activation_energy = cycle_energy(
        baseline_phase,
        baseline["activation_cost"],
        dt=scalar(baseline, "control_dt"),
        cycle_id=baseline_cycle_id,
    )
    baseline_torque_impulse = cycle_energy(
        baseline_phase,
        baseline["muscle_torque_cost"],
        dt=scalar(baseline, "control_dt"),
        cycle_id=baseline_cycle_id,
    )

    actual_activation_energy = cycle_energy(
        assisted_phase,
        assisted["activation_cost"],
        dt=scalar(assisted, "control_dt"),
        cycle_id=actual_cycle_id,
    )
    actual_torque_impulse = cycle_energy(
        assisted_phase,
        assisted["muscle_torque_cost"],
        dt=scalar(assisted, "control_dt"),
        cycle_id=actual_cycle_id,
    )
    ground_truth_saving = (
        baseline_activation_energy - actual_activation_energy
    ) / max(baseline_activation_energy, EPSILON)
    torque_saving = (
        baseline_torque_impulse - actual_torque_impulse
    ) / max(baseline_torque_impulse, EPSILON)
    paired_profile = build_phase_cost_profile(
        baseline_phase,
        baseline["activation_cost"],
        dt=scalar(baseline, "control_dt"),
        cycle_ids=(baseline_cycle_id,),
    )
    paired_phase_score = phase_aligned_score(
        paired_profile,
        assisted_phase,
        assisted["activation_cost"],
        dt=scalar(assisted, "control_dt"),
        cycle_id=actual_cycle_id,
    )
    pooled_phase_score = phase_aligned_score(
        activation_profile,
        assisted_phase,
        assisted["activation_cost"],
        dt=scalar(assisted, "control_dt"),
        cycle_id=actual_cycle_id,
    )
    pooled_phase_score *= activation_profile.cycle_energy_mean / max(
        baseline_activation_energy, EPSILON
    )
    context_phase_score = phase_aligned_score(
        context_profile,
        assisted_phase,
        assisted["activation_cost"],
        dt=scalar(assisted, "control_dt"),
        cycle_id=actual_cycle_id,
    )
    context_phase_score *= context_profile.cycle_energy_mean / max(
        baseline_activation_energy, EPSILON
    )
    if exact_context_profile is None:
        exact_context_profile = paired_profile
    causal_exact_context_score = phase_aligned_score(
        exact_context_profile,
        causal_assisted_phase,
        assisted["activation_cost"],
        dt=scalar(assisted, "control_dt"),
        cycle_id=actual_cycle_id,
    )
    causal_exact_context_score *= exact_context_profile.cycle_energy_mean / max(
        baseline_activation_energy, EPSILON
    )
    causal_loso_context_score = phase_aligned_score(
        context_profile,
        causal_assisted_phase,
        assisted["activation_cost"],
        dt=scalar(assisted, "control_dt"),
        cycle_id=actual_cycle_id,
    )
    causal_loso_context_score *= context_profile.cycle_energy_mean / max(
        baseline_activation_energy, EPSILON
    )
    finite_same_state = selected & np.isfinite(assisted["same_state_saving"])
    same_state_score = (
        float(np.mean(assisted["same_state_saving"][finite_same_state]))
        if np.any(finite_same_state)
        else float("nan")
    )
    pulse_stop = min(
        pulse_step + scalar(assisted, "pulse_steps", int),
        len(assisted["exo_torque"]),
    )
    pulse_joint = scalar(assisted, "pulse_joint", int)

    return {
        "path": assisted["path"],
        "motion_id": scalar(assisted, "motion_id", int),
        "seed": scalar(assisted, "seed", int),
        "target_phase": scalar(assisted, "target_phase"),
        "reference_phase_at_pulse": float(baseline_phase.phase[pulse_step]),
        "actual_phase_at_pulse": float(assisted_phase.phase[pulse_step]),
        "causal_phase_at_pulse": float(
            causal_assisted_phase.phase[pulse_step]
        ),
        "causal_phase_confidence_at_pulse": (
            float(causal_prediction.confidence[pulse_step])
            if causal_prediction is not None
            else 1.0
        ),
        "pulse_joint": pulse_joint,
        "pulse_nm": scalar(assisted, "pulse_nm"),
        "actual_peak_pulse_torque_nm": float(
            np.max(
                np.abs(
                    assisted["exo_torque"][pulse_step:pulse_stop, pulse_joint]
                )
            )
        ),
        "actual_cycle_id": actual_cycle_id,
        "actual_cycle_duration_s": float(np.sum(selected))
        * scalar(assisted, "control_dt"),
        "joint_position_at_pulse": assisted["joint_position"][
            pulse_step
        ].tolist(),
        "joint_velocity_at_pulse": assisted["joint_velocity"][
            pulse_step
        ].tolist(),
        "ground_truth_activation_saving": float(ground_truth_saving),
        "ground_truth_torque_saving": float(torque_saving),
        "same_state_score": same_state_score,
        "time_aligned_score": time_aligned_score(
            baseline,
            assisted,
            selected=selected,
            denominator=baseline_activation_energy,
        ),
        "phase_aligned_score": float(paired_phase_score),
        "pooled_phase_aligned_score": float(pooled_phase_score),
        "context_phase_aligned_score": float(context_phase_score),
        "causal_exact_context_score": float(causal_exact_context_score),
        "causal_loso_context_score": float(causal_loso_context_score),
        "mean_tracking_mse": float(np.mean(assisted["tracking_mse"][selected])),
        "successful_episode": bool(scalar(assisted, "success", bool)),
    }


def metric_summary(
    rows: list[dict],
    metric: str,
    *,
    deadband: float,
) -> dict:
    truth = np.asarray(
        [row["ground_truth_activation_saving"] for row in rows],
        dtype=np.float64,
    )
    prediction = np.asarray([row[metric] for row in rows], dtype=np.float64)
    valid = np.isfinite(truth) & np.isfinite(prediction)
    truth = truth[valid]
    prediction = prediction[valid]
    decisive = np.abs(truth) >= deadband
    correlation = rank_correlation(truth, prediction)
    return {
        "count": int(truth.size),
        "decisive_count": int(np.sum(decisive)),
        "spearman": correlation,
        "sign_agreement": (
            float(np.mean(np.sign(truth[decisive]) == np.sign(prediction[decisive])))
            if np.any(decisive)
            else float("nan")
        ),
        "mean_absolute_error": (
            float(np.mean(np.abs(prediction - truth)))
            if truth.size
            else float("nan")
        ),
        "score_mean": float(np.mean(prediction)) if truth.size else float("nan"),
        "score_std": float(np.std(prediction)) if truth.size else float("nan"),
    }


def learnability_summary(rows: list[dict], metric: str) -> dict:
    groups: dict[tuple, list[dict]] = defaultdict(list)
    for row in rows:
        key = (
            row["motion_id"],
            row["target_phase"],
            row["pulse_joint"],
            row["pulse_nm"],
        )
        groups[key].append(row)

    group_rows = []
    for key, members in sorted(groups.items()):
        values = np.asarray([member[metric] for member in members], dtype=np.float64)
        truth = np.asarray(
            [member["ground_truth_activation_saving"] for member in members],
            dtype=np.float64,
        )
        valid = np.isfinite(values) & np.isfinite(truth)
        values = values[valid]
        truth = truth[valid]
        if values.size == 0:
            continue
        score_std = float(np.std(values))
        truth_std = float(np.std(truth))
        group_rows.append(
            {
                "motion_id": key[0],
                "target_phase": key[1],
                "pulse_joint": key[2],
                "pulse_nm": key[3],
                "seed_count": int(values.size),
                "mean_score": float(np.mean(values)),
                "score_seed_std": score_std,
                "score_effect_to_seed_noise": float(
                    abs(np.mean(values)) / max(score_std, EPSILON)
                ),
                "mean_ground_truth_saving": float(np.mean(truth)),
                "ground_truth_seed_std": truth_std,
                "ground_truth_effect_to_seed_noise": float(
                    abs(np.mean(truth)) / max(truth_std, EPSILON)
                ),
            }
        )

    score_means = np.asarray(
        [row["mean_score"] for row in group_rows], dtype=np.float64
    )
    within_variances = np.asarray(
        [row["score_seed_std"] ** 2 for row in group_rows],
        dtype=np.float64,
    )
    return {
        "action_group_count": len(group_rows),
        "groups_with_multiple_seeds": int(
            sum(row["seed_count"] >= 2 for row in group_rows)
        ),
        "between_action_variance": (
            float(np.var(score_means)) if score_means.size else float("nan")
        ),
        "mean_within_action_seed_variance": (
            float(np.mean(within_variances))
            if within_variances.size
            else float("nan")
        ),
        "action_to_seed_variance_ratio": (
            float(np.var(score_means) / max(np.mean(within_variances), EPSILON))
            if score_means.size and within_variances.size
            else float("nan")
        ),
        "groups": group_rows,
    }


def state_conditioned_probe(
    rows: list[dict],
    *,
    deadband: float,
    ridge_alpha: float = 10.0,
) -> dict:
    """Use leave-one-seed-out ridge regression as a minimal learnability probe."""

    features = []
    targets = []
    seeds = []
    for row in rows:
        joint_position = np.asarray(
            row["joint_position_at_pulse"], dtype=np.float64
        )
        joint_velocity = np.asarray(
            row["joint_velocity_at_pulse"], dtype=np.float64
        )
        action = np.zeros(4, dtype=np.float64)
        action[row["pulse_joint"]] = row["pulse_nm"]
        angle = 2.0 * np.pi * row["actual_phase_at_pulse"]
        state = np.concatenate((joint_position, joint_velocity))
        features.append(
            np.concatenate(
                (
                    state,
                    [np.sin(angle), np.cos(angle)],
                    action,
                    np.outer(action, state).reshape(-1),
                )
            )
        )
        targets.append(row["ground_truth_activation_saving"])
        seeds.append(row["seed"])

    feature_array = np.asarray(features, dtype=np.float64)
    target_array = np.asarray(targets, dtype=np.float64)
    seed_array = np.asarray(seeds, dtype=np.int64)
    predictions = np.full(target_array.shape, np.nan, dtype=np.float64)
    baseline_predictions = np.full(target_array.shape, np.nan, dtype=np.float64)
    unique_seeds = np.unique(seed_array)

    if unique_seeds.size < 3:
        return {
            "available": False,
            "reason": "at least three seeds are required",
            "seed_count": int(unique_seeds.size),
            "ridge_alpha": ridge_alpha,
        }

    for held_out_seed in unique_seeds:
        train = seed_array != held_out_seed
        test = ~train
        mean = feature_array[train].mean(axis=0)
        std = np.maximum(feature_array[train].std(axis=0), 1.0e-6)
        train_features = (feature_array[train] - mean) / std
        test_features = (feature_array[test] - mean) / std
        train_features = np.column_stack(
            (np.ones(np.sum(train)), train_features)
        )
        test_features = np.column_stack(
            (np.ones(np.sum(test)), test_features)
        )
        regularizer = np.eye(train_features.shape[1]) * ridge_alpha
        regularizer[0, 0] = 0.0
        coefficients = np.linalg.solve(
            train_features.T @ train_features + regularizer,
            train_features.T @ target_array[train],
        )
        predictions[test] = test_features @ coefficients
        baseline_predictions[test] = float(np.mean(target_array[train]))

    squared_error = float(np.sum(np.square(target_array - predictions)))
    baseline_error = float(
        np.sum(np.square(target_array - baseline_predictions))
    )
    decisive = np.abs(target_array) >= deadband
    return {
        "available": True,
        "seed_count": int(unique_seeds.size),
        "sample_count": int(target_array.size),
        "feature_count": int(feature_array.shape[1]),
        "ridge_alpha": ridge_alpha,
        "leave_one_seed_out_r2": float(
            1.0 - squared_error / max(baseline_error, EPSILON)
        ),
        "pearson": float(np.corrcoef(target_array, predictions)[0, 1]),
        "spearman": rank_correlation(target_array, predictions),
        "mean_absolute_error": float(
            np.mean(np.abs(target_array - predictions))
        ),
        "sign_agreement": (
            float(
                np.mean(
                    np.sign(target_array[decisive])
                    == np.sign(predictions[decisive])
                )
            )
            if np.any(decisive)
            else float("nan")
        ),
    }


def pooled_profiles(
    baselines: dict[tuple[int, int], dict]
) -> dict[int, PhaseCostProfile]:
    by_motion: dict[int, list] = defaultdict(list)
    for (motion_id, _), trace in baselines.items():
        phase = trace_phase(trace)
        dt = scalar(trace, "control_dt")
        by_motion[motion_id].append(
            build_phase_cost_profile(phase, trace["activation_cost"], dt=dt)
        )
    return {
        motion_id: merge_phase_cost_profiles(values)
        for motion_id, values in by_motion.items()
    }


def exact_cycle_profiles(
    baselines: dict[tuple[int, int], dict]
) -> dict[tuple[int, int, int], PhaseCostProfile]:
    """Index every baseline by motion, reference seed, cycle, and phase."""

    result = {}
    for (motion_id, seed), trace in baselines.items():
        phase = trace_phase(trace)
        dt = scalar(trace, "control_dt")
        for cycle_id in np.unique(phase.cycle_id[phase.valid]):
            result[(motion_id, seed, int(cycle_id))] = build_phase_cost_profile(
                phase,
                trace["activation_cost"],
                dt=dt,
                cycle_ids=(int(cycle_id),),
            )
    return result


def leave_one_seed_context_profiles(
    exact_profiles: dict[tuple[int, int, int], PhaseCostProfile]
) -> dict[tuple[int, int, int], PhaseCostProfile]:
    """Pool the same reference-cycle ordinal without using the query seed."""

    result = {}
    for motion_id, seed, cycle_id in exact_profiles:
        candidates = [
            profile
            for (other_motion, other_seed, other_cycle), profile
            in exact_profiles.items()
            if other_motion == motion_id
            and other_cycle == cycle_id
            and other_seed != seed
        ]
        if not candidates:
            raise ValueError(
                "Reference context needs another seed for motion "
                f"{motion_id}, cycle {cycle_id}."
            )
        result[(motion_id, seed, cycle_id)] = merge_phase_cost_profiles(
            candidates
        )
    return result


def baseline_consistency(
    baselines: dict[tuple[int, int], dict],
    profiles: dict[int, PhaseCostProfile],
    exact_profiles: dict[tuple[int, int, int], PhaseCostProfile],
    context_profiles: dict[tuple[int, int, int], PhaseCostProfile],
    causal_predictions: dict[str, object] | None = None,
) -> dict:
    rows = []
    all_paired_scores = []
    all_pooled_scores = []
    all_context_scores = []
    all_causal_exact_scores = []
    all_causal_context_scores = []
    for (motion_id, seed), trace in sorted(baselines.items()):
        phase = trace_phase(trace)
        causal_phase = scoring_phase(
            trace,
            None
            if causal_predictions is None
            else causal_predictions[trace["path"]],
        )
        profile = profiles[motion_id]
        cycle_ids = np.unique(phase.cycle_id[phase.valid])
        paired_scores = []
        pooled_scores = []
        context_scores = []
        causal_exact_scores = []
        causal_context_scores = []
        for cycle_id in cycle_ids:
            exact_profile = exact_profiles[(motion_id, seed, int(cycle_id))]
            paired_scores.append(
                phase_aligned_score(
                    exact_profile,
                    phase,
                    trace["activation_cost"],
                    dt=scalar(trace, "control_dt"),
                    cycle_id=int(cycle_id),
                )
            )
            pooled_scores.append(
                phase_aligned_score(
                    profile,
                    phase,
                    trace["activation_cost"],
                    dt=scalar(trace, "control_dt"),
                    cycle_id=int(cycle_id),
                )
            )
            context_scores.append(
                phase_aligned_score(
                    context_profiles[(motion_id, seed, int(cycle_id))],
                    phase,
                    trace["activation_cost"],
                    dt=scalar(trace, "control_dt"),
                    cycle_id=int(cycle_id),
                )
            )
            causal_exact_scores.append(
                phase_aligned_score(
                    exact_profile,
                    causal_phase,
                    trace["activation_cost"],
                    dt=scalar(trace, "control_dt"),
                    cycle_id=int(cycle_id),
                )
            )
            causal_context_scores.append(
                phase_aligned_score(
                    context_profiles[(motion_id, seed, int(cycle_id))],
                    causal_phase,
                    trace["activation_cost"],
                    dt=scalar(trace, "control_dt"),
                    cycle_id=int(cycle_id),
                )
            )
        all_paired_scores.extend(paired_scores)
        all_pooled_scores.extend(pooled_scores)
        all_context_scores.extend(context_scores)
        all_causal_exact_scores.extend(causal_exact_scores)
        all_causal_context_scores.extend(causal_context_scores)
        rows.append(
            {
                "motion_id": motion_id,
                "seed": seed,
                "cycle_count": int(cycle_ids.size),
                "mean_paired_phase_score": float(np.mean(paired_scores)),
                "maximum_absolute_paired_phase_score": float(
                    np.max(np.abs(paired_scores))
                ),
                "mean_pooled_phase_score": float(np.mean(pooled_scores)),
                "maximum_absolute_pooled_phase_score": float(
                    np.max(np.abs(pooled_scores))
                ),
                "mean_context_phase_score": float(np.mean(context_scores)),
                "maximum_absolute_context_phase_score": float(
                    np.max(np.abs(context_scores))
                ),
                "mean_causal_exact_context_score": float(
                    np.mean(causal_exact_scores)
                ),
                "mean_causal_loso_context_score": float(
                    np.mean(causal_context_scores)
                ),
                "cycle_energy_coefficient_of_variation": float(
                    profile.cycle_energy_std
                    / max(profile.cycle_energy_mean, EPSILON)
                ),
            }
        )
    paired_array = np.asarray(all_paired_scores, dtype=np.float64)
    pooled_array = np.asarray(all_pooled_scores, dtype=np.float64)
    context_array = np.asarray(all_context_scores, dtype=np.float64)
    causal_exact_array = np.asarray(all_causal_exact_scores, dtype=np.float64)
    causal_context_array = np.asarray(
        all_causal_context_scores, dtype=np.float64
    )
    return {
        "baseline_count": len(rows),
        "maximum_absolute_paired_zero_assist_score": (
            float(np.max(np.abs(paired_array)))
            if paired_array.size
            else float("nan")
        ),
        "pooled_zero_assist_score_rms": (
            float(np.sqrt(np.mean(np.square(pooled_array))))
            if pooled_array.size
            else float("nan")
        ),
        "maximum_absolute_pooled_zero_assist_score": (
            float(np.max(np.abs(pooled_array)))
            if pooled_array.size
            else float("nan")
        ),
        "context_zero_assist_score_rms": (
            float(np.sqrt(np.mean(np.square(context_array))))
            if context_array.size
            else float("nan")
        ),
        "maximum_absolute_context_zero_assist_score": (
            float(np.max(np.abs(context_array)))
            if context_array.size
            else float("nan")
        ),
        "causal_exact_zero_assist_score_rms": (
            float(np.sqrt(np.mean(np.square(causal_exact_array))))
            if causal_exact_array.size
            else float("nan")
        ),
        "causal_loso_zero_assist_score_rms": (
            float(np.sqrt(np.mean(np.square(causal_context_array))))
            if causal_context_array.size
            else float("nan")
        ),
        "rows": rows,
    }


def rank_correlation(first: np.ndarray, second: np.ndarray) -> float:
    if first.size < 2 or np.all(first == first[0]) or np.all(second == second[0]):
        return float("nan")
    first_rank = average_ranks(first)
    second_rank = average_ranks(second)
    return float(np.corrcoef(first_rank, second_rank)[0, 1])


def average_ranks(values: np.ndarray) -> np.ndarray:
    order = np.argsort(values, kind="mergesort")
    sorted_values = values[order]
    ranks = np.empty(values.size, dtype=np.float64)
    start = 0
    while start < values.size:
        stop = start + 1
        while stop < values.size and sorted_values[stop] == sorted_values[start]:
            stop += 1
        ranks[order[start:stop]] = 0.5 * (start + stop - 1)
        start = stop
    return ranks


def safe_json(value):
    if isinstance(value, dict):
        return {key: safe_json(item) for key, item in value.items()}
    if isinstance(value, list):
        return [safe_json(item) for item in value]
    if isinstance(value, (np.integer, np.floating)):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def load_causal_phase_predictions(
    traces: list[dict],
    phase_model_directory: Path,
) -> tuple[dict[str, object], dict]:
    """Apply each leave-one-seed-out model to its unseen seed only."""

    predictions = {}
    quality_rows = []
    models = {}
    for trace in traces:
        seed = scalar(trace, "seed", int)
        if seed not in models:
            checkpoint = (
                phase_model_directory / f"held_out_seed_{seed:06d}.pt"
            )
            models[seed] = load_phase_checkpoint(checkpoint, device="cpu")
        model, statistics = models[seed]
        prediction = predict_phase(
            model,
            statistics,
            trace["sensor_frame"],
            device="cpu",
        )
        predictions[trace["path"]] = prediction
        if scalar(trace, "kind", str) != "baseline":
            continue
        oracle = trace_phase(trace)
        valid = oracle.valid & prediction.valid
        error = circular_phase_error(
            prediction.phase[valid],
            oracle.phase[valid],
        )
        quality_rows.append(
            {
                "motion_id": scalar(trace, "motion_id", int),
                "seed": seed,
                "samples": int(np.sum(valid)),
                "phase_mae_cycle": float(np.mean(error)),
                "phase_p95_cycle": float(np.quantile(error, 0.95)),
                "rate_mae_hz": float(
                    np.mean(
                        np.abs(
                            prediction.phase_rate_hz[valid]
                            - oracle.phase_rate_hz[valid]
                        )
                    )
                ),
                "mean_confidence": float(
                    np.mean(prediction.confidence[valid])
                ),
            }
        )
    mae = np.asarray(
        [row["phase_mae_cycle"] for row in quality_rows], dtype=np.float64
    )
    p95 = np.asarray(
        [row["phase_p95_cycle"] for row in quality_rows], dtype=np.float64
    )
    quality = {
        "enabled": True,
        "cross_fitted": True,
        "touch_used_for_inference": False,
        "rows": quality_rows,
        "mean_phase_mae_cycle": float(np.mean(mae)),
        "maximum_fold_phase_p95_cycle": float(np.max(p95)),
        "passed": bool(np.mean(mae) <= 0.08 and np.max(p95) <= 0.20),
    }
    return predictions, quality


def analyze_directory(
    trace_directory: Path,
    *,
    deadband: float,
    phase_model_directory: Path | None = None,
) -> dict:
    traces = [load_trace(path) for path in sorted(trace_directory.glob("*.npz"))]
    baselines = {}
    pulses = []
    for trace in traces:
        kind = scalar(trace, "kind", str)
        key = (
            scalar(trace, "motion_id", int),
            scalar(trace, "seed", int),
        )
        if kind == "baseline":
            baselines[key] = trace
        elif kind == "pulse":
            pulses.append(trace)

    if not baselines:
        raise FileNotFoundError(f"No baseline traces in {trace_directory}.")
    if not pulses:
        raise FileNotFoundError(f"No pulse traces in {trace_directory}.")

    profiles = pooled_profiles(baselines)
    exact_profiles = exact_cycle_profiles(baselines)
    context_profiles = leave_one_seed_context_profiles(exact_profiles)
    if phase_model_directory is None:
        causal_predictions = None
        phase_quality = {
            "enabled": False,
            "cross_fitted": False,
            "touch_used_for_inference": False,
            "passed": False,
        }
    else:
        causal_predictions, phase_quality = load_causal_phase_predictions(
            traces,
            phase_model_directory,
        )
    rows = []
    skipped = []
    for pulse in pulses:
        key = (
            scalar(pulse, "motion_id", int),
            scalar(pulse, "seed", int),
        )
        baseline = baselines.get(key)
        if baseline is None:
            skipped.append({"path": pulse["path"], "reason": "missing_baseline"})
            continue
        if not scalar(pulse, "success", bool):
            skipped.append({"path": pulse["path"], "reason": "failed_episode"})
            continue
        try:
            rows.append(
                analyze_intervention(
                    baseline,
                    pulse,
                    activation_profile=profiles[key[0]],
                    context_profile=context_profiles[
                        (
                            key[0],
                            key[1],
                            int(trace_phase(baseline).cycle_id[
                                scalar(pulse, "pulse_start_step", int)
                            ]),
                        )
                    ],
                    exact_context_profile=exact_profiles[
                        (
                            key[0],
                            key[1],
                            int(trace_phase(baseline).cycle_id[
                                scalar(pulse, "pulse_start_step", int)
                            ]),
                        )
                    ],
                    causal_prediction=(
                        None
                        if causal_predictions is None
                        else causal_predictions[pulse["path"]]
                    ),
                )
            )
        except (ValueError, FloatingPointError) as error:
            skipped.append({"path": pulse["path"], "reason": str(error)})

    if not rows:
        raise RuntimeError("No valid paired pulse interventions were analyzed.")

    metric_names = (
        "same_state_score",
        "time_aligned_score",
        "phase_aligned_score",
        "pooled_phase_aligned_score",
        "context_phase_aligned_score",
        "causal_exact_context_score",
        "causal_loso_context_score",
    )
    pulse_phase_errors = np.asarray(
        [
            abs(
                (
                    row["reference_phase_at_pulse"]
                    - row["target_phase"]
                    + 0.5
                )
                % 1.0
                - 0.5
            )
            for row in rows
        ],
        dtype=np.float64,
    )
    body_reference_phase_errors = np.asarray(
        [
            abs(
                (
                    row["actual_phase_at_pulse"]
                    - row["reference_phase_at_pulse"]
                    + 0.5
                )
                % 1.0
                - 0.5
            )
            for row in rows
        ],
        dtype=np.float64,
    )
    causal_phase_errors = np.asarray(
        [
            abs(
                (
                    row["causal_phase_at_pulse"]
                    - row["actual_phase_at_pulse"]
                    + 0.5
                )
                % 1.0
                - 0.5
            )
            for row in rows
        ],
        dtype=np.float64,
    )
    report = {
        "schema_version": 2,
        "trace_directory": str(trace_directory.resolve()),
        "intervention_count": len(rows),
        "skipped_count": len(skipped),
        "analyzed_coverage": len(rows) / max(len(rows) + len(skipped), 1),
        "deadband": deadband,
        "causal_phase": phase_quality,
        "pulse_phase_alignment": {
            "mean_absolute_cycle_error": float(np.mean(pulse_phase_errors)),
            "maximum_absolute_cycle_error": float(np.max(pulse_phase_errors)),
            "mean_actual_reference_cycle_difference": float(
                np.mean(body_reference_phase_errors)
            ),
            "maximum_actual_reference_cycle_difference": float(
                np.max(body_reference_phase_errors)
            ),
            "mean_causal_oracle_cycle_difference": float(
                np.mean(causal_phase_errors)
            ),
            "maximum_causal_oracle_cycle_difference": float(
                np.max(causal_phase_errors)
            ),
        },
        "consistency": baseline_consistency(
            baselines,
            profiles,
            exact_profiles,
            context_profiles,
            causal_predictions,
        ),
        "ranking": {
            name: metric_summary(rows, name, deadband=deadband)
            for name in metric_names
        },
        "learnability": {
            name: learnability_summary(rows, name)
            for name in metric_names
        },
        "interventions": rows,
        "skipped": skipped,
    }
    report["state_conditioned_probe"] = state_conditioned_probe(
        rows,
        deadband=deadband,
    )
    report["learnability"]["ground_truth_activation_saving"] = (
        learnability_summary(rows, "ground_truth_activation_saving")
    )
    report["learnability_by_pulse_magnitude"] = {
        f"{magnitude:g}": {
            name: learnability_summary(
                [row for row in rows if abs(row["pulse_nm"]) == magnitude],
                name,
            )
            for name in (
                "ground_truth_activation_saving",
                "same_state_score",
                "time_aligned_score",
                "context_phase_aligned_score",
                "causal_loso_context_score",
            )
        }
        for magnitude in sorted({abs(row["pulse_nm"]) for row in rows})
    }
    oracle_phase_ranking = report["ranking"]["phase_aligned_score"]
    pooled_phase_ranking = report["ranking"]["pooled_phase_aligned_score"]
    context_phase_ranking = report["ranking"]["context_phase_aligned_score"]
    causal_context_ranking = report["ranking"]["causal_loso_context_score"]
    phase_learning = report["learnability"]["causal_loso_context_score"]
    physical_learning = report["learnability"][
        "ground_truth_activation_saving"
    ]
    coverage = len(rows) / max(len(rows) + len(skipped), 1)
    report["decision"] = {
        "coverage_passed": bool(coverage >= 0.8),
        "pulse_timing_passed": bool(
            report["pulse_phase_alignment"][
                "maximum_absolute_cycle_error"
            ]
            <= 0.05
        ),
        "consistency_passed": bool(
            report["consistency"][
                "maximum_absolute_paired_zero_assist_score"
            ]
            <= 0.01
        ),
        "pooled_baseline_noise_passed": bool(
            report["consistency"]["pooled_zero_assist_score_rms"] <= 0.05
        ),
        "context_baseline_noise_passed": bool(
            report["consistency"]["context_zero_assist_score_rms"] <= 0.05
        ),
        "causal_phase_accuracy_passed": bool(phase_quality["passed"]),
        "causal_context_baseline_noise_passed": bool(
            report["consistency"]["causal_loso_zero_assist_score_rms"]
            <= 0.05
        ),
        "paired_oracle_identity_passed": bool(
            np.isfinite(oracle_phase_ranking["spearman"])
            and oracle_phase_ranking["spearman"] >= 0.6
            and np.isfinite(oracle_phase_ranking["sign_agreement"])
            and oracle_phase_ranking["sign_agreement"] >= 0.7
        ),
        "pooled_ranking_passed": bool(
            np.isfinite(pooled_phase_ranking["spearman"])
            and pooled_phase_ranking["spearman"] >= 0.6
            and np.isfinite(pooled_phase_ranking["sign_agreement"])
            and pooled_phase_ranking["sign_agreement"] >= 0.7
        ),
        "context_ranking_passed": bool(
            np.isfinite(context_phase_ranking["spearman"])
            and context_phase_ranking["spearman"] >= 0.6
            and np.isfinite(context_phase_ranking["sign_agreement"])
            and context_phase_ranking["sign_agreement"] >= 0.7
        ),
        "causal_context_ranking_passed": bool(
            np.isfinite(causal_context_ranking["spearman"])
            and causal_context_ranking["spearman"] >= 0.6
            and np.isfinite(causal_context_ranking["sign_agreement"])
            and causal_context_ranking["sign_agreement"] >= 0.7
        ),
        "phase_only_action_effect_passed": bool(
            physical_learning["groups_with_multiple_seeds"] >= 2
            and np.isfinite(
                physical_learning["action_to_seed_variance_ratio"]
            )
            and physical_learning["action_to_seed_variance_ratio"] >= 1.0
        ),
        "context_reward_signal_passed": bool(
            phase_learning["groups_with_multiple_seeds"] >= 2
            and np.isfinite(phase_learning["action_to_seed_variance_ratio"])
            and phase_learning["action_to_seed_variance_ratio"] >= 1.0
        ),
        "state_conditioned_probe_passed": bool(
            report["state_conditioned_probe"].get("available", False)
            and report["state_conditioned_probe"].get(
                "leave_one_seed_out_r2", float("-inf")
            )
            > 0.0
            and report["state_conditioned_probe"].get(
                "sign_agreement", 0.0
            )
            >= 0.7
        ),
    }
    report["decision"]["action_structure_passed"] = bool(
        report["decision"]["phase_only_action_effect_passed"]
        or report["decision"]["state_conditioned_probe_passed"]
    )
    required_for_ppo = (
        "coverage_passed",
        "pulse_timing_passed",
        "consistency_passed",
        "causal_phase_accuracy_passed",
        "causal_context_baseline_noise_passed",
        "paired_oracle_identity_passed",
        "causal_context_ranking_passed",
        "context_reward_signal_passed",
        "action_structure_passed",
    )
    report["decision"]["ready_for_short_ppo_ab"] = bool(
        all(report["decision"][name] for name in required_for_ppo)
    )
    return safe_json(report)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--traces", type=Path, default=DEFAULT_TRACE_DIR)
    parser.add_argument("--deadband", type=float, default=0.005)
    parser.add_argument(
        "--phase-model-dir",
        type=Path,
        default=None,
        help="Directory containing leave-one-seed-out causal phase checkpoints.",
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args()
    if args.deadband < 0.0:
        raise ValueError("deadband must be nonnegative.")

    report = analyze_directory(
        args.traces,
        deadband=args.deadband,
        phase_model_directory=args.phase_model_dir,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(report, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    print("interventions:", report["intervention_count"])
    print("skipped:", report["skipped_count"])
    for name, metrics in report["ranking"].items():
        print(
            f"{name:20s} spearman={metrics['spearman']} "
            f"sign={metrics['sign_agreement']} "
            f"mae={metrics['mean_absolute_error']}"
        )
    print("decision:", report["decision"])
    print("report:", args.output.resolve())


if __name__ == "__main__":
    main()
