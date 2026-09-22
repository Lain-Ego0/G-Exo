"""Backend-neutral math for the fixed-base Gazebo assistance bench.

The bench is deliberately smaller than a walking-human simulation.  It replays
one measured four-joint gait cycle on the real G-Exo URDF and measures how much
trajectory-driver effort remains after the frozen Actor adds assistance.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import xml.etree.ElementTree as ET

import numpy as np

from RL.env.actor_observation import GRAVITY_M_S2


JOINT_NAMES = (
    "l_thigh_joint",
    "l_calf_joint",
    "r_thigh_joint",
    "r_calf_joint",
)
LINK_NAMES = (
    "l_thigh",
    "l_calf",
    "r_thigh",
    "r_calf",
)

# q_deployment = URDF_TO_DEPLOYMENT_SIGN * q_urdf.  The same relation applies
# to torque so that mechanical power is invariant under the coordinate change.
URDF_TO_DEPLOYMENT_SIGN = np.asarray((-1.0, 1.0, 1.0, -1.0), dtype=np.float64)
DEPLOYMENT_LOWER_RAD = np.asarray(
    (-0.3491, 0.0, -0.3491, 0.0), dtype=np.float64
)
DEPLOYMENT_UPPER_RAD = np.asarray(
    (1.5708, 1.9199, 1.5708, 1.9199), dtype=np.float64
)

# MyoAssist dynamic-URDF IMU sites are Rx(-90 deg) relative to their segment.
# Sensor vectors are therefore Rx(+90 deg) times a vector in the link frame.
LINK_TO_MYOASSIST_IMU = np.asarray(
    ((1.0, 0.0, 0.0), (0.0, 0.0, -1.0), (0.0, 1.0, 0.0)),
    dtype=np.float64,
)


def build_fixed_bench_urdf(
    source: str | Path,
    output: str | Path,
    *,
    joint_damping: float = 2.0,
    joint_friction: float = 0.05,
) -> Path:
    """Create an audit-only URDF with ``base_link`` fixed to Gazebo world."""

    source_path = Path(source).expanduser().resolve(strict=True)
    output_path = Path(output).expanduser().resolve()
    if joint_damping < 0.0 or joint_friction < 0.0:
        raise ValueError("joint_damping and joint_friction must be non-negative.")
    root = ET.parse(source_path).getroot()
    if root.find("link[@name='world']") is not None:
        raise ValueError("Source URDF already defines a world link.")

    world = ET.Element("link", {"name": "world"})
    fixed = ET.Element("joint", {"name": "world_to_gexo", "type": "fixed"})
    ET.SubElement(fixed, "origin", {"xyz": "0 0 1.05", "rpy": "0 0 0"})
    ET.SubElement(fixed, "parent", {"link": "world"})
    ET.SubElement(fixed, "child", {"link": "base_link"})
    root.insert(0, world)
    root.insert(1, fixed)

    package_root = source_path.parent.parent
    for mesh in root.iter("mesh"):
        filename = mesh.get("filename", "")
        prefix = "package://G-exo/"
        if filename.startswith(prefix):
            resolved = (package_root / filename[len(prefix) :]).resolve(strict=True)
            mesh.set("filename", resolved.as_uri())

    for joint in root.findall("joint"):
        if joint.get("type") != "revolute":
            continue
        dynamics = joint.find("dynamics")
        if dynamics is None:
            dynamics = ET.SubElement(joint, "dynamics")
        dynamics.set("damping", f"{float(joint_damping):.12g}")
        dynamics.set("friction", f"{float(joint_friction):.12g}")

    output_path.parent.mkdir(parents=True, exist_ok=True)
    ET.indent(root, space="  ")
    ET.ElementTree(root).write(
        output_path,
        encoding="utf-8",
        xml_declaration=True,
    )
    return output_path


class GaitCycleReference:
    """Periodic q/dq reference interpolated from the frozen MyoAssist cycle."""

    def __init__(
        self,
        path: str | Path,
        *,
        speed_m_s: float = 1.0,
        period_steps: int = 50,
        control_dt: float = 0.02,
    ) -> None:
        if period_steps < 4:
            raise ValueError("period_steps must be at least four.")
        if control_dt <= 0.0:
            raise ValueError("control_dt must be positive.")
        data = json.loads(
            Path(path).expanduser().resolve(strict=True).read_text(
                encoding="utf-8"
            )
        )
        speeds = np.asarray(data["speeds_m_s"], dtype=np.float64)
        means = np.asarray(data["joint_q_mean"], dtype=np.float64)
        if means.ndim != 3 or means.shape[0] != len(speeds) or means.shape[2] != 4:
            raise ValueError("Motion reference must have shape [speed, phase, 4].")
        if speed_m_s < speeds[0] or speed_m_s > speeds[-1]:
            raise ValueError(
                f"speed_m_s must be inside [{speeds[0]}, {speeds[-1]}]."
            )
        self.cycle_q = np.stack(
            [
                np.interp(speed_m_s, speeds, means[:, phase, joint])
                for phase in range(means.shape[1])
                for joint in range(4)
            ]
        ).reshape(means.shape[1], 4)
        self.cycle_q = np.clip(
            self.cycle_q,
            DEPLOYMENT_LOWER_RAD,
            DEPLOYMENT_UPPER_RAD,
        )
        self.speed_m_s = float(speed_m_s)
        self.period_steps = int(period_steps)
        self.control_dt = float(control_dt)

    def sample(self, step: int) -> tuple[np.ndarray, np.ndarray]:
        phase = (int(step) % self.period_steps) / self.period_steps
        q = self._at_phase(phase)
        phase_delta = 1.0 / self.period_steps
        dq = (
            self._at_phase(phase + phase_delta)
            - self._at_phase(phase - phase_delta)
        ) / (2.0 * self.control_dt)
        return q.astype(np.float32), dq.astype(np.float32)

    def _at_phase(self, phase: float) -> np.ndarray:
        position = (phase % 1.0) * len(self.cycle_q)
        lower = int(np.floor(position)) % len(self.cycle_q)
        upper = (lower + 1) % len(self.cycle_q)
        fraction = position - np.floor(position)
        return (1.0 - fraction) * self.cycle_q[lower] + fraction * self.cycle_q[upper]


@dataclass(frozen=True)
class LinkKinematics:
    """One Gazebo link state expressed in world coordinates."""

    quaternion_xyzw: np.ndarray
    linear_velocity_world: np.ndarray
    angular_velocity_world: np.ndarray


class GazeboSensorAssembler:
    """Build the shared 32-D frame from joint and link states."""

    def __init__(self, *, control_dt: float = 0.02) -> None:
        self.control_dt = float(control_dt)
        self._previous_linear_velocity: np.ndarray | None = None

    def reset(self) -> None:
        self._previous_linear_velocity = None

    def build(
        self,
        q_urdf: np.ndarray,
        dq_urdf: np.ndarray,
        links: tuple[LinkKinematics, ...],
        *,
        elapsed_s: float | None = None,
    ) -> np.ndarray:
        if len(links) != 4:
            raise ValueError("Exactly four link states are required.")
        q = _vector4(q_urdf, "q_urdf") * URDF_TO_DEPLOYMENT_SIGN
        dq = _vector4(dq_urdf, "dq_urdf") * URDF_TO_DEPLOYMENT_SIGN
        linear_velocity = np.stack(
            [np.asarray(link.linear_velocity_world, dtype=np.float64) for link in links]
        )
        dt = self.control_dt if elapsed_s is None else float(elapsed_s)
        if dt <= 0.0 or self._previous_linear_velocity is None:
            acceleration_world = np.zeros((4, 3), dtype=np.float64)
        else:
            acceleration_world = (
                linear_velocity - self._previous_linear_velocity
            ) / dt
        self._previous_linear_velocity = linear_velocity.copy()

        gravity_world = np.asarray((0.0, 0.0, -GRAVITY_M_S2))
        gyro = []
        specific_force = []
        for index, link in enumerate(links):
            world_from_link = quaternion_xyzw_to_matrix(link.quaternion_xyzw)
            link_from_world = world_from_link.T
            gyro_link = link_from_world @ np.asarray(
                link.angular_velocity_world, dtype=np.float64
            )
            force_link = link_from_world @ (
                acceleration_world[index] - gravity_world
            )
            gyro.append(LINK_TO_MYOASSIST_IMU @ gyro_link)
            specific_force.append(LINK_TO_MYOASSIST_IMU @ force_link)

        frame = np.concatenate(
            (q, dq, np.asarray(gyro).reshape(-1), np.asarray(specific_force).reshape(-1))
        ).astype(np.float32)
        if frame.shape != (32,) or not np.all(np.isfinite(frame)):
            raise FloatingPointError("Gazebo sensor frame is invalid.")
        return frame


def quaternion_xyzw_to_matrix(value: np.ndarray) -> np.ndarray:
    quaternion = np.asarray(value, dtype=np.float64)
    if quaternion.shape != (4,) or not np.all(np.isfinite(quaternion)):
        raise ValueError("quaternion_xyzw must be finite with shape (4,).")
    norm = float(np.linalg.norm(quaternion))
    if norm <= 1.0e-12:
        raise ValueError("Quaternion norm is zero.")
    x, y, z, w = quaternion / norm
    return np.asarray(
        (
            (1.0 - 2.0 * (y * y + z * z), 2.0 * (x * y - z * w), 2.0 * (x * z + y * w)),
            (2.0 * (x * y + z * w), 1.0 - 2.0 * (x * x + z * z), 2.0 * (y * z - x * w)),
            (2.0 * (x * z - y * w), 2.0 * (y * z + x * w), 1.0 - 2.0 * (x * x + y * y)),
        ),
        dtype=np.float64,
    )


def deployment_to_urdf(value: np.ndarray) -> np.ndarray:
    return _vector4(value, "deployment_value") * URDF_TO_DEPLOYMENT_SIGN


def _vector4(value: np.ndarray, name: str) -> np.ndarray:
    array = np.asarray(value, dtype=np.float64)
    if array.shape != (4,) or not np.all(np.isfinite(array)):
        raise ValueError(f"{name} must be finite with shape (4,).")
    return array


__all__ = [
    "DEPLOYMENT_LOWER_RAD",
    "DEPLOYMENT_UPPER_RAD",
    "GaitCycleReference",
    "GazeboSensorAssembler",
    "JOINT_NAMES",
    "LINK_NAMES",
    "LinkKinematics",
    "URDF_TO_DEPLOYMENT_SIGN",
    "build_fixed_bench_urdf",
    "deployment_to_urdf",
    "quaternion_xyzw_to_matrix",
]
