from __future__ import annotations

import json
from pathlib import Path
import tempfile
import unittest

import numpy as np

from RL.controllers.tcn_impedance import TCNImpedanceController
from RL.env.actor_observation import (
    ACTOR_FRAME_DIM,
    ACTOR_HISTORY_DIM,
    ACTOR_OBSERVATION_DIM,
    DEFAULT_ACTOR_FRAME_SCALE,
    RESET_PROTOCOL,
    RESET_WARMUP_STEPS,
)


class TCNImpedanceControllerTest(unittest.TestCase):
    def make_controller(self, **overrides) -> TCNImpedanceController:
        options = {
            "feature_mean": np.zeros(16, dtype=np.float32),
            "feature_std": np.ones(16, dtype=np.float32),
            "feature_clip": 10.0,
            "horizon_steps": (5, 10),
            "selected_horizon_steps": 5,
            "kp_nm_per_rad": 4.0,
            "kd_nm_s_per_rad": 0.2,
            "action_scale_nm": 2.0,
        }
        options.update(overrides)
        return TCNImpedanceController(**options)

    @staticmethod
    def observation(
        controller: TCNImpedanceController,
        *,
        current_q: np.ndarray | None = None,
        current_dq: np.ndarray | None = None,
        raw_delta16: np.ndarray | None = None,
    ) -> np.ndarray:
        observation = np.zeros(ACTOR_OBSERVATION_DIM, dtype=np.float32)
        frame = np.zeros(ACTOR_FRAME_DIM, dtype=np.float32)
        if current_q is not None:
            frame[:4] = current_q
        if current_dq is not None:
            frame[4:8] = current_dq
        frame_start = ACTOR_HISTORY_DIM - ACTOR_FRAME_DIM
        observation[frame_start:ACTOR_HISTORY_DIM] = (
            frame / DEFAULT_ACTOR_FRAME_SCALE
        )
        raw = (
            np.zeros(16, dtype=np.float32)
            if raw_delta16 is None
            else np.asarray(raw_delta16, dtype=np.float32)
        )
        observation[-16:] = (
            raw - controller.feature_mean
        ) / controller.feature_std
        return observation

    def test_zero_delta_returns_zero_action(self) -> None:
        controller = self.make_controller()
        command = controller.compute(self.observation(controller))
        np.testing.assert_array_equal(command.target_torque_nm, 0.0)
        np.testing.assert_array_equal(command.action, 0.0)
        self.assertEqual(command.confidence, 1.0)

    def test_decodes_current_state_and_applies_per_joint_gains(self) -> None:
        kp = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        kd = np.asarray([0.5, 0.4, 0.3, 0.2], dtype=np.float32)
        controller = self.make_controller(
            kp_nm_per_rad=kp,
            kd_nm_s_per_rad=kd,
            action_scale_nm=np.full(4, 4.0, dtype=np.float32),
        )
        q = np.asarray([0.1, 0.2, 0.3, 0.4], dtype=np.float32)
        dq = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        raw = np.zeros(16, dtype=np.float32)
        raw[:4] = np.asarray([0.5, -0.4, 0.3, -0.2])
        raw[4:8] = np.asarray([2.0, -1.0, 0.5, -0.25])
        command = controller.compute(
            self.observation(
                controller,
                current_q=q,
                current_dq=dq,
                raw_delta16=raw,
            )
        )
        expected_torque = 0.2 * (kp * raw[:4] + kd * raw[4:8])
        np.testing.assert_allclose(command.current_q_rad, q, atol=1.0e-6)
        np.testing.assert_allclose(command.current_dq_rad_s, dq, atol=1.0e-6)
        np.testing.assert_allclose(
            command.predicted_q_rad,
            q + raw[:4],
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            command.target_torque_nm,
            expected_torque,
            atol=1.0e-6,
        )
        np.testing.assert_allclose(
            command.action,
            expected_torque / 4.0,
            atol=1.0e-6,
        )

    def test_nontrivial_feature_normalization_is_reversed(self) -> None:
        mean = np.linspace(-0.5, 0.5, 16, dtype=np.float32)
        std = np.linspace(0.5, 2.0, 16, dtype=np.float32)
        controller = self.make_controller(
            feature_mean=mean,
            feature_std=std,
            feature_clip=20.0,
            kp_nm_per_rad=1.0,
            kd_nm_s_per_rad=0.0,
        )
        raw = np.linspace(-1.0, 1.0, 16, dtype=np.float32)
        command = controller.compute(
            self.observation(controller, raw_delta16=raw)
        )
        np.testing.assert_allclose(command.delta_q_rad, raw[:4], atol=1.0e-6)
        np.testing.assert_allclose(
            command.delta_dq_rad_s,
            raw[4:8],
            atol=1.0e-6,
        )

    def test_200ms_horizon_uses_second_eight_features(self) -> None:
        controller = self.make_controller(
            selected_horizon_steps=10,
            kp_nm_per_rad=5.0,
            kd_nm_s_per_rad=0.0,
        )
        raw = np.zeros(16, dtype=np.float32)
        raw[:4] = 9.0
        raw[8:12] = np.asarray([1.0, 0.0, 0.0, 0.0])
        command = controller.compute(
            self.observation(controller, raw_delta16=raw)
        )
        np.testing.assert_allclose(
            command.target_torque_nm,
            np.asarray([0.5, 0.0, 0.0, 0.0]),
            atol=1.0e-6,
        )

    def test_confidence_fades_before_selected_feature_clip(self) -> None:
        controller = self.make_controller(feature_clip=5.0)
        raw = np.zeros(16, dtype=np.float32)
        raw[0] = 4.0
        command = controller.compute(
            self.observation(controller, raw_delta16=raw)
        )
        self.assertFalse(command.feature_saturated)
        self.assertAlmostEqual(command.feature_ood_ratio, 0.8)
        self.assertAlmostEqual(command.confidence, 0.5)
        self.assertAlmostEqual(float(command.target_torque_nm[0]), 0.4)

    def test_selected_feature_at_clip_disables_assistance(self) -> None:
        controller = self.make_controller(feature_clip=5.0)
        raw = np.zeros(16, dtype=np.float32)
        raw[0] = 5.0
        command = controller.compute(
            self.observation(controller, raw_delta16=raw)
        )
        self.assertTrue(command.feature_saturated)
        self.assertEqual(command.confidence, 0.0)
        np.testing.assert_array_equal(command.action, 0.0)

    def test_physical_prediction_error_is_limited_for_control_only(self) -> None:
        controller = self.make_controller(
            feature_clip=100.0,
            kp_nm_per_rad=4.0,
            kd_nm_s_per_rad=0.2,
            position_delta_limit_rad=1.0,
            velocity_delta_limit_rad_s=10.0,
        )
        raw = np.zeros(16, dtype=np.float32)
        raw[0] = 3.0
        raw[4] = 20.0
        command = controller.compute(
            self.observation(controller, raw_delta16=raw)
        )
        self.assertTrue(command.error_limited)
        self.assertAlmostEqual(float(command.delta_q_rad[0]), 3.0)
        self.assertAlmostEqual(float(command.predicted_q_rad[0]), 3.0)
        self.assertAlmostEqual(float(command.control_delta_q_rad[0]), 1.0)
        self.assertAlmostEqual(float(command.control_delta_dq_rad_s[0]), 10.0)
        self.assertAlmostEqual(float(command.target_torque_nm[0]), 1.2)

    def test_unselected_feature_at_clip_does_not_gate_selected_horizon(self) -> None:
        controller = self.make_controller(feature_clip=5.0)
        raw = np.zeros(16, dtype=np.float32)
        raw[0] = 1.0
        raw[8] = 5.0
        command = controller.compute(
            self.observation(controller, raw_delta16=raw)
        )
        self.assertFalse(command.feature_saturated)
        self.assertEqual(command.confidence, 1.0)
        self.assertGreater(float(command.action[0]), 0.0)

    def test_current_sensor_at_clip_disables_assistance(self) -> None:
        controller = self.make_controller()
        raw = np.zeros(16, dtype=np.float32)
        raw[0] = 1.0
        current_q = np.zeros(4, dtype=np.float32)
        current_q[0] = 5.0 * np.pi
        command = controller.compute(
            self.observation(
                controller,
                current_q=current_q,
                raw_delta16=raw,
            )
        )
        self.assertTrue(command.sensor_saturated)
        self.assertEqual(command.confidence, 0.0)
        np.testing.assert_array_equal(command.action, 0.0)

    def test_action_is_clipped_and_reported(self) -> None:
        controller = self.make_controller(
            feature_clip=100.0,
            kp_nm_per_rad=10.0,
            kd_nm_s_per_rad=0.0,
            action_scale_nm=2.0,
        )
        raw = np.zeros(16, dtype=np.float32)
        raw[2] = 10.0
        command = controller.compute(
            self.observation(controller, raw_delta16=raw)
        )
        self.assertTrue(command.action_saturated)
        np.testing.assert_array_equal(
            command.action,
            np.asarray([0.0, 0.0, 1.0, 0.0], dtype=np.float32),
        )

    def test_invalid_observation_is_rejected(self) -> None:
        controller = self.make_controller()
        with self.assertRaises(ValueError):
            controller.compute(np.zeros(159, dtype=np.float32))
        invalid = np.zeros(160, dtype=np.float32)
        invalid[0] = np.nan
        with self.assertRaises(ValueError):
            controller.compute(invalid)

    def test_calibration_factory_reads_protocol(self) -> None:
        calibration = {
            "protocol": "gexo_myoassist_phase12_tcn_calibration_v1",
            "schema_version": 1,
            "domain_randomization_enabled": False,
            "tcn_checkpoint_sha256": "expected",
            "fit": {
                "warmup_protocol": RESET_PROTOCOL,
                "warmup_steps": RESET_WARMUP_STEPS,
                "reset_state_contract": "canonical_full_state_v1",
            },
            "actor_feature_normalization": {
                "mean": [0.0] * 16,
                "std": [1.0] * 16,
                "clip": 5.0,
                "horizon_steps": [5, 10],
            }
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(calibration), encoding="utf-8")
            controller = TCNImpedanceController.from_calibration(
                path,
                expected_tcn_checkpoint_sha256="expected",
            )
        self.assertEqual(controller.selected_horizon_steps, 5)
        self.assertAlmostEqual(controller.prediction_fraction, 0.2)

    def test_calibration_factory_rejects_wrong_checkpoint(self) -> None:
        calibration = {
            "protocol": "gexo_myoassist_phase12_tcn_calibration_v1",
            "schema_version": 1,
            "domain_randomization_enabled": False,
            "tcn_checkpoint_sha256": "actual",
            "fit": {
                "warmup_protocol": RESET_PROTOCOL,
                "warmup_steps": RESET_WARMUP_STEPS,
                "reset_state_contract": "canonical_full_state_v1",
            },
            "actor_feature_normalization": {
                "mean": [0.0] * 16,
                "std": [1.0] * 16,
                "clip": 5.0,
                "horizon_steps": [5, 10],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(calibration), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "hash mismatch"):
                TCNImpedanceController.from_calibration(
                    path,
                    expected_tcn_checkpoint_sha256="expected",
                )

    def test_calibration_factory_rejects_wrong_horizons(self) -> None:
        calibration = {
            "protocol": "gexo_myoassist_phase12_tcn_calibration_v1",
            "schema_version": 1,
            "domain_randomization_enabled": False,
            "tcn_checkpoint_sha256": "expected",
            "fit": {
                "warmup_protocol": RESET_PROTOCOL,
                "warmup_steps": RESET_WARMUP_STEPS,
                "reset_state_contract": "canonical_full_state_v1",
            },
            "actor_feature_normalization": {
                "mean": [0.0] * 16,
                "std": [1.0] * 16,
                "clip": 5.0,
                "horizon_steps": [5, 9],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(calibration), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "exactly"):
                TCNImpedanceController.from_calibration(path)

    def test_calibration_factory_rejects_wrong_reset_contract(self) -> None:
        calibration = {
            "protocol": "gexo_myoassist_phase12_tcn_calibration_v1",
            "schema_version": 1,
            "domain_randomization_enabled": False,
            "tcn_checkpoint_sha256": "expected",
            "fit": {
                "warmup_protocol": RESET_PROTOCOL,
                "warmup_steps": RESET_WARMUP_STEPS,
                "reset_state_contract": "wrong",
            },
            "actor_feature_normalization": {
                "mean": [0.0] * 16,
                "std": [1.0] * 16,
                "clip": 5.0,
                "horizon_steps": [5, 10],
            },
        }
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "calibration.json"
            path.write_text(json.dumps(calibration), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "reset-state"):
                TCNImpedanceController.from_calibration(path)


if __name__ == "__main__":
    unittest.main()
