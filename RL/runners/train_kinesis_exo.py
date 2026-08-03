"""Train the four-joint exoskeleton policy on a frozen Kinesis human."""

from __future__ import annotations

import argparse
import json
from functools import partial
from pathlib import Path

import torch.nn as nn

from RL.env.kinesis.baseline_reference import (
    DEFAULT_CYCLE_BASELINE_DIR,
    DEFAULT_PHYSICAL_BASELINE_DIR,
    BaselineReference,
)
from RL.env.kinesis.causal_phase import CausalPhaseAdapter
from RL.env.kinesis.exo_env import (
    CYCLE_REWARD_SETTINGS,
    CYCLE_REWARD_WEIGHTS,
    DEFAULT_PHASE_TCN_CHECKPOINT,
    DEFAULT_TCN_CALIBRATION,
    DEFAULT_TCN_CHECKPOINT,
    KinesisExoEnv,
    REWARD_SETTINGS,
    REWARD_WEIGHTS,
    SCHEME_C_OBSERVATION_DIM,
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
SCHEME_C_TRAIN_MOTIONS = (2, 8, 9, 11, 16, 38, 52)
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
    use_phase_tcn: bool = False,
    phase_tcn_checkpoint: Path = DEFAULT_PHASE_TCN_CHECKPOINT,
    reward_mode: str = "same_state",
    training_motions: tuple[int, ...] = TRAIN_MOTIONS,
) -> tuple:
    """Assign one stable motion to each subprocess."""

    if num_envs < 1:
        raise ValueError("num_envs must be positive.")

    return tuple(
        partial(
            KinesisExoEnv,
            motion_id=training_motions[index % len(training_motions)],
            baseline_dir=baseline_dir,
            action_torque_scale_nm=action_torque_scale_nm,
            warmup_steps=WARMUP_STEPS,
            use_tcn=use_tcn,
            tcn_checkpoint=tcn_checkpoint,
            tcn_calibration=tcn_calibration,
            tcn_device=tcn_device,
            use_phase_tcn=use_phase_tcn,
            phase_tcn_checkpoint=phase_tcn_checkpoint,
            reward_mode=reward_mode,
        )
        for index in range(num_envs)
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=None,
        help="Defaults to the matched cycle baseline under --scheme-c.",
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
        default=None,
        help=(
            "Normalized action scale. Defaults to 17 Nm for scheme C and "
            "0.5 Nm for legacy experiments."
        ),
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="cpu",
    )
    parser.add_argument("--seed", type=int, default=42)
    parser.add_argument(
        "--scheme-c",
        action="store_true",
        help=(
            "Use 163-D Actor input and matched complete-cycle physiology reward."
        ),
    )
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
    parser.add_argument(
        "--phase-tcn-checkpoint",
        type=Path,
        default=DEFAULT_PHASE_TCN_CHECKPOINT,
    )
    parser.add_argument(
        "--log-std-init",
        type=float,
        default=-1.0,
        help="Initial log standard deviation of the four PPO actions.",
    )
    args = parser.parse_args()

    if args.scheme_c:
        args.use_tcn = True
    if args.action_scale_nm is None:
        args.action_scale_nm = 17.0 if args.scheme_c else 0.5
    if args.baseline_dir is None:
        args.baseline_dir = (
            DEFAULT_CYCLE_BASELINE_DIR
            if args.scheme_c
            else DEFAULT_PHYSICAL_BASELINE_DIR
        )
    reward_mode = "cycle_c" if args.scheme_c else "same_state"
    training_motions = (
        SCHEME_C_TRAIN_MOTIONS if args.scheme_c else TRAIN_MOTIONS
    )

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
    if args.scheme_c:
        phase_probe = CausalPhaseAdapter(
            args.phase_tcn_checkpoint,
            device=args.tcn_device,
        )
        del phase_probe
    # Fail before spawning workers if any motion lacks a valid paired baseline.
    for motion_id in training_motions + VALIDATION_MOTIONS:
        reference = BaselineReference(args.baseline_dir, motion_id)
        if args.scheme_c and not reference.supports_exact_cycles:
            raise RuntimeError(
                f"Motion {motion_id} has no exact-cycle baseline in "
                f"{args.baseline_dir}."
            )

    training_factories = make_training_factories(
        args.num_envs,
        args.baseline_dir,
        args.action_scale_nm,
        use_tcn=args.use_tcn,
        tcn_checkpoint=args.tcn_checkpoint,
        tcn_calibration=args.tcn_calibration,
        tcn_device=args.tcn_device,
        use_phase_tcn=args.scheme_c,
        phase_tcn_checkpoint=args.phase_tcn_checkpoint,
        reward_mode=reward_mode,
        training_motions=training_motions,
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
            use_phase_tcn=args.scheme_c,
            phase_tcn_checkpoint=args.phase_tcn_checkpoint,
            reward_mode=reward_mode,
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
                "training_motions": list(training_motions),
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
                    SCHEME_C_OBSERVATION_DIM
                    if args.scheme_c
                    else TCN_OBSERVATION_DIM
                    if args.use_tcn
                    else 144
                ),
                "action_dim": 4,
                "scheme_c": args.scheme_c,
                "reward_mode": reward_mode,
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
                "phase_tcn_enabled": args.scheme_c,
                "phase_tcn_checkpoint": (
                    str(args.phase_tcn_checkpoint.expanduser().resolve())
                    if args.scheme_c
                    else None
                ),
                "phase_tcn_feature_dim": 3 if args.scheme_c else 0,
                "phase_tcn_used_in_reward": False,
                "actor_feature_layout": (
                    "144 proprioception + 16 motion TCN + 3 phase TCN"
                    if args.scheme_c
                    else None
                ),
                "effort_reward_reference": (
                    "matched_zero_assist_cycle"
                    if args.scheme_c
                    else "same_state_no_assist"
                ),
                "offline_baseline_role": (
                    "cycle_reward_tracking_and_final_evaluation"
                    if args.scheme_c
                    else "tracking_final_evaluation_and_diagnostics"
                ),
                "reward_weights": (
                    CYCLE_REWARD_WEIGHTS
                    if args.scheme_c
                    else REWARD_WEIGHTS
                ),
                "reward_settings": (
                    CYCLE_REWARD_SETTINGS
                    if args.scheme_c
                    else REWARD_SETTINGS
                ),
                "log_std_init": args.log_std_init,
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
            "policy_kwargs": {
                "activation_fn": nn.ReLU,
                "log_std_init": args.log_std_init,
                "net_arch": {
                    "pi": [128, 64],
                    "vf": [128, 64],
                },
            },
        },
    )

    print("Kinesis exoskeleton training finished")
    print("model:", model_path)


if __name__ == "__main__":
    main()
