"""检查四个外骨骼力矩通道的方向和因果响应。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.env.kinesis.teacher import KinesisPolicy, make_agent

GEXO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    GEXO_ROOT
    / "RL/outputs/kinesis_pulse_test/report.json"
)

from RL.env.kinesis.assist_backend import (  # noqa: E402
    AssistBackend,
    JOINT_NAMES,
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
    settle_steps: int,
) -> dict[str, np.ndarray]:
    """运行零力矩基准或单关节脉冲实验."""

    policy.reset(seed)
    backend.reset(seed=seed)

    total_steps = (
        warmup_steps
        + pulse_steps
        + settle_steps
    )

    time = []
    joint_position = []
    joint_velocity = []
    applied_torque = []

    for step in range(total_steps):
        torque = np.zeros(4, dtype=np.float32)

        pulse_active = (
            joint_index is not None
            and warmup_steps
            <= step
            < warmup_steps + pulse_steps 
        )

        if pulse_active:
            torque[joint_index] = pulse_nm

        state = backend.step(torque, policy)

        time.append(state["time"])
        joint_position.append(state["joint_position"])
        joint_velocity.append(state["joint_velocity"])
        applied_torque.append(state["exo_torque"])

        if state["terminated"] or state["truncated"]:
            break

    return {
        "time": np.asarray(time, dtype=np.float64),
        "q": np.asarray(
            joint_position,
            dtype=np.float64,
        ),
        "dq": np.asarray(
            joint_velocity,
            dtype=np.float64,
        ),
        "tau": np.asarray(
            applied_torque,
            dtype=np.float64,
        ),
    }


def evaluate_pulse(
    baseline: dict[str, np.ndarray],
    pulse: dict[str, np.ndarray],
    *,
    joint_index: int,
    pulse_nm: float,
    warmup_steps: int,
    pulse_steps: int,
) -> dict[str, object]:
    """比较同 seed 的脉冲轨迹与零力矩轨迹."""

    sample_count = min(
        len(baseline["dq"]),
        len(pulse["dq"]),
    )

    start = warmup_steps
    stop = min(
        warmup_steps + pulse_steps,
        sample_count,
    )

    if stop <= start:
        raise RuntimeError(
            "Episode ended before the pulse window."
        )

    # 配对相减消除人体正常步态造成的角速度变化。
    delta_velocity = (
        pulse["dq"][start:stop, joint_index]
        - baseline["dq"][start:stop, joint_index]
    )

    first_delta = float(delta_velocity[0])
    mean_delta = float(np.mean(delta_velocity))

    # 第一个20 ms响应尚未被后续人体反馈大幅修正，
    # 因此最适合检查力矩通道方向。
    signed_response = float(
        np.sign(pulse_nm) * first_delta
    )

    return {
        "joint": JOINT_NAMES[joint_index],
        "pulse_nm": float(pulse_nm),
        "first_delta_dq_rad_s": first_delta,
        "mean_delta_dq_rad_s": mean_delta,
        "signed_first_response": signed_response,
        "direction_passed": bool(
            signed_response > 1e-5
        ),
        "actual_peak_torque_nm": float(
            np.max(
                np.abs(
                    pulse["tau"][
                        start:stop,
                        joint_index,
                    ]
                )
            )
        ),
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-id", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--pulse-nm", type=float, default=1.0)
    parser.add_argument("--warmup-steps", type=int, default=50)
    parser.add_argument("--pulse-steps", type=int, default=5)
    parser.add_argument("--settle-steps", type=int, default=10)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args()

    agent = make_agent(args.motion_id)
    policy = KinesisPolicy(agent)

    backend = AssistBackend(
        agent.env,
        torque_rate_limit_nm_s=50.0,
        load_sharing=False,
    )

    try:
        # 所有脉冲实验都和这一条零力矩轨迹比较。
        baseline = run_rollout(
            backend,
            policy,
            seed=args.seed,
            joint_index=None,
            pulse_nm=0.0,
            warmup_steps=args.warmup_steps,
            pulse_steps=args.pulse_steps,
            settle_steps=args.settle_steps,
        )

        results = []

        for joint_index in range(4):
            for pulse_nm in (
                args.pulse_nm,
                -args.pulse_nm,
            ):
                pulse = run_rollout(
                    backend,
                    policy,
                    seed=args.seed,
                    joint_index=joint_index,
                    pulse_nm=pulse_nm,
                    warmup_steps=args.warmup_steps,
                    pulse_steps=args.pulse_steps,
                    settle_steps=args.settle_steps,
                )

                result = evaluate_pulse(
                    baseline,
                    pulse,
                    joint_index=joint_index,
                    pulse_nm=pulse_nm,
                    warmup_steps=args.warmup_steps,
                    pulse_steps=args.pulse_steps,
                )
                results.append(result)

                print(
                    f"{result['joint']:18s} "
                    f"pulse={pulse_nm:+.1f} Nm "
                    f"delta_dq="
                    f"{result['first_delta_dq_rad_s']:+.6f} "
                    f"passed={result['direction_passed']}"
                )

        report = {
            "motion_id": args.motion_id,
            "seed": args.seed,
            "pulse_nm": args.pulse_nm,
            "all_passed": all(
                result["direction_passed"]
                for result in results
            ),
            "results": results,
        }

        args.output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        with args.output.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                report,
                file,
                indent=2,
                ensure_ascii=False,
            )

        print(f"all passed: {report['all_passed']}")
        print(f"report: {args.output}")

    finally:
        backend.close()


if __name__ == "__main__":
    main()
