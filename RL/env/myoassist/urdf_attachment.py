"""Attach the G-Exo URDF to the planar MyoAssist human.

The rigid variant is retained as a load-only diagnostic.  The dynamic variant
keeps four articulated exoskeleton joints and transfers their loads to the
human through compliant thigh and shank cuffs.
"""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import mujoco
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_GEXO_URDF_PATH = (
    PROJECT_ROOT / "1.hardware/G-exo_URDF/urdf/G-exo.urdf"
)
RIGID_BODY_PREFIX = "gexo_urdf_"
DYNAMIC_BODY_PREFIX = "gexo_dynamic_"
DYNAMIC_JOINT_PREFIX = "gexo_dynamic_"

# The transform was visually checked against the MyoAssist pelvis.  It maps
# URDF +X/+Y/+Z to the human frame while keeping the back support posterior.
BASE_POSITION_IN_PELVIS = (-0.2035, 0.052, 0.0)
BASE_QUATERNION_IN_PELVIS = (
    math.sqrt(0.5),
    -math.sqrt(0.5),
    0.0,
    0.0,
)


@dataclass(frozen=True)
class LinkAttachment:
    """Map one URDF link to the human segment carrying it."""

    link: str
    human_body: str


@dataclass(frozen=True)
class UrdfImuMount:
    """Nominal IMU pose expressed directly in one URDF link frame."""

    name: str
    link: str
    position: tuple[float, float, float]


@dataclass(frozen=True)
class DynamicImuPose:
    """One link-aligned IMU pose expressed in a dynamic MuJoCo body."""

    name: str
    body: str
    position: tuple[float, float, float]
    quaternion: tuple[float, float, float, float]


@dataclass(frozen=True)
class UrdfJoint:
    """The URDF fields needed to build one dynamic hinge."""

    name: str
    parent: str
    child: str
    lower: float
    upper: float


@dataclass(frozen=True)
class CuffAttachment:
    """Connect one point on a rigid support plate to a human segment."""

    link: str
    human_body: str
    mount: str
    human_position: tuple[float, float, float]


LINK_ATTACHMENTS = (
    LinkAttachment("base_link", "pelvis"),
    LinkAttachment("l_thigh", "femur_l"),
    LinkAttachment("l_calf", "tibia_l"),
    LinkAttachment("r_thigh", "femur_r"),
    LinkAttachment("r_calf", "tibia_r"),
)

# Repeatable installation points referenced to URDF joint axes.  The thigh IMU
# is 100 mm below the hip axis on the upper structural member.  The shank IMU
# is on the upper support plate, close to the knee.  Sensor axes are aligned
# with the link axes; only these positions need updating after CAD hole design.
URDF_IMU_MOUNTS = (
    UrdfImuMount("left_thigh", "l_thigh", (0.0100, 0.0000, -0.1000)),
    UrdfImuMount("left_shank", "l_calf", (-0.0600, -0.0600, -0.0800)),
    UrdfImuMount("right_thigh", "r_thigh", (0.0100, 0.0000, -0.1000)),
    UrdfImuMount("right_shank", "r_calf", (-0.0600, 0.0600, -0.0800)),
)
URDF_IMU_FRAMES = (
    ("A1_mount_joint", "A1_link"),
    ("A2_mount_joint", "A2_link"),
    ("B1_mount_joint", "B1_link"),
    ("B2_mount_joint", "B2_link"),
)

URDF_JOINT_NAMES = (
    "l_thigh_joint",
    "l_calf_joint",
    "r_thigh_joint",
    "r_calf_joint",
)
HUMAN_JOINT_NAMES = (
    "hip_flexion_l",
    "knee_angle_l",
    "hip_flexion_r",
    "knee_angle_r",
)
# Both arrays map their native joint coordinate into the deployment convention:
# left hip, left knee flexion, right hip, right knee flexion.
URDF_ANATOMICAL_SIGNS = np.asarray((-1.0, 1.0, 1.0, -1.0))
HUMAN_ANATOMICAL_SIGNS = np.asarray((1.0, -1.0, 1.0, -1.0))

