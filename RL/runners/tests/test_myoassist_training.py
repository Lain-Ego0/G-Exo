"""Training protocol, resume provenance and metrics tests for route B."""

from __future__ import annotations

from copy import deepcopy
import json
from pathlib import Path
import tempfile
import unittest

import gymnasium as gym
import numpy as np
import torch

from RL.env.myoassist.baseline import (
    BASELINE_SCHEMA,
    NAKED_REFERENCE_CONDITION,
    TRAINING_SPEED_SCHEDULE,
)
from RL.env.myoassist.motion_reference import (
    MOTION_REFERENCE_SCHEMA,
    URDF_ZERO_ASSIST_CONDITION,
)
from RL.env.actor_observation import (
    JOINT_ORDER,
    RESET_PROTOCOL,
    RESET_WARMUP_STEPS,
)
from RL.runners.myoassist_training import (
    CanonicalEvaluationEnv,
    ProtocolMismatchError,
    build_training_protocol,
    collect_myoassist_metrics,
    file_sha256,
    prepare_run_config,
)


class RecordingEnv(gym.Env):
    def __init__(self) -> None:
        self.observation_space = gym.spaces.Box(-1.0, 1.0, shape=(1,))
        self.action_space = gym.spaces.Box(-1.0, 1.0, shape=(1,))
        self.last_seed = None
        self.last_options = None

    def reset(self, *, seed=None, options=None):
        self.last_seed = seed
        self.last_options = options
        return np.zeros(1, dtype=np.float32), {}


