"""Minimal ROS/Gazebo transport for the fixed assistance bench."""

from __future__ import annotations

import os
from pathlib import Path
import signal
import socket
import subprocess
import sys
import threading
import time
from typing import TextIO

import numpy as np

from RL.env.gazebo.bench import JOINT_NAMES, LINK_NAMES, LinkKinematics


class GazeboLauncher:
    """Own a private ROS master and paused headless Gazebo server."""

    def __init__(
        self,
        runtime_dir: str | Path,
        *,
        ros_port: int = 11318,
        gazebo_port: int = 11348,
        render: bool = False,
    ) -> None:
        self.runtime_dir = Path(runtime_dir).expanduser().resolve()
        self.ros_port = int(ros_port)
        self.gazebo_port = int(gazebo_port)
        self.render = bool(render)
        self.processes: list[subprocess.Popen] = []
        self._logs: list[TextIO] = []

    def start(self) -> None:
        self.runtime_dir.mkdir(parents=True, exist_ok=True)
        os.environ.update(self.environment())
        self._start(
            "roscore",
            ("/opt/ros/noetic/bin/roscore", "-p", str(self.ros_port)),
        )
        _wait_tcp("127.0.0.1", self.ros_port, timeout_s=20.0)
        self._start(
            "gzserver",
            (
                "/usr/bin/gzserver",
                "-u",
                "-s",
                "/opt/ros/noetic/lib/libgazebo_ros_api_plugin.so",
                "/usr/share/gazebo-11/worlds/empty.world",
            ),
        )
        if self.render:
            self._start("gzclient", ("/usr/bin/gzclient",))

    def environment(self) -> dict[str, str]:
        ros_home = self.runtime_dir / "ros"
        gazebo_home = self.runtime_dir / "gazebo"
        ros_home.mkdir(parents=True, exist_ok=True)
        gazebo_home.mkdir(parents=True, exist_ok=True)
        existing_library_path = os.environ.get("LD_LIBRARY_PATH", "")
        existing_path = os.environ.get("PATH", "")
        return {
            "ROS_MASTER_URI": f"http://127.0.0.1:{self.ros_port}",
            "GAZEBO_MASTER_URI": f"http://127.0.0.1:{self.gazebo_port}",
            "ROS_HOME": str(ros_home),
            "ROS_LOG_DIR": str(ros_home / "log"),
            "GAZEBO_LOG_PATH": str(gazebo_home),
            "GAZEBO_IP": "127.0.0.1",
            "IGN_IP": "127.0.0.1",
            "ROS_DISTRO": "noetic",
            "ROS_VERSION": "1",
            "ROS_PYTHON_VERSION": "3",
            "ROS_ETC_DIR": "/opt/ros/noetic/etc/ros",
            "ROS_ROOT": "/opt/ros/noetic/share/ros",
            "ROS_PACKAGE_PATH": "/opt/ros/noetic/share",
            "CMAKE_PREFIX_PATH": "/opt/ros/noetic",
            "PKG_CONFIG_PATH": (
                "/opt/ros/noetic/lib/pkgconfig:"
                "/opt/ros/noetic/lib/x86_64-linux-gnu/pkgconfig"
            ),
            "PATH": f"/opt/ros/noetic/bin:{existing_path}",
            "LD_LIBRARY_PATH": (
                "/opt/ros/noetic/lib:/opt/ros/noetic/lib/x86_64-linux-gnu:"
                + existing_library_path
            ).rstrip(":"),
        }

    def close(self) -> None:
        for process in reversed(self.processes):
            if process.poll() is None:
                os.killpg(process.pid, signal.SIGTERM)
        deadline = time.monotonic() + 5.0
        for process in reversed(self.processes):
            remaining = max(deadline - time.monotonic(), 0.0)
            try:
                process.wait(timeout=remaining)
            except subprocess.TimeoutExpired:
                os.killpg(process.pid, signal.SIGKILL)
        for stream in self._logs:
            stream.close()
        self.processes.clear()
        self._logs.clear()

    def _start(self, name: str, command: tuple[str, ...]) -> None:
        stream = (self.runtime_dir / f"{name}.log").open("w", encoding="utf-8")
        child_environment = os.environ.copy()
        # ROS Noetic's launch scripts use Ubuntu's Python 3.8.  The policy
        # process intentionally runs in the Python 3.11 hackthon environment;
        # leaking its PYTHONPATH makes roscore import incompatible packages.
        child_environment["PYTHONPATH"] = (
            "/opt/ros/noetic/lib/python3/dist-packages:/usr/lib/python3/dist-packages"
        )
        child_environment.pop("PYTHONHOME", None)
        process = subprocess.Popen(
            command,
            env=child_environment,
            stdout=stream,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
        self._logs.append(stream)
        self.processes.append(process)

    def __enter__(self) -> "GazeboLauncher":
        self.start()
        return self

    def __exit__(self, *_args) -> None:
        self.close()


class GazeboRosBackend:
    """Apply one control interval of effort and read four joints/four links."""

    def __init__(
        self,
        urdf_path: str | Path,
        *,
        model_name: str = "gexo_sim2sim",
        control_dt: float = 0.02,
        service_timeout_s: float = 30.0,
    ) -> None:
        _append_ros_python_paths()
        import rospy
        from gazebo_msgs.srv import (
            ApplyJointEffort,
            GetJointProperties,
            GetLinkState,
            JointRequest,
            SetModelConfiguration,
            SpawnModel,
        )
        from std_srvs.srv import Empty
        from rosgraph_msgs.msg import Clock

        self.rospy = rospy
        self.model_name = str(model_name)
        self.control_dt = float(control_dt)
        self.urdf_xml = (
            Path(urdf_path)
            .expanduser()
            .resolve(strict=True)
            .read_text(encoding="utf-8")
        )
        if not rospy.core.is_initialized():
            rospy.init_node("gexo_gazebo_sim2sim", anonymous=True, disable_signals=True)
        rospy.set_param("/use_sim_time", True)
        services = {
            "spawn": ("/gazebo/spawn_urdf_model", SpawnModel),
            "pause": ("/gazebo/pause_physics", Empty),
            "unpause": ("/gazebo/unpause_physics", Empty),
            "reset_simulation": ("/gazebo/reset_simulation", Empty),
            "clear_joint_forces": (
                "/gazebo/clear_joint_forces",
                JointRequest,
            ),
            "set_configuration": (
                "/gazebo/set_model_configuration",
                SetModelConfiguration,
            ),
            "apply": ("/gazebo/apply_joint_effort", ApplyJointEffort),
            "joint": ("/gazebo/get_joint_properties", GetJointProperties),
            "link": ("/gazebo/get_link_state", GetLinkState),
        }
        for path, _ in services.values():
            rospy.wait_for_service(path, timeout=service_timeout_s)
        for name, (path, service_type) in services.items():
            setattr(self, name, rospy.ServiceProxy(path, service_type, persistent=True))

        self._clock = 0.0
        self._spawned = False
        self._clock_condition = threading.Condition()

        def on_clock(message: Clock) -> None:
            with self._clock_condition:
                self._clock = message.clock.to_sec()
                self._clock_condition.notify_all()

        self._clock_subscription = rospy.Subscriber(
            "/clock", Clock, on_clock, queue_size=1
        )
        self.pause()

    def reset(self, initial_q_deployment: np.ndarray) -> None:
        from geometry_msgs.msg import Pose

        self.pause()
        if not self._spawned:
            response = self.spawn(
                self.model_name,
                self.urdf_xml,
                "",
                Pose(),
                "world",
            )
            if not response.success:
                raise RuntimeError(f"Gazebo spawn failed: {response.status_message}")
            deadline = time.monotonic() + 10.0
            while time.monotonic() < deadline:
                probe = self.joint(f"{self.model_name}::{JOINT_NAMES[0]}")
                if probe.success and probe.position:
                    break
                time.sleep(0.05)
            else:
                raise RuntimeError(
                    "Gazebo spawned the model but its joints are unavailable."
                )
            self._spawned = True
        else:
            for joint_name in JOINT_NAMES:
                self.clear_joint_forces(f"{self.model_name}::{joint_name}")
            self.reset_simulation()
        q_urdf = np.asarray(initial_q_deployment, dtype=np.float64) * np.asarray(
            (-1.0, 1.0, 1.0, -1.0)
        )
        response = self.set_configuration(
            self.model_name,
            "robot_description",
            list(JOINT_NAMES),
            q_urdf.tolist(),
        )
        if not response.success:
            raise RuntimeError(
                f"Gazebo joint initialization failed: {response.status_message}"
            )
        with self._clock_condition:
            self._clock = 0.0

    def step(self, total_torque_urdf: np.ndarray) -> float:
        torque = np.asarray(total_torque_urdf, dtype=np.float64)
        if torque.shape != (4,) or not np.all(np.isfinite(torque)):
            raise ValueError("total_torque_urdf must be finite with shape (4,).")
        start = self.clock
        duration = self.rospy.Duration.from_sec(self.control_dt * 1.25)
        for joint_name, effort in zip(JOINT_NAMES, torque):
            response = self.apply(
                f"{self.model_name}::{joint_name}",
                float(effort),
                self.rospy.Time(0),
                duration,
            )
            if not response.success:
                raise RuntimeError(
                    f"Applying effort to {joint_name} failed: {response.status_message}"
                )
        self.unpause()
        target = start + self.control_dt
        deadline = time.monotonic() + 5.0
        with self._clock_condition:
            while self._clock < target and time.monotonic() < deadline:
                self._clock_condition.wait(timeout=0.05)
        self.pause()
        elapsed = self.clock - start
        if elapsed <= 0.0:
            raise RuntimeError("Gazebo simulation clock did not advance.")
        return elapsed

    def read(self) -> tuple[np.ndarray, np.ndarray, tuple[LinkKinematics, ...]]:
        q = []
        dq = []
        for joint_name in JOINT_NAMES:
            response = self.joint(f"{self.model_name}::{joint_name}")
            if not response.success or not response.position or not response.rate:
                raise RuntimeError(
                    f"Reading {joint_name} failed: {response.status_message}"
                )
            q.append(response.position[0])
            dq.append(response.rate[0])
        links = []
        for link_name in LINK_NAMES:
            response = self.link(f"{self.model_name}::{link_name}", "world")
            if not response.success:
                raise RuntimeError(
                    f"Reading {link_name} failed: {response.status_message}"
                )
            pose = response.link_state.pose
            twist = response.link_state.twist
            links.append(
                LinkKinematics(
                    quaternion_xyzw=np.asarray(
                        (pose.orientation.x, pose.orientation.y, pose.orientation.z, pose.orientation.w)
                    ),
                    linear_velocity_world=np.asarray(
                        (twist.linear.x, twist.linear.y, twist.linear.z)
                    ),
                    angular_velocity_world=np.asarray(
                        (twist.angular.x, twist.angular.y, twist.angular.z)
                    ),
                )
            )
        return np.asarray(q), np.asarray(dq), tuple(links)

    @property
    def clock(self) -> float:
        with self._clock_condition:
            return float(self._clock)

    def close(self) -> None:
        self._clock_subscription.unregister()
        for name in (
            "spawn",
            "pause",
            "unpause",
            "reset_simulation",
            "clear_joint_forces",
            "set_configuration",
            "apply",
            "joint",
            "link",
        ):
            getattr(self, name).close()


def _wait_tcp(host: str, port: int, *, timeout_s: float) -> None:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return
        except OSError:
            time.sleep(0.1)
    raise TimeoutError(f"Timed out waiting for {host}:{port}.")


def _append_ros_python_paths() -> None:
    """Expose Noetic's pure-Python modules after the active Conda packages."""

    for value in (
        "/opt/ros/noetic/lib/python3/dist-packages",
        "/usr/lib/python3/dist-packages",
    ):
        if value not in sys.path:
            sys.path.append(value)


__all__ = ["GazeboLauncher", "GazeboRosBackend"]