# A single point cannot transmit a pure moment from a support plate.  Two
# points 100 mm apart approximate the distributed load of the rigid thigh and
# shank supports while retaining a small amount of soft-tissue compliance.
CUFF_ATTACHMENTS = (
    CuffAttachment("l_thigh", "femur_l", "proximal", (0.0, -0.18, 0.0)),
    CuffAttachment("l_thigh", "femur_l", "distal", (0.0, -0.28, 0.0)),
    CuffAttachment("l_calf", "tibia_l", "proximal", (0.0, -0.13, 0.0)),
    CuffAttachment("l_calf", "tibia_l", "distal", (0.0, -0.23, 0.0)),
    CuffAttachment("r_thigh", "femur_r", "proximal", (0.0, -0.18, 0.0)),
    CuffAttachment("r_thigh", "femur_r", "distal", (0.0, -0.28, 0.0)),
    CuffAttachment("r_calf", "tibia_r", "proximal", (0.0, -0.13, 0.0)),
    CuffAttachment("r_calf", "tibia_r", "distal", (0.0, -0.23, 0.0)),
)
CUFF_SOLREF = (0.02, 1.0)
CUFF_SOLIMP = (0.9, 0.99, 0.001)


def add_rigid_gexo_urdf(
    root: ET.Element,
    *,
    source_model_path: Path,
    urdf_path: Path = DEFAULT_GEXO_URDF_PATH,
) -> None:
    """Add fixed URDF links, inertias and meshes to a MyoAssist XML tree."""

    urdf_path = Path(urdf_path).expanduser().resolve(strict=True)
    urdf_root = ET.parse(urdf_path).getroot()
    _validate_imu_frames(urdf_root)
    links = _read_links(urdf_root, urdf_path)
    base_from_link = _zero_pose_links(urdf_root)
    attachment_poses = _attachment_poses(
        Path(source_model_path),
        base_from_link,
    )

    human_bodies = {
        body.get("name"): body
        for body in root.iter("body")
        if body.get("name") is not None
    }
    asset = root.find("asset")
    if asset is None:
        raise ValueError("MyoAssist model has no <asset> section.")

    for attachment in LINK_ATTACHMENTS:
        if attachment.human_body not in human_bodies:
            raise ValueError(
                f"Missing human body {attachment.human_body!r}."
            )
        link = links[attachment.link]
        position, quaternion = attachment_poses[attachment.link]
        body_name = rigid_body_name(attachment.link)
        mesh_name = f"{body_name}_mesh"
        ET.SubElement(
            asset,
            "mesh",
            {
                "name": mesh_name,
                "file": str(link["mesh_path"]),
                "scale": _format(link["mesh_scale"]),
            },
        )
        body = ET.SubElement(
            human_bodies[attachment.human_body],
            "body",
            {
                "name": body_name,
                "pos": _format(position),
                "quat": _format(quaternion),
            },
        )
        ET.SubElement(
            body,
            "inertial",
            {
                "pos": _format(link["inertial_position"]),
                "mass": f"{float(link['mass']):.12g}",
                "fullinertia": _format(link["full_inertia"]),
            },
        )
        ET.SubElement(
            body,
            "geom",
            {
                "name": f"{body_name}_visual",
                "type": "mesh",
                "mesh": mesh_name,
                "pos": _format(link["visual_position"]),
                "quat": _format(link["visual_quaternion"]),
                "rgba": _format(link["color"]),
                "contype": "0",
                "conaffinity": "0",
                "group": "2",
                "mass": "0",
            },
        )

