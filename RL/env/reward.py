from __future__ import annotations

from collections import deque
from typing import Any, Callable

import numpy as np

RewardContext = dict[str, Any]
RewardParameters = dict[str, Any]
RewardFunction = Callable[
    [RewardContext, RewardParameters],
    float,
]

def reward_motion(
    context: RewardContext,
    parameters: RewardParameters,
) -> float:
    q_error = (
        context["q"] - context["q_ref"]
    ) / parameters["q_scale"]
    
    dq_error = (
        context["dq"] - context["dq_ref"]
    ) / parameters["dq_scale"]
    
    position_error = np.mean(
        np.square(q_error)
    )
    
    velocity_error = np.mean(
        np.square(dq_error)
    )
    
    return float(
        np.exp(-position_error - parameters["velocity_weight"] * velocity_error)
    )
    
def reward_human_effort(
    context: RewardContext,
    parameters: RewardParameters,
) -> float:
    normalized_control = (
        context["human_control"]
        / parameters["control_scale"]
    )

    return float(
        np.mean(
            np.square(normalized_control)
        )
    )
    
def reward_exo_power(
    context: RewardContext,
    parameters: RewardParameters,
) -> float:
    mechanical_power = np.abs(
        context["exo_torque"]
        * context["motor_dq"]
    )

    return float(
        np.mean(mechanical_power)
        / parameters["power_scale"]
    )
    
def reward_smoothness(
    context: RewardContext,
    parameters: RewardParameters,
) -> float:
    if not context["smoothness_valid"]:
        return 0.0

    second_difference = (
        context["exo_torque"]
        - 2.0 * context["previous_torque"]
        + context["previous_previous_torque"]
    )
    normalized_difference = (
        second_difference
        / parameters["torque_scale"]
    )

    return float(
        np.mean(
            np.square(normalized_difference)
        )
    )
    
REWARD_REGISTRY: dict[str, RewardFunction] = {
    "motion": reward_motion,
    "human_effort": reward_human_effort,
    "exo_power": reward_exo_power,
    "smoothness": reward_smoothness,
}

