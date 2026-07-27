from __future__ import annotations

import sys
from typing import Any

import gymnasium
import numpy as np

sys.modules.setdefault("gym",gymnasium,) #兼容模块

import deprl

class DepRLTeacherController:
    def __init__(
        self,
        environment: Any,
    ) -> None:
        self._observation_shape = tuple(
            environment.observation_space.shape
        )
        
        self._action_shape = tuple(
            environment.action_space.shape
        )
        
        self._action_low = np.asarray(
            environment.action_space.low,
            dtype=np.float32,
        )

        self._action_high = np.asarray(
            environment.action_space.high,
            dtype=np.float32,
        )
        
        self._policy = deprl.load_baseline(
            environment
        )
        
        self._last_action = np.zeros(
            self._action_shape,
            dtype=np.float32,
        )
        
    def reset(self) -> None:
        self._policy.reset()
        self._last_action.fill(0.0)
        
    def compute(
        self,
        native_observation: np.ndarray,
    ) -> np.ndarray:
        
        observation = np.asarray(
            native_observation,
            dtype=np.float32,
        )
        
        if observation.shape != self._observation_shape:
            raise ValueError(
                "native observation must have shape "
                f"{self._observation_shape}, "
                f"got {observation.shape}."
            )
            
        if not np.all(np.isfinite(observation)):
            raise FloatingPointError(
                "native observation contains NaN or Inf."
            )
            
        action = np.asarray(
            self._policy(observation),
            dtype=np.float32,
        ).squeeze() 
        
        if action.shape != self._action_shape:
            raise RuntimeError(
                "DEPRL action must have shape "
                f"{self._action_shape}, "
                f"got {action.shape}."
            )

        if not np.all(np.isfinite(action)):
            raise FloatingPointError(
                "DEPRL action contains NaN or Inf."
            )
            
        self._last_action = np.clip(
            action,
            self._action_low,
            self._action_high,
        ).astype(np.float32,copy=False,)
        
        return self._last_action.copy() 
    
    @property #只读属性
    def last_action(self) -> np.ndarray:
        return self._last_action.copy()
        
        