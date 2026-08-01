"""ROS-free controller simulation core.

Shared by two shells:
- `MockTransport` (in-process, for Windows dev / demo without ROS 2)
- `scripts/mock_controller.py` / `mock_controller_node.py` (standalone rclpy
  node on the device)

The core is the authoritative "controller" in mock mode: it re-validates every
command the same way the real controller would, so the web agent's safety layer
is never the only line of defense.
"""
from __future__ import annotations

import threading
from typing import Any, Optional

from .schemas import (
    BridgeResult,
    BridgeState,
    ErrorCode,
    Mode,
    StateData,
)

SCENARIOS = ("normal", "estop", "fault", "can_offline", "moving", "overheat", "no_reply", "fail")

ASSIST_MIN = 0.3
ASSIST_MAX = 1.0
ASSIST_STEP = 0.1


class MockControllerCore:
    """Simulated exoskeleton controller state machine."""

    def __init__(self, scenario: str = "normal", source_id: str = "gexo_controller_mock") -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario: {scenario!r}")
        self._lock = threading.Lock()
        self._source_id = source_id
        self._scenario = scenario
        self._mode = Mode.ASSIST
        self._assist_ratio = 0.5

    # -- scenario control ---------------------------------------------------

    def set_scenario(self, scenario: str) -> None:
        if scenario not in SCENARIOS:
            raise ValueError(f"unknown scenario: {scenario!r}")
        with self._lock:
            self._scenario = scenario

    def get_scenario(self) -> str:
        with self._lock:
            return self._scenario

    # -- state --------------------------------------------------------------

    def build_state(self) -> dict[str, Any]:
        """Produce a `state` wire message dict reflecting the scenario."""
        with self._lock:
            s = self._scenario
            data = StateData(
                mode=self._mode,
                assist_ratio=round(self._assist_ratio, 1),
                is_stationary=(s != "moving"),
                joint_position=[0.12, 0.34, 0.11, 0.33],
                joint_velocity=[0.0, 0.0, 0.0, 0.0] if s != "moving" else [0.8, 1.2, 0.7, 1.1],
                command_torque=[1.5, 2.0, 1.4, 2.1],
                estimated_torque=[1.4, 1.9, 1.5, 2.0],
                motor_temperature=[38.0, 41.0, 39.0, 40.0] if s != "overheat" else [38.0, 85.0, 39.0, 40.0],
                bus_voltage=24.1,
                bus_current=1.8,
                battery_percent=76.0,
                imu_online=[True, True, True, True],
                imu_calibrated=[True, True, True, True],
                can_online=(s != "can_offline"),
                emergency_stop=(s == "estop"),
                fault_code="OVER_TEMP" if s == "overheat" else ("E100" if s == "fault" else ""),
                fault_message="电机温度过高" if s == "overheat" else ("模拟故障" if s == "fault" else ""),
            )
        return BridgeState(source=self._source_id, data=data).model_dump()

    # -- command handling ---------------------------------------------------

    def handle_command(self, cmd: dict[str, Any]) -> Optional[dict[str, Any]]:
        """Validate & apply a `command` wire message.

        Returns a `result` wire message dict, or None for the `no_reply`
        scenario (simulating a dead controller → web agent must time out).
        """
        request_id = str(cmd.get("request_id", ""))
        action = cmd.get("action")
        params = cmd.get("params") or {}

        with self._lock:
            s = self._scenario
            if s == "no_reply":
                return None
            if s == "fail":
                return self._result(request_id, False, ErrorCode.INVALID_MODE, "模拟执行失败")
            if s == "estop":
                return self._result(request_id, False, ErrorCode.EMERGENCY_STOP_ACTIVE, "急停已触发，拒绝执行")
            if s in ("fault", "overheat"):
                return self._result(request_id, False, ErrorCode.FAULT_ACTIVE, "存在故障，拒绝执行")
            if s == "can_offline":
                return self._result(request_id, False, ErrorCode.CAN_OFFLINE, "CAN 总线离线，拒绝执行")

            if action == "set_mode":
                return self._handle_set_mode(request_id, params, moving=(s == "moving"))
            if action == "adjust_assist":
                return self._handle_adjust_assist(request_id, params)
            return self._result(request_id, False, ErrorCode.INVALID_MODE, f"未知命令: {action}")

    def _handle_set_mode(self, request_id: str, params: dict[str, Any], moving: bool) -> dict[str, Any]:
        target = params.get("mode")
        if target not in (Mode.ASSIST.value, Mode.DAMPING.value):
            return self._result(request_id, False, ErrorCode.INVALID_MODE, f"无效模式: {target}")
        if moving:
            return self._result(request_id, False, ErrorCode.NOT_STATIONARY, "运动中禁止切换模式，请先站立静止")
        self._mode = Mode(target)
        label = "助力模式" if self._mode is Mode.ASSIST else "阻尼训练模式"
        return self._result(request_id, True, None, f"已切换到{label}")

    def _handle_adjust_assist(self, request_id: str, params: dict[str, Any]) -> dict[str, Any]:
        if self._mode is Mode.DAMPING:
            return self._result(request_id, False, ErrorCode.INVALID_MODE, "阻尼训练模式下不允许调节助力")
        try:
            delta = float(params.get("delta"))
        except (TypeError, ValueError):
            return self._result(request_id, False, ErrorCode.INVALID_MODE, "无效的助力调节参数")
        if abs(abs(delta) - ASSIST_STEP) > 1e-9:
            return self._result(request_id, False, ErrorCode.INVALID_MODE, "助力调节步长必须为 ±0.1")
        target = round(self._assist_ratio + delta, 1)
        if target > ASSIST_MAX + 1e-9:
            return self._result(request_id, False, ErrorCode.ASSIST_AT_MAXIMUM, "助力已达最大值 100%")
        if target < ASSIST_MIN - 1e-9:
            return self._result(request_id, False, ErrorCode.ASSIST_AT_MINIMUM, "助力已达最小值 30%")
        self._assist_ratio = target
        return self._result(request_id, True, None, f"助力已调整到 {int(round(target * 100))}%")

    def _result(
        self,
        request_id: str,
        success: bool,
        error_code: Optional[ErrorCode],
        message: str,
    ) -> dict[str, Any]:
        return BridgeResult(
            source=self._source_id,
            request_id=request_id,
            success=success,
            error_code=error_code.value if error_code else "",
            message=message,
            result={"mode": self._mode.value, "assist_ratio": round(self._assist_ratio, 1)},
        ).model_dump()
