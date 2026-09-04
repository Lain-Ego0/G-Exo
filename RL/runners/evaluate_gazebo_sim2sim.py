"""Run a frozen G-Exo Actor on a fixed-base Gazebo/ODE assistance bench."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import numpy as np

from RL.env.actor_observation import (
    ACTOR_OBSERVATION_DIM,
    ACTOR_OBSERVATION_PROTOCOL,
    JOINT_ORDER,
    RESET_PROTOCOL,
    ActorObservationBuilder,
)
from RL.env.gazebo.bench import (
    GaitCycleReference,
    GazeboSensorAssembler,
    build_fixed_bench_urdf,
    deployment_to_urdf,
)
from RL.env.gazebo.ros_backend import GazeboLauncher, GazeboRosBackend
from RL.env.sensors import SensorReader
from RL.env.torque import TorqueActuator
from RL.runners.evaluate_myoassist_kinesis_sim2sim import (
    file_sha256,
    find_source_protocol,
)
from RL.runners.policy_load_compat import (
    load_ppo_for_inference,
    saved_space_shapes,
)
from RL.runners.predictors.tcn_runtime import FrozenTCNRuntime


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = (
    PROJECT_ROOT
    / "RL/outputs/myoassist_urdf_phasefree_dr_fixed_1ms_1m"
    / "best_model/best_model.zip"
)
DEFAULT_TCN = PROJECT_ROOT / "RL/outputs/tcn_runs/seed_43/best_model.pt"
DEFAULT_CALIBRATION = (
    PROJECT_ROOT / "RL/assets/tcn/myoassist_urdf_dynamic_stiff_cuff_v5.json"
)
DEFAULT_REFERENCE = (
    PROJECT_ROOT / "RL/assets/myoassist/urdf_zero_assist_motion_stiff_cuff_v1.json"
)
DEFAULT_URDF = PROJECT_ROOT / "1.hardware/G-exo_URDF/urdf/G-exo.urdf"
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/outputs/gazebo_sim2sim/report.json"

CONTROL_DT = 0.02
SUPPORTED_MODES = ("baseline", "policy")
REPORT_SCHEMA = "gexo_gazebo_fixed_bench_sim2sim_v1"


def validate_contract(
    model_path: Path,
    tcn_checkpoint: Path,
    calibration: Path,
) -> dict[str, Any]:
    config_path, protocol = find_source_protocol(model_path)
    observation = protocol.get("observation", {})
    action = protocol.get("action_and_safety", {})
    reset = protocol.get("reset", {})
    if protocol.get("backend") != "myoassist":
        raise ValueError("Gazebo audit requires a MyoAssist source policy.")
    if (
        observation.get("dimension") != ACTOR_OBSERVATION_DIM
        or observation.get("protocol") != ACTOR_OBSERVATION_PROTOCOL
    ):
        raise ValueError("Source policy does not use the shared 160-D protocol.")
    if tuple(action.get("joint_order", ())) != JOINT_ORDER:
        raise ValueError("Source policy joint order is incompatible.")
    if reset.get("protocol") != RESET_PROTOCOL:
        raise ValueError("Source policy warmup protocol is incompatible.")
    observation_shape, action_shape = saved_space_shapes(model_path)
    if observation_shape != (160,) or action_shape != (4,):
        raise ValueError("Source PPO model must map 160 observations to 4 actions.")
    expected_tcn = protocol.get("artifacts", {}).get("tcn_checkpoint", {}).get(
        "sha256"
    )
    if expected_tcn != file_sha256(tcn_checkpoint):
        raise ValueError("TCN checkpoint differs from the source policy contract.")
    action_scale = float(action["action_scale_nm"])
    hard_limit = np.asarray(action["hard_torque_limit_nm"], dtype=np.float64)
    rate_limit = np.asarray(
        action["torque_rate_limit_nm_s"], dtype=np.float64
    )
    if hard_limit.shape != (4,) or rate_limit.shape != (4,):
        raise ValueError("Source torque limits must contain four joints.")
    return {
        "source_config": str(config_path),
        "source_protocol_sha256": protocol.get("sha256"),
        "source_model_sha256": file_sha256(model_path),
        "tcn_checkpoint_sha256": file_sha256(tcn_checkpoint),
        "tcn_calibration_sha256": file_sha256(calibration),
        "action_scale_nm": action_scale,
        "hard_torque_limit_nm": hard_limit,
        "torque_rate_limit_nm_s": rate_limit,
        "warmup_steps": int(reset["warmup_steps"]),
    }


def run_mode(
    *,
    mode: str,
    backend: GazeboRosBackend,
    model,
    reference: GaitCycleReference,
    tcn_checkpoint: Path,
    calibration: Path,
    contract: dict[str, Any],
    steps: int,
    kp_nm_rad: float,
    kd_nm_s_rad: float,
    driver_limit_nm: float,
    tcn_device: str,
) -> tuple[dict[str, Any], dict[str, np.ndarray]]:
    if mode not in SUPPORTED_MODES:
        raise ValueError(f"Unsupported mode {mode!r}.")
    tcn = FrozenTCNRuntime(
        tcn_checkpoint,
        calibration=calibration,
        device=tcn_device,
        allow_legacy_checkpoint=True,
    )
    observation_builder = ActorObservationBuilder()
    sensor_assembler = GazeboSensorAssembler(control_dt=CONTROL_DT)
    sensor_reader = SensorReader()
    actuator = TorqueActuator(
        torque_limit_nm=contract["hard_torque_limit_nm"],
        torque_rate_limit_nm_s=contract["torque_rate_limit_nm_s"],
        action_torque_scale_nm=np.full(4, contract["action_scale_nm"]),
        control_dt=CONTROL_DT,
    )
    tcn.reset()
    observation_builder.reset()
    sensor_assembler.reset()
    sensor_reader.reset(seed=0)
    actuator.reset()

    initial_q, _ = reference.sample(0)
    backend.reset(initial_q)
    q_urdf, dq_urdf, links = backend.read()
    sensor32 = sensor_reader.read_runtime32(
        state=_sensor_state(sensor_assembler.build(q_urdf, dq_urdf, links))
    )
    observation = None
    previous_action = np.zeros(4, dtype=np.float32)
    traces: dict[str, list] = {
        "q_rad": [],
        "dq_rad_s": [],
        "reference_q_rad": [],
        "driver_torque_nm": [],
        "exo_torque_nm": [],
        "exo_power_w": [],
        "raw_action": [],
        "elapsed_s": [],
    }
    total_steps = contract["warmup_steps"] + steps
    for step_index in range(total_steps):
        reference_q, reference_dq = reference.sample(step_index + 1)
        q = sensor32[:4]
        dq = sensor32[4:8]
        driver_torque = np.clip(
            kp_nm_rad * (reference_q - q) + kd_nm_s_rad * (reference_dq - dq),
            -driver_limit_nm,
            driver_limit_nm,
        ).astype(np.float32)

        evaluating = step_index >= contract["warmup_steps"]
        if mode == "policy" and evaluating:
            if observation is None:
                raise RuntimeError("Actor observation was not primed by warmup.")
            raw_action, _ = model.predict(observation, deterministic=True)
            raw_action = np.asarray(raw_action, dtype=np.float32)
        else:
            raw_action = np.zeros(4, dtype=np.float32)
        exo_torque = actuator.process(raw_action)
        if not evaluating:
            exo_torque.fill(0.0)
        elapsed = backend.step(
            deployment_to_urdf(driver_torque + exo_torque)
        )
        q_urdf, dq_urdf, links = backend.read()
        sensor32 = sensor_reader.read_runtime32(
            state=_sensor_state(
                sensor_assembler.build(
                    q_urdf,
                    dq_urdf,
                    links,
                    elapsed_s=elapsed,
                )
            )
        )
        previous_action = exo_torque / contract["action_scale_nm"]
        tcn.append(sensor32)
        observation_builder.append(sensor32, previous_action)
        if tcn.ready and observation_builder.ready:
            prediction = tcn.predict(sensor32[:4], sensor32[4:8])
            observation = observation_builder.build(prediction.feature16)

        if evaluating:
            traces["q_rad"].append(sensor32[:4].copy())
            traces["dq_rad_s"].append(sensor32[4:8].copy())
            traces["reference_q_rad"].append(reference_q.copy())
            traces["driver_torque_nm"].append(driver_torque.copy())
            traces["exo_torque_nm"].append(exo_torque.copy())
            traces["exo_power_w"].append(exo_torque * sensor32[4:8])
            traces["raw_action"].append(raw_action.copy())
            traces["elapsed_s"].append(elapsed)

    arrays = {name: np.asarray(values, dtype=np.float32) for name, values in traces.items()}
    q_error = arrays["q_rad"] - arrays["reference_q_rad"]
    elapsed = arrays["elapsed_s"][:, None]
    driver_square_integral = float(
        np.sum(np.mean(np.square(arrays["driver_torque_nm"]), axis=1) * arrays["elapsed_s"])
    )
    exo_work = arrays["exo_power_w"] * elapsed
    summary = {
        "mode": mode,
        "steps": int(len(arrays["q_rad"])),
        "finite": bool(all(np.all(np.isfinite(value)) for value in arrays.values())),
        "tracking_rmse_rad": float(np.sqrt(np.mean(np.square(q_error)))),
        "tracking_rmse_by_joint_rad": np.sqrt(
            np.mean(np.square(q_error), axis=0)
        ).tolist(),
        "driver_torque_rms_nm": float(
            np.sqrt(np.mean(np.square(arrays["driver_torque_nm"])))
        ),
        "driver_torque_rms_by_joint_nm": np.sqrt(
            np.mean(np.square(arrays["driver_torque_nm"]), axis=0)
        ).tolist(),
        "driver_torque_square_integral_nm2_s": driver_square_integral,
        "mean_absolute_exo_torque_nm": float(
            np.mean(np.abs(arrays["exo_torque_nm"]))
        ),
        "peak_absolute_exo_torque_nm": float(
            np.max(np.abs(arrays["exo_torque_nm"]))
        ),
        "positive_exo_work_j": float(np.sum(np.maximum(exo_work, 0.0))),
        "negative_exo_work_j": float(np.sum(np.minimum(exo_work, 0.0))),
        "action_saturation_ratio": float(
            np.mean(np.abs(arrays["raw_action"]) >= 0.999)
        ),
        "simulated_duration_s": float(np.sum(arrays["elapsed_s"])),
    }
    return summary, arrays


def compare_runs(baseline: dict[str, Any], policy: dict[str, Any]) -> dict[str, Any]:
    denominator = max(
        float(baseline["driver_torque_square_integral_nm2_s"]), 1.0e-9
    )
    saving = 1.0 - float(
        policy["driver_torque_square_integral_nm2_s"]
    ) / denominator
    baseline_rmse = float(baseline["tracking_rmse_rad"])
    policy_rmse = float(policy["tracking_rmse_rad"])
    tracking_limit = max(1.10 * baseline_rmse, baseline_rmse + 0.02)
    checks = {
        "finite": bool(baseline["finite"] and policy["finite"]),
        "tracking_nondegradation": policy_rmse <= tracking_limit,
        "driver_effort_reduced": saving > 0.0,
        "action_not_saturated": float(policy["action_saturation_ratio"]) <= 0.10,
    }
    return {
        "passed": bool(all(checks.values())),
        "checks": checks,
        "driver_torque_square_saving_fraction": saving,
        "tracking_rmse_delta_rad": policy_rmse - baseline_rmse,
        "tracking_rmse_limit_rad": tracking_limit,
    }


def _sensor_state(frame: np.ndarray) -> dict[str, np.ndarray]:
    return {
        "motor_q": frame[:4],
        "motor_dq": frame[4:8],
        "imu_angular_velocity": frame[8:20].reshape(4, 3),
        "imu_specific_force": frame[20:32].reshape(4, 3),
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--tcn-checkpoint", type=Path, default=DEFAULT_TCN)
    parser.add_argument("--tcn-calibration", type=Path, default=DEFAULT_CALIBRATION)
    parser.add_argument("--motion-reference", type=Path, default=DEFAULT_REFERENCE)
    parser.add_argument("--urdf", type=Path, default=DEFAULT_URDF)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--modes", default="baseline,policy")
    parser.add_argument("--steps", type=int, default=250)
    parser.add_argument("--speed", type=float, default=1.0)
    parser.add_argument("--gait-period-steps", type=int, default=50)
    parser.add_argument("--kp", type=float, default=20.0)
    parser.add_argument("--kd", type=float, default=2.0)
    parser.add_argument("--driver-limit-nm", type=float, default=17.0)
    parser.add_argument("--joint-damping", type=float, default=2.0)
    parser.add_argument("--joint-friction", type=float, default=0.05)
    parser.add_argument("--device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--tcn-device", choices=("cpu", "cuda"), default="cpu")
    parser.add_argument("--ros-port", type=int, default=11318)
    parser.add_argument("--gazebo-port", type=int, default=11348)
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--no-auto-launch", action="store_true")
    parser.add_argument("--contract-only", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    model_path = args.model.expanduser().resolve(strict=True)
    tcn_path = args.tcn_checkpoint.expanduser().resolve(strict=True)
    calibration = args.tcn_calibration.expanduser().resolve(strict=True)
    reference_path = args.motion_reference.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    contract = validate_contract(model_path, tcn_path, calibration)
    print(json.dumps(contract, indent=2, default=_json_default))
    if args.contract_only:
        return
    modes = tuple(value.strip() for value in args.modes.split(",") if value.strip())
    if set(modes) != set(SUPPORTED_MODES):
        raise ValueError("This paired audit requires --modes baseline,policy.")
    fixed_urdf = build_fixed_bench_urdf(
        args.urdf,
        output.parent / "generated/G-exo-fixed-bench.urdf",
        joint_damping=args.joint_damping,
        joint_friction=args.joint_friction,
    )
    reference = GaitCycleReference(
        reference_path,
        speed_m_s=args.speed,
        period_steps=args.gait_period_steps,
        control_dt=CONTROL_DT,
    )
    model = load_ppo_for_inference(model_path, device=args.device)
    launcher = GazeboLauncher(
        output.parent / f"runtime_{output.stem}",
        ros_port=args.ros_port,
        gazebo_port=args.gazebo_port,
        render=args.render,
    )
    backend = None
    traces: dict[str, dict[str, np.ndarray]] = {}
    try:
        if not args.no_auto_launch:
            launcher.start()
        backend = GazeboRosBackend(fixed_urdf, control_dt=CONTROL_DT)
        runs = {}
        for mode in modes:
            summary, mode_traces = run_mode(
                mode=mode,
                backend=backend,
                model=model,
                reference=reference,
                tcn_checkpoint=tcn_path,
                calibration=calibration,
                contract=contract,
                steps=args.steps,
                kp_nm_rad=args.kp,
                kd_nm_s_rad=args.kd,
                driver_limit_nm=args.driver_limit_nm,
                tcn_device=args.tcn_device,
            )
            runs[mode] = summary
            traces[mode] = mode_traces
            print(
                f"{mode:8s} rmse={summary['tracking_rmse_rad']:.4f} rad "
                f"driver={summary['driver_torque_rms_nm']:.3f} Nm "
                f"exo={summary['mean_absolute_exo_torque_nm']:.3f} Nm"
            )
        comparison = compare_runs(runs["baseline"], runs["policy"])
        report = {
            "schema": REPORT_SCHEMA,
            "interpretation": (
                "Cross-engine mechanical assistance audit only. Driver torque is "
                "not muscle activation or a metabolic estimate."
            ),
            "physics_engine": "Gazebo Classic 11 / ODE",
            "bench": "fixed_base_four_joint_periodic_driver",
            "settings": {
                "speed_m_s": args.speed,
                "gait_period_steps": args.gait_period_steps,
                "control_dt_s": CONTROL_DT,
                "steps": args.steps,
                "kp_nm_rad": args.kp,
                "kd_nm_s_rad": args.kd,
                "driver_limit_nm": args.driver_limit_nm,
                "joint_damping": args.joint_damping,
                "joint_friction": args.joint_friction,
            },
            "contract": contract,
            "runs": runs,
            "comparison": comparison,
        }
        output.write_text(
            json.dumps(report, indent=2, default=_json_default), encoding="utf-8"
        )
        np.savez_compressed(
            output.with_suffix(".npz"),
            **{
                f"{mode}_{name}": value
                for mode, mode_traces in traces.items()
                for name, value in mode_traces.items()
            },
        )
        print(
            "driver effort saving: "
            f"{100.0 * comparison['driver_torque_square_saving_fraction']:+.2f}%"
        )
        print(f"passed: {comparison['passed']}")
        print(f"report: {output}")
    finally:
        if backend is not None:
            backend.close()
        if not args.no_auto_launch:
            launcher.close()


def _json_default(value):
    if isinstance(value, np.ndarray):
        return value.tolist()
    if isinstance(value, np.generic):
        return value.item()
    raise TypeError(type(value).__name__)


if __name__ == "__main__":
    main()
