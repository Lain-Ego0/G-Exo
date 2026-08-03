from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np

from RL.env.kinesis.baseline_reference import (
    BaselineReference,
    baseline_path,
    cycle_duration_cost,
    relative_rate_saving,
)
from RL.env.kinesis.oracle_phase import CausalContactCycleTracker


class SchemeCTest(unittest.TestCase):
    def test_rate_saving_cannot_be_gamed_by_a_shorter_cycle(self) -> None:
        energy_saving = 1.0 - 8.0 / 10.0
        rate_saving = relative_rate_saving(
            actual_total=8.0,
            actual_duration=0.8,
            baseline_total=10.0,
            baseline_duration=1.0,
        )
        self.assertAlmostEqual(energy_saving, 0.2)
        self.assertAlmostEqual(rate_saving, 0.0)

    def test_rate_saving_rewards_a_real_load_rate_reduction(self) -> None:
        self.assertAlmostEqual(
            relative_rate_saving(8.0, 1.0, 10.0, 1.0),
            0.2,
        )
        self.assertAlmostEqual(
            relative_rate_saving(8.0, 0.5, 10.0, 1.0),
            -0.6,
        )

    def test_duration_cost_has_dead_band_and_cap(self) -> None:
        settings = {
            "free_ratio": 0.05,
            "scale_ratio": 0.10,
            "cap": 4.0,
        }
        self.assertAlmostEqual(cycle_duration_cost(1.04, 1.0, **settings), 0.0)
        self.assertAlmostEqual(cycle_duration_cost(0.85, 1.0, **settings), 1.0)
        self.assertAlmostEqual(cycle_duration_cost(0.75, 1.0, **settings), 4.0)

    def test_baseline_returns_only_the_selected_complete_cycle(self) -> None:
        with tempfile.TemporaryDirectory() as temporary_directory:
            directory = Path(temporary_directory)
            path = baseline_path(directory, motion_id=8, seed=0)
            np.savez_compressed(
                path,
                seed=0,
                valid=True,
                time_s=np.arange(6, dtype=np.float64) * 0.02,
                activation_cost=np.asarray([9, 1, 2, 3, 4, 9], dtype=float),
                muscle_effort_torque_cost=np.asarray(
                    [9, 10, 20, 30, 40, 9], dtype=float
                ),
                torque_cost=np.ones(6),
                human_torque=np.zeros((6, 4)),
                tracking_mse=np.ones(6) * 1.0e-4,
                mpjpe_mm=np.ones(6) * 20.0,
                phase=np.asarray([np.nan, 0.0, 0.5, 0.0, 0.5, np.nan]),
                phase_rate_hz=np.asarray([np.nan, 1.0, 1.0, 1.0, 1.0, np.nan]),
                phase_valid=np.asarray([False, True, True, True, True, False]),
                cycle_id=np.asarray([-1, 0, 0, 1, 1, -1]),
                reward_cycle_id=np.asarray([-1, 0, 0, 1, 1, -1]),
                touch=np.zeros((6, 4)),
                sensor_frame=np.zeros((6, 32)),
                control_dt=0.02,
                contact_on_threshold=1.0,
                contact_off_threshold=0.5,
            )

            reference = BaselineReference(directory, motion_id=8)
            self.assertTrue(reference.supports_exact_cycles)
            self.assertIsNone(reference.cycle_at_time(0, 0.0))

            cycle = reference.cycle_at_time(0, 0.04)
            self.assertIsNotNone(cycle)
            assert cycle is not None
            self.assertEqual(cycle.cycle_id, 0)
            self.assertAlmostEqual(cycle.activation_energy, 0.06)
            self.assertAlmostEqual(cycle.torque_impulse, 0.60)
            self.assertAlmostEqual(cycle.duration_s, 0.04)

    def test_contact_tracker_emits_one_event_per_stance(self) -> None:
        tracker = CausalContactCycleTracker(
            on_threshold=1.0,
            off_threshold=0.5,
        )
        force = (0.0, 2.0, 2.0, 2.0, 0.0, 0.0, 2.0, 2.0)
        events = [index for index, value in enumerate(force) if tracker.update(value)]
        self.assertEqual(events, [2, 7])


if __name__ == "__main__":
    unittest.main()
