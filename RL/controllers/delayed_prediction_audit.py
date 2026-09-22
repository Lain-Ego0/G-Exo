"""Causal alignment of a prediction with the state observed h steps later."""

from __future__ import annotations

import numpy as np


class DelayedPredictionAudit:
    """Pair each prediction with the state at its declared future horizon."""

    def __init__(self, horizon_steps: int, state_size: int = 4) -> None:
        self.horizon_steps = int(horizon_steps)
        self.state_size = int(state_size)
        if self.horizon_steps < 1 or self.state_size < 1:
            raise ValueError("horizon_steps and state_size must be positive.")
        self.reset()

    def reset(self) -> None:
        self.step_index = 0
        self._pending: dict[int, tuple[np.ndarray, np.ndarray]] = {}

    def update(
        self,
        *,
        current_q: np.ndarray,
        current_dq: np.ndarray,
        predicted_q: np.ndarray,
        predicted_dq: np.ndarray,
        prediction_valid: bool = True,
    ) -> tuple[np.ndarray, np.ndarray]:
        current_q = self._state(current_q, "current_q")
        current_dq = self._state(current_dq, "current_dq")
        predicted_q = self._state(predicted_q, "predicted_q")
        predicted_dq = self._state(predicted_dq, "predicted_dq")

        pending = self._pending.pop(self.step_index, None)
        if pending is None:
            q_error = np.full(self.state_size, np.nan, dtype=np.float32)
            dq_error = np.full(self.state_size, np.nan, dtype=np.float32)
        else:
            q_error = current_q - pending[0]
            dq_error = current_dq - pending[1]

        target_step = self.step_index + self.horizon_steps
        if prediction_valid:
            self._pending[target_step] = (
                predicted_q.copy(),
                predicted_dq.copy(),
            )
        self.step_index += 1
        return q_error.astype(np.float32), dq_error.astype(np.float32)

    def _state(self, value: np.ndarray, name: str) -> np.ndarray:
        array = np.asarray(value, dtype=np.float32)
        if array.shape != (self.state_size,) or not np.all(np.isfinite(array)):
            raise ValueError(
                f"{name} must be finite with shape ({self.state_size},)."
            )
        return array


__all__ = ["DelayedPredictionAudit"]
