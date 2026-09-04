"""Tests for zero-exoskeleton human-policy adaptation and weight transfer."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import numpy as np
from stable_baselines3 import PPO

from RL.env.myoassist.human_adaptation import make_human_adaptation_env
from RL.env.myoassist.human_runtime import HUMAN_ACTION_DIM
from RL.env.myoassist.model_builder import TEACHER_INERTIA_PREFIX
from RL.env.myoassist.policy_transfer import (
    FrozenHumanPolicy,
    HUMAN_LOG_STD_INIT,
    make_human_ppo,
    transfer_released_human_weights,
)


class HumanAdaptationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.environment = make_human_adaptation_env(
            seed=3,
            max_episode_steps=20,
            evaluate=True,
        )
        cls.released_policy = FrozenHumanPolicy(device="cpu")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.environment.close()

    def test_physical_model_and_zero_exoskeleton_contract(self) -> None:
        model = self.environment.unwrapped.sim.model
        body_names = {
            model.body(body_id).name
            for body_id in range(model.nbody)
        }
        self.assertFalse(
            any(name.startswith(TEACHER_INERTIA_PREFIX) for name in body_names)
        )
        self.assertEqual(self.environment.action_space.shape, (HUMAN_ACTION_DIM,))

        observation, info = self.environment.reset(
            seed=5,
            options={"target_speed": 1.0, "reference_index": 0},
        )
        self.assertEqual(observation.shape, (44,))
        np.testing.assert_array_equal(info["adaptation_exo_torque_nm"], 0.0)

        result = self.environment.step(
            np.linspace(-1.0, 1.0, HUMAN_ACTION_DIM, dtype=np.float32)
        )
        np.testing.assert_array_equal(
            result[4]["adaptation_exo_torque_nm"],
            0.0,
        )
        np.testing.assert_array_equal(
            self.environment.last_combined_action[-4:],
            0.0,
        )
        np.testing.assert_array_equal(self.environment.last_exo_ctrl, 0.0)
        np.testing.assert_array_equal(
            self.environment.last_exo_actuator_force,
            0.0,
        )
        np.testing.assert_array_equal(
            self.environment.last_exo_generalized_force,
            0.0,
        )

    def test_fixed_speed_curriculum_only_changes_reset_target(self) -> None:
        environment = make_human_adaptation_env(
            seed=13,
            max_episode_steps=10,
            evaluate=False,
            min_target_speed_m_s=0.8,
            max_target_speed_m_s=1.25,
            default_target_speed_m_s=0.8,
        )
        try:
            _, info = environment.reset(seed=13)
            self.assertEqual(info["target_speed"], 0.8)
            np.testing.assert_array_equal(
                info["adaptation_exo_torque_nm"],
                0.0,
            )
        finally:
            environment.close()

    def test_adaptation_can_enable_four_joint_imitation(self) -> None:
        environment = make_human_adaptation_env(
            seed=17,
            max_episode_steps=10,
            evaluate=True,
            qpos_imitation_weight=0.12,
            qvel_imitation_weight=0.04,
        )
        try:
            rewards = environment.unwrapped._reward_keys_and_weights
            for joint in (
                "hip_flexion_l",
                "knee_angle_l",
                "hip_flexion_r",
                "knee_angle_r",
            ):
                self.assertEqual(rewards.qpos_imitation_rewards[joint], 0.12)
                self.assertEqual(rewards.qvel_imitation_rewards[joint], 0.04)
            self.assertAlmostEqual(
                environment.unwrapped.rwd_keys_wt["qpos_imitation_rewards"],
                0.48,
            )
            self.assertAlmostEqual(
                environment.unwrapped.rwd_keys_wt["qvel_imitation_rewards"],
                0.16,
            )
        finally:
            environment.close()

    def _make_transferred_model(self) -> PPO:
        target = make_human_ppo(
            self.environment,
            device="cpu",
            seed=7,
            n_steps=8,
            batch_size=8,
            n_epochs=1,
            verbose=0,
        )
        critic_before = {
            name: value.detach().cpu().numpy().copy()
            for name, value in (
                target.policy.policy_network.value_net.state_dict().items()
            )
        }
        report = transfer_released_human_weights(target, device="cpu")
        self.assertEqual(report["actor_max_abs_error"], 0.0)
        self.assertEqual(report["critic_max_abs_change"], 0.0)
        self.assertEqual(report["log_std_init"], HUMAN_LOG_STD_INIT)
        for name, value in target.policy.policy_network.value_net.state_dict().items():
            np.testing.assert_array_equal(
                value.detach().cpu().numpy(),
                critic_before[name],
            )
        np.testing.assert_array_equal(
            target.policy.log_std.detach().cpu().numpy(),
            HUMAN_LOG_STD_INIT,
        )
        return target

    def test_released_actor_transfer_is_deterministically_exact(self) -> None:
        target = self._make_transferred_model()
        observation, _ = self.environment.reset(
            seed=9,
            options={"target_speed": 1.0, "reference_index": 0},
        )
        expected_action = self.released_policy(observation)
        actual_action, _ = target.predict(observation, deterministic=True)
        np.testing.assert_array_equal(actual_action, expected_action)

    def test_transferred_model_save_and_reload(self) -> None:
        target = self._make_transferred_model()

        observation, _ = self.environment.reset(
            seed=9,
            options={"target_speed": 1.0, "reference_index": 0},
        )
        action_before, _ = target.predict(observation, deterministic=True)

        with tempfile.TemporaryDirectory() as temporary_directory:
            checkpoint = Path(temporary_directory) / "adapted_human"
            target.save(checkpoint)
            reloaded = PPO.load(
                checkpoint.with_suffix(".zip"),
                env=self.environment,
                device="cpu",
            )
            action_after, _ = reloaded.predict(
                observation,
                deterministic=True,
            )

        np.testing.assert_array_equal(action_after, action_before)

    def test_tiny_ppo_learn(self) -> None:
        target = self._make_transferred_model()
        target.learn(total_timesteps=8, progress_bar=False)
        self.assertGreaterEqual(target.num_timesteps, 8)
        np.testing.assert_array_equal(self.environment.last_exo_ctrl, 0.0)
        np.testing.assert_array_equal(
            self.environment.last_exo_actuator_force,
            0.0,
        )
        np.testing.assert_array_equal(
            self.environment.last_exo_generalized_force,
            0.0,
        )


if __name__ == "__main__":
    unittest.main()
