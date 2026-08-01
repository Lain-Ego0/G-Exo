"""Command lifecycle: confirmation → publish → result correlation → timeout.

`CommandManager` is the single source of truth for command records:

    pending_confirmation ─▶ sent ─▶ success | failed
                │                        │
                ├─▶ expired / cancelled  └─(no result)─▶ timeout
    (safety) ─▶ rejected

Rules enforced here:
- success is ONLY reported after a controller `result` arrives (never assumed)
- timeout means failure; there is NO automatic retry
- confirm re-runs SafetyGuard against FRESH state (things may have changed
  while the user was staring at the dialog)
- one write command in flight at a time (second one → BUSY)

Thread model: the asyncio web thread calls submit/confirm/get_view; the
transport thread calls on_result.  Records are guarded by a threading.Lock;
completion is signalled via loop.call_soon_threadsafe(event.set).
"""
from __future__ import annotations

import asyncio
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

from .config import CommandConfig, SafetyConfig
from .logging_config import control_event
from .ros_bridge import RosBridgeAdapter
from .safety_guard import Reject, check
from .schemas import (
    Action,
    BridgeCommand,
    BridgeResult,
    CommandStatus,
    CommandView,
    ErrorCode,
    SetModeAction,
    new_request_id,
    now_ms,
)
from .state_cache import StateCache

TERMINAL = {
    CommandStatus.SUCCESS,
    CommandStatus.FAILED,
    CommandStatus.TIMEOUT,
    CommandStatus.REJECTED,
    CommandStatus.EXPIRED,
    CommandStatus.CANCELLED,
}


@dataclass
class CommandRecord:
    request_id: str
    action: str
    params: dict[str, Any]
    status: CommandStatus
    action_obj: Optional[Action] = None
    error_code: str = ""
    message: str = ""
    result: dict[str, Any] = field(default_factory=dict)
    created_ms: int = field(default_factory=now_ms)
    finished_ms: Optional[int] = None
    expires_monotonic: Optional[float] = None
    event: Optional[asyncio.Event] = None

    def view(self) -> CommandView:
        return CommandView(
            request_id=self.request_id,
            status=self.status,
            action=self.action,
            params=self.params,
            error_code=self.error_code,
            message=self.message,
            result=self.result,
            created_ms=self.created_ms,
            finished_ms=self.finished_ms,
        )


def _action_params(action: Action) -> dict[str, Any]:
    return action.model_dump(exclude={"action"})


