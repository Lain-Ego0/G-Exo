from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

import numpy as np
import torch

from RL.env.kinesis.tcn_adapter import TCNInputAdapter
from RL.runners.predictors.tcn import MotionTCN
from RL.runners.predictors.tcn_runtime import FrozenTCNRuntime


class FrozenTCNRuntimeTest(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary_directory = tempfile.TemporaryDirectory()
        root = Path(self.temporary_directory.name)
        self.checkpoint = root / "tcn.pt"
        model = MotionTCN(
            input_dim=32,
            hidden_dim=64,
            target_dim=12,
            horizon_count=2,
            dropout=0.0,
        )
        torch.save(
            {
                "model_state_dict": model.state_dict(),
                "input_dim": 32,
                "hidden_dim": 64,
                "target_dim": 12,
                "history": 50,
                "horizons": (5, 10),
                "dropout": 0.0,
                "statistics": {
                    "input_mean": np.zeros(32, dtype=np.float32),
                    "input_std": np.ones(32, dtype=np.float32),
                    "target_mean": np.zeros(12, dtype=np.float32),
                    "target_std": np.ones(12, dtype=np.float32),
                },
            },
            self.checkpoint,
        )
        rotation = np.repeat(np.eye(3)[None, :, :], 4, axis=0)
        rotation[0] = np.asarray(
            [[0.0, -1.0, 0.0], [1.0, 0.0, 0.0], [0.0, 0.0, 1.0]]
        )
        self.calibration = root / "calibration.json"
        self.calibration.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "input": {
                        "motor_position_scale": [1.0, -1.0, 1.0, -1.0],
                        "motor_position_offset": [0.1, 0.2, 0.3, 0.4],
                        "motor_velocity_scale": [1.0, -1.0, 1.0, -1.0],
                        "imu_rotation": rotation.tolist(),
                    },
                    "output": {
                        "target_position_scale": [1.0] * 4,
                        "target_position_offset": [0.0] * 4,
                        "target_velocity_scale": [1.0] * 4,
                    },
                    "actor_feature_normalization": {
                        "horizon_steps": [5, 10],
                        "mean": [0.0] * 16,
                        "std": [1.0] * 16,
                        "clip": 5.0,
                    },
                }
            ),
            encoding="utf-8",
        )

    def tearDown(self) -> None:
        self.temporary_directory.cleanup()

    def _runtime(self) -> FrozenTCNRuntime:
        return FrozenTCNRuntime(
            self.checkpoint,
            calibration=self.calibration,
            allow_legacy_checkpoint=True,
        )

    def test_input_calibration_precedes_phase12_reordering(self) -> None:
        runtime = self._runtime()
        frame = np.arange(32, dtype=np.float32)
        converted = runtime.to_tcn_order(frame)
        np.testing.assert_allclose(
            converted[:8],
            [0.1, -0.8, 2.3, -2.6, 4.0, -5.0, 6.0, -7.0],
        )
        np.testing.assert_allclose(
            converted[8:14],
            [-9.0, 8.0, 10.0, -21.0, 20.0, 22.0],
        )
        np.testing.assert_allclose(
            converted[14:20],
            [11.0, 12.0, 13.0, 23.0, 24.0, 25.0],
        )

    def test_history_is_causal_and_prediction_contract_is_finite(self) -> None:
        runtime = self._runtime()
        history = np.arange(50 * 32, dtype=np.float32).reshape(50, 32) / 100.0
        runtime.extend(history)
        before = runtime.predict(history[-1, :4], history[-1, 4:8])

        changed_future = history.copy()
        changed_future[-1] = history[-1]
        self.assertTrue(runtime.ready)
        self.assertEqual(runtime.history_size, 50)
        self.assertEqual(before.prediction.shape, (2, 12))
        self.assertEqual(before.joint_prediction.shape, (2, 8))
        self.assertEqual(before.raw_delta16.shape, (16,))
        self.assertEqual(before.feature16.shape, (16,))
        self.assertTrue(np.all(np.isfinite(before.feature16)))
        self.assertTrue(
            all(
                not parameter.requires_grad
                for parameter in runtime.model.parameters()
            )
        )

    def test_matches_existing_kinesis_adapter_at_shared_boundary(self) -> None:
        runtime = self._runtime()
        reference = TCNInputAdapter(
            self.checkpoint,
            calibration=self.calibration,
        )
        history = np.arange(50 * 32, dtype=np.float32).reshape(50, 32) / 100.0
        runtime.extend(history)
        reference.extend(history)
        current_q = history[-1, :4]
        current_dq = history[-1, 4:8]

        actual = runtime.predict(current_q, current_dq)
        expected_prediction = reference.predict()
        expected_raw = reference.raw_deployment_features(
            expected_prediction,
            current_q,
            current_dq,
        )
        expected_feature = reference.deployment_features(
            expected_prediction,
            current_q,
            current_dq,
        )

        np.testing.assert_array_equal(
            runtime.latest_normalized_frame,
            reference.latest_normalized_frame,
        )
        np.testing.assert_allclose(
            actual.joint_prediction,
            expected_prediction.joint_prediction,
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            actual.raw_delta16,
            expected_raw,
            rtol=0.0,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            actual.feature16,
            expected_feature,
            rtol=0.0,
            atol=1.0e-6,
        )

    def test_legacy_checkpoint_requires_explicit_opt_in(self) -> None:
        with self.assertRaisesRegex(ValueError, "allow_legacy_checkpoint"):
            FrozenTCNRuntime(self.checkpoint, calibration=self.calibration)


if __name__ == "__main__":
    unittest.main()
