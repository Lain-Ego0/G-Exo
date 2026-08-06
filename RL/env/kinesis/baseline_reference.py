"""Load time-aligned zero-assistance Kinesis reference statistics."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np


RL_ROOT = Path(__file__).resolve().parents[2]
DEFAULT_BASELINE_DIR = RL_ROOT / "outputs/kinesis_baseline_v4"
DEFAULT_PHYSICAL_BASELINE_DIR = (
    RL_ROOT / "outputs/kinesis_physical_baseline_v2"
)
DEFAULT_CYCLE_BASELINE_DIR = RL_ROOT / "outputs/kinesis_cycle_baseline_c"


def baseline_path(directory: Path, motion_id: int, seed: int) -> Path:
    """Return the stable on-disk name for one paired baseline rollout."""

    return directory / f"motion_{motion_id:03d}_seed_{seed:06d}.npz"


def relative_rate_saving(
    actual_total: float,
    actual_duration: float,
    baseline_total: float,
    baseline_duration: float,
) -> float:
    """Compare cycle-integrated load after normalizing both cycle durations."""

    if actual_total < 0.0 or baseline_total <= 0.0:
        raise ValueError("Cycle loads must be non-negative with a positive baseline.")
    if actual_duration <= 0.0 or baseline_duration <= 0.0:
        raise ValueError("Cycle durations must be positive.")
    actual_rate = actual_total / actual_duration
    baseline_rate = baseline_total / baseline_duration
    return float(np.clip(1.0 - actual_rate / baseline_rate, -1.0, 1.0))


def cycle_duration_cost(
    actual_duration: float,
    baseline_duration: float,
    *,
    free_ratio: float,
    scale_ratio: float,
    cap: float,
) -> float:
    """Penalize cadence drift only after a configurable relative dead band."""

    if actual_duration <= 0.0 or baseline_duration <= 0.0:
        raise ValueError("Cycle durations must be positive.")
    if free_ratio < 0.0 or scale_ratio <= 0.0 or cap <= 0.0:
        raise ValueError("Duration-cost settings are invalid.")
    ratio = actual_duration / baseline_duration
    excess = max(abs(ratio - 1.0) - free_ratio, 0.0)
    return float(min((excess / scale_ratio) ** 2, cap))


def motion_time(environment, simulation_time: float) -> np.ndarray:
    """Map continuous MuJoCo time to the loaded Kinesis motion timeline."""

    start = np.asarray(
        environment._motion_start_times,
        dtype=np.float64,
    )
    offset = np.asarray(
        environment._motion_start_times_offset,
        dtype=np.float64,
    )
    return start + offset + float(simulation_time)


def tracking_metrics(
    environment,
    simulation_time: float,
) -> tuple[float, float]:
    """Return body-position MSE and MPJPE at continuous simulation time."""

    reference = environment.get_state_from_motionlib_cache(
        environment._sampled_motion_ids,
        motion_time(environment, simulation_time),
        environment.global_offset,
    )
    current = environment.get_body_xpos()[None, ...]
    current = current[..., environment.tracked_bodies_id, :]
    target = reference.xpos[..., environment.smpl_tracked_ids, :]
    error = current - target

    mse = float(np.mean(np.square(error)))
    mpjpe = float(np.mean(np.linalg.norm(error, axis=-1)))
    return mse, mpjpe


@dataclass(frozen=True)
class BaselineSample:
    """Time-aligned target-muscle costs consumed by the reward."""

    activation_cost: float
    torque_cost: float
    muscle_effort_torque_cost: float
    human_torque: np.ndarray
    tracking_mse: float
    mpjpe_mm: float


@dataclass(frozen=True)
class BaselineCycle:
    """One exact zero-assist reference cycle selected by simulation time."""

    cycle_id: int
    activation_energy: float
    torque_impulse: float
    duration_s: float


class BaselineReference:
    """Keep successful zero-assistance rollouts for one motion in memory."""

    def __init__(self, directory: str | Path, motion_id: int) -> None:
        self.directory = Path(directory)
        self.motion_id = int(motion_id)
        self._rollouts: dict[int, dict[str, np.ndarray]] = {}

        pattern = f"motion_{self.motion_id:03d}_seed_*.npz"
        for path in sorted(self.directory.glob(pattern)):
            with np.load(path, allow_pickle=False) as data:
                required = {
                    "seed",
                    "valid",
                    "time_s",
                    "activation_cost",
                    "muscle_effort_torque_cost",
                    "torque_cost",
                    "human_torque",
                    "tracking_mse",
                    "mpjpe_mm",
                }
                missing = required.difference(data.files)
                if missing:
                    raise ValueError(
                        f"Baseline {path} uses the old metric schema; "
                        f"missing {sorted(missing)}. Regenerate physical "
                        "baselines with collect_kinesis_baseline."
                    )
                seed = int(np.asarray(data["seed"]).item())
                valid = bool(np.asarray(data["valid"]).item())
                if not valid:
                    continue

                rollout = {
                    "time_s": np.asarray(data["time_s"], dtype=np.float64),
                    "activation_cost": np.asarray(
                        data["activation_cost"], dtype=np.float64
                    ),
                    "torque_cost":np.asarray(
                        data["torque_cost"],
                        dtype = np.float64,
                    ),
                    "muscle_effort_torque_cost": np.asarray(
                        data["muscle_effort_torque_cost"],
                        dtype=np.float64,
                    ),
                    "human_torque":np.asarray(
                        data["human_torque"],
                        dtype = np.float64,
                    ),
                    "tracking_mse": np.asarray(
                        data["tracking_mse"], dtype=np.float64
                    ),
                    "mpjpe_mm": np.asarray(
                        data["mpjpe_mm"], dtype=np.float64
                    ),
                }
                optional = (
                    "phase",
                    "phase_rate_hz",
                    "cycle_id",
                    "reward_cycle_id",
                    "phase_valid",
                    "touch",
                    "sensor_frame",
                )
                for name in optional:
                    if name in data:
                        rollout[name] = np.asarray(data[name]).copy()
                for name in ("control_dt", "contact_on_threshold", "contact_off_threshold"):
                    if name in data:
                        rollout[name] = float(np.asarray(data[name]).item())
            self._validate_rollout(path, rollout)
            self._rollouts[seed] = rollout

        if not self._rollouts:
            raise FileNotFoundError(
                f"No successful baseline files for motion {self.motion_id} "
                f"in {self.directory}. Run collect_kinesis_baseline first."
            )

    @property
    def seeds(self) -> tuple[int, ...]:
        return tuple(sorted(self._rollouts))

    def resolve_seed(self, requested_seed: int, *, strict: bool = False) -> int:
        """Resolve a seed, optionally forbidding evaluation-time fallback."""

        requested_seed = int(requested_seed)
        if requested_seed in self._rollouts:
            return requested_seed
        if strict:
            raise KeyError(
                f"Missing baseline seed {requested_seed} for motion "
                f"{self.motion_id}; available seeds: {self.seeds}."
            )
        return self.seeds[requested_seed % len(self.seeds)]

    def sample(self, seed: int, simulation_time: float) -> BaselineSample:
        """Linearly interpolate a cached rollout at the current 50 Hz time."""

        rollout = self._rollouts[int(seed)]
        time_s = rollout["time_s"]
        query_time = float(np.clip(simulation_time, time_s[0], time_s[-1]))

        def interpolate_scalar(name: str) -> float:
            return float(
                np.interp(query_time, time_s, rollout[name])
            )
            
        def interpolate_vector(name: str) -> np.ndarray:
            values = rollout[name]
            
            return np.asarray(
                [
                    np.interp(
                        query_time,
                        time_s,
                        values[:,index],
                    )
                    for index in range(values.shape[1])
                ],
                dtype=np.float64,
            )

        return BaselineSample(
            activation_cost=interpolate_scalar("activation_cost"),
            torque_cost = interpolate_scalar("torque_cost"),
            muscle_effort_torque_cost=interpolate_scalar(
                "muscle_effort_torque_cost"
            ),
            human_torque=interpolate_vector("human_torque"),
            tracking_mse=interpolate_scalar("tracking_mse"),
            mpjpe_mm=interpolate_scalar("mpjpe_mm"),
        )

    @property
    def supports_exact_cycles(self) -> bool:
        return all(
            all(
                name in rollout
                for name in (
                    "phase",
                    "cycle_id",
                    "reward_cycle_id",
                    "phase_valid",
                    "touch",
                    "control_dt",
                    "contact_on_threshold",
                    "contact_off_threshold",
                )
            )
            for rollout in self._rollouts.values()
        )

    def contact_thresholds(self, seed: int) -> tuple[float, float]:
        rollout = self._rollouts[int(seed)]
        if not self.supports_exact_cycles:
            raise RuntimeError("Baseline directory has no exact-cycle data.")
        return (
            float(rollout["contact_on_threshold"]),
            float(rollout["contact_off_threshold"]),
        )

    def cycle_at_time(self, seed: int, simulation_time: float) -> BaselineCycle | None:
        """Return the exact reference cycle containing the queried time."""

        rollout = self._rollouts[int(seed)]
        if not self.supports_exact_cycles:
            raise RuntimeError("Baseline directory has no exact-cycle data.")
        time_s = rollout["time_s"]
        index = int(np.argmin(np.abs(time_s - float(simulation_time))))
        cycle_id = int(rollout["reward_cycle_id"][index])
        if cycle_id < 0:
            return None
        selected = np.asarray(rollout["reward_cycle_id"] == cycle_id)
        dt = float(rollout["control_dt"])
        return BaselineCycle(
            cycle_id=cycle_id,
            activation_energy=float(
                np.sum(rollout["activation_cost"][selected]) * dt
            ),
            torque_impulse=float(
                np.sum(rollout["muscle_effort_torque_cost"][selected]) * dt
            ),
            duration_s=float(np.sum(selected) * dt),
        )

    @staticmethod
    def _validate_rollout(
        path: Path,
        rollout: dict[str, np.ndarray],
    ) -> None:
        length = len(rollout["time_s"])
        if length < 2:
            raise ValueError(f"Baseline is too short: {path}")
        arrays = [
            values
            for values in rollout.values()
            if isinstance(values, np.ndarray) and values.ndim >= 1
        ]
        if any(len(values) != length for values in arrays):
            raise ValueError(f"Baseline columns have different lengths: {path}")
        if rollout["human_torque"].shape != (length, 4):
            raise ValueError(
                "Baseline human_torque must have shape "
                f"({length}, 4): {path}"
            )
        numeric_values = [
            values
            for name, values in rollout.items()
            if name not in ("phase", "phase_rate_hz")
            if np.isscalar(values)
            or (isinstance(values, np.ndarray) and values.dtype.kind not in "USO")
        ]
        if not all(np.all(np.isfinite(values)) for values in numeric_values):
            raise ValueError(f"Baseline contains NaN or Inf: {path}")
        if np.any(np.diff(rollout["time_s"]) <= 0.0):
            raise ValueError(f"Baseline time is not strictly increasing: {path}")
