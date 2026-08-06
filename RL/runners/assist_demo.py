from __future__ import annotations

import argparse
import csv
import json
import time
from contextlib import nullcontext
from pathlib import Path

import mujoco
import mujoco.viewer
import myosuite
import numpy as np
from myosuite.utils import gym

from RL.env.myosuite.exo_overlay import (
    GExoMocapDriver,
    build_gexo_overlay_model,
)
from RL.env.myosuite.teacher_controller import (
    DepRLTeacherController,
)
from RL.env.torque import TorqueActuator


PROJECT_ROOT = Path(__file__).resolve().parents[2]

DEFAULT_OUTPUT_DIR = (
    PROJECT_ROOT / "RL/output/demo_7_27/runs"
)

JOINT_NAMES = (
    "hip_flexion_l",
    "knee_angle_l",
    "hip_flexion_r",
    "knee_angle_r",
)

JOINT_LABELS = (
    "left_hip",
    "left_knee",
    "right_hip",
    "right_knee",
)

RATED_TORQUE_NM = 6.0
PEAK_TORQUE_NM = 17.0
EXO_CONTROL_DT = 0.02


def get_joint_addresses(
    model: mujoco.MjModel,
) -> tuple[np.ndarray, np.ndarray]:
    """查询四个人体关节的 qpos 和 qvel 地址。"""

    qpos_addresses = []
    dof_addresses = []

    for joint_name in JOINT_NAMES:
        joint_id = mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_JOINT,
            joint_name,
        )

        if joint_id < 0:
            raise ValueError(
                f"Missing MuJoCo joint: {joint_name}"
            )

        qpos_addresses.append(
            int(model.jnt_qposadr[joint_id])
        )
        dof_addresses.append(
            int(model.jnt_dofadr[joint_id])
        )

    return (
        np.asarray(qpos_addresses, dtype=np.int32),
        np.asarray(dof_addresses, dtype=np.int32),
    )


def termination_reason(
    base_environment,
    terminated: bool,
    truncated: bool,
    com_height: float,
) -> str:
    if truncated:
        return "time_limit"

    if terminated:
        if com_height < float(base_environment.min_height):
            return "low_com_height"

        return "root_rotation"

    return "manual_step_limit"


def write_csv(
    output_path: Path,
    rows: list[dict[str, float | int | bool]],
) -> None:
    output_path.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    with output_path.open(
        "w",
        encoding="utf-8",
        newline="",
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=list(rows[0]),
        )
        writer.writeheader()
        writer.writerows(rows)


