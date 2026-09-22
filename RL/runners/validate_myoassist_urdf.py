"""Validate naked/URDF gait consistency and four physical torque paths."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.env.actor_observation import RESET_WARMUP_STEPS
from RL.env.myoassist.gexo_leg_env import PLANT_TORQUE_SCALE_NM
from RL.env.myoassist.human_runtime import make_human_runtime
from RL.env.myoassist.model_builder import (
    DEFAULT_PHYSICAL_OUTPUT_PATH,
    DEFAULT_URDF_DYNAMIC_OUTPUT_PATH,
)
from RL.env.myoassist.policy_transfer import FrozenHumanPolicy, file_sha256
from RL.env.myoassist.sensor_adapter import JOINT_SPECS
from RL.metrics.trajectory import constrained_dtw_rmse


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/outputs/myoassist_urdf_validation.json"
JOINT_NAMES = ("left_hip", "left_knee", "right_hip", "right_knee")


def rollout(
    policy: FrozenHumanPolicy,
    *,
    model_path: Path,
    speed_m_s: float,
    seed: int,
    steps: int,
    pulse_joint: int | None = None,
    pulse_nm: float = 0.0,
    pulse_start: int = 20,
    pulse_steps: int = 5,
) -> dict[str, object]:
    environment = make_human_runtime(
        seed=seed,
        max_episode_steps=RESET_WARMUP_STEPS + steps,
        evaluate=True,
        model_path=model_path,
    )
    observation, _ = environment.reset(
        seed=seed,
        options={"target_speed": speed_m_s, "reference_index": 0},
    )
    q: list[np.ndarray] = []
    dq: list[np.ndarray] = []
    ctrl: list[np.ndarray] = []
    speed: list[float] = []
    reason = "evaluation_horizon"

    def step(target_torque: np.ndarray):
        human_action = policy(observation_holder[0])
        combined = np.concatenate(
            (human_action, target_torque / PLANT_TORQUE_SCALE_NM)
        ).astype(np.float32)
        result = environment.step(combined)
        observation_holder[0] = result[0]
        return result[2], result[3]

    observation_holder = [observation]
    try:
        zero = np.zeros(4, dtype=np.float32)
        for _ in range(RESET_WARMUP_STEPS):
            terminated, truncated = step(zero)
            if terminated or truncated:
                reason = "warmup_failed"
                break
        else:
            environment.finish_preroll()
            for index in range(steps):
                torque = zero.copy()
                if (
                    pulse_joint is not None
                    and pulse_start <= index < pulse_start + pulse_steps
                ):
                    torque[pulse_joint] = pulse_nm
                terminated, truncated = step(torque)
                simulation = environment.sim
                q.append(
                    np.asarray(
                        [
                            spec.sign
                            * float(simulation.data.joint(spec.name).qpos[0])
                            for spec in JOINT_SPECS
                        ]
                    )
                )
                dq.append(
                    np.asarray(
                        [
                            spec.sign
                            * float(simulation.data.joint(spec.name).qvel[0])
                            for spec in JOINT_SPECS
                        ]
                    )
                )
                ctrl.append(np.asarray(simulation.data.ctrl[-4:]).copy())
                speed.append(
                    float(simulation.data.joint("pelvis_tx").qvel[0])
                )
                if terminated:
                    reason = "terminated"
                    break
                if truncated:
                    reason = "truncated"
                    break
    finally:
        environment.close()
    return {
        "q": np.asarray(q),
        "dq": np.asarray(dq),
        "ctrl": np.asarray(ctrl),
        "speed": np.asarray(speed),
        "steps": len(q),
        "success": len(q) == steps and reason == "evaluation_horizon",
        "reason": reason,
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--human-checkpoint", type=Path, required=True)
    parser.add_argument(
        "--reference-model", type=Path, default=DEFAULT_PHYSICAL_OUTPUT_PATH
    )
    parser.add_argument(
        "--urdf-model", type=Path, default=DEFAULT_URDF_DYNAMIC_OUTPUT_PATH
    )
    parser.add_argument("--speeds", default="0.8,1.0,1.25")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--steps", type=int, default=300)
    parser.add_argument("--pulse-nm", type=float, default=1.0)
    parser.add_argument("--pulse-start", type=int, default=20)
    parser.add_argument("--pulse-steps", type=int, default=5)
    parser.add_argument("--movement-rmse-rad", type=float, default=0.15)
    parser.add_argument("--speed-delta-m-s", type=float, default=0.15)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--require-pass", action="store_true")
    args = parser.parse_args()

    checkpoint = args.human_checkpoint.expanduser().resolve(strict=True)
    reference_model = args.reference_model.expanduser().resolve(strict=True)
    urdf_model = args.urdf_model.expanduser().resolve(strict=True)
    policy = FrozenHumanPolicy(checkpoint, device=args.device)
    speeds = tuple(float(value) for value in args.speeds.split(","))

    consistency = []
    for speed in speeds:
        naked = rollout(
            policy,
            model_path=reference_model,
            speed_m_s=speed,
            seed=args.seed,
            steps=args.steps,
        )
        urdf = rollout(
            policy,
            model_path=urdf_model,
            speed_m_s=speed,
            seed=args.seed,
            steps=args.steps,
        )
        equal = naked["q"].shape == urdf["q"].shape and naked["q"].size > 0
        rmse = (
            float(np.sqrt(np.mean(np.square(urdf["q"] - naked["q"]))))
            if equal else None
        )
        aligned_rmse = (
            constrained_dtw_rmse(naked["q"], urdf["q"])
            if equal else None
        )
        speed_delta = (
            abs(float(np.mean(urdf["speed"])) - float(np.mean(naked["speed"])))
            if naked["speed"].size and urdf["speed"].size else None
        )
        row = {
            "speed_m_s": speed,
            "naked_success": naked["success"],
            "urdf_success": urdf["success"],
            "naked_steps": naked["steps"],
            "urdf_steps": urdf["steps"],
            "joint_rmse_rad": rmse,
            "phase_aligned_joint_rmse_rad": aligned_rmse,
            "absolute_speed_delta_m_s": speed_delta,
            "naked_mean_speed_m_s": (
                float(np.mean(naked["speed"])) if naked["speed"].size else None
            ),
            "urdf_mean_speed_m_s": (
                float(np.mean(urdf["speed"])) if urdf["speed"].size else None
            ),
            "passed": bool(
                naked["success"]
                and urdf["success"]
                and aligned_rmse is not None
                and aligned_rmse <= args.movement_rmse_rad
                and speed_delta is not None
                and speed_delta <= args.speed_delta_m_s
            ),
        }
        consistency.append(row)
        print(
            f"speed={speed:.2f} naked={naked['success']} urdf={urdf['success']} "
            f"joint_rmse={rmse} aligned_rmse={aligned_rmse} "
            f"speed_delta={speed_delta}"
        )

    pulse_baseline = rollout(
        policy,
        model_path=urdf_model,
        speed_m_s=1.0,
        seed=args.seed,
        steps=args.steps,
    )
    pulses = []
    pulse_slice = slice(args.pulse_start, args.pulse_start + args.pulse_steps)
    for joint, name in enumerate(JOINT_NAMES):
        positive = rollout(
            policy,
            model_path=urdf_model,
            speed_m_s=1.0,
            seed=args.seed,
            steps=args.steps,
            pulse_joint=joint,
            pulse_nm=abs(args.pulse_nm),
            pulse_start=args.pulse_start,
            pulse_steps=args.pulse_steps,
        )
        negative = rollout(
            policy,
            model_path=urdf_model,
            speed_m_s=1.0,
            seed=args.seed,
            steps=args.steps,
            pulse_joint=joint,
            pulse_nm=-abs(args.pulse_nm),
            pulse_start=args.pulse_start,
            pulse_steps=args.pulse_steps,
        )
        enough = all(
            run["steps"] >= args.pulse_start + args.pulse_steps
            for run in (pulse_baseline, positive, negative)
        )
        response = (
            float(
                (
                    positive["dq"][args.pulse_start, joint]
                    - negative["dq"][args.pulse_start, joint]
                ) / 2.0
            )
            if enough else None
        )
        closed_loop_response = (
            float(
                np.mean(
                    positive["dq"][pulse_slice, joint]
                    - negative["dq"][pulse_slice, joint]
                ) / 2.0
            )
            if enough else None
        )
        applied = (
            float(np.mean(positive["ctrl"][pulse_slice, joint]))
            if enough else None
        )
        row = {
            "joint": name,
            "pulse_nm": abs(args.pulse_nm),
            "mean_applied_positive_nm": applied,
            "signed_velocity_response_rad_s": response,
            "closed_loop_mean_velocity_response_rad_s": closed_loop_response,
            "passed": bool(
                enough
                and applied is not None
                and np.isclose(applied, abs(args.pulse_nm), atol=1.0e-5)
                and response is not None
                and response > 1.0e-5
            ),
        }
        pulses.append(row)
        print(
            f"{name:12s} applied={applied} response={response} "
            f"passed={row['passed']}"
        )

    report = {
        "schema": "gexo_myoassist_urdf_validation_v1",
        "human_checkpoint": str(checkpoint),
        "human_checkpoint_sha256": file_sha256(checkpoint),
        "reference_model": str(reference_model),
        "reference_model_sha256": file_sha256(reference_model),
        "urdf_model": str(urdf_model),
        "urdf_model_sha256": file_sha256(urdf_model),
        "movement_rmse_tolerance_rad": args.movement_rmse_rad,
        "speed_delta_tolerance_m_s": args.speed_delta_m_s,
        "consistency": consistency,
        "pulses": pulses,
        "all_passed": all(row["passed"] for row in consistency + pulses),
    }
    output = args.output.expanduser().resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    print(f"all passed: {report['all_passed']}")
    print(f"report: {output}")
    if args.require_pass and not report["all_passed"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
