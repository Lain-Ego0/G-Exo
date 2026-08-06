"""Build and run the G-Exo URDF as a dynamic Kinesis attachment.

The URDF links keep their mass, inertia and four articulated joints.  A soft
pelvis weld and four point cuffs transmit motor loads through the thigh and
shank supports.  The Kinesis checkpoint is loaded on the unchanged human
model first; this module then swaps in the augmented MuJoCo model while
preserving the checkpoint's human-only observation and action interfaces.
"""

from __future__ import annotations

import os
import tempfile
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np

from RL.env.myosuite.exo_overlay import (
    BASE_POSITION_IN_PELVIS,
    BASE_QUATERNION_IN_PELVIS,
    DEFAULT_URDF_PATH,
    _matrix_pose,
    _pose_matrix,
)


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "RL/output/kinesis_physical/gexo_dynamic.xml"
)

EXO_LINK_NAMES = (
    "base_link",
    "l_thigh",
    "l_calf",
    "r_thigh",
    "r_calf",
)
EXO_JOINT_NAMES = (
    "l_thigh_joint",
    "l_calf_joint",
    "r_thigh_joint",
    "r_calf_joint",
)
MOTOR_NAMES = tuple(f"gexo_motor_{name}" for name in EXO_JOINT_NAMES)

# URDF joint coordinate -> anatomical coordinate used by the PPO action.
ANATOMICAL_SIGNS = np.asarray((-1.0, 1.0, 1.0, -1.0))
HUMAN_JOINT_NAMES = (
    "hip_flexion_l",
    "knee_angle_l",
    "hip_flexion_r",
    "knee_angle_r",
)
PASSIVE_HIP_JOINT_NAMES = (
    "hip_adduction_l",
    "hip_rotation_l",
    "hip_adduction_r",
    "hip_rotation_r",
)

# Cuff centers in each human segment's local frame.  The force application
# points represent the padded thigh and shank supports, not point torques at
# the anatomical joint centers.
CUFFS = (
    ("l_thigh", "femur_l", (0.0, -0.23, 0.0)),
    ("l_calf", "tibia_l", (0.0, -0.18, 0.0)),
    ("r_thigh", "femur_r", (0.0, -0.23, 0.0)),
    ("r_calf", "tibia_r", (0.0, -0.18, 0.0)),
)


@dataclass(frozen=True)
class UrdfLink:
    name: str
    mass: float
    inertial_position: tuple[float, float, float]
    inertial_quaternion: tuple[float, float, float, float]
    full_inertia: tuple[float, float, float, float, float, float]
    mesh_path: Path
    mesh_scale: tuple[float, float, float]
    color: tuple[float, float, float, float]


@dataclass(frozen=True)
class UrdfJoint:
    name: str
    parent: str
    child: str
    position: tuple[float, float, float]
    quaternion: tuple[float, float, float, float]
    axis: tuple[float, float, float]
    lower: float
    upper: float
    effort: float
    velocity: float


