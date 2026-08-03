import { useMemo } from "react";

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
  requestId: null;
  intent: null;
  safetyDecision: null;
  acknowledgementMs: null;
}

const STAGES: Array<Pick<AgentStageView, "id" | "label">> = [
  { id: "intent", label: "User Intent" },
  { id: "parsing", label: "LLM Intent Parsing" },
  { id: "safety", label: "Safety Validation" },
  { id: "ros2", label: "ROS2 Service" },
  { id: "controller", label: "Controller" },
];

export function useAgentEvents(): AgentEventsView {
  return useMemo(
    () => ({
      supported: false,
      stages: STAGES.map((stage) => ({
        ...stage,
        status: "unavailable" as const,
        detail: "DATA UNAVAILABLE",
        durationMs: null,
      })),
      requestId: null,
      intent: null,
      safetyDecision: null,
      acknowledgementMs: null,
    }),
    [],
  );
}
