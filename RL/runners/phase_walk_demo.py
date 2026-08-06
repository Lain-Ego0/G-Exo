"""Phase1/2参考轨迹驱动的人体快速行走demo。

人体控制链固定为：Phase参考力矩 + PD -> 肌肉募集 -> MyoSuite。
外骨骼模式只额外注入四个髋膝力矩，不训练人体PPO。
"""

from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from contextlib import nullcontext
from pathlib import Path

import gymnasium as gym
import mujoco
import mujoco.viewer
import numpy as np

sys.modules.setdefault("gym", gym)

from RL.env.myosuite.exo_overlay import (
    GExoMocapDriver,
    build_gexo_overlay_model,
)
from RL.env.myosuite.human_balance_env import (
    DEFAULT_MANIFEST,
    HumanBalanceEnv,
)


PROJECT_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_OUTPUT = PROJECT_ROOT / "RL/outputs/phase_walk_demo"

# MyoSuite参考顺序为右髋、右膝、左髋、左膝；单位为N m。
EXO_INDICES = (0, 3, 6, 9)
EXO_TORQUE_LIMITS = np.asarray((17.0, 17.0, 17.0, 17.0), dtype=np.float64)
ZERO_RESIDUAL = np.zeros(12, dtype=np.float32)


def write_csv(path: Path, rows: list[dict[str, float | int | bool]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)


def run(
    *,
    mode: str,
    steps: int,
    seed: int,
    speed: float,
    assist_gain: float,
    support_scale: float,
    kp: float,
    kd: float,
    output: Path,
    viewer_enabled: bool,
    real_time: bool,
    show_muscles: bool,
) -> dict[str, float | int | str]:
    model_path = build_gexo_overlay_model()
    environment = HumanBalanceEnv(
        manifest_path=DEFAULT_MANIFEST,
        split="train",
        speeds=(speed,),
        max_episode_steps=steps,
        support_range=(support_scale, support_scale),
        model_path=model_path,
    )
    environment.controller.kp = kp
    environment.controller.kd = kd

    rows: list[dict[str, float | int | bool]] = []
    overlay = GExoMocapDriver(environment.base.mj_model)
    base = environment.base
    pelvis_id = mujoco.mj_name2id(
        base.mj_model,
        mujoco.mjtObj.mjOBJ_BODY,
        "pelvis",
    )

    observation, reset_info = environment.reset(seed=seed)
    del observation
    environment.set_exo_torque(np.zeros(12, dtype=np.float64))
    overlay.update(base.mj_data)

    viewer_context = (
        mujoco.viewer.launch_passive(base.mj_model, base.mj_data)
        if viewer_enabled
        else nullcontext(None)
    )

    terminated = False
    truncated = False
    reason = "time_limit"

    with viewer_context as viewer:
        if viewer is not None:
            viewer.opt.geomgroup[4] = 0
            viewer.opt.flags[mujoco.mjtVisFlag.mjVIS_TENDON] = show_muscles
            viewer.cam.type = mujoco.mjtCamera.mjCAMERA_TRACKING
            viewer.cam.trackbodyid = pelvis_id
            viewer.cam.distance = 3.2
            viewer.cam.azimuth = 145.0
            viewer.cam.elevation = -12.0

        for step in range(steps):
            wall_start = time.perf_counter()
            if viewer is not None and not viewer.is_running():
                reason = "viewer_closed"
                break

            # 用当前所需关节力矩的固定比例助力，不训练人体策略。
            reference = environment.reference_now()
            exo_torque = np.zeros(12, dtype=np.float64)
            if mode == "assist":
                q = base.mj_data.qpos[environment.controller.qpos_ids]
                dq = base.mj_data.qvel[environment.controller.dof_ids]
                required_torque = (
                    np.asarray(reference["moment_nm_kg"], dtype=np.float64)
                    * environment.controller.body_mass_kg
                    + kp * (np.asarray(reference["q"]) - q)
                    + kd * (np.asarray(reference["dq"]) - dq)
                )
                exo_torque[list(EXO_INDICES)] = (
                    assist_gain * required_torque[list(EXO_INDICES)]
                )
                exo_torque[list(EXO_INDICES)] = np.clip(
                    exo_torque[list(EXO_INDICES)],
                    -EXO_TORQUE_LIMITS,
                    EXO_TORQUE_LIMITS,
                )

            environment.set_exo_torque(exo_torque)
            observation, reward, terminated, truncated, step_info = (
                environment.step(ZERO_RESIDUAL)
            )
            del observation
            overlay.update(base.mj_data)

            row = {
                "step": step,
                "time_s": float(base.mj_data.time),
                "reward": float(reward),
                "q_rmse_rad": float(step_info["q_rmse_rad"]),
                "mean_activation": float(np.mean(base.mj_data.act)),
                "support_scale": support_scale,
                "terminated": bool(terminated),
                "truncated": bool(truncated),
            }
            for index, name in enumerate(("r_hip", "r_knee", "l_hip", "l_knee")):
                row[f"{name}_exo_torque_nm"] = float(exo_torque[EXO_INDICES[index]])
            rows.append(row)

            if step % 50 == 0:
                print(
                    f"{mode:7s} t={base.mj_data.time:5.2f} "
                    f"q_rmse={row['q_rmse_rad']:.3f} "
                    f"activation={row['mean_activation']:.3f}"
                )

            if viewer is not None:
                viewer.sync()
            if terminated or truncated:
                reason = step_info["termination_reason"]
                break
            if real_time:
                time.sleep(max(0.0, float(base.dt) - (time.perf_counter() - wall_start)))

    environment.close()
    if not rows:
        raise RuntimeError("Phase demo produced no samples.")

    write_csv(output, rows)
    summary = {
        "mode": mode,
        "seed": seed,
        "steps": len(rows),
        "survival_time_s": float(base.dt * len(rows)),
        "mean_q_rmse_rad": float(np.mean([row["q_rmse_rad"] for row in rows])),
        "mean_activation": float(np.mean([row["mean_activation"] for row in rows])),
        "mean_abs_exo_torque_nm": float(
            np.mean(
                np.abs(
                    [
                        [
                            row[f"{name}_exo_torque_nm"]
                            for name in ("r_hip", "r_knee", "l_hip", "l_knee")
                        ]
                        for row in rows
                    ]
                )
            )
        ),
        "subject": reset_info["subject"],
        "trial": reset_info["trial"],
        "speed_mps": reset_info["speed_mps"],
        "kp": kp,
        "kd": kd,
        "assist_gain": assist_gain if mode == "assist" else 0.0,
        "support_scale": support_scale,
        "termination_reason": reason,
        "csv": str(output.resolve()),
    }
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return summary


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mode", choices=("baseline", "assist"), default="assist")
    parser.add_argument("--steps", type=int, default=1000)
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument(
        "--speed",
        type=float,
        choices=(0.6, 1.2, 1.8, 2.0, 2.5),
        default=0.6,
    )
    parser.add_argument("--assist-gain", type=float, default=0.30)
    parser.add_argument("--support-scale", type=float, default=0.75)
    parser.add_argument("--kp", type=float, default=100.0)
    parser.add_argument("--kd", type=float, default=8.0)
    parser.add_argument("--output", type=Path, default=None)
    parser.add_argument("--no-viewer", action="store_true")
    parser.add_argument("--no-real-time", action="store_true")
    parser.add_argument("--hide-muscles", action="store_true")
    args = parser.parse_args()

    output = args.output or (
        DEFAULT_OUTPUT / f"{args.mode}_seed{args.seed}.csv"
    )
    run(
        mode=args.mode,
        steps=args.steps,
        seed=args.seed,
        speed=args.speed,
        assist_gain=args.assist_gain,
        support_scale=args.support_scale,
        kp=args.kp,
        kd=args.kd,
        output=output,
        viewer_enabled=not args.no_viewer,
        real_time=not args.no_real_time,
        show_muscles=not args.hide_muscles,
    )


if __name__ == "__main__":
    main()
