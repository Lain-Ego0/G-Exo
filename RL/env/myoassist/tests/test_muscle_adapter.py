"""Contract and sign tests for the MyoAssist muscle adapter."""

from __future__ import annotations

import hashlib
import unittest

import mujoco
import numpy as np

from RL.env.myoassist.model_builder import DEFAULT_PHYSICAL_OUTPUT_PATH
from RL.env.myoassist.muscle_adapter import (
    DEFAULT_ACTIVATION_HORIZON_S,
    MUSCLE_COUNT,
    MyoAssistMuscleAdapter,
    TARGET_JOINT_NAMES,
    TARGET_JOINT_SIGNS,
)


class MuscleAdapterTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.model = mujoco.MjModel.from_xml_path(
            str(DEFAULT_PHYSICAL_OUTPUT_PATH),
        )
        cls.model_hash = hashlib.sha256(
            DEFAULT_PHYSICAL_OUTPUT_PATH.read_bytes(),
        ).hexdigest()
        cls.target_dof_ids = np.asarray(
            [
                cls.model.jnt_dofadr[
                    mujoco.mj_name2id(
                        cls.model,
                        mujoco.mjtObj.mjOBJ_JOINT,
                        name,
                    )
                ]
                for name in TARGET_JOINT_NAMES
            ],
            dtype=np.int32,
        )

    def _make_data(
        self,
        *,
        exo_ctrl: np.ndarray | None = None,
    ) -> mujoco.MjData:
        data = mujoco.MjData(self.model)
        mujoco.mj_resetDataKeyframe(self.model, data, 0)
        data.act[:] = np.linspace(0.05, 0.75, MUSCLE_COUNT)
        data.ctrl[:MUSCLE_COUNT] = data.act
        if exo_ctrl is not None:
            data.ctrl[MUSCLE_COUNT:] = exo_ctrl
        mujoco.mj_forward(self.model, data)
        return data

    def _adapter(self, data: mujoco.MjData) -> MyoAssistMuscleAdapter:
        return MyoAssistMuscleAdapter(
            self.model,
            data,
            model_hash=self.model_hash,
        )

    def test_snapshot_shape_finite_order_and_provenance(self) -> None:
        data = self._make_data()
        adapter = self._adapter(data)
        snapshot = adapter.snapshot()

        expected_names = tuple(
            mujoco.mj_id2name(
                self.model,
                mujoco.mjtObj.mjOBJ_ACTUATOR,
                index,
            )
            for index in range(MUSCLE_COUNT)
        )
        self.assertEqual(adapter.muscle_names, expected_names)
        self.assertEqual(snapshot.model_hash, self.model_hash)
        self.assertEqual(snapshot.activation.shape, (MUSCLE_COUNT,))
        self.assertEqual(snapshot.moment_arm_m.shape, (MUSCLE_COUNT, 4))
        self.assertEqual(snapshot.muscle_force_n.shape, (MUSCLE_COUNT,))
        self.assertTrue(np.all(snapshot.target_mask))
        for value in (
            snapshot.activation,
            snapshot.activation_lower,
            snapshot.activation_upper,
            snapshot.moment_arm_m,
            snapshot.muscle_force_n,
            snapshot.active_force_gain_n,
            snapshot.passive_force_n,
        ):
            self.assertTrue(np.all(np.isfinite(value)))
        self.assertTrue(np.all(snapshot.muscle_force_n >= 0.0))

    def test_sparse_moment_reconstruction_and_protocol_signs(self) -> None:
        data = self._make_data()
        snapshot = self._adapter(data).snapshot()
        expected = np.zeros((MUSCLE_COUNT, 4), dtype=np.float64)

        for muscle_id in range(MUSCLE_COUNT):
            start = int(data.moment_rowadr[muscle_id])
            stop = start + int(data.moment_rownnz[muscle_id])
            columns = data.moment_colind[start:stop]
            values = data.actuator_moment[start:stop]
            for target_id, (dof_id, joint_sign) in enumerate(
                zip(self.target_dof_ids, TARGET_JOINT_SIGNS)
            ):
                matches = np.flatnonzero(columns == dof_id)
                raw_moment = 0.0 if matches.size == 0 else values[matches[0]]
                expected[muscle_id, target_id] = -raw_moment * joint_sign

        np.testing.assert_allclose(snapshot.moment_arm_m, expected, atol=0.0)
        raw_dense = np.zeros((MUSCLE_COUNT, self.model.nv))
        for muscle_id in range(MUSCLE_COUNT):
            start = int(data.moment_rowadr[muscle_id])
            stop = start + int(data.moment_rownnz[muscle_id])
            raw_dense[muscle_id, data.moment_colind[start:stop]] = (
                data.actuator_moment[start:stop]
            )
        np.testing.assert_allclose(
            snapshot.moment_arm_m[:, 1],
            raw_dense[:, self.target_dof_ids[1]],
            atol=0.0,
        )
        np.testing.assert_allclose(
            snapshot.moment_arm_m[:, 3],
            raw_dense[:, self.target_dof_ids[3]],
            atol=0.0,
        )

    def test_activation_bounds_follow_muscle_dynamics(self) -> None:
        data = self._make_data()
        adapter = self._adapter(data)
        snapshot = adapter.snapshot()
        physics_dt = float(self.model.opt.timestep)
        substeps = round(DEFAULT_ACTIVATION_HORIZON_S / physics_dt)

        endpoints = []
        for excitation in (0.0, 1.0):
            value = snapshot.activation.copy()
            for _ in range(substeps):
                derivative = np.asarray(
                    [
                        mujoco.mju_muscleDynamics(
                            excitation,
                            value[index],
                            self.model.actuator_dynprm[index, :3],
                        )
                        for index in range(MUSCLE_COUNT)
                    ]
                )
                value = np.clip(value + physics_dt * derivative, 0.0, 1.0)
            endpoints.append(value)

        np.testing.assert_allclose(
            snapshot.activation_lower,
            np.minimum(endpoints[0], snapshot.activation),
        )
        np.testing.assert_allclose(
            snapshot.activation_upper,
            np.maximum(endpoints[1], snapshot.activation),
        )

    def test_snapshot_is_immutable_and_force_model_resolves(self) -> None:
        snapshot = self._adapter(self._make_data()).snapshot()
        with self.assertRaises(ValueError):
            snapshot.activation[0] = 0.5
        with self.assertRaises(ValueError):
            snapshot.moment_arm_m[0, 0] = 0.0

        np.testing.assert_allclose(
            snapshot.resolved_muscle_force_n(),
            snapshot.muscle_force_n,
        )
        np.testing.assert_allclose(
            snapshot.resolved_muscle_force_n(snapshot.activation),
            snapshot.muscle_force_n,
        )

    def test_zero_exo_and_same_state_exo_control_do_not_pollute_snapshot(self) -> None:
        zero = self._adapter(self._make_data()).snapshot()
        controlled = self._adapter(
            self._make_data(exo_ctrl=np.asarray([3.0, -4.0, 5.0, -6.0])),
        ).snapshot()

        for name in (
            "activation",
            "activation_lower",
            "activation_upper",
            "moment_arm_m",
            "muscle_force_n",
            "active_force_gain_n",
            "passive_force_n",
        ):
            np.testing.assert_array_equal(
                getattr(controlled, name),
                getattr(zero, name),
            )

    def test_same_reset_state_is_deterministic(self) -> None:
        data = self._make_data()
        adapter = self._adapter(data)
        first = adapter.snapshot()

        data.qpos[:] += np.linspace(-0.01, 0.01, self.model.nq)
        data.act[:] = np.linspace(0.8, 0.2, MUSCLE_COUNT)
        data.ctrl[:] = 0.0
        mujoco.mj_forward(self.model, data)

        mujoco.mj_resetDataKeyframe(self.model, data, 0)
        data.act[:] = np.linspace(0.05, 0.75, MUSCLE_COUNT)
        data.ctrl[:MUSCLE_COUNT] = data.act
        mujoco.mj_forward(self.model, data)
        second = adapter.snapshot()

        for name in (
            "activation",
            "activation_lower",
            "activation_upper",
            "moment_arm_m",
            "muscle_force_n",
            "active_force_gain_n",
            "passive_force_n",
        ):
            np.testing.assert_array_equal(
                getattr(second, name),
                getattr(first, name),
            )


if __name__ == "__main__":
    unittest.main()
