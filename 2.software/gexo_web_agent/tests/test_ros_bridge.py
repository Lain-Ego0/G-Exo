"""RosBridgeAdapter + MockTransport integration (no ROS 2 required)."""
from __future__ import annotations

import threading
import time

from gexo_web_agent.mock_controller_core import MockControllerCore
from gexo_web_agent.ros_bridge import MockTransport, RosBridgeAdapter
from gexo_web_agent.schemas import BridgeCommand, BridgeResult, BridgeState


def make_bridge(scenario: str = "normal", state_hz: float = 50.0, latency_ms: int = 10):
    core = MockControllerCore(scenario=scenario)
    transport = MockTransport(core, state_hz=state_hz, result_latency_ms=latency_ms)
    adapter = RosBridgeAdapter(transport)
    return core, transport, adapter


def test_state_flows_to_callback():
    _, transport, adapter = make_bridge()
    got = threading.Event()
    states: list[BridgeState] = []

    def on_state(msg: BridgeState) -> None:
        states.append(msg)
        got.set()

    adapter.on_state(on_state)
    adapter.start()
    try:
        assert got.wait(timeout=2.0), "no state received from mock transport"
        assert states[0].data.can_online is True
    finally:
        adapter.stop()


def test_command_gets_correlated_result():
    _, transport, adapter = make_bridge()
    got = threading.Event()
    results: list[BridgeResult] = []
    adapter.on_result(lambda m: (results.append(m), got.set()))
    adapter.start()
    try:
        cmd = BridgeCommand(action="adjust_assist", params={"delta": 0.1})
        adapter.send_command(cmd)
        assert got.wait(timeout=2.0), "no result received"
        assert results[0].request_id == cmd.request_id
        assert results[0].success is True
    finally:
        adapter.stop()


def test_own_source_messages_filtered():
    """Messages carrying our own source id must be ignored (shared topic)."""
    _, transport, adapter = make_bridge(state_hz=0.1)
    received: list = []
    adapter.on_result(received.append)
    adapter.on_state(received.append)

    echo = BridgeResult(source="gexo_web_agent", request_id="x", success=True).model_dump()
    adapter._on_message(echo)
    assert received == []

    real = BridgeResult(source="gexo_controller", request_id="x", success=True).model_dump()
    adapter._on_message(real)
    assert len(received) == 1


def test_malformed_message_dropped():
    _, transport, adapter = make_bridge(state_hz=0.1)
    received: list = []
    adapter.on_state(received.append)
    adapter.on_result(received.append)
    adapter._on_message({"type": "state", "source": "ctrl", "data": {"assist_ratio": "not-a-number"}})
    adapter._on_message({"garbage": True})
    assert received == []


def test_no_reply_scenario_produces_no_result():
    _, transport, adapter = make_bridge(scenario="no_reply")
    results: list = []
    adapter.on_result(results.append)
    adapter.start()
    try:
        adapter.send_command(BridgeCommand(action="adjust_assist", params={"delta": 0.1}))
        time.sleep(0.2)
        assert results == []
    finally:
        adapter.stop()


def test_transport_stop_is_clean():
    _, transport, adapter = make_bridge()
    adapter.start()
    adapter.stop()
    # double stop must not raise
    adapter.stop()
