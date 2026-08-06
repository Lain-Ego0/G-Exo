import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { parseStateEnvelope, type HealthResponse, type RobotSocketView, type StateEnvelope } from "../types/robot";

const STALE_AFTER_MS = 1_000;

export function useSimulatedControl(): RobotSocketView {
  const [snapshot, setSnapshot] = useState<StateEnvelope | null>(null);
  const [socketState, setSocketState] = useState<"connecting" | "open" | "closed">("connecting");
  const [clock, setClock] = useState(Date.now());
  const mounted = useRef(true);

  const refresh = useCallback(async () => {
    try {
      const response = await fetch("/control/api/state", { cache: "no-store" });
      const parsed = response.ok ? parseStateEnvelope(await response.json()) : null;
      if (mounted.current && parsed) setSnapshot(parsed);
    } catch {
      // The websocket reconnect loop owns the visible connection state.
    }
  }, []);

  useEffect(() => {
    mounted.current = true;
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;
    let stopped = false;
    const connect = () => {
      if (stopped) return;
      setSocketState("connecting");
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${window.location.host}/control/ws`);
      socket.onopen = () => setSocketState("open");
      socket.onmessage = (event) => {
        try {
          const parsed = parseStateEnvelope(JSON.parse(String(event.data)));
          if (parsed && !stopped) {
            setSnapshot(parsed);
            setClock(Date.now());
          }
        } catch { /* keep the last valid simulated state */ }
      };
      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (stopped) return;
        setSocketState("closed");
        retryTimer = window.setTimeout(connect, 1_000);
      };
    };
    void refresh();
    connect();
    const timer = window.setInterval(() => setClock(Date.now()), 250);
    return () => {
      stopped = true;
      mounted.current = false;
      window.clearInterval(timer);
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [refresh]);

  const ageMs = snapshot?.last_update_ms === null || snapshot?.last_update_ms === undefined
    ? null : Math.max(0, clock - snapshot.last_update_ms);
  const connection = useMemo(() => {
    if (socketState === "closed") return "offline" as const;
    if (socketState === "connecting") return snapshot ? "stale" as const : "connecting" as const;
    if (!snapshot || (ageMs !== null && ageMs > STALE_AFTER_MS)) return "stale" as const;
    return "online" as const;
  }, [ageMs, snapshot, socketState]);
  const health: HealthResponse | null = { status: "simulated", transport: "mock", stateOnline: connection === "online" };
  return { snapshot, connection, ageMs, apiReachable: socketState === "open", health, roundTripMs: null, refresh };
}
