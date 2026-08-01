"""Check same-state continuity of exoskeleton muscle load sharing."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.env.kinesis.assist_backend import AssistBackend, JOINT_NAMES
from RL.env.kinesis.directional_teacher import (
    make_directional_agent,
    make_directional_policy,
)
from RL.runners.evaluate_kinesis_directional import set_command


DEFAULT_LEVELS_NM = (
    -1.0,
    -0.5,
    -0.2,
    -0.1,
    -0.05,
    -0.01,
    -0.001,
    0.0,
    0.001,
    0.01,
    0.05,
    0.1,
    0.2,
    0.5,
    1.0,
)
DEFAULT_OUTPUT = Path(
    "RL/outputs/kinesis_directional_assist/solver_continuity.json"
)


def nominal_excitation(backend: AssistBackend) -> np.ndarray:
    """Compute the native PD excitation at the unchanged physical state."""

    target_lengths = backend._action_to_target_length(
        backend.human_action,
        backend.model,
    )
    return np.asarray(
        backend._target_length_to_activation(
            target_lengths,
            backend.data,
            backend.model,
        ),
        dtype=np.float64,
    )


def evaluate_level(
    backend: AssistBackend,
    nominal: np.ndarray,
    *,
    joint_index: int,
    torque_nm: float,
) -> dict[str, object]:
    """Evaluate one torque without advancing MuJoCo."""

    load_sharing = backend.load_sharing
    torque = np.zeros(4, dtype=np.float64)
    torque[joint_index] = torque_nm

    bias, gain = load_sharing._force_terms(backend.data)
    moment = np.asarray(backend.data.actuator_moment, dtype=np.float64)
    nominal_next = load_sharing._next_activation(backend.data, nominal)
    nominal_generalized = moment.T @ (bias + gain * nominal_next)

    adjusted = load_sharing.compute_excitation(
        backend.data,
        nominal,
        torque,
    )
    desired = (
        nominal_next
        if torque_nm == 0.0
        else load_sharing.desired_activation.copy()
    )
    predicted_generalized = moment.T @ (bias + gain * desired)
    delta_target_torque = (
        predicted_generalized - nominal_generalized
    )[backend.dof_addresses]
    residual = delta_target_torque + torque

    if abs(torque_nm) > 0.0:
        replacement_ratio = float(
            -delta_target_torque[joint_index] / torque_nm
        )
    else:
        replacement_ratio = 0.0

    other = np.delete(delta_target_torque, joint_index)
    return {
        "joint": JOINT_NAMES[joint_index],
        "torque_nm": torque_nm,
        "replacement_ratio": replacement_ratio,
        "target_balance_residual_nm": float(residual[joint_index]),
        "other_target_joint_crosstalk_max_nm": float(
            np.max(np.abs(other))
        ),
        "excitation_adjustment_rms": float(
            np.sqrt(np.mean(np.square(adjusted - nominal)))
        ),
        "activation_adjustment_rms": float(
            np.sqrt(np.mean(np.square(desired - nominal_next)))
        ),
        "solver_failed": bool(load_sharing.solve_failed),
    }


def summarize(rows: list[dict[str, object]]) -> dict[str, float]:
    """Return strict solver-level acceptance metrics."""

    nonzero = [row for row in rows if row["torque_nm"] != 0.0]
    zero = next(row for row in rows if row["torque_nm"] == 0.0)
    return {
        "zero_excitation_adjustment_rms": float(
            zero["excitation_adjustment_rms"]
        ),
        "replacement_ratio_max_error": float(
            max(abs(row["replacement_ratio"] - 1.0) for row in nonzero)
        ),
        "balance_residual_max_nm": float(
            max(abs(row["target_balance_residual_nm"]) for row in nonzero)
        ),
        "crosstalk_max_nm": float(
            max(row["other_target_joint_crosstalk_max_nm"] for row in nonzero)
        ),
        "solver_failure_count": int(
            sum(row["solver_failed"] for row in rows)
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--warmup-steps", type=int, default=100)
    parser.add_argument("--direction-deg", type=float, default=0.0)
    parser.add_argument("--speed-m-s", type=float, default=1.0)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    agent = make_directional_agent(render=False)
    policy = make_directional_policy(agent)
    backend = AssistBackend(agent.env, load_sharing=True)

    try:
        policy.reset(args.seed)
        backend.reset(seed=args.seed)
        set_command(
            backend.env,
            float(np.deg2rad(args.direction_deg)),
            args.speed_m_s,
        )
        backend.observation = np.asarray(
            backend.env.compute_observations(), dtype=np.float32
        )
        for _ in range(args.warmup_steps):
            state = backend.step(np.zeros(4, dtype=np.float32), policy)
            if state["terminated"] or state["truncated"]:
                raise RuntimeError("Directional human ended during warmup.")

        nominal = nominal_excitation(backend)
        rows = [
            evaluate_level(
                backend,
                nominal,
                joint_index=joint_index,
                torque_nm=torque_nm,
            )
            for joint_index in range(4)
            for torque_nm in DEFAULT_LEVELS_NM
        ]
    finally:
        backend.close()

    joint_summaries = {
        joint: summarize([row for row in rows if row["joint"] == joint])
        for joint in JOINT_NAMES
    }
    report = {
        "seed": args.seed,
        "warmup_steps": args.warmup_steps,
        "same_state": True,
        "levels_nm": list(DEFAULT_LEVELS_NM),
        "joint_summaries": joint_summaries,
        "rows": rows,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    for joint, summary in joint_summaries.items():
        print(
            f"{joint:18s} "
            f"ratio_error={summary['replacement_ratio_max_error']:.4f} "
            f"residual={summary['balance_residual_max_nm']:.4f} Nm "
            f"crosstalk={summary['crosstalk_max_nm']:.4f} Nm"
        )
    print("report:", args.output)


if __name__ == "__main__":
    main()
