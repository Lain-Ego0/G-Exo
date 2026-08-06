"""Contract tests for the MyoAssist deployment-sensor adapter."""

from __future__ import annotations

import unittest

import numpy as np

from RL.env.myoassist.human_runtime import make_human_runtime
from RL.env.myoassist.sensor_adapter import (
    IMU_NAMES,
    JOINT_SPECS,
    MyoAssistSensorAdapter,
)


class SensorAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.environment = make_human_runtime(
            seed=3,
            max_episode_steps=10,
        )
        cls.adapter = MyoAssistSensorAdapter()

    @classmethod
    def tearDownClass(cls) -> None:
        cls.environment.close()

    def test_shape_order_sign_and_determinism(self) -> None:
        options = {"reference_index": 0, "target_speed": 1.25}
        self.environment.reset(seed=4, options=options)
        first = self.adapter.read_state(self.environment)
        second = self.adapter.read_state(self.environment)

        self.assertEqual(first["motor_q"].shape, (4,))
        self.assertEqual(first["motor_dq"].shape, (4,))
        self.assertEqual(first["imu_angular_velocity"].shape, (4, 3))
        self.assertEqual(first["imu_specific_force"].shape, (4, 3))
        for key in first:
            np.testing.assert_array_equal(first[key], second[key])

        expected_q = np.asarray(
            [
                spec.sign
                * float(self.environment.sim.data.joint(spec.name).qpos[0])
                for spec in JOINT_SPECS
            ],
            dtype=np.float32,
        )
        expected_dq = np.asarray(
            [
                spec.sign
                * float(self.environment.sim.data.joint(spec.name).qvel[0])
                for spec in JOINT_SPECS
            ],
            dtype=np.float32,
        )
        np.testing.assert_array_equal(first["motor_q"], expected_q)
        np.testing.assert_array_equal(first["motor_dq"], expected_dq)

    def test_imu_order_matches_generated_sensor_names(self) -> None:
        self.environment.reset(
            seed=5,
            options={"reference_index": 0, "target_speed": 1.25},
        )
        state = self.adapter.read_state(self.environment)
        for index, name in enumerate(IMU_NAMES):
            np.testing.assert_allclose(
                state["imu_angular_velocity"][index],
                self.environment.sim.data.sensor(
                    f"gexo_imu_{name}_gyro"
                ).data,
                atol=1e-7,
                rtol=1e-7,
            )
            np.testing.assert_allclose(
                state["imu_specific_force"][index],
                self.environment.sim.data.sensor(
                    f"gexo_imu_{name}_accelerometer"
                ).data,
                atol=1e-7,
                rtol=1e-7,
            )


if __name__ == "__main__":
    unittest.main()