class RewardCalculator:
    def __init__(
        self,
        reward_config: dict[str, dict[str, Any]],
    ) -> None:
        self._registered_terms:list[tuple[str,float,RewardFunction,RewardParameters,]] = []
        
        self._torque_history:deque[np.ndarray] = deque(maxlen=2)
        
        self._register_terms(reward_config)
        
    def reset(self) -> None:
        self._torque_history.clear()
        
    def compute(
        self,
        *,
        state:dict[str,Any],
        reference:dict[str,Any],
        human_control:np.ndarray,
        exo_torque:np.ndarray,
    ) -> tuple[float,dict[str,float]]:
        context = self._build_context(
            state=state,
            reference=reference,
            human_control=human_control,
            exo_torque=exo_torque,
        )
        
        total_reward = 0.0
        reward_terms:dict[str,float] = {}
        
        for(
            name,weight,reward_function,parameters,
        ) in self._registered_terms:
            raw_value = float(
                reward_function(
                    context,
                    parameters,
                )
            )
            
            if not np.isfinite(raw_value):
                raise FloatingPointError(
                    f"Reward term '{name}' produced NaN or Inf."
                )
                
            weighted_value = raw_value * weight
            
            reward_terms[name] = raw_value
            reward_terms[f"{name}_weighted"] = (
                weighted_value
            )
            
            total_reward += weighted_value
            
        if not np.isfinite(total_reward):
            raise FloatingPointError(
                "Total reward is NaN or Inf."
            )
            
        self._torque_history.append(
            context["exo_torque"].copy()
        )
        
        reward_terms["total"] = float(total_reward)
        
        return float(total_reward),reward_terms
    
    def _register_terms(
        self,
        reward_config:dict[str,dict[str,Any]],
    ) -> None:
        for name,config in reward_config.items():
            if name not in REWARD_REGISTRY:
                available = ", ".join(
                    sorted(REWARD_REGISTRY)
                )

                raise KeyError(
                    f"Unknown reward term '{name}'. "
                    f"Available terms: {available}"
                )
            
            if "weight" not in config:
                raise KeyError(
                    f"Reward term '{name}' has no weight."
                )

            weight = float(config["weight"])

            if not np.isfinite(weight):
                raise ValueError(
                    f"Weight for '{name}' must be finite."
                )
        
            if weight == 0.0:
                continue

            parameters = {
                key: self._convert_parameter(value)
                for key, value in config.items()
                if key != "weight"
            }
            
            self._registered_terms.append(
                (
                    name,
                    weight,
                    REWARD_REGISTRY[name],
                    parameters,
                )
            )
            
    def _build_context(
        self,
        *,
        state:dict[str,Any],
        reference:dict[str,Any],
        human_control:np.ndarray,
        exo_torque:np.ndarray,
    ) -> RewardContext:
        q = self._read_array(state, key="tracking_q",)
        dq= self._read_array(state, key="tracking_dq",)
        motor_dq = self._read_array(state, key="motor_dq",expected_shape = (4,),)
        q_ref = self._read_array(reference, key="q",)
        dq_ref = self._read_array(reference, key="dq",)
        
        human_control_array = self._to_array(human_control, name="human_control",)
        exo_torque_array = self._to_array(exo_torque, name="exo_torque",expected_shape = (4,),)
        
        if q.shape != q_ref.shape:
            raise ValueError(
                "tracking_q and reference q must have "
                f"the same shape, got {q.shape} and {q_ref.shape}."
            )

        if dq.shape != dq_ref.shape:
            raise ValueError(
                "tracking_dq and reference dq must have "
                f"the same shape, got {dq.shape} and {dq_ref.shape}."
            )

        if q.shape != dq.shape:
            raise ValueError(
                "tracking_q and tracking_dq must have "
                f"the same shape, got {q.shape} and {dq.shape}."
            )
            
        smoothness_valid = (
            len(self._torque_history) == 2
        )

        if smoothness_valid:
            previous_previous_torque = (
                self._torque_history[0]
            )
            previous_torque = (
                self._torque_history[1]
            )
        else:
            previous_previous_torque = (
                exo_torque_array
            )
            previous_torque = (
                exo_torque_array
            )

        return {
            "q": q,
            "dq": dq,
            "q_ref": q_ref,
            "dq_ref": dq_ref,
            "human_control": human_control_array,
            "exo_torque": exo_torque_array,
            "motor_dq": motor_dq,
            "previous_torque": previous_torque,
            "previous_previous_torque": (
                previous_previous_torque
            ),
            "smoothness_valid": smoothness_valid,
        }
                
    @staticmethod
    def _read_array(
        source: dict[str, Any],
        *,
        key: str,
        expected_shape: tuple[int, ...] | None = None,
    ) -> np.ndarray:
        if key not in source:
            raise KeyError(
                f"Missing required field: {key}"
            )
            
        return RewardCalculator._to_array(
            source[key],
            name=key,
            expected_shape=expected_shape,
        )
        
    @staticmethod
    def _to_array(
        value: Any,
        *,
        name: str,
        expected_shape: tuple[int, ...] | None = None,
    ) -> np.ndarray:
        array = np.asarray(
            value,
            dtype=np.float32,
        )

        if array.ndim != 1:
            raise ValueError(
                f"{name} must be one-dimensional, "
                f"got shape {array.shape}."
            )

        if expected_shape is not None:
            if array.shape != expected_shape:
                raise ValueError(
                    f"{name} must have shape {expected_shape}, "
                    f"got {array.shape}."
                )

        if not np.all(np.isfinite(array)):
            raise FloatingPointError(
                f"{name} contains NaN or Inf."
            )

        return array
    
    @staticmethod
    def _convert_parameter(
        value: Any,
    ) -> Any:
        if isinstance(
            value,
            (list, tuple),
        ):
            array = np.asarray(
                value,
                dtype=np.float32,
            )

            if not np.all(np.isfinite(array)):
                raise ValueError(
                    "Reward parameter contains NaN or Inf."
                )

            return array

        if isinstance(
            value,
            (int, float),
        ):
            numeric_value = float(value)

            if not np.isfinite(numeric_value):
                raise ValueError(
                    "Reward parameter must be finite."
                )

            return numeric_value

        return value
    
    
    
    