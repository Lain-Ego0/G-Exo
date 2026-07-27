from __future__ import annotations

import argparse
import csv
import sys
import time
from pathlib import Path

import numpy as np
import opensim as osim

CONTROL_DT = 0.02

COORDINATE_NAMES = [
    "LHip_rz",
    "LKnee_rz",
    "RHip_rz",
    "RKnee_rz",
]

def default_model_path() -> Path:
    return(
        Path(sys.prefix)
        / "share"
        / "doc"
        / "OpenSim"
        / "Code"
        / "Python"
        / "dynamic_walker_example_model.osim"
    )
    
def add_exoskeleton_actuators(
    model:osim.Model,
    torque_limit_nm:float,
) -> list[osim.Constant]:
    controller = osim.PrescribedController()
    controller.setName("exo_controller")
    
    for coordinate_name in COORDINATE_NAMES:
        actuator = osim.CoordinateActuator(coordinate_name)
        actuator.setName(f"exo_{coordinate_name}")
        actuator.setOptimalForce(1.0)
        actuator.setMinControl(-torque_limit_nm)
        actuator.setMaxControl(torque_limit_nm)
        
        model.addForce(actuator)
        controller.addActuator(actuator)
        
        controller.prescribeControlForActuator(
            actuator.getName(),
            osim.Constant(0.0)
        )
        
    model.addController(controller)
    
    functions = controller.upd_ControlFunctions()
    
    return [
        osim.Constant.safeDownCast(functions.get(index))
        for index in range(functions.getSize())
    ]
    
def read_feedback(
    model:osim.Model,
    state:osim.State,
) -> tuple[np.ndarray,np.ndarray,float,float]:
    coordinates = model.getCoordinateSet()
    
    q = np.asarray(
        [
            coordinates.get(name).getValue(state)
            for name in COORDINATE_NAMES
        ],
        dtype=np.float64
    )
    
    dq = np.asarray(
        [
            coordinates.get(name).getSpeedValue(state)
            for name in COORDINATE_NAMES
        ],
        dtype = np.float64
    )
    
    pelvis_x = coordinates.get("Pelvis_tx").getValue(state)
    pelvis_y = coordinates.get("Pelvis_ty").getValue(state)

    return q, dq, float(pelvis_x), float(pelvis_y)

def pd_control(
    q: np.ndarray,
    dq: np.ndarray,
    q_reference: np.ndarray,
    *,
    kp: float,
    kd: float,
    torque_limit_nm: float,
) -> np.ndarray:
    torque = kp * (q_reference - q) - kd * dq

    return np.clip(
        torque,
        -torque_limit_nm,
        torque_limit_nm,
    )
    
def run_demo(
    *,
    model_path: Path,
    output_dir: Path,
    duration_s: float,
    visualize: bool,
) -> None:
    torque_limit_nm = 10.0
    kp = 2.0
    kd = 0.2

    if not model_path.is_file():
        raise FileNotFoundError(model_path)

    output_dir.mkdir(parents=True, exist_ok=True)

    # 关闭每个20 ms积分周期的OpenSim日志。
    osim.Logger.setLevelString("Warn")

    model = osim.Model(str(model_path))
    model.setName("controlled_dynamic_walker")
    model.setUseVisualizer(visualize)

    torque_commands = add_exoskeleton_actuators(
        model,
        torque_limit_nm,
    )

    state = model.initSystem()
    state.setTime(0.0)
    
    q_reference, _, _, _ = read_feedback(model, state)

    manager = osim.Manager(model)
    manager.setIntegratorAccuracy(1.0e-4)
    manager.initialize(state)

    feedback_rows: list[list[float]] = []

    number_of_steps = int(round(duration_s / CONTROL_DT))

    for step in range(number_of_steps):
        q, dq, pelvis_x, pelvis_y = read_feedback(
            model,
            state,
        )
        
        torque = pd_control(
                q,
                dq,
                q_reference,
                kp=kp,
                kd=kd,
                torque_limit_nm=torque_limit_nm,
            )
    
        for command, value in zip(torque_commands, torque):
            command.setValue(float(value))

        feedback_rows.append(
            [
                float(state.getTime()),
                pelvis_x,
                pelvis_y,
                *q.tolist(),
                *dq.tolist(),
                *torque.tolist(),
            ]
        )

        # OpenSim在下一个20 ms区间内以当前控制量积分。
        next_time = (step + 1) * CONTROL_DT
        state = manager.integrate(next_time)

        if step % 10 == 0:
            print(
                f"t={next_time:5.2f} "
                f"pelvis_x={pelvis_x:7.3f} "
                f"pelvis_y={pelvis_y:7.3f} "
                f"tau={np.round(torque, 3)}"
            )

        # 开启可视化时按真实时间播放。
        if visualize:
            time.sleep(CONTROL_DT)

    final_q, final_dq, final_pelvis_x, final_pelvis_y = (
        read_feedback(model, state)
    )

    feedback_rows.append(
        [
            float(state.getTime()),
            final_pelvis_x,
            final_pelvis_y,
            *final_q.tolist(),
            *final_dq.tolist(),
            *([0.0] * len(COORDINATE_NAMES)),
        ]
    )

    states_path = output_dir / "states.sto"
    feedback_path = output_dir / "feedback.csv"
    controlled_model_path = output_dir / "controlled_walker.osim"

    osim.STOFileAdapter.write(
        manager.getStatesTable(),
        str(states_path),
    )

    model.printToXML(str(controlled_model_path))

    header = [
        "time_s",
        "pelvis_x_m",
        "pelvis_y_m",
        *[f"{name}_q_rad" for name in COORDINATE_NAMES],
        *[f"{name}_dq_rad_s" for name in COORDINATE_NAMES],
        *[f"{name}_torque_nm" for name in COORDINATE_NAMES],
    ]

    with feedback_path.open(
        "w",
        newline="",
        encoding="utf-8",
    ) as file:
        writer = csv.writer(file)
        writer.writerow(header)
        writer.writerows(feedback_rows)

    values = np.asarray(feedback_rows, dtype=np.float64)
    
    if not np.all(np.isfinite(values)):
        raise RuntimeError("Simulation produced NaN or Inf.")

    if abs(float(state.getTime()) - duration_s) > 1.0e-9:
        raise RuntimeError(
            "Simulation did not reach the requested duration."
        )

    print("\nOpenSim demo passed")
    print("final time:", state.getTime())
    print("final pelvis x:", final_pelvis_x)
    print("model:", controlled_model_path)
    print("states:", states_path)
    print("feedback:", feedback_path)

    if visualize:
        input("Press Enter to close the visualizer...")

def main():
    parser = argparse.ArgumentParser()

    parser.add_argument(
        "--model",
        type=Path,
        default=default_model_path(),
    )

    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("RL/output/opensim_demo"),
    )

    parser.add_argument(
        "--duration",
        type=float,
        default=2.0,
    )

    parser.add_argument(
        "--visualize",
        action="store_true",
    )

    args = parser.parse_args()

    run_demo(
        model_path=args.model.expanduser().resolve(),
        output_dir=args.output_dir.expanduser().resolve(),
        duration_s=args.duration,
        visualize=args.visualize,
    )


if __name__ == "__main__":
    main()