class DynamicExoSystem:
    """Own the augmented model and keep Kinesis' human interface unchanged."""

    def __init__(
        self,
        environment,
        *,
        urdf_path: Path = DEFAULT_URDF_PATH,
        output_path: Path = DEFAULT_OUTPUT_PATH,
    ) -> None:
        self.environment = environment
        self.human_model = environment.mj_model
        self.human_data = environment.mj_data
        self.human_nq = int(self.human_model.nq)
        self.human_nv = int(self.human_model.nv)
        self.human_nu = int(self.human_model.nu)
        self.human_na = int(self.human_model.na)
        self.human_nbody = int(self.human_model.nbody)

        source_path = Path(environment.cfg.run.xml_path).resolve()
        self.model_path = build_dynamic_exo_model(
            output_path=output_path,
            human_model_path=source_path,
            urdf_path=urdf_path,
        )
        self.model = mujoco.MjModel.from_xml_path(str(self.model_path))
        self.model.opt.timestep = float(self.human_model.opt.timestep)
        self.data = mujoco.MjData(self.model)

        expected = (
            self.human_nq + 8,
            self.human_nv + 8,
            self.human_nu + 4,
            self.human_na,
            self.human_nbody + 5,
        )
        actual = (
            self.model.nq,
            self.model.nv,
            self.model.nu,
            self.model.na,
            self.model.nbody,
        )
        if actual != expected:
            raise RuntimeError(
                f"Unexpected dynamic G-Exo dimensions: {actual} != {expected}."
            )

        self.motor_ids = self._ids(mujoco.mjtObj.mjOBJ_ACTUATOR, MOTOR_NAMES)
        self.exo_joint_ids = self._ids(
            mujoco.mjtObj.mjOBJ_JOINT,
            tuple(f"gexo_{name}" for name in EXO_JOINT_NAMES),
        )
        self.human_joint_ids = self._ids(
            mujoco.mjtObj.mjOBJ_JOINT,
            HUMAN_JOINT_NAMES,
        )
        self.exo_qpos_addresses = self.model.jnt_qposadr[
            self.exo_joint_ids
        ].astype(np.int32)
        self.exo_dof_addresses = self.model.jnt_dofadr[
            self.exo_joint_ids
        ].astype(np.int32)
        self.human_qpos_addresses = self.model.jnt_qposadr[
            self.human_joint_ids
        ].astype(np.int32)
        self.human_dof_addresses = self.model.jnt_dofadr[
            self.human_joint_ids
        ].astype(np.int32)
        self.passive_exo_joint_ids = self._ids(
            mujoco.mjtObj.mjOBJ_JOINT,
            tuple(
                f"gexo_passive_{name}"
                for name in PASSIVE_HIP_JOINT_NAMES
            ),
        )
        self.passive_human_joint_ids = self._ids(
            mujoco.mjtObj.mjOBJ_JOINT, PASSIVE_HIP_JOINT_NAMES
        )
        self.passive_exo_qpos_addresses = self.model.jnt_qposadr[
            self.passive_exo_joint_ids
        ].astype(np.int32)
        self.passive_exo_dof_addresses = self.model.jnt_dofadr[
            self.passive_exo_joint_ids
        ].astype(np.int32)
        self.passive_human_qpos_addresses = self.model.jnt_qposadr[
            self.passive_human_joint_ids
        ].astype(np.int32)
        self.passive_human_dof_addresses = self.model.jnt_dofadr[
            self.passive_human_joint_ids
        ].astype(np.int32)

        self.pelvis_body_id = self._id(
            mujoco.mjtObj.mjOBJ_BODY, "pelvis"
        )
        self.exo_body_ids = self._ids(
            mujoco.mjtObj.mjOBJ_BODY,
            tuple(f"gexo_{name}" for name in EXO_LINK_NAMES),
        )
        self.cuff_equality_ids = self._ids(
            mujoco.mjtObj.mjOBJ_EQUALITY,
            tuple(f"gexo_cuff_{name}" for name, _, _ in CUFFS),
        )
        self.cuff_exo_body_ids = self._ids(
            mujoco.mjtObj.mjOBJ_BODY,
            tuple(f"gexo_{name}" for name, _, _ in CUFFS),
        )
        self.cuff_human_body_ids = self._ids(
            mujoco.mjtObj.mjOBJ_BODY,
            tuple(name for _, name, _ in CUFFS),
        )
        self.viewer = None
        self.activate()

    @property
    def mass_kg(self) -> float:
        return float(np.sum(self.model.body_mass[self.exo_body_ids]))

    def activate(self) -> None:
        self.environment.mj_model = self.model
        self.environment.mj_data = self.data

    def restore_human(self) -> None:
        self.environment.mj_model = self.human_model
        self.environment.mj_data = self.human_data

    def reset(self, *, seed: int, options=None) -> np.ndarray:
        """Reset Kinesis on its original model, then copy into the exo model."""

        self.restore_human()
        observation, _ = self.environment.reset(seed=seed, options=options)
        mujoco.mj_forward(self.human_model, self.human_data)

        mujoco.mj_resetData(self.model, self.data)
        self.data.qpos[: self.human_nq] = self.human_data.qpos
        self.data.qvel[: self.human_nv] = self.human_data.qvel
        self.data.act[: self.human_na] = self.human_data.act
        self.data.time = self.human_data.time

        human_q = self.data.qpos[self.human_qpos_addresses]
        human_dq = self.data.qvel[self.human_dof_addresses]
        self.data.qpos[self.exo_qpos_addresses] = human_q
        self.data.qvel[self.exo_dof_addresses] = human_dq
        self.data.qpos[self.passive_exo_qpos_addresses] = self.data.qpos[
            self.passive_human_qpos_addresses
        ]
        self.data.qvel[self.passive_exo_dof_addresses] = self.data.qvel[
            self.passive_human_dof_addresses
        ]
        self.data.ctrl.fill(0.0)
        self.data.qfrc_applied.fill(0.0)
        mujoco.mj_forward(self.model, self.data)
        self._fit_cuffs()
        mujoco.mj_forward(self.model, self.data)
        self.activate()

        # The human state is unchanged, so the observation returned by the
        # original reset remains the exact checkpoint input.
        return np.asarray(observation, dtype=np.float32)

    def set_motor_torque(self, anatomical_torque_nm: np.ndarray) -> None:
        torque = np.asarray(anatomical_torque_nm, dtype=np.float64)
        if torque.shape != (4,):
            raise ValueError("Motor torque must have shape (4,).")
        self.data.ctrl[self.motor_ids] = torque

    def measured_motor_torque(self) -> np.ndarray:
        return self.data.actuator_force[self.motor_ids].copy()

    def measured_interaction_torque(self) -> np.ndarray:
        """Return cuff-transmitted generalized force at human hip/knee DOFs."""

        generalized = self._cuff_generalized_force()
        return generalized[self.human_dof_addresses].copy()

    def motor_induced_interaction_torque(
        self, anatomical_torque_nm: np.ndarray
    ) -> np.ndarray:
        """Subtract the same-state passive exoskeleton/cuff interaction."""

        self.set_motor_torque(anatomical_torque_nm)
        mujoco.mj_forward(self.model, self.data)
        assisted = self.measured_interaction_torque()
        saved_control = self.data.ctrl[self.motor_ids].copy()
        self.data.ctrl[self.motor_ids] = 0.0
        mujoco.mj_forward(self.model, self.data)
        passive = self.measured_interaction_torque()
        self.data.ctrl[self.motor_ids] = saved_control
        mujoco.mj_forward(self.model, self.data)
        return assisted - passive

    def transmission_matrix(self) -> np.ndarray:
        """Linear same-state map from four motor torques to human support."""

        saved = self.data.ctrl[self.motor_ids].copy()
        matrix = np.empty((4, 4), dtype=np.float64)
        for motor_id in range(4):
            unit = np.zeros(4, dtype=np.float64)
            unit[motor_id] = 1.0
            matrix[:, motor_id] = self.motor_induced_interaction_torque(
                unit
            )
        self.data.ctrl[self.motor_ids] = saved
        mujoco.mj_forward(self.model, self.data)
        return matrix

    def cuff_force_norms(self) -> np.ndarray:
        values = np.zeros(4, dtype=np.float64)
        efc_type = np.asarray(self.data.efc_type)
        efc_id = np.asarray(self.data.efc_id)
        equality_type = int(mujoco.mjtConstraint.mjCNSTR_EQUALITY)

        for index, equality_id in enumerate(self.cuff_equality_ids):
            rows = (efc_type == equality_type) & (efc_id == equality_id)
            values[index] = float(np.linalg.norm(self.data.efc_force[rows]))
        return values

    def cuff_error_norms(self) -> np.ndarray:
        """Return one translational constraint error per physical cuff."""

        values = np.zeros(4, dtype=np.float64)
        efc_type = np.asarray(self.data.efc_type)
        efc_id = np.asarray(self.data.efc_id)
        equality_type = int(mujoco.mjtConstraint.mjCNSTR_EQUALITY)
        for index, equality_id in enumerate(self.cuff_equality_ids):
            rows = (efc_type == equality_type) & (efc_id == equality_id)
            values[index] = float(np.linalg.norm(self.data.efc_pos[rows]))
        return values

    def constraint_error_norm(self) -> float:
        """Return the mean cuff displacement, not a four-cuff L2 sum."""

        return float(np.mean(self.cuff_error_norms()))

    def render(self) -> None:
        if self.viewer is None:
            self.viewer = mujoco.viewer.launch_passive(self.model, self.data)
        if self.viewer.is_running():
            self.viewer.cam.lookat[:] = self.data.qpos[:3]
            self.viewer.sync()

    def close(self) -> None:
        if self.viewer is not None:
            self.viewer.close()
            self.viewer = None
        self.restore_human()

    def _cuff_generalized_force(self) -> np.ndarray:
        if self.data.nefc == 0:
            return np.zeros(self.model.nv, dtype=np.float64)
        jacobian = np.asarray(self.data.efc_J).reshape(
            self.data.nefc, self.model.nv
        )
        efc_type = np.asarray(self.data.efc_type)
        efc_id = np.asarray(self.data.efc_id)
        equality_type = int(mujoco.mjtConstraint.mjCNSTR_EQUALITY)
        rows = (efc_type == equality_type) & np.isin(
            efc_id, self.cuff_equality_ids
        )
        return jacobian[rows].T @ self.data.efc_force[rows]

    def _fit_cuffs(self) -> None:
        """Fit adjustable strap anchors to the current wearing posture."""

        for index, (_, _, human_local_anchor) in enumerate(CUFFS):
            exo_body_id = self.cuff_exo_body_ids[index]
            human_body_id = self.cuff_human_body_ids[index]
            equality_id = self.cuff_equality_ids[index]
            human_rotation = self.data.xmat[human_body_id].reshape(3, 3)
            exo_rotation = self.data.xmat[exo_body_id].reshape(3, 3)
            world_anchor = self.data.xpos[human_body_id] + (
                human_rotation
                @ np.asarray(human_local_anchor, dtype=np.float64)
            )
            self.model.eq_data[equality_id, :3] = (
                exo_rotation.T
                @ (world_anchor - self.data.xpos[exo_body_id])
            )
            self.model.eq_data[equality_id, 3:6] = (
                human_rotation.T
                @ (world_anchor - self.data.xpos[human_body_id])
            )

    def _id(self, object_type, name: str) -> int:
        object_id = mujoco.mj_name2id(self.model, object_type, name)
        if object_id < 0:
            raise ValueError(f"Missing dynamic G-Exo object: {name}")
        return int(object_id)

    def _ids(self, object_type, names: tuple[str, ...]) -> np.ndarray:
        return np.asarray(
            [self._id(object_type, name) for name in names],
            dtype=np.int32,
        )


