"""Validate physical G-Exo transmission and paired muscle unloading."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
from scipy.optimize import lsq_linear

from RL.env.kinesis.assist_backend import AssistBackend
from RL.env.kinesis.baseline_reference import (
    DEFAULT_PHYSICAL_BASELINE_DIR,
    BaselineReference,
    tracking_metrics,
)
from RL.env.kinesis.exo_env import CONTROL_DT
from RL.env.kinesis.physical_exo import DynamicExoSystem
from RL.env.kinesis.teacher import KinesisPolicy, make_agent


DEFAULT_OUTPUT = Path(
    "RL/outputs/kinesis_physical_validation/report.json"
)


def run_case(
    *,
    motion_id: int,
    seed: int,
    mode: str,
    gain: float,
    max_steps: int,
    warmup_steps: int,
    baseline_dir: Path,
) -> dict[str, object]:
    agent = make_agent(motion_id, render=False)
    policy = KinesisPolicy(agent)
    physical = DynamicExoSystem(agent.env)
    backend = AssistBackend(
        agent.env,
        exo_control_dt=CONTROL_DT,
        torque_limit_nm=17.0,
        torque_rate_limit_nm_s=50.0,
        load_sharing=True,
        physical_exo=physical,
    )
    baseline = BaselineReference(baseline_dir, motion_id)
    resolved_seed = baseline.resolve_seed(seed)
    policy.reset(resolved_seed)
    backend.reset(seed=resolved_seed)

    records = {
        "activation": [],
        "baseline_activation": [],
        "muscle_torque": [],
        "baseline_muscle_torque": [],
        "motor_torque": [],
        "motor_assistance": [],
        "supported_assistance": [],
        "full_balance_rms": [],
        "predicted_full_balance_rms": [],
        "cuff_force": [],
        "cuff_error": [],
        "mpjpe_mm": [],
    }
    zero = np.zeros(4, dtype=np.float32)
    state = None

    try:
        for _ in range(warmup_steps):
            state = backend.step(zero, policy)
            if state["terminated"] or state["truncated"]:
                break

        for _ in range(max_steps):
            assert state is not None
            sample = baseline.sample(resolved_seed, float(state["time"]))
            if mode == "passive":
                target = zero
            elif mode == "oracle":
                desired_support = gain * sample.human_torque
                transmission = physical.transmission_matrix()
                regularization = 0.05 * np.eye(4)
                solution = lsq_linear(
                    np.vstack((transmission, regularization)),
                    np.concatenate((desired_support, np.zeros(4))),
                    bounds=(-6.0, 6.0),
                    method="bvls",
                )
                target = solution.x.astype(np.float32)
            else:
                raise ValueError(f"Unknown mode: {mode}")

            state = backend.step(target, policy)
            sample = baseline.sample(resolved_seed, float(state["time"]))
            _, mpjpe_m = tracking_metrics(agent.env, float(state["time"]))
            records["activation"].append(
                float(np.mean(np.square(state["muscle_activation"])))
            )
            records["baseline_activation"].append(sample.activation_cost)
            records["muscle_torque"].append(
                float(np.mean(np.abs(state["muscle_torque"])))
            )
            records["baseline_muscle_torque"].append(sample.torque_cost)
            records["motor_torque"].append(
                np.asarray(state["exo_torque"], dtype=np.float64)
            )
            records["motor_assistance"].append(
                np.asarray(
                    state["motor_assistance_torque"], dtype=np.float64
                )
            )
            records["supported_assistance"].append(
                np.asarray(
                    state["supported_assistance_torque"], dtype=np.float64
                )
            )
            records["full_balance_rms"].append(
                float(state["full_balance_rms"])
            )
            records["predicted_full_balance_rms"].append(
                float(state["predicted_full_balance_rms"])
            )
            records["cuff_force"].append(
                np.asarray(state["cuff_force_n"], dtype=np.float64)
            )
            records["cuff_error"].append(
                float(state["cuff_constraint_error_m"])
            )
            records["mpjpe_mm"].append(1000.0 * mpjpe_m)
            if state["terminated"] or state["truncated"]:
                break
    finally:
        backend.close()

    arrays = {
        name: np.asarray(values, dtype=np.float64)
        for name, values in records.items()
    }
    activation_saving = _saving(
        arrays["baseline_activation"], arrays["activation"]
    )
    torque_saving = _saving(
        arrays["baseline_muscle_torque"], arrays["muscle_torque"]
    )
    motor_norm = np.linalg.norm(arrays["motor_torque"], axis=1)
    motor_assistance_norm = np.linalg.norm(
        arrays["motor_assistance"], axis=1
    )
    supported_norm = np.linalg.norm(
        arrays["supported_assistance"], axis=1
    )
    nonzero = motor_assistance_norm > 1.0e-8
    accepted_ratio = (
        float(
            np.mean(
                np.minimum(
                    supported_norm[nonzero] / motor_assistance_norm[nonzero],
                    1.0,
                )
            )
        )
        if np.any(nonzero)
        else 0.0
    )
    return {
        "mode": mode,
        "motion_id": motion_id,
        "seed": resolved_seed,
        "steps": int(len(arrays["activation"])),
        "terminated": bool(state["terminated"]),
        "truncated": bool(state["truncated"]),
        "exo_mass_kg": physical.mass_kg,
        "activation_saving_percent": 100.0 * activation_saving,
        "muscle_torque_saving_percent": 100.0 * torque_saving,
        "mean_mpjpe_mm": float(np.mean(arrays["mpjpe_mm"])),
        "mean_abs_motor_torque_nm": float(
            np.mean(np.abs(arrays["motor_torque"]))
        ),
        "mean_abs_motor_assistance_nm": float(
            np.mean(np.abs(arrays["motor_assistance"]))
        ),
        "accepted_motor_assistance_ratio": accepted_ratio,
        "mean_full_balance_rms": float(
            np.mean(arrays["full_balance_rms"])
        ),
        "mean_predicted_full_balance_rms": float(
            np.mean(arrays["predicted_full_balance_rms"])
        ),
        "activation_integral": float(np.sum(arrays["activation"])),
        "muscle_torque_integral": float(
            np.sum(arrays["muscle_torque"])
        ),
        "mean_cuff_force_n": float(np.mean(arrays["cuff_force"])),
        "peak_cuff_force_n": float(np.max(arrays["cuff_force"])),
        "mean_cuff_error_m": float(np.mean(arrays["cuff_error"])),
        "peak_cuff_error_m": float(np.max(arrays["cuff_error"])),
        "max_abs_motor_assistance_nm": float(
            np.max(np.abs(arrays["motor_assistance"]))
        ),
        "max_abs_supported_assistance_nm": float(
            np.max(np.abs(arrays["supported_assistance"]))
        ),
        "finite": bool(
            all(np.all(np.isfinite(values)) for values in arrays.values())
        ),
        "mean_motor_norm_nm": float(np.mean(motor_norm)),
    }


def _saving(baseline: np.ndarray, actual: np.ndarray) -> float:
    baseline_sum = float(np.sum(baseline))
    return (baseline_sum - float(np.sum(actual))) / max(
        baseline_sum, 1.0e-12
    )


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-id", type=int, default=82)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--gain", type=float, default=0.05)
    parser.add_argument("--max-steps", type=int, default=500)
    parser.add_argument("--warmup-steps", type=int, default=25)
    parser.add_argument(
        "--baseline-dir",
        type=Path,
        default=DEFAULT_PHYSICAL_BASELINE_DIR,
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    results = [
        run_case(
            motion_id=args.motion_id,
            seed=args.seed,
            mode=mode,
            gain=args.gain,
            max_steps=args.max_steps,
            warmup_steps=args.warmup_steps,
            baseline_dir=args.baseline_dir,
        )
        for mode in ("passive", "oracle")
    ]
    passive, assisted = results
    paired = {
        "activation_saving_percent": 100.0
        * (
            passive["activation_integral"]
            - assisted["activation_integral"]
        )
        / max(passive["activation_integral"], 1.0e-12),
        "muscle_torque_saving_percent": 100.0
        * (
            passive["muscle_torque_integral"]
            - assisted["muscle_torque_integral"]
        )
        / max(passive["muscle_torque_integral"], 1.0e-12),
        "mpjpe_change_mm": (
            assisted["mean_mpjpe_mm"] - passive["mean_mpjpe_mm"]
        ),
    }
    checks = {
        "urdf_mass_preserved": abs(passive["exo_mass_kg"] - 3.09834816165551)
        < 1.0e-6,
        "zero_motor_has_zero_induced_assistance": passive[
            "max_abs_motor_assistance_nm"
        ]
        < 1.0e-8,
        "zero_motor_has_zero_supported_assistance": passive[
            "max_abs_supported_assistance_nm"
        ]
        < 1.0e-8,
        "passive_rollout_completed": not passive["terminated"],
        "assisted_rollout_completed": not assisted["terminated"],
        "all_metrics_finite": passive["finite"] and assisted["finite"],
    }
    report = {
        "cases": results,
        "paired_assisted_vs_passive": paired,
        "checks": checks,
        "all_passed": all(checks.values()),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    for row in results:
        print(
            f"{row['mode']:8s} steps={row['steps']:3d} "
            f"activation={row['activation_saving_percent']:+.2f}% "
            f"muscle={row['muscle_torque_saving_percent']:+.2f}% "
            f"mpjpe={row['mean_mpjpe_mm']:.2f} mm "
            f"motor={row['mean_abs_motor_torque_nm']:.2f} Nm "
            f"cuff={row['mean_cuff_force_n']:.1f} N"
        )
    print("all passed:", report["all_passed"])
    print(
        "paired assisted vs passive: "
        f"activation={paired['activation_saving_percent']:+.2f}% "
        f"muscle={paired['muscle_torque_saving_percent']:+.2f}% "
        f"mpjpe={paired['mpjpe_change_mm']:+.2f} mm"
    )
    print("report:", args.output.resolve())


if __name__ == "__main__":
    main()
