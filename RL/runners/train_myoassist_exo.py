"""Start fresh PPO for the four-output MyoAssist G-Exo policy."""

from __future__ import annotations

import argparse
from functools import partial
import json
from pathlib import Path

import torch
import torch.nn as nn

from RL.env.myoassist.gexo_leg_env import GexoMyoAssistEnv
from RL.env.myoassist.model_builder import build_model
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


def make_environment(
    *,
    rank: int,
    seed: int,
    human_checkpoint: str,
    baseline: str,
    tcn_checkpoint: str,
    tcn_calibration: str,
    model_path: str,
    max_episode_steps: int,
    min_speed: float,
    max_speed: float,
    action_scale_nm: float,
) -> GexoMyoAssistEnv:
    torch.set_num_threads(1)
    if torch.get_num_interop_threads() != 1:
        torch.set_num_interop_threads(1)
    return GexoMyoAssistEnv(
        human_checkpoint=human_checkpoint,
        baseline_path=baseline,
        tcn_checkpoint=tcn_checkpoint,
        tcn_calibration=tcn_calibration,
        model_path=model_path,
        seed=seed + rank,
        max_episode_steps=max_episode_steps,
        min_speed_m_s=min_speed,
        max_speed_m_s=max_speed,
        action_torque_scale_nm=action_scale_nm,
        human_device="cpu",
        tcn_device="cpu",
    )


def make_canonical_evaluation_environment(
    *,
    evaluation_speed_m_s: float,
    evaluation_seed: int,
    **environment_options,
) -> CanonicalEvaluationEnv:
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
    parser.add_argument("--tcn-checkpoint", type=Path, default=DEFAULT_TCN)
    parser.add_argument("--tcn-calibration", type=Path, required=True)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--timesteps", type=int, default=100_000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--max-episode-steps", type=int, default=1000)
    parser.add_argument("--min-speed", type=float, default=0.8)
    parser.add_argument("--max-speed", type=float, default=1.25)
    parser.add_argument("--action-scale-nm", type=float, default=8.0)
    parser.add_argument("--learning-rate", type=float, default=3.0e-4)
    parser.add_argument("--n-steps", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=256)
    parser.add_argument("--n-epochs", type=int, default=10)
    parser.add_argument("--log-std-init", type=float, default=-1.0)
    parser.add_argument("--checkpoint-interval", type=int, default=100_000)
    parser.add_argument("--evaluation-interval", type=int, default=50_000)
    parser.add_argument("--evaluation-episodes", type=int, default=1)
    parser.add_argument("--evaluation-speed", type=float, default=1.0)
    parser.add_argument("--evaluation-seed", type=int, default=0)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--max-hours", type=float)
    parser.add_argument("--device", default="cpu")
    args = parser.parse_args()

    if args.workers < 1 or args.timesteps < 1:
        raise ValueError("workers and timesteps must be positive.")
    if not 0.0 < args.min_speed <= args.max_speed:
        raise ValueError("Speed range must satisfy 0 < min <= max.")
    artifacts = {
        "human_checkpoint": args.human_checkpoint.expanduser().resolve(strict=True),
        "baseline": args.baseline.expanduser().resolve(strict=True),
        "tcn_checkpoint": args.tcn_checkpoint.expanduser().resolve(strict=True),
        "tcn_calibration": args.tcn_calibration.expanduser().resolve(strict=True),
    }
    model_path = build_model().expanduser().resolve(strict=True)
    output = args.output.expanduser().resolve()
    resume = (
        None
        if args.resume is None
        else args.resume.expanduser().resolve(strict=True)
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
        tcn_checkpoint=artifacts["tcn_checkpoint"],
        tcn_calibration_path=artifacts["tcn_calibration"],
        model_path=model_path,
        min_speed_m_s=args.min_speed,
        max_speed_m_s=args.max_speed,
        action_scale_nm=args.action_scale_nm,
        max_episode_steps=args.max_episode_steps,
        workers=args.workers,
        seed=args.seed,
        ppo_parameters=ppo_parameters,
        evaluation_speed_m_s=args.evaluation_speed,
        evaluation_seed=args.evaluation_seed,
    )
    prepare_run_config(
        output_dir=output,
        protocol=protocol,
        resume_from=resume,
        launch={
            "timesteps": args.timesteps,
            "max_hours": args.max_hours,
            "device": args.device,
            "checkpoint_interval": args.checkpoint_interval,
            "evaluation_interval": args.evaluation_interval,
            "evaluation_episodes": args.evaluation_episodes,
            "resume_from": None if resume is None else str(resume),
            "artifact_paths": {
                name: str(path) for name, path in artifacts.items()
            },
            "physical_model_path": str(model_path),
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
            tcn_checkpoint=str(artifacts["tcn_checkpoint"]),
            tcn_calibration=str(artifacts["tcn_calibration"]),
            model_path=str(model_path),
            max_episode_steps=args.max_episode_steps,
            min_speed=args.min_speed,
            max_speed=args.max_speed,
            action_scale_nm=args.action_scale_nm,
        )
        for rank in range(args.workers)
    ]
    eval_factory = partial(
        make_canonical_evaluation_environment,
        rank=10_000,
        seed=args.seed,
        evaluation_speed_m_s=args.evaluation_speed,
        evaluation_seed=args.evaluation_seed,
        human_checkpoint=str(artifacts["human_checkpoint"]),
        baseline=str(artifacts["baseline"]),
        tcn_checkpoint=str(artifacts["tcn_checkpoint"]),
        tcn_calibration=str(artifacts["tcn_calibration"]),
        model_path=str(model_path),
        max_episode_steps=args.max_episode_steps,
        min_speed=args.evaluation_speed,
        max_speed=args.evaluation_speed,
        action_scale_nm=args.action_scale_nm,
    )
    model = None
    try:
        model = train(
            factories,
            eval_env_factory=eval_factory,
            output_dir=output,
            resume_from=resume,
            total_timesteps=args.timesteps,
            num_envs=args.workers,
            seed=args.seed,
            checkpoint_interval=args.checkpoint_interval,
            evaluation_interval=args.evaluation_interval,
            evaluation_episodes=args.evaluation_episodes,
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
