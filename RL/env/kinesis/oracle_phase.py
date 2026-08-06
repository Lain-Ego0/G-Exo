"""Offline gait-phase extraction and phase-aligned cost utilities.

The phase returned here is an oracle because it uses the next initial-contact
event to normalize the current stride.  It is intended for reward audits, not
for Actor observations or online deployment.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


RIGHT_CONTACT_CHANNELS = (0, 1)
LEFT_CONTACT_CHANNELS = (2, 3)
EPSILON = 1.0e-12


@dataclass(frozen=True)
class OraclePhase:
    """One offline stride segmentation result."""

    phase: np.ndarray
    phase_rate_hz: np.ndarray
    cycle_id: np.ndarray
    valid: np.ndarray
    event_indices: np.ndarray
    right_contact: np.ndarray
    left_contact: np.ndarray
    contact_on_threshold: float
    contact_off_threshold: float


@dataclass(frozen=True)
class PhaseCostProfile:
    """Mean zero-assistance cost rate indexed by gait phase."""

    phase_centers: np.ndarray
    cost_rate_mean: np.ndarray
    cost_rate_std: np.ndarray
    energy_density_mean: np.ndarray
    energy_density_std: np.ndarray
    cycle_energy_mean: float
    cycle_energy_std: float
    cycle_ids: np.ndarray

    @property
    def cycle_count(self) -> int:
        return int(self.cycle_ids.size)


class CausalContactCycleTracker:
    """Detect debounced initial-contact events using current and past force only."""

    def __init__(
        self,
        *,
        on_threshold: float,
        off_threshold: float,
        min_on_frames: int = 2,
        min_off_frames: int = 2,
    ) -> None:
        if not 0.0 <= off_threshold < on_threshold:
            raise ValueError("Require 0 <= off_threshold < on_threshold.")
        self.on_threshold = float(on_threshold)
        self.off_threshold = float(off_threshold)
        self.min_on_frames = int(min_on_frames)
        self.min_off_frames = int(min_off_frames)
        self.reset()

    def reset(self) -> None:
        self.contact = False
        self._on_run = 0
        self._off_run = 0

    def update(self, force: float) -> bool:
        """Return True once when a new contact has been causally confirmed."""

        value = float(force)
        if not np.isfinite(value):
            raise FloatingPointError("Contact force is not finite.")
        if not self.contact:
            self._on_run = self._on_run + 1 if value >= self.on_threshold else 0
            if self._on_run >= self.min_on_frames:
                self.contact = True
                self._on_run = 0
                self._off_run = 0
                return True
            return False
        self._off_run = self._off_run + 1 if value <= self.off_threshold else 0
        if self._off_run >= self.min_off_frames:
            self.contact = False
            self._off_run = 0
            self._on_run = 0
        return False


def merge_phase_cost_profiles(
    profiles: list[PhaseCostProfile],
) -> PhaseCostProfile:
    """Pool per-rollout profiles with cycle-count weighting."""

    if not profiles:
        raise ValueError("At least one phase profile is required.")
    reference_centers = profiles[0].phase_centers
    if any(
        profile.phase_centers.shape != reference_centers.shape
        or not np.allclose(profile.phase_centers, reference_centers)
        for profile in profiles[1:]
    ):
        raise ValueError("Phase profiles use different bin grids.")

    counts = np.asarray(
        [profile.cycle_count for profile in profiles], dtype=np.float64
    )
    total = float(np.sum(counts))
    if total <= 0.0:
        raise ValueError("Phase profiles contain no cycles.")

    means = np.stack([profile.cost_rate_mean for profile in profiles])
    variances = np.stack(
        [np.square(profile.cost_rate_std) for profile in profiles]
    )
    pooled_mean = np.sum(means * counts[:, None], axis=0) / total
    pooled_variance = np.sum(
        counts[:, None]
        * (variances + np.square(means - pooled_mean[None, :])),
        axis=0,
    ) / total
    density_means = np.stack(
        [profile.energy_density_mean for profile in profiles]
    )
    density_variances = np.stack(
        [np.square(profile.energy_density_std) for profile in profiles]
    )
    pooled_density_mean = (
        np.sum(density_means * counts[:, None], axis=0) / total
    )
    pooled_density_variance = np.sum(
        counts[:, None]
        * (
            density_variances
            + np.square(density_means - pooled_density_mean[None, :])
        ),
        axis=0,
    ) / total

    energy_means = np.asarray(
        [profile.cycle_energy_mean for profile in profiles]
    )
    energy_variances = np.asarray(
        [profile.cycle_energy_std**2 for profile in profiles]
    )
    pooled_energy_mean = float(np.sum(energy_means * counts) / total)
    pooled_energy_variance = float(
        np.sum(
            counts
            * (
                energy_variances
                + np.square(energy_means - pooled_energy_mean)
            )
        )
        / total
    )
    return PhaseCostProfile(
        phase_centers=reference_centers.copy(),
        cost_rate_mean=pooled_mean,
        cost_rate_std=np.sqrt(np.maximum(pooled_variance, 0.0)),
        energy_density_mean=pooled_density_mean,
        energy_density_std=np.sqrt(
            np.maximum(pooled_density_variance, 0.0)
        ),
        cycle_energy_mean=pooled_energy_mean,
        cycle_energy_std=float(np.sqrt(max(pooled_energy_variance, 0.0))),
        cycle_ids=np.arange(int(total), dtype=np.int64),
    )


def infer_contact_thresholds(touch: np.ndarray) -> tuple[float, float]:
    """Infer conservative hysteresis thresholds from one baseline trace."""

    values = _touch_array(touch)
    side_force = np.concatenate(
        (
            values[:, RIGHT_CONTACT_CHANNELS].sum(axis=1),
            values[:, LEFT_CONTACT_CHANNELS].sum(axis=1),
        )
    )
    positive = side_force[np.isfinite(side_force) & (side_force > 0.0)]
    if positive.size == 0:
        raise ValueError("Touch trace contains no positive contact samples.")

    typical_contact = float(np.percentile(positive, 75.0))
    peak_contact = float(np.max(positive))
    on_threshold = max(
        0.05 * typical_contact,
        1.0e-6 * peak_contact,
        1.0e-9,
    )
    return on_threshold, 0.5 * on_threshold


def hysteresis_contact(
    force: np.ndarray,
    *,
    on_threshold: float,
    off_threshold: float,
    min_on_frames: int = 2,
    min_off_frames: int = 2,
) -> np.ndarray:
    """Convert one force trace to a debounced boolean contact trace."""

    values = np.asarray(force, dtype=np.float64)
    if values.ndim != 1 or not np.all(np.isfinite(values)):
        raise ValueError("Contact force must be a finite one-dimensional array.")
    if not 0.0 <= off_threshold < on_threshold:
        raise ValueError("Require 0 <= off_threshold < on_threshold.")
    if min_on_frames < 1 or min_off_frames < 1:
        raise ValueError("Debounce frame counts must be positive.")

    contact = np.zeros(values.size, dtype=bool)
    state = False
    on_run = 0
    off_run = 0

    for index, value in enumerate(values):
        if not state:
            if value >= on_threshold:
                on_run += 1
            else:
                on_run = 0

            if on_run >= min_on_frames:
                start = index - min_on_frames + 1
                contact[start : index + 1] = True
                state = True
                on_run = 0
                off_run = 0
            continue

        contact[index] = True
        if value <= off_threshold:
            off_run += 1
        else:
            off_run = 0

        if off_run >= min_off_frames:
            start = index - min_off_frames + 1
            contact[start : index + 1] = False
            state = False
            on_run = 0
            off_run = 0

    return contact


def phase_from_contact(
    contact: np.ndarray,
    *,
    dt: float,
    minimum_stride_s: float = 0.5,
    maximum_stride_s: float = 2.0,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Build oracle phase between consecutive valid initial contacts."""

    contact = np.asarray(contact, dtype=bool)
    if contact.ndim != 1:
        raise ValueError("Contact state must be one-dimensional.")
    if dt <= 0.0:
        raise ValueError("dt must be positive.")
    if not 0.0 < minimum_stride_s < maximum_stride_s:
        raise ValueError("Stride limits are invalid.")

    previous = np.concatenate(([False], contact[:-1]))
    events = np.flatnonzero(contact & ~previous)
    # A trace that starts in stance has no observable initial-contact event.
    events = events[events > 0]

    phase = np.full(contact.size, np.nan, dtype=np.float64)
    phase_rate = np.full(contact.size, np.nan, dtype=np.float64)
    cycle_id = np.full(contact.size, -1, dtype=np.int64)
    minimum_steps = int(np.ceil(minimum_stride_s / dt))
    maximum_steps = int(np.floor(maximum_stride_s / dt))
    next_cycle_id = 0

    for start, stop in zip(events[:-1], events[1:]):
        stride_steps = int(stop - start)
        if not minimum_steps <= stride_steps <= maximum_steps:
            continue

        indices = np.arange(start, stop)
        phase[indices] = (indices - start) / stride_steps
        phase_rate[indices] = 1.0 / (stride_steps * dt)
        cycle_id[indices] = next_cycle_id
        next_cycle_id += 1

    valid = cycle_id >= 0
    return phase, phase_rate, cycle_id, events.astype(np.int64)