def run_episode(
    environment,
    teacher: DepRLTeacherController,
    overlay: GExoMocapDriver,
    actuator: TorqueActuator,
    *,
    mode: str,
    seed: int,
    max_steps: int,
    assist_gain: float,
    use_viewer: bool,
    real_time: bool,
    show_muscles: bool,
    end_pause_s: float,
) -> tuple[list[dict], dict]:
    """运行一次 baseline 或 assist episode。"""

    if mode not in ("baseline", "assist"):
        raise ValueError(f"Unknown mode: {mode}")

    base_environment = environment.unwrapped
    model = base_environment.mj_model
    view_data = base_environment.mj_data
    sim_data = base_environment.robot.mj_data

    qpos_addresses, dof_addresses = (
        get_joint_addresses(model)
    )

    # A/B 两组必须从同一个随机初态开始。
    np.random.seed(seed)
    base_environment.seed(seed)

    observation, _ = environment.reset(seed=seed)

    teacher.reset()
    actuator.reset()
    sim_data.qfrc_applied[:] = 0.0
    overlay.update(view_data)

    native_dt = float(base_environment.dt)
    control_stride = int(
        round(EXO_CONTROL_DT / native_dt)
    )

    if not np.isclose(
        control_stride * native_dt,
        EXO_CONTROL_DT,
    ):
        raise RuntimeError(
            "MyoSuite dt cannot represent 50 Hz control."
        )

    pelvis_id = mujoco.mj_name2id(
        model,
        mujoco.mjtObj.mjOBJ_BODY,
        "pelvis",
    )

    start_forward_position = float(sim_data.qpos[1])
    episode_return = 0.0
    rows: list[dict] = []
    current_exo_torque = np.zeros(4, dtype=np.float32)
    reason = "manual_step_limit"

    viewer_context = (
        mujoco.viewer.launch_passive(model, view_data)
        if use_viewer
        else nullcontext(None)
    )

    with viewer_context as viewer:
        if viewer is not None:
            # 隐藏碰撞几何，但保留人体肌肉 tendon。
            viewer.opt.geomgroup[4] = 0
            viewer.opt.flags[
                mujoco.mjtVisFlag.mjVIS_TENDON
            ] = show_muscles

            viewer.cam.type = (
                mujoco.mjtCamera.mjCAMERA_TRACKING
            )
            viewer.cam.trackbodyid = pelvis_id
            viewer.cam.distance = 3.2
            viewer.cam.azimuth = 145.0
            viewer.cam.elevation = -12.0

        for step in range(max_steps):
            wall_start = time.perf_counter()

            if viewer is not None and not viewer.is_running():
                reason = "viewer_closed"
                break

            # 外骨骼以 50 Hz 更新，MyoSuite 以 100 Hz 积分。
            if step % control_stride == 0:
                if mode == "assist":
                    muscle_joint_torque = np.asarray(
                        sim_data.qfrc_actuator[dof_addresses],
                        dtype=np.float32,
                    )

                    target_torque = (
                        assist_gain * muscle_joint_torque
                    )

                    normalized_action = (
                        target_torque / PEAK_TORQUE_NM
                    )
                else:
                    normalized_action = np.zeros(
                        4,
                        dtype=np.float32,
                    )

                current_exo_torque = actuator.process(
                    normalized_action
                )

            # 只在四个人体髋膝自由度施加外骨骼力矩。
            sim_data.qfrc_applied[:] = 0.0
            sim_data.qfrc_applied[
                dof_addresses
            ] = current_exo_torque

            muscle_action = teacher.compute(observation)

            (
                observation,
                reward,
                terminated,
                truncated,
                info,
            ) = environment.step(muscle_action)

            episode_return += float(reward)

            # 环境积分后，根据新人体姿态更新外骨骼外观。
            overlay.update(view_data)

            com_height = float(
                np.asarray(
                    info["obs_dict"]["height"]
                ).reshape(-1)[0]
            )

            com_velocity = np.asarray(
                info["obs_dict"]["com_vel"],
                dtype=np.float64,
            ).reshape(-1)

            forward_speed = float(com_velocity[1])
            distance = (
                start_forward_position
                - float(sim_data.qpos[1])
            )

            joint_position = np.asarray(
                sim_data.qpos[qpos_addresses],
                dtype=np.float64,
            )

            joint_velocity = np.asarray(
                sim_data.qvel[dof_addresses],
                dtype=np.float64,
            )

            muscle_joint_torque = np.asarray(
                sim_data.qfrc_actuator[dof_addresses],
                dtype=np.float64,
            )

            exo_power = (
                current_exo_torque * joint_velocity
            )

            row = {
                "step": step,
                "time_s": float(sim_data.time),
                "com_height_m": com_height,
                "forward_speed_m_s": forward_speed,
                "distance_m": distance,
                "mean_excitation": float(
                    np.mean(base_environment.last_ctrl)
                ),
                "mean_activation": float(
                    np.mean(sim_data.act)
                ),
                "exo_power_w": float(
                    np.sum(exo_power)
                ),
                "terminated": bool(terminated),
                "truncated": bool(truncated),
            }

            for index, label in enumerate(JOINT_LABELS):
                row[f"{label}_q_rad"] = float(
                    joint_position[index]
                )
                row[f"{label}_dq_rad_s"] = float(
                    joint_velocity[index]
                )
                row[f"{label}_muscle_tau_nm"] = float(
                    muscle_joint_torque[index]
                )
                row[f"{label}_exo_tau_nm"] = float(
                    current_exo_torque[index]
                )

            rows.append(row)

            if step % 50 == 0:
                print(
                    f"{mode:8s} "
                    f"t={sim_data.time:5.2f} "
                    f"height={com_height:5.3f} "
                    f"speed={forward_speed:6.3f} "
                    f"distance={distance:6.3f} "
                    f"tau={np.round(current_exo_torque, 2)}"
                )

            if viewer is not None:
                viewer.sync()

            if terminated or truncated:
                reason = termination_reason(
                    base_environment,
                    terminated,
                    truncated,
                    com_height,
                )
                break

            if real_time:
                elapsed = time.perf_counter() - wall_start
                time.sleep(max(0.0, native_dt - elapsed))

        sim_data.qfrc_applied[:] = 0.0

        if viewer is not None and end_pause_s > 0.0:
            deadline = time.perf_counter() + end_pause_s

            while (
                viewer.is_running()
                and time.perf_counter() < deadline
            ):
                viewer.sync()
                time.sleep(0.02)

    if not rows:
        raise RuntimeError("Episode produced no samples.")

    exo_torque = np.asarray(
        [
            [
                row[f"{label}_exo_tau_nm"]
                for label in JOINT_LABELS
            ]
            for row in rows
        ],
        dtype=np.float64,
    )

    exo_power = np.asarray(
        [row["exo_power_w"] for row in rows],
        dtype=np.float64,
    )

    summary = {
        "mode": mode,
        "seed": seed,
        "steps": len(rows),
        "survival_time_s": float(
            len(rows) * native_dt
        ),
        "episode_return": episode_return,
        "forward_distance_m": float(
            rows[-1]["distance_m"]
        ),
        "mean_forward_speed_m_s": float(
            np.mean(
                [
                    row["forward_speed_m_s"]
                    for row in rows
                ]
            )
        ),
        "minimum_com_height_m": float(
            min(row["com_height_m"] for row in rows)
        ),
        "mean_activation": float(
            np.mean(
                [
                    row["mean_activation"]
                    for row in rows
                ]
            )
        ),
        "mean_absolute_exo_torque_nm": float(
            np.mean(np.abs(exo_torque))
        ),
        "peak_absolute_exo_torque_nm": float(
            np.max(np.abs(exo_torque))
        ),
        "above_rated_torque_ratio": float(
            np.mean(
                np.abs(exo_torque) > RATED_TORQUE_NM
            )
        ),
        "positive_exo_work_j": float(
            np.sum(np.maximum(exo_power, 0.0))
            * native_dt
        ),
        "termination_reason": reason,
    }

    return rows, summary


