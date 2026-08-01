"""区分外骨骼机械作用和 Kinesis 闭环补偿。"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np

from RL.env.kinesis.assist_backend import AssistBackend
from RL.runners.kinesis_assist_evaluate import to_float
from RL.env.kinesis.teacher import (
    KinesisPolicy,
    make_agent,
)


GEXO_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = (
    GEXO_ROOT
    / "RL/outputs/kinesis_feedback/report.json"
)


class RecordingPolicy:
    """执行 Kinesis，同时记录每次输出的86维动作。"""

    def __init__(self, policy: KinesisPolicy) -> None:
        self.policy = policy
        self.actions = []

    def reset(self, seed: int) -> None:
        self.policy.reset(seed)
        self.actions = []

    def __call__(self, observation: np.ndarray) -> np.ndarray:
        action = self.policy(observation)
        self.actions.append(action.copy())
        return action


class ReplayPolicy:
    """忽略 observation，依次回放已经记录的动作。"""

    def __init__(self, actions: list[np.ndarray]) -> None:
        self.actions = [
            action.copy()
            for action in actions
        ]
        self.index = 0
        self.used_actions = []

    def reset(self, seed: int) -> None:
        del seed
        self.index = 0
        self.used_actions = []

    def __call__(self, observation: np.ndarray) -> np.ndarray:
        del observation

        if self.index >= len(self.actions):
            raise RuntimeError(
                "Replay action sequence is exhausted."
            )

        action = self.actions[self.index]
        self.index += 1
        self.used_actions.append(action.copy())
        return action.copy()


def policy_hash(model) -> str:
    """计算权重与buffer的SHA256，确认评估前后完全一致。"""

    digest = hashlib.sha256()

    for name, tensor in sorted(
        model.state_dict().items()
    ):
        digest.update(name.encode("utf-8"))
        digest.update(
            tensor.detach().cpu().numpy().tobytes()
        )

    return digest.hexdigest()


def rms_difference(first: np.ndarray, second: np.ndarray) -> float:
    """计算两段相同语义数据的配对RMSE。"""

    length = min(len(first), len(second))

    if length == 0:
        return float("nan")

    difference = first[:length] - second[:length]
    return float(np.sqrt(np.mean(difference ** 2)))


def run_trial(
    agent,
    policy,
    *,
    seed: int,
    assist_gain: float,
    warmup_steps: int,
    max_steps: int,
    torque_reference=None,
) -> dict:
    """运行闭环或动作回放实验。"""

    backend = AssistBackend(
        agent.env,
        torque_limit_nm=6.0,
        torque_rate_limit_nm_s=50.0,
    )

    policy.reset(seed)
    backend.reset(seed=seed)

    previous_muscle_torque = np.zeros(
        4,
        dtype=np.float32,
    )

    positions = []
    muscle_torques = []
    exo_torques = []
    exo_powers = []
    rewards = []

    terminated = False
    truncated = False

    for step in range(max_steps):
        if step < warmup_steps:
            target_torque = np.zeros(
                4,
                dtype=np.float32,
            )
        elif torque_reference is None:
            # 闭环模式：使用当前实验的上一时刻肌肉力矩。
            target_torque = (
                assist_gain
                * previous_muscle_torque
            )
        else:
            # 隔离模式：使用基准实验记录的肌肉力矩。
            reference_index = min(
                step - 1,
                len(torque_reference) - 1,
            )
            target_torque = (
                assist_gain
                * torque_reference[reference_index]
            )

        state = backend.step(
            target_torque,
            policy,
        )

        previous_muscle_torque = np.asarray(
            state["muscle_torque"],
            dtype=np.float32,
        )

        positions.append(state["joint_position"])
        muscle_torques.append(state["muscle_torque"])
        exo_torques.append(state["exo_torque"])
        exo_powers.append(state["exo_power"])
        rewards.append(state["reward"])

        terminated = bool(state["terminated"])
        truncated = bool(state["truncated"])

        if terminated or truncated:
            break

    positions = np.asarray(positions)
    muscle_torques = np.asarray(muscle_torques)
    exo_torques = np.asarray(exo_torques)
    exo_powers = np.asarray(exo_powers)

    return {
        "q": positions,
        "muscle_torque": muscle_torques,
        "summary": {
            "success": bool(truncated and not terminated),
            "steps": len(positions),
            "mpjpe_mm": 1000.0 * to_float(
                getattr(agent.env, "mpjpe_value", np.nan)
            ),
            "frame_coverage": to_float(
                getattr(agent.env, "frame_coverage", np.nan)
            ),
            "episode_return": float(np.sum(rewards)),
            "mean_absolute_muscle_torque_nm": float(
                np.mean(np.abs(muscle_torques))
            ),
            "mean_absolute_exo_torque_nm": float(
                np.mean(np.abs(exo_torques))
            ),
            "positive_exo_work_j": float(
                np.sum(np.maximum(exo_powers, 0.0))
                * 0.02
            ),
            "negative_exo_work_j": float(
                np.sum(np.minimum(exo_powers, 0.0))
                * 0.02
            ),
        },
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--motion-id", type=int, default=8)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--assist-gain", type=float, default=0.05)
    parser.add_argument("--warmup-steps", type=int, default=25)
    parser.add_argument("--max-steps", type=int, default=300)
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    args = parser.parse_args()

    agent = make_agent(args.motion_id)

    # 显式禁止梯度，使“冻结”在代码语义上也完全明确。
    for parameter in agent.policy_net.parameters():
        parameter.requires_grad_(False)

    agent.policy_net.eval()
    hash_before = policy_hash(agent.policy_net)

    baseline_policy = RecordingPolicy(
        KinesisPolicy(agent)
    )
    baseline = run_trial(
        agent,
        baseline_policy,
        seed=args.seed,
        assist_gain=0.0,
        warmup_steps=args.warmup_steps,
        max_steps=args.max_steps,
    )

    replay_zero_policy = ReplayPolicy(
        baseline_policy.actions
    )
    replay_zero = run_trial(
        agent,
        replay_zero_policy,
        seed=args.seed,
        assist_gain=0.0,
        warmup_steps=args.warmup_steps,
        max_steps=args.max_steps,
        torque_reference=baseline["muscle_torque"],
    )

    replay_assist_policy = ReplayPolicy(
        baseline_policy.actions
    )
    replay_assist = run_trial(
        agent,
        replay_assist_policy,
        seed=args.seed,
        assist_gain=args.assist_gain,
        warmup_steps=args.warmup_steps,
        max_steps=args.max_steps,
        torque_reference=baseline["muscle_torque"],
    )

    closed_policy = RecordingPolicy(
        KinesisPolicy(agent)
    )
    closed_assist = run_trial(
        agent,
        closed_policy,
        seed=args.seed,
        assist_gain=args.assist_gain,
        warmup_steps=args.warmup_steps,
        max_steps=args.max_steps,
    )

    hash_after = policy_hash(agent.policy_net)

    report = {
        "policy_hash_before": hash_before,
        "policy_hash_after": hash_after,
        "policy_weights_unchanged": (
            hash_before == hash_after
        ),
        "baseline_replay_q_rmse_rad": rms_difference(
            baseline["q"],
            replay_zero["q"],
        ),
        "baseline_replay_action_rmse": rms_difference(
            np.asarray(baseline_policy.actions),
            np.asarray(replay_zero_policy.used_actions),
        ),
        "closed_loop_action_change_rmse": rms_difference(
            np.asarray(baseline_policy.actions),
            np.asarray(closed_policy.actions),
        ),
        "baseline": baseline["summary"],
        "replay_zero": replay_zero["summary"],
        "replay_assist": replay_assist["summary"],
        "closed_assist": closed_assist["summary"],
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

    print(
        "weights unchanged:",
        report["policy_weights_unchanged"],
    )
    print(
        "baseline/replay q RMSE:",
        report["baseline_replay_q_rmse_rad"],
    )
    print(
        "closed-loop action change RMSE:",
        report["closed_loop_action_change_rmse"],
    )
    print("report:", args.output)

    agent.env.close()


if __name__ == "__main__":
    main()
