"""Render the complete G-Exo URDF around a MyoSuite human.

The demo keeps the URDF as one articulated mechanism.  Five MuJoCo mocap
bodies display its links, while human pelvis pose and four hip/knee angles
drive the URDF forward kinematics.  Mocap bodies add no state or dynamics, so
the depRL teacher keeps its original 403 observations and 80 muscle actions.

External assistance is applied separately through MuJoCo ``qfrc_applied``.
This file therefore handles geometry and kinematics only, not assistance.
"""

from __future__ import annotations

import argparse
import importlib.util
import math
import os
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

import mujoco
import mujoco.viewer
import numpy as np


PROJECT_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_URDF_PATH = (
    PROJECT_ROOT / "1.hardware/G-exo_URDF/urdf/G-exo.urdf"
)
DEFAULT_OUTPUT_PATH = (
    PROJECT_ROOT / "RL/output/demo_7_27/generated/myolegs_gexo.xml"
)
DEFAULT_KINESIS_OUTPUT_PATH = (
    PROJECT_ROOT / "RL/output/demo_7_27/generated/kinesis_gexo.xml"
)

LINK_NAMES = (
    "base_link",
    "l_thigh",
    "l_calf",
    "r_thigh",
    "r_calf",
)

# At the neutral pose, the URDF hip-axis midpoint is (0.1475, 0, -0.13)
# relative to base_link.  This mount puts that midpoint near the MyoSuite hip
# midpoint while retaining the exoskeleton's wider motor spacing.
BASE_POSITION_IN_PELVIS = (-0.2035, 0.052, 0.0)

# URDF x/y/z -> MyoSuite pelvis x/-z/y.
BASE_QUATERNION_IN_PELVIS = (
    math.sqrt(0.5),
    -math.sqrt(0.5),
    0.0,
    0.0,
)

# Exoskeleton joint -> (MyoSuite joint, angle sign).
# Signs follow the transformed URDF axes and MyoSuite joint axes.
JOINT_DRIVERS = {
    "l_thigh_joint": ("hip_flexion_l", -1.0),
    "l_calf_joint": ("knee_angle_l", 1.0),
    "r_thigh_joint": ("hip_flexion_r", 1.0),
    "r_calf_joint": ("knee_angle_r", -1.0),
}


@dataclass(frozen=True)
class UrdfJoint:
    name: str
    parent: str
    child: str
    position: tuple[float, ...]
    quaternion: tuple[float, ...]
    axis: tuple[float, ...]
    human_joint: str
    angle_sign: float


class GExoMocapDriver:
    """Update five G-Exo mocap links from current human joint states."""

    def __init__(
        self,
        model: mujoco.MjModel,
        urdf_path: Path = DEFAULT_URDF_PATH,
    ) -> None:
        self.model = model
        self.joints = _read_joints(Path(urdf_path).resolve())
        self.pelvis_id = _required_id(
            model,
            mujoco.mjtObj.mjOBJ_BODY,
            "pelvis",
        )

        self.mocap_ids = {
            link_name: int(
                model.body_mocapid[
                    _required_id(
                        model,
                        mujoco.mjtObj.mjOBJ_BODY,
                        f"gexo_{link_name}",
                    )
                ]
            )
            for link_name in LINK_NAMES
        }

        if any(mocap_id < 0 for mocap_id in self.mocap_ids.values()):
            raise RuntimeError("A generated G-Exo body is not a mocap body.")

        self.human_qpos_addresses = {}

        for human_joint, _ in JOINT_DRIVERS.values():
            joint_id = _required_id(
                model,
                mujoco.mjtObj.mjOBJ_JOINT,
                human_joint,
            )
            self.human_qpos_addresses[human_joint] = int(
                model.jnt_qposadr[joint_id]
            )

        self.pelvis_from_base = _pose_matrix(
            BASE_POSITION_IN_PELVIS,
            BASE_QUATERNION_IN_PELVIS,
        )

    def update(
        self,
        data: mujoco.MjData,
        *,
        run_forward: bool = True,
    ) -> None:
        """Apply human pose to G-Exo and optionally refresh MuJoCo kinematics."""

        world_from_pelvis = _pose_matrix(
            data.xpos[self.pelvis_id],
            data.xquat[self.pelvis_id],
        )
        transforms = {
            "base_link": world_from_pelvis @ self.pelvis_from_base
        }
        pending = list(self.joints)

        while pending:
            unresolved: list[UrdfJoint] = []
            progress = False

            for joint in pending:
                if joint.parent not in transforms:
                    unresolved.append(joint)
                    continue

                angle = (
                    joint.angle_sign
                    * float(
                        data.qpos[
                            self.human_qpos_addresses[joint.human_joint]
                        ]
                    )
                )
                transforms[joint.child] = (
                    transforms[joint.parent]
                    @ _pose_matrix(joint.position, joint.quaternion)
                    @ _axis_angle_matrix(joint.axis, angle)
                )
                progress = True

            if not progress:
                names = ", ".join(joint.name for joint in unresolved)
                raise RuntimeError(f"Cannot resolve URDF joints: {names}")

            pending = unresolved

        for link_name, world_from_link in transforms.items():
            mocap_id = self.mocap_ids[link_name]
            position, quaternion = _matrix_pose(world_from_link)
            data.mocap_pos[mocap_id] = position
            data.mocap_quat[mocap_id] = quaternion

        if run_forward:
            mujoco.mj_forward(self.model, data)


