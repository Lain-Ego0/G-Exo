"""Calibrate the frozen Phase 1/2 TCN for the MyoAssist physical plant."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

import numpy as np
import torch

from RL.env.actor_observation import RESET_PROTOCOL, RESET_WARMUP_STEPS
from RL.env.myoassist.human_adaptation import make_human_adaptation_env
from RL.env.myoassist.model_builder import DEFAULT_PHYSICAL_OUTPUT_PATH
from RL.env.myoassist.policy_transfer import FrozenHumanPolicy, file_sha256
from RL.env.myoassist.sensor_adapter import MyoAssistSensorAdapter
from RL.env.sensors import SensorReader
from RL.runners.predictors.tcn_calibration import (
    collect_raw_delta_features,
    distribution_metrics,
    fit_feature_normalization,
    fit_imu_rotations,
    fit_motor_input_calibration,
    fit_output_calibration,
)
from RL.runners.predictors.tcn_runtime import FrozenTCNRuntime


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TCN_CHECKPOINT = PROJECT_ROOT / "RL/outputs/tcn_runs/seed_43/best_model.pt"
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/assets/tcn/myoassist_phase12_calibration.json"
LOCAL_PHASE_ROOT = PROJECT_ROOT / "tmp/tcn50_variable_speed_smoke/train"
VERIFIED_SPEEDS_M_S = (0.8, 1.0, 1.25)


def load_phase_inputs(root: Path) -> np.ndarray:
    paths = sorted(root.glob("*/*.npz"))
    if not paths:
        raise FileNotFoundError(f"No Phase 1/2 training NPZ files in {root}")
    frames: list[np.ndarray] = []
    for path in paths:
        with np.load(path) as data:
            inputs = np.asarray(data["input"], dtype=np.float64)
            valid = np.asarray(data["input_valid"], dtype=bool)
            if inputs.ndim != 2 or inputs.shape[1] != 32:
                raise ValueError(f"Invalid TCN input shape in {path}: {inputs.shape}.")
            if valid.shape != (len(inputs),):
                raise ValueError(f"Invalid TCN validity mask in {path}: {valid.shape}.")
            frames.append(inputs[valid])
    result = np.concatenate(frames)
    if len(result) == 0 or not np.all(np.isfinite(result)):
        raise ValueError("Phase 1/2 training inputs contain no finite valid frames.")
    return result


def load_checkpoint_input_moments(checkpoint: Path) -> np.ndarray:
    """Reconstruct the exact per-channel moments stored by TCN pretraining."""

    try:
        payload = torch.load(checkpoint, map_location="cpu", weights_only=False)
    except TypeError:
        payload = torch.load(checkpoint, map_location="cpu")
    statistics = payload.get("statistics")
    if not isinstance(statistics, dict):
        raise ValueError("TCN checkpoint has no training statistics.")
    mean = np.asarray(statistics.get("input_mean"), dtype=np.float64)
    std = np.asarray(statistics.get("input_std"), dtype=np.float64)
    if (
        mean.shape != (32,)
        or std.shape != (32,)
        or not np.all(np.isfinite(mean))
        or not np.all(np.isfinite(std))
        or np.any(std <= 0.0)
    ):
        raise ValueError("TCN checkpoint input statistics are invalid.")
    return np.stack((mean - std, mean + std))


def resolve_phase_inputs(
    requested_root: Path | None,
    checkpoint: Path,
) -> tuple[np.ndarray, str, str | None]:
    """Load raw train frames when available, otherwise use frozen moments."""

    if requested_root is not None:
        root = requested_root.expanduser().resolve(strict=True)
        return load_phase_inputs(root), "explicit_phase_train_npz", str(root)

    candidates: list[tuple[str, Path]] = []
    data_root = os.environ.get("GEXO_DATA_ROOT")
    if data_root:
        candidates.append(
            (
                "gexo_data_root_phase_train_npz",
                Path(data_root).expanduser() / "processed/tcn50/train",
            )
        )
    candidates.append(("local_phase_train_npz", LOCAL_PHASE_ROOT))
    for source, candidate in candidates:
        if candidate.is_dir() and any(candidate.glob("*/*.npz")):
            root = candidate.resolve()
            return load_phase_inputs(root), source, str(root)

    return (
        load_checkpoint_input_moments(checkpoint),
        "checkpoint_frozen_input_mean_std",
        None,
    )


def collect_zero_assist_trajectories(
    human_checkpoint: Path,
    *,
    speeds: tuple[float, ...],
    seeds: tuple[int, ...],
    reference_indices: tuple[int, ...],
    warmup_steps: int,
    steps: int,
    device: str,
) -> tuple[list[np.ndarray], list[dict[str, object]]]:
    policy = FrozenHumanPolicy(human_checkpoint, device=device)
    backend_sensor = MyoAssistSensorAdapter()
    sensor_reader = SensorReader()
    trajectories: list[np.ndarray] = []
    episodes: list[dict[str, object]] = []

    for speed in speeds:
        for seed in seeds:
            for reference_index in reference_indices:
                environment = make_human_adaptation_env(
                    seed=seed,
                    max_episode_steps=warmup_steps + steps,
                    evaluate=True,
                )
                frames: list[np.ndarray] = []
                reason = "time_limit"
                try:
                    observation, _ = environment.reset(
                        seed=seed,
                        options={
                            "target_speed": speed,
                            "reference_index": reference_index,
                        },
                    )
                    sensor_reader.reset(seed=seed)
                    warmup_complete = True
                    for _ in range(warmup_steps):
                        observation, _, terminated, truncated, _ = environment.step(
                            policy(observation)
                        )
                        if terminated or truncated:
                            reason = "warmup_failed"
                            warmup_complete = False
                            break
                    if warmup_complete:
                        frames.append(
                            sensor_reader.read_runtime32(
                                state=backend_sensor.read_state(environment.unwrapped)
                            )
                        )
                        for _ in range(steps):
                            observation, _, terminated, truncated, _ = environment.step(
                                policy(observation)
                            )
                            frames.append(
                                sensor_reader.read_runtime32(
                                    state=backend_sensor.read_state(environment.unwrapped)
                                )
                            )
                            if terminated:
                                reason = "terminated"
                                break
                            if truncated:
                                break
                finally:
                    environment.close()
                complete = len(frames) == steps + 1 and reason == "time_limit"
                row = {
                    "speed_m_s": speed,
                    "seed": seed,
                    "reference_index": reference_index,
                    "frames": len(frames),
                    "warmup_steps": warmup_steps,
                    "complete": complete,
                    "reason": reason,
                }
                episodes.append(row)
                if complete:
                    trajectories.append(np.stack(frames).astype(np.float64))
    if not trajectories:
        raise RuntimeError("No complete zero-assist trajectory was collected.")
    completed_speeds = {
        float(row["speed_m_s"])
        for row in episodes
        if bool(row["complete"])
    }
    missing_speeds = [speed for speed in speeds if speed not in completed_speeds]
    if missing_speeds:
        raise RuntimeError(
            "No complete canonical TCN calibration trajectory at speeds: "
            f"{missing_speeds}."
        )
    return trajectories, episodes


def make_runtime(
    checkpoint: Path,
    *,
    device: str,
    motor_scale: np.ndarray,
    motor_offset: np.ndarray,
    velocity_scale: np.ndarray,
    imu_rotation: np.ndarray,
    target_scale: np.ndarray | None = None,
    target_offset: np.ndarray | None = None,
) -> FrozenTCNRuntime:
    return FrozenTCNRuntime(
        checkpoint,
        device=device,
        motor_position_scale=motor_scale,
        motor_position_offset=motor_offset,
        motor_velocity_scale=velocity_scale,
        imu_rotation=imu_rotation,
        target_position_scale=target_scale,
        target_position_offset=target_offset,
        target_velocity_scale=target_scale,
        feature_mean=np.zeros(16, dtype=np.float32),
        feature_std=np.ones(16, dtype=np.float32),
        feature_clip=5.0,
        allow_legacy_checkpoint=True,
    )


def parse_csv(value: str, conversion) -> tuple:
    return tuple(conversion(item.strip()) for item in value.split(",") if item.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--human-checkpoint", type=Path, required=True)
    parser.add_argument("--tcn-checkpoint", type=Path, default=DEFAULT_TCN_CHECKPOINT)
    parser.add_argument("--phase-root", type=Path)
    parser.add_argument("--speeds", default="0.8,1.0,1.25")
    parser.add_argument("--seeds", default="0")
    parser.add_argument("--reference-indices", default="0")
    parser.add_argument(
        "--warmup-steps",
        type=int,
        default=RESET_WARMUP_STEPS,
    )
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    human_checkpoint = args.human_checkpoint.expanduser().resolve(strict=True)
    tcn_checkpoint = args.tcn_checkpoint.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Calibration already exists: {output}")
    if args.steps < 60:
        raise ValueError("Calibration trajectories need at least 60 control steps.")
    if args.warmup_steps != RESET_WARMUP_STEPS:
        raise ValueError(
            "TCN protocol requires exactly "
            f"{RESET_WARMUP_STEPS} warmup steps."
        )

    speeds = parse_csv(args.speeds, float)
    seeds = parse_csv(args.seeds, int)
    reference_indices = parse_csv(args.reference_indices, int)
    if not speeds or not seeds or reference_indices != (0,):
        raise ValueError(
            "Formal TCN calibration requires non-empty speeds/seeds and "
            "canonical reference-indices=0."
        )
    if any(speed not in VERIFIED_SPEEDS_M_S for speed in speeds):
        raise ValueError(
            "Formal TCN calibration speeds must be selected from the verified "
            f"set {VERIFIED_SPEEDS_M_S}."
        )
    phase_inputs, phase_source, phase_root = resolve_phase_inputs(
        args.phase_root,
        tcn_checkpoint,
    )
    trajectories, episodes = collect_zero_assist_trajectories(
        human_checkpoint,
        speeds=speeds,
        seeds=seeds,
        reference_indices=reference_indices,
        warmup_steps=args.warmup_steps,
        steps=args.steps,
        device=args.device,
    )
    runtime_frames = np.concatenate(trajectories)
    motor_scale, motor_offset, velocity_scale = fit_motor_input_calibration(
        phase_inputs,
        runtime_frames,
    )
    imu_rotation, imu_diagnostics = fit_imu_rotations(
        phase_inputs,
        runtime_frames,
    )
    input_runtime = make_runtime(
        tcn_checkpoint,
        device=args.device,
        motor_scale=motor_scale,
        motor_offset=motor_offset,
        velocity_scale=velocity_scale,
        imu_rotation=imu_rotation,
    )
    target_scale, target_offset, target_velocity_scale, output_diagnostics = (
        fit_output_calibration(trajectories, input_runtime)
    )
    calibrated_runtime = make_runtime(
        tcn_checkpoint,
        device=args.device,
        motor_scale=motor_scale,
        motor_offset=motor_offset,
        velocity_scale=velocity_scale,
        imu_rotation=imu_rotation,
        target_scale=target_scale,
        target_offset=target_offset,
    )
    raw_features = collect_raw_delta_features(trajectories, calibrated_runtime)
    feature_normalization = fit_feature_normalization(raw_features)
    calibrated_input = np.stack(
        [calibrated_runtime.to_tcn_order(frame) for frame in runtime_frames]
    )
    input_z = (
        calibrated_input - calibrated_runtime.input_mean
    ) / calibrated_runtime.input_std

    calibration = {
        "schema_version": 1,
        "protocol": "gexo_myoassist_phase12_tcn_calibration_v1",
        "method": "train_phase_input_moments_and_direct_zero_assist_output_affine",
        "tcn_checkpoint": str(tcn_checkpoint),
        "tcn_checkpoint_sha256": file_sha256(tcn_checkpoint),
        "human_checkpoint": str(human_checkpoint),
        "human_checkpoint_sha256": file_sha256(human_checkpoint),
        "physical_model": str(DEFAULT_PHYSICAL_OUTPUT_PATH.resolve(strict=True)),
        "physical_model_sha256": file_sha256(DEFAULT_PHYSICAL_OUTPUT_PATH),
        "phase_input_source": phase_source,
        "phase_root": phase_root,
        "verified_speed_set_m_s": list(VERIFIED_SPEEDS_M_S),
        "input": {
            "motor_position_scale": motor_scale.tolist(),
            "motor_position_offset": motor_offset.tolist(),
            "motor_velocity_scale": velocity_scale.tolist(),
            "imu_rotation": imu_rotation.tolist(),
        },
        "output": {
            "target_position_scale": target_scale.tolist(),
            "target_position_offset": target_offset.tolist(),
            "target_velocity_scale": target_velocity_scale.tolist(),
        },
        "actor_feature_normalization": {
            **feature_normalization,
            "source": "myoassist_zero_assist_complete_rollouts",
        },
        "fit": {
            "phase_frames": int(len(phase_inputs)),
            "runtime_frames": int(len(runtime_frames)),
            "complete_trajectories": len(trajectories),
            "episodes": episodes,
            "reset_state_contract": "canonical_full_state_v1",
            "warmup_protocol": RESET_PROTOCOL,
            "warmup_steps": args.warmup_steps,
            "imu_rotation_cost": imu_diagnostics,
            "direct_tcn_to_myoassist": output_diagnostics,
            "calibrated_input_distribution": distribution_metrics(input_z),
        },
        "urdf_enabled": False,
        "domain_randomization_enabled": False,
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(
        json.dumps(calibration, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"complete trajectories: {len(trajectories)}")
    print(f"input distribution: {distribution_metrics(input_z)}")
    print(f"calibration: {output}")


if __name__ == "__main__":
    main()
