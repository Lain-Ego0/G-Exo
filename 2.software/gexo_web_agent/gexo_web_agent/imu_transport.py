"""Direct ROS 2 sensor_msgs/Imu subscriptions for read-only telemetry."""
from __future__ import annotations

import logging
import threading
import time
from typing import Callable, Optional

from .config import ImuChannelConfig
from .schemas import ImuReading, JointId, QuaternionData, Vector3Data

logger = logging.getLogger(__name__)
SampleCallback = Callable[[JointId, ImuReading, float, float], None]


class ImuRos2Transport:
    def __init__(self, channels: list[ImuChannelConfig], node_name: str = "gexo_imu_web") -> None:
        self._channels = channels
        self._node_name = node_name
        self._sample_callback: Optional[SampleCallback] = None
        self._node = None
        self._executor = None
        self._rclpy = None
        self._thread: threading.Thread | None = None
        self._owns_context = False

    def set_sample_callback(self, callback: SampleCallback) -> None:
        self._sample_callback = callback

    def start(self) -> None:
        if self._thread is not None:
            return
        import rclpy
        from rclpy.qos import HistoryPolicy, QoSProfile, ReliabilityPolicy
        from sensor_msgs.msg import Imu

        self._rclpy = rclpy
        if not rclpy.ok():
            rclpy.init()
            self._owns_context = True
        self._node = rclpy.create_node(self._node_name)
        qos = QoSProfile(
            depth=5,
            history=HistoryPolicy.KEEP_LAST,
            reliability=ReliabilityPolicy.BEST_EFFORT,
        )
        for channel in self._channels:
            self._node.create_subscription(
                Imu,
                channel.topic,
                self._make_callback(channel.joint),
                qos,
            )
        self._executor = rclpy.executors.SingleThreadedExecutor()
        self._executor.add_node(self._node)
        self._thread = threading.Thread(target=self._spin, name="imu-ros2-spin", daemon=True)
        self._thread.start()
        logger.info("subscribed to IMU topics: %s", [channel.topic for channel in self._channels])

    def stop(self) -> None:
        if self._rclpy is None:
            return
        if self._executor is not None:
            self._executor.shutdown()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        if self._node is not None:
            self._node.destroy_node()
        self._executor = None
        self._node = None
        if self._owns_context and self._rclpy.ok():
            self._rclpy.shutdown()
        self._owns_context = False

    def _spin(self) -> None:
        try:
            self._executor.spin()
        except Exception:
            logger.exception("IMU ROS executor exited abnormally")

    def _make_callback(self, joint: JointId):
        def callback(message) -> None:
            sample_callback = self._sample_callback
            if sample_callback is None:
                return
            received_wall_ms = time.time() * 1000.0
            received_monotonic = time.monotonic()
            reading = ImuReading(
                frame_id=message.header.frame_id,
                timestamp_ms=(
                    float(message.header.stamp.sec) * 1000.0
                    + float(message.header.stamp.nanosec) / 1_000_000.0
                ),
                orientation=QuaternionData(
                    x=message.orientation.x,
                    y=message.orientation.y,
                    z=message.orientation.z,
                    w=message.orientation.w,
                ),
                angular_velocity=Vector3Data(
                    x=message.angular_velocity.x,
                    y=message.angular_velocity.y,
                    z=message.angular_velocity.z,
                ),
                linear_acceleration=Vector3Data(
                    x=message.linear_acceleration.x,
                    y=message.linear_acceleration.y,
                    z=message.linear_acceleration.z,
                ),
                orientation_covariance_known=(
                    len(message.orientation_covariance) > 0
                    and message.orientation_covariance[0] != -1.0
                ),
            )
            sample_callback(joint, reading, received_wall_ms, received_monotonic)

        return callback
