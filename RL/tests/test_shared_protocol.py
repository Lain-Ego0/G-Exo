"""Tests for runtime32, Actor160 and torque safety contracts."""

from __future__ import annotations

import unittest

import numpy as np

from RL.env.actor_observation import (
    ACTOR_OBSERVATION_DIM,
    ActorObservationBuilder,
    build_tcn_delta16,
    runtime32_to_phase12_interleaved,
)
from RL.env.sensors import FRAME_DIM, SENSOR_DIM, SensorReader
from RL.env.torque import TorqueActuator


class SharedProtocolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "motor_q": np.asarray([0.1, 0.2, 0.3, 0.4]),
            "motor_dq": np.asarray([1.1, 1.2, 1.3, 1.4]),
            "imu_angular_velocity": np.arange(12).reshape(4, 3) + 2.0,
            "imu_specific_force": np.arange(12).reshape(4, 3) + 20.0,
        }

    def test_sensor_reader_keeps_legacy_36_dimensional_output(self) -> None:
        reader = SensorReader()
        action = np.asarray([0.1, -0.2, 0.3, -0.4], dtype=np.float32)
        runtime32 = reader.read_runtime32(state=self.state)
        reader.reset(seed=0)
        legacy36 = reader.read(state=self.state, previous_action=action)

        self.assertEqual(runtime32.shape, (SENSOR_DIM,))
        self.assertEqual(legacy36.shape, (FRAME_DIM,))
        np.testing.assert_array_equal(legacy36[:SENSOR_DIM], runtime32)
        np.testing.assert_array_equal(legacy36[SENSOR_DIM:], action)

    def test_runtime_to_phase_order_uses_index_sentinel(self) -> None:
        runtime = np.arange(32, dtype=np.float32)
        converted = runtime32_to_phase12_interleaved(runtime)
        expected_indices = np.asarray(
            list(range(8))
            + [8, 9, 10, 20, 21, 22]
            + [11, 12, 13, 23, 24, 25]
            + [14, 15, 16, 26, 27, 28]
            + [17, 18, 19, 29, 30, 31],
            dtype=np.float32,
        )
        np.testing.assert_array_equal(converted, expected_indices)

    def test_actor_history_uses_real_frames_oldest_to_newest(self) -> None:
        builder = ActorObservationBuilder(
            frame_scale=np.ones(36, dtype=np.float32),
            clip=100.0,
        )
        with self.assertRaises(RuntimeError):
            builder.build(np.zeros(16, dtype=np.float32))

        for value in range(1, 5):
            builder.append(
                np.full(32, value, dtype=np.float32),
                np.full(4, value / 10.0, dtype=np.float32),
            )
        history = builder.history144().reshape(4, 36)
        for index, value in enumerate(range(1, 5)):
            np.testing.assert_array_equal(history[index, :32], value)
            np.testing.assert_allclose(history[index, 32:], value / 10.0)
        observation = builder.build(np.arange(16, dtype=np.float32))
        self.assertEqual(observation.shape, (ACTOR_OBSERVATION_DIM,))
        np.testing.assert_array_equal(observation[-16:], np.arange(16))

        builder.reset()
        self.assertFalse(builder.ready)
        self.assertEqual(builder.history_size, 0)

    def test_delta16_order_is_q_dq_at_five_then_ten_steps(self) -> None:
        current_q = np.asarray([1.0, 2.0, 3.0, 4.0])
        current_dq = np.asarray([5.0, 6.0, 7.0, 8.0])
        prediction = np.asarray(
            [
                [2, 4, 6, 8, 10, 12, 14, 16],
                [3, 6, 9, 12, 15, 18, 21, 24],
            ],
            dtype=np.float32,
        )
        expected = np.asarray(
            [
                1, 2, 3, 4,
                5, 6, 7, 8,
                2, 4, 6, 8,
                10, 12, 14, 16,
            ],
            dtype=np.float32,
        )
        np.testing.assert_array_equal(
            build_tcn_delta16(prediction, current_q, current_dq),
            expected,
        )

    def test_default_action_scale_is_elementwise_legacy_equivalent(self) -> None:
        limit = np.asarray([17.0, 16.0, 15.0, 14.0], dtype=np.float32)
        rate = np.asarray([50.0, 60.0, 70.0, 80.0], dtype=np.float32)
        implicit = TorqueActuator(
            limit,
            rate,
            control_dt=0.02,
            filter_time_constant_s=0.03,
        )
        explicit = TorqueActuator(
            limit,
            rate,
            action_torque_scale_nm=limit,
            control_dt=0.02,
            filter_time_constant_s=0.03,
        )
        actions = (
            np.asarray([1.0, -1.0, 0.5, -0.5]),
            np.asarray([-0.2, 0.3, -0.4, 0.5]),
            np.asarray([2.0, -2.0, 0.0, 0.1]),
        )
        for action in actions:
            np.testing.assert_array_equal(
                implicit.process(action),
                explicit.process(action),
            )

    def test_independent_action_scale_precedes_hard_limit(self) -> None:
        actuator = TorqueActuator(
            torque_limit_nm=np.full(4, 17.0),
            torque_rate_limit_nm_s=np.full(4, 1.0e6),
            action_torque_scale_nm=np.asarray([2.0, 3.0, 4.0, 5.0]),
        )
        np.testing.assert_array_equal(
            actuator.process(np.ones(4)),
            [2.0, 3.0, 4.0, 5.0],
        )
        with self.assertRaises(ValueError):
            TorqueActuator(
                torque_limit_nm=np.full(4, 5.0),
                torque_rate_limit_nm_s=np.full(4, 100.0),
                action_torque_scale_nm=np.full(4, 6.0),
            )


if __name__ == "__main__":
    unittest.main()
