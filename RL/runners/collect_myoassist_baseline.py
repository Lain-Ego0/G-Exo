"""Collect the frozen-human, zero-assist baseline required before Exo PPO."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mujoco
import numpy as np

from RL.env.actor_observation import RESET_PROTOCOL, RESET_WARMUP_STEPS
from RL.env.myoassist.baseline import (
    NAKED_REFERENCE_CONDITION,
    PHASE_BIN_COUNT,
    SPEED_WINDOW_STEPS,
    ForwardSpeedWindow,
    fit_baseline,
)
from RL.env.myoassist.human_adaptation import make_human_adaptation_env
from RL.env.myoassist.gait_phase import CausalGaitPhase, left_foot_force
from RL.env.myoassist.muscle_adapter import (
    ACTIVATION_SIDE_ORDER,
    MyoAssistMuscleAdapter,
)
from RL.env.myoassist.model_builder import DEFAULT_PHYSICAL_OUTPUT_PATH
from RL.env.myoassist.policy_transfer import FrozenHumanPolicy, file_sha256
from RL.env.myoassist.sensor_adapter import JOINT_SPECS, MyoAssistSensorAdapter
from RL.env.myoassist.urdf_attachment import model_has_gexo_urdf


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/assets/myoassist/zero_assist_baseline.json"
VERIFIED_SPEEDS_M_S = (0.8, 1.0, 1.25)


def parse_csv(value: str, conversion) -> tuple:
    return tuple(conversion(item.strip()) for item in value.split(",") if item.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--human-checkpoint", type=Path, required=True)
    parser.add_argument(
        "--physical-model",
        type=Path,
        default=DEFAULT_PHYSICAL_OUTPUT_PATH,
    )
    parser.add_argument("--speeds", default="0.8,1.0,1.25")
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--reference-indices", default="0")
    parser.add_argument(
        "--warmup-steps",
        type=int,
        default=RESET_WARMUP_STEPS,
    )
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    checkpoint = args.human_checkpoint.expanduser().resolve(strict=True)
    physical_model = args.physical_model.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    if output.suffix.lower() != ".json":
        raise ValueError("Baseline output must use a .json suffix.")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Baseline already exists: {output}")
    if args.warmup_steps != RESET_WARMUP_STEPS:
        raise ValueError(
            "Baseline protocol requires exactly "
            f"{RESET_WARMUP_STEPS} warmup steps."
        )
    if args.steps < 1:
        raise ValueError("steps must be positive.")
    compiled_reference_model = mujoco.MjModel.from_xml_path(str(physical_model))
    if model_has_gexo_urdf(compiled_reference_model):
        raise ValueError("Formal baseline must use the naked-human model without URDF.")
    policy = FrozenHumanPolicy(checkpoint, device=args.device)
    speeds = parse_csv(args.speeds, float)
    seeds = parse_csv(args.seeds, int)
    references = parse_csv(args.reference_indices, int)
    if not speeds or not seeds or references != (0,):
        raise ValueError(
            "Formal baseline requires non-empty speeds/seeds and canonical "
            "reference-indices=0."
        )
    if any(speed not in VERIFIED_SPEEDS_M_S for speed in speeds):
        raise ValueError(
            "Formal baseline speeds must be selected from the verified set "
            f"{VERIFIED_SPEEDS_M_S}."
        )
    rows: dict[str, list] = {
        key: []
        for key in (
            "speed",
            "gait_phase",
            "target_speed_raw",
            "target_speed_filtered",
            "activation",
            "target_activation",
            "human_torque",
            "gross",
            "forward_speed_raw",
            "forward_speed_filtered",
            "pelvis_height",
            "pelvis_pitch",
            "joint_q",
        )
    }
    episode_records: list[dict[str, object]] = []
    joint_lower = joint_upper = None
    model_hash = None

    for speed in speeds:
        complete_for_speed = 0
        for seed in seeds:
            for reference_index in references:
                environment = make_human_adaptation_env(
                    seed=seed,
                    max_episode_steps=args.warmup_steps + args.steps,
                    evaluate=True,
                    model_path=physical_model,
                )
                simulation = environment.unwrapped.sim
                muscle = MyoAssistMuscleAdapter(
                    simulation.model.ptr,
                    simulation.data.ptr,
                    model_hash=file_sha256(physical_model),
                )
                sensors = MyoAssistSensorAdapter()
                observation, _ = environment.reset(
                    seed=seed,
                    options={
                        "target_speed": speed,
                        "reference_index": reference_index,
                    },
                )
                episode: dict[str, list] = {key: [] for key in rows}
                terminated = False
                truncated = False
                warmup_complete = True
                speed_window = ForwardSpeedWindow(SPEED_WINDOW_STEPS)
                target_speed_window = ForwardSpeedWindow(SPEED_WINDOW_STEPS)
                phase_tracker = CausalGaitPhase()
                try:
                    for _ in range(args.warmup_steps):
                        observation, _, terminated, truncated, _ = environment.step(
                            policy(observation)
                        )
                        if terminated or truncated:
                            warmup_complete = False
                            break
                        speed_window.append(
                            simulation.data.joint("pelvis_tx").qvel[0]
                        )
                        target_speed_window.append(
                            environment.unwrapped._target_velocity
                        )
                        phase_tracker.update(left_foot_force(environment.unwrapped))

                    if warmup_complete:
                        if not speed_window.full or not target_speed_window.full:
                            raise RuntimeError(
                                "Actual/target speed windows were not fully seeded "
                                "by preroll."
                            )
                        if not phase_tracker.ready:
                            raise RuntimeError(
                                "Gait phase was not calibrated by zero-assist preroll."
                            )
                        for _ in range(args.steps):
                            observation, _, terminated, truncated, _ = environment.step(
                                policy(observation)
                            )
                            snapshot = muscle.snapshot()
                            state = sensors.read_state(environment.unwrapped)
                            contribution = (
                                snapshot.moment_arm_m
                                * snapshot.resolved_muscle_force_n()[:, None]
                            )
                            raw_target_speed = float(
                                environment.unwrapped._target_velocity
                            )
                            filtered_target_speed = target_speed_window.append(
                                raw_target_speed
                            )
                            gait_phase = phase_tracker.update(
                                left_foot_force(environment.unwrapped)
                            )
                            episode["speed"].append(filtered_target_speed)
                            episode["gait_phase"].append(gait_phase)
                            episode["target_speed_raw"].append(raw_target_speed)
                            episode["target_speed_filtered"].append(
                                filtered_target_speed
                            )
                            episode["activation"].append(
                                float(np.mean(np.square(snapshot.activation)))
                            )
                            squared_activation = np.square(snapshot.activation)
                            episode["target_activation"].append(
                                np.asarray(
                                    [
                                        np.mean(squared_activation[mask])
                                        for mask in muscle.target_activation_masks
                                    ],
                                    dtype=np.float64,
                                )
                            )
                            episode["human_torque"].append(
                                np.sum(contribution, axis=0)
                            )
                            episode["gross"].append(
                                np.sum(np.abs(contribution), axis=0)
                            )
                            raw_speed = float(
                                simulation.data.joint("pelvis_tx").qvel[0]
                            )
                            episode["forward_speed_raw"].append(raw_speed)
                            episode["forward_speed_filtered"].append(
                                speed_window.append(raw_speed)
                            )
                            episode["pelvis_height"].append(
                                float(simulation.data.joint("pelvis_ty").qpos[0])
                            )
                            episode["pelvis_pitch"].append(
                                float(simulation.data.joint("pelvis_tilt").qpos[0])
                            )
                            episode["joint_q"].append(state["motor_q"])
                            if terminated or truncated:
                                break
                finally:
                    environment.close()
                complete = (
                    warmup_complete
                    and len(episode["speed"]) == args.steps
                    and not terminated
                )
                episode_records.append(
                    {
                        "speed_m_s": speed,
                        "seed": seed,
                        "reference_index": reference_index,
                        "steps": len(episode["speed"]),
                        "warmup_steps": args.warmup_steps,
                        "warmup_complete": warmup_complete,
                        "complete": complete,
                    }
                )
                if complete:
                    complete_for_speed += 1
                    for key in rows:
                        rows[key].extend(episode[key])
                if joint_lower is None:
                    model = muscle.model
                    bounds = []
                    for spec in JOINT_SPECS:
                        raw = np.asarray(model.joint(spec.name).range, dtype=np.float64)
                        converted = np.sort(raw * spec.sign)
                        bounds.append(converted)
                    joint_lower = np.asarray(bounds)[:, 0]
                    joint_upper = np.asarray(bounds)[:, 1]
                    model_hash = muscle.model_hash
        if complete_for_speed == 0:
            raise RuntimeError(f"No complete zero-assist baseline at {speed} m/s.")

    target_speed = np.asarray(rows["speed"], dtype=np.float64)
    raw_target_speed = np.asarray(
        rows["target_speed_raw"],
        dtype=np.float64,
    )
    raw_speed = np.asarray(rows["forward_speed_raw"], dtype=np.float64)
    filtered_speed = np.asarray(
        rows["forward_speed_filtered"],
        dtype=np.float64,
    )
    raw_speed_error = np.abs(raw_speed - raw_target_speed)
    filtered_speed_error = np.abs(filtered_speed - target_speed)
    per_speed_diagnostics = []
    for speed in np.unique(target_speed):
        mask = np.isclose(target_speed, speed, rtol=0.0, atol=1.0e-9)
        raw_error_at_speed = raw_speed_error[mask]
        filtered_error_at_speed = filtered_speed_error[mask]
        per_speed_diagnostics.append(
            {
                "target_speed_m_s": float(speed),
                "frames": int(np.count_nonzero(mask)),
                "raw_abs_error_mean_m_s": float(np.mean(raw_error_at_speed)),
                "raw_abs_error_p95_m_s": float(
                    np.percentile(raw_error_at_speed, 95.0)
                ),
                "filtered_abs_error_mean_m_s": float(
                    np.mean(filtered_error_at_speed)
                ),
                "filtered_abs_error_p95_m_s": float(
                    np.percentile(filtered_error_at_speed, 95.0)
                ),
                "filtered_abs_error_std_m_s": float(
                    np.std(filtered_error_at_speed)
                ),
                "transition_m_s": max(
                    float(np.std(filtered_error_at_speed)),
                    0.1,
                ),
            }
        )
    baseline = fit_baseline(
        speed_m_s=target_speed,
        gait_phase=np.asarray(rows["gait_phase"]),
        activation_cost=np.asarray(rows["activation"]),
        target_activation_cost=np.asarray(rows["target_activation"]),
        human_joint_torque_nm=np.asarray(rows["human_torque"]),
        gross_joint_load_nm=np.asarray(rows["gross"]),
        forward_speed_filtered_m_s=filtered_speed,
        pelvis_height_m=np.asarray(rows["pelvis_height"]),
        pelvis_pitch_rad=np.asarray(rows["pelvis_pitch"]),
        joint_q_rad=np.asarray(rows["joint_q"]),
        joint_lower_rad=joint_lower,
        joint_upper_rad=joint_upper,
        metadata={
            "human_checkpoint": str(checkpoint),
            "human_checkpoint_sha256": file_sha256(checkpoint),
            "physical_model": str(physical_model),
            "model_sha256": model_hash,
            "reference_model_sha256": model_hash,
            "physiology_signature": muscle.physiology_signature,
            "reference_condition": NAKED_REFERENCE_CONDITION,
            "baseline_split": "canonical_naked_human_training_v1",
            "verified_speed_set_m_s": list(speeds),
            "episodes": episode_records,
            "frames": len(rows["speed"]),
            "control_hz": 50,
            "reset_state_contract": "canonical_full_state_v1",
            "warmup_protocol": RESET_PROTOCOL,
            "warmup_steps": args.warmup_steps,
            "speed_window_steps": SPEED_WINDOW_STEPS,
            "gait_phase": {
                "kind": "causal_left_foot_contact_v1",
                "phase_zero": "stable_left_foot_contact",
                "future_frames_used": 0,
                "phase_bin_count": PHASE_BIN_COUNT,
            },
            "speed_filter": {
                "kind": "causal_rolling_mean",
                "window_steps": SPEED_WINDOW_STEPS,
                "seed": "exact_zero_assist_preroll",
                "reward_signal": "forward_speed_filtered",
                "raw_signal": "forward_speed_raw",
                "target_reward_signal": "target_speed_filtered",
                "target_raw_signal": "target_speed_raw",
                "comparison": "filtered_actual_minus_filtered_target",
            },
            "speed_diagnostics": {
                "raw_abs_error_mean_m_s": float(np.mean(raw_speed_error)),
                "raw_abs_error_p95_m_s": float(
                    np.percentile(raw_speed_error, 95.0)
                ),
                "filtered_abs_error_mean_m_s": float(
                    np.mean(filtered_speed_error)
                ),
                "filtered_abs_error_p95_m_s": float(
                    np.percentile(filtered_speed_error, 95.0)
                ),
                "per_speed": per_speed_diagnostics,
            },
            "statistics": {
                "center": "mean_activation_mean_human_torque_median_gross",
                "minimum_scale_fraction": 0.05,
                "minimum_scale": 1.0e-6,
                "speed_free_error_percentile": 95.0,
                "speed_threshold_scope": "per_speed_bin_with_interpolation",
                "speed_threshold_source": (
                    "forward_speed_filtered_minus_target_speed_filtered"
                ),
                "minimum_height_percentile": 1.0,
                "pitch_free_percentile": 99.0,
                "joint_envelope_percentiles": [0.1, 99.9],
                "joint_envelope_padding_rad": 0.05,
            },
            "target_activation": {
                "cost": "mean_squared_activation",
                "side_order": list(ACTIVATION_SIDE_ORDER),
                "muscle_names_by_side": {
                    side: [
                        name
                        for name, selected in zip(
                            muscle.muscle_names,
                            muscle.target_activation_masks[side_index],
                        )
                        if selected
                    ]
                    for side_index, side in enumerate(ACTIVATION_SIDE_ORDER)
                },
            },
            "urdf_enabled": model_has_gexo_urdf(muscle.model),
            "domain_randomization_enabled": False,
        },
    )
    saved = baseline.save(output)
    raw_output = output.with_suffix(".npz")
    np.savez_compressed(raw_output, **{key: np.asarray(value) for key, value in rows.items()})
    print(f"baseline: {saved}")
    print(f"raw frames: {raw_output}")
    print(f"frames: {len(rows['speed'])}")


if __name__ == "__main__":
    main()
