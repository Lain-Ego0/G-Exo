"""Direct contracts for MyoAssist zero-assist statistics and reward V1."""

from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import numpy as np

from RL.env.myoassist.baseline import (
    NAKED_REFERENCE_CONDITION,
    PHASE_BIN_COUNT,
    SPEED_WINDOW_STEPS,
    ForwardSpeedWindow,
    MyoAssistBaseline,
    fit_baseline,
    validate_calibrated_speed_range,
)
from RL.env.myoassist.reward import MyoAssistReward, RewardConfig
from RL.env.myoassist.muscle_adapter import target_activation_masks
from RL.env.myoassist.motion_reference import (
    URDF_ZERO_ASSIST_CONDITION,
    MyoAssistMotionReference,
)
from RL.optimization.contracts import MuscleSnapshot


MODEL_HASH = "physical-model-hash"
PHYSIOLOGY_SIGNATURE = "physiology-signature"
MUSCLE_NAMES = tuple(
    f"{stem}_{side}"
    for side in ("r", "l")
    for stem in (
        "hamstrings",
        "bifemsh",
        "edl",
        "fdl",
        "glutmax",
        "iliopsoas",
        "rectfem",
        "vasti",
        "gastroc",
        "soleus",
        "tibant",
    )
)


def baseline_metadata() -> dict[str, object]:
    return {
        "model_sha256": MODEL_HASH,
        "reference_model_sha256": MODEL_HASH,
        "human_checkpoint_sha256": "human-checkpoint",
        "physiology_signature": PHYSIOLOGY_SIGNATURE,
        "reference_condition": NAKED_REFERENCE_CONDITION,
        "urdf_enabled": False,
        "target_activation": {
            "cost": "mean_squared_activation",
            "side_order": ["left", "right"],
            "muscle_names_by_side": {
                side: [
                    name
                    for name, selected in zip(
                        MUSCLE_NAMES,
                        target_activation_masks(MUSCLE_NAMES)[side_index],
                    )
                    if selected
                ]
                for side_index, side in enumerate(("left", "right"))
            },
        },
    }


def make_baseline(*, gross_scale: float = 0.1) -> MyoAssistBaseline:
    def phase_table(values: list[float]) -> np.ndarray:
        return np.repeat(
            np.asarray(values, dtype=np.float64)[:, None],
            PHASE_BIN_COUNT,
            axis=1,
        )

    return MyoAssistBaseline(
        speeds_m_s=np.asarray([1.0, 1.25]),
        activation_mean=phase_table([0.09, 0.08]),
        activation_std=phase_table([0.01, 0.02]),
        target_activation_mean=np.repeat(
            phase_table([0.09, 0.08])[..., None], 2, axis=2
        ),
        target_activation_std=np.repeat(
            phase_table([0.01, 0.02])[..., None], 2, axis=2
        ),
        human_torque_mean=phase_table([1.0, 1.2]),
        human_torque_std=phase_table([0.5, 0.6]),
        gross_median=phase_table([1.0, 1.1]),
        gross_scale=phase_table([gross_scale, gross_scale]),
        joint_q_mean=np.full((2, PHASE_BIN_COUNT, 4), 0.5),
        joint_q_scale=np.full((2, PHASE_BIN_COUNT, 4), 0.1),
        human_joint_scale_nm=np.ones(4),
        gross_joint_scale_nm=np.ones(4),
        phase_bin_count=PHASE_BIN_COUNT,
        speed_window_steps=SPEED_WINDOW_STEPS,
        speed_free_error_m_s=np.asarray([0.05, 0.20]),
        speed_transition_m_s=np.asarray([0.10, 0.30]),
        minimum_pelvis_height_m=0.8,
        pelvis_height_transition_m=0.05,
        pelvis_pitch_free_rad=0.2,
        pelvis_pitch_transition_rad=0.1,
        joint_lower_rad=np.zeros(4),
        joint_upper_rad=np.full(4, 2.0),
        joint_limit_margin_rad=np.full(4, 0.1),
        joint_limit_transition_rad=np.full(4, 0.1),
        metadata=baseline_metadata(),
    )


def make_motion_reference() -> MyoAssistMotionReference:
    return MyoAssistMotionReference(
        speeds_m_s=np.asarray([1.0, 1.25]),
        joint_q_mean=np.full((2, PHASE_BIN_COUNT, 4), 0.5),
        joint_q_scale=np.full((2, PHASE_BIN_COUNT, 4), 0.1),
        movement_free_z=np.ones(2),
        movement_transition_z=np.full(2, 0.5),
        phase_bin_count=PHASE_BIN_COUNT,
        metadata={
            "reference_condition": URDF_ZERO_ASSIST_CONDITION,
            "urdf_enabled": True,
            "physical_model_sha256": MODEL_HASH,
            "human_checkpoint_sha256": "human-checkpoint",
        },
    )