class CommandManager:
    def __init__(
        self,
        state_cache: StateCache,
        bridge: RosBridgeAdapter,
        safety_cfg: SafetyConfig,
        command_cfg: CommandConfig,
        source_id: str = "gexo_web_agent",
    ) -> None:
        self._state_cache = state_cache
        self._bridge = bridge
        self._safety_cfg = safety_cfg
        self._cfg = command_cfg
        self._source_id = source_id
        self._records: OrderedDict[str, CommandRecord] = OrderedDict()
        self._lock = threading.Lock()
        self._loop: Optional[asyncio.AbstractEventLoop] = None
        self._inflight = asyncio.Lock()
        bridge.on_result(self.on_result)

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        self._loop = loop

    # ------------------------------------------------------------------ API

    async def submit(self, action: Action) -> CommandView:
        """Entry point for both /api/chat and /api/action write requests."""
        if action.action not in ("set_mode", "adjust_assist"):
            raise ValueError("submit() only accepts write actions")

        decision = check(
            action,
            self._state_cache.get(),
            state_stale=self._state_cache.is_stale(),
            confirmed=False,
            cfg=self._safety_cfg,
        )

        if isinstance(decision, Reject):
            if (
                isinstance(action, SetModeAction)
                and decision.error_code is ErrorCode.CONFIRMATION_REQUIRED
            ):
                return self._create_pending(action)
            return self._record_rejected(action, decision)

        return await self._publish_and_wait(action, request_id=new_request_id())

    async def confirm(self, request_id: str, approve: bool) -> Optional[CommandView]:
        """Resolve a pending_confirmation record. Returns None if unknown."""
        with self._lock:
            rec = self._records.get(request_id)
            if rec is None:
                return None
            if rec.status is not CommandStatus.PENDING_CONFIRMATION:
                return rec.view()
            if rec.expires_monotonic is not None and time.monotonic() > rec.expires_monotonic:
                self._finish_locked(rec, CommandStatus.EXPIRED, ErrorCode.CONFIRMATION_EXPIRED.value, "确认已超时，请重新发起")
                return rec.view()
            if not approve:
                self._finish_locked(rec, CommandStatus.CANCELLED, "", "已取消")
                return rec.view()
            action = rec.action_obj

        assert action is not None
        # Re-validate against FRESH state now that the user has confirmed.
        decision = check(
            action,
            self._state_cache.get(),
            state_stale=self._state_cache.is_stale(),
            confirmed=True,
            cfg=self._safety_cfg,
        )
        if isinstance(decision, Reject):
            with self._lock:
                self._finish_locked(rec, CommandStatus.REJECTED, decision.error_code.value, decision.message)
            control_event(
                "safety_reject", request_id=request_id, action=action.action,
                error_code=decision.error_code.value,
            )
            return rec.view()

        return await self._publish_and_wait(action, request_id=request_id, record=rec)

    def get_view(self, request_id: str) -> Optional[CommandView]:
        with self._lock:
            rec = self._records.get(request_id)
            # surface expiry on read, so polling clients see the truth
            if (
                rec is not None
                and rec.status is CommandStatus.PENDING_CONFIRMATION
                and rec.expires_monotonic is not None
                and time.monotonic() > rec.expires_monotonic
            ):
                self._finish_locked(rec, CommandStatus.EXPIRED, ErrorCode.CONFIRMATION_EXPIRED.value, "确认已超时，请重新发起")
            return rec.view() if rec else None

    # ------------------------------------------------------- transport side

    def on_result(self, result: BridgeResult) -> None:
        """Called from the transport thread for every controller result."""
        with self._lock:
            rec = self._records.get(result.request_id)
            if rec is None or rec.status is not CommandStatus.SENT:
                return  # late/duplicate/foreign result — first terminal state wins
            status = CommandStatus.SUCCESS if result.success else CommandStatus.FAILED
            self._finish_locked(rec, status, result.error_code, result.message, result.result)
            event, loop = rec.event, self._loop
        if event is not None:
            if loop is not None:
                loop.call_soon_threadsafe(event.set)
            else:  # pragma: no cover - test convenience
                event.set()

    # -------------------------------------------------------------- helpers

    def _create_pending(self, action: SetModeAction) -> CommandView:
        rec = CommandRecord(
            request_id=new_request_id(),
            action=action.action,
            params=_action_params(action),
            status=CommandStatus.PENDING_CONFIRMATION,
            action_obj=action,
            message="模式切换需要确认",
            expires_monotonic=time.monotonic() + self._cfg.confirm_ttl_s,
        )
        with self._lock:
            self._store_locked(rec)
        control_event("pending_confirmation", request_id=rec.request_id, action=action.action, params=rec.params)
        return rec.view()

    def _record_rejected(self, action: Action, decision: Reject) -> CommandView:
        rec = CommandRecord(
            request_id=new_request_id(),
            action=action.action,
            params=_action_params(action),
            status=CommandStatus.REJECTED,
            error_code=decision.error_code.value,
            message=decision.message,
            finished_ms=now_ms(),
        )
        with self._lock:
            self._store_locked(rec)
        control_event(
            "safety_reject", request_id=rec.request_id, action=action.action,
            error_code=decision.error_code.value,
        )
        return rec.view()

    async def _publish_and_wait(
        self,
        action: Action,
        request_id: str,
        record: Optional[CommandRecord] = None,
    ) -> CommandView:
        if self._inflight.locked():
            busy = Reject(ErrorCode.BUSY, "已有命令执行中，请稍候")
            if record is not None:
                with self._lock:
                    self._finish_locked(record, CommandStatus.REJECTED, busy.error_code.value, busy.message)
                return record.view()
            return self._record_rejected(action, busy)

        async with self._inflight:
            event = asyncio.Event()
            with self._lock:
                if record is None:
                    record = CommandRecord(
                        request_id=request_id,
                        action=action.action,
                        params=_action_params(action),
                        status=CommandStatus.SENT,
                        action_obj=action,
                    )
                    self._store_locked(record)
                else:
                    record.status = CommandStatus.SENT
                    record.message = ""
                record.event = event

            command = BridgeCommand(
                source=self._source_id,
                request_id=request_id,
                action=action.action,  # type: ignore[arg-type]
                params=_action_params(action),
            )
            start = time.monotonic()
            control_event("command_sent", request_id=request_id, action=action.action, params=command.params)
            self._bridge.send_command(command)

            try:
                await asyncio.wait_for(event.wait(), timeout=self._cfg.result_timeout_s)
            except asyncio.TimeoutError:
                with self._lock:
                    if record.status is CommandStatus.SENT:  # result may have just landed
                        self._finish_locked(
                            record,
                            CommandStatus.TIMEOUT,
                            ErrorCode.CONTROLLER_TIMEOUT.value,
                            "控制器未在时限内响应，命令执行失败",
                        )
            elapsed_ms = int((time.monotonic() - start) * 1000)
            with self._lock:
                view = record.view()
            control_event(
                "command_finished", request_id=request_id, action=action.action,
                status=view.status.value, error_code=view.error_code, elapsed_ms=elapsed_ms,
            )
            return view

    def _store_locked(self, rec: CommandRecord) -> None:
        self._records[rec.request_id] = rec
        while len(self._records) > self._cfg.history_size:
            self._records.popitem(last=False)

    @staticmethod
    def _finish_locked(
        rec: CommandRecord,
        status: CommandStatus,
        error_code: str,
        message: str,
        result: Optional[dict[str, Any]] = None,
    ) -> None:
        rec.status = status
        rec.error_code = error_code
        rec.message = message
        if result is not None:
            rec.result = result
        rec.finished_ms = now_ms()