def add_dynamic_gexo_urdf(
    root: ET.Element,
    *,
    source_model_path: Path,
    urdf_path: Path = DEFAULT_GEXO_URDF_PATH,
) -> tuple[DynamicImuPose, ...]:
    """Add four URDF hinges and compliant thigh/shank load paths."""

    source_model_path = Path(source_model_path).expanduser().resolve(strict=True)
    urdf_path = Path(urdf_path).expanduser().resolve(strict=True)
    urdf_root = ET.parse(urdf_path).getroot()
    _validate_imu_frames(urdf_root)
    links = _read_links(urdf_root, urdf_path)
    joints = _read_joints(urdf_root)
    base_from_link = _zero_pose_links(urdf_root)
    model, _, world_from_human = _neutral_human_state(source_model_path)

    pelvis = next(
        (body for body in root.iter("body") if body.get("name") == "pelvis"),
        None,
    )
    asset = root.find("asset")
    equality = root.find("equality")
    if pelvis is None or asset is None:
        raise ValueError("MyoAssist model is missing pelvis or asset sections.")
    if equality is None:
        equality = ET.SubElement(root, "equality")

    world_from_base = world_from_human["pelvis"] @ _pose_matrix(
        BASE_POSITION_IN_PELVIS,
        BASE_QUATERNION_IN_PELVIS,
    )
    world_from_visual = {
        link_name: world_from_base @ base_from_link[link_name]
        for link_name in links
    }
    physical_body = {
        "base_link": "pelvis",
        "l_thigh": "femur_l",
        "l_calf": "tibia_l",
        "r_thigh": "femur_r",
        "r_calf": "tibia_r",
    }
    children: dict[str, list[UrdfJoint]] = {}
    for joint in joints.values():
        children.setdefault(joint.parent, []).append(joint)

    imu_poses: list[DynamicImuPose] = []

    def append_link(
        parent: ET.Element,
        link_name: str,
        *,
        position: np.ndarray | tuple[float, ...],
        quaternion: np.ndarray | tuple[float, ...],
        joint: UrdfJoint | None,
    ) -> None:
        body = ET.SubElement(
            parent,
            "body",
            {
                "name": dynamic_body_name(link_name),
                "pos": _format(position),
                "quat": _format(quaternion),
            },
        )
        if joint is not None:
            joint_index = URDF_JOINT_NAMES.index(joint.name)
            human_joint_id = _required_id(
                model,
                mujoco.mjtObj.mjOBJ_JOINT,
                HUMAN_JOINT_NAMES[joint_index],
            )
            deployment_range = np.sort(
                URDF_ANATOMICAL_SIGNS[joint_index]
                * np.asarray((joint.lower, joint.upper))
            )
            human_range = np.sort(
                deployment_range / HUMAN_ANATOMICAL_SIGNS[joint_index]
            )
            ET.SubElement(
                body,
                "joint",
                {
                    "name": dynamic_joint_name(joint.name),
                    "type": "hinge",
                    "axis": _format(model.jnt_axis[human_joint_id]),
                    "range": _format(human_range),
                    "limited": "true",
                    "damping": "0.1",
                    "frictionloss": "0.05",
                    "armature": "0.01",
                },
            )

        link = links[link_name]
        physical_from_visual = (
            _inverse_pose(world_from_human[physical_body[link_name]])
            @ world_from_visual[link_name]
        )
        inertial_position = (
            physical_from_visual
            @ np.asarray((*link["inertial_position"], 1.0), dtype=np.float64)
        )[:3]
        link_inertia = _full_inertia_matrix(link["full_inertia"])
        rotation = physical_from_visual[:3, :3]
        physical_inertia = rotation @ link_inertia @ rotation.T
        ET.SubElement(
            body,
            "inertial",
            {
                "pos": _format(inertial_position),
                "mass": f"{float(link['mass']):.12g}",
                "fullinertia": _format(_matrix_full_inertia(physical_inertia)),
            },
        )

        mesh_name = f"{dynamic_body_name(link_name)}_mesh"
        ET.SubElement(
            asset,
            "mesh",
            {
                "name": mesh_name,
                "file": str(link["mesh_path"]),
                "scale": _format(link["mesh_scale"]),
            },
        )
        visual_position, visual_quaternion = _matrix_pose(physical_from_visual)
        ET.SubElement(
            body,
            "geom",
            {
                "name": f"{dynamic_body_name(link_name)}_visual",
                "type": "mesh",
                "mesh": mesh_name,
                "pos": _format(visual_position),
                "quat": _format(visual_quaternion),
                "rgba": _format(link["color"]),
                "contype": "0",
                "conaffinity": "0",
                "group": "2",
                "mass": "0",
            },
        )

        for cuff in CUFF_ATTACHMENTS:
            if cuff.link == link_name:
                ET.SubElement(
                    body,
                    "site",
                    {
                        "name": cuff_site_name("exo", cuff),
                        "pos": _format(cuff.human_position),
                        "size": "0.006",
                        "group": "4",
                        "rgba": "0.9 0.2 0.1 0.7",
                    },
                )

        for mount in URDF_IMU_MOUNTS:
            if mount.link != link_name:
                continue
            site_position = (
                physical_from_visual
                @ np.asarray((*mount.position, 1.0), dtype=np.float64)
            )[:3]
            _, site_quaternion = _matrix_pose(physical_from_visual)
            imu_poses.append(
                DynamicImuPose(
                    mount.name,
                    dynamic_body_name(link_name),
                    tuple(site_position),
                    tuple(site_quaternion),
                )
            )

        for child_joint in children.get(link_name, ()):
            parent_from_child = (
                _inverse_pose(world_from_human[physical_body[link_name]])
                @ world_from_human[physical_body[child_joint.child]]
            )
            child_position, child_quaternion = _matrix_pose(parent_from_child)
            append_link(
                body,
                child_joint.child,
                position=child_position,
                quaternion=child_quaternion,
                joint=child_joint,
            )

    append_link(
        pelvis,
        "base_link",
        position=(0.0, 0.0, 0.0),
        quaternion=(1.0, 0.0, 0.0, 0.0),
        joint=None,
    )

    human_bodies = {
        body.get("name"): body
        for body in root.iter("body")
        if body.get("name") is not None
    }
    for cuff in CUFF_ATTACHMENTS:
        human_site = cuff_site_name("human", cuff)
        ET.SubElement(
            human_bodies[cuff.human_body],
            "site",
            {
                "name": human_site,
                "pos": _format(cuff.human_position),
                "size": "0.006",
                "group": "4",
                "rgba": "0.1 0.8 0.2 0.7",
            },
        )
        ET.SubElement(
            equality,
            "connect",
            {
                "name": cuff_equality_name(cuff.link, cuff.mount),
                "site1": cuff_site_name("exo", cuff),
                "site2": human_site,
                "solref": _format(CUFF_SOLREF),
                "solimp": _format(CUFF_SOLIMP),
            },
        )

    _extend_keyframes(root, model)
    if len(imu_poses) != len(URDF_IMU_MOUNTS):
        raise RuntimeError("Dynamic URDF did not create all four IMU poses.")
    return tuple(imu_poses)


