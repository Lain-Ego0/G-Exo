import {
  parseChatResponse,
  parseCommandView,
  type ChatResponse,
  type CommandAction,
  type CommandView,
} from "../types/command";

export class ApiError extends Error {
  readonly status: number | null;

  constructor(message: string, status: number | null = null) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

async function timedFetch(
  input: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeoutMs);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") {
      throw new ApiError("Backend request timed out");
    }
    throw new ApiError("Backend is not reachable");
  } finally {
    window.clearTimeout(timer);
  }
}

async function responseBody(response: Response): Promise<unknown> {
  try {
    return await response.json();
  } catch {
    throw new ApiError(`Backend returned an invalid response (${response.status})`, response.status);
  }
}

function detailMessage(value: unknown, fallback: string): string {
  if (typeof value === "object" && value !== null && "detail" in value) {
    const detail = (value as { detail?: unknown }).detail;
    if (typeof detail === "string") return detail;
  }
  return fallback;
}

export async function postAction(
  action: CommandAction,
  params: Record<string, unknown>,
): Promise<CommandView> {
  const response = await timedFetch(
    "/api/action",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ action, params }),
    },
    8_000,
  );
  const body = await responseBody(response);
  const command = parseCommandView(body);
  if (command) return command;
  throw new ApiError(
    detailMessage(body, `Action request failed (${response.status})`),
    response.status,
  );
}

export async function postConfirmation(
  requestId: string,
  approve: boolean,
): Promise<CommandView> {
  const response = await timedFetch(
    "/api/confirm",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ request_id: requestId, approve }),
    },
    8_000,
  );
  const body = await responseBody(response);
  const command = parseCommandView(body);
  if (command) return command;
  throw new ApiError(
    detailMessage(body, `Confirmation request failed (${response.status})`),
    response.status,
  );
}

export async function postChat(text: string): Promise<ChatResponse> {
  const response = await timedFetch(
    "/api/chat",
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    },
    40_000,
  );
  const body = await responseBody(response);
  const chat = parseChatResponse(body);
  if (chat) return chat;
  throw new ApiError(
    detailMessage(body, `Agent request failed (${response.status})`),
    response.status,
  );
}

export interface DebugScenarioView {
  scenario: string;
  available: string[];
}

export async function getDebugScenario(): Promise<DebugScenarioView | null> {
  const response = await fetch("/api/debug/scenario", { cache: "no-store" });
  if (!response.ok) return null;
  const body: unknown = await response.json();
  if (typeof body !== "object" || body === null) return null;
  const record = body as Record<string, unknown>;
  if (typeof record.scenario !== "string" || !Array.isArray(record.available)) return null;
  return {
    scenario: record.scenario,
    available: record.available.filter((item): item is string => typeof item === "string"),
  };
}

export async function setDebugScenario(scenario: string): Promise<void> {
  const response = await fetch("/api/debug/scenario", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ scenario }),
  });
  if (!response.ok) throw new ApiError(`Debug scenario update failed (${response.status})`);
}
