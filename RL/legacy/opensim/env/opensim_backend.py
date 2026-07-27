from __future__ import annotations

import sys
from pathlib import Path
from typing import Any

import numpy as np
import opensim as osim

JOINT_NAMES = (
    "LHip_rz",
    "LKnee_rz",
    "RHip_rz",
    "RKnee_rz",
)

IMU_BODY_NAMES = (
    "LeftThigh",
    "LeftShank",
    "RightThigh",
    "RightShank",
)

def default_model_path() -> Path:
    return (
        Path(sys.prefix)
        / "share"
        / "doc"
        / "OpenSim"
        / "Code"
        / "Python"
        / "dynamic_walker_example_model.osim"
    )
    
class OpenSimBackend:
    def __init__(
        self,
        model_path:str | Path | None = None,
        *,
        control_dt:float = 0.02,
        human_torque_limit_nm:float = 150.0,
        exo_torque_limit_nm:float = 10.0,
    ) -> None:
        self.model_path = (
            default_model_path() 
            if model_path is None 
            else Path(model_path)
        )
        
        self.control_dt = control_dt
        self.human_torque_limit_nm = float(human_torque_limit_nm)
        self.exo_torque_limit_nm = float(exo_torque_limit_nm)
        
        self._model:osim.Model | None = None
        self._manager:osim.Manager | None = None
        self._state:osim.State | None = None
        
        self._human_controller:osim.PrescribedController | None = None
        self._exo_controller:osim.PrescribedController | None = None
        
        self._human_commands:tuple[osim.Constant,...] = ()
        self._exo_commands:tuple[osim.Constant,...] = ()
        
        osim.Logger.setLevelString("Error")
        
    def reset(
        self,
        seed:int | None = None,
    ) -> dict[str, Any]:
        del seed
        
        self.close()
        
        self._model = osim.Model(str(self.model_path))
        
        (
            self._human_controller,
            self._human_commands,
        ) = self._add_actuator_bank(
            prefix = "human",
            torque_limit_nm = self.human_torque_limit_nm,
        )
        
        (
            self._exo_controller,
            self._exo_commands,
        ) = self._add_actuator_bank(
            prefix = "exo",
            torque_limit_nm = self.exo_torque_limit_nm,
        )
        
        self._state = self._model.initSystem()
        self._state.setTime(0.0)
        
        self._manager = osim.Manager(self._model)
        self._manager.setIntegratorAccuracy(1.0e-4)
        self._manager.initialize(self._state)
        
        self._write_commands(
            self._human_commands,
            np.zeros(4,dtype=np.float32),
        )
        
        self._write_commands(
            self._exo_commands,
            np.zeros(4,dtype=np.float32),
        )
        
        return self._state_dict()
    
    def step(
        self,
        *,
        human_control:np.ndarray,
        exo_torque:np.ndarray,
        control_dt:float,
    ) -> dict[str,Any]:
        if(
            self._model is None
            or self._manager is None
            or self._state is None
        ):
            raise RuntimeError("call reset() before step()")
        
        dt = float(control_dt)
        
        if abs(dt - self.control_dt) > 1.0e-12:
            raise ValueError(
                "control_dt must match backend control_dt."
            )
            
        self._write_commands(
            self._human_commands,
            human_control,
        )
        
        self._write_commands(
            self._exo_commands,
            exo_torque,
        )
        
        next_time = float(self._state.getTime() + self.control_dt)
        
        self._state = self._manager.integrate(next_time)
        
        return self._state_dict()
    
    def close(self) -> None:
        self._manager = None
        self._state = None
        
        self._human_commands = ()
        self._exo_commands = ()
        
        self._human_controller = None
        self._exo_controller = None
        
        self._model = None
        
    def _add_actuator_bank(
        self,
        *,
        prefix:str,
        torque_limit_nm:float,
    ) -> tuple[
        osim.PrescribedController,
        tuple[osim.Constant,...],
    ]:
        if self._model is None:
            raise RuntimeError("Model has not been created.")
      
        controller = osim.PrescribedController()
        controller.setName(f"{prefix}_controller")
      
        for joint_name in JOINT_NAMES:
            actuator = osim.CoordinateActuator(joint_name)
            actuator.setName(f"{prefix}_{joint_name}")
          
            actuator.setOptimalForce(1.0)
            actuator.setMinControl(-torque_limit_nm)
            actuator.setMaxControl(torque_limit_nm)
          
            self._model.addForce(actuator)
          
            controller.addActuator(actuator)
          
            controller.prescribeControlForActuator(
                actuator.getName(),
                osim.Constant(0.0),
            )  
          
        self._model.addController(controller)
        
        functions = controller.upd_ControlFunctions()
        
        commands = tuple(
            osim.Constant.safeDownCast(
                functions.get(index)
            )
            for index in range(functions.getSize())
        )
        
        return controller, commands
    
    @staticmethod
    def _write_commands(
        commands:tuple[osim.Constant,...],
        torque:np.ndarray,
    ) -> None:
        values = np.asarray(
            torque,
            dtype=np.float64,
        )
        
        if values.shape != (4,):
            raise ValueError(
                f"Torque must have shape (4,),got {values.shape}."
            )
        
        for command,value in zip(commands,values):
            command.setValue(float(value))
            
    def _read_virtual_imus(
        self,
    ) -> tuple[np.ndarray,np.ndarray]:
        if self._model is None or self._state is None:
            raise RuntimeError(
                "OpenSim state is unavailable."
        )
            
        self._model.realizeAcceleration(
            self._state
        )
        
        gravity_ground = self._vec3_to_numpy(
            self._model.getGravity()
        )
        
        body_set = self._model.getBodySet()
        
        angular_velocity_rows = []
        specific_force_rows = []
        
        for body_name in IMU_BODY_NAMES:
            body = body_set.get(body_name)
            
            rotation = body.getTransformInGround(
                self._state
            ).R()
            
            rotation_ground_from_body = np.asarray(
            [
                [
                    rotation.get(row, column)
                    for column in range(3)
                ]
                for row in range(3)
            ],
            dtype=np.float64,
            )
            
            angular_velocity_ground = (
                self._vec3_to_numpy(
                    body.getAngularVelocityInGround(
                        self._state
                    )
                )
            )
            
            linear_acceleration_ground = (
                self._vec3_to_numpy(
                    body.findStationAccelerationInGround(
                        self._state,
                        body.getMassCenter(),
                    )
                )
            )
            
            angular_velocity_body = (
                rotation_ground_from_body.T
                @ angular_velocity_ground
            )
            
            specific_force_body = (
                rotation_ground_from_body.T
                @ (
                    linear_acceleration_ground
                    - gravity_ground
                )
            )
            
            angular_velocity_rows.append(
                angular_velocity_body
            )

            specific_force_rows.append(
                specific_force_body
            )
            
        return (
            np.asarray(
                angular_velocity_rows,
                dtype=np.float64,
            ),
            np.asarray(
                specific_force_rows,
                dtype=np.float64,
            ),
        )
          
    @staticmethod  
    def _vec3_to_numpy(
        value:osim.Vec3,
    ) -> np.ndarray:
        return np.asarray(
            [
                value.get(index)
                for index in range(3)
            ],
            dtype=np.float64,
        )
            
    def _state_dict(self) -> dict[str,Any]:
        if self._model is None or self._state is None:
            raise RuntimeError("OpenSim state is unavailable.")
        
        coordinates = self._model.getCoordinateSet()
        
        tracking_q = np.asarray(
            [
                coordinates.get(name).getValue(self._state)
                for name in JOINT_NAMES
            ],
            dtype=np.float32,
        )
        
        tracking_dq = np.asarray(
            [
                coordinates.get(name).getSpeedValue(self._state)
                for name in JOINT_NAMES
            ],
            dtype=np.float32,
        )

        pelvis_x = coordinates.get(
            "Pelvis_tx"
        )

        pelvis_y = coordinates.get(
            "Pelvis_ty"
        )

        pelvis_rz = coordinates.get(
            "Pelvis_rz"
        )
        
        imu_angular_velocity, imu_specific_force = self._read_virtual_imus()

        return {
            "time": float(self._state.getTime()),

            "tracking_q": tracking_q,
            "tracking_dq": tracking_dq,

            # 临时模型中，外骨骼与人体关节刚性重合。
            "motor_q": tracking_q.copy(),
            "motor_dq": tracking_dq.copy(),

            "pelvis_x": float(
                pelvis_x.getValue(self._state)
            ),

            "pelvis_y": float(
                pelvis_y.getValue(self._state)
            ),

            "pelvis_dx": float(
                pelvis_x.getSpeedValue(self._state)
            ),

            "pelvis_dy": float(
                pelvis_y.getSpeedValue(self._state)
            ),

            "pelvis_angle": float(
                pelvis_rz.getValue(self._state)
            ),

            "pelvis_dangle": float(
                pelvis_rz.getSpeedValue(self._state)
            ),
            
            "imu_angular_velocity": imu_angular_velocity,
            "imu_specific_force": imu_specific_force,
        }