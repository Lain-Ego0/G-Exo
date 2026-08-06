"""MyoAssist-side provenance checks for the shared frozen TCN calibration."""

from __future__ import annotations

import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

import numpy as np
import torch

from RL.env.actor_observation import runtime32_to_phase12_interleaved
from RL.runners.calibrate_myoassist_tcn import (
    load_checkpoint_input_moments,
    load_phase_inputs,
    resolve_phase_inputs,
)
from RL.runners.predictors.tcn_calibration import (
    runtime32_to_interleaved_batch,
)


class MyoAssistTCNCalibrationContractTest(unittest.TestCase):
    def test_batch_reorder_is_the_shared_per_frame_conversion(self) -> None:
        frames = np.arange(3 * 32, dtype=np.float64).reshape(3, 32)
        expected = np.stack(
            [runtime32_to_phase12_interleaved(frame) for frame in frames]
        )
        np.testing.assert_array_equal(
            runtime32_to_interleaved_batch(frames),
            expected,
        )

    def test_checkpoint_fallback_exactly_restores_input_moments(self) -> None:
        mean = np.linspace(-2.0, 2.0, 32)
        std = np.linspace(0.1, 1.0, 32)
        with tempfile.TemporaryDirectory() as directory:
            checkpoint = Path(directory) / "checkpoint.pt"
            torch.save(
                {"statistics": {"input_mean": mean, "input_std": std}},
                checkpoint,
            )
            restored = load_checkpoint_input_moments(checkpoint)
            np.testing.assert_allclose(restored.mean(axis=0), mean)
            np.testing.assert_allclose(restored.std(axis=0), std)

            missing = Path(directory) / "missing"
            with patch.dict(os.environ, {}, clear=True), patch(
                "RL.runners.calibrate_myoassist_tcn.LOCAL_PHASE_ROOT",
                missing,
            ):
                values, source, root = resolve_phase_inputs(None, checkpoint)
            np.testing.assert_array_equal(values, restored)
            self.assertEqual(source, "checkpoint_frozen_input_mean_std")
            self.assertIsNone(root)

    def test_explicit_missing_root_and_all_invalid_data_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            checkpoint = root / "checkpoint.pt"
            torch.save(
                {
                    "statistics": {
                        "input_mean": np.zeros(32),
                        "input_std": np.ones(32),
                    }
                },
                checkpoint,
            )
            with self.assertRaises(FileNotFoundError):
                resolve_phase_inputs(root / "does-not-exist", checkpoint)

            subject = root / "BT01"
            subject.mkdir()
            np.savez_compressed(
                subject / "invalid.npz",
                input=np.zeros((2, 32)),
                input_valid=np.zeros(2, dtype=bool),
            )
            with self.assertRaisesRegex(ValueError, "no finite valid frames"):
                load_phase_inputs(root)


if __name__ == "__main__":
    unittest.main()
