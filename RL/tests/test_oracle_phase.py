from __future__ import annotations

import unittest
from dataclasses import replace
from pathlib import Path
from tempfile import TemporaryDirectory

import numpy as np

from RL.env.kinesis.oracle_phase import (
    build_phase_cost_profile,
    extract_oracle_phase,
    hysteresis_contact,
    phase_aligned_score,
)
from RL.runners.analyze_oracle_phase_reward import analyze_directory


DT = 0.02


def synthetic_touch(
    *,
    length: int = 300,
    left_start: int = 25,
    stride_steps: int = 50,
) -> np.ndarray:
    touch = np.zeros((length, 4), dtype=np.float64)
    for start in range(left_start, length, stride_steps):
        touch[start : min(start + 30, length), 2] = 80.0
        touch[start + 18 : min(start + 32, length), 3] = 40.0
    for start in range(left_start - stride_steps // 2, length, stride_steps):
        begin = max(start, 0)
        touch[begin : min(start + 30, length), 0] = 75.0
        touch[max(start + 18, 0) : min(start + 32, length), 1] = 35.0
    return touch


class OraclePhaseTest(unittest.TestCase):
    def test_hysteresis_rejects_one_frame_spike(self) -> None:
        force = np.zeros(20)
        force[5] = 100.0
        contact = hysteresis_contact(
            force,
            on_threshold=10.0,
            off_threshold=5.0,
            min_on_frames=2,
            min_off_frames=2,
        )
        self.assertFalse(contact.any())

    def test_stride_events_produce_circular_phase(self) -> None:
        phase = extract_oracle_phase(
            synthetic_touch(),
            dt=DT,
            on_threshold=5.0,
            off_threshold=2.0,
        )
        self.assertGreaterEqual(len(phase.event_indices), 5)
        self.assertGreaterEqual(len(np.unique(phase.cycle_id[phase.valid])), 4)

        first_cycle = int(np.min(phase.cycle_id[phase.valid]))
        indices = np.flatnonzero(phase.cycle_id == first_cycle)
        self.assertAlmostEqual(float(phase.phase[indices[0]]), 0.0)
        self.assertAlmostEqual(float(phase.phase[indices[25]]), 0.5)
        self.assertTrue(np.all(np.diff(phase.phase[indices]) > 0.0))
        self.assertTrue(
            np.allclose(phase.phase_rate_hz[indices], 1.0)
        )

    def test_phase_score_is_zero_for_baseline_and_has_correct_sign(self) -> None:
        phase = extract_oracle_phase(
            synthetic_touch(),
            dt=DT,
            on_threshold=5.0,
            off_threshold=2.0,
        )
        cost = np.full(phase.phase.size, 2.0)
        cost[phase.valid] += np.sin(2.0 * np.pi * phase.phase[phase.valid])
        profile = build_phase_cost_profile(phase, cost, dt=DT, bins=20)
        cycle_id = int(profile.cycle_ids[1])

        baseline_score = phase_aligned_score(
            profile,
            phase,
            cost,
            dt=DT,
            cycle_id=cycle_id,
        )
        higher_cost_score = phase_aligned_score(
            profile,
            phase,
            1.1 * cost,
            dt=DT,
            cycle_id=cycle_id,
        )
        lower_cost_score = phase_aligned_score(
            profile,
            phase,
            0.9 * cost,
            dt=DT,
            cycle_id=cycle_id,
        )

        self.assertAlmostEqual(baseline_score, 0.0, delta=0.01)
        self.assertLess(higher_cost_score, -0.08)
        self.assertGreater(lower_cost_score, 0.08)

    def test_phase_alignment_removes_a_pure_timing_shift(self) -> None:
        baseline_phase = extract_oracle_phase(
            synthetic_touch(),
            dt=DT,
            on_threshold=5.0,
            off_threshold=2.0,
        )
        shifted_phase = extract_oracle_phase(
            synthetic_touch(left_start=35),
            dt=DT,
            on_threshold=5.0,
            off_threshold=2.0,
        )
        baseline_cost = np.full(baseline_phase.phase.size, 2.0)
        baseline_cost[baseline_phase.valid] += np.sin(
            2.0 * np.pi * baseline_phase.phase[baseline_phase.valid]
        )
        shifted_cost = np.full(shifted_phase.phase.size, 2.0)
        shifted_cost[shifted_phase.valid] += np.sin(
            2.0 * np.pi * shifted_phase.phase[shifted_phase.valid]
        )
        profile = build_phase_cost_profile(
            baseline_phase,
            baseline_cost,
            dt=DT,
            bins=20,
        )
        cycle_id = int(np.unique(shifted_phase.cycle_id[shifted_phase.valid])[1])
        phase_score = phase_aligned_score(
            profile,
            shifted_phase,
            shifted_cost,
            dt=DT,
            cycle_id=cycle_id,
        )

        selected = shifted_phase.cycle_id == cycle_id
        time_residual_rms = float(
            np.sqrt(
                np.mean(
                    np.square(
                        baseline_cost[selected] - shifted_cost[selected]
                    )
                )
            )
        )
        self.assertAlmostEqual(phase_score, 0.0, delta=0.01)
        self.assertGreater(time_residual_rms, 0.5)

    def test_phase_score_does_not_hide_a_wrong_phase_rate(self) -> None:
        phase = extract_oracle_phase(
            synthetic_touch(),
            dt=DT,
            on_threshold=5.0,
            off_threshold=2.0,
        )
        cost = np.full(phase.phase.size, 2.0)
        profile = build_phase_cost_profile(phase, cost, dt=DT)
        cycle_id = int(profile.cycle_ids[1])
        too_fast = replace(
            phase,
            phase_rate_hz=1.2 * phase.phase_rate_hz,
        )
        score = phase_aligned_score(
            profile,
            too_fast,
            cost,
            dt=DT,
            cycle_id=cycle_id,
        )
        self.assertGreater(score, 0.15)

    def test_audit_recovers_controlled_action_ranking(self) -> None:
        touch = synthetic_touch()
        phase = extract_oracle_phase(
            touch,
            dt=DT,
            on_threshold=5.0,
            off_threshold=2.0,
        )
        base_cost = np.full(phase.phase.size, 2.0)
        base_cost[phase.valid] += 0.5 * np.sin(
            2.0 * np.pi * phase.phase[phase.valid]
        )
        base_torque = np.full(phase.phase.size, 10.0)
        time_s = np.arange(phase.phase.size) * DT

        with TemporaryDirectory() as directory:
            root = Path(directory)
            for seed in (0, 1, 2):
                common = {
                    "motion_id": 8,
                    "seed": seed,
                    "success": True,
                    "terminated": False,
                    "truncated": True,
                    "termination_reason": "time_limit",
                    "time_s": time_s,
                    "touch": touch,
                    "muscle_torque_cost": base_torque,
                    "tracking_mse": np.full(phase.phase.size, 5.0e-4),
                    "reward": np.zeros(phase.phase.size),
                    "joint_position": np.zeros((phase.phase.size, 4)),
                    "joint_velocity": np.zeros((phase.phase.size, 4)),
                    "control_dt": DT,
                    "contact_on_threshold": 5.0,
                    "contact_off_threshold": 2.0,
                }
                np.savez_compressed(
                    root / f"baseline_{seed}.npz",
                    **common,
                    kind="baseline",
                    activation_cost=base_cost,
                    same_state_saving=np.zeros(phase.phase.size),
                    exo_torque=np.zeros((phase.phase.size, 4)),
                    pulse_start_step=-1,
                    pulse_joint=-1,
                    pulse_nm=0.0,
                    pulse_steps=0,
                    target_phase=np.nan,
                )

                for pulse_nm in (-2.0, -1.0, 1.0, 2.0):
                    saving = 0.02 * pulse_nm + 0.001 * (seed - 1)
                    exo_torque = np.zeros((phase.phase.size, 4))
                    exo_torque[100:104, 0] = pulse_nm
                    np.savez_compressed(
                        root / f"pulse_{seed}_{pulse_nm:+.0f}.npz",
                        **common,
                        kind="pulse",
                        activation_cost=(1.0 - saving) * base_cost,
                        same_state_saving=np.full(phase.phase.size, saving),
                        exo_torque=exo_torque,
                        pulse_start_step=100,
                        pulse_joint=0,
                        pulse_nm=pulse_nm,
                        pulse_steps=4,
                        target_phase=0.5,
                    )

            report = analyze_directory(root, deadband=0.005)

        phase_ranking = report["ranking"]["phase_aligned_score"]
        self.assertGreater(phase_ranking["spearman"], 0.95)
        self.assertEqual(phase_ranking["sign_agreement"], 1.0)
        self.assertTrue(report["decision"]["paired_oracle_identity_passed"])
        # Oracle-only agreement is no longer enough to authorize PPO.  The
        # stricter decision also requires a held-out causal phase model.
        self.assertFalse(report["decision"]["ready_for_short_ppo_ab"])


if __name__ == "__main__":
    unittest.main()
