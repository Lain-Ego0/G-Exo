"""MockControllerCore behavior per scenario."""
from __future__ import annotations

import pytest

from gexo_web_agent.mock_controller_core import MockControllerCore
from gexo_web_agent.schemas import BridgeCommand, ErrorCode, Mode, parse_bridge_message


def cmd(action: str, **params) -> dict:
    return BridgeCommand(action=action, params=params).model_dump()


def test_build_state_normal():
    core = MockControllerCore()
    msg = parse_bridge_message(core.build_state())
    assert msg.type == "state"
    assert msg.data.mode is Mode.ASSIST
    assert msg.data.is_stationary is True
    assert msg.data.can_online is True
    assert msg.data.emergency_stop is False


def test_adjust_assist_success_and_bounds():
    core = MockControllerCore()  # starts at 0.5
    r = core.handle_command(cmd("adjust_assist", delta=0.1))
    assert r["success"] and r["result"]["assist_ratio"] == pytest.approx(0.6)
    # walk to max
    for _ in range(4):
        r = core.handle_command(cmd("adjust_assist", delta=0.1))
    assert r["success"] and r["result"]["assist_ratio"] == pytest.approx(1.0)
    r = core.handle_command(cmd("adjust_assist", delta=0.1))
    assert not r["success"] and r["error_code"] == ErrorCode.ASSIST_AT_MAXIMUM.value
    # walk to min
    for _ in range(7):
        r = core.handle_command(cmd("adjust_assist", delta=-0.1))
    assert r["success"] and r["result"]["assist_ratio"] == pytest.approx(0.3)
    r = core.handle_command(cmd("adjust_assist", delta=-0.1))
    assert not r["success"] and r["error_code"] == ErrorCode.ASSIST_AT_MINIMUM.value


def test_set_mode_and_damping_blocks_assist():
    core = MockControllerCore()
    r = core.handle_command(cmd("set_mode", mode="damping"))
    assert r["success"] and r["result"]["mode"] == "damping"
    r = core.handle_command(cmd("adjust_assist", delta=0.1))
    assert not r["success"]
    r = core.handle_command(cmd("set_mode", mode="assist"))
    assert r["success"] and r["result"]["mode"] == "assist"


def test_moving_blocks_mode_switch():
    core = MockControllerCore(scenario="moving")
    st = parse_bridge_message(core.build_state())
    assert st.data.is_stationary is False
    r = core.handle_command(cmd("set_mode", mode="damping"))
    assert not r["success"] and r["error_code"] == ErrorCode.NOT_STATIONARY.value


@pytest.mark.parametrize(
    "scenario,error_code",
    [
        ("estop", ErrorCode.EMERGENCY_STOP_ACTIVE),
        ("fault", ErrorCode.FAULT_ACTIVE),
        ("overheat", ErrorCode.FAULT_ACTIVE),
        ("can_offline", ErrorCode.CAN_OFFLINE),
    ],
)
def test_unsafe_scenarios_reject_writes(scenario: str, error_code: ErrorCode):
    core = MockControllerCore(scenario=scenario)
    r = core.handle_command(cmd("adjust_assist", delta=0.1))
    assert not r["success"] and r["error_code"] == error_code.value


def test_scenario_reflected_in_state():
    core = MockControllerCore(scenario="estop")
    assert parse_bridge_message(core.build_state()).data.emergency_stop is True
    core.set_scenario("can_offline")
    assert parse_bridge_message(core.build_state()).data.can_online is False
    core.set_scenario("overheat")
    st = parse_bridge_message(core.build_state())
    assert max(st.data.motor_temperature) > 80 and st.data.fault_code


def test_no_reply_returns_none():
    core = MockControllerCore(scenario="no_reply")
    assert core.handle_command(cmd("adjust_assist", delta=0.1)) is None


def test_fail_scenario():
    core = MockControllerCore(scenario="fail")
    r = core.handle_command(cmd("adjust_assist", delta=0.1))
    assert not r["success"]


def test_unknown_scenario_rejected():
    with pytest.raises(ValueError):
        MockControllerCore(scenario="chaos")
    core = MockControllerCore()
    with pytest.raises(ValueError):
        core.set_scenario("chaos")
