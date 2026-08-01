"""评估外骨骼是否能替代一部分人体髋膝输出。

这是仿真特权控制器，不是最终可部署控制器：

    tau_exo(t) = assist_gain * tau_baseline(t)

实验比较正常人体、轻度肌力下降、正确助力和反向阻力。
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np

from RL.env.kinesis.assist_backend import AssistBackend
from RL.env.kinesis.teacher import (
    KinesisPolicy,
    make_agent,
)


GEXO_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_OUTPUT = (
    GEXO_ROOT
    / "RL/outputs/kinesis_assist/report.json"
)

CONDITIONS = (
    {
        "name": "baseline",
        "human_strength": 1.00,
        "assist_gain": 0.00,
    },
    {
        "name": "full_strength_assist",
        "human_strength": 1.00,
        "assist_gain": 0.10,
    },
    {
        "name": "reduced_strength",
        "human_strength": 0.95,
        "assist_gain": 0.00,
    },
    {
        "name": "reduced_strength_assist",
        "human_strength": 0.95,
        "assist_gain": 0.10,
    },
    {
        "name": "reduced_strength_resist",
        "human_strength": 0.95,
        "assist_gain": -0.10,
    },
)


def to_float(value, default=np.nan) -> float:
    """把 Kinesis 的标量或单元素数组统一转换为 float."""

    array = np.asarray(value, dtype=np.float64)

    if array.size == 0:
        return float(default)

    return float(np.mean(array))


def run_condition(
    agent,
    policy: KinesisPolicy,
    condition: dict,
    *,
    seed: int,
    warmup_steps: int,
    max_steps: int,
    torque_limit_nm: float = 6.0,
) -> dict:
    """运行一个完整运动片段并汇总助力指标."""

    # 训练阶段使用独立于电机峰值的保守力矩限制。
    backend = AssistBackend(
        agent.env,
        torque_limit_nm=torque_limit_nm,
        torque_rate_limit_nm_s=50.0,
        human_strength=1.0,
    )

    policy.reset(seed)
    backend.reset(seed=seed)

    excitation = []
    squared_excitation = []
    activation = []
    muscle_torque = []
    exo_torque = []
    exo_power = []
    torque_balance_error = []
    predicted_balance_error = []
    rewards = []

    terminated = False
    truncated = False

    for step in range(max_steps):
        # 所有实验先用正常人体走相同的热身段。
        if step >= warmup_steps:
            backend.human_strength = float(
                condition["human_strength"]
            )

            target_exo_torque = (
                float(condition["assist_gain"])
                * backend.baseline_muscle_torque()
            )
        else:
            target_exo_torque = np.zeros(
                4,
                dtype=np.float32,
            )

        state = backend.step(
            target_exo_torque,
            policy,
        )

        current_excitation = (
            backend.data.ctrl.copy()
        )

        excitation.append(
            float(np.mean(current_excitation))
        )
        squared_excitation.append(
            float(np.mean(current_excitation ** 2))
        )
        activation.append(
            float(np.mean(backend.data.act))
        )
        muscle_torque.append(
            np.asarray(state["muscle_torque"])
        )
        exo_torque.append(
            np.asarray(state["exo_torque"])
        )
        exo_power.append(
            float(state["exo_power"])
        )
        torque_balance_error.append(
            np.asarray(state["torque_balance_error"])
        )
        predicted_balance_error.append(
            np.asarray(state["predicted_balance_error"])
        )
        rewards.append(
            float(state["reward"])
        )

        terminated = bool(state["terminated"])
        truncated = bool(state["truncated"])

        if terminated or truncated:
            break

    muscle_torque = np.asarray(
        muscle_torque,
        dtype=np.float64,
    )
    exo_torque = np.asarray(
        exo_torque,
        dtype=np.float64,
    )
    exo_power = np.asarray(
        exo_power,
        dtype=np.float64,
    )
    torque_balance_error = np.asarray(
        torque_balance_error,
        dtype=np.float64,
    )
    predicted_balance_error = np.asarray(
        predicted_balance_error,
        dtype=np.float64,
    )

    # step() 的控制周期固定为20 ms。
    positive_exo_work = float(
        np.sum(np.maximum(exo_power, 0.0)) * 0.02
    )
    negative_exo_work = float(
        np.sum(np.minimum(exo_power, 0.0)) * 0.02
    )

    success = bool(truncated and not terminated)

    return {
        "name": condition["name"],
        "human_strength": condition["human_strength"],
        "assist_gain": condition["assist_gain"],
        "torque_limit_nm": torque_limit_nm,
        "steps": len(rewards),
        "duration_s": len(rewards) * 0.02,
        "success": success,
        "terminated": terminated,
        "truncated": truncated,
        "frame_coverage": to_float(
            getattr(agent.env, "frame_coverage", np.nan)
        ),
        "mpjpe_mm": 1000.0 * to_float(
            getattr(agent.env, "mpjpe_value", np.nan)
        ),
        "episode_return": float(np.sum(rewards)),
        "mean_excitation": float(
            np.mean(excitation)
        ),
        "mean_squared_excitation": float(
            np.mean(squared_excitation)
        ),
        "mean_activation": float(
            np.mean(activation)
        ),
        "mean_absolute_muscle_torque_nm": float(
            np.mean(np.abs(muscle_torque))
        ),
        "mean_absolute_exo_torque_nm": float(
            np.mean(np.abs(exo_torque))
        ),
        "peak_absolute_exo_torque_nm": float(
            np.max(np.abs(exo_torque))
        ),
        "rated_torque_saturation_ratio": float(
            np.mean(np.abs(exo_torque) >= 5.99)
        ),
        "mean_absolute_balance_error_nm": float(
            np.mean(np.abs(torque_balance_error))
        ),
        "mean_absolute_predicted_error_nm": float(
            np.mean(np.abs(predicted_balance_error))
        ),
        "positive_exo_work_j": positive_exo_work,
        "negative_exo_work_j": negative_exo_work,
    }


def make_comparisons(results: list[dict]) -> dict:
    """提取最重要的有无助力差异."""

    by_name = {
        result["name"]: result
        for result in results
    }

    weak = by_name["reduced_strength"]
    assisted = by_name["reduced_strength_assist"]
    resisted = by_name["reduced_strength_resist"]

    return {
        "assist_coverage_change": (
            assisted["frame_coverage"]
            - weak["frame_coverage"]
        ),
        "assist_mpjpe_change_mm": (
            assisted["mpjpe_mm"]
            - weak["mpjpe_mm"]
        ),
        "assist_excitation_change": (
            assisted["mean_squared_excitation"]
            - weak["mean_squared_excitation"]
        ),
        "assist_muscle_torque_change_percent": (
            100.0
            * (
                assisted["mean_absolute_muscle_torque_nm"]
                / weak["mean_absolute_muscle_torque_nm"]
                - 1.0
            )
        ),
        "assist_squared_excitation_change_percent": (
            100.0
            * (
                assisted["mean_squared_excitation"]
                / weak["mean_squared_excitation"]
                - 1.0
            )
        ),
        "assist_balance_error_ratio": (
            assisted["mean_absolute_balance_error_nm"]
            / assisted["mean_absolute_exo_torque_nm"]
        ),
        "resist_coverage_change": (
            resisted["frame_coverage"]
            - weak["frame_coverage"]
        ),
    }


def make_checks(results: list[dict]) -> dict:
    """给模式三最小实现提供可重复的验收条件。"""

    by_name = {
        result["name"]: result
        for result in results
    }
    baseline = by_name["baseline"]
    weak = by_name["reduced_strength"]
    assisted = by_name["reduced_strength_assist"]

    checks = {
        "zero_torque_equivalence": (
            baseline["mean_absolute_balance_error_nm"]
            < 1e-6
        ),
        "assisted_rollout_success": assisted["success"],
        "tracking_change_below_2_mm": (
            abs(assisted["mpjpe_mm"] - weak["mpjpe_mm"])
            < 2.0
        ),
        "muscle_torque_reduced": (
            assisted["mean_absolute_muscle_torque_nm"]
            < weak["mean_absolute_muscle_torque_nm"]
        ),
        "squared_excitation_reduced": (
            assisted["mean_squared_excitation"]
            < weak["mean_squared_excitation"]
        ),
        "balance_error_below_exo_torque": (
            assisted["mean_absolute_balance_error_nm"]
            < assisted["mean_absolute_exo_torque_nm"]
        ),
    }
    checks["all_passed"] = all(checks.values())
    return checks


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-id", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--warmup-steps",
        type=int,
        default=25,
    )
    parser.add_argument(
        "--max-steps",
        type=int,
        default=300,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args()

    agent = make_agent(args.motion_id)
    policy = KinesisPolicy(agent)

    try:
        results = []

        for condition in CONDITIONS:
            result = run_condition(
                agent,
                policy,
                condition,
                seed=args.seed,
                warmup_steps=args.warmup_steps,
                max_steps=args.max_steps,
                torque_limit_nm=6.0,
            )
            results.append(result)

            print(
                f"{result['name']:24s} "
                f"success={result['success']} "
                f"coverage={result['frame_coverage']:.3f} "
                f"mpjpe={result['mpjpe_mm']:.2f} mm "
                f"exo={result['mean_absolute_exo_torque_nm']:.2f} Nm "
                f"balance={result['mean_absolute_balance_error_nm']:.2f} Nm"
            )

        report = {
            "motion_id": args.motion_id,
            "seed": args.seed,
            "conditions": results,
            "comparisons": make_comparisons(results),
            "checks": make_checks(results),
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

        print(f"report: {args.output}")
        print(
            "all checks passed:",
            report["checks"]["all_passed"],
        )

    finally:
        agent.env.close()


if __name__ == "__main__":
    main()
