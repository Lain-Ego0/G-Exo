"""Decompose V9 activation savings at frozen physical states."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import mujoco
import numpy as np
from scipy.optimize import lsq_linear

from RL.env.kinesis.exo_env import KinesisExoEnv
from RL.env.torque import TorqueActuator


DEFAULT_MODEL = Path(
    "RL/outputs/kinesis_exo_ppo_v9_1m/checkpoints/"
    "gexo_ppo_500000_steps.zip"
)
DEFAULT_OUTPUT = Path(
    "RL/outputs/kinesis_exo_ppo_v9_1m/fixed_state_audit.json"
)


def solve_activation(
    backend,
    nominal_excitation: np.ndarray,
    exo_torque: np.ndarray,
    *,
    reference_activation: np.ndarray,
    effort_regularization: float,
) -> tuple[np.ndarray, np.ndarray]:
    """Rebuild one old or corrected bounded load-sharing solve."""

    solver = backend.load_sharing
    data = backend.data
    bias, gain = solver._force_terms(data)
    moment = np.asarray(data.actuator_moment, dtype=np.float64)
    reference_force = bias + gain * reference_activation
    reference_torque = moment.T @ reference_force
    exo_generalized = solver.exo_embedding @ exo_torque

    activation_matrix = moment.T * gain
    passive_torque = moment.T @ bias
    lower, upper = solver._reachable_activation_bounds(data)
    variable = (
        np.any(
            np.abs(moment[:, solver.dof_addresses]) > 1.0e-8,
            axis=1,
        )
        & (np.abs(gain) > 1.0e-8)
        & (upper - lower > 1.0e-8)
    )

    desired = reference_activation.copy()
    fixed_torque = (
        activation_matrix[:, ~variable]
        @ reference_activation[~variable]
    )
    target = (
        reference_torque
        - exo_generalized
        - passive_torque
        - fixed_torque
    )
    matrix = activation_matrix[:, variable]
    identity = np.eye(int(np.sum(variable)))
    blocks = [
        solver.dof_weights[:, None] * matrix,
        np.sqrt(solver.nominal_regularization) * identity,
    ]
    targets = [
        solver.dof_weights * target,
        np.sqrt(solver.nominal_regularization)
        * reference_activation[variable],
    ]
    if effort_regularization > 0.0:
        blocks.append(np.sqrt(effort_regularization) * identity)
        targets.append(np.zeros(identity.shape[0], dtype=np.float64))

    result = lsq_linear(
        np.vstack(blocks),
        np.concatenate(targets),
        bounds=(lower[variable], upper[variable]),
        method="bvls",
        tol=1.0e-6,
        max_iter=100,
    )
    if not result.success:
        raise RuntimeError(result.message)
    desired[variable] = result.x

    predicted_torque = moment.T @ (bias + gain * desired)
    residual = (
        predicted_torque + exo_generalized - reference_torque
    )[solver.dof_addresses]
    return desired, residual


def relative_saving(baseline: float, assisted: float) -> float:
    """Return positive fractional saving relative to a baseline cost."""

    return (baseline - assisted) / max(baseline, 1.0e-8)


def advance_activation(
    model,
    activation: np.ndarray,
    excitation: np.ndarray,
    dt: float,
) -> np.ndarray:
    """Advance a copied activation vector by one MuJoCo physics step."""

    advanced = np.asarray(activation, dtype=np.float64).copy()
    for actuator_id in range(model.nu):
        activation_id = model.actuator_actadr[actuator_id]
        derivative = mujoco.mju_muscleDynamics(
            float(excitation[actuator_id]),
            float(advanced[activation_id]),
            model.actuator_dynprm[actuator_id, :3],
        )
        advanced[activation_id] += dt * derivative
    return advanced


def summarize(rows: list[dict[str, float]]) -> dict[str, float]:
    """Average causal components over frozen states."""

    keys = (
        "mean_abs_exo_torque_nm",
        "old_reported_activation_saving",
        "old_solver_switch_activation_saving",
        "old_exo_incremental_activation_saving",
        "corrected_exo_activation_saving",
        "old_balance_residual_nm",
        "corrected_balance_residual_nm",
    )
    summary = {
        key: float(np.mean([row[key] for row in rows]))
        for key in keys
    }
    summary["states"] = len(rows)
    cost_pairs = {
        "old_reported_activation_saving_integrated": (
            "bypass_activation_cost",
            "old_assisted_activation_cost",
        ),
        "old_solver_switch_activation_saving_integrated": (
            "bypass_activation_cost",
            "old_zero_activation_cost",
        ),
        "old_exo_incremental_activation_saving_integrated": (
            "old_zero_activation_cost",
            "old_assisted_activation_cost",
        ),
        "corrected_exo_activation_saving_integrated": (
            "corrected_zero_activation_cost",
            "corrected_assisted_activation_cost",
        ),
    }
    for name, (baseline_key, assisted_key) in cost_pairs.items():
        baseline = float(np.sum([row[baseline_key] for row in rows]))
        assisted = float(np.sum([row[assisted_key] for row in rows]))
        summary[name] = relative_saving(baseline, assisted)
    return summary


def run_motion(
    model,
    *,
    motion_id: int,
    seed: int,
    steps: int,
) -> list[dict[str, float]]:
    """Audit policy torques along one stable zero-assistance trajectory."""

    env = KinesisExoEnv(motion_id=motion_id)
    probe_actuator = TorqueActuator(
        torque_limit_nm=env.backend.torque_limit_nm,
        torque_rate_limit_nm_s=(
            env.backend.actuator.torque_rate_limit_nm_s
        ),
        control_dt=env.backend.actuator.control_dt,
    )
    observation, _ = env.reset(seed=seed)
    rows = []

    try:
        for step in range(steps):
            action, _ = model.predict(observation, deterministic=True)
            exo_torque = probe_actuator.process(action)
            nominal = np.asarray(
                env._last_state["nominal_excitation"],
                dtype=np.float64,
            )
            actual_next = env.backend.load_sharing._next_activation(
                env.backend.data,
                nominal,
            )
            shadow = np.asarray(
                env.backend.load_sharing.shadow_activation,
                dtype=np.float64,
            ).copy()
            shadow_next = advance_activation(
                env.backend.model,
                shadow,
                nominal,
                env.backend.sim_dt,
            )

            old_zero, old_zero_residual = solve_activation(
                env.backend,
                nominal,
                np.zeros(4, dtype=np.float64),
                reference_activation=shadow_next,
                effort_regularization=0.01,
            )
            old_assisted, old_residual = solve_activation(
                env.backend,
                nominal,
                exo_torque.astype(np.float64),
                reference_activation=shadow_next,
                effort_regularization=0.01,
            )
            corrected_zero, corrected_zero_residual = solve_activation(
                env.backend,
                nominal,
                np.zeros(4, dtype=np.float64),
                reference_activation=actual_next,
                effort_regularization=0.0,
            )
            corrected_assisted, corrected_residual = solve_activation(
                env.backend,
                nominal,
                exo_torque.astype(np.float64),
                reference_activation=actual_next,
                effort_regularization=0.0,
            )

            bypass_cost = float(np.mean(np.square(actual_next)))
            old_zero_cost = float(np.mean(np.square(old_zero)))
            old_assisted_cost = float(np.mean(np.square(old_assisted)))
            corrected_zero_cost = float(
                np.mean(np.square(corrected_zero))
            )
            corrected_assisted_cost = float(
                np.mean(np.square(corrected_assisted))
            )
            rows.append(
                {
                    "motion_id": motion_id,
                    "seed": seed,
                    "step": step,
                    "mean_abs_exo_torque_nm": float(
                        np.mean(np.abs(exo_torque))
                    ),
                    "bypass_activation_cost": bypass_cost,
                    "old_zero_activation_cost": old_zero_cost,
                    "old_assisted_activation_cost": old_assisted_cost,
                    "corrected_zero_activation_cost": corrected_zero_cost,
                    "corrected_assisted_activation_cost": (
                        corrected_assisted_cost
                    ),
                    "old_reported_activation_saving": relative_saving(
                        bypass_cost, old_assisted_cost
                    ),
                    "old_solver_switch_activation_saving": relative_saving(
                        bypass_cost, old_zero_cost
                    ),
                    "old_exo_incremental_activation_saving": relative_saving(
                        old_zero_cost, old_assisted_cost
                    ),
                    "corrected_exo_activation_saving": relative_saving(
                        corrected_zero_cost, corrected_assisted_cost
                    ),
                    "old_balance_residual_nm": float(
                        np.mean(np.abs(old_residual))
                    ),
                    "corrected_balance_residual_nm": float(
                        np.mean(np.abs(corrected_residual))
                    ),
                    "old_zero_balance_residual_nm": float(
                        np.mean(np.abs(old_zero_residual))
                    ),
                    "corrected_zero_balance_residual_nm": float(
                        np.mean(np.abs(corrected_zero_residual))
                    ),
                }
            )

            observation, _, terminated, truncated, _ = env.step(
                np.zeros(4, dtype=np.float32)
            )
            if terminated or truncated:
                break
    finally:
        env.close()

    return rows


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model", type=Path, default=DEFAULT_MODEL)
    parser.add_argument("--motion-ids", default="64,82,99")
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--seeds", default=None)
    parser.add_argument("--steps", type=int, default=100)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()
    motion_ids = [int(value) for value in args.motion_ids.split(",")]
    seeds = (
        [int(value) for value in args.seeds.split(",")]
        if args.seeds is not None
        else [args.seed]
    )
    if len(motion_ids) > 1 or len(seeds) > 1:
        rows = []
        for motion_id in motion_ids:
            for seed in seeds:
                part_path = args.output.with_name(
                    f"{args.output.stem}.motion_{motion_id:03d}"
                    f".seed_{seed:03d}.json"
                )
                subprocess.run(
                    [
                        sys.executable,
                        "-m",
                        "RL.runners.audit_v9_fixed_state_savings",
                        "--model",
                        str(args.model),
                        "--motion-ids",
                        str(motion_id),
                        "--seed",
                        str(seed),
                        "--steps",
                        str(args.steps),
                        "--output",
                        str(part_path),
                    ],
                    check=True,
                )
                with part_path.open("r", encoding="utf-8") as file:
                    rows.extend(json.load(file)["rows"])
                part_path.unlink()

        report = {
            "model": str(args.model),
            "frozen_state_audit": True,
            "seeds": seeds,
            "motion_summaries": {
                str(motion_id): summarize(
                    [row for row in rows if row["motion_id"] == motion_id]
                )
                for motion_id in motion_ids
            },
            "summary": summarize(rows),
            "rows": rows,
        }
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with args.output.open("w", encoding="utf-8") as file:
            json.dump(report, file, indent=2, ensure_ascii=False)
        print("report:", args.output)
        return

    from stable_baselines3 import PPO

    model = PPO.load(args.model, device="cpu")
    rows = []
    for motion_id in motion_ids:
        motion_rows = run_motion(
            model,
            motion_id=motion_id,
            seed=seeds[0],
            steps=args.steps,
        )
        rows.extend(motion_rows)
        summary = summarize(motion_rows)
        print(
            f"motion={motion_id:03d} "
            f"old_total={summary['old_reported_activation_saving']:+.3%} "
            f"switch={summary['old_solver_switch_activation_saving']:+.3%} "
            f"old_exo={summary['old_exo_incremental_activation_saving']:+.3%} "
            f"corrected_exo={summary['corrected_exo_activation_saving']:+.3%}"
        )

    report = {
        "model": str(args.model),
        "frozen_state_audit": True,
        "motion_summaries": {
            str(motion_id): summarize(
                [row for row in rows if row["motion_id"] == motion_id]
            )
            for motion_id in motion_ids
        },
        "summary": summarize(rows),
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)
    print("report:", args.output)


if __name__ == "__main__":
    main()
