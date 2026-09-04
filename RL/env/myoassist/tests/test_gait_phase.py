"""Tests for the causal foot-contact gait phase."""

from __future__ import annotations

import unittest

from RL.env.myoassist.gait_phase import CausalGaitPhase, GaitPhaseConfig


class CausalGaitPhaseTest(unittest.TestCase):
    def test_two_left_contacts_calibrate_period_without_future_frames(self) -> None:
        tracker = CausalGaitPhase(
            GaitPhaseConfig(
                default_period_steps=40,
                minimum_period_steps=20,
                maximum_period_steps=80,
                stable_contact_steps=1,
                stable_release_steps=1,
                period_smoothing=1.0,
            )
        )
        self.assertEqual(tracker.update(1.0), 0.0)
        for _ in range(39):
            tracker.update(0.0)
        self.assertEqual(tracker.update(1.0), 0.0)
        self.assertTrue(tracker.ready)
        self.assertEqual(tracker.period_steps, 40.0)
        for _ in range(10):
            phase = tracker.update(0.0)
        self.assertAlmostEqual(phase, 0.25)

    def test_reset_removes_period_history(self) -> None:
        tracker = CausalGaitPhase()
        tracker.update(1.0)
        tracker.reset()
        self.assertFalse(tracker.ready)
        self.assertEqual(tracker.phase, 0.0)


if __name__ == "__main__":
    unittest.main()