def build_dynamic_exo_model(
    output_path: Path = DEFAULT_OUTPUT_PATH,
    *,
    human_model_path: Path,
    urdf_path: Path = DEFAULT_URDF_PATH,
) -> Path:
    """Expand the Kinesis XML and append the articulated URDF mechanism."""

    output_path = Path(output_path).expanduser().resolve()
    human_model_path = Path(human_model_path).expanduser().resolve()
    urdf_path = Path(urdf_path).expanduser().resolve()
    output_path.parent.mkdir(parents=True, exist_ok=True)

    human_model = mujoco.MjModel.from_xml_path(str(human_model_path))
    human_data = mujoco.MjData(human_model)
    mujoco.mj_forward(human_model, human_data)
    links, joints = _read_urdf(urdf_path)

    temporary_fd, temporary_name = tempfile.mkstemp(
        suffix=".xml", dir=output_path.parent
    )
    os.close(temporary_fd)
    temporary_path = Path(temporary_name)

    try:
        mujoco.mj_saveLastXML(str(temporary_path), human_model)
        tree = ET.parse(temporary_path)
        root = tree.getroot()
        _repair_expanded_xml_paths(root, human_model_path, output_path.parent)

        # Existing keyframes only contain the human qpos/qvel dimensions.
        keyframe = root.find("keyframe")
        if keyframe is not None:
            root.remove(keyframe)

        asset = root.find("asset")
        worldbody = root.find("worldbody")
        actuator = root.find("actuator")
        equality = root.find("equality")
        if asset is None or worldbody is None or actuator is None:
            raise ValueError("Expanded Kinesis XML is missing core sections.")
        if equality is None:
            equality = ET.SubElement(root, "equality")

        for link in links.values():
            ET.SubElement(
                asset,
                "mesh",
                {
                    "name": f"gexo_mesh_{link.name}",
                    "file": str(link.mesh_path),
                    "scale": _vector(link.mesh_scale),
                },
            )

        pelvis_id = mujoco.mj_name2id(
            human_model, mujoco.mjtObj.mjOBJ_BODY, "pelvis"
        )
        world_from_pelvis = _pose_matrix(
            human_data.xpos[pelvis_id], human_data.xquat[pelvis_id]
        )
        world_from_base = world_from_pelvis @ _pose_matrix(
            BASE_POSITION_IN_PELVIS, BASE_QUATERNION_IN_PELVIS
        )
        base_position, base_quaternion = _matrix_pose(world_from_base)
        _append_aligned_exo_tree(
            root,
            links,
            joints,
            human_model,
            human_data,
            world_from_base,
        )

        for joint in joints.values():
            ET.SubElement(
                actuator,
                "motor",
                {
                    "name": f"gexo_motor_{joint.name}",
                    "joint": f"gexo_{joint.name}",
                    "gear": "1",
                    "ctrllimited": "true",
                    "ctrlrange": f"{-joint.effort:.9g} {joint.effort:.9g}",
                    "forcelimited": "true",
                    "forcerange": f"{-joint.effort:.9g} {joint.effort:.9g}",
                },
            )

        for exo_link, human_body, local_anchor in CUFFS:
            body_id = mujoco.mj_name2id(
                human_model, mujoco.mjtObj.mjOBJ_BODY, human_body
            )
            rotation = human_data.xmat[body_id].reshape(3, 3)
            anchor = human_data.xpos[body_id] + rotation @ np.asarray(
                local_anchor, dtype=np.float64
            )
            ET.SubElement(
                equality,
                "connect",
                {
                    "name": f"gexo_cuff_{exo_link}",
                    "body1": f"gexo_{exo_link}",
                    "body2": human_body,
                    "anchor": _vector(anchor),
                    # Passive hip alignment handles ab/adduction and axial
                    # rotation. Remaining compliance represents cuff padding
                    # and the anatomical knee's coupled translation.
                    "solref": "0.1 1",
                    "solimp": "0.8 0.95 0.01",
                },
            )

        tree.write(temporary_path, encoding="utf-8", xml_declaration=True)
        candidate = mujoco.MjModel.from_xml_path(str(temporary_path))
        expected = (
            human_model.nq + 8,
            human_model.nv + 8,
            human_model.nu + 4,
            human_model.na,
            human_model.nbody + 5,
            human_model.neq + 4,
        )
        actual = (
            candidate.nq,
            candidate.nv,
            candidate.nu,
            candidate.na,
            candidate.nbody,
            candidate.neq,
        )
        if actual != expected:
            raise RuntimeError(f"Dynamic model dimensions {actual} != {expected}.")
        os.replace(temporary_path, output_path)
    finally:
        temporary_path.unlink(missing_ok=True)

    return output_path


