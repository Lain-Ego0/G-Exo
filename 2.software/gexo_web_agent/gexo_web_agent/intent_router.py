"""Intent routing: deterministic rules first, LLM structured extraction second.

Pipeline for /api/chat:

    text ──▶ rule fast-path (regex, <1ms) ──┐
        └──▶ LLM tool-call extraction ──────┴─▶ Pydantic validation
                                                  │
              query_status ─▶ StateCache (REAL data only; LLM never invents)
              document_qa  ─▶ RagService → LLM answer with sources
              set_mode / adjust_assist ─▶ CommandManager (same SafetyGuard
                                          as the buttons — no privilege)

Anything unparseable or out-of-whitelist → clarification request, never a
guessed write.  LLM outage degrades chat but NEVER touches the control path.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import threading
from typing import Any, Optional, Union

from pydantic import ValidationError

from .command_manager import CommandManager
from .config import Settings
from .llm_client import LlmClient, LlmError, extract_tool_call
from .logging_config import control_event
from .rag_service import RagHit, RagService
from .schemas import (
    Action,
    ActionEnvelope,
    AdjustAssistAction,
    ChatResponse,
    CommandStatus,
    CommandView,
    DocumentQaAction,
    Mode,
    QueryStatusAction,
    SetModeAction,
    StateData,
)
from .state_cache import StateCache

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Rule fast-path
# ---------------------------------------------------------------------------

_PUNCT_RE = re.compile(r"[\s。，、！？!?,.；;：:　\"'“”‘’()（）]+")


def _normalize(text: str) -> str:
    # full-width → half-width, strip punctuation/whitespace
    text = "".join(
        chr(ord(c) - 0xFEE0) if 0xFF01 <= ord(c) <= 0xFF5E else c for c in text
    )
    return _PUNCT_RE.sub("", text).lower()


_STATUS_PATTERNS = [
    r"(现在|当前|目前).*(模式|助力|温度|电|状态|can)",
    r"(还有|剩)(多少|余)",
    r"多少(度|电)",
    r"(正常|在线|好使|好用|连着)吗",
    r"^(状态|电量|电池|查询状态|刷新状态)$",
    r"(电池|电量)(怎么样|如何|还剩)",
]
_DOC_PATTERNS = [
    r"怎么|怎样|如何|什么是|是什么|为什么|教程|说明书|穿戴|使用方法|注意事项",
]
_MODE_DAMPING_PATTERNS = [
    r"(切|换|进入|开启|启动|调到|改成|变成).*(阻尼|训练)",
    r"^(阻尼模式|阻尼训练模式|训练模式)$",
]
_MODE_ASSIST_PATTERNS = [
    r"(切|换|进入|开启|启动|调到|改成|变成).*助力(模式)?$",
    r"^助力模式$",
]
_ASSIST_UP_PATTERNS = [
    r"助力.*(大|增|加|高|强|提)",
    r"(增加|加大|加点|提高|增强).*助力",
    r"^(大一点|再大一点|大点|强一点)$",
]
_ASSIST_DOWN_PATTERNS = [
    r"助力.*(小|减|降|低|弱)",
    r"(减小|减少|降低|减弱|调低).*助力",
    r"^(小一点|再小一点|小点|弱一点)$",
]


def _match_any(patterns: list[str], text: str) -> bool:
    return any(re.search(p, text) for p in patterns)


def route_by_rules(text: str) -> Optional[Action]:
    """Deterministic mapping for unambiguous phrasings; None → ask the LLM."""
    t = _normalize(text)
    if not t:
        return None
    # order matters: status ("现在是什么模式") must win over doc-qa ("是什么")
    if _match_any(_STATUS_PATTERNS, t):
        return QueryStatusAction()
    if _match_any(_DOC_PATTERNS, t):
        return DocumentQaAction(question=text.strip())
    if _match_any(_MODE_DAMPING_PATTERNS, t):
        return SetModeAction(mode=Mode.DAMPING)
    if _match_any(_MODE_ASSIST_PATTERNS, t):
        return SetModeAction(mode=Mode.ASSIST)
    if _match_any(_ASSIST_UP_PATTERNS, t):
        return AdjustAssistAction(delta=0.1)
    if _match_any(_ASSIST_DOWN_PATTERNS, t):
        return AdjustAssistAction(delta=-0.1)
    return None


# ---------------------------------------------------------------------------
# LLM tool schema (compiled to GBNF by llama-server)
# ---------------------------------------------------------------------------

TOOLS: list[dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "query_status",
            "description": "查询外骨骼当前状态（模式、助力、电量、温度、关节、IMU、CAN、故障）",
            "parameters": {
                "type": "object",
                "properties": {
                    "fields": {
                        "type": "array",
                        "items": {
                            "type": "string",
                            "enum": ["mode", "assist_ratio", "battery", "temperature",
                                     "joints", "imu", "can", "fault"],
                        },
                    }
                },
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_mode",
            "description": "切换工作模式。仅在用户明确要求切换时使用。",
            "parameters": {
                "type": "object",
                "properties": {"mode": {"type": "string", "enum": ["assist", "damping"]}},
                "required": ["mode"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "adjust_assist",
            "description": "调节助力强度，一次只能 +0.1（增大）或 -0.1（减小）。",
            "parameters": {
                "type": "object",
                "properties": {"delta": {"type": "number", "enum": [0.1, -0.1]}},
                "required": ["delta"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "document_qa",
            "description": "在教程文档中查找操作方法、概念解释等问题的答案。",
            "parameters": {
                "type": "object",
                "properties": {"question": {"type": "string"}},
                "required": ["question"],
            },
        },
    },
]

SYSTEM_PROMPT = """你是外骨骼设备 G-Exo 的语音助手。你只能通过给定的四个工具帮助用户：
- query_status: 查询设备状态
- set_mode: 切换助力模式(assist)或阻尼训练模式(damping)
- adjust_assist: 增大(+0.1)或减小(-0.1)助力
- document_qa: 教程文档问答（怎么穿戴、概念解释等）

