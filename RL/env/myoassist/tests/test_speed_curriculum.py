"""Tests for stratified speed sampling."""

import unittest

import numpy as np

from RL.env.myoassist.speed_curriculum import (
    SpeedCurriculumConfig,
    StratifiedSpeedSampler,
)


class SpeedCurriculumTest(unittest.TestCase):
    def test_anchor_only_stage_samples_inside_anchor(self) -> None:
        sampler = StratifiedSpeedSampler(
            SpeedCurriculumConfig(0.9, 1.1, 0.9, 1.1)
        )
        samples = [sampler.sample(np.random.default_rng(seed)) for seed in range(50)]
        self.assertTrue(all(0.9 <= value <= 1.1 for value, _, _ in samples))
        self.assertEqual({name for _, name, _ in samples}, {"anchor"})

    def test_expansion_keeps_half_of_episodes_in_anchor(self) -> None:
        sampler = StratifiedSpeedSampler(
            SpeedCurriculumConfig(0.8, 1.2, 0.9, 1.1)
        )
        rng = np.random.default_rng(7)
        samples = [sampler.sample(rng) for _ in range(20_000)]
        counts = {
            name: sum(sample_name == name for _, sample_name, _ in samples)
            for name in ("lower", "anchor", "upper")
        }
        self.assertAlmostEqual(counts["anchor"] / len(samples), 0.50, delta=0.02)
        self.assertAlmostEqual(counts["lower"] / len(samples), 0.25, delta=0.02)
        self.assertAlmostEqual(counts["upper"] / len(samples), 0.25, delta=0.02)

    def test_invalid_anchor_range_is_rejected(self) -> None:
        with self.assertRaises(ValueError):
            SpeedCurriculumConfig(0.8, 1.2, 0.7, 1.1)


if __name__ == "__main__":
    unittest.main()
