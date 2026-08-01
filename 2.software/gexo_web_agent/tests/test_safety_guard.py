"""Exhaustive SafetyGuard tests — every rejection code, every boundary."""
from __future__ import annotations

import pytest

from gexo_web_agent.config import SafetyConfig
from gexo_web_agent.safety_guard import Allow, Reject, check
from gexo_web_agent.schemas import (
    AdjustAssistAction,
    DocumentQaAction,
    ErrorCode,
    Mode,
    QueryStatusAction,
    SetModeAction,
    StateData,
)

CFG = SafetyConfig()  # 0.3 / 1.0 / 0.1


def good_state(**overrides) -> StateData:
    base = dict(
        mode=Mode.ASSIST,
        assist_ratio=0.5,
        is_stationary=True,
        can_online=True,
        emergency_stop=False,
        fault_code="",
    )
    base.update(overrides)
    return StateData(**base)


def run(action, state, *, stale=False, confirmed=False):
    return check(action, state, state_stale=stale, confirmed=confirmed, cfg=CFG)


PLUS = AdjustAssistAction(delta=0.1)
MINUS = AdjustAssistAction(delta=-0.1)
TO_DAMPING = SetModeAction(mode=Mode.DAMPING)
TO_ASSIST = SetModeAction(mode=Mode.ASSIST)


class TestReadOnlyAlwaysAllowed:
    def test_query_with_no_state(self):
        assert isinstance(run(QueryStatusAction(), None), Allow)

    def test_qa_with_stale_state(self):
        assert isinstance(run(DocumentQaAction(question="怎么穿戴？"), good_state(), stale=True), Allow)

    def test_query_with_estop(self):
        assert isinstance(run(QueryStatusAction(), good_state(emergency_stop=True)), Allow)


class TestPlatformInterlocks:
    @pytest.mark.parametrize("action", [PLUS, TO_DAMPING])
    def test_no_state(self, action):
        d = run(action, None, confirmed=True)
        assert isinstance(d, Reject) and d.error_code is ErrorCode.NO_STATE

    @pytest.mark.parametrize("action", [PLUS, TO_DAMPING])
    def test_stale_state(self, action):
        d = run(action, good_state(), stale=True, confirmed=True)
        assert isinstance(d, Reject) and d.error_code is ErrorCode.STATE_TIMEOUT

    @pytest.mark.parametrize("action", [PLUS, MINUS, TO_DAMPING])
    def test_estop(self, action):
        d = run(action, good_state(emergency_stop=True), confirmed=True)
        assert isinstance(d, Reject) and d.error_code is ErrorCode.EMERGENCY_STOP_ACTIVE

    @pytest.mark.parametrize("action", [PLUS, TO_DAMPING])
    def test_fault(self, action):
        d = run(action, good_state(fault_code="E42"), confirmed=True)
        assert isinstance(d, Reject) and d.error_code is ErrorCode.FAULT_ACTIVE

    @pytest.mark.parametrize("action", [PLUS, TO_DAMPING])
    def test_can_offline(self, action):
        d = run(action, good_state(can_online=False), confirmed=True)
        assert isinstance(d, Reject) and d.error_code is ErrorCode.CAN_OFFLINE

    def test_interlock_order_estop_before_fault(self):
        d = run(PLUS, good_state(emergency_stop=True, fault_code="E1", can_online=False))
        assert isinstance(d, Reject) and d.error_code is ErrorCode.EMERGENCY_STOP_ACTIVE


class TestAdjustAssist:
    def test_normal_plus(self):
        assert isinstance(run(PLUS, good_state(assist_ratio=0.5)), Allow)

    def test_normal_minus(self):
        assert isinstance(run(MINUS, good_state(assist_ratio=0.5)), Allow)

    def test_damping_blocks_assist(self):
        d = run(PLUS, good_state(mode=Mode.DAMPING))
        assert isinstance(d, Reject) and d.error_code is ErrorCode.ASSIST_IN_DAMPING

    def test_at_max_plus_rejected(self):
        d = run(PLUS, good_state(assist_ratio=1.0))
        assert isinstance(d, Reject) and d.error_code is ErrorCode.ASSIST_AT_MAXIMUM

    def test_at_min_minus_rejected(self):
        d = run(MINUS, good_state(assist_ratio=0.3))
        assert isinstance(d, Reject) and d.error_code is ErrorCode.ASSIST_AT_MINIMUM

    def test_boundary_09_plus_allowed(self):
        assert isinstance(run(PLUS, good_state(assist_ratio=0.9)), Allow)

    def test_boundary_04_minus_allowed(self):
        assert isinstance(run(MINUS, good_state(assist_ratio=0.4)), Allow)

    def test_float_noise_tolerated(self):
        # 0.7000000000000001 + 0.1 must still be allowed (rounds to 0.8)
        assert isinstance(run(PLUS, good_state(assist_ratio=0.7000000000000001)), Allow)
        # 0.9999999999 + 0.1 → rounds to 1.1 → reject
        d = run(PLUS, good_state(assist_ratio=0.9999999999))
        assert isinstance(d, Reject) and d.error_code is ErrorCode.ASSIST_AT_MAXIMUM

    def test_assist_allowed_while_moving(self):
        # only MODE SWITCH requires stationary; assist tweak does not
        assert isinstance(run(PLUS, good_state(is_stationary=False)), Allow)


class TestSetMode:
    def test_unconfirmed_rejected(self):
        d = run(TO_DAMPING, good_state(), confirmed=False)
        assert isinstance(d, Reject) and d.error_code is ErrorCode.CONFIRMATION_REQUIRED

    def test_confirmed_stationary_allowed(self):
        assert isinstance(run(TO_DAMPING, good_state(), confirmed=True), Allow)

    def test_moving_rejected_even_confirmed(self):
        d = run(TO_DAMPING, good_state(is_stationary=False), confirmed=True)
        assert isinstance(d, Reject) and d.error_code is ErrorCode.NOT_STATIONARY

    def test_same_mode_soft_rejected(self):
        d = run(TO_ASSIST, good_state(mode=Mode.ASSIST), confirmed=True)
        assert isinstance(d, Reject) and d.error_code is ErrorCode.INVALID_MODE

    def test_damping_to_assist_allowed(self):
        assert isinstance(run(TO_ASSIST, good_state(mode=Mode.DAMPING), confirmed=True), Allow)

    def test_confirmation_checked_before_stationary(self):
        d = run(TO_DAMPING, good_state(is_stationary=False), confirmed=False)
        assert isinstance(d, Reject) and d.error_code is ErrorCode.CONFIRMATION_REQUIRED


class TestRejectMessagesAreChinese:
    def test_messages_human_readable(self):
        d = run(PLUS, good_state(mode=Mode.DAMPING))
        assert isinstance(d, Reject) and "阻尼" in d.message
        d = run(TO_DAMPING, good_state(is_stationary=False), confirmed=True)
        assert isinstance(d, Reject) and "静止" in d.message
