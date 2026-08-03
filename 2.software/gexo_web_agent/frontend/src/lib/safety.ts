import type { RobotSocketView, RobotMode } from "../types/robot";

export function baseWriteBlocker(robot: RobotSocketView): string | null {
  const state = robot.snapshot?.state;
  if (!state) return "NO CONTROLLER STATE";
  if (robot.connection !== "online") return "CONTROLLER STATE IS STALE";
  if (state.emergency_stop) return "E-STOP ACTIVE";
  if (state.fault_code) return `FAULT ${state.fault_code}`;
  if (state.can_online !== true) return "CAN OFFLINE";
  return null;
}

export function modeWriteBlocker(
  robot: RobotSocketView,
  targetMode: RobotMode,
): string | null {
  const blocker = baseWriteBlocker(robot);
  if (blocker) return blocker;
  const state = robot.snapshot?.state;
  if (state?.is_stationary !== true) return "WEARER IS MOVING";
  if (state.mode === targetMode) return "MODE ALREADY ACTIVE";
  return null;
}

export function assistWriteBlocker(
  robot: RobotSocketView,
  delta: 0.1 | -0.1,
): string | null {
  const blocker = baseWriteBlocker(robot);
  if (blocker) return blocker;
  const state = robot.snapshot?.state;
  if (state?.mode === "damping") return "ASSIST DISABLED IN DAMPING";
  if (typeof state?.assist_ratio !== "number") return "ASSIST DATA UNAVAILABLE";
  const target = Math.round((state.assist_ratio + delta) * 10) / 10;
  if (target > 1.0) return "ASSIST AT MAXIMUM";
  if (target < 0.3) return "ASSIST AT MINIMUM";
  return null;
}
