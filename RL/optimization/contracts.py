"""Pure-array contracts shared by musculoskeletal backends."""

from __future__ import annotations

from dataclasses import dataclass, field
from numbers import Real
from types import MappingProxyType
from typing import Any, Mapping

import numpy as np


MUSCLE_SNAPSHOT_SCHEMA = "gexo_muscle_snapshot_v1"
TARGET_JOINT_COUNT = 4


@dataclass(frozen=True)
class MuscleSnapshot:
    """One backend-neutral muscle state at a fixed instant.

    A backend may provide measured ``muscle_force_n`` or an affine force model
    ``passive_force_n + active_force_gain_n * activation``.  The latter is
    required by the future fixed-trajectory optimizer; either representation
    is sufficient for the current metrics layer.
    """

    time_s: float
    activation: np.ndarray
    activation_lower: np.ndarray
    activation_upper: np.ndarray
    moment_arm_m: np.ndarray
    target_mask: np.ndarray
    model_hash: str
    valid: bool = True
    validity_reason: str = ""
    muscle_force_n: np.ndarray | None = None
    active_force_gain_n: np.ndarray | None = None
    passive_force_n: np.ndarray | None = None
    metadata: Mapping[str, Any] = field(default_factory=dict)
    schema_version: str = MUSCLE_SNAPSHOT_SCHEMA

    def __post_init__(self) -> None:
        if isinstance(self.time_s, (bool, np.bool_)) or not isinstance(
            self.time_s,
            Real,
        ):
            raise TypeError("time_s must be a real scalar.")
        time_s = float(self.time_s)
        if not np.isfinite(time_s):
            raise ValueError("time_s must be finite.")
        activation = _vector(self.activation, "activation")
        muscle_count = activation.size
        lower = _vector(
            self.activation_lower,
            "activation_lower",
            muscle_count,
        )
        upper = _vector(
            self.activation_upper,
            "activation_upper",
            muscle_count,
        )
        if np.any(lower < 0.0) or np.any(upper > 1.0):
            raise ValueError("Activation bounds must lie in [0, 1].")
        if np.any(lower > upper):
            raise ValueError("activation_lower must not exceed activation_upper.")
        if np.any(activation < lower) or np.any(activation > upper):
            raise ValueError("activation lies outside its declared bounds.")

        moment_arm = np.asarray(self.moment_arm_m, dtype=np.float64)
        if moment_arm.shape != (muscle_count, TARGET_JOINT_COUNT):
            raise ValueError(
                "moment_arm_m must have shape "
                f"({muscle_count}, {TARGET_JOINT_COUNT}), got "
                f"{moment_arm.shape}."
            )
        if not np.all(np.isfinite(moment_arm)):
            raise ValueError("moment_arm_m contains NaN or Inf.")

        target_mask = np.asarray(self.target_mask, dtype=bool)
        if target_mask.shape != (muscle_count,):
            raise ValueError(
                f"target_mask must have shape ({muscle_count},), got "
                f"{target_mask.shape}."
            )
        if not np.any(target_mask):
            raise ValueError("target_mask selects no muscles.")

        force = _optional_vector(
            self.muscle_force_n,
            "muscle_force_n",
            muscle_count,
        )
        gain = _optional_vector(
            self.active_force_gain_n,
            "active_force_gain_n",
            muscle_count,
        )
        passive = _optional_vector(
            self.passive_force_n,
            "passive_force_n",
            muscle_count,
        )
        if (gain is None) != (passive is None):
            raise ValueError(
                "active_force_gain_n and passive_force_n must be provided "
                "together."
            )
        if force is None and gain is None:
            raise ValueError(
                "Provide muscle_force_n or active_force_gain_n with "
                "passive_force_n."
            )
        if force is not None and np.any(force < 0.0):
            raise ValueError("muscle_force_n must be non-negative.")
        if gain is not None and np.any(gain < 0.0):
            raise ValueError("active_force_gain_n must be non-negative.")
        if passive is not None and np.any(passive < 0.0):
            raise ValueError("passive_force_n must be non-negative.")
        if not isinstance(self.model_hash, str) or not self.model_hash.strip():
            raise ValueError("model_hash must be a non-empty string.")
        if self.schema_version != MUSCLE_SNAPSHOT_SCHEMA:
            raise ValueError(
                f"Unsupported MuscleSnapshot schema: {self.schema_version}."
            )
        if not isinstance(self.valid, (bool, np.bool_)):
            raise TypeError("valid must be a boolean.")
        if not isinstance(self.validity_reason, str):
            raise TypeError("validity_reason must be a string.")
        valid = bool(self.valid)
        reason = self.validity_reason.strip()
        if valid and reason:
            raise ValueError("A valid snapshot cannot have a validity_reason.")
        if not valid and not reason:
            raise ValueError("An invalid snapshot needs a validity_reason.")

        object.__setattr__(self, "time_s", time_s)
        object.__setattr__(self, "valid", valid)
        object.__setattr__(self, "validity_reason", reason)
        object.__setattr__(self, "activation", _readonly(activation))
        object.__setattr__(self, "activation_lower", _readonly(lower))
        object.__setattr__(self, "activation_upper", _readonly(upper))
        object.__setattr__(self, "moment_arm_m", _readonly(moment_arm))
        object.__setattr__(self, "target_mask", _readonly(target_mask))
        object.__setattr__(self, "muscle_force_n", _readonly_optional(force))
        object.__setattr__(
            self,
            "active_force_gain_n",
            _readonly_optional(gain),
        )
        object.__setattr__(
            self,
            "passive_force_n",
            _readonly_optional(passive),
        )
        object.__setattr__(
            self,
            "metadata",
            MappingProxyType(dict(self.metadata)),
        )

    @property
    def muscle_count(self) -> int:
        return int(self.activation.size)

    def resolved_muscle_force_n(
        self,
        activation: np.ndarray | None = None,
    ) -> np.ndarray:
        """Return measured force or evaluate the declared affine force model."""

        if activation is None and self.muscle_force_n is not None:
            return self.muscle_force_n.copy()
        if self.active_force_gain_n is None or self.passive_force_n is None:
            raise RuntimeError(
                "This snapshot has measured force but no affine force model."
            )
        value = (
            self.activation
            if activation is None
            else _vector(activation, "activation", self.muscle_count)
        )
        if np.any(value < self.activation_lower) or np.any(
            value > self.activation_upper
        ):
            raise ValueError("activation lies outside the snapshot bounds.")
        return (
            self.passive_force_n + self.active_force_gain_n * value
        ).astype(np.float64)


def _vector(value: np.ndarray, name: str, size: int | None = None) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.ndim != 1 or (size is not None and array.size != size):
        expected = "[muscle]" if size is None else f"({size},)"
        raise ValueError(f"{name} must have shape {expected}, got {array.shape}.")
    if array.size < 1 or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite and non-empty.")
    return array.copy()


def _optional_vector(
    value: np.ndarray | None,
    name: str,
    size: int,
) -> np.ndarray | None:
    return None if value is None else _vector(value, name, size)


def _readonly(value: np.ndarray) -> np.ndarray:
    result = value.copy()
    result.flags.writeable = False
    return result


def _readonly_optional(value: np.ndarray | None) -> np.ndarray | None:
    return None if value is None else _readonly(value)


__all__ = [
    "MUSCLE_SNAPSHOT_SCHEMA",
    "MuscleSnapshot",
    "TARGET_JOINT_COUNT",
]
