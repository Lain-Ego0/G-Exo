"""Standalone mock controller ROS 2 node.

Wraps the same `MockControllerCore` used by the in-process MockTransport in an
rclpy shell, so on-device integration tests exercise the REAL topic path:

    web agent (transport=ros2)  ⇄  /g_exo/bridge  ⇄  this node

Run:  ros2 run gexo_web_agent gexo-mock-controller
  or: python -m gexo_web_agent.mock_controller_node --scenario estop
"""
from __future__ import annotations

import argparse
import json
import logging
from typing import Any

from .mock_controller_core import SCENARIOS, MockControllerCore

logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="G-Exo mock controller node")
    parser.add_argument("--topic", default="/g_exo/bridge")
    parser.add_argument("--scenario", default="normal", choices=SCENARIOS)
    parser.add_argument("--state-hz", type=float, default=5.0)
    args, _ = parser.parse_known_args()

    import rclpy
    from std_msgs.msg import String

    logging.basicConfig(level=logging.INFO)
    rclpy.init()
    node = rclpy.create_node("gexo_mock_controller")
    core = MockControllerCore(scenario=args.scenario)
    pub = node.create_publisher(String, args.topic, 10)

    def publish(payload: dict[str, Any]) -> None:
        msg = String()
        msg.data = json.dumps(payload, ensure_ascii=False)
        pub.publish(msg)

    def on_message(msg: String) -> None:
        try:
            data = json.loads(msg.data)
        except json.JSONDecodeError:
            return
        if not isinstance(data, dict) or data.get("type") != "command":
            return
        if data.get("source") == "gexo_controller_mock":
            return
        result = core.handle_command(data)
        if result is not None:
            publish(result)
            logger.info("result %s -> success=%s", data.get("request_id"), result["success"])

    node.create_subscription(String, args.topic, on_message, 10)
    node.create_timer(1.0 / max(args.state_hz, 0.1), lambda: publish(core.build_state()))

    logger.info("mock controller on %s (scenario=%s)", args.topic, args.scenario)
    try:
        rclpy.spin(node)
    except KeyboardInterrupt:
        pass
    finally:
        rclpy.shutdown()


if __name__ == "__main__":
    main()
