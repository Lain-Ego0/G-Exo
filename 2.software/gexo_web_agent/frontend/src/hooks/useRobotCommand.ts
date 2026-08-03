import { useCallback, useRef, useState } from "react";

import { ApiError, postAction, postChat, postConfirmation } from "../lib/api";
import type {
  ChatMessage,
  CommandAction,
  CommandActivity,
  CommandView,
} from "../types/command";

const TERMINAL_STATUSES = new Set([
  "success",
  "failed",
  "timeout",
  "rejected",
  "expired",
  "cancelled",
]);

export interface RobotCommandView {
  activity: CommandActivity | null;
  busy: boolean;
  lastCommand: CommandView | null;
  messages: ChatMessage[];
  executeAction: (
    action: CommandAction,
    params: Record<string, unknown>,
  ) => Promise<CommandView | null>;
  confirmPending: (approve: boolean) => Promise<CommandView | null>;
  sendChat: (text: string) => Promise<void>;
}

function messageId(role: ChatMessage["role"]): string {
  return `${role}-${Date.now()}-${Math.random().toString(16).slice(2)}`;
}

function phaseFor(command: CommandView): CommandActivity["phase"] {
  if (command.status === "pending_confirmation") return "awaiting_confirmation";
  if (command.status === "sent") return "awaiting_controller";
  return "complete";
}

function errorPhase(error: unknown): CommandActivity["phase"] {
  return error instanceof ApiError && error.status !== null ? "request_error" : "network_error";
}

export function useRobotCommand(refreshState: () => Promise<void>): RobotCommandView {
  const [activity, setActivity] = useState<CommandActivity | null>(null);
  const [lastCommand, setLastCommand] = useState<CommandView | null>(null);
  const [messages, setMessages] = useState<ChatMessage[]>([]);
  const [busy, setBusy] = useState(false);
  const busyRef = useRef(false);

  const begin = useCallback((source: CommandActivity["source"], action: string | null) => {
    const startedMs = Date.now();
    setActivity({
      source,
      phase: "submitting",
      action,
      intent: null,
      command: null,
      startedMs,
      finishedMs: null,
      error: null,
    });
    return startedMs;
  }, []);

  const executeAction = useCallback(async (
    action: CommandAction,
    params: Record<string, unknown>,
  ): Promise<CommandView | null> => {
    if (busyRef.current) return null;
    busyRef.current = true;
    setBusy(true);
    const startedMs = begin("button", action);
    try {
      const command = await postAction(action, params);
      setLastCommand(command);
      setActivity({
        source: "button",
        phase: phaseFor(command),
        action,
        intent: action,
        command,
        startedMs,
        finishedMs: TERMINAL_STATUSES.has(command.status) ? Date.now() : null,
        error: null,
      });
      if (TERMINAL_STATUSES.has(command.status)) void refreshState();
      return command;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Backend request failed";
      setActivity({
        source: "button",
        phase: errorPhase(error),
        action,
        intent: action,
        command: null,
        startedMs,
        finishedMs: Date.now(),
        error: message,
      });
      return null;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [begin, refreshState]);

  const confirmPending = useCallback(async (approve: boolean): Promise<CommandView | null> => {
    if (busyRef.current || lastCommand?.status !== "pending_confirmation") return null;
    busyRef.current = true;
    setBusy(true);
    const previous = activity;
    setActivity((current) => current ? {
      ...current,
      phase: approve ? "awaiting_controller" : "submitting",
      error: null,
    } : current);
    try {
      const command = await postConfirmation(lastCommand.request_id, approve);
      setLastCommand(command);
      setActivity({
        source: previous?.source ?? "button",
        phase: phaseFor(command),
        action: command.action,
        intent: previous?.intent ?? command.action,
        command,
        startedMs: previous?.startedMs ?? command.created_ms,
        finishedMs: TERMINAL_STATUSES.has(command.status) ? Date.now() : null,
        error: null,
      });
      void refreshState();
      return command;
    } catch (error) {
      const message = error instanceof Error ? error.message : "Confirmation failed";
      setActivity((current) => current ? {
        ...current,
        phase: errorPhase(error),
        finishedMs: Date.now(),
        error: message,
      } : current);
      return null;
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [activity, lastCommand, refreshState]);

  const sendChat = useCallback(async (text: string): Promise<void> => {
    const trimmed = text.trim();
    if (!trimmed || busyRef.current) return;
    busyRef.current = true;
    setBusy(true);
    const startedMs = begin("chat", null);
    setMessages((current) => [...current, {
      id: messageId("user"),
      role: "user",
      text: trimmed,
      sources: [],
      timestamp: startedMs,
    }]);
    try {
      const response = await postChat(trimmed);
      setMessages((current) => [...current, {
        id: messageId("agent"),
        role: "agent",
        text: response.reply,
        sources: response.sources,
        timestamp: Date.now(),
      }]);
      if (response.command) setLastCommand(response.command);
      setActivity({
        source: "chat",
        phase: response.command ? phaseFor(response.command) : "complete",
        action: response.command?.action ?? null,
        intent: response.intent,
        command: response.command,
        startedMs,
        finishedMs: response.command?.status === "pending_confirmation" ? null : Date.now(),
        error: null,
      });
      if (response.command && TERMINAL_STATUSES.has(response.command.status)) {
        void refreshState();
      }
    } catch (error) {
      const message = error instanceof Error ? error.message : "Agent request failed";
      setMessages((current) => [...current, {
        id: messageId("agent"),
        role: "agent",
        text: message,
        sources: [],
        timestamp: Date.now(),
      }]);
      setActivity({
        source: "chat",
        phase: errorPhase(error),
        action: null,
        intent: null,
        command: null,
        startedMs,
        finishedMs: Date.now(),
        error: message,
      });
    } finally {
      busyRef.current = false;
      setBusy(false);
    }
  }, [begin, refreshState]);

  return {
    activity,
    busy,
    lastCommand,
    messages,
    executeAction,
    confirmPending,
    sendChat,
  };
}
