"""Fast tests for deterministic MyoAssist human-policy composition."""

from __future__ import annotations

import unittest

import numpy as np

from RL.env.myoassist.human_runtime import (
    EXO_ACTION_DIM,
    HUMAN_ACTION_DIM,
    make_human_runtime,
)
from RL.env.myoassist.policy_transfer import FrozenHumanPolicy


class HumanRuntimeTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.environment = make_human_runtime(
            seed=7,
            max_episode_steps=50,
        )
        cls.policy = FrozenHumanPolicy(device="cpu")

    @classmethod
    def tearDownClass(cls) -> None:
        cls.environment.close()

    def test_repeated_reset_restores_full_state(self) -> None:
        options = {"reference_index": 0, "target_speed": 1.0}
        observation_a, info_a = self.environment.reset(seed=11, options=options)
        qpos_a = self.environment.sim.data.qpos.copy()
        qvel_a = self.environment.sim.data.qvel.copy()

        human_action = self.policy(observation_a)
        action = np.concatenate(
            (human_action, np.ones(EXO_ACTION_DIM, dtype=np.float32))
        )
        self.environment.step(action)

        observation_b, info_b = self.environment.reset(seed=11, options=options)
        np.testing.assert_array_equal(self.environment.sim.data.qpos, qpos_a)
        np.testing.assert_array_equal(self.environment.sim.data.qvel, qvel_a)
        np.testing.assert_array_equal(observation_b, observation_a)
        self.assertEqual(info_b, info_a)
        self.assertEqual(self.environment.sim.data.time, 0.0)

    def test_frozen_policy_and_combined_action_shapes(self) -> None:
        observation, _ = self.environment.reset(
            seed=13,
            options={"reference_index": 0, "target_speed": 1.0},
        )
        muscle_action = self.policy(observation)
        self.assertEqual(muscle_action.shape, (HUMAN_ACTION_DIM,))
        self.assertTrue(np.all(np.isfinite(muscle_action)))
        self.assertTrue(np.all(np.abs(muscle_action) <= 1.0))

        combined = np.concatenate(
            (muscle_action, np.zeros(EXO_ACTION_DIM, dtype=np.float32))
        )
        result = self.environment.step(combined)
        self.assertEqual(len(result), 5)
        self.assertTrue(np.all(np.isfinite(result[0])))

    def test_default_reset_uses_canonical_reference_state(self) -> None:
        indices = []
        for seed in range(5):
            _, info = self.environment.reset(seed=seed)
            indices.append(info["reference_index"])
        self.assertEqual(indices, [0] * 5)

    def test_imitation_termination_is_disabled_by_default(self) -> None:
        options = {"reference_index": 0, "target_speed": 1.0}
        observation, _ = self.environment.reset(seed=17, options=options)
        original_threshold = self.environment._out_of_trajectory_threshold
        try:
            self.environment._out_of_trajectory_threshold = 0.0
            action = np.concatenate(
                (
                    self.policy(observation),
                    np.zeros(EXO_ACTION_DIM, dtype=np.float32),
                )
            )
            _, _, terminated, _, _ = self.environment.step(action)
            self.assertFalse(terminated)
        finally:
            self.environment._out_of_trajectory_threshold = original_threshold

    def test_finish_preroll_resets_runtime_accounting(self) -> None:
        options = {"reference_index": 0, "target_speed": 1.0}
        observation, _ = self.environment.reset(seed=19, options=options)
        action = np.concatenate(
            (
                self.policy(observation),
                np.zeros(EXO_ACTION_DIM, dtype=np.float32),
            )
        )
        for _ in range(3):
            observation, _, _, _, _ = self.environment.step(action)
            action[:HUMAN_ACTION_DIM] = self.policy(observation)
        self.assertEqual(self.environment._step_count_per_episode, 3)

        self.environment.finish_preroll()

        self.assertEqual(self.environment._step_count_per_episode, 0)
        self.assertEqual(self.environment._r_heel_striking_value_buffer, [])
        self.assertEqual(self.environment._l_heel_striking_value_buffer, [])


if __name__ == "__main__":
    unittest.main()
