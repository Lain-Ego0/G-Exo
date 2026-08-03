"""Tests for backend-neutral muscle contracts and physiology metrics."""

from __future__ import annotations

from dataclasses import fields
import unittest

import numpy as np

from RL.env.kinesis.physiology_metrics import (
    compute_physiology_metrics as compute_kinesis_metrics,
)
from RL.metrics.physiology import compute_physiology_metrics
from RL.optimization.contracts import MuscleSnapshot


class PhysiologyTest(unittest.TestCase):
    def setUp(self) -> None:
        self.arguments = {
            "activation": np.asarray([0.4, 0.3, 0.2, 0.5]),
            "baseline_activation": np.asarray([0.3, 0.35, 0.25, 0.45]),
            "muscle_force_n": np.asarray([10.0, 8.0, 3.0, 5.0]),
            "baseline_muscle_force_n": np.asarray([8.0, 9.0, 4.0, 4.5]),
            "target_moment_arm_m": np.asarray(
                [
                    [0.10, 0.00, 0.00, 0.00],
                    [-0.10, 0.05, 0.00, 0.00],
                    [0.00, -0.04, 0.08, 0.00],
                    [0.00, 0.00, -0.06, 0.07],
                ]
            ),
            "target_mask": np.asarray([True, True, True, False]),
            "overload_top_k": 2,
        }

    def test_neutral_metrics_are_kinesis_formula_equivalent(self) -> None:
        neutral = compute_physiology_metrics(**self.arguments)
        reference = compute_kinesis_metrics(**self.arguments)
        for field in fields(neutral):
            actual = getattr(neutral, field.name)
            expected = getattr(reference, field.name)
            if isinstance(actual, np.ndarray):
                np.testing.assert_array_equal(actual, expected)
            else:
                self.assertEqual(actual, expected)

    def test_antagonists_do_not_cancel_gross_load(self) -> None:
        result = compute_physiology_metrics(
            activation=np.asarray([0.2, 0.2]),
            baseline_activation=np.asarray([0.2, 0.2]),
            muscle_force_n=np.asarray([10.0, 10.0]),
            baseline_muscle_force_n=np.asarray([10.0, 10.0]),
            target_moment_arm_m=np.asarray([[0.1], [-0.1]]),
        )
        np.testing.assert_allclose(result.net_joint_torque_nm, [0.0])
        np.testing.assert_allclose(result.muscle_effort_nm, [1.0, 1.0])
        np.testing.assert_allclose(result.co_contraction_abs_nm, [1.0])
        np.testing.assert_allclose(result.co_contraction_index, [1.0])

    def test_snapshot_validates_and_copies_affine_force_model(self) -> None:
        activation = np.asarray([0.2, 0.3])
        snapshot = MuscleSnapshot(
            time_s=0.02,
            activation=activation,
            activation_lower=np.zeros(2),
            activation_upper=np.ones(2),
            moment_arm_m=np.asarray(
                [[0.1, 0.0, 0.0, 0.0], [-0.1, 0.2, 0.0, 0.0]]
            ),
            target_mask=np.asarray([True, True]),
            model_hash="synthetic-sha256",
            active_force_gain_n=np.asarray([10.0, 20.0]),
            passive_force_n=np.asarray([1.0, 2.0]),
        )
        activation.fill(0.9)
        np.testing.assert_allclose(snapshot.activation, [0.2, 0.3])
        np.testing.assert_allclose(
            snapshot.resolved_muscle_force_n(),
            [3.0, 8.0],
        )
        with self.assertRaises(ValueError):
            snapshot.activation[0] = 0.4

    def test_snapshot_rejects_incomplete_force_representation(self) -> None:
        with self.assertRaises(ValueError):
            MuscleSnapshot(
                time_s=0.0,
                activation=np.asarray([0.2]),
                activation_lower=np.asarray([0.0]),
                activation_upper=np.asarray([1.0]),
                moment_arm_m=np.zeros((1, 4)),
                target_mask=np.asarray([True]),
                model_hash="synthetic-sha256",
                active_force_gain_n=np.asarray([10.0]),
            )


if __name__ == "__main__":
    unittest.main()