def make_snapshot(
    *,
    activation: float | np.ndarray = 0.3,
    joint_load: float = 1.0,
    model_hash: str = MODEL_HASH,
    target_mask: np.ndarray | None = None,
    valid: bool = True,
    physiology_signature: str = PHYSIOLOGY_SIGNATURE,
) -> MuscleSnapshot:
    moment_arm = np.zeros((22, 4), dtype=np.float64)
    moment_arm[np.arange(4), np.arange(4)] = joint_load
    return MuscleSnapshot(
        time_s=0.02,
        activation=np.broadcast_to(
            np.asarray(activation, dtype=np.float64), (22,)
        ).copy(),
        activation_lower=np.zeros(22),
        activation_upper=np.ones(22),
        moment_arm_m=moment_arm,
        target_mask=(
            np.ones(22, dtype=bool)
            if target_mask is None
            else target_mask
        ),
        model_hash=model_hash,
        valid=valid,
        validity_reason="" if valid else "synthetic failure",
        muscle_force_n=np.ones(22),
        metadata={
            "physiology_signature": physiology_signature,
            "muscle_names": MUSCLE_NAMES,
        },
    )


def compute(
    reward: MyoAssistReward,
    snapshot: MuscleSnapshot,
    *,
    speed: float = 1.0,
    target_speed: float = 1.0,
    torque: float | np.ndarray = 0.0,
    gait_phase: float = 0.0,
    joint_q: float | np.ndarray = 0.5,
    terminated: bool = False,
    remaining_steps: int = 0,
) -> dict[str, float]:
    _, diagnostics = reward.compute(
        snapshot=snapshot,
        gait_phase=gait_phase,
        gait_period_steps=50.0,
        filtered_target_speed_m_s=target_speed,
        filtered_forward_speed_m_s=speed,
        pelvis_height_m=1.0,
        pelvis_pitch_rad=0.0,
        joint_q_rad=np.broadcast_to(
            np.asarray(joint_q, dtype=np.float64), (4,)
        ).copy(),
        joint_dq_rad_s=np.zeros(4),
        exo_torque_nm=np.broadcast_to(
            np.asarray(torque, dtype=np.float64),
            (4,),
        ).copy(),
        terminated=terminated,
        remaining_steps=remaining_steps,
    )
    return diagnostics