def _append_aligned_exo_tree(
    xml_root: ET.Element,
    links: dict[str, UrdfLink],
    joints: dict[str, UrdfJoint],
    human_model: mujoco.MjModel,
    human_data: mujoco.MjData,
    world_from_urdf_base: np.ndarray,
) -> None:
    """Align dynamic axes to anatomy while retaining URDF mass and visuals."""

    worldbody = xml_root.find("worldbody")
    if worldbody is None:
        raise ValueError("Expanded Kinesis XML lacks worldbody.")
    pelvis_element = next(
        (
            body
            for body in worldbody.iter("body")
            if body.get("name") == "pelvis"
        ),
        None,
    )
    if pelvis_element is None:
        raise ValueError("Expanded Kinesis XML lacks pelvis body.")

    human_body_for_link = {
        "base_link": "pelvis",
        "l_thigh": "femur_l",
        "l_calf": "tibia_l",
        "r_thigh": "femur_r",
        "r_calf": "tibia_r",
    }
    human_joint_for_urdf = dict(zip(EXO_JOINT_NAMES, HUMAN_JOINT_NAMES))
    world_from_human: dict[str, np.ndarray] = {}
    for link_name, body_name in human_body_for_link.items():
        body_id = mujoco.mj_name2id(
            human_model, mujoco.mjtObj.mjOBJ_BODY, body_name
        )
        world_from_human[link_name] = _pose_matrix(
            human_data.xpos[body_id], human_data.xquat[body_id]
        )

    world_from_visual = {"base_link": world_from_urdf_base}
    pending = list(joints.values())
    while pending:
        unresolved = []
        for joint in pending:
            if joint.parent not in world_from_visual:
                unresolved.append(joint)
                continue
            world_from_visual[joint.child] = (
                world_from_visual[joint.parent]
                @ _pose_matrix(joint.position, joint.quaternion)
            )
        if len(unresolved) == len(pending):
            raise ValueError("Cannot resolve URDF link tree.")
        pending = unresolved

    children: dict[str, list[UrdfJoint]] = {}
    for joint in joints.values():
        children.setdefault(joint.parent, []).append(joint)

    def append_link(
        parent_element: ET.Element,
        link_name: str,
        *,
        position: tuple[float, ...] | np.ndarray,
        quaternion: tuple[float, ...] | np.ndarray,
        joint: UrdfJoint | None,
    ) -> None:
        body = ET.SubElement(
            parent_element,
            "body",
            {
                "name": f"gexo_{link_name}",
                "pos": _vector(position),
                "quat": _vector(quaternion),
            },
        )
        if joint is not None:
            human_joint_name = human_joint_for_urdf[joint.name]
            human_joint_id = mujoco.mj_name2id(
                human_model,
                mujoco.mjtObj.mjOBJ_JOINT,
                human_joint_name,
            )
            sign = ANATOMICAL_SIGNS[EXO_JOINT_NAMES.index(joint.name)]
            lower, upper = sorted((sign * joint.lower, sign * joint.upper))
            ET.SubElement(
                body,
                "joint",
                {
                    "name": f"gexo_{joint.name}",
                    "type": "hinge",
                    "axis": _vector(human_model.jnt_axis[human_joint_id]),
                    "range": f"{lower:.9g} {upper:.9g}",
                    "limited": "true",
                    "damping": "0.1",
                    "frictionloss": "0.05",
                    "armature": "0.01",
                },
            )
            if joint.name in ("l_thigh_joint", "r_thigh_joint"):
                side = "l" if joint.name.startswith("l_") else "r"
                for passive_name in (
                    f"hip_adduction_{side}",
                    f"hip_rotation_{side}",
                ):
                    passive_id = mujoco.mj_name2id(
                        human_model,
                        mujoco.mjtObj.mjOBJ_JOINT,
                        passive_name,
                    )
                    ET.SubElement(
                        body,
                        "joint",
                        {
                            "name": f"gexo_passive_{passive_name}",
                            "type": "hinge",
                            "axis": _vector(
                                human_model.jnt_axis[passive_id]
                            ),
                            "range": _vector(
                                human_model.jnt_range[passive_id]
                            ),
                            "limited": "true",
                            "damping": "0.2",
                            "frictionloss": "0.02",
                            "armature": "0.002",
                        },
                    )

        link = links[link_name]
        physical_from_visual = np.linalg.inv(
            world_from_human[link_name]
        ) @ world_from_visual[link_name]
        physical_from_inertial = physical_from_visual @ _pose_matrix(
            link.inertial_position,
            link.inertial_quaternion,
        )
        inertial_position = physical_from_inertial[:3, 3]
        inertia_urdf = np.asarray(
            (
                (link.full_inertia[0], link.full_inertia[3], link.full_inertia[4]),
                (link.full_inertia[3], link.full_inertia[1], link.full_inertia[5]),
                (link.full_inertia[4], link.full_inertia[5], link.full_inertia[2]),
            ),
            dtype=np.float64,
        )
        rotation = physical_from_inertial[:3, :3]
        inertia = rotation @ inertia_urdf @ rotation.T
        ET.SubElement(
            body,
            "inertial",
            {
                "pos": _vector(inertial_position),
                "mass": f"{link.mass:.12g}",
                "fullinertia": _vector(
                    (
                        inertia[0, 0],
                        inertia[1, 1],
                        inertia[2, 2],
                        inertia[0, 1],
                        inertia[0, 2],
                        inertia[1, 2],
                    )
                ),
            },
        )
        visual_position, visual_quaternion = _matrix_pose(
            physical_from_visual
        )
        ET.SubElement(
            body,
            "geom",
            {
                "name": f"gexo_visual_{link_name}",
                "type": "mesh",
                "mesh": f"gexo_mesh_{link_name}",
                "pos": _vector(visual_position),
                "quat": _vector(visual_quaternion),
                "rgba": _vector(link.color),
                "contype": "0",
                "conaffinity": "0",
                "group": "2",
                "mass": "0",
            },
        )
        for child_joint in children.get(link_name, []):
            parent_from_child = np.linalg.inv(
                world_from_human[link_name]
            ) @ world_from_human[child_joint.child]
            child_position, child_quaternion = _matrix_pose(
                parent_from_child
            )
            append_link(
                body,
                child_joint.child,
                position=child_position,
                quaternion=child_quaternion,
                joint=child_joint,
            )

    append_link(
        pelvis_element,
        "base_link",
        position=(0.0, 0.0, 0.0),
        quaternion=(1.0, 0.0, 0.0, 0.0),
        joint=None,
    )


