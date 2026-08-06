from __future__ import annotations

from pathlib import Path

import gymnasium as gym
import mujoco
import numpy as np
from gymnasium import spaces

from temporarysim.pd import PDMimic
from temporarysim.gait import GaitSource

JOINT_NAMES = [
    "left_hip",
    "left_knee",
    "right_hip",
    "right_knee"
]

MOTOR_NAMES = [
    "left_hip_motor",
    "left_knee_motor",
    "right_hip_motor",
    "right_knee_motor"
]



class MimicEnv(gym.Env):
    metadata = {"render_modes": []}
    
    def __init__(
        self,
        model_path: str | Path = "temporarysim/model.xml",
        gait: GaitSource | None = None,
        control_dt:float = 0.02,
        episode_seconds: float = 10.0,
        residual_limit: float = 20.0,
    ):
        super().__init__()
        
        if gait is None:
            raise ValueError("gait must be provided")
        
        self.model_path = Path(model_path)
        self.gait = gait
        self.control_dt = float(control_dt)
        self.episode_seconds = float(episode_seconds)
        self.residual_limit = float(residual_limit)
        
        self.model = mujoco.Mjmodel.from_xml_path(str(self.model_path))
        self.data = mujoco.MjData(self.model)
        
        self.joint_qpos_ids = np.array(
            [self.model.jnt_qposadr[self.model.joint(name).id] for name in JOINT_NAMES],
            dtype=np.int32,
        )
        self.motor_ids = np.array(
            [self.model.actuator(name).id for name in MOTOR_NAMES],
            dtype=np.int32,
        )
        
        self.pd = PDMimic()
        self.t = 0.0
        self.step_count = 0
        self.max_steps = int(self.episode_seconds / self.control_dt)

        self.prev_action = np.zeros(4,dtype=np.float32)
        self.prev_tau = np.zeros(4,dtype=np.float32)
        
        self.observation_space = spaces.Box(
            low = -np.inf,
            high=np.inf,
            shape =(30,),
            dtype = np.float32,
        )        
        
        self.action_space = spaces.Box(
            low = -1.0,
            high=1.0,
            shape = (4,),
            dtype = np.float32,
        )
        
    def reset(self,*,seed:int | None = None,options:dict | None = None):
       super().reset(seed=seed)
       
       mujoco.mj_resetData(self.model, self.data)
       
       self.t = 0.0
       self.step_count = 0
       self.prev_action[:] = 0.0
       self.prev_tau[:] = 0.0
       
       q_ref,dq_ref,_ = self.gait.get(self.t)
       self.data.qpos[self.joint_qpos_ids] = q_ref
       self.data.qvel[self.joint_qpos_ids] = dq_ref
       mujoco.mj_forward(self.model, self.data)
       
       obs = self._make_obs()
       info = {}
       
       return obs, info
       
    def step(self,action:np.ndarray):
        action = np.asarray(action,dtype=np.float32)
        action = np.clip(action,-1.0,1.0)
        
        q,dq = self._get_d_dq()
        q_ref,dq_ref,phase = self.gait.get(self.t)
        
        tau_pd = self.pd(q=q,q_ref=q_ref,dq=dq,dq_ref=dq_ref)
        tau_rl = action* self.residual_limit
        tau = tau_pd + tau_rl
        tau = np.clip(tau,-80.0,80.0).astype(np.float32)
        
        self.data.ctrl[self.motor_ids] = tau
        
        sim_steps = max(1,int(round(self.control_dt / self.model.opt.timestep)))
        for _ in range(sim_steps):
            mujoco.mj_step(self.model, self.data)
            
        self.t += self.control_dt
        self.step_count += 1
        
        reward,reward_info = self._reward(tau = tau)
        
        terminated = self._failed()
        truncated = self.step_count >= self.max_steps
        
        self.prev_action = action.copy()
        obs = self._make_obs()
        self.prev_tau = tau.copy()
        
        _,_,phase_now = self.gait.get(self.t)
        
        info = {
            "tau_pd": tau_pd,
            "tau_rl": tau_rl,
            "tau": tau,
            "phase": phase,
            "reward_info": reward_info,
        }
        
        return obs, reward, terminated, truncated, info
    
    def _get_q_dq(self) -> tuple[np.ndarray,np.ndarray]:
        q,dq = self._get_q_dq()
        q_ref,dq_ref,phase = self.gait.get(self.t)
        
        q_err = q_ref - q
        dq_err = dq_ref - dq
        
        phase_angle = 2.0*np.pi*phase
        phase_vec = np.array(
            [np.sin(phase_angle),np.cos(phase_angle)],
            dtype=np.float32,
        )
        
        obs = np.concatenate(
            [
                q,
                dq,
                q_ref,
                dq_ref,
                q_err,
                dq_err,
                phase_vec,
                self.prev_action,
            ]
        )
        
        return obs.astype(np.float32)
    
    def _reward(self,tau:np.ndarray) -> tuple[float,dict[str,float]]:
        q,dq = self._get_q_dq()
        q_ref,dq_ref,_ = self.gait.get(self.t)
        
        q_err = q - q_ref
        dq_err = dq - dq_ref
        
        r_q = np.exp(-5.0*float(np.mean(q_err * q_err)))
        r_dq= np.exp(-0.1*float(np.mean(dq_err * dq_err)))
        
        torque_cost = np.exp(-0.1 * float(np.mean(tau * tau)))
        smooth_cost = np.exp(-0.1 * float(np.mean(dq_err * dq_err)))
        
        alive = 0.5
        
        reward = r_q + 0.2 * r_dq + alive - torque_cost - smooth_cost
        info ={
            "r_q": r_q,
            "r_dq": r_dq,
            "alive": alive,
            "torque_cost": torque_cost,
            "smooth_cost": smooth_cost,
        }
        
        return float(reward), info
    
    def _failed(self) -> bool:
        if not np.isfinite(self.data.qpos).all():
            return True
        if not np.isfinite(self.data.qvel).all():
            return True
        
        q,dq = self._get_q_dq()
        
        if np.any(np.abs(q) > 3.0):
            return True
        if np.any(np.abs(dq) > 30.0):
            return True
        
        return False
    
    def close(self):
        pass
    
    