def rigid_body_name(link_name: str) -> str:
    return f"{RIGID_BODY_PREFIX}{link_name}"


def dynamic_body_name(link_name: str) -> str:
    return f"{DYNAMIC_BODY_PREFIX}{link_name}"


def dynamic_joint_name(joint_name: str) -> str:
    return f"{DYNAMIC_JOINT_PREFIX}{joint_name}"


def cuff_site_name(side: str, cuff: CuffAttachment) -> str:
    if side not in {"exo", "human"}:
        raise ValueError(f"Unsupported cuff site side: {side!r}.")
    return f"gexo_cuff_{side}_{cuff.link}_{cuff.mount}"


def cuff_equality_name(link_name: str, mount: str) -> str:
    return f"gexo_cuff_{link_name}_{mount}"


def model_has_rigid_gexo(model: mujoco.MjModel) -> bool:
    """Return whether a compiled model contains the complete rigid URDF."""

    model = _raw_model(model)
    found = [
        mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_BODY,
            rigid_body_name(spec.link),
        )
        >= 0
        for spec in LINK_ATTACHMENTS
    ]
    if any(found) and not all(found):
        raise ValueError("Compiled model contains an incomplete G-Exo URDF.")
    return all(found)


def model_has_dynamic_gexo(model: mujoco.MjModel) -> bool:
    """Return whether a compiled model contains the complete dynamic URDF."""

    model = _raw_model(model)
    body_found = [
        mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_BODY,
            dynamic_body_name(spec.link),
        )
        >= 0
        for spec in LINK_ATTACHMENTS
    ]
    joint_found = [
        mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_JOINT,
            dynamic_joint_name(name),
        )
        >= 0
        for name in URDF_JOINT_NAMES
    ]
    cuff_found = [
        mujoco.mj_name2id(
            model,
            mujoco.mjtObj.mjOBJ_EQUALITY,
            cuff_equality_name(spec.link, spec.mount),
        )
        >= 0
        for spec in CUFF_ATTACHMENTS
    ]
    found = body_found + joint_found + cuff_found
    if any(found) and not all(found):
        raise ValueError("Compiled model contains an incomplete dynamic G-Exo URDF.")
    return all(found)