def _read_urdf(
    urdf_path: Path,
) -> tuple[dict[str, UrdfLink], dict[str, UrdfJoint]]:
    root = ET.parse(urdf_path).getroot()
    links: dict[str, UrdfLink] = {}
    joints: dict[str, UrdfJoint] = {}
    package_root = urdf_path.parents[1]

    for element in root.findall("link"):
        name = element.attrib["name"]
        inertial = element.find("inertial")
        visual = element.find("visual")
        if inertial is None or visual is None:
            raise ValueError(f"URDF link {name} lacks inertial or visual data.")
        origin = inertial.find("origin")
        inertia = inertial.find("inertia")
        mass = inertial.find("mass")
        mesh = visual.find("geometry/mesh")
        if inertia is None or mass is None or mesh is None:
            raise ValueError(f"URDF link {name} is incomplete.")
        inertial_xyz, inertial_quat = _origin(origin)
        mesh_path = _resolve_mesh(mesh.attrib["filename"], package_root)
        scale = _floats(mesh.attrib.get("scale", "1 1 1"), 3)
        color_element = visual.find("material/color")
        color = (
            _floats(color_element.attrib["rgba"], 4)
            if color_element is not None
            else (0.75, 0.8, 0.9, 1.0)
        )
        links[name] = UrdfLink(
            name=name,
            mass=float(mass.attrib["value"]),
            inertial_position=inertial_xyz,
            inertial_quaternion=inertial_quat,
            full_inertia=(
                float(inertia.attrib["ixx"]),
                float(inertia.attrib["iyy"]),
                float(inertia.attrib["izz"]),
                float(inertia.attrib["ixy"]),
                float(inertia.attrib["ixz"]),
                float(inertia.attrib["iyz"]),
            ),
            mesh_path=mesh_path,
            mesh_scale=scale,
            color=color,
        )

    for element in root.findall("joint"):
        name = element.attrib["name"]
        origin_xyz, origin_quat = _origin(element.find("origin"))
        limit = element.find("limit")
        axis = element.find("axis")
        if limit is None or axis is None:
            raise ValueError(f"URDF joint {name} lacks axis or limits.")
        joints[name] = UrdfJoint(
            name=name,
            parent=element.find("parent").attrib["link"],
            child=element.find("child").attrib["link"],
            position=origin_xyz,
            quaternion=origin_quat,
            axis=_floats(axis.attrib["xyz"], 3),
            lower=float(limit.attrib["lower"]),
            upper=float(limit.attrib["upper"]),
            effort=float(limit.attrib["effort"]),
            velocity=float(limit.attrib["velocity"]),
        )

    if set(links) != set(EXO_LINK_NAMES) or set(joints) != set(EXO_JOINT_NAMES):
        raise ValueError("The G-Exo URDF topology does not match the expected 5/4 model.")
    return links, joints