class ProtocolFixture:
    def __init__(self, root: Path) -> None:
        self.root = root
        self.root.mkdir(parents=True, exist_ok=True)
        self.human = self._bytes("human.zip", b"frozen-human")
        self.model = self._bytes("model.xml", b"physical-model")
        self.reference_model = self._bytes("reference.xml", b"naked-model")
        self.physiology_signature = "shared-physiology"
        self.tcn = root / "tcn.pt"
        torch.save(
            {
                "input_dim": 32,
                "target_dim": 12,
                "history": 50,
                "horizons": (5, 10),
                "pipeline_version": "test-v1",
            },
            self.tcn,
        )
        self.baseline = root / "baseline.json"
        self.motion_reference = root / "motion_reference.json"
        self.calibration = root / "calibration.json"
        self.baseline.write_text(
            json.dumps(
                {
                    "schema": BASELINE_SCHEMA,
                    "speed_window_steps": 50,
                    "speeds_m_s": [0.8, 1.0, 1.25],
                    "metadata": {
                        "human_checkpoint_sha256": file_sha256(self.human),
                        "model_sha256": file_sha256(self.reference_model),
                        "reference_model_sha256": file_sha256(
                            self.reference_model
                        ),
                        "physiology_signature": self.physiology_signature,
                        "reference_condition": NAKED_REFERENCE_CONDITION,
                        "warmup_steps": RESET_WARMUP_STEPS,
                        "warmup_protocol": RESET_PROTOCOL,
                        "urdf_enabled": False,
                        "domain_randomization_enabled": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.motion_reference.write_text(
            json.dumps(
                {
                    "schema": MOTION_REFERENCE_SCHEMA,
                    "speeds_m_s": [0.8, 1.0, 1.25],
                    "metadata": {
                        "human_checkpoint_sha256": file_sha256(self.human),
                        "physical_model_sha256": file_sha256(self.model),
                        "reference_condition": URDF_ZERO_ASSIST_CONDITION,
                        "warmup_steps": RESET_WARMUP_STEPS,
                        "warmup_protocol": RESET_PROTOCOL,
                        "urdf_enabled": True,
                        "domain_randomization_enabled": False,
                    },
                }
            ),
            encoding="utf-8",
        )
        self.calibration.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "protocol": "gexo_myoassist_phase12_tcn_calibration_v1",
                    "human_checkpoint_sha256": file_sha256(self.human),
                    "physical_model_sha256": file_sha256(self.model),
                    "physiology_signature": self.physiology_signature,
                    "tcn_checkpoint_sha256": file_sha256(self.tcn),
                    "verified_speed_set_m_s": [0.8, 1.0, 1.25],
                    "fit": {
                        "warmup_steps": RESET_WARMUP_STEPS,
                        "warmup_protocol": RESET_PROTOCOL,
                    },
                    "urdf_enabled": True,
                    "domain_randomization_enabled": False,
                }
            ),
            encoding="utf-8",
        )

    def protocol(self, **changes):
        values = {
            "human_checkpoint": self.human,
            "baseline_path": self.baseline,
            "motion_reference_path": self.motion_reference,
            "tcn_checkpoint": self.tcn,
            "tcn_calibration_path": self.calibration,
            "model_path": self.model,
            "min_speed_m_s": 0.8,
            "max_speed_m_s": 1.25,
            "action_scale_nm": 8.0,
            "max_episode_steps": 1000,
            "workers": 8,
            "seed": 42,
            "ppo_parameters": {"learning_rate": 3.0e-4},
            "evaluation_speed_m_s": 1.0,
            "evaluation_seed": 0,
        }
        values.update(changes)
        return build_training_protocol(**values)

    def _bytes(self, name: str, value: bytes) -> Path:
        path = self.root / name
        path.write_bytes(value)
        return path


class MyoAssistTrainingProtocolTest(unittest.TestCase):
    def test_eval_wrapper_forces_one_canonical_condition(self) -> None:
        base = RecordingEnv()
        environment = CanonicalEvaluationEnv(
            base,
            target_speed_m_s=1.0,
            reference_index=0,
            seed=7,
        )
        _, info = environment.reset(
            seed=999,
            options={"target_speed": 1.25, "reference_index": 100},
        )
        self.assertEqual(base.last_seed, 7)
        self.assertEqual(
            base.last_options,
            {"target_speed": 1.0, "reference_index": 0},
        )
        self.assertTrue(info["canonical_evaluation"])

    def test_protocol_contains_physical_and_learning_contracts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            protocol = ProtocolFixture(Path(directory)).protocol()
        self.assertEqual(protocol["observation"]["dimension"], 160)
        self.assertEqual(protocol["action_and_safety"]["joint_order"], list(JOINT_ORDER))
        self.assertEqual(protocol["training_domain"]["speed_range_m_s"], [0.8, 1.25])
        self.assertEqual(
            protocol["training_domain"]["speed_sampling"]["anchor_range_m_s"],
            [0.8, 1.25],
        )
        self.assertEqual(
            protocol["training_domain"]["speed_schedule"],
            TRAINING_SPEED_SCHEDULE,
        )
        self.assertEqual(protocol["evaluation"]["reference_index"], 0)
        self.assertFalse(protocol["training_domain"]["domain_randomization_enabled"])
        self.assertEqual(
            protocol["action_and_safety"]["hard_torque_limit_nm"],
            [8.0] * 4,
        )
        self.assertEqual(
            protocol["action_and_safety"]["torque_soft_threshold_nm"],
            6.5,
        )
        self.assertEqual(
            protocol["action_and_safety"]["torque_termination_threshold_nm"],
            8.0,
        )
        self.assertEqual(
            protocol["action_and_safety"]["torque_rate_limit_nm_s"],
            [20.0] * 4,
        )
        self.assertEqual(
            protocol["reward"]["jerk_scale_nm"],
            [0.4] * 4,
        )
        self.assertEqual(len(protocol["sha256"]), 64)

    def test_protocol_records_narrow_domain_randomization(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            protocol = ProtocolFixture(Path(directory)).protocol(
                domain_randomization_enabled=True
            )
        domain = protocol["training_domain"]
        self.assertTrue(domain["domain_randomization_enabled"])
        self.assertEqual(domain["domain_randomization"]["max_action_delay_steps"], 1)
        self.assertAlmostEqual(
            domain["domain_randomization"]["torque_gain_fraction"],
            0.05,
        )

    def test_requested_speed_must_be_inside_both_artifacts(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProtocolFixture(Path(directory))
            with self.assertRaisesRegex(ValueError, "outside calibrated range"):
                fixture.protocol(max_speed_m_s=1.5)

    def test_protocol_keeps_naked_reference_and_accepts_urdf_runtime(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProtocolFixture(Path(directory))
            baseline = json.loads(fixture.baseline.read_text(encoding="utf-8"))
            baseline["metadata"]["urdf_enabled"] = True
            fixture.baseline.write_text(json.dumps(baseline), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "explicitly False"):
                fixture.protocol()

            baseline["metadata"]["urdf_enabled"] = False
            fixture.baseline.write_text(json.dumps(baseline), encoding="utf-8")
            calibration = json.loads(
                fixture.calibration.read_text(encoding="utf-8")
            )
            calibration["urdf_enabled"] = True
            fixture.calibration.write_text(
                json.dumps(calibration),
                encoding="utf-8",
            )
            protocol = fixture.protocol()
            self.assertTrue(protocol["training_domain"]["urdf_enabled"])

    def test_artifact_identity_mismatch_fails_before_training(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            fixture = ProtocolFixture(Path(directory))
            calibration = json.loads(fixture.calibration.read_text(encoding="utf-8"))
            calibration["tcn_checkpoint_sha256"] = "0" * 64
            fixture.calibration.write_text(json.dumps(calibration), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "tcn_checkpoint_sha256"):
                fixture.protocol()

    def test_resume_compares_protocol_and_preserves_config_bytes(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = ProtocolFixture(root / "artifacts")
            protocol = fixture.protocol()
            run = root / "run"
            config = prepare_run_config(
                output_dir=run,
                protocol=protocol,
                launch={"timesteps": 1000},
                resume_from=None,
            )
            checkpoint = run / "checkpoints" / "gexo_ppo_1000_steps.zip"
            checkpoint.parent.mkdir()
            checkpoint.write_bytes(b"policy")
            original = config.read_bytes()

            same = prepare_run_config(
                output_dir=run,
                protocol=protocol,
                launch={"timesteps": 2000},
                resume_from=checkpoint,
            )
            self.assertEqual(same, config)
            self.assertEqual(config.read_bytes(), original)

            changed = deepcopy(protocol)
            changed["action_and_safety"]["action_scale_nm"] = 10.0
            with self.assertRaises(ProtocolMismatchError):
                prepare_run_config(
                    output_dir=run,
                    protocol=changed,
                    launch={"timesteps": 2000},
                    resume_from=checkpoint,
                )
            self.assertEqual(config.read_bytes(), original)

    def test_resume_allows_only_explicit_randomization_curriculum(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = ProtocolFixture(root / "artifacts")
            nominal = fixture.protocol()
            source = root / "nominal"
            prepare_run_config(
                output_dir=source,
                protocol=nominal,
                launch={"timesteps": 1000},
                resume_from=None,
            )
            checkpoint = source / "best_model" / "best_model.zip"
            checkpoint.parent.mkdir()
            checkpoint.write_bytes(b"policy")
            randomized = fixture.protocol(domain_randomization_enabled=True)

            with self.assertRaises(ProtocolMismatchError):
                prepare_run_config(
                    output_dir=root / "strict",
                    protocol=randomized,
                    launch={"timesteps": 1000},
                    resume_from=checkpoint,
                )
            config = prepare_run_config(
                output_dir=root / "curriculum",
                protocol=randomized,
                launch={"timesteps": 1000},
                resume_from=checkpoint,
                allow_domain_randomization_enable=True,
            )
            self.assertTrue(config.is_file())

            incompatible = deepcopy(randomized)
            incompatible["action_and_safety"]["action_scale_nm"] = 7.0
            with self.assertRaises(ProtocolMismatchError):
                prepare_run_config(
                    output_dir=root / "incompatible",
                    protocol=incompatible,
                    launch={"timesteps": 1000},
                    resume_from=checkpoint,
                    allow_domain_randomization_enable=True,
                )

    def test_resume_allows_only_explicit_speed_curriculum_widening(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = ProtocolFixture(root / "artifacts")
            narrow = fixture.protocol(
                min_speed_m_s=0.9,
                max_speed_m_s=1.1,
                evaluation_speeds_m_s=(0.9, 1.0, 1.1),
            )
            source = root / "narrow"
            prepare_run_config(
                output_dir=source,
                protocol=narrow,
                launch={"timesteps": 1000},
                resume_from=None,
            )
            checkpoint = source / "best_model" / "best_model.zip"
            checkpoint.parent.mkdir()
            checkpoint.write_bytes(b"policy")
            wide = fixture.protocol(
                min_speed_m_s=0.8,
                max_speed_m_s=1.25,
                anchor_min_speed_m_s=0.9,
                anchor_max_speed_m_s=1.1,
                evaluation_speeds_m_s=(0.8, 1.0, 1.25),
            )

            with self.assertRaises(ProtocolMismatchError):
                prepare_run_config(
                    output_dir=root / "strict",
                    protocol=wide,
                    launch={"timesteps": 1000},
                    resume_from=checkpoint,
                )
            config = prepare_run_config(
                output_dir=root / "curriculum",
                protocol=wide,
                launch={"timesteps": 1000},
                resume_from=checkpoint,
                allow_speed_curriculum_widening=True,
            )
            self.assertTrue(config.is_file())

    def test_fresh_run_rejects_nonempty_unproven_output(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            fixture = ProtocolFixture(root / "artifacts")
            output = root / "legacy-output"
            output.mkdir()
            (output / "final_model.zip").write_bytes(b"unproven")
            with self.assertRaisesRegex(FileExistsError, "must be empty"):
                prepare_run_config(
                    output_dir=output,
                    protocol=fixture.protocol(),
                    launch={"timesteps": 1000},
                    resume_from=None,
                )

    def test_metrics_include_reward_physiology_and_four_joint_traces(self) -> None:
        info = {
            "reward_terms": {"effort": 0.25, "total": 0.2},
            "reward_metrics": {
                "activation_cost": 0.4,
                "human_torque_cost": 1.2,
                "gross_load_cost": 1.1,
                "activation_saving_ratio": 0.03,
                "human_torque_saving_ratio": -0.01,
                "activation_residual_z": 0.3,
                "human_torque_residual_z": -0.1,
                "activation_cost_ema": 0.39,
                "human_torque_cost_ema": 1.1,
                "saving_raw": 0.14,
                "safety_gate": 1.0,
                "speed_excess": 0.0,
                "upright_excess": 0.0,
                "joint_limit_excess": 0.0,
                "positive_power_w": 4.0,
                "mean_absolute_human_torque_nm": 30.0,
                "mean_absolute_exo_torque_nm": 2.0,
                "torque_usage_cost": 0.01,
                "torque_cost": 0.02,
                "torque_overload": 0.1,
                "max_absolute_exo_torque_nm": 7.0,
                "jerk_cost": 0.03,
            },
            "target_speed_m_s": 1.0,
            "forward_speed_raw_m_s": 1.1,
            "forward_speed_filtered_m_s": 1.02,
            "pelvis_height_m": 0.9,
            "pelvis_pitch_rad": 0.02,
            "torque_overload": False,
            "max_absolute_exo_torque_nm": 7.0,
            "gait_phase": 0.25,
            "gait_period_steps": 50.0,
            "speed_curriculum_band_id": 1,
            "domain_randomization": {
                "enabled": 1.0,
                "action_delay_steps": 1.0,
            },
            "joint_q_rad": np.arange(4),
            "joint_dq_rad_s": np.arange(4) + 1,
            "exo_torque": np.arange(4) + 2,
            "exo_joint_power_w": np.arange(4) + 3,
        }
        metrics = collect_myoassist_metrics(info)
        self.assertEqual(metrics["myoassist_reward/effort"], 0.25)
        self.assertEqual(metrics["myoassist_human/gross_load_cost"], 1.1)
        self.assertEqual(metrics["myoassist_exo/max_abs_torque_nm"], 7.0)
        self.assertEqual(metrics["myoassist_exo/torque_usage_cost"], 0.01)
        self.assertEqual(metrics["myoassist_safety/torque_overload"], 0.0)
        self.assertEqual(metrics["myoassist_phase/value"], 0.25)
        self.assertEqual(metrics["myoassist_locomotion/speed_band_id"], 1.0)
        self.assertEqual(metrics["myoassist_randomization/enabled"], 1.0)
        for joint in JOINT_ORDER:
            self.assertIn(f"myoassist_joint/q_rad/{joint}", metrics)
            self.assertIn(f"myoassist_joint/exo_torque_nm/{joint}", metrics)


if __name__ == "__main__":
    unittest.main()
