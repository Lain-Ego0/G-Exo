"""Typed contracts for gexo_web_agent.

Three layers of models:

1. Actions       — the ONLY four intents the LLM / web UI may produce
                   (query_status / set_mode / adjust_assist / document_qa).
2. Wire messages — the JSON payload carried on the single bridge topic
                   (command / state / result), correlated by request_id.
3. API models    — request/response bodies for the HTTP endpoints.

Everything coming from the LLM or the network MUST pass through these
models before it can reach the ROS bridge.  Untrusted input is never
forwarded raw.
"""
from __future__ import annotations

import enum
import time
import uuid
from typing import Annotated, Any, Literal, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator

WIRE_VERSION = "1.0"

JOINT_NAMES = ["left_hip", "left_knee", "right_hip", "right_knee"]

STATUS_FIELDS = [
    "mode",
    "assist_ratio",
    "battery",
    "temperature",
    "joints",
    "imu",
    "can",
    "fault",
]


class Mode(str, enum.Enum):
    ASSIST = "assist"
    DAMPING = "damping"


class ErrorCode(str, enum.Enum):
    # Controller-reported / safety failure reasons (part of the wire contract)
    NOT_STATIONARY = "NOT_STATIONARY"
    EMERGENCY_STOP_ACTIVE = "EMERGENCY_STOP_ACTIVE"
    FAULT_ACTIVE = "FAULT_ACTIVE"
    CAN_OFFLINE = "CAN_OFFLINE"
    STATE_TIMEOUT = "STATE_TIMEOUT"
    ASSIST_AT_MAXIMUM = "ASSIST_AT_MAXIMUM"
    ASSIST_AT_MINIMUM = "ASSIST_AT_MINIMUM"
    INVALID_MODE = "INVALID_MODE"
    CONTROLLER_TIMEOUT = "CONTROLLER_TIMEOUT"
    # Web-agent-side rejection reasons
    NO_STATE = "NO_STATE"
    ASSIST_IN_DAMPING = "ASSIST_IN_DAMPING"
    INVALID_DELTA = "INVALID_DELTA"
    CONFIRMATION_REQUIRED = "CONFIRMATION_REQUIRED"
    CONFIRMATION_EXPIRED = "CONFIRMATION_EXPIRED"
    BUSY = "BUSY"
    INVALID_ACTION = "INVALID_ACTION"


class CommandStatus(str, enum.Enum):
    PENDING_CONFIRMATION = "pending_confirmation"
    SENT = "sent"
    SUCCESS = "success"
    FAILED = "failed"
    TIMEOUT = "timeout"
    REJECTED = "rejected"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


# ---------------------------------------------------------------------------
# 1. Actions (LLM tool schema — the whitelist)
# ---------------------------------------------------------------------------


class QueryStatusAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["query_status"] = "query_status"
    fields: list[str] = Field(default_factory=lambda: list(STATUS_FIELDS))

    @field_validator("fields")
    @classmethod
    def _known_fields(cls, v: list[str]) -> list[str]:
        unknown = [f for f in v if f not in STATUS_FIELDS]
        if unknown:
            raise ValueError(f"unknown status fields: {unknown}")
        return v or list(STATUS_FIELDS)


class SetModeAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["set_mode"] = "set_mode"
    mode: Mode


class AdjustAssistAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["adjust_assist"] = "adjust_assist"
    delta: float

    @field_validator("delta")
    @classmethod
    def _delta_exact_step(cls, v: float) -> float:
        # The ONLY legal deltas are +0.1 and -0.1 (tolerate float representation).
        if abs(abs(v) - 0.1) > 1e-9:
            raise ValueError("delta must be exactly +0.1 or -0.1")
        return 0.1 if v > 0 else -0.1