def model_has_gexo_urdf(model: mujoco.MjModel) -> bool:
    """Return whether either complete URDF integration variant is present."""

    rigid = model_has_rigid_gexo(model)
    dynamic = model_has_dynamic_gexo(model)
    if rigid and dynamic:
        raise ValueError("Compiled model mixes rigid and dynamic G-Exo variants.")
    return rigid or dynamic


def synchronize_dynamic_gexo_state(
    model: mujoco.MjModel,
    qpos: np.ndarray,
    qvel: np.ndarray,
) -> None:
    """Initialize exoskeleton hinges from the corresponding human joints."""

    model = _raw_model(model)
    if not model_has_dynamic_gexo(model):
        return
    for dynamic_name, human_name in zip(URDF_JOINT_NAMES, HUMAN_JOINT_NAMES):
        exo_id = _required_id(
            model,
            mujoco.mjtObj.mjOBJ_JOINT,
            dynamic_joint_name(dynamic_name),
        )
        human_id = _required_id(
            model,
            mujoco.mjtObj.mjOBJ_JOINT,
            human_name,
        )
        qpos[int(model.jnt_qposadr[exo_id])] = qpos[
            int(model.jnt_qposadr[human_id])
        ]
        qvel[int(model.jnt_dofadr[exo_id])] = qvel[
            int(model.jnt_dofadr[human_id])
        ]


def _read_links(
    root: ET.Element,
    urdf_path: Path,
) -> dict[str, dict[str, object]]:
    links: dict[str, dict[str, object]] = {}
    for attachment in LINK_ATTACHMENTS:
        name = attachment.link
        link = root.find(f"./link[@name='{name}']")
        if link is None:
            raise ValueError(f"URDF has no link {name!r}.")
        inertial = _required_child(link, "inertial", name)
        mass = float(_required_child(inertial, "mass", name).get("value", "nan"))
        inertia = _required_child(inertial, "inertia", name)
        visual = _required_child(link, "visual", name)
        mesh = _required_child(visual, "geometry/mesh", name)
        filename = mesh.get("filename")
        if not filename or not math.isfinite(mass) or mass <= 0.0:
            raise ValueError(f"URDF link {name!r} has invalid mass or mesh.")
        mesh_path = _resolve_mesh(filename, urdf_path)
        if not mesh_path.is_file():
            raise FileNotFoundError(f"Missing URDF mesh: {mesh_path}")
        inertial_position, inertial_rpy = _origin(inertial)
        visual_position, visual_rpy = _origin(visual)
        color = visual.find("material/color")
        ixx = float(inertia.get("ixx", "nan"))
        iyy = float(inertia.get("iyy", "nan"))
        izz = float(inertia.get("izz", "nan"))
        ixy = float(inertia.get("ixy", "nan"))
        ixz = float(inertia.get("ixz", "nan"))
        iyz = float(inertia.get("iyz", "nan"))
        urdf_inertia = np.array(
            (
                (ixx, ixy, ixz),
                (ixy, iyy, iyz),
                (ixz, iyz, izz),
            ),
            dtype=np.float64,
        )
        if not np.all(np.isfinite(urdf_inertia)):
            raise ValueError(f"URDF link {name!r} has invalid inertia.")
        inertial_quaternion = _rpy_to_quaternion(inertial_rpy)
        rotation = np.empty(9, dtype=np.float64)
        mujoco.mju_quat2Mat(
            rotation,
            np.asarray(inertial_quaternion, dtype=np.float64),
        )
        rotation = rotation.reshape(3, 3)
        link_inertia = rotation @ urdf_inertia @ rotation.T
        full_inertia = (
            link_inertia[0, 0],
            link_inertia[1, 1],
            link_inertia[2, 2],
            link_inertia[0, 1],
            link_inertia[0, 2],
            link_inertia[1, 2],
        )
        links[name] = {
            "mass": mass,
            "inertial_position": inertial_position,
            "full_inertia": full_inertia,
            "mesh_path": mesh_path,
            "mesh_scale": _vector(mesh.get("scale"), 3, (1.0, 1.0, 1.0)),
            "visual_position": visual_position,
            "visual_quaternion": _rpy_to_quaternion(visual_rpy),
            "color": _vector(
                None if color is None else color.get("rgba"),
                4,
                (0.85, 0.85, 0.85, 1.0),
            ),
        }
    return links


