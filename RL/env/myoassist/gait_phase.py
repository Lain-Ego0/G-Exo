"""Causal gait-phase tracking shared by baseline collection and PPO reward."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


DEFAULT_GAIT_PERIOD_STEPS = 50
FOOT_CONTACT_THRESHOLD = 0.1


@dataclass(frozen=True)
class GaitPhaseConfig:
    default_period_steps: int = DEFAULT_GAIT_PERIOD_STEPS
    minimum_period_steps: int = 20
    maximum_period_steps: int = 100
    stable_contact_steps: int = 3
    stable_release_steps: int = 3
    period_smoothing: float = 0.25


class CausalGaitPhase:
    """Estimate phase from past and current left-foot contact only.

    A stable left-foot contact starts phase zero. The interval between the two
    latest valid contacts updates the gait period; no future frame is used.
    """

    def __init__(self, config: GaitPhaseConfig = GaitPhaseConfig()) -> None:
        self.config = config
        if not (
            0 < config.minimum_period_steps
            <= config.default_period_steps
            <= config.maximum_period_steps
        ):
            raise ValueError("Invalid gait-period bounds.")
        if config.stable_contact_steps < 1 or config.stable_release_steps < 1:
            raise ValueError("Contact debounce lengths must be positive.")
        if not 0.0 < config.period_smoothing <= 1.0:
            raise ValueError("period_smoothing must be in (0, 1].")
        self.reset()

    def reset(self) -> None:
        self._step = -1
        self._anchor_step: int | None = None
        self._period_steps = float(self.config.default_period_steps)
        self._contact_count = 0
        self._release_count = 0
        self._in_contact = False
        self._valid_period_count = 0
        self._phase = 0.0

    def update(self, left_foot_force: float) -> float:
        force = float(left_foot_force)
        if not np.isfinite(force):
            raise ValueError("left_foot_force must be finite.")
        self._step += 1
        strike = self._update_contact(force > FOOT_CONTACT_THRESHOLD)
        if strike:
            self._update_period(self._step)

        if self._anchor_step is None:
            self._phase = 0.0
        else:
            elapsed = self._step - self._anchor_step
            self._phase = float((elapsed / self._period_steps) % 1.0)
        return self._phase

    def _update_contact(self, contact: bool) -> bool:
        if contact:
            self._contact_count += 1
            self._release_count = 0
            if (
                not self._in_contact
                and self._contact_count >= self.config.stable_contact_steps
            ):
                self._in_contact = True
                return True
        else:
            self._release_count += 1
            self._contact_count = 0
            if self._release_count >= self.config.stable_release_steps:
                self._in_contact = False
        return False

    def _update_period(self, strike_step: int) -> None:
        if self._anchor_step is not None:
            measured = strike_step - self._anchor_step
            if self.config.minimum_period_steps <= measured <= self.config.maximum_period_steps:
                alpha = self.config.period_smoothing
                self._period_steps = (
                    (1.0 - alpha) * self._period_steps + alpha * measured
                )
                self._valid_period_count += 1
        self._anchor_step = strike_step

    @property
    def phase(self) -> float:
        return self._phase

    @property
    def period_steps(self) -> float:
        return self._period_steps

    @property
    def ready(self) -> bool:
        return self._valid_period_count > 0


def left_foot_force(environment) -> float:
    """Read the same foot and toe sensors used by MyoAssist."""

    data = environment.sim.data
    return float(data.sensor("l_foot").data[0] + data.sensor("l_toes").data[0])


__all__ = [
    "CausalGaitPhase",
    "DEFAULT_GAIT_PERIOD_STEPS",
    "FOOT_CONTACT_THRESHOLD",
    "GaitPhaseConfig",
    "left_foot_force",
]
