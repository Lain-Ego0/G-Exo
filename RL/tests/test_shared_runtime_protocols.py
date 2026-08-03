from __future__ import annotations

import unittest

import numpy as np

from RL.env.actor_observation import (
    ACTOR_HISTORY_DIM,
    ACTOR_OBSERVATION_DIM,
    ActorObservationBuilder,
    build_actor_frame,
    build_tcn_delta16,
    runtime32_to_phase12_interleaved,
)
from RL.env.sensors import FRAME_DIM, SENSOR_DIM, SensorReader
from RL.env.torque import TorqueActuator


class SharedSensorProtocolTest(unittest.TestCase):
    def setUp(self) -> None:
        self.state = {
            "motor_q": np.asarray([0.1, 0.2, 0.3, 0.4], dtype=np.float32),
            "motor_dq": np.asarray([1.1, 1.2, 1.3, 1.4], dtype=np.float32),
            "imu_angular_velocity": np.arange(12, dtype=np.float32).reshape(4, 3),
            "imu_specific_force": np.arange(20, 32, dtype=np.float32).reshape(4, 3),
        }
        self.reader = SensorReader(
            gyro_limit_rad_s=100.0,
            specific_force_limit_m_s2=100.0,
        )

    def test_runtime32_and_legacy36_preserve_bank_order(self) -> None:
        runtime = self.reader.read_runtime32(state=self.state)
        expected_runtime = np.concatenate(
            (
                self.state["motor_q"],
                self.state["motor_dq"],
                self.state["imu_angular_velocity"].reshape(-1),
                self.state["imu_specific_force"].reshape(-1),
            )
        ).astype(np.float32)

        self.assertEqual(SENSOR_DIM, 32)
        self.assertEqual(runtime.shape, (32,))
        self.assertEqual(runtime.dtype, np.float32)
        np.testing.assert_array_equal(runtime, expected_runtime)

        previous_action = np.asarray([0.5, -0.5, 0.25, -0.25], dtype=np.float32)
        legacy = self.reader.read(
            state=self.state,
            previous_action=previous_action,
        )
        self.assertEqual(FRAME_DIM, 36)
        self.assertEqual(legacy.shape, (36,))
        np.testing.assert_array_equal(legacy[:32], expected_runtime)
        np.testing.assert_array_equal(legacy[32:], previous_action)

    def test_phase12_conversion_interleaves_each_imu_gyro_and_force(self) -> None:
        runtime = np.arange(32, dtype=np.float32)
        converted = runtime32_to_phase12_interleaved(runtime)
        expected = np.concatenate(
            (
                runtime[:8],
                *(
                    np.concatenate(
                        (runtime[8 + 3 * imu : 11 + 3 * imu],
                         runtime[20 + 3 * imu : 23 + 3 * imu])
                    )
                    for imu in range(4)
                ),
            )
        )

        self.assertEqual(converted.shape, (32,))
        np.testing.assert_array_equal(converted, expected)


class SharedActorObservationProtocolTest(unittest.TestCase):
    def test_four_real_frames_and_explicit_delta_form_actor160(self) -> None:
        builder = ActorObservationBuilder(
            frame_scale=np.ones(36, dtype=np.float32),
            clip=1000.0,
        )
        expected_frames = []
        for frame_index in range(4):
            sensor = np.arange(32, dtype=np.float32) + 40.0 * frame_index
            action = np.arange(4, dtype=np.float32) + 4.0 * frame_index
            expected_frames.append(build_actor_frame(sensor, action))
            builder.append(sensor, action)
            if frame_index < 3:
                self.assertFalse(builder.ready)
                with self.assertRaises(RuntimeError):
                    builder.build(np.zeros(16, dtype=np.float32))

        current_q = np.asarray([1.0, 2.0, 3.0, 4.0], dtype=np.float32)
        current_dq = np.asarray([5.0, 6.0, 7.0, 8.0], dtype=np.float32)
        prediction = np.asarray(
            [
                [2.0, 4.0, 6.0, 8.0, 10.0, 12.0, 14.0, 16.0],
                [0.0, 1.0, 2.0, 3.0, 4.0, 3.0, 2.0, 1.0],
            ],
            dtype=np.float32,
        )
        delta = build_tcn_delta16(prediction, current_q, current_dq)
        expected_delta = np.concatenate(
            (
                prediction[0, :4] - current_q,
                prediction[0, 4:] - current_dq,
                prediction[1, :4] - current_q,
                prediction[1, 4:] - current_dq,
            )
        )
        observation = builder.build(delta)

        self.assertTrue(builder.ready)
        self.assertEqual(builder.history_size, 4)
        self.assertEqual(builder.history144().shape, (ACTOR_HISTORY_DIM,))
        self.assertEqual(observation.shape, (ACTOR_OBSERVATION_DIM,))
        np.testing.assert_array_equal(
            observation[:ACTOR_HISTORY_DIM],
            np.concatenate(expected_frames),
        )
        np.testing.assert_array_equal(observation[ACTOR_HISTORY_DIM:], expected_delta)

    def test_history_is_a_four_real_frame_sliding_window(self) -> None:
        builder = ActorObservationBuilder(
            frame_scale=np.ones(36, dtype=np.float32),
            clip=1000.0,
        )
        frames = []
        for frame_index in range(5):
            sensor = np.full(32, frame_index, dtype=np.float32)
            action = np.full(4, -frame_index, dtype=np.float32)
            frames.append(build_actor_frame(sensor, action))
            builder.append(sensor, action)

        self.assertEqual(builder.history_size, 4)
        np.testing.assert_array_equal(
            builder.history144(),
            np.concatenate(frames[1:]),
        )


class SharedTorqueProtocolTest(unittest.TestCase):
    def test_default_action_scale_reaches_but_never_exceeds_hard_limit(self) -> None:
        limits = np.asarray([10.0, 20.0, 30.0, 40.0], dtype=np.float32)
        actuator = TorqueActuator(
            torque_limit_nm=limits,
            torque_rate_limit_nm_s=np.full(4, 10000.0, dtype=np.float32),
            control_dt=0.1,
        )

        np.testing.assert_array_equal(actuator.action_torque_scale_nm, limits)
        output = actuator.process(
            np.asarray([2.0, -2.0, 0.5, -0.5], dtype=np.float32)
        )
        np.testing.assert_array_equal(
            output,
            np.asarray([10.0, -20.0, 15.0, -20.0], dtype=np.float32),
        )
        self.assertTrue(np.all(np.abs(output) <= limits))

    def test_optional_scale_retains_rate_limit_and_low_pass_order(self) -> None:
        actuator = TorqueActuator(
            torque_limit_nm=np.full(4, 10.0, dtype=np.float32),
            torque_rate_limit_nm_s=np.full(4, 20.0, dtype=np.float32),
            action_torque_scale_nm=np.full(4, 8.0, dtype=np.float32),
            control_dt=0.1,
            filter_time_constant_s=0.1,
        )
        action = np.asarray([1.0, -1.0, 0.5, -0.5], dtype=np.float32)

        first = actuator.process(action)
        second = actuator.process(action)

        np.testing.assert_allclose(first, [1.0, -1.0, 1.0, -1.0], rtol=0.0, atol=1e-7)
        np.testing.assert_allclose(second, [2.5, -2.5, 2.5, -2.5], rtol=0.0, atol=1e-7)
        self.assertTrue(np.all(np.abs(second) <= actuator.torque_limit_nm))


if __name__ == "__main__":
    unittest.main()
