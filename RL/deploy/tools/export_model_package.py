#!/usr/bin/env python3
"""Export the frozen G-Exo TCN and deterministic Actor model package."""

from __future__ import annotations

import argparse
import hashlib
import io
import json
from pathlib import Path
import sys
import zipfile

import numpy as np
import onnx
import onnxruntime as ort
import torch
from torch import nn


sys.dont_write_bytecode = True


SCRIPT_PATH = Path(__file__).resolve()
REPOSITORY_ROOT = SCRIPT_PATH.parents[3]
RL_ROOT = REPOSITORY_ROOT / "RL"

TCN_INPUT_NAME = "sensor_history"
TCN_OUTPUT_NAME = "prediction"
ACTOR_INPUT_NAME = "observation"
ACTOR_OUTPUT_NAME = "action"

TCN_INPUT_SHAPE = (1, 32, 50)
TCN_OUTPUT_SHAPE = (1, 2, 12)
ACTOR_INPUT_SHAPE = (1, 160)
ACTOR_OUTPUT_SHAPE = (1, 4)

JOINT_ORDER = [
    "left_hip",
    "left_knee",
    "right_hip",
    "right_knee",
]
GRAVITY_M_S2 = 9.80665
ACTOR_FRAME_SCALE = np.asarray(
    [np.pi] * 4
    + [20.0] * 4
    + [20.0] * 12
    + [4.0 * GRAVITY_M_S2] * 12
    + [1.0] * 4,
    dtype=np.float32,
)