规则：
1. 你不能直接控制关节力矩、电流或单个关节，不能解除急停，不能修改任何安全参数。
2. 用户意图明确时调用对应工具；意图不明确时不要调用工具，直接用中文简短提问澄清。
3. 「XX是什么/怎么做」类问题用 document_qa；「现在是什么模式/还有多少电」类问题用 query_status。
4. 不要编造设备数据。"""

_JSON_FALLBACK_SCHEMA = {
    "type": "json_schema",
    "json_schema": {
        "name": "intent",
        "schema": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": ["query_status", "set_mode", "adjust_assist", "document_qa", "clarify"],
                },
                "mode": {"type": "string", "enum": ["assist", "damping"]},
                "delta": {"type": "number", "enum": [0.1, -0.1]},
                "question": {"type": "string"},
                "reply": {"type": "string"},
            },
            "required": ["action"],
        },
    },
}


# ---------------------------------------------------------------------------
# Status rendering (program is the source of truth, never the model)
# ---------------------------------------------------------------------------

_FIELD_ALIASES = {
    "mode": ("mode",),
    "assist_ratio": ("assist_ratio",),
    "battery": ("battery",),
    "temperature": ("temperature",),
    "joints": ("joints",),
    "imu": ("imu",),
    "can": ("can",),
    "fault": ("fault",),
}


def render_status(state: Optional[StateData], stale: bool, fields: list[str]) -> str:
    if state is None or stale:
        return "设备数据失联：当前没有可用的实时状态，请检查设备连接。"
    parts: list[str] = []
    fset = set(fields or _FIELD_ALIASES.keys())
    if "mode" in fset:
        parts.append("当前模式：" + ("助力模式" if state.mode is Mode.ASSIST else "阻尼训练模式"))
    if "assist_ratio" in fset:
        parts.append(f"助力强度：{int(round(state.assist_ratio * 100))}%")
    if "battery" in fset:
        parts.append(f"电池：{state.battery_percent:.0f}%（{state.bus_voltage:.1f}V）")
    if "temperature" in fset:
        parts.append(f"电机最高温度:{max(state.motor_temperature):.1f}℃")
    if "joints" in fset:
        names = ["左髋", "左膝", "右髋", "右膝"]
        joints = "，".join(
            f"{n} {p:.2f}rad" for n, p in zip(names, state.joint_position)
        )
        parts.append("关节角度：" + joints)
    if "imu" in fset:
        online = sum(state.imu_online)
        calibrated = sum(state.imu_calibrated)
        parts.append(f"IMU：{online}/4 在线，{calibrated}/4 已标定")
    if "can" in fset:
        parts.append("CAN 总线：" + ("正常" if state.can_online else "离线"))
    if "fault" in fset:
        if state.emergency_stop:
            parts.append("⚠️ 急停已触发")
        parts.append(
            f"故障：{state.fault_code}（{state.fault_message}）" if state.fault_code else "无故障"
        )
    return "；".join(parts) + "。"


def describe_command(view: CommandView) -> str:
    label = {"set_mode": "模式切换", "adjust_assist": "助力调节"}.get(view.action, view.action)
    if view.status is CommandStatus.SUCCESS:
        return f"{label}执行成功。{view.message}".strip()
    if view.status is CommandStatus.PENDING_CONFIRMATION:
        return "模式切换需要二次确认，请在弹窗中确认。"
    if view.status is CommandStatus.TIMEOUT:
        return f"{label}超时：控制器未响应，命令执行失败。"
    if view.status is CommandStatus.REJECTED:
        return f"{label}被拒绝:{view.message or view.error_code}"
    if view.status is CommandStatus.FAILED:
        return f"{label}执行失败:{view.message or view.error_code}"
    return f"{label}状态:{view.status.value}"


# ---------------------------------------------------------------------------
# The router
# ---------------------------------------------------------------------------

CLARIFY_REPLY = "抱歉，我没听懂你的意思。你可以说：「查询状态」「增大/减小助力」「切换到阻尼训练模式」，或询问教程问题。"
NO_DOC_REPLY = "当前教程文档中没有找到相关说明。"


class IntentRouter:
    def __init__(
        self,
        settings: Settings,
        cache: StateCache,
        commands: CommandManager,
        llm: LlmClient,
        rag: RagService,
    ) -> None:
        self._settings = settings
        self._cache = cache
        self._commands = commands
        self._llm = llm
        self._rag = rag
        self._rag_ready = threading.Event()

    def start_rag_indexing(self) -> None:
        """Build the RAG index off the event loop (jieba warmup + PDFs)."""

        def _build() -> None:
            try:
                stats = self._rag.build_index()
                logger.info("RAG index ready: %s", stats)
            except Exception:
                logger.exception("RAG index build failed")
            finally:
                self._rag_ready.set()

        threading.Thread(target=_build, name="rag-index", daemon=True).start()

    # ------------------------------------------------------------ pipeline

    async def handle(self, text: str) -> ChatResponse:
        action, clarify_reply = await self._parse(text)
        if action is None:
            return ChatResponse(reply=clarify_reply or CLARIFY_REPLY,
                                intent="clarify", need_clarification=True)

        control_event("intent", text=text, action=action.action,
                      params=action.model_dump(exclude={"action"}))

        if isinstance(action, QueryStatusAction):
            reply = render_status(self._cache.get(), self._cache.is_stale(), action.fields)
            return ChatResponse(reply=reply, intent="query_status")

        if isinstance(action, DocumentQaAction):
            return await self._answer_from_docs(action.question)

        # write actions → command manager (same SafetyGuard as buttons)
        view = await self._commands.submit(action)
        return ChatResponse(
            reply=describe_command(view),
            intent=action.action,
            command=view,
            need_confirmation=view.status is CommandStatus.PENDING_CONFIRMATION,
        )

    async def _parse(self, text: str) -> tuple[Optional[Action], Optional[str]]:
        action = route_by_rules(text)
        if action is not None:
            control_event("intent_source", source="rules", text=text)
            return action, None
        try:
            if self._settings.llm.force_json_fallback:
                return await self._parse_via_json(text)
            return await self._parse_via_tools(text)
        except LlmError as exc:
            logger.warning("LLM unavailable: %s", exc)
            return None, "本地大模型暂时不可用。你仍可以使用页面按钮，或用「查询状态」「增大助力」这类固定说法。"

    async def _parse_via_tools(self, text: str) -> tuple[Optional[Action], Optional[str]]:
        message = await self._llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": text},
            ],
            tools=TOOLS,
        )
        call = extract_tool_call(message)
        if call is None:
            content = (message.get("content") or "").strip()
            return None, content or None  # model chose to clarify in words
        name, args = call
        return self._validate(name, args)

    async def _parse_via_json(self, text: str) -> tuple[Optional[Action], Optional[str]]:
        message = await self._llm.chat(
            [
                {"role": "system", "content": SYSTEM_PROMPT
                 + "\n请以 JSON 输出你的决定：{\"action\": ..., 其他参数}；无法判断时 {\"action\": \"clarify\", \"reply\": \"...\"}"},
                {"role": "user", "content": text},
            ],
            response_format=_JSON_FALLBACK_SCHEMA,
        )
        try:
            data = json.loads(message.get("content") or "{}")
        except json.JSONDecodeError:
            return None, None
        name = data.pop("action", "")
        if name == "clarify":
            return None, data.get("reply") or None
        data.pop("reply", None)
        return self._validate(name, {k: v for k, v in data.items() if v is not None})

    def _validate(self, name: str, args: dict[str, Any]) -> tuple[Optional[Action], Optional[str]]:
        """LLM output is untrusted: re-validate through the typed whitelist."""
        try:
            action = ActionEnvelope.parse_untrusted({"action": name, **args})
            control_event("intent_source", source="llm", action=name)
            return action, None
        except ValidationError:
            control_event("intent_invalid", action=name, args=args)
            logger.warning("LLM produced invalid action %r %r", name, args)
            return None, None

    # ------------------------------------------------------------- doc QA

    async def _answer_from_docs(self, question: str) -> ChatResponse:
        if not self._rag_ready.is_set():
            return ChatResponse(reply="教程索引正在构建，请稍后再试。", intent="document_qa")
        hits = await asyncio.to_thread(self._rag.search, question)
        if not hits:
            return ChatResponse(reply=NO_DOC_REPLY, intent="document_qa")

        sources = [{"file": h.file, "section": h.section} for h in hits]
        context = "\n\n".join(
            f"【片段{i} 来源:{h.file} {h.section}】\n{h.text}" for i, h in enumerate(hits, 1)
        )
        try:
            message = await self._llm.chat(
                [
                    {
                        "role": "system",
                        "content": "你是外骨骼设备的教程问答助手。只根据提供的文档片段回答，"
                        "不得编造文档中没有的操作步骤。回答末尾注明依据的来源文件名。"
                        "如果片段与问题无关，回答「当前教程文档中没有找到相关说明」。",
                    },
                    {"role": "user", "content": f"文档片段：\n{context}\n\n问题：{question}"},
                ],
            )
            reply = (message.get("content") or "").strip() or NO_DOC_REPLY
        except LlmError:
            # degrade: return raw best chunk so the demo still works
            reply = f"（大模型不可用，以下为最相关的文档片段）\n{hits[0].text[:500]}"
        return ChatResponse(reply=reply, intent="document_qa", sources=sources)


def build_chat_handler(settings: Settings, cache: StateCache, commands: CommandManager):
    """Factory used by main.build_app; returns an async ChatHandler."""
    from .config import PACKAGE_ROOT

    llm = LlmClient(settings.llm)
    rag = RagService(settings.rag, base_dir=PACKAGE_ROOT)
    router = IntentRouter(settings, cache, commands, llm, rag)
    router.start_rag_indexing()

    async def handler(text: str) -> ChatResponse:
        return await router.handle(text)

    handler.router = router  # type: ignore[attr-defined]  # exposed for tests
    return handler