def _read_joints(root: ET.Element) -> dict[str, UrdfJoint]:
    joints: dict[str, UrdfJoint] = {}
    for name in URDF_JOINT_NAMES:
        element = root.find(f"./joint[@name='{name}']")
        if element is None:
            raise ValueError(f"URDF has no joint {name!r}.")
        parent = _required_child(element, "parent", name).get("link")
        child = _required_child(element, "child", name).get("link")
        limit = _required_child(element, "limit", name)
        if parent is None or child is None:
            raise ValueError(f"URDF joint {name!r} has no parent or child link.")
        lower = float(limit.get("lower", "nan"))
        upper = float(limit.get("upper", "nan"))
        if not all(math.isfinite(value) for value in (lower, upper)):
            raise ValueError(f"URDF joint {name!r} has invalid limits.")
        joints[name] = UrdfJoint(name, parent, child, lower, upper)
    return joints


def _validate_imu_frames(root: ET.Element) -> None:
    """Reject divergence between URDF IMU frames and the training contract."""

    for mount, (joint_name, child_name) in zip(
        URDF_IMU_MOUNTS, URDF_IMU_FRAMES
    ):
        joint = root.find(f"./joint[@name='{joint_name}']")
        if joint is None or joint.get("type") != "fixed":
            raise ValueError(f"URDF has no fixed IMU joint {joint_name!r}.")
        parent = _required_child(joint, "parent", joint_name).get("link")
        child = _required_child(joint, "child", joint_name).get("link")
        position, rpy = _origin(joint)
        if parent != mount.link or child != child_name:
            raise ValueError(f"URDF IMU joint {joint_name!r} has wrong links.")
        if not np.allclose(position, mount.position, atol=1.0e-12, rtol=0.0):
            raise ValueError(f"URDF IMU joint {joint_name!r} has wrong position.")
        if not np.allclose(rpy, (0.0, 0.0, 0.0), atol=0.0, rtol=0.0):
            raise ValueError(f"URDF IMU joint {joint_name!r} must align axes.")


def _neutral_human_state(
    source_model_path: Path,
) -> tuple[mujoco.MjModel, mujoco.MjData, dict[str, np.ndarray]]:
    """Return source-model body transforms at its compiler reference state."""

    model = mujoco.MjModel.from_xml_path(str(source_model_path))
    data = mujoco.MjData(model)
    stand_key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "stand")
    if stand_key >= 0:
        mujoco.mj_resetDataKeyframe(model, data, stand_key)
    else:
        mujoco.mj_resetData(model, data)
    for joint_name in HUMAN_JOINT_NAMES:
        joint_id = _required_id(
            model,
            mujoco.mjtObj.mjOBJ_JOINT,
            joint_name,
        )
        data.qpos[int(model.jnt_qposadr[joint_id])] = 0.0
    mujoco.mj_forward(model, data)
    body_names = {spec.human_body for spec in LINK_ATTACHMENTS}
    transforms = {
        name: _pose_matrix(
            data.xpos[_required_id(model, mujoco.mjtObj.mjOBJ_BODY, name)],
            data.xquat[_required_id(model, mujoco.mjtObj.mjOBJ_BODY, name)],
        )
        for name in body_names
    }
    return model, data, transforms


