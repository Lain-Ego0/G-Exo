"""Bridge transports + RosBridgeAdapter.

`RosBridgeAdapter` is the ONLY entry point the rest of the app uses to talk to
the controller.  It owns a `BridgeTransport` implementation:

- `MockTransport`  — in-process, embeds `MockControllerCore`; works anywhere
  (no ROS 2 required, acceptance test #18).
- `Ros2Transport`  — single topic (`std_msgs/String` + JSON), rclpy imported
  lazily inside `start()` so the package imports fine on machines without ROS.

Wire schema knowledge (JSON envelope, `source` filtering, message typing)
lives HERE and nowhere above.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from typing import Any, Callable, Optional, Protocol

from .mock_controller_core import MockControllerCore
from .schemas import (
    BridgeCommand,
    BridgeResult,
    BridgeState,
    parse_bridge_message,
)

logger = logging.getLogger(__name__)

MessageCallback = Callable[[dict[str, Any]], None]


class BridgeTransport(Protocol):
    def start(self) -> None: ...

    def stop(self) -> None: ...

    def publish_command(self, payload: dict[str, Any]) -> None:
        """Fire-and-forget, thread-safe."""

    def set_message_callback(self, cb: MessageCallback) -> None:
        """cb receives every decoded JSON dict; called from the transport's
        own thread and must be non-blocking."""


# ---------------------------------------------------------------------------
# Mock transport (in-process)
# ---------------------------------------------------------------------------


class MockTransport:
    def __init__(
        self,
        core: MockControllerCore,
        state_hz: float = 5.0,
        result_latency_ms: int = 150,
    ) -> None:
        self.core = core
        self._interval = 1.0 / max(state_hz, 0.1)
        self._latency_s = max(result_latency_ms, 0) / 1000.0
        self._cb: Optional[MessageCallback] = None
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    def set_message_callback(self, cb: MessageCallback) -> None:
        self._cb = cb

    def start(self) -> None:
        if self._thread is not None:
            return
        self._stop.clear()
        self._thread = threading.Thread(target=self._tick_loop, name="mock-transport", daemon=True)
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None

    def publish_command(self, payload: dict[str, Any]) -> None:
        # Simulate controller processing latency off the caller's thread.
        timer = threading.Timer(self._latency_s, self._process_command, args=(payload,))
        timer.daemon = True
        timer.start()

    def _process_command(self, payload: dict[str, Any]) -> None:
        try:
            result = self.core.handle_command(payload)
        except Exception:
            logger.exception("mock controller failed to handle command")
            return
        if result is not None:
            self._emit(result)

    def _tick_loop(self) -> None:
        while not self._stop.wait(self._interval):
            try:
                self._emit(self.core.build_state())
            except Exception:
                logger.exception("mock controller failed to build state")

    def _emit(self, msg: dict[str, Any]) -> None:
        cb = self._cb
        if cb is not None:
            try:
                cb(msg)
            except Exception:
                logger.exception("bridge message callback raised")


# ---------------------------------------------------------------------------
# ROS 2 transport (lazy rclpy)
# ---------------------------------------------------------------------------


class Ros2Transport:
    def __init__(self, topic: str = "/g_exo/bridge", node_name: str = "gexo_web_agent") -> None:
        self._topic = topic
        self._node_name = node_name
        self._cb: Optional[MessageCallback] = None
        self._node = None
        self._pub = None
        self._thread: Optional[threading.Thread] = None
        self._rclpy = None
        self._string_msg_cls = None

    def set_message_callback(self, cb: MessageCallback) -> None:
        self._cb = cb

    def start(self) -> None:
        if self._thread is not None:
            return
        import rclpy  # lazy: only needed when transport=ros2
        from std_msgs.msg import String

        self._rclpy = rclpy
        self._string_msg_cls = String
        if not rclpy.ok():
            rclpy.init()
        self._node = rclpy.create_node(self._node_name)
        self._pub = self._node.create_publisher(String, self._topic, 10)
        self._node.create_subscription(String, self._topic, self._on_ros_message, 10)
        self._thread = threading.Thread(target=self._spin, name="ros2-spin", daemon=True)
        self._thread.start()
        logger.info("Ros2Transport started on topic %s", self._topic)

    def stop(self) -> None:
        if self._rclpy is None:
            return
        try:
            self._rclpy.shutdown()
        except Exception:
            logger.exception("rclpy shutdown failed")
        if self._thread is not None:
            self._thread.join(timeout=2.0)
            self._thread = None
        self._node = None
        self._pub = None

    def publish_command(self, payload: dict[str, Any]) -> None:
        if self._pub is None or self._string_msg_cls is None:
            raise RuntimeError("Ros2Transport not started")
        msg = self._string_msg_cls()
        msg.data = json.dumps(payload, ensure_ascii=False)
        self._pub.publish(msg)  # rclpy publish is thread-safe

    def _spin(self) -> None:
        try:
            self._rclpy.spin(self._node)
        except Exception:
            logger.exception("rclpy spin exited abnormally")

    def _on_ros_message(self, msg: Any) -> None:
        cb = self._cb
        if cb is None:
            return
        try:
            data = json.loads(msg.data)
        except (json.JSONDecodeError, TypeError):
            logger.warning("dropping non-JSON bridge message")
            return
        if isinstance(data, dict):
            cb(data)


# ---------------------------------------------------------------------------
# Adapter (the business-facing API)
# ---------------------------------------------------------------------------


class RosBridgeAdapter:
    """Decouples business logic from topic name / wire format / transport."""

    def __init__(self, transport: BridgeTransport, source_id: str = "gexo_web_agent") -> None:
        self._transport = transport
        self._source_id = source_id
        self._state_cb: Optional[Callable[[BridgeState], None]] = None
        self._result_cb: Optional[Callable[[BridgeResult], None]] = None
        transport.set_message_callback(self._on_message)

    def on_state(self, cb: Callable[[BridgeState], None]) -> None:
        self._state_cb = cb

    def on_result(self, cb: Callable[[BridgeResult], None]) -> None:
        self._result_cb = cb

    def start(self) -> None:
        self._transport.start()

    def stop(self) -> None:
        self._transport.stop()

    def send_command(self, command: BridgeCommand) -> None:
        """Publish a validated command. Never called with raw model output."""
        payload = command.model_dump()
        payload["timestamp_ms"] = int(time.time() * 1000)
        self._transport.publish_command(payload)

    # -- incoming -----------------------------------------------------------

    def _on_message(self, data: dict[str, Any]) -> None:
        """Runs on the transport thread: parse, filter, dispatch. Non-blocking."""
        if data.get("source") == self._source_id:
            return  # ignore our own messages echoed back on the shared topic
        try:
            msg = parse_bridge_message(data)
        except Exception:
            logger.warning("dropping malformed bridge message: %.200s", data)
            return
        if isinstance(msg, BridgeState):
            if self._state_cb is not None:
                self._state_cb(msg)
        elif isinstance(msg, BridgeResult):
            if self._result_cb is not None:
                self._result_cb(msg)
        # BridgeCommand from other sources is intentionally ignored.
