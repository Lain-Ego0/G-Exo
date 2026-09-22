#!/usr/bin/env python3
"""Export the frozen G-Exo TCN+PD deployment model package and replay."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys

import numpy as np
import onnx
import onnxruntime as ort
import torch
from torch import nn


sys.dont_write_bytecode = True

SCRIPT_PATH = Path(__file__).resolve()
DEPLOY_ROOT = SCRIPT_PATH.parents[1]
REPOSITORY_ROOT = SCRIPT_PATH.parents[4]
RL_ROOT = REPOSITORY_ROOT / "RL"

TCN_INPUT_NAME = "sensor_history"
TCN_OUTPUT_NAME = "prediction"
TCN_INPUT_SHAPE = (1, 32, 50)
TCN_OUTPUT_SHAPE = (1, 2, 12)

JOINT_ORDER = [
    "left_hip",
    "left_knee",
    "right_hip",
    "right_knee",
]
GRAVITY_M_S2 = 9.80665
SENSOR_SCALE32 = np.asarray(
    [np.pi] * 4
    + [20.0] * 4
    + [20.0] * 12
    + [4.0 * GRAVITY_M_S2] * 12,
    dtype=np.float32,
)
SENSOR_CLIP = 5.0
WARMUP_STEPS = 150

SELECTED_HORIZON_STEPS = 5
PREDICTION_FRACTION = 0.2
KP_NM_PER_RAD = np.full(4, 4.0, dtype=np.float32)
KD_NM_S_PER_RAD = np.full(4, 0.2, dtype=np.float32)
ACTION_SCALE_NM = np.full(4, 2.0, dtype=np.float32)
OOD_SOFT_RATIO = 0.6
POSITION_DELTA_LIMIT_RAD = np.full(4, 1.0, dtype=np.float32)
VELOCITY_DELTA_LIMIT_RAD_S = np.full(4, 10.0, dtype=np.float32)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--tcn-checkpoint",
        type=Path,
        default=RL_ROOT / "outputs/tcn_runs/seed_43/best_model.pt",
    )
    parser.add_argument(
        "--tcn-calibration",
        type=Path,
        default=(
            RL_ROOT
            / "assets/tcn/myoassist_phase12_calibration_preroll150.json"
        ),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=DEPLOY_ROOT / "models",
    )
    parser.add_argument(
        "--reference-replay",
        type=Path,
        default=DEPLOY_ROOT / "tests/reference_replay.json",
    )
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def repository_relative(path: Path) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(REPOSITORY_ROOT).as_posix()
    except ValueError:
        return str(resolved)


def load_torch(path: Path) -> object:
    try:
        return torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        return torch.load(path, map_location="cpu")


def require_keys(value: dict, keys: set[str], name: str) -> None:
    missing = keys - set(value)
    if missing:
        raise ValueError(f"{name} is missing keys: {sorted(missing)}")


def finite_vector(value: object, size: int, name: str) -> np.ndarray:
    vector = np.asarray(value, dtype=np.float32)
    if vector.shape != (size,):
        raise ValueError(f"{name} must have shape ({size},), got {vector.shape}")
    if not np.all(np.isfinite(vector)):
        raise ValueError(f"{name} contains NaN or Inf")
    return vector


def positive_vector(value: object, size: int, name: str) -> np.ndarray:
    vector = finite_vector(value, size, name)
    if np.any(vector <= 0.0):
        raise ValueError(f"{name} must be strictly positive")
    return vector


def list32(value: object, size: int, name: str) -> list[float]:
    return finite_vector(value, size, name).tolist()


def build_tcn(checkpoint: dict) -> nn.Module:
    require_keys(
        checkpoint,
        {
            "model_state_dict",
            "input_dim",
            "hidden_dim",
            "target_dim",
            "history",
            "horizons",
            "statistics",
        },
        "TCN checkpoint",
    )
    if int(checkpoint["input_dim"]) != 32:
        raise ValueError("TCN input_dim must be 32")
    if int(checkpoint["target_dim"]) != 12:
        raise ValueError("TCN target_dim must be 12")
    if int(checkpoint["history"]) != 50:
        raise ValueError("TCN history must be 50")
    if tuple(int(item) for item in checkpoint["horizons"]) != (5, 10):
        raise ValueError("TCN horizons must be (5, 10)")

    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    from RL.runners.predictors.tcn import MotionTCN

    model = MotionTCN(
        input_dim=32,
        hidden_dim=int(checkpoint["hidden_dim"]),
        target_dim=12,
        horizon_count=2,
        dropout=float(checkpoint.get("dropout", 0.0)),
        auxiliary_dim=int(checkpoint.get("auxiliary_dim", 0)),
    )
    model.load_state_dict(checkpoint["model_state_dict"], strict=True)
    model.eval()
    model.requires_grad_(False)
    return model


def export_tcn(model: nn.Module, sample: torch.Tensor, output_path: Path) -> None:
    with torch.inference_mode():
        torch.onnx.export(
            model,
            sample,
            output_path,
            export_params=True,
            opset_version=17,
            do_constant_folding=True,
            input_names=[TCN_INPUT_NAME],
            output_names=[TCN_OUTPUT_NAME],
            dynamic_axes=None,
            dynamo=False,
        )


def validate_tcn_interface(model_path: Path) -> ort.InferenceSession:
    model = onnx.load(model_path)
    onnx.checker.check_model(model, full_check=True)
    if len(model.opset_import) != 1 or model.opset_import[0].version != 17:
        raise ValueError("TCN ONNX must use opset 17")

    options = ort.SessionOptions()
    options.intra_op_num_threads = 1
    options.inter_op_num_threads = 1
    session = ort.InferenceSession(
        str(model_path),
        sess_options=options,
        providers=["CPUExecutionProvider"],
    )
    inputs = session.get_inputs()
    outputs = session.get_outputs()
    if len(inputs) != 1 or len(outputs) != 1:
        raise ValueError("TCN ONNX must have exactly one input and one output")
    actual_input = (inputs[0].name, inputs[0].type, tuple(inputs[0].shape))
    expected_input = (TCN_INPUT_NAME, "tensor(float)", TCN_INPUT_SHAPE)
    if actual_input != expected_input:
        raise ValueError(f"TCN input is {actual_input}, expected {expected_input}")
    actual_output = (outputs[0].name, outputs[0].type, tuple(outputs[0].shape))
    expected_output = (TCN_OUTPUT_NAME, "tensor(float)", TCN_OUTPUT_SHAPE)
    if actual_output != expected_output:
        raise ValueError(f"TCN output is {actual_output}, expected {expected_output}")
    return session


def compare_tcn_runtime(
    model: nn.Module,
    session: ort.InferenceSession,
    sample: torch.Tensor,
) -> tuple[float, float]:
    with torch.inference_mode():
        expected = model(sample).cpu().numpy()
    actual = session.run(
        [TCN_OUTPUT_NAME],
        {TCN_INPUT_NAME: sample.cpu().numpy()},
    )[0]
    absolute_error = np.abs(expected - actual)
    maximum_absolute_error = float(absolute_error.max(initial=0.0))
    denominator = np.maximum(np.abs(expected), np.float32(1.0e-7))
    maximum_relative_error = float((absolute_error / denominator).max(initial=0.0))
    np.testing.assert_allclose(actual, expected, rtol=1.0e-5, atol=1.0e-6)
    return maximum_absolute_error, maximum_relative_error


def validate_calibration(calibration: dict, checkpoint_path: Path) -> None:
    if calibration.get("protocol") != "gexo_myoassist_phase12_tcn_calibration_v1":
        raise ValueError("Unsupported TCN calibration protocol")
    if calibration.get("schema_version") != 1:
        raise ValueError("Unsupported TCN calibration schema_version")
    if calibration.get("tcn_checkpoint_sha256") != sha256(checkpoint_path):
        raise ValueError("Calibration TCN checkpoint SHA256 mismatch")
    fit = calibration.get("fit")
    if not isinstance(fit, dict):
        raise ValueError("Calibration lacks fit metadata")
    if fit.get("warmup_steps") != WARMUP_STEPS:
        raise ValueError("Calibration warmup_steps must be 150")
    if fit.get("warmup_protocol") != "gexo_zero_assist_preroll150_v1":
        raise ValueError("Calibration warmup protocol is incompatible")
    if fit.get("reset_state_contract") != "canonical_full_state_v1":
        raise ValueError("Calibration reset-state contract is incompatible")
    if calibration.get("domain_randomization_enabled") is not False:
        raise ValueError("Calibration must disable domain randomization")


def build_config(
    checkpoint: dict,
    calibration: dict,
    tcn_path: Path,
    checkpoint_path: Path,
    calibration_path: Path,
) -> dict[str, object]:
    statistics = checkpoint.get("statistics")
    if not isinstance(statistics, dict):
        raise ValueError("TCN checkpoint lacks statistics")
    require_keys(
        statistics,
        {"input_mean", "input_std", "target_mean", "target_std"},
        "TCN statistics",
    )
    input_calibration = calibration.get("input")
    target_calibration = calibration.get("output")
    feature_normalization = calibration.get("actor_feature_normalization")
    if not all(
        isinstance(value, dict)
        for value in (
            input_calibration,
            target_calibration,
            feature_normalization,
        )
    ):
        raise ValueError("Calibration preprocessing blocks must be objects")
    require_keys(
        input_calibration,
        {
            "motor_position_scale",
            "motor_position_offset",
            "motor_velocity_scale",
            "imu_rotation",
        },
        "TCN input calibration",
    )
    require_keys(
        target_calibration,
        {
            "target_position_scale",
            "target_position_offset",
            "target_velocity_scale",
        },
        "TCN target calibration",
    )
    require_keys(
        feature_normalization,
        {"mean", "std", "clip", "horizon_steps"},
        "TCN delta feature normalization",
    )

    rotation = np.asarray(input_calibration["imu_rotation"], dtype=np.float32)
    if rotation.shape != (4, 3, 3) or not np.all(np.isfinite(rotation)):
        raise ValueError("imu_rotation must be finite with shape (4, 3, 3)")
    for matrix in rotation:
        np.testing.assert_allclose(matrix @ matrix.T, np.eye(3), atol=1.0e-5)
        if not np.isclose(np.linalg.det(matrix), 1.0, atol=1.0e-5):
            raise ValueError("imu_rotation matrices must be proper rotations")

    feature_clip_value = np.asarray(feature_normalization["clip"], dtype=np.float32)
    if feature_clip_value.ndim == 0:
        feature_clip = np.full(16, float(feature_clip_value), dtype=np.float32)
    else:
        feature_clip = positive_vector(feature_clip_value, 16, "feature_clip")
    positive_vector(feature_clip, 16, "feature_clip")
    if tuple(feature_normalization["horizon_steps"]) != (5, 10):
        raise ValueError("Feature normalization horizons must be [5, 10]")

    return {
        "schema": "gexo_tcn_pd_deploy_model_v1",
        "schema_version": 1,
        "warmup_steps": WARMUP_STEPS,
        "control_frequency_hz": 50.0,
        "joint_order": JOINT_ORDER,
        "protocols": {
            "runtime_sensor": "gexo_sensor32_runtime_v1",
            "tcn_sensor": "phase12_tcn32_interleaved_v1",
            "warmup": "gexo_zero_assist_preroll150_v1",
            "calibration": "gexo_myoassist_phase12_tcn_calibration_v1",
        },
        "models": {
            "tcn": {
                "file": tcn_path.name,
                "sha256": sha256(tcn_path),
                "input": {
                    "name": TCN_INPUT_NAME,
                    "dtype": "float32",
                    "shape": list(TCN_INPUT_SHAPE),
                },
                "output": {
                    "name": TCN_OUTPUT_NAME,
                    "dtype": "float32",
                    "shape": list(TCN_OUTPUT_SHAPE),
                },
            }
        },
        "tcn_preprocessing": {
            "history_length": 50,
            "horizon_steps": [5, 10],
            "target_order": ["q4", "dq4", "biological_moment4"],
            "feature_order": [
                "delta_q(+5)",
                "delta_dq(+5)",
                "delta_q(+10)",
                "delta_dq(+10)",
            ],
            "input_mean": list32(statistics["input_mean"], 32, "input_mean"),
            "input_std": positive_vector(
                statistics["input_std"], 32, "input_std"
            ).tolist(),
            "target_mean": list32(statistics["target_mean"], 12, "target_mean"),
            "target_std": positive_vector(
                statistics["target_std"], 12, "target_std"
            ).tolist(),
            "motor_position_scale": list32(
                input_calibration["motor_position_scale"],
                4,
                "motor_position_scale",
            ),
            "motor_position_offset": list32(
                input_calibration["motor_position_offset"],
                4,
                "motor_position_offset",
            ),
            "motor_velocity_scale": list32(
                input_calibration["motor_velocity_scale"],
                4,
                "motor_velocity_scale",
            ),
            "imu_rotation": rotation.tolist(),
            "target_position_scale": list32(
                target_calibration["target_position_scale"],
                4,
                "target_position_scale",
            ),
            "target_position_offset": list32(
                target_calibration["target_position_offset"],
                4,
                "target_position_offset",
            ),
            "target_velocity_scale": list32(
                target_calibration["target_velocity_scale"],
                4,
                "target_velocity_scale",
            ),
            "feature_mean": list32(
                feature_normalization["mean"], 16, "feature_mean"
            ),
            "feature_std": positive_vector(
                feature_normalization["std"], 16, "feature_std"
            ).tolist(),
            "feature_clip": feature_clip.tolist(),
        },
        "sensor_normalization": {
            "order": ["q4", "dq4", "gyro12", "specific_force12"],
            "scale32": SENSOR_SCALE32.tolist(),
            "clip": SENSOR_CLIP,
        },
        "controller": {
            "selected_horizon_steps": SELECTED_HORIZON_STEPS,
            "prediction_fraction": PREDICTION_FRACTION,
            "kp_nm_per_rad": KP_NM_PER_RAD.tolist(),
            "kd_nm_s_per_rad": KD_NM_S_PER_RAD.tolist(),
            "action_scale_nm": ACTION_SCALE_NM.tolist(),
            "disable_on_saturation": True,
            "ood_soft_ratio": OOD_SOFT_RATIO,
            "position_delta_limit_rad": POSITION_DELTA_LIMIT_RAD.tolist(),
            "velocity_delta_limit_rad_s": VELOCITY_DELTA_LIMIT_RAD_S.tolist(),
            "output_clip": [-1.0, 1.0],
        },
        "source": {
            "tcn_checkpoint": {
                "path": repository_relative(checkpoint_path),
                "sha256": sha256(checkpoint_path),
            },
            "tcn_calibration": {
                "path": repository_relative(calibration_path),
                "sha256": sha256(calibration_path),
            },
        },
    }


def deterministic_sensor_frames() -> list[list[float]]:
    """Build 151 reproducible, finite sensor32 frames."""

    frames: list[list[float]] = []
    for frame_index in range(151):
        step = frame_index + 1
        sensor = np.empty(32, dtype=np.float32)
        for joint in range(4):
            sensor[joint] = (
                ((step * (7 + 2 * joint) + 13 * joint) % 101) - 50
            ) * np.float32(0.006)
            sensor[4 + joint] = (
                ((step * (11 + 2 * joint) + 17 * joint) % 121) - 60
            ) * np.float32(0.05)
        for channel in range(12):
            sensor[8 + channel] = (
                ((step * (5 + channel) + 19 * channel) % 81) - 40
            ) * np.float32(0.04)
            acceleration_center = GRAVITY_M_S2 if channel % 3 == 2 else 0.0
            sensor[20 + channel] = np.float32(
                acceleration_center
                + (((step * (3 + channel) + 23 * channel) % 101) - 50)
                * 0.025
            )
        if not np.all(np.isfinite(sensor)):
            raise RuntimeError("Generated reference sensor contains NaN or Inf")
        frames.append(sensor.tolist())
    return frames


def command_diagnostics(command: object) -> dict[str, object]:
    return {
        "action": command.action.astype(np.float32).tolist(),
        "target_torque_nm": command.target_torque_nm.astype(np.float32).tolist(),
        "current_q_rad": command.current_q_rad.astype(np.float32).tolist(),
        "current_dq_rad_s": command.current_dq_rad_s.astype(np.float32).tolist(),
        "predicted_q_rad": command.predicted_q_rad.astype(np.float32).tolist(),
        "predicted_dq_rad_s": command.predicted_dq_rad_s.astype(np.float32).tolist(),
        "reference_q_rad": command.reference_q_rad.astype(np.float32).tolist(),
        "reference_dq_rad_s": command.reference_dq_rad_s.astype(np.float32).tolist(),
        "delta_q_rad": command.delta_q_rad.astype(np.float32).tolist(),
        "delta_dq_rad_s": command.delta_dq_rad_s.astype(np.float32).tolist(),
        "control_delta_q_rad": command.control_delta_q_rad.astype(np.float32).tolist(),
        "control_delta_dq_rad_s": (
            command.control_delta_dq_rad_s.astype(np.float32).tolist()
        ),
        "confidence": float(command.confidence),
        "feature_ood_ratio": float(command.feature_ood_ratio),
        "sensor_ood_ratio": float(command.sensor_ood_ratio),
        "feature_saturated": bool(command.feature_saturated),
        "sensor_saturated": bool(command.sensor_saturated),
        "error_limited": bool(command.error_limited),
        "action_saturated": bool(command.action_saturated),
    }


def compute_reference_result(
    sensor_frames: list[list[float]],
    checkpoint_path: Path,
    calibration_path: Path,
    tcn_session: ort.InferenceSession,
) -> dict[str, object]:
    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    from RL.controllers.tcn_impedance import TCNImpedanceController
    from RL.env.actor_observation import ActorObservationBuilder
    from RL.runners.predictors.tcn_runtime import FrozenTCNRuntime

    if len(sensor_frames) != 151:
        raise ValueError("Reference replay must contain exactly 151 sensor frames")
    tcn_runtime = FrozenTCNRuntime(
        checkpoint_path,
        device="cpu",
        calibration=calibration_path,
        allow_legacy_checkpoint=True,
    )
    actor_frame_scale = np.concatenate(
        (SENSOR_SCALE32, np.ones(4, dtype=np.float32))
    )
    observation_builder = ActorObservationBuilder(
        frame_scale=actor_frame_scale,
        clip=SENSOR_CLIP,
    )
    controller = TCNImpedanceController.from_calibration(
        calibration_path,
        selected_horizon_steps=SELECTED_HORIZON_STEPS,
        kp_nm_per_rad=KP_NM_PER_RAD,
        kd_nm_s_per_rad=KD_NM_S_PER_RAD,
        action_scale_nm=ACTION_SCALE_NM,
        prediction_fraction=PREDICTION_FRACTION,
        disable_on_saturation=True,
        ood_soft_ratio=OOD_SOFT_RATIO,
        position_delta_limit_rad=POSITION_DELTA_LIMIT_RAD,
        velocity_delta_limit_rad_s=VELOCITY_DELTA_LIMIT_RAD_S,
        expected_tcn_checkpoint_sha256=sha256(checkpoint_path),
    )
    expected_metadata = {
        "selected_horizon_steps": SELECTED_HORIZON_STEPS,
        "prediction_fraction": PREDICTION_FRACTION,
        "kp_nm_per_rad": KP_NM_PER_RAD.tolist(),
        "kd_nm_s_per_rad": KD_NM_S_PER_RAD.tolist(),
        "action_scale_nm": ACTION_SCALE_NM.tolist(),
        "disable_on_saturation": True,
        "ood_soft_ratio": OOD_SOFT_RATIO,
        "position_delta_limit_rad": POSITION_DELTA_LIMIT_RAD.tolist(),
        "velocity_delta_limit_rad_s": VELOCITY_DELTA_LIMIT_RAD_S.tolist(),
    }
    metadata = controller.metadata()
    for key, expected_value in expected_metadata.items():
        if metadata[key] != expected_value:
            raise RuntimeError(f"Controller metadata mismatch for {key}")

    normalized_tcn_history: list[np.ndarray] = []
    zero_action = np.zeros(4, dtype=np.float32)
    reference_results: dict[str, object] = {}
    for frame_index, sensor_values in enumerate(sensor_frames):
        step = frame_index + 1
        sensor = finite_vector(sensor_values, 32, "sensor32")
        tcn_runtime.append(sensor)
        normalized_tcn_history.append(tcn_runtime.latest_normalized_frame)
        observation_builder.append(sensor, zero_action)
        if step not in (150, 151):
            continue
        if not tcn_runtime.ready or not observation_builder.ready:
            raise RuntimeError(f"Reference histories are not ready at step {step}")

        tcn_result = tcn_runtime.predict(sensor[:4], sensor[4:8])
        tcn_input = np.stack(normalized_tcn_history[-50:], axis=0).T[None, :, :]
        tcn_onnx = tcn_session.run(
            [TCN_OUTPUT_NAME],
            {TCN_INPUT_NAME: tcn_input.astype(np.float32, copy=False)},
        )[0][0]
        tcn_absolute_error = float(
            np.max(
                np.abs(tcn_onnx - tcn_result.normalized_prediction),
                initial=0.0,
            )
        )
        np.testing.assert_allclose(
            tcn_onnx,
            tcn_result.normalized_prediction,
            rtol=1.0e-5,
            atol=1.0e-6,
        )

        observation = observation_builder.build(tcn_result.feature16)
        command = controller.compute(observation)
        normalized_sensor32 = np.clip(
            sensor / SENSOR_SCALE32,
            -SENSOR_CLIP,
            SENSOR_CLIP,
        ).astype(np.float32)
        diagnostics = command_diagnostics(command)
        diagnostics.update(
            {
                "normalized_sensor32": normalized_sensor32.tolist(),
                "normalized_tcn_prediction": (
                    tcn_result.normalized_prediction.astype(np.float32).tolist()
                ),
                "denormalized_tcn_prediction": (
                    tcn_result.prediction.astype(np.float32).tolist()
                ),
                "joint_prediction": (
                    tcn_result.joint_prediction.astype(np.float32).tolist()
                ),
                "raw_delta16": (
                    tcn_result.raw_delta16.astype(np.float32).tolist()
                ),
                "feature16": tcn_result.feature16.astype(np.float32).tolist(),
                "tcn_python_ort_max_abs_error": tcn_absolute_error,
            }
        )
        reference_results[f"expected_step{step}"] = diagnostics

    if set(reference_results) != {"expected_step150", "expected_step151"}:
        raise RuntimeError("Reference replay did not produce steps 150 and 151")
    return reference_results


def build_reference_fixture(
    sensor_frames: list[list[float]],
    reference_results: dict[str, object],
    config_path: Path,
    tcn_path: Path,
) -> dict[str, object]:
    expected_step150 = reference_results["expected_step150"]
    expected_step151 = reference_results["expected_step151"]
    zero_action = [0.0, 0.0, 0.0, 0.0]
    frames: list[dict[str, object]] = []
    for frame_index, sensor32 in enumerate(sensor_frames):
        step = frame_index + 1
        frames.append(
            {
                "sensor32": sensor32,
                "expected_state": (
                    "WARMUP" if step <= WARMUP_STEPS else "READY"
                ),
                "expected_action": (
                    expected_step151["action"]
                    if step == 151
                    else zero_action
                ),
            }
        )
    return {
        "schema": "gexo_tcn_pd_reference_replay_v1",
        "schema_version": 1,
        "frame_count": 151,
        "warmup_steps": WARMUP_STEPS,
        "expected_zero_action_through_step": WARMUP_STEPS,
        "first_action_step": WARMUP_STEPS + 1,
        "absolute_tolerance": 1.0e-5,
        "frames": frames,
        "expected_step150": expected_step150,
        "expected_step151": expected_step151,
        "model_package": {
            "schema": "gexo_tcn_pd_deploy_model_v1",
            "model_config_sha256": sha256(config_path),
            "tcn_onnx_sha256": sha256(tcn_path),
        },
    }


def validate_reference_structure(fixture: dict[str, object]) -> list[list[float]]:
    if fixture.get("schema") != "gexo_tcn_pd_reference_replay_v1":
        raise ValueError("Unsupported TCN+PD reference replay schema")
    if fixture.get("schema_version") != 1:
        raise ValueError("Unsupported TCN+PD reference replay schema_version")
    if fixture.get("frame_count") != 151 or fixture.get("warmup_steps") != 150:
        raise ValueError("Reference replay must contain 151 frames with warmup 150")
    if fixture.get("first_action_step") != 151:
        raise ValueError("Reference replay first_action_step must be 151")
    if fixture.get("expected_zero_action_through_step") != 150:
        raise ValueError("Reference replay must return zero through step 150")
    frames = fixture.get("frames")
    if not isinstance(frames, list) or len(frames) != 151:
        raise ValueError("Reference replay frames must contain 151 entries")

    sensor_frames: list[list[float]] = []
    for frame_index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise TypeError(f"Reference frame {frame_index} must be an object")
        sensor = finite_vector(frame.get("sensor32"), 32, "sensor32")
        expected_action = finite_vector(
            frame.get("expected_action"), 4, "expected_action"
        )
        expected_state = "WARMUP" if frame_index < WARMUP_STEPS else "READY"
        if frame.get("expected_state") != expected_state:
            raise ValueError(
                f"Reference frame {frame_index + 1} state must be {expected_state}"
            )
        if frame_index < WARMUP_STEPS:
            if not np.array_equal(expected_action, np.zeros(4, dtype=np.float32)):
                raise ValueError("Warmup expected actions must be exactly zero")
        sensor_frames.append(sensor.tolist())

    for step in (151,):
        expected = fixture.get(f"expected_step{step}")
        if not isinstance(expected, dict):
            raise TypeError(f"expected_step{step} must be an object")
        for name in (
            "action",
            "target_torque_nm",
            "current_q_rad",
            "current_dq_rad_s",
            "predicted_q_rad",
            "predicted_dq_rad_s",
            "reference_q_rad",
            "reference_dq_rad_s",
            "delta_q_rad",
            "delta_dq_rad_s",
            "control_delta_q_rad",
            "control_delta_dq_rad_s",
        ):
            finite_vector(expected.get(name), 4, name)
        for name in ("confidence", "feature_ood_ratio", "sensor_ood_ratio"):
            value = float(expected.get(name))
            if not np.isfinite(value):
                raise ValueError(f"{name} must be finite")
        for name in (
            "feature_saturated",
            "sensor_saturated",
            "error_limited",
            "action_saturated",
        ):
            if not isinstance(expected.get(name), bool):
                raise TypeError(f"{name} must be boolean")
    return sensor_frames


def compare_reference_results(
    expected: dict[str, object],
    actual: dict[str, object],
    tolerance: float,
) -> float:
    maximum_error = 0.0
    vector_sizes = {
        "action": 4,
        "target_torque_nm": 4,
        "current_q_rad": 4,
        "current_dq_rad_s": 4,
        "predicted_q_rad": 4,
        "predicted_dq_rad_s": 4,
        "reference_q_rad": 4,
        "reference_dq_rad_s": 4,
        "delta_q_rad": 4,
        "delta_dq_rad_s": 4,
        "control_delta_q_rad": 4,
        "control_delta_dq_rad_s": 4,
        "normalized_sensor32": 32,
        "raw_delta16": 16,
        "feature16": 16,
    }
    for name, size in vector_sizes.items():
        expected_value = finite_vector(expected[name], size, name)
        actual_value = finite_vector(actual[name], size, name)
        maximum_error = max(
            maximum_error,
            float(np.max(np.abs(actual_value - expected_value), initial=0.0)),
        )
        np.testing.assert_allclose(
            actual_value,
            expected_value,
            rtol=0.0,
            atol=tolerance,
        )
    for name in ("confidence", "feature_ood_ratio", "sensor_ood_ratio"):
        error = abs(float(actual[name]) - float(expected[name]))
        maximum_error = max(maximum_error, error)
        if error > tolerance:
            raise AssertionError(f"Reference scalar mismatch for {name}: {error}")
    for name in (
        "feature_saturated",
        "sensor_saturated",
        "error_limited",
        "action_saturated",
    ):
        if bool(actual[name]) != bool(expected[name]):
            raise AssertionError(f"Reference flag mismatch for {name}")
    return maximum_error


def main() -> None:
    args = parse_args()
    checkpoint_path = args.tcn_checkpoint.expanduser().resolve()
    calibration_path = args.tcn_calibration.expanduser().resolve()
    output_directory = args.output_directory.expanduser().resolve()
    reference_replay_path = args.reference_replay.expanduser().resolve()
    for path in (checkpoint_path, calibration_path):
        if not path.is_file():
            raise FileNotFoundError(path)
    output_directory.mkdir(parents=True, exist_ok=True)

    checkpoint = load_torch(checkpoint_path)
    if not isinstance(checkpoint, dict):
        raise TypeError("TCN checkpoint root must be a dictionary")
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if not isinstance(calibration, dict):
        raise TypeError("TCN calibration root must be a dictionary")
    validate_calibration(calibration, checkpoint_path)

    tcn_model = build_tcn(checkpoint)
    sample = torch.randn(
        TCN_INPUT_SHAPE,
        generator=torch.Generator().manual_seed(20260804),
    )
    tcn_path = output_directory / "tcn.onnx"
    export_tcn(tcn_model, sample, tcn_path)
    tcn_session = validate_tcn_interface(tcn_path)
    tcn_error = compare_tcn_runtime(tcn_model, tcn_session, sample)

    config = build_config(
        checkpoint,
        calibration,
        tcn_path,
        checkpoint_path,
        calibration_path,
    )
    config_path = output_directory / "model_config.json"
    config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    sensor_frames = deterministic_sensor_frames()
    reference_results = compute_reference_result(
        sensor_frames,
        checkpoint_path,
        calibration_path,
        tcn_session,
    )
    fixture = build_reference_fixture(
        sensor_frames,
        reference_results,
        config_path,
        tcn_path,
    )
    reference_replay_path.parent.mkdir(parents=True, exist_ok=True)
    reference_replay_path.write_text(
        json.dumps(fixture, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    loaded_fixture = json.loads(reference_replay_path.read_text(encoding="utf-8"))
    loaded_sensor_frames = validate_reference_structure(loaded_fixture)
    recomputed_results = compute_reference_result(
        loaded_sensor_frames,
        checkpoint_path,
        calibration_path,
        tcn_session,
    )
    fixture_recompute_error = 0.0
    for step in (150, 151):
        fixture_recompute_error = max(
            fixture_recompute_error,
            compare_reference_results(
                loaded_fixture[f"expected_step{step}"],
                recomputed_results[f"expected_step{step}"],
                float(loaded_fixture["absolute_tolerance"]),
            ),
        )
        if step == 151 and loaded_fixture["frames"][step - 1][
            "expected_action"
        ] != loaded_fixture[f"expected_step{step}"]["action"]:
            raise RuntimeError(
                f"Frame {step} action does not match expected_step{step}"
            )
    model_package = loaded_fixture["model_package"]
    if model_package["model_config_sha256"] != sha256(config_path):
        raise RuntimeError("Reference replay model_config SHA256 is stale")
    if model_package["tcn_onnx_sha256"] != sha256(tcn_path):
        raise RuntimeError("Reference replay TCN SHA256 is stale")

    print(f"Wrote {tcn_path} ({sha256(tcn_path)})")
    print(f"Wrote {config_path} ({sha256(config_path)})")
    print(
        f"Wrote {reference_replay_path} "
        f"({sha256(reference_replay_path)})"
    )
    print(
        "TCN PyTorch/ORT max error: "
        f"abs={tcn_error[0]:.9g}, rel={tcn_error[1]:.9g}"
    )
    for step in (150, 151):
        result = reference_results[f"expected_step{step}"]
        print(
            f"Reference step {step} action: "
            + json.dumps(result["action"])
        )
        print(
            f"Reference step {step} target torque Nm: "
            + json.dumps(result["target_torque_nm"])
        )
    replay_tcn_error = max(
        float(reference_results[f"expected_step{step}"][
            "tcn_python_ort_max_abs_error"
        ])
        for step in (150, 151)
    )
    print(
        "Reference replay verification: "
        f"recompute_abs={fixture_recompute_error:.9g}, "
        f"tcn_python_ort_abs="
        f"{replay_tcn_error:.9g}"
    )


if __name__ == "__main__":
    main()
