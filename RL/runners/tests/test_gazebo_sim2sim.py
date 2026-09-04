"""Unit tests for the Gazebo bench without starting ROS or Gazebo."""

from __future__ import annotations

from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from RL.env.gazebo.bench import (
    GaitCycleReference,
    GazeboSensorAssembler,
    LinkKinematics,
    build_fixed_bench_urdf,
    deployment_to_urdf,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]


def test_fixed_urdf_keeps_real_links_and_adds_world_joint(tmp_path: Path) -> None:
    output = build_fixed_bench_urdf(
        PROJECT_ROOT / "1.hardware/G-exo_URDF/urdf/G-exo.urdf",
        tmp_path / "fixed.urdf",
    )
    root = ET.parse(output).getroot()
    assert root.find("link[@name='base_link']") is not None
    fixed = root.find("joint[@name='world_to_gexo']")
    assert fixed is not None
    assert fixed.get("type") == "fixed"
    assert fixed.find("parent").get("link") == "world"
    assert all(
        mesh.get("filename", "").startswith("file://")
        for mesh in root.iter("mesh")
    )


def test_reference_and_joint_sign_contract() -> None:
    reference = GaitCycleReference(
        PROJECT_ROOT
        / "RL/assets/myoassist/urdf_zero_assist_motion_stiff_cuff_v1.json",
        speed_m_s=1.0,
        period_steps=50,
    )
    q0, dq0 = reference.sample(0)
    q1, dq1 = reference.sample(50)
    np.testing.assert_allclose(q0, q1, atol=1.0e-7)
    np.testing.assert_allclose(dq0, dq1, atol=1.0e-7)
    np.testing.assert_allclose(
        deployment_to_urdf(np.ones(4)),
        (-1.0, 1.0, 1.0, -1.0),
    )


def test_stationary_link_reports_gravity_as_specific_force() -> None:
    link = LinkKinematics(
        quaternion_xyzw=np.asarray((0.0, 0.0, 0.0, 1.0)),
        linear_velocity_world=np.zeros(3),
        angular_velocity_world=np.zeros(3),
    )
    assembler = GazeboSensorAssembler()
    frame = assembler.build(np.zeros(4), np.zeros(4), (link,) * 4)
    forces = frame[20:32].reshape(4, 3)
    # MyoAssist's Rx(-90 deg) IMU mount maps link +Z to sensor -Y.
    np.testing.assert_allclose(forces[:, 0], 0.0, atol=1.0e-6)
    np.testing.assert_allclose(forces[:, 1], -9.80665, atol=1.0e-5)
    np.testing.assert_allclose(forces[:, 2], 0.0, atol=1.0e-6)

