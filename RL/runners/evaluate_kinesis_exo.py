"""Evaluate or render baseline, oracle, and PPO exoskeleton assistance."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np

from RL.env.kinesis.exo_env import (
    BASE_OBSERVATION_DIM,
    CONTROL_DT,
    DEFAULT_TCN_CALIBRATION,
    DEFAULT_TCN_CHECKPOINT,
    KinesisExoEnv,
    TCN_OBSERVATION_DIM,
)
from RL.env.kinesis.baseline_reference import DEFAULT_PHYSICAL_BASELINE_DIR
from RL.runners.policy_load_compat import (
    load_ppo_for_inference,
    saved_space_shapes,
)


RL_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_OUTPUT = RL_ROOT / "outputs/kinesis_exo_evaluation/report.json"
LEGACY_ACTION_SCALE_NM = 0.5
VALID_MODES = (
    "baseline",
    "positive_constant",
    "negative_constant",
    "velocity_assist",
    "velocity_resist",
    "oracle",
    "policy",
)


def parse_csv(text: str, value_type: Callable) -> list:
    """Parse a small comma-separated command-line list."""

    return [
        value_type(item.strip())
        for item in text.split(",")
        if item.strip()
    ]


def load_run_config(model_path: Path | None) -> dict:
    """Load the nearest training config belonging to a saved policy."""

    if model_path is None:
        return {}

    directory = model_path.expanduser().resolve().parent
    for _ in range(3):
        config_path = directory / "config.json"
        if config_path.is_file():
            with config_path.open("r", encoding="utf-8") as file:
                return json.load(file)
        directory = directory.parent
    return {}


def policy_observation_dim(model_path: Path, device: str) -> int:
    """Read the policy input width before constructing Kinesis."""

    del device
    shape, _ = saved_space_shapes(model_path)
    if shape is None or len(shape) != 1:
        raise ValueError(
            "The evaluator requires a one-dimensional Box observation."
        )
    return int(shape[0])


def resolve_evaluation_settings(
    args: argparse.Namespace,
    modes: list[str],
) -> tuple[dict, int | None]:
    """Restore the environment contract saved beside a policy."""

    requires_policy = "policy" in modes
    if requires_policy:
        if args.model is None or not args.model.is_file():
            raise FileNotFoundError(
                "A valid --model is required for policy mode."
            )

    run_config = load_run_config(args.model)
    observation_dim = (
        policy_observation_dim(args.model, args.device)
        if requires_policy
        else None
    )

    if args.action_scale_nm is None:
        saved_scale = run_config.get("action_torque_scale_nm")
        if saved_scale is None and requires_policy:
            raise ValueError(
                "Cannot infer the policy torque scale. Pass "
                "--action-scale-nm or keep config.json beside the run."
            )
        args.action_scale_nm = (
            LEGACY_ACTION_SCALE_NM
            if saved_scale is None
            else float(saved_scale)
        )
    if not 0.0 < args.action_scale_nm <= 17.0:
        raise ValueError("--action-scale-nm must be in (0, 17].")

    if args.baseline_dir is None:
        args.baseline_dir = Path(
            run_config.get(
                "baseline_dir",
                DEFAULT_PHYSICAL_BASELINE_DIR,
            )
        )

    if args.use_tcn is None:
        saved_tcn = run_config.get("tcn_enabled")
        if saved_tcn is not None:
            args.use_tcn = bool(saved_tcn)
        elif observation_dim is not None:
            args.use_tcn = observation_dim == TCN_OBSERVATION_DIM
        else:
            args.use_tcn = False

    args.tcn_checkpoint = Path(
        args.tcn_checkpoint
        or run_config.get("tcn_checkpoint")
        or DEFAULT_TCN_CHECKPOINT
    )
    args.tcn_calibration = Path(
        args.tcn_calibration
        or run_config.get("tcn_calibration")
        or DEFAULT_TCN_CALIBRATION
    )

    expected_dim = (
        TCN_OBSERVATION_DIM if args.use_tcn else BASE_OBSERVATION_DIM
    )
    if observation_dim is not None and observation_dim != expected_dim:
        raise ValueError(
            f"Policy expects {observation_dim} observations, but the "
            f"resolved environment produces {expected_dim}. Check the "
            "run config or explicitly select --use-tcn/--no-tcn."
        )
    if args.use_tcn:
        for path in (args.tcn_checkpoint, args.tcn_calibration):
            if not path.is_file():
                raise FileNotFoundError(path)

    return run_config, observation_dim


def action_for_mode(
    mode: str,
    env: KinesisExoEnv,
    observation: np.ndarray,
    model,
    oracle_gain: float,
    test_torque_nm: float,
) -> np.ndarray:
    """Return a deployable action or the privileged oracle comparison."""

    if mode == "baseline":
        return np.zeros(4, dtype=np.float32)

    if mode in ("positive_constant", "negative_constant"):
        sign = 1.0 if mode == "positive_constant" else -1.0
        target_torque = np.full(4, sign * test_torque_nm)
        return np.asarray(
            target_torque / env.action_torque_scale_nm,
            dtype=np.float32,
        )

    if mode in ("velocity_assist", "velocity_resist"):
        joint_velocity = np.asarray(
            env._last_state["joint_velocity"], dtype=np.float32
        )
        sign = 1.0 if mode == "velocity_assist" else -1.0
        target_torque = sign * test_torque_nm * np.tanh(
            joint_velocity / 0.5
        )
        return np.asarray(
            target_torque / env.action_torque_scale_nm,
            dtype=np.float32,
        )

    if mode == "oracle":
        target_torque = (
            oracle_gain * env.backend.baseline_muscle_torque()
        )
        return np.clip(
            target_torque / env.action_torque_scale_nm,
            -1.0,
            1.0,
        ).astype(np.float32)

    if model is None:
        raise ValueError("policy mode requires --model.")

    action, _ = model.predict(observation, deterministic=True)
    return np.asarray(action, dtype=np.float32)


def run_episode(
    env: KinesisExoEnv,
    *,
    mode: str,
    seed: int,
    model,
    oracle_gain: float,
    test_torque_nm: float,
    real_time: bool,
) -> dict:
    """Run one paired episode and aggregate interpretable physical metrics."""

    observation, reset_info = env.reset(seed=seed)
    episode_return = 0.0
    mpjpe = []
    activation_cost = []
    baseline_activation_cost = []
    tracking_mse = []
    baseline_tracking_mse = []
    muscle_torque = []
    baseline_muscle_torque = []
    exo_torque = []
    balance_error = []
    balance_ratio = []
    actual_balance_ratio = []
    jerk_cost = []
    rated_torque_exceed_ratio = []
    positive_power_samples = []
    co_contraction = []
    baseline_co_contraction = []
    co_contraction_excess = []
    activation_overload_topk = []
    action_samples = []
    cuff_force_samples = []
    cuff_error_samples = []
    cuff_constraint_error_samples = []
    positive_work_j = 0.0
    negative_work_j = 0.0
    terminated = False
    truncated = False
    info = {}

    for step in range(env.max_episode_steps):
        started_at = time.monotonic()
        action = action_for_mode(
            mode,
            env,
            observation,
            model,
            oracle_gain,
            test_torque_nm,
        )
        action_samples.extend(np.abs(action).tolist())
        observation, reward, terminated, truncated, info = env.step(
            action
        )

        episode_return += float(reward)
        mpjpe.append(float(info["mpjpe_mm"]))

        metrics = info["reward_metrics"]
        # Evaluation uses raw per-step costs.  Reward metrics contain a
        # sliding-window mean and must not be averaged a second time.
        activation_cost.append(float(info["target_activation_cost"]))
        baseline_sample = env.baseline.sample(
            int(info["episode_seed"]),
            float(info["time_s"]),
        )
        baseline_activation_cost.append(
            float(baseline_sample.activation_cost)
        )
        tracking_mse.append(float(info["tracking_mse"]))
        baseline_tracking_mse.append(
            float(info["baseline_tracking_mse"])
        )
        muscle_torque.append(float(info["muscle_effort_torque_cost"]))
        baseline_muscle_torque.append(
            float(baseline_sample.muscle_effort_torque_cost)
        )
        exo_torque.append(
            float(np.mean(np.abs(info["exo_torque"])))
        )
        balance_error.append(
            float(np.mean(np.abs(info["torque_balance_error"])))
        )
        balance_ratio.append(float(metrics["balance_ratio"]))
        actual_balance_ratio.append(
            float(metrics["actual_balance_ratio"])
        )
        jerk_cost.append(float(metrics["jerk_cost"]))
        rated_torque_exceed_ratio.append(
            float(metrics["rated_torque_exceed_ratio"])
        )
        co_contraction.append(
            float(metrics["co_contraction_index_mean"])
        )
        baseline_co_contraction.append(
            float(metrics["baseline_co_contraction_index_mean"])
        )
        co_contraction_excess.append(
            float(metrics["co_contraction_excess_mean"])
        )
        activation_overload_topk.append(
            float(metrics["activation_overload_topk"])
        )
        cuff_force_samples.extend(
            np.abs(np.asarray(info["cuff_force_n"], dtype=np.float64)).ravel().tolist()
        )
        cuff_error_samples.extend(
            np.abs(np.asarray(info["cuff_error_m"], dtype=np.float64)).ravel().tolist()
        )
        cuff_constraint_error_samples.append(
            abs(float(info["cuff_constraint_error_m"]))
        )

        joint_power = np.asarray(
            info["exo_joint_power_w"], dtype=np.float64
        )
        positive_power = np.maximum(joint_power, 0.0)
        positive_power_samples.extend(positive_power.tolist())
        positive_work_j += float(np.sum(positive_power)) * CONTROL_DT
        negative_work_j += float(
            np.sum(np.minimum(joint_power, 0.0))
        ) * CONTROL_DT

        if real_time:
            remaining = CONTROL_DT - (time.monotonic() - started_at)
            if remaining > 0.0:
                time.sleep(remaining)

        if terminated or truncated:
            break

    actual_cost = float(np.mean(activation_cost))
    baseline_cost = float(np.mean(baseline_activation_cost))
    actual_torque = float(np.mean(muscle_torque))
    baseline_torque = float(np.mean(baseline_muscle_torque))
    success = bool(truncated and not terminated)

    return {
        "mode": mode,
        "motion_id": env.motion_id,
        "seed": int(reset_info["episode_seed"]),
        "steps": step + 1,
        "success": success,
        "termination_reason": info.get(
            "termination_reason", "unknown"
        ),
        "episode_return": episode_return,
        "mean_mpjpe_mm": float(np.mean(mpjpe)),
        "mean_tracking_mse": float(np.mean(tracking_mse)),
        "mean_baseline_tracking_mse": float(
            np.mean(baseline_tracking_mse)
        ),
        "mean_squared_activation": actual_cost,
        "mean_squared_baseline_activation": baseline_cost,
        "activation_cost_integral_s": (
            float(np.sum(activation_cost)) * CONTROL_DT
        ),
        "baseline_activation_cost_integral_s": (
            float(np.sum(baseline_activation_cost)) * CONTROL_DT
        ),
        "activation_change_percent": (
            100.0 * (actual_cost / max(baseline_cost, 1.0e-8) - 1.0)
        ),
        "mean_absolute_muscle_torque_nm": actual_torque,
        "mean_absolute_baseline_muscle_torque_nm": baseline_torque,
        "absolute_muscle_torque_integral_nms": (
            float(np.sum(muscle_torque)) * CONTROL_DT
        ),
        "baseline_absolute_muscle_torque_integral_nms": (
            float(np.sum(baseline_muscle_torque)) * CONTROL_DT
        ),
        "muscle_torque_change_percent": (
            100.0
            * (actual_torque / max(baseline_torque, 1.0e-8) - 1.0)
        ),
        "mean_absolute_exo_torque_nm": float(np.mean(exo_torque)),
        "mean_absolute_balance_error_nm": float(
            np.mean(balance_error)
        ),
        "mean_balance_residual_ratio": float(np.mean(balance_ratio)),
        "mean_actual_balance_residual_ratio": float(
            np.mean(actual_balance_ratio)
        ),
        "mean_jerk_cost": float(np.mean(jerk_cost)),
        "rated_torque_exceed_ratio": float(
            np.mean(rated_torque_exceed_ratio)
        ),
        "mean_co_contraction_index": float(np.mean(co_contraction)),
        "mean_baseline_co_contraction_index": float(
            np.mean(baseline_co_contraction)
        ),
        "mean_co_contraction_excess": float(
            np.mean(co_contraction_excess)
        ),
        "mean_activation_overload_topk": float(
            np.mean(activation_overload_topk)
        ),
        "positive_power_p95_w": float(
            np.percentile(positive_power_samples, 95)
        ),
        "positive_power_p99_w": float(
            np.percentile(positive_power_samples, 99)
        ),
        "positive_power_max_w": float(np.max(positive_power_samples)),
        "positive_exo_work_j": positive_work_j,
        "negative_exo_work_j": negative_work_j,
        "action_saturation_ratio": float(
            np.mean(np.asarray(action_samples) >= 0.98)
        ),
        "cuff_force_p95_n": float(np.percentile(cuff_force_samples, 95)),
        "cuff_force_max_n": float(np.max(cuff_force_samples)),
        "cuff_error_p95_mm": float(
            1000.0 * np.percentile(cuff_error_samples, 95)
        ),
        "cuff_constraint_error_max_mm": float(
            1000.0 * np.max(cuff_constraint_error_samples)
        ),
    }


def aggregate(rows: list[dict]) -> list[dict]:
    """Average episode metrics for each evaluation mode."""

    summaries = []
    numeric_keys = (
        "episode_return",
        "mean_mpjpe_mm",
        "mean_tracking_mse",
        "mean_baseline_tracking_mse",
        "mean_squared_activation",
        "mean_squared_baseline_activation",
        "activation_change_percent",
        "mean_absolute_muscle_torque_nm",
        "mean_absolute_baseline_muscle_torque_nm",
        "muscle_torque_change_percent",
        "mean_absolute_exo_torque_nm",
        "mean_absolute_balance_error_nm",
        "mean_balance_residual_ratio",
        "mean_actual_balance_residual_ratio",
        "mean_jerk_cost",
        "rated_torque_exceed_ratio",
        "mean_co_contraction_index",
        "mean_baseline_co_contraction_index",
        "mean_co_contraction_excess",
        "mean_activation_overload_topk",
        "positive_power_p95_w",
        "positive_power_p99_w",
        "positive_power_max_w",
        "positive_exo_work_j",
        "negative_exo_work_j",
        "action_saturation_ratio",
        "cuff_force_p95_n",
        "cuff_force_max_n",
        "cuff_error_p95_mm",
        "cuff_constraint_error_max_mm",
    )

    for mode in VALID_MODES:
        selected = [row for row in rows if row["mode"] == mode]
        if not selected:
            continue

        summary = {
            "mode": mode,
            "episodes": len(selected),
            "success_rate": float(
                np.mean([row["success"] for row in selected])
            ),
            "mean_steps": float(
                np.mean([row["steps"] for row in selected])
            ),
        }
        for key in numeric_keys:
            summary[key] = float(
                np.mean([row[key] for row in selected])
            )
        actual_activation = float(
            np.sum(
                [row["activation_cost_integral_s"] for row in selected]
            )
        )
        baseline_activation = float(
            np.sum(
                [
                    row["baseline_activation_cost_integral_s"]
                    for row in selected
                ]
            )
        )
        actual_torque = float(
            np.sum(
                [
                    row["absolute_muscle_torque_integral_nms"]
                    for row in selected
                ]
            )
        )
        baseline_torque = float(
            np.sum(
                [
                    row[
                        "baseline_absolute_muscle_torque_integral_nms"
                    ]
                    for row in selected
                ]
            )
        )
        summary["pooled_activation_change_percent"] = 100.0 * (
            actual_activation / max(baseline_activation, 1.0e-8) - 1.0
        )
        summary["pooled_muscle_torque_change_percent"] = 100.0 * (
            actual_torque / max(baseline_torque, 1.0e-8) - 1.0
        )
        summaries.append(summary)

    return summaries


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-ids", default="64,82,99")
    parser.add_argument("--modes", default="baseline,policy")
    parser.add_argument("--episodes", type=int, default=3)
    parser.add_argument("--first-seed", type=int, default=0)
    parser.add_argument("--oracle-gain", type=float, default=0.025)
    parser.add_argument("--test-torque-nm", type=float, default=2.0)
    parser.add_argument(
        "--action-scale-nm",
        type=float,
        default=None,
        help=(
            "Torque represented by policy action magnitude 1.0. "
            "Defaults to the model run's config.json value."
        ),
    )
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=None,
        help="Defaults to the model run's config.json value.",
    )
    parser.add_argument("--model", type=Path, default=None)
    parser.add_argument("--torque-limit-nm", type=float, default=17.0)
    parser.add_argument("--torque-rate-limit-nm-s", type=float, default=50.0)
    parser.add_argument("--warmup-steps", type=int, default=50)
    parser.add_argument("--max-episode-steps", type=int, default=500)
    tcn_group = parser.add_mutually_exclusive_group()
    tcn_group.add_argument(
        "--use-tcn",
        dest="use_tcn",
        action="store_true",
        help="Force the 160-dimensional TCN observation.",
    )
    tcn_group.add_argument(
        "--no-tcn",
        dest="use_tcn",
        action="store_false",
        help="Force the 144-dimensional sensor-only observation.",
    )
    parser.set_defaults(use_tcn=None)
    parser.add_argument(
        "--tcn-checkpoint",
        type=Path,
        default=None,
        help="Defaults to the model run's config.json value.",
    )
    parser.add_argument(
        "--tcn-calibration",
        type=Path,
        default=None,
        help="Defaults to the model run's config.json value.",
    )
    parser.add_argument(
        "--tcn-device",
        choices=("cpu", "cuda"),
        default="cpu",
    )
    parser.add_argument(
        "--device",
        choices=("auto", "cpu", "cuda"),
        default="cpu",
    )
    parser.add_argument("--render", action="store_true")
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    motion_ids = parse_csv(args.motion_ids, int)
    modes = parse_csv(args.modes, str)
    unknown_modes = sorted(set(modes) - set(VALID_MODES))
    if unknown_modes:
        raise ValueError(f"Unknown modes: {unknown_modes}")
    if args.episodes < 1:
        raise ValueError("episodes must be positive.")
    run_config, observation_dim = resolve_evaluation_settings(
        args,
        modes,
    )
    print(
        "evaluation settings: "
        f"observation_dim={observation_dim or 'not applicable'}, "
        f"action_scale={args.action_scale_nm:g} Nm, "
        f"tcn={args.use_tcn}"
    )

    # Kinesis keeps process-global motion caches. Evaluate each motion in a
    # fresh interpreter, then merge the physical metrics in this parent.
    if len(motion_ids) > 1:
        rows = []
        part_paths = []
        for motion_id in motion_ids:
            part_path = args.output.with_name(
                f"{args.output.stem}.motion_{motion_id:03d}.json"
            )
            command = [
                sys.executable,
                "-m",
                "RL.runners.evaluate_kinesis_exo",
                "--motion-ids",
                str(motion_id),
                "--modes",
                ",".join(modes),
                "--episodes",
                str(args.episodes),
                "--first-seed",
                str(args.first_seed),
                "--oracle-gain",
                str(args.oracle_gain),
                "--test-torque-nm",
                str(args.test_torque_nm),
                "--action-scale-nm",
                str(args.action_scale_nm),
                "--baseline-dir",
                str(args.baseline_dir),
                "--torque-limit-nm",
                str(args.torque_limit_nm),
                "--torque-rate-limit-nm-s",
                str(args.torque_rate_limit_nm_s),
                "--warmup-steps",
                str(args.warmup_steps),
                "--max-episode-steps",
                str(args.max_episode_steps),
                "--device",
                args.device,
                "--output",
                str(part_path),
            ]
            if args.model is not None:
                command.extend(("--model", str(args.model)))
            if args.use_tcn:
                command.extend((
                    "--use-tcn",
                    "--tcn-checkpoint",
                    str(args.tcn_checkpoint),
                    "--tcn-calibration",
                    str(args.tcn_calibration),
                    "--tcn-device",
                    args.tcn_device,
                ))
            else:
                command.append("--no-tcn")
            if args.render:
                command.append("--render")
            subprocess.run(command, check=True)
            with part_path.open("r", encoding="utf-8") as file:
                rows.extend(json.load(file)["rows"])
            part_paths.append(part_path)

        report = {
            "motion_ids": motion_ids,
            "modes": modes,
            "episodes_per_motion": args.episodes,
            "oracle_gain": args.oracle_gain,
            "test_torque_nm": args.test_torque_nm,
            "action_torque_scale_nm": args.action_scale_nm,
            "torque_limit_nm": args.torque_limit_nm,
            "torque_rate_limit_nm_s": args.torque_rate_limit_nm_s,
            "warmup_steps": args.warmup_steps,
            "max_episode_steps": args.max_episode_steps,
            "baseline_dir": str(args.baseline_dir.resolve()),
            "model": str(args.model) if args.model else None,
            "tcn_enabled": args.use_tcn,
            "tcn_checkpoint": (
                str(args.tcn_checkpoint) if args.use_tcn else None
            ),
            "tcn_calibration": (
                str(args.tcn_calibration) if args.use_tcn else None
            ),
            "policy_observation_dim": observation_dim,
            "run_config_found": bool(run_config),
            "rows": rows,
            "summary": aggregate(rows),
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as file:
            json.dump(report, file, indent=2, ensure_ascii=False)
        for part_path in part_paths:
            part_path.unlink()
        print("report:", args.output)
        return

    model = None
    if "policy" in modes:
        model = load_ppo_for_inference(args.model, device=args.device)

    rows = []
    for motion_id in motion_ids:
        env = KinesisExoEnv(
            motion_id=motion_id,
            render_mode="human" if args.render else None,
            baseline_dir=args.baseline_dir,
            strict_baseline_seed=True,
            torque_limit_nm=args.torque_limit_nm,
            action_torque_scale_nm=args.action_scale_nm,
            torque_rate_limit_nm_s=args.torque_rate_limit_nm_s,
            warmup_steps=args.warmup_steps,
            max_episode_steps=args.max_episode_steps,
            use_tcn=args.use_tcn,
            tcn_checkpoint=args.tcn_checkpoint,
            tcn_calibration=args.tcn_calibration,
            tcn_device=args.tcn_device,
        )

        try:
            for mode in modes:
                for episode in range(args.episodes):
                    row = run_episode(
                        env,
                        mode=mode,
                        seed=args.first_seed + episode,
                        model=model,
                        oracle_gain=args.oracle_gain,
                        test_torque_nm=args.test_torque_nm,
                        real_time=args.render,
                    )
                    rows.append(row)
                    print(
                        f"{mode:8s} motion={motion_id:03d} "
                        f"seed={row['seed']:03d} "
                        f"success={row['success']} "
                        f"mpjpe={row['mean_mpjpe_mm']:.2f} mm "
                        f"activation={row['activation_change_percent']:+.2f}% "
                        f"muscle={row['muscle_torque_change_percent']:+.2f}% "
                        f"exo={row['mean_absolute_exo_torque_nm']:.2f} Nm"
                    )
        finally:
            env.close()

    report = {
        "motion_ids": motion_ids,
        "modes": modes,
        "episodes_per_motion": args.episodes,
        "oracle_gain": args.oracle_gain,
        "test_torque_nm": args.test_torque_nm,
        "action_torque_scale_nm": args.action_scale_nm,
        "torque_limit_nm": args.torque_limit_nm,
        "torque_rate_limit_nm_s": args.torque_rate_limit_nm_s,
        "warmup_steps": args.warmup_steps,
        "max_episode_steps": args.max_episode_steps,
        "baseline_dir": str(args.baseline_dir.resolve()),
        "model": str(args.model) if args.model else None,
        "tcn_enabled": args.use_tcn,
        "tcn_checkpoint": (
            str(args.tcn_checkpoint) if args.use_tcn else None
        ),
        "tcn_calibration": (
            str(args.tcn_calibration) if args.use_tcn else None
        ),
        "policy_observation_dim": observation_dim,
        "run_config_found": bool(run_config),
        "rows": rows,
        "summary": aggregate(rows),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    print("report:", args.output)


if __name__ == "__main__":
    main()
