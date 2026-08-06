from __future__ import annotations

import unittest

import numpy as np
import torch

from RL.env.kinesis.causal_phase import (
    CausalPhaseTCN,
    circular_phase_error,
    predict_phase,
)
from RL.env.kinesis.oracle_phase import PhaseCostProfile
from RL.runners.analyze_oracle_phase_reward import (
    leave_one_seed_context_profiles,
)


class CausalPhaseTest(unittest.TestCase):
    def test_circular_error_wraps_at_cycle_boundary(self) -> None:
        error = circular_phase_error(
            np.asarray([0.99, 0.01]),
            np.asarray([0.01, 0.99]),
        )
        np.testing.assert_allclose(error, [0.02, 0.02], atol=1.0e-12)

    def test_model_uses_only_provided_history(self) -> None:
        torch.manual_seed(0)
        model = CausalPhaseTCN(dropout=0.0).eval()
        prefix = torch.randn(1, 32, 32)
        changed_future = torch.randn(1, 32, 10)
        with torch.inference_mode():
            first_phase, first_rate = model(prefix)
            extended_phase, extended_rate = model(
                torch.cat((prefix, changed_future), dim=2)[:, :, :32]
            )
        self.assertTrue(torch.equal(first_phase, extended_phase))
        self.assertTrue(torch.equal(first_rate, extended_rate))

    def test_predict_phase_preserves_history_warmup(self) -> None:
        model = CausalPhaseTCN(hidden_dim=8, dropout=0.0).eval()
        statistics = {
            "history": 8,
            "input_mean": np.zeros(32, dtype=np.float32),
            "input_std": np.ones(32, dtype=np.float32),
        }
        prediction = predict_phase(
            model,
            statistics,
            np.zeros((20, 32), dtype=np.float32),
        )
        self.assertFalse(prediction.valid[:7].any())
        self.assertTrue(prediction.valid[7:].all())
        self.assertTrue(np.all(prediction.phase_rate_hz[7:] > 0.0))

    def test_context_profile_excludes_query_seed(self) -> None:
        def profile(energy: float) -> PhaseCostProfile:
            values = np.full(4, energy, dtype=np.float64)
            return PhaseCostProfile(
                phase_centers=np.asarray([0.125, 0.375, 0.625, 0.875]),
                cost_rate_mean=values,
                cost_rate_std=np.zeros(4),
                energy_density_mean=values,
                energy_density_std=np.zeros(4),
                cycle_energy_mean=energy,
                cycle_energy_std=0.0,
                cycle_ids=np.asarray([0]),
            )

        exact = {
            (8, 0, 1): profile(1.0),
            (8, 1, 1): profile(2.0),
            (8, 2, 1): profile(4.0),
        }
        contexts = leave_one_seed_context_profiles(exact)
        self.assertAlmostEqual(contexts[(8, 0, 1)].cycle_energy_mean, 3.0)
        self.assertAlmostEqual(contexts[(8, 1, 1)].cycle_energy_mean, 2.5)
        self.assertAlmostEqual(contexts[(8, 2, 1)].cycle_energy_mean, 1.5)


if __name__ == "__main__":
    unittest.main()
