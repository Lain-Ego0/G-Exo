"""CommandManager lifecycle tests over the in-process mock transport."""
from __future__ import annotations

import asyncio

import pytest

from gexo_web_agent.command_manager import CommandManager
from gexo_web_agent.config import CommandConfig, SafetyConfig
from gexo_web_agent.mock_controller_core import MockControllerCore
from gexo_web_agent.ros_bridge import MockTransport, RosBridgeAdapter
from gexo_web_agent.schemas import (
    AdjustAssistAction,
    CommandStatus,
    ErrorCode,
    Mode,
    SetModeAction,
    StateData,
)
from gexo_web_agent.state_cache import StateCache


def fresh_state(**overrides) -> StateData:
    base = dict(mode=Mode.ASSIST, assist_ratio=0.5, is_stationary=True,
                can_online=True, emergency_stop=False, fault_code="")
    base.update(overrides)
    return StateData(**base)


def make_manager(scenario="normal", result_timeout_s=1.0, confirm_ttl_s=30.0, latency_ms=20):
    core = MockControllerCore(scenario=scenario)
    transport = MockTransport(core, state_hz=0.01, result_latency_ms=latency_ms)  # state pushed manually
    bridge = RosBridgeAdapter(transport)
    cache = StateCache(stale_timeout_s=5.0)
    mgr = CommandManager(
        cache,
        bridge,
        SafetyConfig(),
        CommandConfig(result_timeout_s=result_timeout_s, confirm_ttl_s=confirm_ttl_s, history_size=5),
    )
    mgr.set_event_loop(asyncio.get_event_loop())
    cache.update(fresh_state())
    return core, transport, bridge, cache, mgr


async def test_adjust_assist_success():
    _, t, _, _, mgr = make_manager()
    t.start()
    try:
        view = await mgr.submit(AdjustAssistAction(delta=0.1))
        assert view.status is CommandStatus.SUCCESS
        assert view.result["assist_ratio"] == pytest.approx(0.6)
        assert mgr.get_view(view.request_id).status is CommandStatus.SUCCESS
    finally:
        t.stop()


async def test_safety_reject_never_publishes():
    _, t, _, cache, mgr = make_manager()
    cache.update(fresh_state(emergency_stop=True))
    view = await mgr.submit(AdjustAssistAction(delta=0.1))
    assert view.status is CommandStatus.REJECTED
    assert view.error_code == ErrorCode.EMERGENCY_STOP_ACTIVE.value


async def test_set_mode_requires_confirmation_then_succeeds():
    _, t, _, _, mgr = make_manager()
    t.start()
    try:
        view = await mgr.submit(SetModeAction(mode=Mode.DAMPING))
        assert view.status is CommandStatus.PENDING_CONFIRMATION
        done = await mgr.confirm(view.request_id, approve=True)
        assert done.status is CommandStatus.SUCCESS
        assert done.result["mode"] == "damping"
        assert done.request_id == view.request_id
    finally:
        t.stop()


async def test_confirm_decline_cancels():
    _, _, _, _, mgr = make_manager()
    view = await mgr.submit(SetModeAction(mode=Mode.DAMPING))
    done = await mgr.confirm(view.request_id, approve=False)
    assert done.status is CommandStatus.CANCELLED


async def test_confirm_revalidates_fresh_state():
    """State degrades between pending and confirm → must be rejected."""
    _, _, _, cache, mgr = make_manager()
    view = await mgr.submit(SetModeAction(mode=Mode.DAMPING))
    cache.update(fresh_state(is_stationary=False))  # user started walking
    done = await mgr.confirm(view.request_id, approve=True)
    assert done.status is CommandStatus.REJECTED
    assert done.error_code == ErrorCode.NOT_STATIONARY.value


async def test_confirm_expiry():
    _, _, _, _, mgr = make_manager(confirm_ttl_s=0.01)
    view = await mgr.submit(SetModeAction(mode=Mode.DAMPING))
    await asyncio.sleep(0.05)
    done = await mgr.confirm(view.request_id, approve=True)
    assert done.status is CommandStatus.EXPIRED
    # polling also surfaces expiry
    assert mgr.get_view(view.request_id).status is CommandStatus.EXPIRED


async def test_confirm_unknown_id_returns_none():
    _, _, _, _, mgr = make_manager()
    assert await mgr.confirm("nonexistent", approve=True) is None


async def test_controller_timeout_is_failure_no_retry():
    core, t, _, _, mgr = make_manager(scenario="no_reply", result_timeout_s=0.15)
    t.start()
    try:
        view = await mgr.submit(AdjustAssistAction(delta=0.1))
        assert view.status is CommandStatus.TIMEOUT
        assert view.error_code == ErrorCode.CONTROLLER_TIMEOUT.value
        # no retry: controller received exactly one command; a later poll
        # still shows timeout (nothing resent behind the scenes)
        await asyncio.sleep(0.3)
        assert mgr.get_view(view.request_id).status is CommandStatus.TIMEOUT
    finally:
        t.stop()


async def test_controller_failure_reported_verbatim():
    _, t, _, _, mgr = make_manager(scenario="moving")
    t.start()
    try:
        view = await mgr.submit(SetModeAction(mode=Mode.DAMPING))
        done = await mgr.confirm(view.request_id, approve=True)
        # web-agent cache says stationary (we set it), controller says moving:
        # controller verdict wins and is surfaced verbatim
        assert done.status is CommandStatus.FAILED
        assert done.error_code == ErrorCode.NOT_STATIONARY.value
    finally:
        t.stop()


async def test_busy_second_write_rejected():
    _, t, _, _, mgr = make_manager(latency_ms=200, result_timeout_s=2.0)
    t.start()
    try:
        first = asyncio.create_task(mgr.submit(AdjustAssistAction(delta=0.1)))
        await asyncio.sleep(0.05)  # let the first command acquire the lock
        second = await mgr.submit(AdjustAssistAction(delta=0.1))
        assert second.status is CommandStatus.REJECTED
        assert second.error_code == ErrorCode.BUSY.value
        assert (await first).status is CommandStatus.SUCCESS
    finally:
        t.stop()


async def test_history_eviction():
    _, _, _, cache, mgr = make_manager()
    cache.update(fresh_state(emergency_stop=True))  # every submit → instant reject
    ids = []
    for _ in range(8):
        v = await mgr.submit(AdjustAssistAction(delta=0.1))
        ids.append(v.request_id)
    assert mgr.get_view(ids[0]) is None          # evicted (cap=5)
    assert mgr.get_view(ids[-1]) is not None


async def test_read_only_action_rejected_by_submit():
    from gexo_web_agent.schemas import QueryStatusAction
    _, _, _, _, mgr = make_manager()
    with pytest.raises(ValueError):
        await mgr.submit(QueryStatusAction())
