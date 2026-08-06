"""Immutable training protocol and TensorBoard metrics for MyoAssist G-Exo."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping

import gymnasium as gym
import numpy as np
import torch
from stable_baselines3.common.callbacks import BaseCallback

from RL.env.actor_observation import (
    ACTION_DIM,
    ACTOR_HISTORY_LENGTH,
    ACTOR_OBSERVATION_DIM,
    ACTOR_OBSERVATION_PROTOCOL,
    JOINT_ORDER,
    RESET_PROTOCOL,
    RESET_WARMUP_STEPS,
    RUNTIME_SENSOR_DIM,
    RUNTIME_SENSOR_PROTOCOL,
    TCN_FEATURE_DIM,
    TCN_HISTORY_LENGTH,
    TCN_SENSOR_PROTOCOL,
)
from RL.env.myoassist.baseline import (
    BASELINE_SCHEMA,
    SPEED_WINDOW_STEPS,
    TRAINING_SPEED_SCHEDULE,
)
from RL.env.myoassist.reward import RewardConfig


PROTOCOL_SCHEMA = "gexo_myoassist_ppo_protocol_v4"
RUN_CONFIG_SCHEMA = "gexo_myoassist_ppo_run_v2"
CONTROL_HZ = 50
WARMUP_STEPS = RESET_WARMUP_STEPS
HARD_TORQUE_LIMIT_NM = 8.0
TORQUE_SOFT_THRESHOLD_NM = 6.5
TORQUE_TERMINATION_THRESHOLD_NM = 8.0
TORQUE_RATE_LIMIT_NM_S = 20.0


class ProtocolMismatchError(ValueError):
    """Raised before resume when a physical or learning contract changed."""


class CanonicalEvaluationEnv(gym.Wrapper):
    """Force every EvalCallback episode to use one reproducible condition."""

    def __init__(
        self,
        env: gym.Env,
        *,
        target_speed_m_s: float = 1.0,
        reference_index: int = 0,
        seed: int = 0,
    ) -> None:
        super().__init__(env)
        self.target_speed_m_s = float(target_speed_m_s)
        self.reference_index = int(reference_index)
        self.canonical_seed = int(seed)

    def reset(self, *, seed=None, options=None):
        del seed, options
        observation, info = self.env.reset(
            seed=self.canonical_seed,
            options={
                "target_speed": self.target_speed_m_s,
                "reference_index": self.reference_index,
            },
        )
        info = dict(info)
        info["canonical_evaluation"] = True
        return observation, info


def file_sha256(path: str | Path) -> str:
    source = Path(path).expanduser().resolve(strict=True)
    digest = hashlib.sha256()
    with source.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def build_training_protocol(
    *,
    human_checkpoint: str | Path,
    baseline_path: str | Path,
    tcn_checkpoint: str | Path,
    tcn_calibration_path: str | Path,
    model_path: str | Path,
    min_speed_m_s: float,
    max_speed_m_s: float,
    action_scale_nm: float,
    max_episode_steps: int,
    workers: int,
    seed: int,
    ppo_parameters: Mapping[str, Any],
    evaluation_speed_m_s: float,
    evaluation_seed: int,
) -> dict[str, Any]:
    """Load every artifact and return the exact immutable PPO contract."""

    paths = {
        "human_checkpoint": _path(human_checkpoint),
        "baseline": _path(baseline_path),
        "tcn_checkpoint": _path(tcn_checkpoint),
        "tcn_calibration": _path(tcn_calibration_path),
        "physical_model": _path(model_path),
    }
    baseline = _json_object(paths["baseline"])
    calibration = _json_object(paths["tcn_calibration"])
    tcn = _load_tcn_metadata(paths["tcn_checkpoint"])
    hashes = {name: file_sha256(path) for name, path in paths.items()}

    baseline_metadata = _mapping(baseline.get("metadata"), "baseline.metadata")
    calibration_fit = _mapping(calibration.get("fit"), "calibration.fit")
    if baseline.get("schema") != BASELINE_SCHEMA:
        raise ValueError(
            f"Baseline schema must be {BASELINE_SCHEMA}, got {baseline.get('schema')}."
        )
    if int(calibration.get("schema_version", -1)) != 1:
        raise ValueError("TCN calibration schema_version must be 1.")
    if calibration.get("protocol") != "gexo_myoassist_phase12_tcn_calibration_v1":
        raise ValueError("Unsupported MyoAssist TCN calibration protocol.")
    _require_flag(baseline_metadata, "urdf_enabled", False)
    _require_flag(baseline_metadata, "domain_randomization_enabled", False)
    _require_flag(calibration, "urdf_enabled", False)
    _require_flag(calibration, "domain_randomization_enabled", False)

    identities = {
        "human_checkpoint_sha256": hashes["human_checkpoint"],
        "physical_model_sha256": hashes["physical_model"],
        "tcn_checkpoint_sha256": hashes["tcn_checkpoint"],
    }
    expected_identity_fields = (
        (baseline_metadata, "human_checkpoint_sha256", identities["human_checkpoint_sha256"]),
        (baseline_metadata, "model_sha256", identities["physical_model_sha256"]),
        (calibration, "human_checkpoint_sha256", identities["human_checkpoint_sha256"]),
        (calibration, "physical_model_sha256", identities["physical_model_sha256"]),
        (calibration, "tcn_checkpoint_sha256", identities["tcn_checkpoint_sha256"]),
    )
    for source, name, expected in expected_identity_fields:
        if source.get(name) != expected:
            raise ValueError(f"Artifact identity mismatch for {name}.")

    baseline_speeds = _positive_speeds(baseline.get("speeds_m_s"), "baseline")
    calibration_speeds = _positive_speeds(
        calibration.get("verified_speed_set_m_s"),
        "TCN calibration",
    )
    calibrated_min = max(float(baseline_speeds[0]), float(calibration_speeds[0]))
    calibrated_max = min(float(baseline_speeds[-1]), float(calibration_speeds[-1]))
    _validate_requested_range(
        min_speed_m_s,
        max_speed_m_s,
        calibrated_min,
        calibrated_max,
    )
    _validate_requested_range(
        evaluation_speed_m_s,
        evaluation_speed_m_s,
        calibrated_min,
        calibrated_max,
    )
    if int(baseline.get("speed_window_steps", -1)) != SPEED_WINDOW_STEPS:
        raise ValueError("Baseline forward-speed filter contract is incompatible.")
    if int(baseline_metadata.get("warmup_steps", -1)) != WARMUP_STEPS:
        raise ValueError(
            f"Baseline must use the {WARMUP_STEPS}-step warmup protocol."
        )
    if baseline_metadata.get("warmup_protocol") != RESET_PROTOCOL:
        raise ValueError("Baseline reset/warmup protocol is incompatible.")
    if int(calibration_fit.get("warmup_steps", -1)) != WARMUP_STEPS:
        raise ValueError(
            f"TCN calibration must use the {WARMUP_STEPS}-step warmup protocol."
        )
    if calibration_fit.get("warmup_protocol") != RESET_PROTOCOL:
        raise ValueError("TCN calibration reset/warmup protocol is incompatible.")
    if int(tcn["history"]) != TCN_HISTORY_LENGTH:
        raise ValueError("TCN checkpoint history must be exactly 50 frames.")
    if tuple(tcn["horizons"]) != (5, 10) or int(tcn["input_dim"]) != 32:
        raise ValueError("TCN checkpoint must use 32 inputs and horizons (5, 10).")
    if int(tcn["target_dim"]) < 8:
        raise ValueError("TCN checkpoint target must contain four q and four dq values.")
    if not 0.0 < float(action_scale_nm) <= HARD_TORQUE_LIMIT_NM:
        raise ValueError(
            f"action_scale_nm must be in (0, {HARD_TORQUE_LIMIT_NM:g}]."
        )
    if int(max_episode_steps) < 1 or int(workers) < 1:
        raise ValueError("max_episode_steps and workers must be positive.")

    reward = RewardConfig(
        torque_limit_nm=np.full(4, HARD_TORQUE_LIMIT_NM),
        jerk_scale_nm=np.full(4, TORQUE_RATE_LIMIT_NM_S / CONTROL_HZ),
        torque_soft_threshold_nm=TORQUE_SOFT_THRESHOLD_NM,
        torque_termination_threshold_nm=TORQUE_TERMINATION_THRESHOLD_NM,
    )
    protocol = {
        "schema": PROTOCOL_SCHEMA,
        "backend": "myoassist",
        "artifacts": {
            "human_checkpoint": {"sha256": hashes["human_checkpoint"]},
            "baseline": {
                "sha256": hashes["baseline"],
                "schema": baseline["schema"],
            },
            "tcn_checkpoint": {
                "sha256": hashes["tcn_checkpoint"],
                "pipeline_version": tcn.get("pipeline_version"),
            },
            "tcn_calibration": {
                "sha256": hashes["tcn_calibration"],
                "schema_version": int(calibration["schema_version"]),
                "protocol": calibration["protocol"],
            },
            "physical_model": {"sha256": hashes["physical_model"]},
        },
        "identities": identities,
        "observation": {
            "dimension": ACTOR_OBSERVATION_DIM,
            "protocol": ACTOR_OBSERVATION_PROTOCOL,
            "sensor_dimension": RUNTIME_SENSOR_DIM,
            "sensor_protocol": RUNTIME_SENSOR_PROTOCOL,
            "history_frames": ACTOR_HISTORY_LENGTH,
            "tcn_sensor_protocol": TCN_SENSOR_PROTOCOL,
            "tcn_history_frames": TCN_HISTORY_LENGTH,
            "tcn_feature_dimension": TCN_FEATURE_DIM,
            "tcn_horizon_steps": [5, 10],
        },
        "action_and_safety": {
            "dimension": ACTION_DIM,
            "joint_order": list(JOINT_ORDER),
            "normalized_range": [-1.0, 1.0],
            "action_scale_nm": float(action_scale_nm),
            "hard_torque_limit_nm": [HARD_TORQUE_LIMIT_NM] * ACTION_DIM,
            "torque_soft_threshold_nm": TORQUE_SOFT_THRESHOLD_NM,
            "torque_termination_threshold_nm": TORQUE_TERMINATION_THRESHOLD_NM,
            "torque_rate_limit_nm_s": [TORQUE_RATE_LIMIT_NM_S] * ACTION_DIM,
            "filter_time_constant_s": 0.0,
            "control_hz": CONTROL_HZ,
        },
        "human": {"frozen": True, "muscle_action_dimension": 22},
        "reset": {
            "protocol": RESET_PROTOCOL,
            "warmup_steps": WARMUP_STEPS,
            "speed_window_steps": SPEED_WINDOW_STEPS,
            "reference_index": 0,
        },
        "training_domain": {
            "terrain": "flat",
            "speed_schedule": TRAINING_SPEED_SCHEDULE,
            "speed_range_m_s": [float(min_speed_m_s), float(max_speed_m_s)],
            "calibrated_speed_range_m_s": [calibrated_min, calibrated_max],
            "max_episode_steps": int(max_episode_steps),
            "urdf_enabled": False,
            "domain_randomization_enabled": False,
        },
        "evaluation": {
            "canonical": True,
            "target_speed_m_s": float(evaluation_speed_m_s),
            "reference_index": 0,
            "seed": int(evaluation_seed),
            "deterministic_actor": True,
        },
        "reward": _json_value(asdict(reward)),
        "ppo": _json_value(dict(ppo_parameters)),
        "workers": int(workers),
        "seed": int(seed),
    }
    protocol["sha256"] = protocol_sha256(protocol)
    return protocol


def protocol_sha256(protocol: Mapping[str, Any]) -> str:
    value = dict(protocol)
    value.pop("sha256", None)
    encoded = json.dumps(
        _json_value(value), sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def assert_protocol_matches(expected: Mapping[str, Any], actual: Mapping[str, Any]) -> None:
    expected_value = _json_value(dict(expected))
    actual_value = _json_value(dict(actual))
    if expected_value == actual_value:
        return
    differences = _differences(expected_value, actual_value)
    detail = "; ".join(differences[:8])
    raise ProtocolMismatchError(f"Immutable PPO protocol mismatch: {detail}")


def prepare_run_config(
    *,
    output_dir: str | Path,
    protocol: Mapping[str, Any],
    launch: Mapping[str, Any],
    resume_from: str | Path | None,
) -> Path:
    """Validate resume provenance before creating, and never overwrite config."""

    output = Path(output_dir).expanduser().resolve()
    config_path = output / "config.json"
    if resume_from is not None:
        source_config = find_run_config(resume_from)
        source = _json_object(source_config)
        source_protocol = _mapping(
            source.get("immutable_protocol"), "source immutable_protocol"
        )
        assert_protocol_matches(source_protocol, protocol)
        if config_path.is_file():
            existing = _json_object(config_path)
            assert_protocol_matches(
                _mapping(existing.get("immutable_protocol"), "immutable_protocol"),
                protocol,
            )
            return config_path
    elif config_path.exists():
        raise FileExistsError(
            f"Refusing to overwrite existing run config: {config_path}"
        )
    elif output.is_dir() and any(output.iterdir()):
        raise FileExistsError(
            f"Fresh training output must be empty: {output}"
        )

    output.mkdir(parents=True, exist_ok=True)
    value = {
        "schema": RUN_CONFIG_SCHEMA,
        "immutable_protocol": _json_value(protocol),
        "launch": _json_value(dict(launch)),
    }
    with config_path.open("x", encoding="utf-8") as stream:
        json.dump(value, stream, indent=2, sort_keys=True)
        stream.write("\n")
    return config_path


def find_run_config(checkpoint: str | Path) -> Path:
    source = _path(checkpoint)
    directory = source.parent
    for _ in range(4):
        candidate = directory / "config.json"
        if candidate.is_file():
            value = _json_object(candidate)
            if "immutable_protocol" in value:
                return candidate
        directory = directory.parent
    raise FileNotFoundError(
        f"No immutable config.json found beside resume checkpoint: {source}"
    )


def collect_myoassist_metrics(info: Mapping[str, Any]) -> dict[str, float]:
    """Flatten every optimizer cause needed to audit route-B PPO."""

    result: dict[str, float] = {}
    terms = info.get("reward_terms", {})
    diagnostics = info.get("reward_metrics", {})
    for name, value in terms.items():
        _record_scalar(result, f"myoassist_reward/{name}", value)
    metric_names = {
        "activation_cost": "myoassist_human/activation_squared",
        "human_torque_cost": "myoassist_human/joint_torque_cost",
        "gross_load_cost": "myoassist_human/gross_load_cost",
        "activation_saving_z": "myoassist_saving/activation_z",
        "human_torque_saving_z": "myoassist_saving/joint_torque_z",
        "saving_raw": "myoassist_saving/combined_raw",
        "safety_gate": "myoassist_safety/gate",
        "speed_excess": "myoassist_safety/speed_excess",
        "upright_excess": "myoassist_safety/upright_excess",
        "joint_limit_excess": "myoassist_safety/joint_limit_excess",
        "positive_power_w": "myoassist_exo/positive_power_w",
        "mean_absolute_human_torque_nm": "myoassist_human/mean_abs_torque_nm",
        "mean_absolute_exo_torque_nm": "myoassist_exo/mean_abs_torque_nm",
        "torque_usage_cost": "myoassist_exo/torque_usage_cost",
        "torque_cost": "myoassist_exo/torque_cost",
        "torque_overload": "myoassist_safety/torque_overload_excess",
        "max_absolute_exo_torque_nm": "myoassist_exo/max_abs_torque_nm",
        "jerk_cost": "myoassist_exo/second_difference_cost",
    }
    for source, destination in metric_names.items():
        if source in diagnostics:
            _record_scalar(result, destination, diagnostics[source])
    top_level = {
        "target_speed_m_s": "myoassist_locomotion/target_speed_m_s",
        "forward_speed_raw_m_s": "myoassist_locomotion/raw_speed_m_s",
        "forward_speed_filtered_m_s": "myoassist_locomotion/filtered_speed_m_s",
        "pelvis_height_m": "myoassist_pose/pelvis_height_m",
        "pelvis_pitch_rad": "myoassist_pose/pelvis_pitch_rad",
        "torque_overload": "myoassist_safety/torque_overload",
        "max_absolute_exo_torque_nm": "myoassist_exo/max_abs_torque_nm",
    }
    for source, destination in top_level.items():
        if source in info:
            _record_scalar(result, destination, info[source])
    arrays = {
        "joint_q_rad": "myoassist_joint/q_rad",
        "joint_dq_rad_s": "myoassist_joint/dq_rad_s",
        "exo_torque": "myoassist_joint/exo_torque_nm",
        "exo_joint_power_w": "myoassist_joint/exo_power_w",
    }
    for source, prefix in arrays.items():
        if source not in info:
            continue
        values = np.asarray(info[source], dtype=np.float64)
        if values.shape != (4,) or not np.all(np.isfinite(values)):
            continue
        for joint, value in zip(JOINT_ORDER, values):
            result[f"{prefix}/{joint}"] = float(value)
    return result


class MyoAssistMetricsCallback(BaseCallback):
    """Record route-B physical metrics without teaching RL/train.py backend names."""

    def _on_step(self) -> bool:
        for info in self.locals.get("infos", ()):
            for name, value in collect_myoassist_metrics(info).items():
                self.logger.record_mean(name, value)
        return True


def _load_tcn_metadata(path: Path) -> Mapping[str, Any]:
    try:
        value = torch.load(path, map_location="cpu", weights_only=False)
    except TypeError:
        value = torch.load(path, map_location="cpu")
    if not isinstance(value, Mapping):
        raise ValueError("TCN checkpoint must contain a mapping.")
    required = {"input_dim", "target_dim", "history", "horizons"}
    missing = required - set(value)
    if missing:
        raise ValueError(f"TCN checkpoint is missing {sorted(missing)}.")
    return value


def _validate_requested_range(
    minimum: float,
    maximum: float,
    calibrated_minimum: float,
    calibrated_maximum: float,
) -> None:
    low = float(minimum)
    high = float(maximum)
    if not np.isfinite([low, high]).all() or not 0.0 < low <= high:
        raise ValueError("Speed range must be finite and satisfy 0 < min <= max.")
    tolerance = 1.0e-9
    if low < calibrated_minimum - tolerance or high > calibrated_maximum + tolerance:
        raise ValueError(
            f"Requested speed range [{low}, {high}] is outside calibrated range "
            f"[{calibrated_minimum}, {calibrated_maximum}]."
        )


def _positive_speeds(value: Any, name: str) -> np.ndarray:
    speeds = np.asarray(value, dtype=np.float64)
    if (
        speeds.ndim != 1
        or len(speeds) < 1
        or not np.all(np.isfinite(speeds))
        or np.any(speeds <= 0.0)
        or np.any(np.diff(speeds) <= 0.0)
    ):
        raise ValueError(f"{name} speeds must be positive and strictly increasing.")
    return speeds


def _require_flag(source: Mapping[str, Any], name: str, expected: bool) -> None:
    if source.get(name) is not expected:
        raise ValueError(f"{name} must be explicitly {expected}.")


def _path(value: str | Path) -> Path:
    return Path(value).expanduser().resolve(strict=True)


def _json_object(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"Expected a JSON object: {path}")
    return value


def _mapping(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{name} must be a mapping.")
    return value


def _json_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {str(key): _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, type):
        return f"{value.__module__}.{value.__qualname__}"
    if isinstance(value, np.generic):
        return value.item()
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    raise TypeError(f"Cannot encode immutable protocol value {type(value).__name__}.")


def _record_scalar(result: dict[str, float], name: str, value: Any) -> None:
    scalar = float(value)
    if np.isfinite(scalar):
        result[name] = scalar


def _differences(expected: Any, actual: Any, path: str = "protocol") -> list[str]:
    if isinstance(expected, dict) and isinstance(actual, dict):
        differences: list[str] = []
        for key in sorted(set(expected) | set(actual)):
            child = f"{path}.{key}"
            if key not in expected:
                differences.append(f"{child} added")
            elif key not in actual:
                differences.append(f"{child} missing")
            else:
                differences.extend(_differences(expected[key], actual[key], child))
        return differences
    if expected != actual:
        return [f"{path}: {expected!r} != {actual!r}"]
    return []


__all__ = [
    "CanonicalEvaluationEnv",
    "MyoAssistMetricsCallback",
    "PROTOCOL_SCHEMA",
    "ProtocolMismatchError",
    "assert_protocol_matches",
    "build_training_protocol",
    "collect_myoassist_metrics",
    "file_sha256",
    "find_run_config",
    "prepare_run_config",
    "protocol_sha256",
]
