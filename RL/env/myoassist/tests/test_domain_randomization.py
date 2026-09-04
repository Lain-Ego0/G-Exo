"""Tests for bounded deployment randomization."""

from __future__ import annotations

import unittest

import numpy as np
import mujoco

from RL.env.myoassist.domain_randomization import (
    DeploymentRandomizationConfig,
    DeploymentRandomizer,
)


def state() -> dict[str, np.ndarray]:
    return {
        "motor_q": np.arange(4, dtype=np.float32),
        "motor_dq": np.arange(4, dtype=np.float32) + 1.0,
        "imu_angular_velocity": np.ones((4, 3), dtype=np.float32),
        "imu_specific_force": np.full((4, 3), 9.8, dtype=np.float32),
    }


class DeploymentRandomizerTest(unittest.TestCase):
    def test_disabled_mode_is_exact_identity(self) -> None:
        randomizer = DeploymentRandomizer(
            DeploymentRandomizationConfig(enabled=False),
            torque_limit_nm=np.full(4, 8.0),
        )
        randomizer.reset(np.random.default_rng(7))
        randomized = randomizer.randomize_state(state())
        for name, value in state().items():
            np.testing.assert_allclose(randomized[name], value)
        np.testing.assert_allclose(randomizer.apply_torque(np.ones(4)), np.ones(4))

    def test_enabled_mode_is_seeded_and_bounded(self) -> None:
        config = DeploymentRandomizationConfig(
            enabled=True,
            max_action_delay_steps=0,
        )
        options = {
            "torque_limit_nm": np.full(4, 8.0),
            "torque_rate_limit_nm_s": np.full(4, 20.0),
            "control_dt": 0.02,
        }
        first = DeploymentRandomizer(config, **options)
        second = DeploymentRandomizer(config, **options)
        first.reset(np.random.default_rng(11))
        second.reset(np.random.default_rng(11))
        for name in state():
            np.testing.assert_allclose(
                first.randomize_state(state())[name],
                second.randomize_state(state())[name],
            )
        applied = first.apply_torque(np.full(4, 8.0))
        self.assertTrue(np.all(np.abs(applied) <= 8.0))
        self.assertTrue(np.all(np.abs(applied) <= 0.4 + 1.0e-7))
        self.assertTrue(np.all(np.abs(first.torque_gain - 1.0) <= 0.05))

    def test_one_step_delay_returns_previous_command(self) -> None:
        randomizer = DeploymentRandomizer(
            DeploymentRandomizationConfig(
                enabled=False,
                max_action_delay_steps=0,
            ),
            torque_limit_nm=np.full(4, 8.0),
        )
        randomizer.action_delay_steps = 1
        from collections import deque

        randomizer._torque_queue = deque(
            [np.zeros(4), np.zeros(4)],
            maxlen=2,
        )
        np.testing.assert_allclose(randomizer.apply_torque(np.ones(4)), 0.0)
        np.testing.assert_allclose(randomizer.apply_torque(np.full(4, 2.0)), 1.0)

    def test_dynamic_urdf_parameters_are_seeded_bounded_and_restored(self) -> None:
        model = mujoco.MjModel.from_xml_path(
            "RL/assets/myoassist/myoLeg22_2D_GEXO_URDF_DYNAMIC.xml"
        )
        data = mujoco.MjData(model)
        randomizer = DeploymentRandomizer(
            DeploymentRandomizationConfig(enabled=True),
            torque_limit_nm=np.full(4, 8.0),
            model=model,
            data=data,
        )
        nominal_mass = randomizer._nominal_body_mass.copy()
        nominal_inertia = randomizer._nominal_body_inertia.copy()
        randomizer.reset(np.random.default_rng(17))
        np.testing.assert_allclose(
            model.body_mass[randomizer._urdf_body_ids],
            nominal_mass * randomizer.urdf_inertial_scale,
        )
        np.testing.assert_allclose(
            model.body_inertia[randomizer._urdf_body_ids],
            nominal_inertia * randomizer.urdf_inertial_scale[:, None],
        )
        self.assertTrue(
            np.all(np.abs(randomizer.urdf_inertial_scale - 1.0) <= 0.05)
        )
        randomizer.config = DeploymentRandomizationConfig(enabled=False)
        randomizer.reset(np.random.default_rng(17))
        np.testing.assert_allclose(
            model.body_mass[randomizer._urdf_body_ids],
            nominal_mass,
        )
        np.testing.assert_allclose(
            model.body_inertia[randomizer._urdf_body_ids],
            nominal_inertia,
        )


if __name__ == "__main__":
    unittest.main()
