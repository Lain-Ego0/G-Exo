"""Schema contract tests: action whitelist, wire format round-trip."""
from __future__ import annotations

import pytest
from pydantic import ValidationError

from gexo_web_agent.schemas import (
    ActionEnvelope,
    AdjustAssistAction,
    BridgeCommand,
    BridgeResult,
    BridgeState,
    DocumentQaAction,
    Mode,
    QueryStatusAction,
    SetModeAction,
    StateData,
    parse_bridge_message,
)


class TestAdjustAssist:
    def test_plus_step(self):
        a = AdjustAssistAction(delta=0.1)
        assert a.delta == pytest.approx(0.1)

    def test_minus_step(self):
        a = AdjustAssistAction(delta=-0.1)
        assert a.delta == pytest.approx(-0.1)

    def test_float_representation_tolerated(self):
        a = AdjustAssistAction(delta=0.10000000000000003)
        assert a.delta == pytest.approx(0.1)

    @pytest.mark.parametrize("bad", [0.2, -0.2, 0.05, 0.0, 1.0, -0.3, 0.11])
    def test_illegal_delta_rejected(self, bad: float):
        with pytest.raises(ValidationError):
            AdjustAssistAction(delta=bad)

    def test_extra_field_rejected(self):
        with pytest.raises(ValidationError):
            AdjustAssistAction(delta=0.1, joint="left_hip")  # type: ignore[call-arg]


class TestSetMode:
    def test_valid_modes(self):
        assert SetModeAction(mode="assist").mode is Mode.ASSIST
        assert SetModeAction(mode="damping").mode is Mode.DAMPING

    @pytest.mark.parametrize("bad", ["impedance", "stop", "", "ASSIST_MAX"])
    def test_invalid_mode_rejected(self, bad: str):
        with pytest.raises(ValidationError):
            SetModeAction(mode=bad)  # type: ignore[arg-type]


class TestQueryStatus:
    def test_default_fields(self):
        a = QueryStatusAction()
        assert "mode" in a.fields and "battery" in a.fields

    def test_unknown_field_rejected(self):
        with pytest.raises(ValidationError):
            QueryStatusAction(fields=["mode", "torque_raw"])


class TestDocumentQa:
    def test_ok(self):
        assert DocumentQaAction(question="怎么穿戴？").question

    def test_empty_rejected(self):
        with pytest.raises(ValidationError):
            DocumentQaAction(question="")


class TestActionEnvelope:
    def test_dispatch_by_action(self):
        a = ActionEnvelope.parse_untrusted({"action": "adjust_assist", "delta": 0.1})
        assert isinstance(a, AdjustAssistAction)

    @pytest.mark.parametrize(
        "payload",
        [
            {"action": "set_torque", "torque": [1, 2, 3, 4]},
            {"action": "release_estop"},
            {"action": "run_shell", "cmd": "rm -rf /"},
            {"action": ""},
            {},
        ],
    )
    def test_undefined_actions_rejected(self, payload: dict):
        with pytest.raises(ValidationError):
            ActionEnvelope.parse_untrusted(payload)


class TestWireFormat:
    def test_command_roundtrip(self):
        cmd = BridgeCommand(action="adjust_assist", params={"delta": 0.1})
        parsed = parse_bridge_message(cmd.model_dump())
        assert isinstance(parsed, BridgeCommand)
        assert parsed.request_id == cmd.request_id
        assert parsed.source == "gexo_web_agent"

    def test_state_roundtrip(self):
        st = BridgeState(data=StateData(mode=Mode.DAMPING, assist_ratio=0.7))
        parsed = parse_bridge_message(st.model_dump())
        assert isinstance(parsed, BridgeState)
        assert parsed.data.mode is Mode.DAMPING

    def test_state_tolerates_extra_keys(self):
        st = BridgeState(data=StateData())
        raw = st.model_dump()
        raw["data"]["future_field"] = 42
        parsed = parse_bridge_message(raw)
        assert isinstance(parsed, BridgeState)

    def test_result_roundtrip(self):
        r = BridgeResult(request_id="abc", success=False, error_code="NOT_STATIONARY")
        parsed = parse_bridge_message(r.model_dump())
        assert isinstance(parsed, BridgeResult)
        assert parsed.error_code == "NOT_STATIONARY"

    def test_unknown_type_rejected(self):
        with pytest.raises(ValueError):
            parse_bridge_message({"type": "telemetry"})