class GExoOverlayViewer:
    """Render a dynamics model through a same-state model with G-Exo meshes."""

    def __init__(
        self,
        human_model_path: Path,
        output_path: Path,
    ) -> None:
        generated_path = build_gexo_overlay_model(
            output_path,
            human_model_path=human_model_path,
        )
        self.model = mujoco.MjModel.from_xml_path(
            str(generated_path)
        )
        self.data = mujoco.MjData(self.model)
        self.overlay = GExoMocapDriver(self.model)
        self.viewer = None

    def sync(self, source_data: mujoco.MjData) -> None:
        """Copy one physical state, update URDF links, and draw one frame."""

        for name in ("qpos", "qvel", "act", "ctrl"):
            source = getattr(source_data, name)
            target = getattr(self.data, name)
            if source.shape != target.shape:
                raise RuntimeError(
                    f"Viewer {name} shape changed: "
                    f"{source.shape} != {target.shape}."
                )
            target[:] = source

        self.data.time = source_data.time
        mujoco.mj_forward(self.model, self.data)
        self.overlay.update(self.data)

        if self.viewer is None:
            self.viewer = mujoco.viewer.launch_passive(
                self.model,
                self.data,
            )

        if self.viewer.is_running():
            self.viewer.cam.lookat[:] = self.data.qpos[:3]
            self.viewer.sync()

    def close(self) -> None:
        if self.viewer is not None:
            self.viewer.close()
            self.viewer = None


def find_myosuite_leg_model() -> Path:
    package = importlib.util.find_spec("myosuite")

    if package is None or not package.submodule_search_locations:
        raise ModuleNotFoundError("MyoSuite is not installed.")

    model_path = (
        Path(package.submodule_search_locations[0])
        / "simhive/myo_sim/leg/myolegs.xml"
    )

    if not model_path.is_file():
        raise FileNotFoundError(f"Missing MyoSuite model: {model_path}")

    return model_path.resolve()


