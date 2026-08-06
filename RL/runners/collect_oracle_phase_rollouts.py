"""Collect paired zero-assistance and phase-targeted pulse rollouts."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.env.kinesis.oracle_phase import extract_oracle_phase


CONTROL_DT = 0.02
PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/outputs/oracle_phase_audit/traces"
DEFAULT_BASELINE_DIR = (
    PROJECT_ROOT / "RL/outputs/kinesis_physical_baseline_v2"
)


def parse_csv(text: str, converter) -> tuple:
    return tuple(
        converter(item.strip())
        for item in text.split(",")
        if item.strip()
    )


def collect_trace(
    environment,
    *,
    seed: int,
    pulse_start_step: int | None = None,
    pulse_joint: int = -1,
    pulse_nm: float = 0.0,
    pulse_steps: int = 0,
) -> dict[str, np.ndarray | float | int | bool]:
    """Collect one deterministic trace from the physical exoskeleton env."""

    _, reset_info = environment.reset(seed=seed)
    time_s = []
    touch = []
    activation_cost = []
    muscle_torque_cost = []
    same_state_saving = []
    tracking_mse = []
    reward = []
    exo_torque = []
    joint_position = []
    joint_velocity = []
    sensor_frame = []
    terminated = False
    truncated = False
    termination_reason = "running"

    for step in range(environment.max_episode_steps):
        target_torque = np.zeros(4, dtype=np.float32)
        pulse_active = (
            pulse_start_step is not None
            and pulse_start_step <= step < pulse_start_step + pulse_steps
        )
        if pulse_active:
            target_torque[pulse_joint] = pulse_nm
        action = np.clip(
            target_torque / environment.action_torque_scale_nm,
            -1.0,
            1.0,
        ).astype(np.float32)

        _, step_reward, terminated, truncated, info = environment.step(action)
        current_touch = np.asarray(
            environment.agent.env.get_touch(), dtype=np.float64
        ).reshape(-1)
        if current_touch.size < 4:
            raise RuntimeError("Kinesis returned fewer than four touch sensors.")

        metrics = info.get("reward_metrics", {})
        time_s.append(float(info["time_s"]))
        touch.append(current_touch[:4].copy())
        activation_cost.append(float(info.get("target_activation_cost", np.nan)))
        muscle_torque_cost.append(
            float(info.get("muscle_effort_torque_cost", np.nan))
        )
        same_state_saving.append(
            float(metrics.get("activation_saving", np.nan))
        )
        tracking_mse.append(float(info.get("tracking_mse", np.nan)))
        reward.append(float(step_reward))
        exo_torque.append(
            np.asarray(info.get("exo_torque", np.full(4, np.nan))).copy()
        )
        joint_position.append(
            np.asarray(info.get("joint_position", np.full(4, np.nan))).copy()
        )
        joint_velocity.append(
            np.asarray(info.get("joint_velocity", np.full(4, np.nan))).copy()
        )
        sensor_frame.append(environment.latest_raw_sensor_frame)
        termination_reason = str(info.get("termination_reason", "unknown"))

        if terminated or truncated:
            break

    return {
        "seed": int(reset_info["episode_seed"]),
        "success": bool(truncated and not terminated),
        "terminated": bool(terminated),
        "truncated": bool(truncated),
        "termination_reason": termination_reason,
        "time_s": np.asarray(time_s, dtype=np.float64),
        "touch": np.asarray(touch, dtype=np.float64),
        "activation_cost": np.asarray(activation_cost, dtype=np.float64),
        "muscle_torque_cost": np.asarray(
            muscle_torque_cost, dtype=np.float64
        ),
        "same_state_saving": np.asarray(
            same_state_saving, dtype=np.float64
        ),
        "tracking_mse": np.asarray(tracking_mse, dtype=np.float64),
        "reward": np.asarray(reward, dtype=np.float64),
        "exo_torque": np.asarray(exo_torque, dtype=np.float64),
        "joint_position": np.asarray(joint_position, dtype=np.float64),
        "joint_velocity": np.asarray(joint_velocity, dtype=np.float64),
        # Deployable 32-D motor/IMU observation.  Touch sensors are stored
        # separately and are used only to create offline supervision labels.
        "sensor_frame": np.asarray(sensor_frame, dtype=np.float32),
    }


def save_trace(
    path: Path,
    trace: dict,
    *,
    motion_id: int,
    kind: str,
    pulse_start_step: int,
    pulse_joint: int,
    pulse_nm: float,
    pulse_steps: int,
    target_phase: float,
    contact_on_threshold: float,
    contact_off_threshold: float,
) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        **trace,
        motion_id=int(motion_id),
        kind=str(kind),
        pulse_start_step=int(pulse_start_step),
        pulse_joint=int(pulse_joint),
        pulse_nm=float(pulse_nm),
        pulse_steps=int(pulse_steps),
        target_phase=float(target_phase),
        control_dt=CONTROL_DT,
        contact_on_threshold=float(contact_on_threshold),
        contact_off_threshold=float(contact_off_threshold),
    )


def pulse_file_name(
    *,
    motion_id: int,
    seed: int,
    target_phase: float,
    joint: int,
    pulse_nm: float,
) -> str:
    phase_code = int(round(1000.0 * target_phase))
    torque_code = int(round(1000.0 * abs(pulse_nm)))
    sign = "p" if pulse_nm >= 0.0 else "n"
    return (
        f"motion_{motion_id:03d}_seed_{seed:06d}_"
        f"phase_{phase_code:04d}_joint_{joint}_{sign}{torque_code:05d}.npz"
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-id", type=int, default=8)
    parser.add_argument(
        "--seeds",
        default="",
        help="Comma-separated baseline seeds; empty selects up to three available.",
    )
    parser.add_argument("--phases", default="0.25,0.75")
    parser.add_argument("--joints", default="0,1,2,3")
    parser.add_argument("--pulse-nm", default="1.0,2.0")
    parser.add_argument("--pulse-steps", type=int, default=4)
    parser.add_argument("--cycle-ordinal", type=int, default=1)
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--warmup-steps", type=int, default=25)
    parser.add_argument("--torque-limit-nm", type=float, default=17.0)
    parser.add_argument("--torque-rate-limit-nm-s", type=float, default=50.0)
    parser.add_argument("--baseline-dir", type=Path, default=DEFAULT_BASELINE_DIR)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    phases = parse_csv(args.phases, float)
    joints = parse_csv(args.joints, int)
    magnitudes = parse_csv(args.pulse_nm, float)
    if any(not 0.0 <= phase < 1.0 for phase in phases):
        raise ValueError("Target phases must be in [0, 1).")
    if any(joint not in range(4) for joint in joints):
        raise ValueError("Joint indices must be 0, 1, 2, or 3.")
    if any(value <= 0.0 for value in magnitudes):
        raise ValueError("Pulse magnitudes must be positive.")
    if args.pulse_steps < 1 or args.cycle_ordinal < 0:
        raise ValueError("Pulse duration and cycle ordinal are invalid.")

    # Importing the simulator is deliberately delayed so analysis and unit
    # tests remain usable on machines without the legacy Kinesis environment.
    try:
        from RL.env.kinesis.exo_env import KinesisExoEnv
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "The collector must run inside the configured Kinesis environment; "
            f"missing Python dependency: {error.name}."
        ) from error

    environment = KinesisExoEnv(
        motion_id=args.motion_id,
        baseline_dir=args.baseline_dir,
        torque_limit_nm=args.torque_limit_nm,
        action_torque_scale_nm=args.torque_limit_nm,
        torque_rate_limit_nm_s=args.torque_rate_limit_nm_s,
        warmup_steps=args.warmup_steps,
        max_episode_steps=args.max_steps,
        strict_baseline_seed=True,
        use_tcn=False,
    )
    requested_seeds = parse_csv(args.seeds, int)
    seeds = requested_seeds or tuple(environment.baseline.seeds[:3])
    manifest_entries = []

    try:
        for seed in seeds:
            baseline = collect_trace(environment, seed=seed)
            if not bool(baseline["success"]):
                print(
                    f"rejected baseline motion={args.motion_id:03d} "
                    f"seed={seed:06d} reason={baseline['termination_reason']}"
                )
                continue

            phase = extract_oracle_phase(
                baseline["touch"],
                dt=CONTROL_DT,
            )
            cycle_ids = np.unique(phase.cycle_id[phase.valid])
            if cycle_ids.size <= args.cycle_ordinal:
                print(
                    f"rejected baseline motion={args.motion_id:03d} "
                    f"seed={seed:06d}: only {cycle_ids.size} complete cycles"
                )
                continue
            target_cycle = int(cycle_ids[args.cycle_ordinal])
            baseline_path = args.output / (
                f"motion_{args.motion_id:03d}_seed_{seed:06d}_baseline.npz"
            )
            save_trace(
                baseline_path,
                baseline,
                motion_id=args.motion_id,
                kind="baseline",
                pulse_start_step=-1,
                pulse_joint=-1,
                pulse_nm=0.0,
                pulse_steps=0,
                target_phase=np.nan,
                contact_on_threshold=phase.contact_on_threshold,
                contact_off_threshold=phase.contact_off_threshold,
            )
            manifest_entries.append(str(baseline_path.resolve()))

            cycle_steps = np.flatnonzero(phase.cycle_id == target_cycle)
            for target_phase in phases:
                phase_error = np.abs(phase.phase[cycle_steps] - target_phase)
                pulse_start = int(cycle_steps[int(np.argmin(phase_error))])
                for joint in joints:
                    for magnitude in magnitudes:
                        for pulse_nm in (magnitude, -magnitude):
                            trace = collect_trace(
                                environment,
                                seed=seed,
                                pulse_start_step=pulse_start,
                                pulse_joint=joint,
                                pulse_nm=pulse_nm,
                                pulse_steps=args.pulse_steps,
                            )
                            output_path = args.output / pulse_file_name(
                                motion_id=args.motion_id,
                                seed=seed,
                                target_phase=target_phase,
                                joint=joint,
                                pulse_nm=pulse_nm,
                            )
                            save_trace(
                                output_path,
                                trace,
                                motion_id=args.motion_id,
                                kind="pulse",
                                pulse_start_step=pulse_start,
                                pulse_joint=joint,
                                pulse_nm=pulse_nm,
                                pulse_steps=args.pulse_steps,
                                target_phase=target_phase,
                                contact_on_threshold=phase.contact_on_threshold,
                                contact_off_threshold=phase.contact_off_threshold,
                            )
                            manifest_entries.append(str(output_path.resolve()))
                            peak = float(np.nanmax(np.abs(trace["exo_torque"])))
                            print(
                                f"motion={args.motion_id:03d} seed={seed:06d} "
                                f"phase={target_phase:.2f} joint={joint} "
                                f"pulse={pulse_nm:+.2f} Nm peak={peak:.2f} Nm "
                                f"success={trace['success']}"
                            )
    finally:
        environment.close()

    manifest = {
        "motion_id": args.motion_id,
        "seeds": list(seeds),
        "phases": list(phases),
        "joints": list(joints),
        "pulse_nm": list(magnitudes),
        "pulse_steps": args.pulse_steps,
        "control_dt": CONTROL_DT,
        "files": manifest_entries,
    }
    args.output.mkdir(parents=True, exist_ok=True)
    manifest_path = args.output / f"motion_{args.motion_id:03d}_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )
    print("manifest:", manifest_path.resolve())


if __name__ == "__main__":
    main()
