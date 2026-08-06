from __future__ import annotations

from collections import deque
from typing import Any

import gymnasium as gym
import numpy as np
from gymnasium import spaces

class GExoEnv(gym.Env[np.ndarray,np.ndarray]):
    metadata = {"render_modes":[]}
    
    def __init__(
    self,
    backend:Any,
    reference:Any,
    human_controller:Any,
    actuator:Any,
    sensors:Any,
    reward:Any,
    termination:Any,
    *,
    control_dt:float = 0.02,
    history_length:int = 4,
    frame_dim:int = 36,
    max_episode_steps:int = 1000 
    ) -> None:
        super().__init__()
        
        if control_dt <= 0.0:
            raise ValueError("control_dt must be positive.")

        if history_length < 1:
            raise ValueError("history_length must be at least 1.")

        if frame_dim < 1:
            raise ValueError("frame_dim must be positive.")

        if max_episode_steps < 1:
            raise ValueError("max_episode_steps must be positive.")
                
        self.backend = backend
        self.reference = reference
        self.human_controller = human_controller
        self.actuator = actuator
        self.sensors = sensors
        self.reward_calculator = reward
        self.termination = termination
        
        self.control_dt = float(control_dt)
        self.history_length = int(history_length)
        self.frame_dim = int(frame_dim)
        self.max_episode_steps = int(max_episode_steps)
        
        self.action_space = spaces.Box(
            low = -1.0,
            high = 1.0,
            shape = (4,),
            dtype = np.float32
        )
        
        self.observation_space = spaces.Box(
            low = -np.inf,
            high = np.inf,
            shape = (self.history_length * self.frame_dim,),
            dtype = np.float32
        )
        
        self._history: deque[np.ndarray] = deque(
            maxlen = self.history_length
        ) #### 固定长度先进先出缓存；满后自动丢弃最旧帧
        self._last_action = np.zeros(4,dtype = np.float32)
        self._state:dict[str,Any] | None = None
        self._episode_steps = 0
        
    def reset(
        self,
        *,
        seed:int | None = None,
        options:dict[str,Any] | None = None,
    ) -> tuple[np.ndarray,dict[str,Any]]:
        super().reset(seed = seed)
        
        self.human_controller.reset()
        self.actuator.reset()
        self.sensors.reset(seed = seed)
        self.reward_calculator.reset()
        self.termination.reset()
        
        self._state = self.backend.reset(seed = seed)
        self._last_action.fill(0.0)
        self._episode_steps = 0
        
        frame = self._read_frame(self._state)
        
        self._history.clear()
        
        for _ in range(self.history_length):
            self._history.append(frame.copy())
            
        observation = self._build_observation()
        
        info = {
            "time_s": float(self._state["time"]),
            "episode_steps": self._episode_steps,
            "reset_options": options or {},
        }
        
        return observation, info
    
    def step(
        self,
        action:np.ndarray,
    ) -> tuple[np.ndarray,float,bool,bool,dict[str,Any]]:
        if self._state is None:
            raise RuntimeError("Call reset() before step().")
        
        normalized_action = self._validate_action(action)
        exo_torque = self.actuator.process(normalized_action)
        
        current_time = float(self._state["time"])
        reference = self.reference.sample(current_time)
        human_control = self.human_controller.compute(
            self._state,
            reference,
        )
        
        self._state = self.backend.step(
            human_control = human_control,
            exo_torque = exo_torque,
            control_dt = self.control_dt,
        )
        
        self._episode_steps += 1
        self._last_action = normalized_action.copy()
        
        next_reference = self.reference.sample(
            float(self._state["time"]),    
        )
        
        frame = self._read_frame(self._state)
        self._history.append(frame)
        
        reward , reward_terms = self.reward_calculator.compute(
            state = self._state,
            reference = next_reference,
            human_control = human_control,
            exo_torque = exo_torque,
        )
        
        terminated,termination_reason = self.termination.check(
            self._state,
        )
        
        truncated = self._episode_steps >= self.max_episode_steps
        if truncated and not terminated:
            termination_reason = "time_limit"
            
        observation = self._build_observation()
        
        info = {
            "time_s": float(self._state["time"]),
            "episode_steps": self._episode_steps,
            "reward_terms": reward_terms,
            "human_torque": np.asarray(human_control, dtype=np.float32),
            "exo_torque": np.asarray(exo_torque, dtype=np.float32),
            "termination_reason": termination_reason,
        }
        
        return observation, float(reward), terminated, truncated, info
    
    def _read_frame(self, state:dict[str,Any]) -> np.ndarray:
        frame = np.asarray(
            self.sensors.read(
                state = state,
                previous_action = self._last_action,
            ),
            dtype = np.float32,
        )        
        
        
        if frame.shape != (self.frame_dim,):
            raise ValueError(
                f"Sensor frame must have shape ({self.frame_dim},), "
                f"got {frame.shape}."
            )
            
        if not np.all(np.isfinite(frame)):
            raise FloatingPointError("Sensor frame contains NaN or Inf.")
        
        return frame
    
    def _build_observation(self) -> np.ndarray:
        if len(self._history) != self.history_length:
            raise RuntimeError("Observation history is incomplete.")
        
        observation = np.concatenate(
            tuple(self._history),
            axis = 0,
        ).astype(np.float32,copy = False)
        
        if observation.shape != self.observation_space.shape:
            raise RuntimeError(
                "Observation shape does not match observation_space."
            )

        return observation
    
    def _validate_action(self,action:np.ndarray) -> np.ndarray:
        action_array = np.asarray(action,dtype=np.float32)
        
        if action_array.shape != (4,):
            raise ValueError(
                f"Action must have shape (4,), got {action_array.shape}."
            )

        if not np.all(np.isfinite(action_array)):
            raise FloatingPointError("Action contains NaN or Inf.")

        return np.clip(action_array, -1.0, 1.0)
    
    def close(self) -> None:
        if hasattr(self.backend,"close"):
            self.backend.close()
            
    