def _extend_keyframes(root: ET.Element, model: mujoco.MjModel) -> None:
    """Append exoskeleton q/dq values synchronized to each human keyframe."""

    human_joint_ids = [
        _required_id(model, mujoco.mjtObj.mjOBJ_JOINT, name)
        for name in HUMAN_JOINT_NAMES
    ]
    qpos_addresses = [int(model.jnt_qposadr[joint_id]) for joint_id in human_joint_ids]
    qvel_addresses = [int(model.jnt_dofadr[joint_id]) for joint_id in human_joint_ids]
    for key in root.findall("./keyframe/key"):
        qpos_text = key.get("qpos")
        if qpos_text is not None:
            qpos = np.fromstring(qpos_text, sep=" ", dtype=np.float64)
            if qpos.size != model.nq:
                raise ValueError(
                    f"Keyframe {key.get('name')!r} qpos has {qpos.size} values, "
                    f"expected {model.nq}."
                )
            key.set("qpos", _format(np.concatenate((qpos, qpos[qpos_addresses]))))

        qvel_text = key.get("qvel")
        if qvel_text is not None:
            qvel = np.fromstring(qvel_text, sep=" ", dtype=np.float64)
            if qvel.size != model.nv:
                raise ValueError(
                    f"Keyframe {key.get('name')!r} qvel has {qvel.size} values, "
                    f"expected {model.nv}."
                )
            key.set("qvel", _format(np.concatenate((qvel, qvel[qvel_addresses]))))


def _full_inertia_matrix(values) -> np.ndarray:
    ixx, iyy, izz, ixy, ixz, iyz = (float(value) for value in values)
    return np.asarray(
        ((ixx, ixy, ixz), (ixy, iyy, iyz), (ixz, iyz, izz)),
        dtype=np.float64,
    )


def _matrix_full_inertia(matrix: np.ndarray) -> tuple[float, ...]:
    return (
        float(matrix[0, 0]),
        float(matrix[1, 1]),
        float(matrix[2, 2]),
        float(matrix[0, 1]),
        float(matrix[0, 2]),
        float(matrix[1, 2]),
    )


def _zero_pose_links(root: ET.Element) -> dict[str, np.ndarray]:
    transforms = {"base_link": np.eye(4, dtype=np.float64)}
    pending = list(root.findall("joint"))
    expected_links = {spec.link for spec in LINK_ATTACHMENTS}
    while pending and not expected_links.issubset(transforms):
        unresolved = []
        progress = False
        for joint in pending:
            owner = joint.get("name", "joint")
            parent = _required_child(joint, "parent", owner).get("link")
            child = _required_child(joint, "child", owner).get("link")
            if parent not in transforms or not child:
                unresolved.append(joint)
                continue
            position, rpy = _origin(joint)
            transforms[child] = transforms[parent] @ _pose_matrix(
                position,
                _rpy_to_quaternion(rpy),
            )
            progress = True
        if not progress:
            break
        pending = unresolved
    missing = expected_links.difference(transforms)
    if missing:
        raise ValueError(f"Cannot resolve URDF links: {sorted(missing)}")
    return transforms


def _attachment_poses(
    source_model_path: Path,
    base_from_link: dict[str, np.ndarray],
) -> dict[str, tuple[np.ndarray, np.ndarray]]:
    model = mujoco.MjModel.from_xml_path(str(source_model_path))
    data = mujoco.MjData(model)
    stand_key = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_KEY, "stand")
    if stand_key >= 0:
        mujoco.mj_resetDataKeyframe(model, data, stand_key)
    else:
        mujoco.mj_resetData(model, data)
    for joint_name in (
        "hip_flexion_l",
        "knee_angle_l",
        "hip_flexion_r",
        "knee_angle_r",
    ):
        joint_id = mujoco.mj_name2id(model, mujoco.mjtObj.mjOBJ_JOINT, joint_name)
        if joint_id < 0:
            raise ValueError(f"MyoAssist model has no joint {joint_name!r}.")
        data.qpos[int(model.jnt_qposadr[joint_id])] = 0.0
    mujoco.mj_forward(model, data)

    pelvis_id = _required_id(model, mujoco.mjtObj.mjOBJ_BODY, "pelvis")
    world_from_pelvis = _pose_matrix(data.xpos[pelvis_id], data.xquat[pelvis_id])
    world_from_base = world_from_pelvis @ _pose_matrix(
        BASE_POSITION_IN_PELVIS,
        BASE_QUATERNION_IN_PELVIS,
    )
    result = {}
    for attachment in LINK_ATTACHMENTS:
        body_id = _required_id(
            model,
            mujoco.mjtObj.mjOBJ_BODY,
            attachment.human_body,
        )
        world_from_human = _pose_matrix(data.xpos[body_id], data.xquat[body_id])
        world_from_link = world_from_base @ base_from_link[attachment.link]
        human_from_link = _inverse_pose(world_from_human) @ world_from_link
        result[attachment.link] = _matrix_pose(human_from_link)
    return result