def build_gexo_overlay_model(
    output_path: Path = DEFAULT_OUTPUT_PATH,
    *,
    urdf_path: Path = DEFAULT_URDF_PATH,
    human_model_path: Path | None = None,
) -> Path:
    """Add five visual mocap links, then save and validate the model."""

    output_path = Path(output_path).expanduser().resolve()
    urdf_path = Path(urdf_path).expanduser().resolve()
    human_model_path = (
        find_myosuite_leg_model()
        if human_model_path is None
        else Path(human_model_path).expanduser().resolve()
    )

    links = _read_visual_links(urdf_path)

    # MuJoCo 3.1 (used by Kinesis) predates MjSpec.  Keep the existing MjSpec
    # path for MyoSuite and use a small XML insertion fallback for Kinesis.
    if not hasattr(mujoco, "MjSpec"):
        _build_overlay_xml(
            human_model_path,
            output_path,
            links,
        )
        return _validate_overlay_model(
            human_model_path,
            output_path,
        )

    specification = mujoco.MjSpec.from_file(str(human_model_path))
    asset_root = human_model_path.parent.parent
    specification.compiler.meshdir = str(asset_root)
    specification.compiler.texturedir = str(asset_root)

    original = specification.compile()
    original_dimensions = (original.nq, original.nv, original.nu)

    for link_name in LINK_NAMES:
        link = links[link_name]
        mesh_name = f"gexo_{link_name}_mesh"
        specification.add_mesh(
            name=mesh_name,
            file=str(link["mesh_path"]),
            scale=link["mesh_scale"],
        )
        body = specification.worldbody.add_body(
            name=f"gexo_{link_name}",
            mocap=1,
        )
        body.add_geom(
            name=f"gexo_{link_name}_visual",
            type=mujoco.mjtGeom.mjGEOM_MESH,
            meshname=mesh_name,
            pos=link["position"],
            quat=link["quaternion"],
            rgba=link["color"],
            contype=0,
            conaffinity=0,
            group=2,
            mass=0.0,
        )

    combined = specification.compile()
    combined_dimensions = (combined.nq, combined.nv, combined.nu)

    if combined_dimensions != original_dimensions or combined.nmocap != 5:
        raise RuntimeError(
            "G-Exo visual model changed the policy interface: "
            f"before={original_dimensions}, after={combined_dimensions}, "
            f"nmocap={combined.nmocap}."
        )

    output_path.parent.mkdir(parents=True, exist_ok=True)
    specification.to_file(str(output_path))
    return _validate_overlay_model(human_model_path, output_path)


def _build_overlay_xml(
    human_model_path: Path,
    output_path: Path,
    links: dict[str, dict[str, object]],
) -> None:
    """Insert the five visual links using only Python's XML library."""

    source_directory = human_model_path.parent
    output_directory = output_path.parent
    source_root = ET.parse(human_model_path).getroot()
    source_compiler = source_root.find("compiler")

    output_directory.mkdir(parents=True, exist_ok=True)
    original_model = mujoco.MjModel.from_xml_path(
        str(human_model_path)
    )
    # Expand all nested Kinesis includes before relocating the XML.
    mujoco.mj_saveLastXML(str(output_path), original_model)
    tree = ET.parse(output_path)
    root = tree.getroot()

    # MuJoCo 3.1 serializes both legacy capacity fields and ``memory``, but
    # refuses to parse that combination again.  Preserve the source memory
    # budget and remove only the mutually exclusive generated fields.
    size = root.find("size")
    if size is not None and size.get("memory") is not None:
        size.attrib.pop("njmax", None)
        size.attrib.pop("nconmax", None)

    # mj_saveLastXML preserves the old relative compiler directories.  Point
    # them back to the original Kinesis assets from the new output location.
    compiler = root.find("compiler")
    if compiler is not None:
        for attribute in ("meshdir", "texturedir"):
            source_value = (
                None
                if source_compiler is None
                else source_compiler.get(attribute)
            )
            source_asset_directory = (
                source_directory
                if not source_value
                else source_directory / source_value
            )
            compiler.set(
                attribute,
                _relative_path(
                    source_asset_directory,
                    output_directory,
                )
            )

    asset = root.find("asset")
    worldbody = root.find("worldbody")
    if asset is None or worldbody is None:
        raise ValueError("Human MJCF must contain asset and worldbody sections.")

    for link_name in LINK_NAMES:
        link = links[link_name]
        mesh_name = f"gexo_{link_name}_mesh"
        ET.SubElement(
            asset,
            "mesh",
            {
                "name": mesh_name,
                # Absolute URDF meshes must not inherit Kinesis' meshdir.
                "file": str(Path(link["mesh_path"]).resolve()),
                "scale": _format_vector(link["mesh_scale"]),
            },
        )
        body = ET.SubElement(
            worldbody,
            "body",
            {
                "name": f"gexo_{link_name}",
                "mocap": "true",
            },
        )
        ET.SubElement(
            body,
            "geom",
            {
                "name": f"gexo_{link_name}_visual",
                "type": "mesh",
                "mesh": mesh_name,
                "pos": _format_vector(link["position"]),
                "quat": _format_vector(link["quaternion"]),
                "rgba": _format_vector(link["color"]),
                "contype": "0",
                "conaffinity": "0",
                "group": "2",
                "mass": "0",
            },
        )

    tree.write(
        output_path,
        encoding="utf-8",
        xml_declaration=True,
    )


