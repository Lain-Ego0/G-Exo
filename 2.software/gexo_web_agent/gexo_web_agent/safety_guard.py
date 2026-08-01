"""Independent safety validation for all write operations.

This module is deliberately a STATELESS pure function: given an action and a
state snapshot, it returns Allow or Reject.  It is shared verbatim by
/api/chat (LLM path) and /api/action (button path) — the LLM path gets no
privilege difference.  Prompt-level "safety" is never the only protection.

Check order for write actions (first failure wins):

 1. NO_STATE                 — never received controller state
 2. STATE_TIMEOUT            — state older than stale_timeout_s
 3. EMERGENCY_STOP_ACTIVE    — e-stop engaged
 4. FAULT_ACTIVE             — fault code present
 5. CAN_OFFLINE              — CAN bus down
 6. ASSIST_IN_DAMPING        — adjust_assist while in DAMPING
 7. INVALID_DELTA            — delta not exactly ±0.1 (defense in depth)
 8. ASSIST_AT_MAXIMUM/MINIMUM— resulting ratio outside [assist_min, assist_max]
 9. CONFIRMATION_REQUIRED    — set_mode without explicit confirmation
10. NOT_STATIONARY           — set_mode while moving
11. INVALID_MODE             — set_mode to the current mode (soft reject)

Read-only actions (query_status / document_qa) are always allowed — staleness
is surfaced by the API layer, not blocked here.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Union

from .config import SafetyConfig
from .schemas import (
    Action,
    AdjustAssistAction,
    ErrorCode,
    Mode,
    SetModeAction,
    StateData,
)

_EPS = 1e-9


@dataclass(frozen=True)
class Allow:
    allowed: bool = field(default=True, init=False)


@dataclass(frozen=True)
class Reject:
    error_code: ErrorCode
    message: str
    allowed: bool = field(default=False, init=False)


SafetyDecision = Union[Allow, Reject]


def check(
    action: Action,
    state: Optional[StateData],
    *,
    state_stale: bool,
    confirmed: bool = False,
    cfg: SafetyConfig,
) -> SafetyDecision:
    """Validate `action` against the latest controller state snapshot.

    `state_stale` must come from StateCache.is_stale() — the guard does not
    read clocks itself so it stays a pure function (trivially testable).
    """
    if action.action not in ("set_mode", "adjust_assist"):
        return Allow()  # read-only actions

    # 1-2: we must have fresh ground truth before any write
    if state is None:
        return Reject(ErrorCode.NO_STATE, "尚未收到设备状态，无法执行操作")
    if state_stale:
        return Reject(ErrorCode.STATE_TIMEOUT, "设备状态数据超时，无法执行操作")

    # 3-5: hard platform interlocks
    if state.emergency_stop:
        return Reject(ErrorCode.EMERGENCY_STOP_ACTIVE, "急停已触发，拒绝所有写操作")
    if state.fault_code:
        return Reject(
            ErrorCode.FAULT_ACTIVE,
            f"设备存在故障（{state.fault_code}），拒绝所有写操作",
        )
    if not state.can_online:
        return Reject(ErrorCode.CAN_OFFLINE, "CAN 总线离线，拒绝所有写操作")

    if isinstance(action, AdjustAssistAction):
        return _check_adjust_assist(action, state, cfg)
    if isinstance(action, SetModeAction):
        return _check_set_mode(action, state, confirmed)
    return Reject(ErrorCode.INVALID_ACTION, "未定义的操作")  # pragma: no cover


def _check_adjust_assist(
    action: AdjustAssistAction, state: StateData, cfg: SafetyConfig
) -> SafetyDecision:
    # 6: assist adjustments are meaningless (and forbidden) in DAMPING
    if state.mode is Mode.DAMPING:
        return Reject(ErrorCode.ASSIST_IN_DAMPING, "阻尼训练模式下不允许调节助力")

    # 7: defense in depth — schemas already enforce this, re-check anyway
    if abs(abs(action.delta) - cfg.assist_step) > _EPS:
        return Reject(ErrorCode.INVALID_DELTA, "助力调节步长必须为 ±10%")

    # 8: resulting ratio must stay inside [assist_min, assist_max]
    target = round(state.assist_ratio + action.delta, 1)
    if target > cfg.assist_max + _EPS:
        return Reject(
            ErrorCode.ASSIST_AT_MAXIMUM,
            f"助力已达最大值 {int(round(cfg.assist_max * 100))}%，无法继续增加",
        )
    if target < cfg.assist_min - _EPS:
        return Reject(
            ErrorCode.ASSIST_AT_MINIMUM,
            f"助力已达最小值 {int(round(cfg.assist_min * 100))}%，无法继续减小",
        )
    return Allow()


def _check_set_mode(action: SetModeAction, state: StateData, confirmed: bool) -> SafetyDecision:
    # 9: mode switch is high-impact — must be explicitly confirmed
    if not confirmed:
        return Reject(ErrorCode.CONFIRMATION_REQUIRED, "模式切换需要二次确认")

    # 10: only allowed while standing still
    if not state.is_stationary:
        return Reject(ErrorCode.NOT_STATIONARY, "请先站立静止，再切换模式")

    # 11: switching to the mode we're already in is pointless (soft reject)
    if state.mode is action.mode:
        label = "助力模式" if action.mode is Mode.ASSIST else "阻尼训练模式"
        return Reject(ErrorCode.INVALID_MODE, f"当前已是{label}")
    return Allow()
