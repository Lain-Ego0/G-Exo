"""Train the four-joint exoskeleton policy on a frozen Kinesis human."""

from __future__ import annotations

import argparse
import json
from functools import partial
from pathlib import Path

from RL.env.kinesis.baseline_reference import (
    DEFAULT_PHYSICAL_BASELINE_DIR,
    BaselineReference,
)
from RL.env.kinesis.exo_env import (
    DEFAULT_TCN_CALIBRATION,
    DEFAULT_TCN_CHECKPOINT,
    KinesisExoEnv,
    REWARD_SETTINGS,
    REWARD_WEIGHTS,
    TCN_OBSERVATION_DIM,
)
from RL.env.kinesis.tcn_adapter import (
    TCN_DEPLOYMENT_FEATURE_DIM,
    TCN_DEPLOYMENT_HORIZON_STEPS,
    TCNInputAdapter,
)
from RL.train import train


RL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = RL_ROOT / "outputs/kinesis_exo_ppo"

# These motions passed the conservative pre-PPO stability screen.  Validation
# motions are never assigned to a training worker.
TRAIN_MOTIONS = (2, 8, 9, 11, 16, 38, 43, 52)
VALIDATION_MOTIONS = (64, 82, 99)
WARMUP_STEPS = 50


def make_training_factories(
    num_envs: int,
    baseline_dir: Path,
    action_torque_scale_nm: float,
    *,
    use_tcn: bool = False,
    tcn_checkpoint: Path = DEFAULT_TCN_CHECKPOINT,
    tcn_calibration: Path = DEFAULT_TCN_CALIBRATION,
    tcn_device: str = "cpu",
) -> tuple:
    """Assign one stable motion to each subprocess."""

    if num_envs < 1:
        raise ValueError("num_envs must be positive.")

    return tuple(
        partial(
            KinesisExoEnv,
            motion_id=TRAIN_MOTIONS[index % len(TRAIN_MOTIONS)],
            baseline_dir=baseline_dir,
            action_torque_scale_nm=action_torque_scale_nm,
            warmup_steps=WARMUP_STEPS,
            use_tcn=use_tcn,
            tcn_checkpoint=tcn_checkpoint,
            tcn_calibration=tcn_calibration,
            tcn_device=tcn_device,
        )
        for index in range(num_envs)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=DEFAULT_PHYSICAL_BASELINE_DIR,
    )
    parser.add_argument("--resume", type=Path, default=None)
    parser.add_argument(
        "--total-timesteps",
        type=int,
        default=100_000_000,
        help="Transition cap; --hours normally stops an overnight run first.",
    )
    parser.add_argument("--hours", type=float, default=None)
    parser.add_argument("--num-envs", type=int, default=8)
    parser.add_argument(
        "--action-scale-nm",
        type=float,
        default=0.5,
        help="Initial PPO action range; the backend hard limit remains 17 Nm.",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="cpu",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--use-tcn",
        action="store_true",
        help="Append frozen 200 ms TCN context to the deployable observation.",
    )
    parser.add_argument(
        "--tcn-checkpoint",
        type=Path,
        default=DEFAULT_TCN_CHECKPOINT,
    )
    parser.add_argument(
        "--tcn-calibration",
        type=Path,
        default=DEFAULT_TCN_CALIBRATION,
    )
    parser.add_argument(
        "--tcn-device",
        choices=("cpu", "cuda"),
        default="cpu",
        help="Use CPU with subprocess workers unless profiling proves otherwise.",
    )
    args = parser.parse_args()

    if not 0.0 < args.action_scale_nm <= 17.0:
        raise ValueError("--action-scale-nm must be in (0, 17].")
    if args.use_tcn and args.tcn_device == "cuda" and args.num_envs > 1:
        raise ValueError(
            "Do not create multiple CUDA TCN copies in subprocess workers. "
            "Use --tcn-device cpu, or run one environment."
        )
    if args.use_tcn:
        # Fail before starting expensive Kinesis subprocesses.
        tcn_probe = TCNInputAdapter(
            args.tcn_checkpoint,
            device=args.tcn_device,
            calibration=args.tcn_calibration,
        )
        if not tcn_probe.has_actor_feature_normalization:
            raise RuntimeError(
                "TCN calibration has no fixed actor feature statistics. "
                "Run RL.runners.fit_kinesis_tcn_feature_stats first."
            )
        del tcn_probe
    # Fail before spawning workers if any motion lacks a valid paired baseline.
    for motion_id in TRAIN_MOTIONS + VALIDATION_MOTIONS:
        BaselineReference(args.baseline_dir, motion_id)

    training_factories = make_training_factories(
        args.num_envs,
        args.baseline_dir,
        args.action_scale_nm,
        use_tcn=args.use_tcn,
        tcn_checkpoint=args.tcn_checkpoint,
        tcn_calibration=args.tcn_calibration,
        tcn_device=args.tcn_device,
    )
    validation_factories = tuple(
        partial(
            KinesisExoEnv,
            motion_id=motion_id,
            baseline_dir=args.baseline_dir,
            action_torque_scale_nm=args.action_scale_nm,
            warmup_steps=WARMUP_STEPS,
            use_tcn=args.use_tcn,
            tcn_checkpoint=args.tcn_checkpoint,
            tcn_calibration=args.tcn_calibration,
            tcn_device=args.tcn_device,
        )
        for motion_id in VALIDATION_MOTIONS
    )

    # Save the effective experiment definition before a long run starts.
    args.output.mkdir(parents=True, exist_ok=True)
    with (args.output / "config.json").open(
        "w", encoding="utf-8"
    ) as file:
        json.dump(
            {
                "total_timesteps": args.total_timesteps,
                "max_hours": args.hours,
                "resume_from": (
                    str(args.resume.resolve())
                    if args.resume is not None
                    else None
                ),
                "num_envs": args.num_envs,
                "device": args.device,
                "seed": args.seed,
                "training_motions": list(TRAIN_MOTIONS),
                "validation_motions": list(VALIDATION_MOTIONS),
                "baseline_dir": str(args.baseline_dir.resolve()),
                "torque_limit_nm": 17.0,
                "action_torque_scale_nm": args.action_scale_nm,
                "rated_torque_nm": 6.0,
                "torque_rate_limit_nm_s": 50.0,
                "control_frequency_hz": 50.0,
                "warmup_steps": WARMUP_STEPS,
                "physical_urdf": True,
                "exo_mass_kg": 3.09834816165551,
                "cuff_time_constant_s": 0.1,
                "passive_alignment_dofs": 4,
                "observation_dim": (
                    TCN_OBSERVATION_DIM if args.use_tcn else 144
                ),
                "action_dim": 4,
                "tcn_enabled": args.use_tcn,
                "tcn_checkpoint": (
                    str(args.tcn_checkpoint.expanduser().resolve())
                    if args.use_tcn
                    else None
                ),
                "tcn_calibration": (
                    str(args.tcn_calibration.expanduser().resolve())
                    if args.use_tcn
                    else None
                ),
                "tcn_device": args.tcn_device if args.use_tcn else None,
                "tcn_feature_dim": (
                    TCN_DEPLOYMENT_FEATURE_DIM if args.use_tcn else 0
                ),
                "tcn_horizons_ms": (
                    [20 * steps for steps in TCN_DEPLOYMENT_HORIZON_STEPS]
                    if args.use_tcn
                    else []
                ),
                "effort_reward_reference": "same_state_no_assist",
                "offline_baseline_role": (
                    "tracking_final_evaluation_and_diagnostics"
                ),
                "reward_weights": REWARD_WEIGHTS,
                "reward_settings": REWARD_SETTINGS,
            },
            file,
            indent=2,
            ensure_ascii=False,
        )

    model_path = train(
        training_factories,
        eval_env_factory=validation_factories,
        output_dir=args.output,
        resume_from=args.resume,
        total_timesteps=args.total_timesteps,
        num_envs=args.num_envs,
        seed=args.seed,
        checkpoint_interval=500_000,
        evaluation_interval=250_000,
        evaluation_episodes=9,
        device=args.device,
        max_hours=args.hours,
        ppo_parameters={
            "learning_rate": 1.0e-4,
            "n_steps": 512,
            "batch_size": 256,
            "n_epochs": 5,
            "gae_lambda": 0.95,
            "ent_coef": 1.0e-3,
        },
    )

    print("Kinesis exoskeleton training finished")
    print("model:", model_path)


if __name__ == "__main__":
    main()
