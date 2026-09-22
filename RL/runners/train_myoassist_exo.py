"""Start fresh PPO for the four-output MyoAssist G-Exo policy."""

from __future__ import annotations

import argparse
from functools import partial
import json
from pathlib import Path

import torch
import torch.nn as nn

from RL.env.myoassist.gexo_leg_env import GexoMyoAssistEnv
from RL.env.myoassist.model_builder import (
    PHYSICAL_VARIANT,
    URDF_DYNAMIC_VARIANT,
    URDF_RIGID_VARIANT,
    build_model,
)
from RL.runners.myoassist_training import (
    CanonicalEvaluationEnv,
    MyoAssistMetricsCallback,
    build_training_protocol,
    file_sha256,
    prepare_run_config,
)
from RL.train import train


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_TCN = PROJECT_ROOT / "RL/outputs/tcn_runs/seed_43/best_model.pt"
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/outputs/myoassist_exo_ppo"


def parse_speeds(value: str) -> tuple[float, ...]:
    speeds = tuple(float(item.strip()) for item in value.split(",") if item.strip())
    if not speeds or any(speed <= 0.0 for speed in speeds):
        raise argparse.ArgumentTypeError("Speeds must be positive and non-empty.")
    return speeds


def make_environment(
    *,
    rank: int,
    seed: int,
    human_checkpoint: str,
    baseline: str,
    motion_reference: str,
    tcn_checkpoint: str,
    tcn_calibration: str,
    model_path: str,
    max_episode_steps: int,
    min_speed: float,
    max_speed: float,
    anchor_min_speed: float,
    anchor_max_speed: float,
    lower_speed_probability: float,
    anchor_speed_probability: float,
    upper_speed_probability: float,
    action_scale_nm: float,
    domain_randomization: bool,
) -> GexoMyoAssistEnv:
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    return GexoMyoAssistEnv(
        human_checkpoint=human_checkpoint,
        baseline_path=baseline,
        motion_reference_path=motion_reference,
        tcn_checkpoint=tcn_checkpoint,
        tcn_calibration=tcn_calibration,
        model_path=model_path,
        seed=seed + rank,
        max_episode_steps=max_episode_steps,
        min_speed_m_s=min_speed,
        max_speed_m_s=max_speed,
        anchor_min_speed_m_s=anchor_min_speed,
        anchor_max_speed_m_s=anchor_max_speed,
        lower_speed_probability=lower_speed_probability,
        anchor_speed_probability=anchor_speed_probability,
        upper_speed_probability=upper_speed_probability,
        action_torque_scale_nm=action_scale_nm,
        domain_randomization=domain_randomization,
        human_device="cpu",
        tcn_device="cpu",
    )