def extract_oracle_phase(
    touch: np.ndarray,
    *,
    dt: float,
    side: str = "left",
    on_threshold: float | None = None,
    off_threshold: float | None = None,
    min_on_frames: int = 2,
    min_off_frames: int = 2,
    minimum_stride_s: float = 0.5,
    maximum_stride_s: float = 2.0,
) -> OraclePhase:
    """Extract left- or right-stride oracle phase from four touch sensors."""

    values = _touch_array(touch)
    if on_threshold is None or off_threshold is None:
        inferred_on, inferred_off = infer_contact_thresholds(values)
        on_threshold = inferred_on if on_threshold is None else on_threshold
        off_threshold = inferred_off if off_threshold is None else off_threshold

    right_force = values[:, RIGHT_CONTACT_CHANNELS].sum(axis=1)
    left_force = values[:, LEFT_CONTACT_CHANNELS].sum(axis=1)
    contact_options = {
        "right": hysteresis_contact(
            right_force,
            on_threshold=float(on_threshold),
            off_threshold=float(off_threshold),
            min_on_frames=min_on_frames,
            min_off_frames=min_off_frames,
        ),
        "left": hysteresis_contact(
            left_force,
            on_threshold=float(on_threshold),
            off_threshold=float(off_threshold),
            min_on_frames=min_on_frames,
            min_off_frames=min_off_frames,
        ),
    }
    if side not in contact_options:
        raise ValueError("side must be 'left' or 'right'.")

    phase, phase_rate, cycle_id, events = phase_from_contact(
        contact_options[side],
        dt=dt,
        minimum_stride_s=minimum_stride_s,
        maximum_stride_s=maximum_stride_s,
    )
    return OraclePhase(
        phase=phase,
        phase_rate_hz=phase_rate,
        cycle_id=cycle_id,
        valid=cycle_id >= 0,
        event_indices=events,
        right_contact=contact_options["right"],
        left_contact=contact_options["left"],
        contact_on_threshold=float(on_threshold),
        contact_off_threshold=float(off_threshold),
    )