def main() -> None:
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--mode",
        choices=("baseline", "assist", "both"),
        default="both",
    )
    parser.add_argument("--seed", type=int, default=0)
    parser.add_argument("--max-steps", type=int, default=1000)
    parser.add_argument(
        "--muscle-strength",
        type=float,
        default=0.55,
    )
    parser.add_argument(
        "--assist-gain",
        type=float,
        default=0.3,
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=DEFAULT_OUTPUT_DIR,
    )
    parser.add_argument(
        "--no-viewer",
        action="store_true",
    )
    parser.add_argument(
        "--no-real-time",
        action="store_true",
    )
    parser.add_argument(
        "--hide-muscles",
        action="store_true",
    )
    parser.add_argument(
        "--end-pause",
        type=float,
        default=2.0,
    )

    arguments = parser.parse_args()

    model_path = build_gexo_overlay_model()

    environment = gym.make(
        "myoLegWalk-v0",
        model_path=str(model_path),
        reset_type="random",
    )

    base_environment = environment.unwrapped

    try:
        teacher = DepRLTeacherController(environment)

        # 构造较弱肌力场景，让助力效果容易观察。
        base_environment.mj_model.actuator_gainprm[
            :, 2
        ] *= arguments.muscle_strength

        overlay = GExoMocapDriver(
            base_environment.mj_model
        )

        actuator = TorqueActuator(
            torque_limit_nm=np.full(
                4,
                PEAK_TORQUE_NM,
                dtype=np.float32,
            ),
            torque_rate_limit_nm_s=np.full(
                4,
                600.0,
                dtype=np.float32,
            ),
            control_dt=EXO_CONTROL_DT,
        )

        modes = (
            ("baseline", "assist")
            if arguments.mode == "both"
            else (arguments.mode,)
        )

        summaries = {}

        for mode in modes:
            rows, summary = run_episode(
                environment,
                teacher,
                overlay,
                actuator,
                mode=mode,
                seed=arguments.seed,
                max_steps=arguments.max_steps,
                assist_gain=arguments.assist_gain,
                use_viewer=not arguments.no_viewer,
                real_time=not arguments.no_real_time,
                show_muscles=not arguments.hide_muscles,
                end_pause_s=arguments.end_pause,
            )

            write_csv(
                arguments.output_dir / f"{mode}.csv",
                rows,
            )

            summaries[mode] = summary
            print(json.dumps(
                summary,
                ensure_ascii=False,
                indent=2,
            ))

        result = {
            "configuration": {
                "seed": arguments.seed,
                "muscle_strength": arguments.muscle_strength,
                "assist_gain": arguments.assist_gain,
                "rated_torque_nm": RATED_TORQUE_NM,
                "peak_torque_nm": PEAK_TORQUE_NM,
                "exo_control_frequency_hz": 50,
            },
            "episodes": summaries,
        }

        if "baseline" in summaries and "assist" in summaries:
            result["comparison"] = {
                "survival_time_change_s": (
                    summaries["assist"]["survival_time_s"]
                    - summaries["baseline"]["survival_time_s"]
                ),
                "distance_change_m": (
                    summaries["assist"]["forward_distance_m"]
                    - summaries["baseline"]["forward_distance_m"]
                ),
                "activation_change": (
                    summaries["assist"]["mean_activation"]
                    - summaries["baseline"]["mean_activation"]
                ),
            }

        arguments.output_dir.mkdir(
            parents=True,
            exist_ok=True,
        )

        summary_path = (
            arguments.output_dir / "summary.json"
        )

        with summary_path.open(
            "w",
            encoding="utf-8",
        ) as file:
            json.dump(
                result,
                file,
                ensure_ascii=False,
                indent=2,
            )

        print(f"summary saved to: {summary_path}")

    finally:
        environment.close()


if __name__ == "__main__":
    main()
