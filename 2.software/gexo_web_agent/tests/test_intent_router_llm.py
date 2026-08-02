"""IntentRouter LLM path with a mocked LlmClient (canned tool-call replies)."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Optional

import pytest

from gexo_web_agent.command_manager import CommandManager
from gexo_web_agent.config import CommandConfig, SafetyConfig, Settings
from gexo_web_agent.intent_router import IntentRouter, render_status
from gexo_web_agent.llm_client import LlmError
from gexo_web_agent.mock_controller_core import MockControllerCore
from gexo_web_agent.ros_bridge import MockTransport, RosBridgeAdapter
from gexo_web_agent.schemas import Mode, StateData
from gexo_web_agent.state_cache import StateCache


class FakeLlm:
    """Scripted LLM: returns queued messages or raises."""

    def __init__(self) -> None:
        self.queue: list[Any] = []
        self.calls: list[dict] = []

    def push_tool_call(self, name: str, args: dict) -> None:
        self.queue.append(
            {"tool_calls": [{"function": {"name": name, "arguments": json.dumps(args)}}]}
        )

    def push_text(self, content: str) -> None:
        self.queue.append({"content": content})

    def push_error(self) -> None:
        self.queue.append(LlmError("down"))

    async def chat(self, messages, **kwargs):
        self.calls.append({"messages": messages, **kwargs})
        item = self.queue.pop(0) if self.queue else {"content": ""}
        if isinstance(item, Exception):
            raise item
        return item


class FakeRag:
    def __init__(self, hits: Optional[list] = None) -> None:
        self.hits = hits or []

    def search(self, query: str, top_k=None):
        return self.hits

    def build_index(self, rebuild: bool = False):
        return {}


def make_router(scenario="normal", hits=None, force_json_fallback=False):
    settings = Settings()
    settings.llm.force_json_fallback = force_json_fallback
    core = MockControllerCore(scenario=scenario)
    transport = MockTransport(core, state_hz=0.01, result_latency_ms=10)
    bridge = RosBridgeAdapter(transport)
    cache = StateCache(stale_timeout_s=5.0)
    cache.update(StateData(mode=Mode.ASSIST, assist_ratio=0.5, is_stationary=True,
                           can_online=True, battery_percent=76.0))
    commands = CommandManager(cache, bridge, SafetyConfig(),
                              CommandConfig(result_timeout_s=0.5))
    commands.set_event_loop(asyncio.get_event_loop())
    llm = FakeLlm()
    rag = FakeRag(hits)
    router = IntentRouter(settings, cache, commands, llm, rag)  # type: ignore[arg-type]
    router._rag_ready.set()  # index "built"
    return router, llm, transport, cache


async def test_llm_tool_call_executes_command():
    router, llm, transport, _ = make_router()
    transport.start()
    try:
        llm.push_tool_call("adjust_assist", {"delta": 0.1})
        resp = await router.handle("腿有点沉，帮我调一下")
        assert resp.intent == "adjust_assist"
        assert resp.command is not None and resp.command.status.value == "success"
    finally:
        transport.stop()


async def test_llm_invalid_tool_rejected_no_command():
    """Model invents an action → clarification, nothing published."""
    router, llm, transport, _ = make_router()
    llm.push_tool_call("set_torque", {"torque": [9, 9, 9, 9]})
    resp = await router.handle("把左腿力矩拉满")
    assert resp.need_clarification
    assert resp.command is None


async def test_llm_out_of_range_delta_rejected():
    router, llm, _, _ = make_router()
    llm.push_tool_call("adjust_assist", {"delta": 0.5})
    resp = await router.handle("给它整猛一些")  # no rule match → LLM path
    assert resp.need_clarification and resp.command is None


async def test_llm_plain_text_becomes_clarification():
    router, llm, _, _ = make_router()
    llm.push_text("请问你是想调节助力，还是想查询状态？")
    resp = await router.handle("那个……弄一下")
    assert resp.need_clarification
    assert "调节助力" in resp.reply


async def test_json_schema_fallback_validates_action():
    router, llm, transport, _ = make_router(force_json_fallback=True)
    transport.start()
    try:
        llm.push_text('{"action":"adjust_assist","delta":0.1}')
        resp = await router.handle("腿有点沉，帮我调一下")
        assert resp.intent == "adjust_assist"
        assert resp.command is not None and resp.command.status.value == "success"
        assert llm.calls[0]["response_format"]["type"] == "json_schema"
    finally:
        transport.stop()


async def test_llm_down_degrades_gracefully():
    router, llm, _, _ = make_router()
    llm.push_error()
    resp = await router.handle("嗯呢帮个忙")
    assert resp.need_clarification
    assert "不可用" in resp.reply


async def test_status_query_uses_real_cache_not_llm():
    router, llm, _, _ = make_router()
    resp = await router.handle("现在是什么模式？")  # rule path — LLM never called
    assert llm.calls == []
    assert "助力模式" in resp.reply and "50%" in resp.reply


async def test_status_stale_reports_disconnect():
    router, _, _, cache = make_router()
    cache._stale_timeout_s = -1  # force stale
    resp = await router.handle("还有多少电？")
    assert "失联" in resp.reply


async def test_mode_switch_via_chat_needs_confirmation():
    router, llm, transport, _ = make_router()
    resp = await router.handle("切换到阻尼训练模式")
    assert resp.need_confirmation
    assert resp.command is not None
    assert resp.command.status.value == "pending_confirmation"


async def test_document_qa_with_hits_cites_sources():
    from gexo_web_agent.rag_service import RagHit

    hits = [RagHit(file="K3手册.pdf", section="第3页", text="穿戴时先固定腰部绑带……", score=-1.0)]
    router, llm, _, _ = make_router(hits=hits)
    llm.push_text("穿戴时应先固定腰部绑带。（来源：K3手册.pdf）")
    resp = await router.handle("怎么正确穿戴设备？")
    assert resp.intent == "document_qa"
    assert resp.sources and resp.sources[0]["file"] == "K3手册.pdf"


async def test_document_qa_no_hits_never_fabricates():
    router, llm, _, _ = make_router(hits=[])
    resp = await router.handle("怎么给设备刷机？")
    assert "没有找到相关说明" in resp.reply
    assert llm.calls == []  # no context → no LLM call → no fabrication


async def test_document_qa_llm_down_returns_chunk():
    from gexo_web_agent.rag_service import RagHit

    hits = [RagHit(file="a.md", section="穿戴", text="第一步系好绑带", score=-1.0)]
    router, llm, _, _ = make_router(hits=hits)
    llm.push_error()
    resp = await router.handle("怎么穿戴？")
    assert "第一步系好绑带" in resp.reply


def test_render_status_fields_subset():
    st = StateData(battery_percent=88.0, bus_voltage=24.2)
    text = render_status(st, stale=False, fields=["battery"])
    assert "88%" in text and "模式" not in text


def test_render_status_none():
    assert "失联" in render_status(None, stale=False, fields=[])
