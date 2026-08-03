export type CommandStatus =
  | "pending_confirmation"
  | "sent"
  | "success"
  | "failed"
  | "timeout"
  | "rejected"
  | "expired"
  | "cancelled";

export type CommandAction = "set_mode" | "adjust_assist";

export interface CommandView {
  request_id: string;
  status: CommandStatus;
  action: string;
  params: Record<string, unknown>;
  error_code: string;
  message: string;
  result: Record<string, unknown>;
  created_ms: number;
  finished_ms: number | null;
}

export interface ChatSource {
  file: string;
  section?: string;
  [key: string]: unknown;
}

export interface ChatResponse {
  reply: string;
  intent: string;
  command: CommandView | null;
  sources: ChatSource[];
  need_confirmation: boolean;
  need_clarification: boolean;
}

export interface ChatMessage {
  id: string;
  role: "user" | "agent";
  text: string;
  sources: ChatSource[];
  timestamp: number;
}

export type ActivitySource = "button" | "chat";
export type ActivityPhase =
  | "submitting"
  | "awaiting_confirmation"
  | "awaiting_controller"
  | "complete"
  | "network_error";

export interface CommandActivity {
  source: ActivitySource;
  phase: ActivityPhase;
  action: string | null;
  intent: string | null;
  command: CommandView | null;
  startedMs: number;
  finishedMs: number | null;
  error: string | null;
}

const COMMAND_STATUSES = new Set<CommandStatus>([
  "pending_confirmation",
  "sent",
  "success",
  "failed",
  "timeout",
  "rejected",
  "expired",
  "cancelled",
]);

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | null {
  return typeof value === "number" && Number.isFinite(value) ? value : null;
}

export function parseCommandView(value: unknown): CommandView | null {
  if (!isRecord(value)) return null;
  if (
    typeof value.request_id !== "string" ||
    typeof value.status !== "string" ||
    !COMMAND_STATUSES.has(value.status as CommandStatus) ||
    typeof value.action !== "string"
  ) {
    return null;
  }

  return {
    request_id: value.request_id,
    status: value.status as CommandStatus,
    action: value.action,
    params: isRecord(value.params) ? value.params : {},
    error_code: typeof value.error_code === "string" ? value.error_code : "",
    message: typeof value.message === "string" ? value.message : "",
    result: isRecord(value.result) ? value.result : {},
    created_ms: finiteNumber(value.created_ms) ?? 0,
    finished_ms: finiteNumber(value.finished_ms),
  };
}

export function parseChatResponse(value: unknown): ChatResponse | null {
  if (!isRecord(value) || typeof value.reply !== "string") return null;
  const sources = Array.isArray(value.sources)
    ? value.sources.flatMap((source): ChatSource[] => {
        if (!isRecord(source) || typeof source.file !== "string") return [];
        return [{
          ...source,
          file: source.file,
          section: typeof source.section === "string" ? source.section : undefined,
        }];
      })
    : [];

  return {
    reply: value.reply,
    intent: typeof value.intent === "string" ? value.intent : "unavailable",
    command: value.command === null || value.command === undefined
      ? null
      : parseCommandView(value.command),
    sources,
    need_confirmation: value.need_confirmation === true,
    need_clarification: value.need_clarification === true,
  };
}