def _pose_matrix(position, quaternion) -> np.ndarray:
    result = np.eye(4, dtype=np.float64)
    rotation = np.empty(9, dtype=np.float64)
    mujoco.mju_quat2Mat(rotation, np.asarray(quaternion, dtype=np.float64))
    result[:3, :3] = rotation.reshape(3, 3)
    result[:3, 3] = np.asarray(position, dtype=np.float64)
    return result


def _inverse_pose(matrix: np.ndarray) -> np.ndarray:
    result = np.eye(4, dtype=np.float64)
    result[:3, :3] = matrix[:3, :3].T
    result[:3, 3] = -result[:3, :3] @ matrix[:3, 3]
    return result


def _matrix_pose(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    quaternion = np.empty(4, dtype=np.float64)
    mujoco.mju_mat2Quat(
        quaternion,
        np.ascontiguousarray(matrix[:3, :3]).reshape(9),
    )
    return matrix[:3, 3], quaternion


def _origin(element: ET.Element) -> tuple[tuple[float, ...], tuple[float, ...]]:
    origin = element.find("origin")
    if origin is None:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)
    return (
        _vector(origin.get("xyz"), 3, (0.0, 0.0, 0.0)),
        _vector(origin.get("rpy"), 3, (0.0, 0.0, 0.0)),
    )


def _rpy_to_quaternion(rpy: tuple[float, ...]) -> tuple[float, ...]:
    roll, pitch, yaw = rpy
    cr, sr = math.cos(roll / 2.0), math.sin(roll / 2.0)
    cp, sp = math.cos(pitch / 2.0), math.sin(pitch / 2.0)
    cy, sy = math.cos(yaw / 2.0), math.sin(yaw / 2.0)
    return (
        cr * cp * cy + sr * sp * sy,
        sr * cp * cy - cr * sp * sy,
        cr * sp * cy + sr * cp * sy,
        cr * cp * sy - sr * sp * cy,
    )


def _resolve_mesh(uri: str, urdf_path: Path) -> Path:
    package_prefix = "package://G-exo/"
    if uri.startswith(package_prefix):
        return (urdf_path.parent.parent / uri[len(package_prefix) :]).resolve()
    if uri.startswith("package://"):
        raise ValueError(f"Unsupported package URI: {uri}")
    path = Path(uri).expanduser()
    return path.resolve() if path.is_absolute() else (urdf_path.parent / path).resolve()


def _required_child(parent: ET.Element, path: str, owner: str) -> ET.Element:
    child = parent.find(path)
    if child is None:
        raise ValueError(f"{owner!r} is missing {path!r}.")
    return child


def _required_id(model: mujoco.MjModel, kind: mujoco.mjtObj, name: str) -> int:
    value = mujoco.mj_name2id(model, kind, name)
    if value < 0:
        raise ValueError(f"MuJoCo model has no {name!r}.")
    return value


def _raw_model(model):
    """Accept either a native MuJoCo model or dm_control's wrapper."""

    return getattr(model, "ptr", model)


def _vector(
    text: str | None,
    length: int,
    default: tuple[float, ...],
) -> tuple[float, ...]:
    values = default if text is None else tuple(float(value) for value in text.split())
    if len(values) != length or not all(math.isfinite(value) for value in values):
        raise ValueError(f"Expected {length} finite values, got {values}.")
    return values


def _format(values) -> str:
    return " ".join(f"{float(value):.12g}" for value in values)