def _validate_overlay_model(
    human_model_path: Path,
    output_path: Path,
) -> Path:
    """Prove that visual URDF links did not alter the policy interface."""

    original = mujoco.MjModel.from_xml_path(str(human_model_path))
    combined = mujoco.MjModel.from_xml_path(str(output_path))
    original_dimensions = (original.nq, original.nv, original.nu)
    combined_dimensions = (combined.nq, combined.nv, combined.nu)

    if combined_dimensions != original_dimensions or combined.nmocap != 5:
        raise RuntimeError(
            "G-Exo visual model changed the policy interface: "
            f"before={original_dimensions}, after={combined_dimensions}, "
            f"nmocap={combined.nmocap}."
        )

    for link_name in LINK_NAMES:
        _required_id(
            combined,
            mujoco.mjtObj.mjOBJ_BODY,
            f"gexo_{link_name}",
        )

    return output_path


def _format_vector(values: object) -> str:
    """Format an MJCF numeric vector without Python container syntax."""

    return " ".join(f"{float(value):.12g}" for value in values)


def _relative_path(path: object, start: Path) -> str:
    """Return a MuJoCo 3.1-compatible path from the generated XML."""

    return os.path.relpath(
        str(Path(path).expanduser().resolve()),
        str(start.resolve()),
    )


def _read_visual_links(urdf_path: Path) -> dict[str, dict[str, object]]:
    if not urdf_path.is_file():
        raise FileNotFoundError(f"Missing G-Exo URDF: {urdf_path}")

    root = ET.parse(urdf_path).getroot()
    links = {}

    for link_name in LINK_NAMES:
        link = root.find(f"./link[@name='{link_name}']")

        if link is None:
            raise ValueError(f"URDF has no link {link_name!r}.")

        visual = _required_child(link, "visual", link_name)
        mesh = _required_child(visual, "geometry/mesh", link_name)
        mesh_uri = mesh.get("filename")

        if not mesh_uri:
            raise ValueError(f"URDF link {link_name!r} has no mesh filename.")

        mesh_path = _resolve_mesh_path(mesh_uri, urdf_path)
        position, rpy = _origin(visual)
        color_element = visual.find("material/color")
        links[link_name] = {
            "mesh_path": mesh_path,
            "mesh_scale": _vector(
                mesh.get("scale"), 3, (1.0, 1.0, 1.0)
            ),
            "position": position,
            "quaternion": _rpy_to_quaternion(rpy),
            "color": _vector(
                None
                if color_element is None
                else color_element.get("rgba"),
                4,
                (0.85, 0.85, 0.85, 1.0),
            ),
        }

        if not mesh_path.is_file():
            raise FileNotFoundError(f"Missing mesh: {mesh_path}")

    return links


def _read_joints(urdf_path: Path) -> tuple[UrdfJoint, ...]:
    root = ET.parse(urdf_path).getroot()
    joints = []

    for joint_name, driver in JOINT_DRIVERS.items():
        joint = root.find(f"./joint[@name='{joint_name}']")

        if joint is None:
            raise ValueError(f"URDF has no joint {joint_name!r}.")

        parent = _required_child(joint, "parent", joint_name).get("link")
        child = _required_child(joint, "child", joint_name).get("link")
        axis_element = _required_child(joint, "axis", joint_name)

        if not parent or not child:
            raise ValueError(f"URDF joint {joint_name!r} has empty links.")

        position, rpy = _origin(joint)
        human_joint, angle_sign = driver
        joints.append(
            UrdfJoint(
                name=joint_name,
                parent=parent,
                child=child,
                position=position,
                quaternion=_rpy_to_quaternion(rpy),
                axis=_vector(
                    axis_element.get("xyz"),
                    3,
                    (1.0, 0.0, 0.0),
                ),
                human_joint=human_joint,
                angle_sign=angle_sign,
            )
        )

    return tuple(joints)