def build_phase_cost_profile(
    phase: OraclePhase,
    cost_rate: np.ndarray,
    *,
    dt: float,
    bins: int = 64,
    minimum_cycle_samples: int = 8,
    cycle_ids: tuple[int, ...] | None = None,
) -> PhaseCostProfile:
    """Average complete-cycle cost rates on a common phase grid."""

    costs = _cost_array(cost_rate, phase.phase.size)
    if dt <= 0.0 or bins < 4 or minimum_cycle_samples < 2:
        raise ValueError("Invalid profile settings.")

    centers = (np.arange(bins, dtype=np.float64) + 0.5) / bins
    profiles = []
    density_profiles = []
    energies = []
    accepted_ids = []

    available_cycle_ids = np.unique(phase.cycle_id[phase.valid])
    selected_cycle_ids = (
        available_cycle_ids
        if cycle_ids is None
        else np.asarray(cycle_ids, dtype=np.int64)
    )
    if not np.all(np.isin(selected_cycle_ids, available_cycle_ids)):
        raise ValueError("A requested cycle is not present in the phase trace.")

    for current_id in selected_cycle_ids:
        selected = phase.cycle_id == current_id
        if int(np.sum(selected)) < minimum_cycle_samples:
            continue
        rate_profile = circular_interpolate(
            phase.phase[selected],
            costs[selected],
            centers,
        )
        profiles.append(rate_profile)
        density_profiles.append(rate_profile * float(np.sum(selected)) * dt)
        energies.append(float(np.sum(costs[selected]) * dt))
        accepted_ids.append(int(current_id))

    if not profiles:
        raise ValueError("No complete gait cycles are available for a profile.")

    profile_array = np.asarray(profiles, dtype=np.float64)
    density_array = np.asarray(density_profiles, dtype=np.float64)
    energy_array = np.asarray(energies, dtype=np.float64)
    return PhaseCostProfile(
        phase_centers=centers,
        cost_rate_mean=profile_array.mean(axis=0),
        cost_rate_std=profile_array.std(axis=0),
        energy_density_mean=density_array.mean(axis=0),
        energy_density_std=density_array.std(axis=0),
        cycle_energy_mean=float(energy_array.mean()),
        cycle_energy_std=float(energy_array.std()),
        cycle_ids=np.asarray(accepted_ids, dtype=np.int64),
    )


