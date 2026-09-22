"""Trajectory-comparison metrics shared by simulation backends."""

from __future__ import annotations

import numpy as np


def constrained_dtw_rmse(
    reference: np.ndarray,
    candidate: np.ndarray,
    *,
    window_ratio: float = 0.25,
) -> float:
    """Compare motion shape while allowing bounded gait-phase drift."""

    reference = np.asarray(reference, dtype=np.float64)
    candidate = np.asarray(candidate, dtype=np.float64)
    if reference.ndim != 2 or candidate.ndim != 2:
        raise ValueError("Trajectories must have shape [time, features].")
    if reference.shape[1] != candidate.shape[1]:
        raise ValueError("Trajectory feature dimensions must match.")
    if not reference.size or not candidate.size:
        raise ValueError("Trajectories cannot be empty.")
    if not np.all(np.isfinite(reference)) or not np.all(np.isfinite(candidate)):
        raise ValueError("Trajectories must be finite.")
    if not 0.0 <= window_ratio <= 1.0:
        raise ValueError("window_ratio must lie in [0, 1].")

    rows, columns = len(reference), len(candidate)
    window = max(abs(rows - columns), int(np.ceil(max(rows, columns) * window_ratio)))
    cost = np.full((rows + 1, columns + 1), np.inf, dtype=np.float64)
    path_length = np.zeros((rows + 1, columns + 1), dtype=np.int32)
    cost[0, 0] = 0.0

    for row in range(1, rows + 1):
        start = max(1, row - window)
        stop = min(columns, row + window) + 1
        for column in range(start, stop):
            predecessors = (
                cost[row - 1, column],
                cost[row, column - 1],
                cost[row - 1, column - 1],
            )
            selected = int(np.argmin(predecessors))
            previous_indices = (
                (row - 1, column),
                (row, column - 1),
                (row - 1, column - 1),
            )
            previous = previous_indices[selected]
            point_mse = float(
                np.mean(np.square(reference[row - 1] - candidate[column - 1]))
            )
            cost[row, column] = predecessors[selected] + point_mse
            path_length[row, column] = path_length[previous] + 1

    if not np.isfinite(cost[rows, columns]) or path_length[rows, columns] == 0:
        raise ValueError("No DTW path exists inside the requested window.")
    return float(np.sqrt(cost[rows, columns] / path_length[rows, columns]))


__all__ = ["constrained_dtw_rmse"]
