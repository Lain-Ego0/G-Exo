"""Validate muscle load sharing with a cloned same-state A/B experiment.

This is a physics check, not an RL evaluation:

    A: nominal Kinesis excitation, zero exoskeleton torque
    B: load-shared excitation, one candidate exoskeleton torque

Both branches start from the same ``MjData``.  The report separates the
solver's full generalized-force residual from the actual one-step change in
``qacc``, ``qvel`` and ``qpos``.  A small residual on the four target joints
alone is not sufficient for acceptance.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import mujoco
import numpy as np

from RL.env.kinesis.assist_backend import (
    AssistBackend,
    JOINT_NAMES,
    MuscleLoadSharing,
)
from RL.env.kinesis.teacher import KinesisPolicy, make_agent


CONTROL_DT = 0.02
DEFAULT_LEVELS_NM = (0.25, 0.5, 1.0, 2.0)
DEFAULT_OUTPUT = Path(
    "RL/outputs/kinesis_load_sharing_validation/report.json"
)


def clone_data(model: mujoco.MjModel, source: mujoco.MjData) -> mujoco.MjData:
    """Copy the physical state needed for a deterministic MuJoCo step."""

    target = mujoco.MjData(model)
    for name in (
        "qpos",
        "qvel",
        "act",
        "qacc_warmstart",
        "mocap_pos",
        "mocap_quat",
        "userdata",
    ):
        source_value = getattr(source, name, None)
        target_value = getattr(target, name, None)
        if source_value is not None and target_value is not None:
            if np.asarray(source_value).shape == np.asarray(target_value).shape:
                target_value[:] = source_value
    target.time = float(source.time)
    target.qfrc_applied[:] = 0.0
    target.ctrl[:] = 0.0
    mujoco.mj_forward(model, target)
    return target


def one_step(
    model: mujoco.MjModel,
    source: mujoco.MjData,
    *,
    control: np.ndarray,
    dof_addresses: np.ndarray,
    exo_torque: np.ndarray,
) -> dict[str, np.ndarray]:
    """Run one isolated physics step and return pre/post dynamics."""

    data = clone_data(model, source)
    data.ctrl[:] = np.asarray(control, dtype=np.float32)
    data.qfrc_applied[dof_addresses] = np.asarray(
        exo_torque,
        dtype=np.float64,
    )

    # ``qacc_pre`` exposes the immediate torque impulse before activation
    # dynamics have had time to respond.  ``qvel_next`` includes one complete
    # MuJoCo step and therefore captures the first compensating response.
    mujoco.mj_forward(model, data)
    qacc_pre = data.qacc.copy()
    efc_force_pre = data.efc_force.copy()
    mujoco.mj_step(model, data)
    mujoco.mj_forward(model, data)
    return {
        "qpos_next": data.qpos.copy(),
        "qvel_next": data.qvel.copy(),
        "qacc_pre": qacc_pre,
        "qacc_next": data.qacc.copy(),
        "efc_force_pre": efc_force_pre,
        "efc_force_next": data.efc_force.copy(),
    }


def norm_ratio(delta: np.ndarray, reference: np.ndarray) -> float:
    """Return a scale-free L2 difference without dividing by zero."""

    return float(
        np.linalg.norm(delta)
        / max(float(np.linalg.norm(reference)), 1.0e-8)
    )


def generalized_force_masks(
    model: mujoco.MjModel,
) -> tuple[np.ndarray, np.ndarray]:
    """Separate generalized forces measured in N from those measured in Nm."""

    translational = np.zeros(model.nv, dtype=bool)
    rotational = np.zeros(model.nv, dtype=bool)
    for dof_id in range(model.nv):
        joint_id = int(
            np.searchsorted(model.jnt_dofadr, dof_id, side="right") - 1
        )
        joint_type = int(model.jnt_type[joint_id])
        local_dof = dof_id - int(model.jnt_dofadr[joint_id])
        if joint_type == int(mujoco.mjtJoint.mjJNT_SLIDE):
            translational[dof_id] = True
        elif joint_type == int(mujoco.mjtJoint.mjJNT_FREE):
            (translational if local_dof < 3 else rotational)[dof_id] = True
        else:
            rotational[dof_id] = True
    return translational, rotational


def nominal_for_data(
    backend: AssistBackend,
    data: mujoco.MjData,
    fixed_nominal: np.ndarray,
) -> np.ndarray:
    """Apply the same high-level human command to one cloned physical state."""

    if backend.human_control_mode == "direct":
        return fixed_nominal.copy()
    if backend.target_muscle_length is None:
        raise RuntimeError("PD target muscle length is unavailable.")
    nominal = backend._target_length_to_activation(
        backend.target_muscle_length,
        data,
        backend.model,
    )
    return np.clip(
        np.asarray(nominal, dtype=np.float64) * backend.human_strength,
        0.0,
        1.0,
    )


def control_horizon(
    backend: AssistBackend,
    source: mujoco.MjData,
    *,
    nominal_excitation: np.ndarray,
    exo_torque: np.ndarray,
) -> dict[str, np.ndarray | float]:
    """Compare A/B over one 20 ms exoskeleton control period."""

    baseline = clone_data(backend.model, source)
    assisted = clone_data(backend.model, source)
    solver = MuscleLoadSharing(backend.model, backend.dof_addresses)
    solver.reset(assisted)
    baseline_activation_cost = 0.0
    assisted_activation_cost = 0.0

    for _ in range(backend.exo_substeps):
        baseline_nominal = nominal_for_data(
            backend,
            baseline,
            nominal_excitation,
        )
        assisted_nominal = nominal_for_data(
            backend,
            assisted,
            nominal_excitation,
        )
        adjusted = solver.compute_excitation(
            assisted,
            assisted_nominal,
            exo_torque,
        )

        baseline.ctrl[:] = baseline_nominal
        baseline.qfrc_applied[:] = 0.0
        assisted.ctrl[:] = adjusted
        assisted.qfrc_applied[:] = 0.0
        assisted.qfrc_applied[backend.dof_addresses] = exo_torque
        mujoco.mj_step(backend.model, baseline)
        mujoco.mj_step(backend.model, assisted)
        mujoco.mj_forward(backend.model, baseline)
        mujoco.mj_forward(backend.model, assisted)
        baseline_activation_cost += float(np.mean(np.square(baseline.act)))
        assisted_activation_cost += float(np.mean(np.square(assisted.act)))

    return {
        "qpos": assisted.qpos - baseline.qpos,
        "qvel": assisted.qvel - baseline.qvel,
        "qacc": assisted.qacc - baseline.qacc,
        "baseline_qvel": baseline.qvel.copy(),
        "baseline_qacc": baseline.qacc.copy(),
        "constraint_force": assisted.efc_force - baseline.efc_force,
        "baseline_constraint_force": baseline.efc_force.copy(),
        "activation_cost_change_percent": 100.0
        * (
            assisted_activation_cost
            / max(baseline_activation_cost, 1.0e-8)
            - 1.0
        ),
    }


def evaluate_level(
    backend: AssistBackend,
    nominal_excitation: np.ndarray,
    *,
    joint_index: int,
    torque_nm: float,
) -> dict[str, object]:
    """Evaluate one torque level without advancing the real backend."""

    solver = backend.load_sharing
    data = backend.data
    torque = np.zeros(4, dtype=np.float64)
    torque[joint_index] = torque_nm

    bias, gain = solver._force_terms(data)
    moment = np.asarray(data.actuator_moment, dtype=np.float64)
    nominal_next = solver._next_activation(data, nominal_excitation)
    nominal_generalized = moment.T @ (bias + gain * nominal_next)

    adjusted_excitation = solver.compute_excitation(
        data,
        nominal_excitation,
        torque,
    )
    desired_activation = (
        nominal_next.copy()
        if np.allclose(torque, 0.0)
        else solver.desired_activation.copy()
    )
    assisted_generalized = moment.T @ (
        bias + gain * desired_activation
    )
    full_residual = (
        assisted_generalized
        + solver.exo_embedding @ torque
        - nominal_generalized
    )
    target = np.asarray(backend.dof_addresses, dtype=np.int32)
    non_target_mask = np.ones(backend.model.nv, dtype=bool)
    non_target_mask[target] = False
    translational_mask, rotational_mask = generalized_force_masks(
        backend.model
    )
    non_target_translational = non_target_mask & translational_mask
    non_target_rotational = non_target_mask & rotational_mask

    baseline_step = one_step(
        backend.model,
        data,
        control=nominal_excitation,
        dof_addresses=target,
        exo_torque=np.zeros(4, dtype=np.float64),
    )
    assisted_step = one_step(
        backend.model,
        data,
        control=adjusted_excitation,
        dof_addresses=target,
        exo_torque=torque,
    )
    horizon = control_horizon(
        backend,
        data,
        nominal_excitation=nominal_excitation,
        exo_torque=torque,
    )

    return {
        "joint": JOINT_NAMES[joint_index],
        "joint_index": joint_index,
        "requested_torque_nm": torque_nm,
        "applied_torque_nm": torque.tolist(),
        "solver_failed": bool(solver.solve_failed),
        "activation_adjustment_rms": float(
            np.sqrt(np.mean(np.square(desired_activation - nominal_next)))
        ),
        "excitation_adjustment_rms": float(
            np.sqrt(np.mean(np.square(adjusted_excitation - nominal_excitation)))
        ),
        "target_residual_max_nm": float(
            np.max(np.abs(full_residual[target]))
        ),
        "non_target_translational_residual_max_n": float(
            np.max(np.abs(full_residual[non_target_translational]))
        ),
        "non_target_translational_residual_rms_n": float(
            np.sqrt(
                np.mean(np.square(full_residual[non_target_translational]))
            )
        ),
        "non_target_rotational_residual_max_nm": float(
            np.max(np.abs(full_residual[non_target_rotational]))
        ),
        "non_target_rotational_residual_rms_nm": float(
            np.sqrt(np.mean(np.square(full_residual[non_target_rotational])))
        ),
        "qacc_pre_relative_difference": norm_ratio(
            assisted_step["qacc_pre"] - baseline_step["qacc_pre"],
            baseline_step["qacc_pre"],
        ),
        "qacc_next_relative_difference": norm_ratio(
            assisted_step["qacc_next"] - baseline_step["qacc_next"],
            baseline_step["qacc_next"],
        ),
        "qvel_next_relative_difference": norm_ratio(
            assisted_step["qvel_next"] - baseline_step["qvel_next"],
            baseline_step["qvel_next"],
        ),
        "qpos_next_difference_norm": float(
            np.linalg.norm(
                assisted_step["qpos_next"] - baseline_step["qpos_next"]
            )
        ),
        "constraint_force_next_relative_difference": norm_ratio(
            assisted_step["efc_force_next"]
            - baseline_step["efc_force_next"],
            baseline_step["efc_force_next"],
        ),
        "horizon_qacc_relative_difference": norm_ratio(
            horizon["qacc"],
            horizon["baseline_qacc"],
        ),
        "horizon_qvel_relative_difference": norm_ratio(
            horizon["qvel"],
            horizon["baseline_qvel"],
        ),
        "horizon_qpos_difference_norm": float(
            np.linalg.norm(horizon["qpos"])
        ),
        "horizon_constraint_force_relative_difference": norm_ratio(
            horizon["constraint_force"],
            horizon["baseline_constraint_force"],
        ),
        "horizon_activation_cost_change_percent": float(
            horizon["activation_cost_change_percent"]
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-id", type=int, default=82)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--warmup-steps", type=int, default=100)
    parser.add_argument(
        "--levels-nm",
        default=",".join(str(level) for level in DEFAULT_LEVELS_NM),
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    levels = tuple(
        float(value)
        for value in args.levels_nm.split(",")
        if value.strip()
    )
    if not levels or any(level <= 0.0 for level in levels):
        raise ValueError("--levels-nm must contain positive values.")

    agent = make_agent(args.motion_id, render=False)
    policy = KinesisPolicy(agent)
    backend = AssistBackend(
        agent.env,
        exo_control_dt=CONTROL_DT,
        load_sharing=True,
    )

    try:
        policy.reset(args.seed)
        backend.reset(seed=args.seed)
        for _ in range(args.warmup_steps):
            state = backend.step(
                np.zeros(4, dtype=np.float32),
                policy,
            )
            if state["terminated"] or state["truncated"]:
                raise RuntimeError("Motion ended during warmup.")

        nominal_excitation = np.asarray(
            backend.nominal_excitation,
            dtype=np.float64,
        ).copy()
        # The zero row verifies that cloning, stepping and metric collection
        # introduce no difference by themselves.
        rows = [
            evaluate_level(
                backend,
                nominal_excitation,
                joint_index=0,
                torque_nm=0.0,
            )
        ]
        for joint_index in range(4):
            for level in levels:
                for sign in (1.0, -1.0):
                    rows.append(
                        evaluate_level(
                            backend,
                            nominal_excitation,
                            joint_index=joint_index,
                            torque_nm=sign * level,
                        )
                    )
    finally:
        backend.close()

    args.output.parent.mkdir(parents=True, exist_ok=True)
    report = {
        "motion_id": args.motion_id,
        "seed": args.seed,
        "warmup_steps": args.warmup_steps,
        "sim_dt_s": backend.sim_dt,
        "control_dt_s": CONTROL_DT,
        "levels_nm": list(levels),
        "target_joint_names": list(JOINT_NAMES),
        "rows": rows,
    }
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    for row in rows:
        print(
            f"{row['joint']:18s} "
            f"tau={row['requested_torque_nm']:+.2f} Nm "
            f"target={row['target_residual_max_nm']:.4g} "
            f"other_rot={row['non_target_rotational_residual_max_nm']:.4g} Nm "
            f"other_slide={row['non_target_translational_residual_max_n']:.4g} N "
            f"qvel20ms={row['horizon_qvel_relative_difference']:.3%}"
        )
    print("report:", args.output)


if __name__ == "__main__":
    main()
