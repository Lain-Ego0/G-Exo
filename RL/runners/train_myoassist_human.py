"""Warm-start and adapt the 22-muscle human policy on the physical G-Exo model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.monitor import Monitor
from stable_baselines3.common.vec_env import DummyVecEnv, SubprocVecEnv, VecEnv

from RL.env.myoassist.human_adaptation import make_human_adaptation_env
from RL.env.myoassist.model_builder import build_model
from RL.env.myoassist.policy_transfer import (
    DEFAULT_HUMAN_CHECKPOINT,
    file_sha256,
    make_human_ppo,
    transfer_released_human_weights,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "RL" / "outputs" / "myoassist_human_adaptation"


def _environment_factory(
    *,
    rank: int,
    seed: int,
    max_episode_steps: int,
    min_speed: float,
    max_speed: float,
    fixed_speed: float | None,
    random_reference_index: bool,
    model_path: Path,
) -> Callable[[], Monitor]:
    def factory() -> Monitor:
        environment = make_human_adaptation_env(
            seed=seed + rank,
            max_episode_steps=max_episode_steps,
            evaluate=False,
            min_target_speed_m_s=min_speed,
            max_target_speed_m_s=max_speed,
            default_target_speed_m_s=fixed_speed,
            random_reference_index=random_reference_index,
            model_path=model_path,
        )
        return Monitor(environment)

    return factory


def make_vector_environment(
    args: argparse.Namespace,
    *,
    model_path: Path,
) -> VecEnv:
    factories = [
        _environment_factory(
            rank=rank,
            seed=args.seed,
            max_episode_steps=args.max_episode_steps,
            min_speed=args.min_speed,
            max_speed=args.max_speed,
            fixed_speed=args.fixed_speed,
            random_reference_index=args.random_reference_index,
            model_path=model_path,
        )
        for rank in range(args.workers)
    ]
    if args.workers == 1:
        return DummyVecEnv(factories)
    return SubprocVecEnv(factories, start_method="spawn")


def _batch_size(rollout_size: int, requested: int) -> int:
    upper = min(rollout_size, requested)
    for candidate in range(upper, 0, -1):
        if rollout_size % candidate == 0:
            return candidate
    raise RuntimeError("Could not select a valid PPO batch size.")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--timesteps", type=int, default=200_000)
    parser.add_argument("--workers", type=int, default=8)
    parser.add_argument("--n-steps", type=int, default=512)
    parser.add_argument("--batch-size", type=int, default=2048)
    parser.add_argument("--n-epochs", type=int, default=10)
    parser.add_argument("--learning-rate", type=float, default=3e-5)
    parser.add_argument("--min-speed", type=float, default=0.8)
    parser.add_argument("--max-speed", type=float, default=1.5)
    parser.add_argument(
        "--fixed-speed",
        type=float,
        help="Use one uniform target speed for a focused adaptation stage.",
    )
    parser.add_argument(
        "--random-reference-index",
        action="store_true",
        help=(
            "Diagnostic only: random q/dq frames lack phase-consistent "
            "muscle activation state."
        ),
    )
    parser.add_argument("--max-episode-steps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--checkpoint-every", type=int, default=50_000)
    parser.add_argument("--source", type=Path, default=DEFAULT_HUMAN_CHECKPOINT)
    parser.add_argument("--resume", type=Path)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    if args.timesteps <= 0 or args.workers <= 0 or args.n_steps <= 0:
        raise ValueError("timesteps, workers and n_steps must be positive.")
    if not 0.0 < args.min_speed <= args.max_speed:
        raise ValueError("Speed bounds must satisfy 0 < min <= max.")
    if args.fixed_speed is not None and not (
        args.min_speed <= args.fixed_speed <= args.max_speed
    ):
        raise ValueError("fixed-speed must lie inside [min-speed, max-speed].")

    output = args.output.expanduser().resolve()
    output.mkdir(parents=True, exist_ok=True)
    checkpoint_directory = output / "checkpoints"
    checkpoint_directory.mkdir(exist_ok=True)
    tensorboard_directory = output / "tensorboard"

    generated_directory = output / "generated"
    generated_directory.mkdir(exist_ok=True)
    physical_model = build_model(
        output_path=generated_directory / "myoLeg22_2D_GEXO.xml"
    )
    vector_environment = make_vector_environment(
        args,
        model_path=physical_model,
    )
    rollout_size = args.n_steps * args.workers
    batch_size = _batch_size(rollout_size, args.batch_size)
    transfer_report: dict[str, float | int | str] | None = None

    try:
        if args.resume is None:
            model = make_human_ppo(
                vector_environment,
                device=args.device,
                seed=args.seed,
                learning_rate=args.learning_rate,
                n_steps=args.n_steps,
                batch_size=batch_size,
                n_epochs=args.n_epochs,
                tensorboard_log=str(tensorboard_directory),
            )
            transfer_report = transfer_released_human_weights(
                model,
                args.source,
                device=args.device,
            )
            initial_checkpoint = output / "human_actor_warm_start"
            model.save(initial_checkpoint)
            reset_num_timesteps = True
        else:
            model = PPO.load(
                str(args.resume.expanduser().resolve(strict=True)),
                env=vector_environment,
                device=args.device,
            )
            if model.action_space.shape != (22,):
                raise ValueError("Resume checkpoint must expose 22 muscle actions.")
            reset_num_timesteps = False

        callback = CheckpointCallback(
            save_freq=max(args.checkpoint_every // args.workers, 1),
            save_path=str(checkpoint_directory),
            name_prefix="human_adapted",
        )
        model.learn(
            total_timesteps=args.timesteps,
            reset_num_timesteps=reset_num_timesteps,
            callback=callback,
            progress_bar=False,
            tb_log_name="human_adaptation",
        )
        checkpoint = output / "adapted_human_final"
        model.save(checkpoint)
        checkpoint = checkpoint.with_suffix(".zip")
    finally:
        vector_environment.close()

    metadata = {
        "schema": "gexo_myoassist_human_adaptation_v1",
        "physical_model": str(physical_model),
        "physical_model_sha256": file_sha256(physical_model),
        "source_checkpoint": str(args.source.expanduser().resolve(strict=True)),
        "source_checkpoint_sha256": file_sha256(args.source),
        "resume_checkpoint": None if args.resume is None else str(args.resume),
        "final_checkpoint": str(checkpoint),
        "final_checkpoint_sha256": file_sha256(checkpoint),
        "transfer": transfer_report,
        "initial_checkpoint": (
            None
            if args.resume is not None
            else str(initial_checkpoint.with_suffix(".zip"))
        ),
        "timesteps_this_run": args.timesteps,
        "workers": args.workers,
        "n_steps": args.n_steps,
        "batch_size": batch_size,
        "n_epochs": args.n_epochs,
        "learning_rate": args.learning_rate,
        "speed_range_m_s": [args.min_speed, args.max_speed],
        "fixed_training_speed_m_s": args.fixed_speed,
        "random_reference_index": args.random_reference_index,
        "reset_state_contract": (
            "kinematic_reference_only_diagnostic_v1"
            if args.random_reference_index
            else "canonical_full_state_v1"
        ),
        "control_hz": 50,
        "physics_hz": 1200,
        "exo_torque_during_adaptation_nm": [0.0, 0.0, 0.0, 0.0],
        "urdf_enabled": False,
        "domain_randomization_enabled": False,
        "seed": args.seed,
    }
    metadata_path = output / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, indent=2, sort_keys=True),
        encoding="utf-8",
    )
    print(f"adapted checkpoint: {checkpoint}")
    print(f"metadata: {metadata_path}")
    print(f"tensorboard: {tensorboard_directory}")


if __name__ == "__main__":
    main()
