"""Device-only ROS 2 transport smoke test.

Skipped automatically wherever rclpy is unavailable (e.g. Windows dev box).
On the K3 run:  python -m pytest tests/test_ros2_transport.py -v
"""
from __future__ import annotations

import threading
import time

import pytest

rclpy = pytest.importorskip("rclpy")

from gexo_web_agent.mock_controller_core import MockControllerCore  # noqa: E402
from gexo_web_agent.ros_bridge import Ros2Transport, RosBridgeAdapter  # noqa: E402
from gexo_web_agent.schemas import BridgeCommand  # noqa: E402

TOPIC = "/g_exo/bridge_test"


@pytest.fixture()
def mock_node():
    """In-process rclpy mock controller on the test topic."""
    import json

    from std_msgs.msg import String

    if not rclpy.ok():
        rclpy.init()
    node = rclpy.create_node("test_mock_controller")
    core = MockControllerCore()
    pub = node.create_publisher(String, TOPIC, 10)

    def on_msg(msg: String) -> None:
        data = json.loads(msg.data)
        if data.get("type") != "command":
            return
        result = core.handle_command(data)
        if result:
            out = String()
            out.data = json.dumps(result, ensure_ascii=False)
            pub.publish(out)

    node.create_subscription(String, TOPIC, on_msg, 10)
    node.create_timer(0.1, lambda: pub.publish(
        String(data=__import__("json").dumps(core.build_state(), ensure_ascii=False))
    ))
    executor = rclpy.executors.SingleThreadedExecutor()
    executor.add_node(node)
    thread = threading.Thread(target=executor.spin, daemon=True)
    thread.start()
    yield node
    executor.shutdown()
    node.destroy_node()


def test_ros2_roundtrip(mock_node):
    transport = Ros2Transport(topic=TOPIC, node_name="test_web_agent")
    adapter = RosBridgeAdapter(transport)

    got_state = threading.Event()
    got_result = threading.Event()
    results = []
    adapter.on_state(lambda m: got_state.set())
    adapter.on_result(lambda m: (results.append(m), got_result.set()))
    adapter.start()
    try:
        assert got_state.wait(timeout=5.0), "no state over ROS topic"
        cmd = BridgeCommand(action="adjust_assist", params={"delta": 0.1})
        adapter.send_command(cmd)
        assert got_result.wait(timeout=5.0), "no result over ROS topic"
        assert results[0].request_id == cmd.request_id
        assert results[0].success
    finally:
        adapter.stop()