def phase_aligned_score(
    profile: PhaseCostProfile,
    phase: OraclePhase,
    cost_rate: np.ndarray,
    *,
    dt: float,
    cycle_id: int,
) -> float:
    """Return dense phase-aligned saving accumulated over one actual cycle."""

    costs = _cost_array(cost_rate, phase.phase.size)
    selected = phase.cycle_id == int(cycle_id)
    if not np.any(selected):
        raise ValueError(f"Cycle {cycle_id} is not present.")

    expected_density = circular_interpolate(
        profile.phase_centers,
        profile.energy_density_mean,
        phase.phase[selected],
    )
    expected_rate = expected_density * phase.phase_rate_hz[selected]
    # Do not rescale the integrated expectation after seeing the full cycle.
    # Such a rescale makes any phase trajectory integrate to the known
    # baseline energy and therefore hides causal phase-estimation errors.
    numerator = float(np.sum(expected_rate - costs[selected]) * dt)
    return numerator / max(profile.cycle_energy_mean, EPSILON)


def cycle_energy(
    phase: OraclePhase,
    cost_rate: np.ndarray,
    *,
    dt: float,
    cycle_id: int,
) -> float:
    """Integrate one raw cost rate over one complete oracle cycle."""

    costs = _cost_array(cost_rate, phase.phase.size)
    selected = phase.cycle_id == int(cycle_id)
    if not np.any(selected):
        raise ValueError(f"Cycle {cycle_id} is not present.")
    return float(np.sum(costs[selected]) * dt)


def circular_interpolate(
    source_phase: np.ndarray,
    values: np.ndarray,
    query_phase: np.ndarray,
) -> np.ndarray:
    """Interpolate periodic values without a discontinuity at phase zero."""

    source = np.mod(np.asarray(source_phase, dtype=np.float64), 1.0)
    data = np.asarray(values, dtype=np.float64)
    query = np.mod(np.asarray(query_phase, dtype=np.float64), 1.0)
    if source.ndim != 1 or data.shape != source.shape:
        raise ValueError("Circular interpolation arrays must be one-dimensional.")
    if source.size < 2 or not np.all(np.isfinite(source + data)):
        raise ValueError("Circular interpolation source is invalid.")

    order = np.argsort(source)
    source = source[order]
    data = data[order]
    unique, unique_indices = np.unique(source, return_index=True)
    data = data[unique_indices]
    if unique.size < 2:
        raise ValueError("Circular interpolation needs two unique phases.")

    extended_phase = np.concatenate(
        ([unique[-1] - 1.0], unique, [unique[0] + 1.0])
    )
    extended_values = np.concatenate(([data[-1]], data, [data[0]]))
    return np.interp(query, extended_phase, extended_values)


def _touch_array(touch: np.ndarray) -> np.ndarray:
    values = np.asarray(touch, dtype=np.float64)
    if values.ndim != 2 or values.shape[1] < 4:
        raise ValueError("Touch trace must have shape [time, at least 4].")
    values = values[:, :4]
    if not np.all(np.isfinite(values)):
        raise ValueError("Touch trace contains NaN or Inf.")
    return values


def _cost_array(cost: np.ndarray, expected_length: int) -> np.ndarray:
    values = np.asarray(cost, dtype=np.float64)
    if values.shape != (expected_length,) or not np.all(np.isfinite(values)):
        raise ValueError("Cost must be a finite vector matching the phase trace.")
    return values
