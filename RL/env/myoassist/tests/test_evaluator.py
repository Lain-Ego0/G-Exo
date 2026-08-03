from __future__ import annotations

import numpy as np
import unittest

from RL.optimization.contracts import MuscleSnapshot
from RL.runners.evaluate_myoassist_exo import (
    _oracle_action,
    _parse_modes,
    finalize_pair,
)


PROTOCOL_THRESHOLDS = {
    "speed_tolerance_m_s": 0.2,
    "minimum_pelvis_height_m": 0.7,
    "maximum_pelvis_pitch_rad": 0.4,
    "maximum_joint_limit_excess": 1.0,
}


def _run(
    mode: str,
    *,
    steps: int = 100,
    success: bool = True,
    activation: float = 10.0,
    torque: float = 20.0,
    gross: float = 30.0,
) -> dict[str, object]:
    return {
        "mode": mode,
        "speed_m_s": 1.0,
        "steps": steps,
        "success": success,
        "activation_cost_integral": activation,
        "human_torque_cost_integral": torque,
        "gross_cost_integral": gross,
        "mean_forward_speed_m_s": 1.05,
        "minimum_pelvis_height_m": 0.8,
        "maximum_absolute_pelvis_pitch_rad": 0.2,
        "maximum_joint_limit_excess": 0.0,
    }


class MyoAssistEvaluatorTest(unittest.TestCase):
    def test_oracle_sums_each_muscle_joint_contribution(self) -> None:
        snapshot = MuscleSnapshot(
            time_s=0.0,
            activation=np.array([0.2, 0.4]),
            activation_lower=np.zeros(2),
            activation_upper=np.ones(2),
            moment_arm_m=np.array(
                [
                    [0.1, -0.1, 0.0, 0.0],
                    [0.2, 0.1, 0.3, -0.2],
                ]
            ),
            target_mask=np.ones(2, dtype=bool),
            model_hash="test-model",
            muscle_force_n=np.array([10.0, 20.0]),
        )

        action = _oracle_action(
            snapshot,
            action_torque_scale_nm=np.full(4, 10.0),
            oracle_gain=0.5,
        )

        np.testing.assert_allclose(action, [0.25, 0.05, 0.30, -0.20])

    def test_valid_pair_computes_savings_and_effectiveness(self) -> None:
        pair = finalize_pair(
            {
                "baseline": _run("baseline"),
                "policy": _run(
                    "policy",
                    activation=9.0,
                    torque=20.0,
                    gross=32.0,
                ),
            },
            requested_modes=("baseline", "policy"),
            requested_steps=100,
            protocol_thresholds=PROTOCOL_THRESHOLDS,
            nondegradation_tolerance=0.0,
            minimum_improvement=0.0,
            gross_degradation_tolerance=0.1,
        )

        self.assertIs(pair["pair_valid"], True)
        self.assertIs(pair["protocol_pass"], True)
        self.assertAlmostEqual(pair["policy_activation_saving_fraction"], 0.1)
        self.assertAlmostEqual(pair["policy_human_torque_saving_fraction"], 0.0)
        self.assertAlmostEqual(
            pair["policy_gross_load_saving_fraction"], -2.0 / 30.0
        )
        self.assertIs(pair["effectiveness_by_mode"]["policy"]["pass"], True)

    def test_short_or_unequal_pair_has_null_savings(self) -> None:
        for steps, success in ((99, False), (99, True)):
            with self.subTest(steps=steps, success=success):
                pair = finalize_pair(
                    {
                        "baseline": _run("baseline"),
                        "policy": _run(
                            "policy",
                            steps=steps,
                            success=success,
                            activation=1.0,
                        ),
                    },
                    requested_modes=("baseline", "policy"),
                    requested_steps=100,
                    protocol_thresholds=PROTOCOL_THRESHOLDS,
                    nondegradation_tolerance=0.0,
                    minimum_improvement=0.0,
                    gross_degradation_tolerance=0.1,
                )

                self.assertIs(pair["pair_valid"], False)
                self.assertIs(pair["protocol_pass"], False)
                self.assertIsNone(pair["policy_activation_saving_fraction"])
                self.assertIsNone(pair["policy_human_torque_saving_fraction"])
                self.assertIsNone(pair["policy_gross_load_saving_fraction"])
                self.assertIs(
                    pair["effectiveness_by_mode"]["policy"]["pass"], False
                )

    def test_protocol_and_effectiveness_are_independent(self) -> None:
        pair = finalize_pair(
            {
                "baseline": _run("baseline"),
                "policy": _run(
                    "policy",
                    activation=10.5,
                    torque=20.5,
                    gross=30.0,
                ),
            },
            requested_modes=("baseline", "policy"),
            requested_steps=100,
            protocol_thresholds=PROTOCOL_THRESHOLDS,
            nondegradation_tolerance=0.0,
            minimum_improvement=0.0,
            gross_degradation_tolerance=0.1,
        )

        self.assertIs(pair["protocol_pass"], True)
        self.assertIs(pair["effectiveness_by_mode"]["policy"]["pass"], False)

    def test_modes_require_baseline_and_are_unique(self) -> None:
        self.assertEqual(_parse_modes("baseline,oracle"), ("baseline", "oracle"))
        with self.assertRaisesRegex(ValueError, "requires baseline"):
            _parse_modes("policy")
        with self.assertRaisesRegex(ValueError, "unique"):
            _parse_modes("baseline,baseline")


if __name__ == "__main__":
    unittest.main()