def make_canonical_evaluation_environment(
    *,
    evaluation_speed_m_s: float,
    evaluation_seed: int,
    **environment_options,
) -> CanonicalEvaluationEnv:
    environment_options["domain_randomization"] = False
    environment = make_environment(**environment_options)
    return CanonicalEvaluationEnv(
        environment,
        target_speed_m_s=evaluation_speed_m_s,
        reference_index=0,
        seed=evaluation_seed,
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--human-checkpoint", type=Path, required=True)
    parser.add_argument("--baseline", type=Path, required=True)
    parser.add_argument("--motion-reference", type=Path, required=True)
    parser.add_argument("--tcn-checkpoint", type=Path, default=DEFAULT_TCN)
    parser.add_argument("--tcn-calibration", type=Path, required=True)
    parser.add_argument(
        "--model-variant",
        choices=(PHYSICAL_VARIANT, URDF_RIGID_VARIANT, URDF_DYNAMIC_VARIANT),
        default=PHYSICAL_VARIANT,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timesteps", type=int, default=100_000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-episode-steps", type=int, default=1000)
    parser.add_argument("--min-speed", type=float, default=0.8)
    parser.add_argument("--max-speed", type=float, default=1.25)
    parser.add_argument("--anchor-min-speed", type=float)
    parser.add_argument("--anchor-max-speed", type=float)
    parser.add_argument("--lower-speed-probability", type=float, default=0.25)
    parser.add_argument("--anchor-speed-probability", type=float, default=0.50)
    parser.add_argument("--upper-speed-probability", type=float, default=0.25)
    parser.add_argument("--action-scale-nm", type=float, default=8.0)
    parser.add_argument("--domain-randomization", action="store_true")
    parser.add_argument(
        "--allow-domain-randomization-transition",
        action="store_true",
        help="Resume a nominal policy into a randomized curriculum stage.",
    )
    parser.add_argument("--learning-rate", type=float, default=3.0e-4)
    parser.add_argument("--n-steps", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--n-epochs", type=int, default=10)
    parser.add_argument("--log-std-init", type=float, default=-1.0)
    parser.add_argument("--checkpoint-interval", type=int, default=100_000)
    parser.add_argument("--evaluation-interval", type=int, default=50_000)
    parser.add_argument("--evaluation-episodes", type=int, default=1)
    parser.add_argument("--evaluation-speed", type=float, default=1.0)
    parser.add_argument(
        "--evaluation-speeds",
        type=parse_speeds,
        help="Comma-separated canonical speeds; defaults to min, center, max.",
    )
    parser.add_argument("--evaluation-seed", type=int, default=0)
    parser.add_argument("--resume", type=Path)
    parser.add_argument(
        "--initialize-from",
        type=Path,
        help="Copy policy weights into a fresh optimizer and training protocol.",
    )
    parser.add_argument(
        "--allow-speed-curriculum-transition",
        action="store_true",
        help="Resume only while widening the calibrated speed range.",
    )
    parser.add_argument("--max-hours", type=float)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    if args.workers < 1 or args.timesteps < 1:
        raise ValueError("workers and timesteps must be positive.")
    if not 0.0 < args.min_speed <= args.max_speed:
        raise ValueError("Speed range must satisfy 0 < min <= max.")
    anchor_min_speed = (
        args.min_speed if args.anchor_min_speed is None else args.anchor_min_speed
    )
    anchor_max_speed = (
        args.max_speed if args.anchor_max_speed is None else args.anchor_max_speed
    )
    if not (
        args.min_speed <= anchor_min_speed
        <= anchor_max_speed <= args.max_speed
    ):
        raise ValueError(
            "Speed ranges must satisfy min <= anchor-min <= anchor-max <= max."
        )
    if args.resume is not None and args.initialize_from is not None:
        raise ValueError("--resume and --initialize-from are mutually exclusive.")
    if args.allow_speed_curriculum_transition and args.resume is None:
        raise ValueError(
            "--allow-speed-curriculum-transition requires --resume."
        )
    if args.allow_domain_randomization_transition and (
        args.resume is None or not args.domain_randomization
    ):
        raise ValueError(
            "--allow-domain-randomization-transition requires both "
            "--resume and --domain-randomization."
        )
    artifacts = {
        "human_checkpoint": args.human_checkpoint.expanduser().resolve(strict=True),
        "baseline": args.baseline.expanduser().resolve(strict=True),
        "motion_reference": args.motion_reference.expanduser().resolve(strict=True),
        "tcn_checkpoint": args.tcn_checkpoint.expanduser().resolve(strict=True),
        "tcn_calibration": args.tcn_calibration.expanduser().resolve(strict=True),
    }
    model_path = build_model(
        variant=args.model_variant,
    ).expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    resume = (
        None
        if args.resume is None
        else args.resume.expanduser().resolve(strict=True)
    )
    initialize = (
        None
        if args.initialize_from is None
        else args.initialize_from.expanduser().resolve(strict=True)
    )
    evaluation_speeds = tuple(
        sorted(
            set(
                args.evaluation_speeds
                or (args.min_speed, args.evaluation_speed, args.max_speed)
            )
        )
    )
    effective_evaluation_episodes = max(
        args.evaluation_episodes,
        len(evaluation_speeds),
    )
    ppo_parameters = {
        "learning_rate": args.learning_rate,
        "n_steps": args.n_steps,
        "batch_size": args.batch_size,
        "n_epochs": args.n_epochs,
        "gamma": 0.99,
        "gae_lambda": 0.95,
        "policy_kwargs": {
            "activation_fn": nn.Tanh,
            "log_std_init": args.log_std_init,
            "net_arch": {"pi": [128, 64], "vf": [128, 64]},
        },
    }
    protocol = build_training_protocol(
        human_checkpoint=artifacts["human_checkpoint"],
        baseline_path=artifacts["baseline"],
        motion_reference_path=artifacts["motion_reference"],
        tcn_checkpoint=artifacts["tcn_checkpoint"],
        tcn_calibration_path=artifacts["tcn_calibration"],
        model_path=model_path,
        min_speed_m_s=args.min_speed,
        max_speed_m_s=args.max_speed,
        anchor_min_speed_m_s=anchor_min_speed,
        anchor_max_speed_m_s=anchor_max_speed,
        lower_speed_probability=args.lower_speed_probability,
        anchor_speed_probability=args.anchor_speed_probability,
        upper_speed_probability=args.upper_speed_probability,
        action_scale_nm=args.action_scale_nm,
        max_episode_steps=args.max_episode_steps,
        workers=args.workers,
        seed=args.seed,
        ppo_parameters=ppo_parameters,
        evaluation_speed_m_s=args.evaluation_speed,
        evaluation_seed=args.evaluation_seed,
        domain_randomization_enabled=args.domain_randomization,
        evaluation_speeds_m_s=evaluation_speeds,
    )
    prepare_run_config(
        output_dir=output,
        protocol=protocol,
        resume_from=resume,
        allow_domain_randomization_enable=(
            args.allow_domain_randomization_transition
        ),
        allow_speed_curriculum_widening=(
            args.allow_speed_curriculum_transition
        ),
        launch={
            "timesteps": args.timesteps,
            "max_hours": args.max_hours,
            "device": args.device,
            "checkpoint_interval": args.checkpoint_interval,
            "evaluation_interval": args.evaluation_interval,
            "evaluation_episodes": effective_evaluation_episodes,
            "resume_from": None if resume is None else str(resume),
            "resume_from_sha256": (
                None if resume is None else file_sha256(resume)
            ),
            "initialize_from": None if initialize is None else str(initialize),
            "initialize_from_sha256": (
                None if initialize is None else file_sha256(initialize)
            ),
            "allow_domain_randomization_transition": (
                args.allow_domain_randomization_transition
            ),
            "allow_speed_curriculum_transition": (
                args.allow_speed_curriculum_transition
            ),
            "artifact_paths": {
                name: str(path) for name, path in artifacts.items()
            },
            "physical_model_path": str(model_path),
            "model_variant": args.model_variant,
        },
    )
    frozen_paths = {
        "human_checkpoint": artifacts["human_checkpoint"],
        "tcn_checkpoint": artifacts["tcn_checkpoint"],
    }
    frozen_hashes_before = {
        name: file_sha256(path) for name, path in frozen_paths.items()
    }
    factories = [
        partial(
            make_environment,
            rank=rank,
            seed=args.seed,
            human_checkpoint=str(artifacts["human_checkpoint"]),
            baseline=str(artifacts["baseline"]),
            motion_reference=str(artifacts["motion_reference"]),
            tcn_checkpoint=str(artifacts["tcn_checkpoint"]),
            tcn_calibration=str(artifacts["tcn_calibration"]),
            model_path=str(model_path),
            max_episode_steps=args.max_episode_steps,
            min_speed=args.min_speed,
            max_speed=args.max_speed,
            anchor_min_speed=anchor_min_speed,
            anchor_max_speed=anchor_max_speed,
            lower_speed_probability=args.lower_speed_probability,
            anchor_speed_probability=args.anchor_speed_probability,
            upper_speed_probability=args.upper_speed_probability,
            action_scale_nm=args.action_scale_nm,
            domain_randomization=args.domain_randomization,
        )
        for rank in range(args.workers)
    ]
    eval_factory = [
        partial(
            make_canonical_evaluation_environment,
            rank=10_000 + index,
            seed=args.seed,
            evaluation_speed_m_s=speed,
            evaluation_seed=args.evaluation_seed,
            human_checkpoint=str(artifacts["human_checkpoint"]),
            baseline=str(artifacts["baseline"]),
            motion_reference=str(artifacts["motion_reference"]),
            tcn_checkpoint=str(artifacts["tcn_checkpoint"]),
            tcn_calibration=str(artifacts["tcn_calibration"]),
            model_path=str(model_path),
            max_episode_steps=args.max_episode_steps,
            min_speed=speed,
            max_speed=speed,
            anchor_min_speed=speed,
            anchor_max_speed=speed,
            lower_speed_probability=args.lower_speed_probability,
            anchor_speed_probability=args.anchor_speed_probability,
            upper_speed_probability=args.upper_speed_probability,
            action_scale_nm=args.action_scale_nm,
            domain_randomization=False,
        )
        for index, speed in enumerate(evaluation_speeds)
    ]
    model = None
    try:
        model = train(
            factories,
            eval_env_factory=eval_factory,
            output_dir=output,
            resume_from=resume,
            initialize_from=initialize,
            total_timesteps=args.timesteps,
            num_envs=args.workers,
            seed=args.seed,
            checkpoint_interval=args.checkpoint_interval,
            evaluation_interval=args.evaluation_interval,
            evaluation_episodes=effective_evaluation_episodes,
            device=args.device,
            ppo_parameters=ppo_parameters,
            max_hours=args.max_hours,
            additional_callbacks=[MyoAssistMetricsCallback()],
        )
    finally:
        frozen_hashes_after = {
            name: file_sha256(path) for name, path in frozen_paths.items()
        }
        integrity = {
            "protocol_sha256": protocol["sha256"],
            "before": frozen_hashes_before,
            "after": frozen_hashes_after,
            "unchanged": frozen_hashes_before == frozen_hashes_after,
        }
        (output / "frozen_artifact_integrity.json").write_text(
            json.dumps(integrity, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        if not integrity["unchanged"]:
            raise RuntimeError("Frozen human or TCN checkpoint changed during training.")
    print(f"model: {model}")
    print(f"tensorboard: {output / 'tensorboard'}")


if __name__ == "__main__":
    main()
