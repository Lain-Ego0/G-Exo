"""Contract tests for the 22-muscle, four-joint G-Exo model."""

from __future__ import annotations

import tempfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path

import mujoco
import numpy as np

from RL.env.myoassist.model_builder import (
    DEFAULT_COMPAT_OUTPUT_PATH,
    DEFAULT_COMPAT_SOURCE_PATH,
    DEFAULT_OUTPUT_PATH,
    DEFAULT_PHYSICAL_OUTPUT_PATH,
    DEFAULT_PHYSICAL_SOURCE_PATH,
    DEFAULT_SOURCE_PATH,
    DEFAULT_URDF_DYNAMIC_OUTPUT_PATH,
    DEFAULT_URDF_OUTPUT_PATH,
    DYNAMIC_EXO_ACTUATORS,
    EXO_ACTUATORS,
    IMU_SPECS,
    LEGACY_EXO_BODY_NAMES,
    LEGACY_EXO_MESH_NAMES,
    MUSCLE_ACTUATOR_COUNT,
    OLD_ANKLE_ACTUATOR_NAMES,
    PHYSICAL_VARIANT,
    TEACHER_INERTIA_PREFIX,
    TEACHER_COMPAT_VARIANT,
    TORQUE_LIMIT_NM,
    URDF_IMU_SPECS,
    URDF_DYNAMIC_VARIANT,
    URDF_RIGID_VARIANT,
    build_model,
)
from RL.env.myoassist.urdf_attachment import (
    LINK_ATTACHMENTS,
    URDF_IMU_MOUNTS,
    CUFF_ATTACHMENTS,
    CUFF_SOLIMP,
    CUFF_SOLREF,
    HUMAN_JOINT_NAMES,
    cuff_equality_name,
    dynamic_body_name,
    model_has_dynamic_gexo,
    model_has_rigid_gexo,
    rigid_body_name,
)


def _names(model: mujoco.MjModel, object_type: mujoco.mjtObj, count: int) -> list[str]:
    return [
        mujoco.mj_id2name(model, object_type, index)
        for index in range(count)
    ]


def _exo_generalized_force(
    model: mujoco.MjModel,
    data: mujoco.MjData,
) -> np.ndarray:
    generalized_force = np.zeros(model.nv)
    for actuator_id in range(MUSCLE_ACTUATOR_COUNT, model.nu):
        row_start = int(data.moment_rowadr[actuator_id])
        row_stop = row_start + int(data.moment_rownnz[actuator_id])
        columns = data.moment_colind[row_start:row_stop]
        moments = data.actuator_moment[row_start:row_stop]
        generalized_force[columns] += (
            moments * data.actuator_force[actuator_id]
        )
    return generalized_force


def _forward_with_pulse(
    model: mujoco.MjModel,
    exo_index: int,
    torque_nm: float,
) -> mujoco.MjData:
    data = mujoco.MjData(model)
    mujoco.mj_resetDataKeyframe(model, data, 0)
    data.ctrl.fill(0.0)
    data.ctrl[MUSCLE_ACTUATOR_COUNT + exo_index] = torque_nm
    mujoco.mj_forward(model, data)
    return data


class ModelBuilderTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.source_model = mujoco.MjModel.from_xml_path(
            str(DEFAULT_PHYSICAL_SOURCE_PATH),
        )
        cls.compat_source_model = mujoco.MjModel.from_xml_path(
            str(DEFAULT_COMPAT_SOURCE_PATH),
        )
        cls.model = mujoco.MjModel.from_xml_path(
            str(DEFAULT_PHYSICAL_OUTPUT_PATH),
        )
        cls.compat_model = mujoco.MjModel.from_xml_path(
            str(DEFAULT_COMPAT_OUTPUT_PATH),
        )
        cls.urdf_model = mujoco.MjModel.from_xml_path(
            str(DEFAULT_URDF_OUTPUT_PATH),
        )
        cls.dynamic_urdf_model = mujoco.MjModel.from_xml_path(
            str(DEFAULT_URDF_DYNAMIC_OUTPUT_PATH),
        )

    def test_physical_builder_compiles_from_another_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "generated.xml"
            build_model(DEFAULT_PHYSICAL_SOURCE_PATH, output)
            model = mujoco.MjModel.from_xml_path(str(output))
        self.assertEqual(
            (model.nq, model.nv, model.nu, model.na),
            (53, 53, 26, 22),
        )

    def test_compat_builder_output_compiles_from_another_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            output = Path(directory) / "generated.xml"
            build_model(
                DEFAULT_COMPAT_SOURCE_PATH,
                output,
                variant=TEACHER_COMPAT_VARIANT,
            )
            model = mujoco.MjModel.from_xml_path(str(output))
        self.assertEqual(
            (model.nq, model.nv, model.nu, model.na),
            (53, 53, 26, 22),
        )

    def test_generation_is_deterministic_for_both_variants(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            for variant in (
                PHYSICAL_VARIANT,
                TEACHER_COMPAT_VARIANT,
                URDF_RIGID_VARIANT,
                URDF_DYNAMIC_VARIANT,
            ):
                output = Path(directory) / f"{variant}.xml"
                build_model(output_path=output, variant=variant)
                first = output.read_bytes()
                build_model(output_path=output, variant=variant)
                self.assertEqual(output.read_bytes(), first)

    def test_physical_asset_is_the_default(self) -> None:
        self.assertEqual(DEFAULT_SOURCE_PATH, DEFAULT_PHYSICAL_SOURCE_PATH)
        self.assertEqual(DEFAULT_OUTPUT_PATH, DEFAULT_PHYSICAL_OUTPUT_PATH)
        self.assertEqual(DEFAULT_OUTPUT_PATH.name, "myoLeg22_2D_GEXO.xml")
        self.assertNotEqual(DEFAULT_OUTPUT_PATH, DEFAULT_COMPAT_OUTPUT_PATH)
        self.assertLess(
            float(self.model.body_mass.sum()),
            float(self.compat_model.body_mass.sum()),
        )

    def test_dimensions_and_actuator_order(self) -> None:
        self.assertEqual(
            (self.model.nq, self.model.nv, self.model.nu, self.model.na),
            (53, 53, 26, 22),
        )

        source_names = _names(
            self.source_model,
            mujoco.mjtObj.mjOBJ_ACTUATOR,
            MUSCLE_ACTUATOR_COUNT,
        )
        generated_names = _names(
            self.model,
            mujoco.mjtObj.mjOBJ_ACTUATOR,
            self.model.nu,
        )
        self.assertEqual(
            generated_names[:MUSCLE_ACTUATOR_COUNT],
            source_names,
        )
        self.assertEqual(
            generated_names[MUSCLE_ACTUATOR_COUNT:],
            [spec.name for spec in EXO_ACTUATORS],
        )
        self.assertTrue(
            set(OLD_ANKLE_ACTUATOR_NAMES).isdisjoint(generated_names),
        )

        compat_names = _names(
            self.compat_model,
            mujoco.mjtObj.mjOBJ_ACTUATOR,
            self.compat_model.nu,
        )
        self.assertEqual(compat_names, generated_names)
        self.assertEqual(
            (
                self.urdf_model.nq,
                self.urdf_model.nv,
                self.urdf_model.nu,
                self.urdf_model.na,
            ),
            (53, 53, 26, 22),
        )

    def test_muscle_actuator_definitions_are_unchanged(self) -> None:
        path_pairs = (
            (DEFAULT_PHYSICAL_SOURCE_PATH, DEFAULT_PHYSICAL_OUTPUT_PATH),
            (DEFAULT_COMPAT_SOURCE_PATH, DEFAULT_COMPAT_OUTPUT_PATH),
        )
        for source_path, output_path in path_pairs:
            source_actuators = list(
                ET.parse(source_path).getroot().find("actuator")
            )[:MUSCLE_ACTUATOR_COUNT]
            generated_actuators = list(
                ET.parse(output_path).getroot().find("actuator")
            )[:MUSCLE_ACTUATOR_COUNT]
            source_definitions = [
                (element.tag, element.attrib)
                for element in source_actuators
            ]
            generated_definitions = [
                (element.tag, element.attrib)
                for element in generated_actuators
            ]
            self.assertEqual(generated_definitions, source_definitions)

    def test_physical_asset_has_no_legacy_or_teacher_inertia(self) -> None:
        root = ET.parse(DEFAULT_PHYSICAL_OUTPUT_PATH).getroot()
        bodies = list(root.iter("body"))
        body_names = {element.get("name") for element in bodies}
        mesh_names = {
            element.get("name")
            for element in root.iter("mesh")
        }
        self.assertTrue(set(LEGACY_EXO_BODY_NAMES).isdisjoint(body_names))
        self.assertTrue(set(LEGACY_EXO_MESH_NAMES).isdisjoint(mesh_names))

        compatibility_names = {
            f"{TEACHER_INERTIA_PREFIX}{name}"
            for name in LEGACY_EXO_BODY_NAMES
        }
        self.assertTrue(compatibility_names.isdisjoint(body_names))
        self.assertEqual(self.model.nbody, self.source_model.nbody)
        np.testing.assert_allclose(
            self.model.body_mass,
            self.source_model.body_mass,
            atol=0.0,
            rtol=0.0,
        )
        np.testing.assert_allclose(
            self.model.body_inertia,
            self.source_model.body_inertia,
            atol=0.0,
            rtol=0.0,
        )

    def test_compat_asset_has_only_invisible_teacher_inertia(self) -> None:
        root = ET.parse(DEFAULT_COMPAT_OUTPUT_PATH).getroot()
        bodies = list(root.iter("body"))
        body_names = {element.get("name") for element in bodies}
        mesh_names = {element.get("name") for element in root.iter("mesh")}
        compatibility_names = {
            f"{TEACHER_INERTIA_PREFIX}{name}"
            for name in LEGACY_EXO_BODY_NAMES
        }
        compatibility_bodies = [
            body for body in bodies if body.get("name") in compatibility_names
        ]
        self.assertTrue(set(LEGACY_EXO_BODY_NAMES).isdisjoint(body_names))
        self.assertTrue(set(LEGACY_EXO_MESH_NAMES).isdisjoint(mesh_names))
        self.assertEqual({body.get("name") for body in compatibility_bodies}, compatibility_names)
        self.assertTrue(
            all(body.find("inertial") is not None for body in compatibility_bodies)
        )
        self.assertTrue(
            all(body.find("geom") is None for body in compatibility_bodies)
        )
        self.assertEqual(self.compat_model.nbody, self.compat_source_model.nbody)
        np.testing.assert_allclose(
            self.compat_model.body_mass,
            self.compat_source_model.body_mass,
            atol=0.0,
            rtol=0.0,
        )
        np.testing.assert_allclose(
            self.compat_model.body_inertia,
            self.compat_source_model.body_inertia,
            atol=0.0,
            rtol=0.0,
        )

    def test_generated_asset_paths_are_relative_and_resolvable(self) -> None:
        for output_path in (
            DEFAULT_PHYSICAL_OUTPUT_PATH,
            DEFAULT_COMPAT_OUTPUT_PATH,
            DEFAULT_URDF_OUTPUT_PATH,
            DEFAULT_URDF_DYNAMIC_OUTPUT_PATH,
        ):
            root = ET.parse(output_path).getroot()
            references = [
                element.get("file")
                for element in root.iter()
                if element.get("file") is not None
            ]
            self.assertGreater(len(references), 0)
            for reference in references:
                self.assertFalse(Path(reference).is_absolute())
                self.assertTrue((output_path.parent / reference).is_file())

    def test_four_actuator_joint_range_and_gear_contract(self) -> None:
        for model in (self.model, self.compat_model, self.urdf_model):
            for offset, spec in enumerate(EXO_ACTUATORS):
                actuator_id = MUSCLE_ACTUATOR_COUNT + offset
                joint_id = int(model.actuator_trnid[actuator_id, 0])
                joint_name = mujoco.mj_id2name(
                    model,
                    mujoco.mjtObj.mjOBJ_JOINT,
                    joint_id,
                )

                self.assertEqual(joint_name, spec.joint)
                self.assertEqual(model.actuator_ctrllimited[actuator_id], 1)
                np.testing.assert_allclose(
                    model.actuator_ctrlrange[actuator_id],
                    [-TORQUE_LIMIT_NM, TORQUE_LIMIT_NM],
                    atol=0.0,
                    rtol=0.0,
                )
                np.testing.assert_allclose(
                    model.actuator_gear[actuator_id],
                    [spec.gear, 0.0, 0.0, 0.0, 0.0, 0.0],
                    atol=0.0,
                    rtol=0.0,
                )

    def test_four_virtual_imus_have_local_gyro_and_accelerometer(self) -> None:
        for model in (self.model, self.compat_model):
            data = mujoco.MjData(model)
            mujoco.mj_resetDataKeyframe(model, data, 0)
            mujoco.mj_forward(model, data)

            for spec in IMU_SPECS:
                site_name = f"gexo_imu_{spec.name}"
                site_id = mujoco.mj_name2id(
                    model,
                    mujoco.mjtObj.mjOBJ_SITE,
                    site_name,
                )
                body_id = mujoco.mj_name2id(
                    model,
                    mujoco.mjtObj.mjOBJ_BODY,
                    spec.body,
                )
                self.assertGreaterEqual(site_id, 0)
                self.assertEqual(int(model.site_bodyid[site_id]), body_id)

                for suffix in ("gyro", "accelerometer"):
                    values = data.sensor(f"{site_name}_{suffix}").data
                    self.assertEqual(values.shape, (3,))
                    self.assertTrue(np.all(np.isfinite(values)))

    def test_urdf_mass_inertia_and_link_aligned_imus_are_present(self) -> None:
        self.assertTrue(model_has_rigid_gexo(self.urdf_model))
        self.assertEqual(self.urdf_model.nbody, self.source_model.nbody + 5)
        self.assertAlmostEqual(
            float(self.urdf_model.body_mass.sum() - self.model.body_mass.sum()),
            3.09834816165551,
            places=10,
        )
        expected_parent = {
            spec.link: spec.human_body for spec in LINK_ATTACHMENTS
        }
        for link_name, human_body in expected_parent.items():
            body_id = mujoco.mj_name2id(
                self.urdf_model,
                mujoco.mjtObj.mjOBJ_BODY,
                rigid_body_name(link_name),
            )
            parent_name = mujoco.mj_id2name(
                self.urdf_model,
                mujoco.mjtObj.mjOBJ_BODY,
                int(self.urdf_model.body_parentid[body_id]),
            )
            self.assertEqual(parent_name, human_body)

        mounts = {mount.name: mount for mount in URDF_IMU_MOUNTS}
        for spec in URDF_IMU_SPECS:
            site_id = mujoco.mj_name2id(
                self.urdf_model,
                mujoco.mjtObj.mjOBJ_SITE,
                f"gexo_imu_{spec.name}",
            )
            body_name = mujoco.mj_id2name(
                self.urdf_model,
                mujoco.mjtObj.mjOBJ_BODY,
                int(self.urdf_model.site_bodyid[site_id]),
            )
            self.assertEqual(body_name, spec.body)
            np.testing.assert_allclose(
                self.urdf_model.site_pos[site_id],
                mounts[spec.name].position,
                atol=1.0e-12,
                rtol=0.0,
            )
            np.testing.assert_allclose(
                self.urdf_model.site_quat[site_id],
                [1.0, 0.0, 0.0, 0.0],
                atol=0.0,
                rtol=0.0,
            )

        data = mujoco.MjData(self.urdf_model)
        mujoco.mj_resetDataKeyframe(self.urdf_model, data, 0)
        mujoco.mj_forward(self.urdf_model, data)
        for mount in URDF_IMU_MOUNTS:
            site_id = mujoco.mj_name2id(
                self.urdf_model,
                mujoco.mjtObj.mjOBJ_SITE,
                f"gexo_imu_{mount.name}",
            )
            np.testing.assert_allclose(
                data.site_xmat[site_id].reshape(3, 3),
                np.eye(3),
                atol=3.0e-4,
                rtol=0.0,
            )

    def test_dynamic_urdf_uses_four_hinges_and_eight_stiff_cuff_points(self) -> None:
        model = self.dynamic_urdf_model
        self.assertTrue(model_has_dynamic_gexo(model))
        self.assertEqual(
            (model.nq, model.nv, model.nu, model.na, model.nbody, model.neq),
            (
                self.source_model.nq + 4,
                self.source_model.nv + 4,
                self.source_model.nu + 4,
                self.source_model.na,
                self.source_model.nbody + 5,
                self.source_model.neq + len(CUFF_ATTACHMENTS),
            ),
        )
        for offset, spec in enumerate(DYNAMIC_EXO_ACTUATORS):
            actuator_id = MUSCLE_ACTUATOR_COUNT + offset
            joint_id = int(model.actuator_trnid[actuator_id, 0])
            self.assertEqual(
                mujoco.mj_id2name(model, mujoco.mjtObj.mjOBJ_JOINT, joint_id),
                spec.joint,
            )
            human_joint_id = mujoco.mj_name2id(
                model,
                mujoco.mjtObj.mjOBJ_JOINT,
                HUMAN_JOINT_NAMES[offset],
            )
            self.assertNotEqual(joint_id, human_joint_id)
            self.assertEqual(model.actuator_gear[actuator_id, 0], spec.gear)

        for cuff in CUFF_ATTACHMENTS:
            self.assertGreaterEqual(
                mujoco.mj_name2id(
                    model,
                    mujoco.mjtObj.mjOBJ_EQUALITY,
                    cuff_equality_name(cuff.link, cuff.mount),
                ),
                0,
            )
            equality_id = mujoco.mj_name2id(
                model,
                mujoco.mjtObj.mjOBJ_EQUALITY,
                cuff_equality_name(cuff.link, cuff.mount),
            )
            np.testing.assert_allclose(
                model.eq_solref[equality_id],
                CUFF_SOLREF,
                atol=0.0,
                rtol=0.0,
            )
            np.testing.assert_allclose(
                model.eq_solimp[equality_id, :3],
                CUFF_SOLIMP,
                atol=0.0,
                rtol=0.0,
            )

        for link in {cuff.link for cuff in CUFF_ATTACHMENTS}:
            points = [
                cuff for cuff in CUFF_ATTACHMENTS if cuff.link == link
            ]
            self.assertEqual({point.mount for point in points}, {"proximal", "distal"})
            self.assertAlmostEqual(
                abs(points[0].human_position[1] - points[1].human_position[1]),
                0.1,
            )
        for mount in URDF_IMU_MOUNTS:
            site_id = mujoco.mj_name2id(
                model,
                mujoco.mjtObj.mjOBJ_SITE,
                f"gexo_imu_{mount.name}",
            )
            self.assertEqual(
                int(model.site_bodyid[site_id]),
                mujoco.mj_name2id(
                    model,
                    mujoco.mjtObj.mjOBJ_BODY,
                    dynamic_body_name(mount.link),
                ),
            )

    def test_dynamic_motor_pulse_reaches_human_without_direct_actuation(self) -> None:
        model = self.dynamic_urdf_model
        for offset, human_joint_name in enumerate(HUMAN_JOINT_NAMES):
            positive = _forward_with_pulse(model, offset, 1.0)
            negative = _forward_with_pulse(model, offset, -1.0)
            human_joint_id = mujoco.mj_name2id(
                model,
                mujoco.mjtObj.mjOBJ_JOINT,
                human_joint_name,
            )
            human_dof = int(model.jnt_dofadr[human_joint_id])
            actuator_force = _exo_generalized_force(model, positive)
            self.assertEqual(actuator_force[human_dof], 0.0)
            self.assertGreater(
                abs(positive.qacc[human_dof] - negative.qacc[human_dof]),
                1.0e-4,
            )

    def test_zero_and_unit_pulses_have_expected_sign(self) -> None:
        for model in (self.model, self.compat_model, self.urdf_model):
            zero_data = _forward_with_pulse(model, 0, 0.0)
            np.testing.assert_allclose(
                _exo_generalized_force(model, zero_data),
                np.zeros(model.nv),
                atol=0.0,
                rtol=0.0,
            )

            for offset, spec in enumerate(EXO_ACTUATORS):
                actuator_id = MUSCLE_ACTUATOR_COUNT + offset
                joint_id = int(model.actuator_trnid[actuator_id, 0])
                dof_id = int(model.jnt_dofadr[joint_id])

                positive = _forward_with_pulse(model, offset, 1.0)
                negative = _forward_with_pulse(model, offset, -1.0)
                positive_force = _exo_generalized_force(model, positive)
                negative_force = _exo_generalized_force(model, negative)

                expected = np.zeros(model.nv)
                expected[dof_id] = spec.gear
                np.testing.assert_allclose(
                    positive_force,
                    expected,
                    atol=1e-12,
                )
                np.testing.assert_allclose(
                    negative_force,
                    -expected,
                    atol=1e-12,
                )

                acceleration_delta = (
                    positive.qacc[dof_id] - negative.qacc[dof_id]
                )
                self.assertGreater(acceleration_delta * spec.gear, 0.0)

                mujoco.mj_step(model, positive)
                mujoco.mj_step(model, negative)
                velocity_delta = (
                    positive.qvel[dof_id] - negative.qvel[dof_id]
                )
                self.assertGreater(velocity_delta * spec.gear, 0.0)


if __name__ == "__main__":
    unittest.main()
