import { useMemo } from "react";

import type { CommandActivity, CommandView } from "../types/command";
import type { StageId } from "../types/ui";

export type AgentStageId = "intent" | "parsing" | "safety" | "ros2" | "controller";
export type AgentStageStatus =
  | "idle"
  | "active"
  | "passed"
  | "awaiting_confirmation"
  | "rejected"
  | "failed"
  | "unavailable";

export interface AgentStageView {
  id: AgentStageId;
  label: string;
  status: AgentStageStatus;
  detail: string;
  durationMs: number | null;
}

export interface AgentEventsView {
  supported: false;
  stages: AgentStageView[];
  requestId: string | null;
  intent: string | null;
  safetyDecision: string | null;
  acknowledgementMs: number | null;
  activeLoopStage: StageId | null;
  eventKey: string | null;
}

const LABELS: Record<AgentStageId, string> = {
  intent: "User Intent",
  parsing: "LLM Intent Parsing",
  safety: "Safety Validation",
  ros2: "ROS2 Service",
  controller: "Controller",
};

function stage(
  id: AgentStageId,
  status: AgentStageStatus,
  detail: string,
  durationMs: number | null = null,
): AgentStageView {
  return { id, label: LABELS[id], status, detail, durationMs };
}

function commandDuration(command: CommandView | null): number | null {
  if (!command?.finished_ms || !command.created_ms) return null;
  return Math.max(0, command.finished_ms - command.created_ms);
}

function safetyStage(command: CommandView | null): AgentStageView {
  if (!command) return stage("safety", "unavailable", "DATA UNAVAILABLE");
  if (command.status === "pending_confirmation") {
    return stage("safety", "awaiting_confirmation", "CONFIRMATION REQUIRED");
  }
  if (command.status === "rejected") {
    return stage(
      "safety",
      "rejected",
      command.message || command.error_code || "REJECTED",
    );
  }
  if (command.status === "cancelled") {
    return stage("safety", "idle", "CANCELLED BEFORE SEND");
  }
  if (command.status === "expired") {
    return stage("safety", "failed", command.message || "CONFIRMATION EXPIRED");
  }
  return stage("safety", "passed", "SAFETYGUARD PASSED");
}

function rosStage(command: CommandView | null): AgentStageView {
  if (!command) return stage("ros2", "unavailable", "DATA UNAVAILABLE");
  if (["success", "failed", "timeout", "sent"].includes(command.status)) {
    return stage("ros2", "passed", `REQUEST ${command.request_id} SENT`);
  }
  return stage("ros2", "idle", "NOT SENT");
}

function controllerStage(command: CommandView | null): AgentStageView {
  if (!command) return stage("controller", "unavailable", "DATA UNAVAILABLE");
  const duration = commandDuration(command);
  if (command.status === "success") {
    return stage("controller", "passed", command.message || "ACKNOWLEDGED", duration);
  }
  if (command.status === "sent") {
    return stage("controller", "active", "WAITING FOR ACKNOWLEDGEMENT");
  }
  if (command.status === "failed" || command.status === "timeout") {
    return stage(
      "controller",
      "failed",
      command.message || command.error_code || command.status.toUpperCase(),
      duration,
    );
  }
  return stage("controller", "idle", "NO CONTROLLER REQUEST");
}

function emptyView(): AgentEventsView {
  return {
    supported: false,
    stages: (Object.keys(LABELS) as AgentStageId[]).map((id) =>
      stage(id, "unavailable", "DATA UNAVAILABLE"),
    ),
    requestId: null,
    intent: null,
    safetyDecision: null,
    acknowledgementMs: null,
    activeLoopStage: null,
    eventKey: null,
  };
}

export function useAgentEvents(activity: CommandActivity | null): AgentEventsView {
  return useMemo(() => {
    if (!activity) return emptyView();

    const isSubmitting = activity.phase === "submitting";
    const intentStage = stage(
      "intent",
      isSubmitting ? "active" : ["network_error", "request_error"].includes(activity.phase) ? "failed" : "passed",
      activity.source === "button"
        ? `BUTTON / ${activity.action ?? "DATA UNAVAILABLE"}`
        : "USER COMMAND RECEIVED",
    );
    const parsingStage = activity.source === "button"
      ? stage("parsing", "idle", "NOT USED / DIRECT CONTROL")
      : activity.phase === "network_error" || activity.phase === "request_error"
        ? stage("parsing", "failed", activity.error ?? "BACKEND UNREACHABLE")
        : activity.intent
          ? stage("parsing", "passed", `INTENT / ${activity.intent} · SOURCE UNAVAILABLE`)
          : stage("parsing", "unavailable", "EVENT API UNAVAILABLE");

    const command = activity.command;
    const readOnly = activity.source === "chat" && activity.phase === "complete" && !command;
    const confirmationInFlight = activity.phase === "awaiting_controller" &&
      command?.status === "pending_confirmation";
    const safety = confirmationInFlight
      ? stage("safety", "active", "VALIDATING CONFIRMED REQUEST")
      : readOnly
      ? stage("safety", "idle", "NOT APPLICABLE / READ-ONLY")
      : safetyStage(command);
    const ros2 = confirmationInFlight
      ? stage("ros2", "unavailable", "BACKEND RESULT PENDING")
      : readOnly
      ? stage("ros2", "idle", "NOT APPLICABLE / READ-ONLY")
      : rosStage(command);
    const controller = confirmationInFlight
      ? stage("controller", "unavailable", "BACKEND RESULT PENDING")
      : readOnly
      ? stage("controller", "idle", "NO CONTROLLER REQUEST")
      : controllerStage(command);

    const controllerBound = Boolean(
      command && ["sent", "success", "failed", "timeout"].includes(command.status),
    );
    const activeLoopStage: StageId = controllerBound ? "act" : "reason";
    const duration = commandDuration(command);

    return {
      supported: false,
      stages: [intentStage, parsingStage, safety, ros2, controller],
      requestId: command?.request_id ?? null,
      intent: activity.intent,
      safetyDecision: command
        ? command.status === "rejected"
          ? command.error_code || "REJECTED"
          : command.status === "pending_confirmation"
            ? "CONFIRMATION REQUIRED"
            : ["success", "failed", "timeout", "sent"].includes(command.status)
              ? "PASSED"
              : command.status.toUpperCase()
        : null,
      acknowledgementMs: duration,
      activeLoopStage,
      eventKey: `${activity.startedMs}-${activity.phase}-${command?.request_id ?? "none"}-${command?.status ?? "none"}`,
    };
  }, [activity]);
}