class DocumentQaAction(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal["document_qa"] = "document_qa"
    question: str = Field(min_length=1, max_length=2000)


Action = Annotated[
    Union[QueryStatusAction, SetModeAction, AdjustAssistAction, DocumentQaAction],
    Field(discriminator="action"),
]

WRITE_ACTIONS = ("set_mode", "adjust_assist")


class ActionEnvelope(BaseModel):
    """Helper for validating an untrusted {'action': ..., ...} dict."""

    root: Action

    @classmethod
    def parse_untrusted(cls, data: dict[str, Any]) -> Action:
        return cls(root=data).root  # type: ignore[arg-type]


# ---------------------------------------------------------------------------
# 2. Wire messages on the bridge topic
# ---------------------------------------------------------------------------


def now_ms() -> int:
    return int(time.time() * 1000)


def new_request_id() -> str:
    return uuid.uuid4().hex


class BridgeCommand(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: str = WIRE_VERSION
    type: Literal["command"] = "command"
    source: str = "gexo_web_agent"
    timestamp_ms: int = Field(default_factory=now_ms)
    request_id: str = Field(default_factory=new_request_id)
    action: Literal["set_mode", "adjust_assist"]
    params: dict[str, Any]


class StateData(BaseModel):
    """Controller state snapshot payload. Extra keys are tolerated (the real
    controller may add fields before we do)."""

    model_config = ConfigDict(extra="allow")

    mode: Mode = Mode.ASSIST
    assist_ratio: float = 0.5
    is_stationary: bool = False
    joint_position: list[float] = Field(default_factory=lambda: [0.0] * 4)
    joint_velocity: list[float] = Field(default_factory=lambda: [0.0] * 4)
    command_torque: list[float] = Field(default_factory=lambda: [0.0] * 4)
    estimated_torque: list[float] = Field(default_factory=lambda: [0.0] * 4)
    motor_temperature: list[float] = Field(default_factory=lambda: [0.0] * 4)
    bus_voltage: float = 0.0
    bus_current: float = 0.0
    battery_percent: float = 0.0
    imu_online: list[bool] = Field(default_factory=lambda: [False] * 4)
    imu_calibrated: list[bool] = Field(default_factory=lambda: [False] * 4)
    can_online: bool = False
    emergency_stop: bool = False
    fault_code: str = ""
    fault_message: str = ""


class BridgeState(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str = WIRE_VERSION
    type: Literal["state"] = "state"
    source: str = "gexo_controller"
    timestamp_ms: int = Field(default_factory=now_ms)
    request_id: str = ""
    data: StateData


class BridgeResult(BaseModel):
    model_config = ConfigDict(extra="allow")
    version: str = WIRE_VERSION
    type: Literal["result"] = "result"
    source: str = "gexo_controller"
    timestamp_ms: int = Field(default_factory=now_ms)
    request_id: str
    success: bool
    error_code: str = ""
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)


def parse_bridge_message(data: dict[str, Any]) -> Union[BridgeCommand, BridgeState, BridgeResult]:
    """Parse an incoming JSON dict into the right wire model by its `type`."""
    msg_type = data.get("type")
    if msg_type == "command":
        return BridgeCommand.model_validate(data)
    if msg_type == "state":
        return BridgeState.model_validate(data)
    if msg_type == "result":
        return BridgeResult.model_validate(data)
    raise ValueError(f"unknown bridge message type: {msg_type!r}")


# ---------------------------------------------------------------------------
# 3. HTTP API models
# ---------------------------------------------------------------------------


class ChatRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    text: str = Field(min_length=1, max_length=2000)


class ActionRequest(BaseModel):
    """Explicit-button endpoint body: a whitelisted action, no NL parsing."""

    model_config = ConfigDict(extra="forbid")
    action: str
    params: dict[str, Any] = Field(default_factory=dict)


class ConfirmRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str
    approve: bool


class CommandView(BaseModel):
    """Serialized command record returned by the API."""

    request_id: str
    status: CommandStatus
    action: str
    params: dict[str, Any] = Field(default_factory=dict)
    error_code: str = ""
    message: str = ""
    result: dict[str, Any] = Field(default_factory=dict)
    created_ms: int = 0
    finished_ms: Optional[int] = None


class ChatResponse(BaseModel):
    reply: str
    intent: str = "chat"
    command: Optional[CommandView] = None
    sources: list[dict[str, Any]] = Field(default_factory=list)
    need_confirmation: bool = False
    need_clarification: bool = False


class StateResponse(BaseModel):
    online: bool
    stale: bool
    state: Optional[StateData] = None
    last_update_ms: Optional[int] = None
