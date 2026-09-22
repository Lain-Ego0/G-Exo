"""Stratified per-episode speed sampling for locomotion curricula."""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


SPEED_SAMPLING_PROTOCOL = "stratified_anchor_expansion_v1"
SPEED_BAND_IDS = {"fixed": -1, "lower": 0, "anchor": 1, "upper": 2}


@dataclass(frozen=True)
class SpeedCurriculumConfig:
    """Define a stable anchor range and the two newly exposed edge bands."""

    minimum_m_s: float
    maximum_m_s: float
    anchor_minimum_m_s: float
    anchor_maximum_m_s: float
    lower_probability: float = 0.25
    anchor_probability: float = 0.50
    upper_probability: float = 0.25

    def __post_init__(self) -> None:
        bounds = np.asarray(
            (
                self.minimum_m_s,
                self.maximum_m_s,
                self.anchor_minimum_m_s,
                self.anchor_maximum_m_s,
            ),
            dtype=np.float64,
        )
        if not np.all(np.isfinite(bounds)):
            raise ValueError("Speed curriculum bounds must be finite.")
        if not (
            0.0 < self.minimum_m_s <= self.anchor_minimum_m_s
            <= self.anchor_maximum_m_s <= self.maximum_m_s
        ):
            raise ValueError(
                "Speed bounds must satisfy 0 < min <= anchor_min <= "
                "anchor_max <= max."
            )
        probabilities = np.asarray(
            (
                self.lower_probability,
                self.anchor_probability,
                self.upper_probability,
            ),
            dtype=np.float64,
        )
        if not np.all(np.isfinite(probabilities)) or np.any(probabilities < 0.0):
            raise ValueError("Speed-band probabilities must be finite and non-negative.")
        if self.anchor_probability <= 0.0:
            raise ValueError("anchor_probability must be positive.")
        if sum(weight for _, _, _, weight in self.active_bands()) <= 0.0:
            raise ValueError("At least one active speed band needs positive probability.")

    def active_bands(self) -> tuple[tuple[str, float, float, float], ...]:
        bands = []
        if self.anchor_minimum_m_s > self.minimum_m_s:
            bands.append(
                (
                    "lower",
                    self.minimum_m_s,
                    self.anchor_minimum_m_s,
                    self.lower_probability,
                )
            )
        bands.append(
            (
                "anchor",
                self.anchor_minimum_m_s,
                self.anchor_maximum_m_s,
                self.anchor_probability,
            )
        )
        if self.maximum_m_s > self.anchor_maximum_m_s:
            bands.append(
                (
                    "upper",
                    self.anchor_maximum_m_s,
                    self.maximum_m_s,
                    self.upper_probability,
                )
            )
        return tuple(band for band in bands if band[3] > 0.0)

    def to_dict(self) -> dict[str, object]:
        return {
            "protocol": SPEED_SAMPLING_PROTOCOL,
            "anchor_range_m_s": [
                float(self.anchor_minimum_m_s),
                float(self.anchor_maximum_m_s),
            ],
            "probabilities": {
                "lower": float(self.lower_probability),
                "anchor": float(self.anchor_probability),
                "upper": float(self.upper_probability),
            },
        }


class StratifiedSpeedSampler:
    """Sample a band first, then sample uniformly inside that band."""

    def __init__(self, config: SpeedCurriculumConfig) -> None:
        self.config = config
        self._bands = config.active_bands()
        weights = np.asarray([band[3] for band in self._bands], dtype=np.float64)
        self._probabilities = weights / np.sum(weights)

    def sample(self, rng: np.random.Generator) -> tuple[float, str, int]:
        index = int(rng.choice(len(self._bands), p=self._probabilities))
        name, lower, upper, _ = self._bands[index]
        speed = lower if lower == upper else float(rng.uniform(lower, upper))
        return speed, name, SPEED_BAND_IDS[name]


__all__ = [
    "SPEED_BAND_IDS",
    "SPEED_SAMPLING_PROTOCOL",
    "SpeedCurriculumConfig",
    "StratifiedSpeedSampler",
]
