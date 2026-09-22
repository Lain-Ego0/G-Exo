"""Collect worn-URDF, zero-assist kinematics for the PPO motion hinge."""

from __future__ import annotations

import argparse
from pathlib import Path

import mujoco
import numpy as np

from RL.env.actor_observation import RESET_PROTOCOL, RESET_WARMUP_STEPS
from RL.env.myoassist.gait_phase import CausalGaitPhase, left_foot_force
from RL.env.myoassist.human_adaptation import make_human_adaptation_env
from RL.env.myoassist.motion_reference import (
    URDF_ZERO_ASSIST_CONDITION,
    fit_motion_reference,
)
from RL.env.myoassist.policy_transfer import FrozenHumanPolicy, file_sha256
from RL.env.myoassist.sensor_adapter import MyoAssistSensorAdapter
from RL.env.myoassist.urdf_attachment import model_has_dynamic_gexo


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_MODEL = (
    PROJECT_ROOT / "RL/assets/myoassist/myoLeg22_2D_GEXO_URDF_DYNAMIC.xml"
)
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/assets/myoassist/urdf_zero_assist_motion_v1.json"
VERIFIED_SPEEDS_M_S = (0.8, 1.0, 1.25)


def parse_csv(value: str, conversion) -> tuple:
    return tuple(conversion(item.strip()) for item in value.split(",") if item.strip())


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--human-checkpoint", type=Path, required=True)
    parser.add_argument("--physical-model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--speeds", default="0.8,1.0,1.25")
    parser.add_argument("--seeds", default="0,1,2")
    parser.add_argument("--reference-indices", default="0")
    parser.add_argument("--warmup-steps", type=int, default=RESET_WARMUP_STEPS)
    parser.add_argument("--steps", type=int, default=500)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    checkpoint = args.human_checkpoint.expanduser().resolve(strict=True)
    physical_model = args.physical_model.expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    if output.suffix.lower() != ".json":
        raise ValueError("Motion-reference output must use a .json suffix.")
    if output.exists() and not args.overwrite:
        raise FileExistsError(f"Motion reference already exists: {output}")
    if args.warmup_steps != RESET_WARMUP_STEPS or args.steps < 1:
        raise ValueError(
            f"Use exactly {RESET_WARMUP_STEPS} warmup steps and positive rollout steps."
        )
    if not model_has_dynamic_gexo(mujoco.MjModel.from_xml_path(str(physical_model))):
        raise ValueError("Motion reference requires the dynamic G-Exo URDF model.")

    speeds = parse_csv(args.speeds, float)
    seeds = parse_csv(args.seeds, int)
    references = parse_csv(args.reference_indices, int)
    if not speeds or not seeds or references != (0,):
        raise ValueError("Use non-empty speeds/seeds and reference-indices=0.")
    if any(speed not in VERIFIED_SPEEDS_M_S for speed in speeds):
        raise ValueError(f"Speeds must be selected from {VERIFIED_SPEEDS_M_S}.")

    policy = FrozenHumanPolicy(checkpoint, device=args.device)
    rows: dict[str, list] = {"speed": [], "gait_phase": [], "joint_q": []}
    episodes: list[dict[str, object]] = []
    for speed in speeds:
        complete_count = 0
        for seed in seeds:
            environment = make_human_adaptation_env(
                seed=seed,
                max_episode_steps=args.warmup_steps + args.steps,
                evaluate=True,
                model_path=physical_model,
                min_target_speed_m_s=speed,
                max_target_speed_m_s=speed,
            )
            observation, _ = environment.reset(
                seed=seed,
                options={"target_speed": speed, "reference_index": 0},
            )
            phase = CausalGaitPhase()
            sensors = MyoAssistSensorAdapter()
            episode_phase: list[float] = []
            episode_q: list[np.ndarray] = []
            warmup_complete = True
            terminated = truncated = False
            try:
                for _ in range(args.warmup_steps):
                    observation, _, terminated, truncated, _ = environment.step(
                        policy(observation)
                    )
                    if terminated or truncated:
                        warmup_complete = False
                        break
                    phase.update(left_foot_force(environment.unwrapped))
                if warmup_complete and not phase.ready:
                    raise RuntimeError("Gait phase was not calibrated during warmup.")
                if warmup_complete:
                    environment.unwrapped.finish_preroll()
                    for _ in range(args.steps):
                        observation, _, terminated, truncated, _ = environment.step(
                            policy(observation)
                        )
                        episode_phase.append(
                            phase.update(left_foot_force(environment.unwrapped))
                        )
                        episode_q.append(
                            sensors.read_state(environment.unwrapped)["motor_q"]
                        )
                        if terminated or truncated:
                            break
            finally:
                environment.close()
            complete = (
                warmup_complete
                and len(episode_phase) == args.steps
                and not terminated
            )
            episodes.append(
                {
                    "speed_m_s": speed,
                    "seed": seed,
                    "reference_index": 0,
                    "steps": len(episode_phase),
                    "complete": complete,
                }
            )
            if complete:
                complete_count += 1
                rows["speed"].extend([speed] * len(episode_phase))
                rows["gait_phase"].extend(episode_phase)
                rows["joint_q"].extend(episode_q)
        if complete_count == 0:
            raise RuntimeError(f"No complete zero-assist URDF rollout at {speed} m/s.")

    model_hash = file_sha256(physical_model)
    reference = fit_motion_reference(
        speed_m_s=np.asarray(rows["speed"]),
        gait_phase=np.asarray(rows["gait_phase"]),
        joint_q_rad=np.asarray(rows["joint_q"]),
        metadata={
            "reference_condition": URDF_ZERO_ASSIST_CONDITION,
            "human_checkpoint": str(checkpoint),
            "human_checkpoint_sha256": file_sha256(checkpoint),
            "physical_model": str(physical_model),
            "physical_model_sha256": model_hash,
            "urdf_enabled": True,
            "domain_randomization_enabled": False,
            "warmup_protocol": RESET_PROTOCOL,
            "warmup_steps": args.warmup_steps,
            "control_hz": 50,
            "episodes": episodes,
            "frames": len(rows["speed"]),
            "statistics": {
                "joint_center": "phase_bin_mean",
                "joint_scale": "max_std_mad_1deg_floor",
                "free_standardized_rmse_percentile": 99.0,
                "transition_standardized_rmse_floor": 1.0,
            },
        },
    )
    saved = reference.save(output)
    raw_output = output.with_suffix(".npz")
    np.savez_compressed(
        raw_output,
        speed=np.asarray(rows["speed"]),
        gait_phase=np.asarray(rows["gait_phase"]),
        joint_q=np.asarray(rows["joint_q"]),
    )
    print(f"motion reference: {saved}")
    print(f"raw frames: {raw_output}")
    print(f"frames: {len(rows['speed'])}")


if __name__ == "__main__":
    main()
