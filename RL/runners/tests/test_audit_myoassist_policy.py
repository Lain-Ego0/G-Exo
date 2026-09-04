from __future__ import annotations

import unittest

import numpy as np

from RL.runners.audit_myoassist_policy import (
    AUDIT_MODES,
    TCN_FEATURE_DIM,
    TcnObservationTransform,
    build_replay_torque,
    finalize_audit_pair,
    summarize_audit,
)


class MyoAssistPolicyAuditTest(unittest.TestCase):
    def test_zero_tcn_preserves_history_and_zeros_feature_bank(self) -> None:
        observation = np.arange(160, dtype=np.float32)
        transformed = TcnObservationTransform("zero_tcn", 2)(observation)

        np.testing.assert_array_equal(
            transformed[:-TCN_FEATURE_DIM],
            observation[:-TCN_FEATURE_DIM],
        )
        np.testing.assert_array_equal(transformed[-TCN_FEATURE_DIM:], 0.0)
        np.testing.assert_array_equal(observation, np.arange(160, dtype=np.float32))

    def test_delayed_tcn_uses_only_past_features(self) -> None:
        transform = TcnObservationTransform("delayed_tcn", 2)
        observations = []
        for value in (1.0, 2.0, 3.0):
            observation = np.zeros(160, dtype=np.float32)
            observation[-TCN_FEATURE_DIM:] = value
            observations.append(transform(observation))

        np.testing.assert_array_equal(observations[0][-TCN_FEATURE_DIM:], 1.0)
        np.testing.assert_array_equal(observations[1][-TCN_FEATURE_DIM:], 2.0)
        np.testing.assert_array_equal(observations[2][-TCN_FEATURE_DIM:], 1.0)

    def test_constant_torque_replays_the_cycle_mean(self) -> None:
        torque = np.asarray([[1.0, 2.0, 3.0, 4.0], [3.0, 4.0, 5.0, 6.0]])
        replay = build_replay_torque(torque, "constant_torque", 1)

        np.testing.assert_allclose(replay, [[2.0, 3.0, 4.0, 5.0]] * 2)

    def test_phase_shift_preserves_samples_and_changes_timing(self) -> None:
        torque = np.arange(24, dtype=np.float32).reshape(6, 4)
        replay = build_replay_torque(torque, "phase_shifted_torque", 3)

        np.testing.assert_array_equal(replay, np.roll(torque, 3, axis=0))
        np.testing.assert_array_equal(np.sort(replay, axis=0), np.sort(torque, axis=0))

    def test_failed_ablation_does_not_invalidate_policy_pair(self) -> None:
        def run(mode: str, *, success: bool = True) -> dict[str, object]:
            return {
                "mode": mode,
                "steps": 10 if success else 5,
                "success": success,
                "mean_forward_speed_m_s": 1.0,
                "speed_m_s": 1.0,
                "minimum_pelvis_height_m": 0.9,
                "maximum_absolute_pelvis_pitch_rad": 0.1,
                "maximum_joint_limit_excess": 0.0,
                "activation_cost_integral": 10.0 if mode == "baseline" else 9.0,
                "target_activation_cost_integral_left": 5.0,
                "target_activation_cost_integral_right": 5.0,
                "human_torque_cost_integral": 10.0 if mode == "baseline" else 9.0,
                "gross_cost_integral": 10.0 if mode == "baseline" else 9.0,
                "naked_phase_aligned_movement_rmse_rad": 0.01,
                "mean_absolute_exo_torque_nm": 1.0,
                "rms_exo_torque_nm": 1.0,
                "dc_fraction": 0.5,
                "dynamic_fraction": 0.5,
            }

        runs = {"baseline": run("baseline")}
        runs.update({mode: run(mode) for mode in AUDIT_MODES})
        runs["zero_tcn"] = run("zero_tcn", success=False)
        pair = finalize_audit_pair(
            runs,
            requested_steps=10,
            protocol_thresholds={
                "speed_tolerance_m_s": 0.1,
                "minimum_pelvis_height_m": 0.8,
                "maximum_pelvis_pitch_rad": 0.2,
                "maximum_joint_limit_excess": 1.0,
            },
        )

        self.assertTrue(pair["pair_valid_by_mode"]["policy"])
        self.assertFalse(pair["pair_valid_by_mode"]["zero_tcn"])
        self.assertIsNotNone(pair["policy_activation_saving_fraction"])
        self.assertIsNone(pair["zero_tcn_activation_saving_fraction"])

        by_mode, conclusions = summarize_audit(
            [pair], strict_speed_delta_m_s=0.03
        )
        self.assertEqual(by_mode["policy"]["valid_pair_count"], 1)
        self.assertEqual(by_mode["zero_tcn"]["valid_pair_count"], 0)
        self.assertFalse(conclusions["tcn_benefit_supported"])


if __name__ == "__main__":
    unittest.main()