def _pose_matrix(
    position: tuple[float, ...] | np.ndarray,
    quaternion: tuple[float, ...] | np.ndarray,
) -> np.ndarray:
    result = np.eye(4, dtype=np.float64)
    rotation = np.empty(9, dtype=np.float64)
    mujoco.mju_quat2Mat(rotation, np.asarray(quaternion, dtype=np.float64))
    result[:3, :3] = rotation.reshape(3, 3)
    result[:3, 3] = np.asarray(position, dtype=np.float64)
    return result


def _axis_angle_matrix(axis: tuple[float, ...], angle: float) -> np.ndarray:
    quaternion = np.empty(4, dtype=np.float64)
    mujoco.mju_axisAngle2Quat(
        quaternion,
        np.asarray(axis, dtype=np.float64),
        angle,
    )
    return _pose_matrix((0.0, 0.0, 0.0), quaternion)


def _matrix_pose(matrix: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    quaternion = np.empty(4, dtype=np.float64)
    mujoco.mju_mat2Quat(
        quaternion,
        np.ascontiguousarray(matrix[:3, :3]).reshape(9),
    )
    return matrix[:3, 3], quaternion


def _resolve_mesh_path(mesh_uri: str, urdf_path: Path) -> Path:
    prefix = "package://G-exo/"

    if mesh_uri.startswith(prefix):
        return (
            # Kinesis uses Python 3.8, which has no str.removeprefix().
            urdf_path.parent.parent / mesh_uri[len(prefix) :]
        ).resolve()

    if mesh_uri.startswith("package://"):
        raise ValueError(f"Unsupported package URI: {mesh_uri}")

    path = Path(mesh_uri).expanduser()
    return (
        path.resolve()
        if path.is_absolute()
        else (urdf_path.parent / path).resolve()
    )


def _required_child(
    parent: ET.Element,
    path: str,
    owner_name: str,
) -> ET.Element:
    child = parent.find(path)

    if child is None:
        raise ValueError(f"URDF {owner_name!r} is missing {path!r}.")

    return child


def _origin(element: ET.Element) -> tuple[tuple[float, ...], tuple[float, ...]]:
    origin = element.find("origin")

    if origin is None:
        return (0.0, 0.0, 0.0), (0.0, 0.0, 0.0)

    return (
        _vector(origin.get("xyz"), 3, (0.0, 0.0, 0.0)),
        _vector(origin.get("rpy"), 3, (0.0, 0.0, 0.0)),
    )


def _vector(
    text: str | None,
    length: int,
    default: tuple[float, ...],
) -> tuple[float, ...]:
    values = default if text is None else tuple(float(x) for x in text.split())

    if len(values) != length or not all(math.isfinite(x) for x in values):
        raise ValueError(f"Expected {length} finite values, got {values}.")

    return values


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


def _required_id(
    model: mujoco.MjModel,
    object_type: mujoco.mjtObj,
    name: str,
) -> int:
    object_id = mujoco.mj_name2id(model, object_type, name)

    if object_id < 0:
        raise ValueError(f"MuJoCo model has no object {name!r}.")

    return object_id


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Generate a MyoSuite model with visual G-Exo mocap links."
    )
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT_PATH)
    parser.add_argument("--urdf", type=Path, default=DEFAULT_URDF_PATH)
    parser.add_argument("--human-model", type=Path, default=None)
    arguments = parser.parse_args()

    output_path = build_gexo_overlay_model(
        arguments.output,
        urdf_path=arguments.urdf,
        human_model_path=arguments.human_model,
    )
    model = mujoco.MjModel.from_xml_path(str(output_path))
    print(f"generated model: {output_path}")
    print(
        f"dimensions: nq={model.nq}, nv={model.nv}, "
        f"nu={model.nu}, nmocap={model.nmocap}"
    )
    print("G-Exo mode: kinematic visual model")


if __name__ == "__main__":
    main()