class MyoAssistBaselineRewardTest(unittest.TestCase):
    def test_phase_conditioning_removes_cycle_mean_bias(self) -> None:
        repeats = 4
        phase_centers = (np.arange(PHASE_BIN_COUNT) + 0.5) / PHASE_BIN_COUNT
        phase = np.repeat(phase_centers, repeats)
        activation = 0.1 + 0.04 * np.sin(2.0 * np.pi * phase)
        count = len(phase)
        baseline = fit_baseline(
            speed_m_s=np.ones(count),
            gait_phase=phase,
            activation_cost=activation,
            target_activation_cost=np.repeat(activation[:, None], 2, axis=1),
            human_joint_torque_nm=np.ones((count, 4)),
            gross_joint_load_nm=np.ones((count, 4)),
            forward_speed_filtered_m_s=np.ones(count),
            pelvis_height_m=np.ones(count),
            pelvis_pitch_rad=np.zeros(count),
            joint_q_rad=np.ones((count, 4)),
            joint_lower_rad=np.zeros(4),
            joint_upper_rad=np.full(4, 2.0),
            metadata=baseline_metadata(),
        )
        for phase_value, expected in zip(phase_centers, activation[::repeats]):
            self.assertAlmostEqual(
                baseline.at_speed(1.0, phase_value).activation_mean,
                expected,
            )

    def test_cycle_average_reference_is_independent_of_phase_origin(self) -> None:
        baseline = make_baseline()
        expected = baseline.cycle_average_at_speed(1.125)
        self.assertAlmostEqual(expected.activation_mean, 0.085)
        self.assertAlmostEqual(expected.human_torque_mean, 1.1)
        raw_saving = (expected.activation_mean - 0.3**2) / expected.activation_mean
        expected_saving = raw_saving - max(-raw_saving, 0.0)
        for phase in (0.0, 0.25, 0.5, 0.99):
            # The training reward no longer selects physiology by this value.
            reward = MyoAssistReward(baseline, make_motion_reference())
            result = compute(
                reward,
                make_snapshot(),
                target_speed=1.125,
                speed=1.125,
                gait_phase=phase,
            )
            self.assertAlmostEqual(
                result["activation_saving_ratio"],
                expected_saving,
            )

    def test_speed_window_is_seeded_by_exact_preroll(self) -> None:
        window = ForwardSpeedWindow(SPEED_WINDOW_STEPS)
        for _ in range(SPEED_WINDOW_STEPS):
            window.append(1.0)
        self.assertTrue(window.full)
        self.assertAlmostEqual(window.mean, 1.0)
        self.assertAlmostEqual(window.append(2.0), 1.02)

    def test_baseline_speed_threshold_uses_filtered_signal(self) -> None:
        count = 100
        target = np.ones(count)
        filtered = np.ones(count)
        raw = 1.0 + 0.5 * np.sin(np.linspace(0.0, 10.0, count))
        baseline = fit_baseline(
            speed_m_s=target,
            gait_phase=np.arange(count) / PHASE_BIN_COUNT,
            activation_cost=np.full(count, 0.1),
            target_activation_cost=np.full((count, 2), 0.1),
            human_joint_torque_nm=np.ones((count, 4)),
            gross_joint_load_nm=np.ones((count, 4)),
            forward_speed_filtered_m_s=filtered,
            pelvis_height_m=np.ones(count),
            pelvis_pitch_rad=np.zeros(count),
            joint_q_rad=np.ones((count, 4)),
            joint_lower_rad=np.zeros(4),
            joint_upper_rad=np.full(4, 2.0),
            metadata=baseline_metadata(),
        )
        np.testing.assert_allclose(baseline.speed_free_error_m_s, [0.0])
        self.assertGreater(float(np.percentile(np.abs(raw - target), 95.0)), 0.4)

    def test_environment_speed_range_uses_baseline_tcn_intersection(self) -> None:
        baseline = make_baseline()
        calibrated = np.asarray([0.8, 1.0, 1.25])
        validate_calibrated_speed_range(
            baseline,
            minimum_m_s=1.0,
            maximum_m_s=1.25,
            verified_speed_m_s=calibrated,
        )
        with self.assertRaisesRegex(ValueError, "calibrated intersection"):
            validate_calibrated_speed_range(
                baseline,
                minimum_m_s=0.8,
                maximum_m_s=1.25,
                verified_speed_m_s=calibrated,
            )
        with self.assertRaisesRegex(ValueError, "calibrated intersection"):
            validate_calibrated_speed_range(
                baseline,
                minimum_m_s=1.0,
                maximum_m_s=1.3,
                verified_speed_m_s=calibrated,
            )
        with self.assertRaisesRegex(ValueError, "no valid verified speed range"):
            validate_calibrated_speed_range(
                baseline,
                minimum_m_s=1.0,
                maximum_m_s=1.25,
                verified_speed_m_s=np.asarray([]),
            )

    def test_speed_interpolation_round_trip_and_no_extrapolation(self) -> None:
        baseline = make_baseline()
        midpoint = baseline.at_speed(1.125)
        self.assertAlmostEqual(midpoint.activation_mean, 0.085)
        self.assertAlmostEqual(midpoint.gross_median, 1.05)
        self.assertAlmostEqual(midpoint.speed_free_error_m_s, 0.125)
        self.assertAlmostEqual(midpoint.speed_transition_m_s, 0.20)
        baseline.at_speed(np.nextafter(1.0, -np.inf))
        baseline.at_speed(np.nextafter(1.25, np.inf))
        with self.assertRaises(ValueError):
            baseline.at_speed(0.99)

        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "baseline.json"
            baseline.save(path)
            loaded = MyoAssistBaseline.load(path)
        np.testing.assert_array_equal(loaded.speeds_m_s, baseline.speeds_m_s)
        self.assertEqual(loaded.metadata["reference_model_sha256"], MODEL_HASH)

        old_payload = baseline.to_dict()
        old_payload["schema"] = "gexo_myoassist_zero_assist_baseline_v2"
        with self.assertRaisesRegex(ValueError, "Unsupported baseline schema"):
            MyoAssistBaseline(**old_payload)

    def test_gross_mad_scale_controls_only_excess_penalty(self) -> None:
        snapshot = make_snapshot(activation=0.3, joint_load=1.2)
        narrow = compute(
            MyoAssistReward(make_baseline(gross_scale=0.1), make_motion_reference()),
            snapshot,
        )
        wide = compute(
            MyoAssistReward(make_baseline(gross_scale=1.0), make_motion_reference()),
            snapshot,
        )
        self.assertAlmostEqual(narrow["gross_penalty"], -0.25)
        self.assertAlmostEqual(wide["gross_penalty"], -0.0025)

        at_threshold = compute(
            MyoAssistReward(
                make_baseline(gross_scale=0.1), make_motion_reference()
            ),
            make_snapshot(activation=0.3, joint_load=1.1),
        )
        self.assertAlmostEqual(at_threshold["gross_penalty"], 0.0)

    def test_positive_saving_is_gated_but_negative_saving_is_kept(self) -> None:
        config = RewardConfig(activation_weight=1.0)
        positive = make_snapshot(activation=0.2)
        safe = compute(
            MyoAssistReward(make_baseline(), make_motion_reference(), config),
            positive,
        )
        unsafe = compute(
            MyoAssistReward(make_baseline(), make_motion_reference(), config),
            positive,
            speed=2.0,
        )
        self.assertGreater(safe["effort"], 0.0)
        self.assertEqual(unsafe["effort"], 0.0)

        negative = make_snapshot(activation=0.4)
        unsafe_negative = compute(
            MyoAssistReward(make_baseline(), make_motion_reference(), config),
            negative,
            speed=2.0,
        )
        self.assertLess(unsafe_negative["effort"], 0.0)

    def test_side_degradation_is_not_hidden_by_the_other_leg(self) -> None:
        masks = target_activation_masks(MUSCLE_NAMES)
        activation = np.full(22, 0.3)
        activation[masks[0]] = 0.4
        activation[masks[1]] = 0.2
        result = compute(
            MyoAssistReward(
                make_baseline(),
                make_motion_reference(),
                RewardConfig(activation_weight=1.0),
            ),
            make_snapshot(activation=activation),
        )
        self.assertLess(result["activation_saving_left_ratio"], 0.0)
        self.assertGreater(result["activation_saving_right_ratio"], 0.0)
        self.assertGreater(result["activation_side_degradation_ratio"], 0.0)
        self.assertLess(
            result["activation_saving_ratio"],
            result["activation_saving_mean_ratio"],
        )

    def test_zero_assist_preroll_fills_causal_cycle_window(self) -> None:
        reward = MyoAssistReward(make_baseline(), make_motion_reference())
        snapshot = make_snapshot()
        for _ in range(50):
            reward.prime(snapshot, gait_period_steps=50.0)
        result = compute(reward, snapshot)
        self.assertEqual(result["physiology_window_target_steps"], 50.0)
        self.assertEqual(result["physiology_window_steps"], 50.0)
        self.assertEqual(result["physiology_window_fill_ratio"], 1.0)

    def test_speed_gate_compares_equally_filtered_actual_and_target(self) -> None:
        snapshot = make_snapshot(activation=0.2)
        matched = compute(
            MyoAssistReward(make_baseline(), make_motion_reference()),
            snapshot,
            speed=1.2,
            target_speed=1.2,
        )
        mismatched = compute(
            MyoAssistReward(make_baseline(), make_motion_reference()),
            snapshot,
            speed=1.2,
            target_speed=1.0,
        )
        self.assertEqual(matched["speed_excess"], 0.0)
        self.assertGreater(mismatched["speed_excess"], 0.0)

    def test_speed_thresholds_are_fitted_per_bin_and_interpolated(self) -> None:
        frames_per_speed = PHASE_BIN_COUNT * 2
        speeds = np.repeat([0.8, 1.0, 1.25], frames_per_speed)
        errors = np.repeat([0.30, 0.15, 0.075], frames_per_speed)
        count = len(speeds)
        baseline = fit_baseline(
            speed_m_s=speeds,
            gait_phase=np.tile(
                np.repeat(
                    (np.arange(PHASE_BIN_COUNT) + 0.5) / PHASE_BIN_COUNT,
                    2,
                ),
                3,
            ),
            activation_cost=np.full(count, 0.1),
            target_activation_cost=np.full((count, 2), 0.1),
            human_joint_torque_nm=np.ones((count, 4)),
            gross_joint_load_nm=np.ones((count, 4)),
            forward_speed_filtered_m_s=speeds + errors,
            pelvis_height_m=np.ones(count),
            pelvis_pitch_rad=np.zeros(count),
            joint_q_rad=np.ones((count, 4)),
            joint_lower_rad=np.zeros(4),
            joint_upper_rad=np.full(4, 2.0),
            metadata=baseline_metadata(),
        )
        np.testing.assert_allclose(
            baseline.speed_free_error_m_s,
            [0.30, 0.15, 0.075],
        )
        np.testing.assert_allclose(
            baseline.speed_transition_m_s,
            [0.10, 0.10, 0.10],
        )
        self.assertAlmostEqual(
            baseline.at_speed(0.9).speed_free_error_m_s,
            0.225,
        )

    def test_jerk_uses_second_difference(self) -> None:
        reward = MyoAssistReward(make_baseline(), make_motion_reference())
        snapshot = make_snapshot()
        compute(reward, snapshot, torque=1.0)
        second = compute(reward, snapshot, torque=1.0)
        third = compute(reward, snapshot, torque=1.0)
        self.assertLess(second["jerk_penalty"], 0.0)
        self.assertAlmostEqual(third["jerk_penalty"], 0.0)

    def test_movement_uses_worn_urdf_reference_and_standardized_hinge(self) -> None:
        reward = MyoAssistReward(make_baseline(), make_motion_reference())
        safe = compute(reward, make_snapshot(), joint_q=0.5)
        outside = compute(reward, make_snapshot(), joint_q=0.8)
        self.assertEqual(safe["movement_penalty"], 0.0)
        self.assertAlmostEqual(outside["movement_z_rms"], 3.0)
        self.assertLess(outside["movement_penalty"], 0.0)

    def test_movement_selects_nearest_cycle_state_not_external_phase(self) -> None:
        motion = make_motion_reference()
        means = motion.joint_q_mean.copy()
        means[:, 0] = 0.0
        means[:, PHASE_BIN_COUNT // 2] = 1.0
        motion = MyoAssistMotionReference(
            speeds_m_s=motion.speeds_m_s,
            joint_q_mean=means,
            joint_q_scale=motion.joint_q_scale,
            movement_free_z=motion.movement_free_z,
            movement_transition_z=motion.movement_transition_z,
            phase_bin_count=motion.phase_bin_count,
            metadata=motion.metadata,
        )
        reward = MyoAssistReward(make_baseline(), motion)
        first = compute(reward, make_snapshot(), gait_phase=0.0, joint_q=1.0)
        reward.reset()
        second = compute(reward, make_snapshot(), gait_phase=0.5, joint_q=1.0)
        self.assertAlmostEqual(first["movement_z_rms"], second["movement_z_rms"])

    def test_termination_charges_discounted_remaining_horizon(self) -> None:
        reward = MyoAssistReward(make_baseline(), make_motion_reference())
        result = compute(
            reward,
            make_snapshot(),
            terminated=True,
            remaining_steps=100,
        )
        expected_tail = 0.05 * (1.0 - 0.99**100) / (1.0 - 0.99)
        self.assertAlmostEqual(
            result["termination_penalty"],
            -1.0 - expected_tail,
        )

    def test_torque_penalty_is_hinged_and_uses_worst_joint(self) -> None:
        reward = MyoAssistReward(make_baseline(), make_motion_reference())
        snapshot = make_snapshot()
        safe = compute(reward, snapshot, torque=6.5)
        warning = compute(
            reward,
            snapshot,
            torque=np.asarray([7.25, 0.0, 0.0, 0.0]),
        )
        terminal = compute(reward, snapshot, torque=8.0)

        self.assertEqual(safe["torque_overload_penalty"], 0.0)
        self.assertAlmostEqual(safe["torque_usage_cost"], 1.0)
        self.assertAlmostEqual(safe["torque_usage_penalty"], -0.01)
        self.assertAlmostEqual(warning["torque_cost"], 0.25)
        self.assertAlmostEqual(warning["torque_overload_penalty"], -0.25)
        self.assertAlmostEqual(warning["max_absolute_exo_torque_nm"], 7.25)
        self.assertAlmostEqual(terminal["torque_cost"], 1.0)

    def test_snapshot_validity_physiology_and_full_mask_are_enforced(self) -> None:
        reward = MyoAssistReward(make_baseline(), make_motion_reference())
        with self.assertRaisesRegex(ValueError, "invalid muscle snapshot"):
            compute(reward, make_snapshot(valid=False))
        with self.assertRaisesRegex(ValueError, "physiology signatures differ"):
            compute(
                reward,
                make_snapshot(physiology_signature="other-physiology"),
            )
        mask = np.ones(22, dtype=bool)
        mask[-1] = False
        with self.assertRaisesRegex(ValueError, "all 22 muscles"):
            compute(reward, make_snapshot(target_mask=mask))


if __name__ == "__main__":
    unittest.main()
