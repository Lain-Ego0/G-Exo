"""Detect immediate unloading and delayed Kinesis compensation."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Callable

import numpy as np

from RL.env.kinesis.assist_backend import AssistBackend, JOINT_NAMES
from RL.env.kinesis.teacher import KinesisPolicy, make_agent


CONTROL_DT = 0.02
MEANINGFUL_POSITION_DIFFERENCE_RAD = 2.0e-3
DEFAULT_OUTPUT = Path(
    "RL/outputs/kinesis_compensation/report.json"
)


def run_rollout(
    backend: AssistBackend,
    policy: KinesisPolicy,
    *,
    seed: int,
    joint_index: int | None,
    pulse_nm: float,
    warmup_steps: int,
    pulse_steps: int,
    recovery_steps: int,
    after_reset: Callable[[AssistBackend], None] | None = None,
) -> dict[str, np.ndarray]:
    """Run one deterministic baseline or pulse rollout."""

    policy.reset(seed)
    backend.reset(seed=seed)
    if after_reset is not None:
        after_reset(backend)

    records: dict[str, list[np.ndarray | float]] = {
        "time": [],
        "q": [],
        "dq": [],
        "exo_torque": [],
        "human_torque": [],
        "nominal_torque": [],
        "activation": [],
        "shadow_activation": [],
        "nominal_excitation": [],
        "adjusted_excitation": [],
    }

    total_steps = warmup_steps + pulse_steps + recovery_steps
    for step in range(total_steps):
        target = np.zeros(4, dtype=np.float32)
        if (
            joint_index is not None
            and warmup_steps <= step < warmup_steps + pulse_steps
        ):
            target[joint_index] = pulse_nm

        state = backend.step(target, policy)
        records["time"].append(float(state["time"]))
        records["q"].append(state["joint_position"])
        records["dq"].append(state["joint_velocity"])
        records["exo_torque"].append(state["exo_torque"])
        records["human_torque"].append(state["muscle_torque"])
        records["nominal_torque"].append(
            state["baseline_muscle_torque"]
        )
        records["activation"].append(state["muscle_activation"])
        records["shadow_activation"].append(
            state["shadow_activation"]
        )
        records["nominal_excitation"].append(
            state["nominal_excitation"]
        )
        records["adjusted_excitation"].append(
            backend.data.ctrl.copy()
        )

        if state["terminated"] or state["truncated"]:
            break

    return {
        key: np.asarray(value, dtype=np.float64)
        for key, value in records.items()
    }


def relative_change(actual: float, baseline: float) -> float:
    """Return percentage change relative to a positive baseline."""

    return 100.0 * (actual / max(baseline, 1.0e-8) - 1.0)


def analyze(
    baseline: dict[str, np.ndarray],
    pulse: dict[str, np.ndarray],
    *,
    joint_index: int,
    warmup_steps: int,
    pulse_steps: int,
) -> tuple[dict[str, object], dict[str, np.ndarray]]:
    """Compare paired rollouts during assistance and after removal."""

    count = min(len(baseline["time"]), len(pulse["time"]))
    start = warmup_steps
    pulse_stop = min(start + pulse_steps, count)
    recovery_start = pulse_stop
    if pulse_stop <= start or recovery_start >= count:
        raise RuntimeError("The motion ended before recovery was observed.")

    paired = {
        key: value[:count]
        for key, value in pulse.items()
    }
    for key in (
        "q",
        "dq",
        "human_torque",
        "nominal_torque",
        "activation",
        "nominal_excitation",
    ):
        paired[f"delta_{key}"] = (
            pulse[key][:count] - baseline[key][:count]
        )

    active = slice(start, pulse_stop)
    recovery = slice(recovery_start, count)
    joint = joint_index

    applied = pulse["exo_torque"][active, joint]
    delta_human = paired["delta_human_torque"][active, joint]
    valid = np.abs(applied) > 1.0e-6
    unloading_ratio = -delta_human[valid] / applied[valid]

    baseline_activation_cost = float(
        np.mean(np.square(baseline["activation"][active]))
    )
    pulse_activation_cost = float(
        np.mean(np.square(pulse["activation"][active]))
    )

    delta_q_recovery = paired["delta_q"][recovery, joint]
    delta_human_recovery = paired["delta_human_torque"][
        recovery, joint
    ]
    restoring = delta_q_recovery * delta_human_recovery < 0.0
    restoring_score = np.maximum(
        -delta_q_recovery * delta_human_recovery,
        0.0,
    )

    nominal_excitation_rms = float(
        np.sqrt(
            np.mean(
                np.square(
                    paired["delta_nominal_excitation"][recovery]
                )
            )
        )
    )
    nominal_torque_change = paired["delta_nominal_torque"][
        recovery, joint
    ]
    pre_pulse_state_error = max(
        float(
            np.max(
                np.abs(
                    pulse[key][:start] - baseline[key][:start]
                )
            )
        )
        for key in ("q", "dq", "human_torque", "activation")
    )
    crossed_baseline = bool(
        np.min(delta_q_recovery)
        < -MEANINGFUL_POSITION_DIFFERENCE_RAD
        and np.max(delta_q_recovery)
        > MEANINGFUL_POSITION_DIFFERENCE_RAD
    )

    summary: dict[str, object] = {
        "joint": JOINT_NAMES[joint],
        "samples": count,
        "pulse_samples": pulse_stop - start,
        "recovery_samples": count - recovery_start,
        "pre_pulse_state_max_error": pre_pulse_state_error,
        "mean_applied_pulse_nm": float(np.mean(applied)),
        "instant_unloading_ratio_mean": float(
            np.mean(unloading_ratio)
        ),
        "instant_unloading_ratio_first": float(unloading_ratio[0]),
        "activation_change_during_pulse_percent": relative_change(
            pulse_activation_cost,
            baseline_activation_cost,
        ),
        "human_torque_change_during_pulse_nm": float(
            np.mean(delta_human)
        ),
        "recovery_restoring_fraction": float(np.mean(restoring)),
        "recovery_restoring_score_mean_nm_rad": float(
            np.mean(restoring_score)
        ),
        "recovery_peak_position_difference_rad": float(
            np.max(np.abs(delta_q_recovery))
        ),
        "recovery_nominal_excitation_rms_change": (
            nominal_excitation_rms
        ),
        "recovery_nominal_torque_change_mean_nm": float(
            np.mean(nominal_torque_change)
        ),
        "returned_across_baseline": crossed_baseline,
    }
    return summary, paired


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-id", type=int, default=64)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--joint", choices=JOINT_NAMES, default=JOINT_NAMES[0])
    parser.add_argument("--pulse-nm", type=float, default=1.0)
    parser.add_argument("--warmup-steps", type=int, default=50)
    parser.add_argument("--pulse-steps", type=int, default=5)
    parser.add_argument("--recovery-steps", type=int, default=25)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    args = parser.parse_args()

    joint_index = JOINT_NAMES.index(args.joint)
    agent = make_agent(args.motion_id)
    policy = KinesisPolicy(agent)
    backend = AssistBackend(
        agent.env,
        exo_control_dt=CONTROL_DT,
        torque_rate_limit_nm_s=50.0,
        load_sharing=True,
    )

    try:
        baseline = run_rollout(
            backend,
            policy,
            seed=args.seed,
            joint_index=None,
            pulse_nm=0.0,
            warmup_steps=args.warmup_steps,
            pulse_steps=args.pulse_steps,
            recovery_steps=args.recovery_steps,
        )
        pulse = run_rollout(
            backend,
            policy,
            seed=args.seed,
            joint_index=joint_index,
            pulse_nm=args.pulse_nm,
            warmup_steps=args.warmup_steps,
            pulse_steps=args.pulse_steps,
            recovery_steps=args.recovery_steps,
        )
    finally:
        backend.close()

    summary, paired = analyze(
        baseline,
        pulse,
        joint_index=joint_index,
        warmup_steps=args.warmup_steps,
        pulse_steps=args.pulse_steps,
    )

    args.output.parent.mkdir(parents=True, exist_ok=True)
    npz_path = args.output.with_suffix(".npz")
    np.savez_compressed(
        npz_path,
        **{f"baseline_{key}": value for key, value in baseline.items()},
        **{f"pulse_{key}": value for key, value in pulse.items()},
        **paired,
    )

    report = {
        "motion_id": args.motion_id,
        "seed": args.seed,
        "pulse_nm": args.pulse_nm,
        "pulse_seconds": args.pulse_steps * CONTROL_DT,
        "recovery_seconds": args.recovery_steps * CONTROL_DT,
        "summary": summary,
        "timeseries": str(npz_path),
    }
    with args.output.open("w", encoding="utf-8") as file:
        json.dump(report, file, indent=2, ensure_ascii=False)

    print(json.dumps(summary, indent=2, ensure_ascii=False))
    print("report:", args.output)
    print("timeseries:", npz_path)


if __name__ == "__main__":
    main()
