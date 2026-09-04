from __future__ import annotations

import unittest

import numpy as np

from RL.metrics.trajectory import constrained_dtw_rmse


class TrajectoryMetricsTest(unittest.TestCase):
    def test_identical_trajectories_have_zero_error(self) -> None:
        trajectory = np.arange(24, dtype=np.float64).reshape(6, 4)
        self.assertEqual(constrained_dtw_rmse(trajectory, trajectory), 0.0)

    def test_bounded_time_stretch_is_smaller_than_direct_error(self) -> None:
        phase = np.linspace(0.0, 4.0 * np.pi, 120)
        reference = np.column_stack((np.sin(phase), np.cos(phase)))
        delayed = np.column_stack(
            (np.sin(phase * 0.9), np.cos(phase * 0.9))
        )
        direct = float(np.sqrt(np.mean(np.square(reference - delayed))))
        self.assertLess(constrained_dtw_rmse(reference, delayed), direct)

    def test_rejects_feature_mismatch(self) -> None:
        with self.assertRaisesRegex(ValueError, "dimensions"):
            constrained_dtw_rmse(np.zeros((4, 2)), np.zeros((4, 3)))


if __name__ == "__main__":
    unittest.main()