class DeterministicActor(nn.Module):
    """The SB3 PPO policy mean branch, without sampling or the critic."""

    def __init__(self) -> None:
        super().__init__()
        self.policy_net = nn.Sequential(
            nn.Linear(160, 128),
            nn.Tanh(),
            nn.Linear(128, 64),
            nn.Tanh(),
        )
        self.action_net = nn.Linear(64, 4)

    def forward(self, observation: torch.Tensor) -> torch.Tensor:
        return self.action_net(self.policy_net(observation))


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
        "--actor-checkpoint",
        type=Path,
        default=(
            RL_ROOT
            / "outputs/myoassist_gexo_effort_torque8_rate20_1m"
            / "best_model/best_model.zip"
        ),
    )
    parser.add_argument(
        "--output-directory",
        type=Path,
        default=RL_ROOT / "deploy/models",
    )
    parser.add_argument(
        "--reference-replay",
        type=Path,
        default=RL_ROOT / "deploy/tests/reference_replay.json",
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


def load_torch_bytes(payload: bytes) -> object:
    stream = io.BytesIO(payload)
    try:
        return torch.load(stream, map_location="cpu", weights_only=False)
    except TypeError:
        stream.seek(0)
        return torch.load(stream, map_location="cpu")


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


def validate_actor_metadata(metadata: dict[str, object]) -> None:
    policy_class = metadata.get("policy_class")
    policy_kwargs = metadata.get("policy_kwargs")
    observation_space = metadata.get("observation_space")
    action_space = metadata.get("action_space")
    if not all(
        isinstance(value, dict)
        for value in (
            policy_class,
            policy_kwargs,
            observation_space,
            action_space,
        )
    ):
        raise ValueError("Actor archive has incomplete SB3 metadata")
    if policy_class.get("__module__") != "stable_baselines3.common.policies":
        raise ValueError("Actor must use the SB3 ActorCriticPolicy")
    if policy_kwargs.get("activation_fn") != (
        "<class 'torch.nn.modules.activation.Tanh'>"
    ):
        raise ValueError("Actor policy activation must be torch.nn.Tanh")
    if policy_kwargs.get("net_arch") != {
        "pi": [128, 64],
        "vf": [128, 64],
    }:
        raise ValueError("Actor policy net_arch must be pi/vf [128, 64]")
    if metadata.get("use_sde") is not False:
        raise ValueError("Actor exporter does not support gSDE or squashed actions")
    if observation_space.get("_shape") != [160]:
        raise ValueError("Actor observation space must have shape [160]")
    if (
        action_space.get("_shape") != [4]
        or action_space.get("low_repr") != "-1.0"
        or action_space.get("high_repr") != "1.0"
    ):
        raise ValueError("Actor action space must be Box([-1, 1], shape=(4,))")


def build_actor(actor_checkpoint: Path) -> nn.Module:
    with zipfile.ZipFile(actor_checkpoint) as archive:
        try:
            metadata = json.loads(archive.read("data"))
            state = load_torch_bytes(archive.read("policy.pth"))
        except (KeyError, json.JSONDecodeError) as error:
            raise ValueError(
                "Actor archive must contain valid data and policy.pth"
            ) from error

    if not isinstance(metadata, dict) or not isinstance(state, dict):
        raise TypeError("Actor metadata and policy state must be dictionaries")
    validate_actor_metadata(metadata)

    expected = {
        "log_std": (4,),
        "mlp_extractor.policy_net.0.weight": (128, 160),
        "mlp_extractor.policy_net.0.bias": (128,),
        "mlp_extractor.policy_net.2.weight": (64, 128),
        "mlp_extractor.policy_net.2.bias": (64,),
        "mlp_extractor.value_net.0.weight": (128, 160),
        "mlp_extractor.value_net.0.bias": (128,),
        "mlp_extractor.value_net.2.weight": (64, 128),
        "mlp_extractor.value_net.2.bias": (64,),
        "action_net.weight": (4, 64),
        "action_net.bias": (4,),
        "value_net.weight": (1, 64),
        "value_net.bias": (1,),
    }
    if set(state) != set(expected):
        unexpected = sorted(set(state) - set(expected))
        missing = sorted(set(expected) - set(state))
        raise ValueError(
            "Actor policy state does not match the supported topology: "
            f"missing={missing}, unexpected={unexpected}"
        )
    for key, shape in expected.items():
        if not isinstance(state[key], torch.Tensor):
            raise TypeError(f"Actor state value {key} must be a tensor")
        if tuple(state[key].shape) != shape:
            raise ValueError(
                f"Actor tensor {key} must have shape {shape}, "
                f"got {tuple(state[key].shape)}"
            )

    model = DeterministicActor()
    actor_state = {
        "policy_net.0.weight": state["mlp_extractor.policy_net.0.weight"],
        "policy_net.0.bias": state["mlp_extractor.policy_net.0.bias"],
        "policy_net.2.weight": state["mlp_extractor.policy_net.2.weight"],
        "policy_net.2.bias": state["mlp_extractor.policy_net.2.bias"],
        "action_net.weight": state["action_net.weight"],
        "action_net.bias": state["action_net.bias"],
    }
    model.load_state_dict(actor_state, strict=True)
    model.eval()
    model.requires_grad_(False)
    return model


def export_onnx(
    model: nn.Module,
    sample: torch.Tensor,
    output_path: Path,
    input_name: str,
    output_name: str,
) -> None:
    with torch.inference_mode():
        torch.onnx.export(
            model,
            sample,
            output_path,
            export_params=True,
            opset_version=17,
            do_constant_folding=True,
            input_names=[input_name],
            output_names=[output_name],
            dynamic_axes=None,
            dynamo=False,
        )


def validate_interface(
    model_path: Path,
    input_name: str,
    input_shape: tuple[int, ...],
    output_name: str,
    output_shape: tuple[int, ...],
) -> ort.InferenceSession:
    model = onnx.load(model_path)
    onnx.checker.check_model(model, full_check=True)

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
        raise ValueError(f"{model_path.name} must have one input and one output")
    actual_input = (inputs[0].name, inputs[0].type, tuple(inputs[0].shape))
    expected_input = (input_name, "tensor(float)", input_shape)
    if actual_input != expected_input:
        raise ValueError(
            f"{model_path.name} input is {actual_input}, expected {expected_input}"
        )
    actual_output = (outputs[0].name, outputs[0].type, tuple(outputs[0].shape))
    expected_output = (output_name, "tensor(float)", output_shape)
    if actual_output != expected_output:
        raise ValueError(
            f"{model_path.name} output is {actual_output}, "
            f"expected {expected_output}"
        )
    return session


def compare_runtime(
    model: nn.Module,
    session: ort.InferenceSession,
    sample: torch.Tensor,
    input_name: str,
    output_name: str,
) -> tuple[float, float]:
    with torch.inference_mode():
        expected = model(sample).cpu().numpy()
    actual = session.run(
        [output_name],
        {input_name: sample.cpu().numpy()},
    )[0]
    absolute_error = np.abs(expected - actual)
    maximum_absolute_error = float(absolute_error.max(initial=0.0))
    denominator = np.maximum(np.abs(expected), np.float32(1.0e-7))
    maximum_relative_error = float((absolute_error / denominator).max(initial=0.0))
    np.testing.assert_allclose(actual, expected, rtol=1.0e-5, atol=1.0e-6)
    return maximum_absolute_error, maximum_relative_error


def deterministic_reference_frames() -> list[dict[str, list[float]]]:
    """Build 151 reproducible finite inputs without a random generator."""

    frames: list[dict[str, list[float]]] = []
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
            imu_axis = channel % 3
            acceleration_center = GRAVITY_M_S2 if imu_axis == 2 else 0.0
            sensor[20 + channel] = np.float32(
                acceleration_center
                + (((step * (3 + channel) + 23 * channel) % 101) - 50)
                * 0.025
            )
        previous_action = np.asarray(
            [
                (((step * (3 + 4 * joint) + 29 * joint) % 101) - 50)
                * 0.016
                for joint in range(4)
            ],
            dtype=np.float32,
        )
        if not np.all(np.isfinite(sensor)):
            raise RuntimeError("Generated reference sensor contains NaN or Inf")
        if not np.all(np.isfinite(previous_action)):
            raise RuntimeError("Generated reference action contains NaN or Inf")
        if frame_index < 150 and not np.any(previous_action != 0.0):
            raise RuntimeError("Warmup reference actions must be deliberately nonzero")
        frames.append(
            {
                "sensor32": sensor.tolist(),
                "previous_applied_action": previous_action.tolist(),
            }
        )
    return frames


def compute_reference_result(
    frames: list[dict[str, list[float]]],
    tcn_checkpoint_path: Path,
    calibration_path: Path,
    actor_model: nn.Module,
    tcn_session: ort.InferenceSession,
    actor_session: ort.InferenceSession,
) -> dict[str, object]:
    """Run the training-time preprocessing path and cross-check both ONNX models."""

    if str(REPOSITORY_ROOT) not in sys.path:
        sys.path.insert(0, str(REPOSITORY_ROOT))
    from RL.env.actor_observation import ActorObservationBuilder
    from RL.runners.predictors.tcn_runtime import FrozenTCNRuntime

    if len(frames) != 151:
        raise ValueError("Reference replay must contain exactly 151 frames")
    tcn_runtime = FrozenTCNRuntime(
        tcn_checkpoint_path,
        device="cpu",
        calibration=calibration_path,
        allow_legacy_checkpoint=True,
    )
    actor_builder = ActorObservationBuilder(
        frame_scale=ACTOR_FRAME_SCALE,
        clip=5.0,
    )
    leaked_warmup_builder = ActorObservationBuilder(
        frame_scale=ACTOR_FRAME_SCALE,
        clip=5.0,
    )
    normalized_tcn_history: list[np.ndarray] = []
    zero_action = np.zeros(4, dtype=np.float32)

    final_sensor: np.ndarray | None = None
    for frame_index, frame in enumerate(frames):
        sensor = finite_vector(frame["sensor32"], 32, "sensor32")
        previous_action = finite_vector(
            frame["previous_applied_action"],
            4,
            "previous_applied_action",
        )
        tcn_runtime.append(sensor)
        normalized_tcn_history.append(tcn_runtime.latest_normalized_frame)
        actor_builder.append(
            sensor,
            zero_action if frame_index < 150 else previous_action,
        )
        leaked_warmup_builder.append(sensor, previous_action)
        final_sensor = sensor

    if final_sensor is None or not tcn_runtime.ready or not actor_builder.ready:
        raise RuntimeError("Reference histories did not become ready")
    tcn_result = tcn_runtime.predict(final_sensor[:4], final_sensor[4:8])

    tcn_input = np.stack(normalized_tcn_history[-50:], axis=0).T[None, :, :]
    tcn_onnx = tcn_session.run(
        [TCN_OUTPUT_NAME],
        {TCN_INPUT_NAME: tcn_input.astype(np.float32, copy=False)},
    )[0][0]
    tcn_absolute_error = float(
        np.max(np.abs(tcn_onnx - tcn_result.normalized_prediction), initial=0.0)
    )
    np.testing.assert_allclose(
        tcn_onnx,
        tcn_result.normalized_prediction,
        rtol=1.0e-5,
        atol=1.0e-6,
    )

    observation = actor_builder.build(tcn_result.feature16)
    observation_tensor = torch.from_numpy(observation[None, :])
    with torch.inference_mode():
        raw_action = actor_model(observation_tensor).cpu().numpy()[0]
    actor_onnx = actor_session.run(
        [ACTOR_OUTPUT_NAME],
        {ACTOR_INPUT_NAME: observation[None, :]},
    )[0][0]
    actor_absolute_error = float(
        np.max(np.abs(actor_onnx - raw_action), initial=0.0)
    )
    np.testing.assert_allclose(
        actor_onnx,
        raw_action,
        rtol=1.0e-5,
        atol=1.0e-6,
    )
    expected_action = np.clip(raw_action, -1.0, 1.0).astype(np.float32)

    leaked_observation = leaked_warmup_builder.build(tcn_result.feature16)
    with torch.inference_mode():
        leaked_raw_action = actor_model(
            torch.from_numpy(leaked_observation[None, :])
        ).cpu().numpy()[0]
    leaked_action = np.clip(leaked_raw_action, -1.0, 1.0).astype(np.float32)
    leak_guard_difference = float(
        np.max(np.abs(leaked_action - expected_action), initial=0.0)
    )
    if leak_guard_difference <= 1.0e-5:
        raise RuntimeError(
            "Reference replay cannot detect leaked warmup action history"
        )

    return {
        "expected_action": expected_action.tolist(),
        "raw_actor_output": raw_action.astype(np.float32).tolist(),
        "tcn_feature16": tcn_result.feature16.astype(np.float32).tolist(),
        "tcn_pytorch_ort_max_abs_error": tcn_absolute_error,
        "actor_pytorch_ort_max_abs_error": actor_absolute_error,
        "warmup_action_leak_guard_max_abs_difference": leak_guard_difference,
    }


def validate_reference_structure(
    fixture: dict[str, object],
) -> list[dict[str, list[float]]]:
    if fixture.get("schema") != "gexo_deploy_reference_replay_v1":
        raise ValueError("Unsupported reference replay schema")
    if fixture.get("schema_version") != 1:
        raise ValueError("Unsupported reference replay schema_version")
    if fixture.get("frame_count") != 151 or fixture.get("warmup_steps") != 150:
        raise ValueError("Reference replay must describe 150 warmup + 1 ready step")
    frames = fixture.get("frames")
    if not isinstance(frames, list) or len(frames) != 151:
        raise ValueError("Reference replay frames must contain 151 entries")
    validated: list[dict[str, list[float]]] = []
    for index, frame in enumerate(frames):
        if not isinstance(frame, dict):
            raise TypeError(f"Reference frame {index} must be an object")
        sensor = finite_vector(frame.get("sensor32"), 32, "sensor32")
        previous_action = finite_vector(
            frame.get("previous_applied_action"),
            4,
            "previous_applied_action",
        )
        validated.append(
            {
                "sensor32": sensor.tolist(),
                "previous_applied_action": previous_action.tolist(),
            }
        )
    finite_vector(fixture.get("expected_action"), 4, "expected_action")
    return validated


def build_reference_fixture(
    tcn_checkpoint_path: Path,
    calibration_path: Path,
    actor_model: nn.Module,
    tcn_session: ort.InferenceSession,
    actor_session: ort.InferenceSession,
    config_path: Path,
    tcn_path: Path,
    actor_path: Path,
) -> tuple[dict[str, object], dict[str, object]]:
    frames = deterministic_reference_frames()
    result = compute_reference_result(
        frames,
        tcn_checkpoint_path,
        calibration_path,
        actor_model,
        tcn_session,
        actor_session,
    )
    fixture: dict[str, object] = {
        "schema": "gexo_deploy_reference_replay_v1",
        "schema_version": 1,
        "frame_count": 151,
        "warmup_steps": 150,
        "first_action_step": 151,
        "expected_zero_action_through_step": 150,
        "warmup_action_history_mode": "force_zero_ignore_input",
        "runtime_sensor_protocol": "gexo_sensor32_runtime_v1",
        "frames": frames,
        "expected_state": "READY",
        "expected_action": result["expected_action"],
        "absolute_tolerance": 1.0e-5,
        "diagnostics": {
            "raw_actor_output": result["raw_actor_output"],
            "tcn_feature16": result["tcn_feature16"],
            "tcn_pytorch_ort_max_abs_error": result[
                "tcn_pytorch_ort_max_abs_error"
            ],
            "actor_pytorch_ort_max_abs_error": result[
                "actor_pytorch_ort_max_abs_error"
            ],
            "warmup_action_leak_guard_max_abs_difference": result[
                "warmup_action_leak_guard_max_abs_difference"
            ],
        },
        "model_package": {
            "schema": "gexo_deploy_model_v1",
            "model_config_sha256": sha256(config_path),
            "tcn_onnx_sha256": sha256(tcn_path),
            "actor_onnx_sha256": sha256(actor_path),
        },
    }
    return fixture, result


def build_config(
    checkpoint: dict,
    calibration: dict,
    tcn_path: Path,
    actor_path: Path,
    source_paths: dict[str, Path],
) -> dict[str, object]:
    require_keys(
        checkpoint["statistics"],
        {"input_mean", "input_std", "target_mean", "target_std"},
        "TCN statistics",
    )
    statistics = checkpoint["statistics"]
    input_calibration = calibration.get("input", {})
    target_calibration = calibration.get("output", {})
    feature_normalization = calibration.get("actor_feature_normalization", {})
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
        raise ValueError("feature normalization horizons must be [5, 10]")

    return {
        "schema": "gexo_deploy_model_v1",
        "schema_version": 1,
        "warmup_steps": 150,
        "control_frequency_hz": 50.0,
        "joint_order": JOINT_ORDER,
        "protocols": {
            "runtime_sensor": "gexo_sensor32_runtime_v1",
            "tcn_sensor": "phase12_tcn32_interleaved_v1",
            "actor_observation": "gexo_actor160_explicit_tcn_v1",
            "warmup": "gexo_zero_assist_preroll150_v1",
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
            },
            "actor": {
                "file": actor_path.name,
                "sha256": sha256(actor_path),
                "input": {
                    "name": ACTOR_INPUT_NAME,
                    "dtype": "float32",
                    "shape": list(ACTOR_INPUT_SHAPE),
                },
                "output": {
                    "name": ACTOR_OUTPUT_NAME,
                    "dtype": "float32",
                    "shape": list(ACTOR_OUTPUT_SHAPE),
                },
            },
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
        "actor_preprocessing": {
            "history_length": 4,
            "frame_order": [
                "q4",
                "dq4",
                "gyro12",
                "specific_force12",
                "previous_applied_action4",
            ],
            "frame_scale": ACTOR_FRAME_SCALE.tolist(),
            "frame_clip": 5.0,
            "output_clip": [-1.0, 1.0],
        },
        "source": {
            name: {
                "path": repository_relative(path),
                "sha256": sha256(path),
            }
            for name, path in source_paths.items()
        },
    }


def main() -> None:
    args = parse_args()
    tcn_checkpoint_path = args.tcn_checkpoint.expanduser().resolve()
    calibration_path = args.tcn_calibration.expanduser().resolve()
    actor_checkpoint_path = args.actor_checkpoint.expanduser().resolve()
    output_directory = args.output_directory.expanduser().resolve()
    reference_replay_path = args.reference_replay.expanduser().resolve()
    for path in (
        tcn_checkpoint_path,
        calibration_path,
        actor_checkpoint_path,
    ):
        if not path.is_file():
            raise FileNotFoundError(path)
    output_directory.mkdir(parents=True, exist_ok=True)

    checkpoint = load_torch(tcn_checkpoint_path)
    if not isinstance(checkpoint, dict):
        raise TypeError("TCN checkpoint root must be a dictionary")
    calibration = json.loads(calibration_path.read_text(encoding="utf-8"))
    if calibration.get("schema_version") != 1:
        raise ValueError("Unsupported TCN calibration schema_version")

    tcn_model = build_tcn(checkpoint)
    actor_model = build_actor(actor_checkpoint_path)
    generator = torch.Generator().manual_seed(20260804)
    tcn_sample = torch.randn(TCN_INPUT_SHAPE, generator=generator)
    actor_sample = torch.randn(ACTOR_INPUT_SHAPE, generator=generator)

    tcn_path = output_directory / "tcn.onnx"
    actor_path = output_directory / "actor.onnx"
    export_onnx(
        tcn_model,
        tcn_sample,
        tcn_path,
        TCN_INPUT_NAME,
        TCN_OUTPUT_NAME,
    )
    export_onnx(
        actor_model,
        actor_sample,
        actor_path,
        ACTOR_INPUT_NAME,
        ACTOR_OUTPUT_NAME,
    )

    tcn_session = validate_interface(
        tcn_path,
        TCN_INPUT_NAME,
        TCN_INPUT_SHAPE,
        TCN_OUTPUT_NAME,
        TCN_OUTPUT_SHAPE,
    )
    actor_session = validate_interface(
        actor_path,
        ACTOR_INPUT_NAME,
        ACTOR_INPUT_SHAPE,
        ACTOR_OUTPUT_NAME,
        ACTOR_OUTPUT_SHAPE,
    )
    tcn_error = compare_runtime(
        tcn_model,
        tcn_session,
        tcn_sample,
        TCN_INPUT_NAME,
        TCN_OUTPUT_NAME,
    )
    actor_error = compare_runtime(
        actor_model,
        actor_session,
        actor_sample,
        ACTOR_INPUT_NAME,
        ACTOR_OUTPUT_NAME,
    )

    config = build_config(
        checkpoint,
        calibration,
        tcn_path,
        actor_path,
        {
            "tcn_checkpoint": tcn_checkpoint_path,
            "tcn_calibration": calibration_path,
            "actor_checkpoint": actor_checkpoint_path,
        },
    )
    config_path = output_directory / "model_config.json"
    config_path.write_text(
        json.dumps(config, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    fixture, reference_result = build_reference_fixture(
        tcn_checkpoint_path,
        calibration_path,
        actor_model,
        tcn_session,
        actor_session,
        config_path,
        tcn_path,
        actor_path,
    )
    reference_replay_path.parent.mkdir(parents=True, exist_ok=True)
    reference_replay_path.write_text(
        json.dumps(fixture, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    loaded_fixture = json.loads(reference_replay_path.read_text(encoding="utf-8"))
    loaded_frames = validate_reference_structure(loaded_fixture)
    recomputed_result = compute_reference_result(
        loaded_frames,
        tcn_checkpoint_path,
        calibration_path,
        actor_model,
        tcn_session,
        actor_session,
    )
    fixture_expected = finite_vector(
        loaded_fixture["expected_action"],
        4,
        "expected_action",
    )
    fixture_recompute_error = float(
        np.max(
            np.abs(
                finite_vector(
                    recomputed_result["expected_action"],
                    4,
                    "recomputed_expected_action",
                )
                - fixture_expected
            ),
            initial=0.0,
        )
    )
    np.testing.assert_allclose(
        recomputed_result["expected_action"],
        fixture_expected,
        rtol=0.0,
        atol=float(loaded_fixture["absolute_tolerance"]),
    )
    model_package = loaded_fixture["model_package"]
    if model_package["model_config_sha256"] != sha256(config_path):
        raise RuntimeError("Reference replay model_config SHA256 is stale")
    if model_package["tcn_onnx_sha256"] != sha256(tcn_path):
        raise RuntimeError("Reference replay TCN SHA256 is stale")
    if model_package["actor_onnx_sha256"] != sha256(actor_path):
        raise RuntimeError("Reference replay Actor SHA256 is stale")

    print(f"Wrote {tcn_path} ({sha256(tcn_path)})")
    print(f"Wrote {actor_path} ({sha256(actor_path)})")
    print(f"Wrote {config_path} ({sha256(config_path)})")
    print(
        f"Wrote {reference_replay_path} "
        f"({sha256(reference_replay_path)})"
    )
    print(
        "TCN PyTorch/ORT max error: "
        f"abs={tcn_error[0]:.9g}, rel={tcn_error[1]:.9g}"
    )
    print(
        "Actor PyTorch/ORT max error: "
        f"abs={actor_error[0]:.9g}, rel={actor_error[1]:.9g}"
    )
    print(
        "Reference step 151 clipped action: "
        + json.dumps(reference_result["expected_action"])
    )
    print(
        "Reference replay verification: "
        f"recompute_abs={fixture_recompute_error:.9g}, "
        "warmup_leak_guard_abs="
        f"{reference_result['warmup_action_leak_guard_max_abs_difference']:.9g}"
    )


if __name__ == "__main__":
    main()
