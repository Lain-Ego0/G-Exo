from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import gymnasium
import numpy as np

sys.modules.setdefault("gym", gymnasium)

import myosuite
from myosuite.utils import gym

from RL.env.myosuite.muscle_controller import MuscleController
from RL.env.myosuite.phase_reference import PhaseReference

RL_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_MANIFEST = (
    RL_ROOT
    / "assets/datasets/phase12_manifest.json"
)

DEFAULT_OUTPUT = (
    RL_ROOT
    / "outputs/human_rollout/rollout.npz"
)


def load_reference(
    manifest_path: Path,
) -> tuple[PhaseReference,dict]:
    
    manifest = json.loads(
        manifest_path.read_text(encoding="utf-8")
    )
    
    dataset_root = Path(manifest["dataset_root"])
    
    for trial in manifest["trials"]:
        if trial["condition"] != "off":
            continue
        
        trial_dir = (
            dataset_root
            / trial["files"]["angle"]
        ).parent
        
        reference = PhaseReference(trial_dir)
        
        if np.all(reference.moment_mask):
            return reference, trial
        
    raise RuntimeError(
        "No off trial has complete 12-joint moment labels."
    )
    
def run_rollout(
    reference: PhaseReference,
    *,
    steps:int,
    seed:int,
) -> dict[str, np.ndarray | float | str]:
    
    environment = gym.make(
        "myoLegWalk-v0",
        reset_type = "init",
    )
    
    environment.reset(seed=seed)
    
    controller = MuscleController(environment)
    controller.reset()
    
    base = environment.unwrapped

    # Phase第0帧不一定对应MyoSuite的初始步态相位。
    # 从整条轨迹中选择与当前12关节姿态最接近的一帧开始。
    initial_q = base.mj_data.qpos[
        controller.qpos_ids
    ]
    start_index = int(
        np.argmin(
            np.mean(
                np.square(reference.q - initial_q),
                axis=1,
            )
        )
    )
    reference_start_time = float(
        reference.time_s[start_index]
    )
    
    time_history = []
    q_history = []
    q_reference_history = []
    reward_history = []
    activation_history = []
    
    termination_reason = "time_limit"
    
    try:
        for step in range(steps):
            reference_now = reference.sample(
                reference_start_time
                + float(base.mj_data.time)
            )
            
            action = controller.compute(reference_now)
            
            result = environment.step(action)
            
            if len(result) == 5:
                _,reward,terminated,truncated,_ = result
            else:
                _,reward,terminated,_ = result
                truncated = False
                
            reference_next = reference.sample(
                reference_start_time
                + float(base.mj_data.time)
            )
            
            q_actual = base.mj_data.qpos[
                controller.qpos_ids
            ].copy()
            
            time_history.append(base.mj_data.time)
            q_history.append(q_actual)
            q_reference_history.append(reference_next["q"])
            reward_history.append(float(reward))
            activation_history.append(
                controller.last_excitation.copy()
            )

            if terminated or truncated:
                termination_reason = (
                    "native_termination"
                    if terminated
                    else "time_limit"
                )
                break

    finally:
        environment.close()
        
    q = np.asarray(q_history,dtype=np.float32)
    q_reference = np.asarray(
        q_reference_history,
        dtype=np.float32,
    )
    
    position_error = q - q_reference
    
    return {
        "time_s": np.asarray(
            time_history,
            dtype=np.float32,
        ),
        "q": q,
        "q_reference": q_reference,
        "position_error": position_error,
        "reward": np.asarray(
            reward_history,
            dtype=np.float32,
        ),
        "activation": np.asarray(
            activation_history,
            dtype=np.float32,
        ),
        "termination_reason": termination_reason,
        "position_rmse_rad": float(
            np.sqrt(np.mean(np.square(position_error)))
        ),
        "mean_activation": float(
            np.mean(activation_history)
        ),
    }
    
def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--manifest",
        type=Path,
        default=DEFAULT_MANIFEST,
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=DEFAULT_OUTPUT,
    )
    parser.add_argument(
        "--steps",
        type=int,
        default=1000,
    )
    parser.add_argument(
        "--seed",
        type=int,
        default=0,
    )

    arguments = parser.parse_args()

    reference, trial = load_reference(
        arguments.manifest
    )

    result = run_rollout(
        reference,
        steps=arguments.steps,
        seed=arguments.seed,
    )

    output_path = arguments.output.resolve()
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    np.savez(
        output_path,
        **result,
    )

    print(
        "trial:",
        trial["subject"],
        trial["trial"],
    )
    print("steps:", len(result["time_s"]))
    print(
        "position RMSE rad:",
        f"{result['position_rmse_rad']:.6f}",
    )
    print(
        "mean activation:",
        f"{result['mean_activation']:.6f}",
    )
    print(
        "termination:",
        result["termination_reason"],
    )
    print("output:", output_path)


if __name__ == "__main__":
    main()
    