def _repair_expanded_xml_paths(
    root: ET.Element,
    source_path: Path,
    output_directory: Path,
) -> None:
    size = root.find("size")
    if size is not None and size.get("memory") is not None:
        size.attrib.pop("njmax", None)
        size.attrib.pop("nconmax", None)
    compiler = root.find("compiler")
    if compiler is not None:
        # The exported calf inertia is rounded to 1e-4 and narrowly violates
        # MuJoCo's triangle test.  Balance the rounded tensor instead of
        # discarding the URDF mass distribution.
        compiler.set("balanceinertia", "true")
        source_root = ET.parse(source_path).getroot()
        source_compiler = source_root.find("compiler")
        for key in ("meshdir", "texturedir"):
            value = None if source_compiler is None else source_compiler.get(key)
            directory = source_path.parent if not value else source_path.parent / value
            compiler.set(key, os.path.relpath(directory.resolve(), output_directory))


def _origin(
    element: ET.Element | None,
) -> tuple[
    tuple[float, float, float],
    tuple[float, float, float, float],
]:
    if element is None:
        return (0.0, 0.0, 0.0), (1.0, 0.0, 0.0, 0.0)
    xyz = _floats(element.attrib.get("xyz", "0 0 0"), 3)
    rpy = _floats(element.attrib.get("rpy", "0 0 0"), 3)
    cr, cp, cy = np.cos(np.asarray(rpy) * 0.5)
    sr, sp, sy = np.sin(np.asarray(rpy) * 0.5)
    quaternion = (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )
    return xyz, tuple(float(value) for value in quaternion)


def _resolve_mesh(filename: str, package_root: Path) -> Path:
    package_prefix = "package://G-exo/"
    if filename.startswith(package_prefix):
        path = package_root / filename[len(package_prefix) :]
    else:
        path = Path(filename)
        if not path.is_absolute():
            path = package_root / path
    path = path.resolve()
    if not path.is_file():
        raise FileNotFoundError(path)
    return path


def _floats(text: str, size: int) -> tuple:
    values = tuple(float(value) for value in text.split())
    if len(values) != size:
        raise ValueError(f"Expected {size} values, got {values}.")
    return values


def _vector(values) -> str:
    return " ".join(f"{float(value):.12g}" for value in values)


__all__ = [
    "ANATOMICAL_SIGNS",
    "DEFAULT_OUTPUT_PATH",
    "DynamicExoSystem",
    "build_dynamic_exo_model",
]
