import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  parseHealthResponse,
  parseStateEnvelope,
  type HealthResponse,
  type RobotSocketView,
  type StateEnvelope,
} from "../types/robot";

const CLIENT_STALE_AFTER_MS = 1_500;
const MAX_RETRY_MS = 15_000;

export function useRobotSocket(): RobotSocketView {
  const [snapshot, setSnapshot] = useState<StateEnvelope | null>(null);
  const [socketState, setSocketState] = useState<"connecting" | "open" | "closed">(
    "connecting",
  );
  const [apiReachable, setApiReachable] = useState(false);
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [roundTripMs, setRoundTripMs] = useState<number | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const mountedRef = useRef(true);

  const probeHealth = useCallback(async () => {
    const started = performance.now();
    try {
      const response = await fetch("/health", { cache: "no-store" });
      if (!response.ok) throw new Error(`health returned ${response.status}`);
      const parsed = parseHealthResponse(await response.json());
      if (!parsed) throw new Error("invalid health response");
      if (!mountedRef.current) return;
      setHealth(parsed);
      setRoundTripMs(Math.max(0, Math.round(performance.now() - started)));
      setApiReachable(true);
    } catch {
      if (!mountedRef.current) return;
      setHealth(null);
      setRoundTripMs(null);
      setApiReachable(false);
    }
  }, []);

  const refresh = useCallback(async () => {
    await probeHealth();
    try {
      const response = await fetch("/api/state", { cache: "no-store" });
      if (!response.ok) throw new Error(`state returned ${response.status}`);
      const parsed = parseStateEnvelope(await response.json());
      if (!parsed) throw new Error("invalid state response");
      if (!mountedRef.current) return;
      setSnapshot(parsed);
      setApiReachable(true);
    } catch {
      if (mountedRef.current) setApiReachable(false);
    }
  }, [probeHealth]);

  useEffect(() => {
    mountedRef.current = true;
    let socket: WebSocket | null = null;
    let retryTimer: number | undefined;
    let retryMs = 1_000;
    let stopped = false;

    const connect = () => {
      if (stopped) return;
      setSocketState("connecting");
      const protocol = window.location.protocol === "https:" ? "wss" : "ws";
      socket = new WebSocket(`${protocol}://${window.location.host}/ws`);

      socket.onopen = () => {
        if (stopped) return;
        retryMs = 1_000;
        setSocketState("open");
        setApiReachable(true);
        void probeHealth();
      };

      socket.onmessage = (event) => {
        try {
          const parsed = parseStateEnvelope(JSON.parse(String(event.data)));
          if (!parsed || stopped) return;
          setSnapshot(parsed);
          setApiReachable(true);
          setClock(Date.now());
        } catch {
          // Ignore malformed frames; the last validated snapshot remains visible.
        }
      };

      socket.onerror = () => socket?.close();
      socket.onclose = () => {
        if (stopped) return;
        setSocketState("closed");
        void probeHealth();
        retryTimer = window.setTimeout(connect, retryMs);
        retryMs = Math.min(retryMs * 2, MAX_RETRY_MS);
      };
    };

    void refresh();
    connect();
    const clockTimer = window.setInterval(() => setClock(Date.now()), 500);

    return () => {
      stopped = true;
      mountedRef.current = false;
      window.clearInterval(clockTimer);
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [probeHealth, refresh]);

  const ageMs = snapshot?.last_update_ms
    ? Math.max(0, clock - snapshot.last_update_ms)
    : null;
  const staleByClock = ageMs !== null && ageMs > CLIENT_STALE_AFTER_MS;

  const connection = useMemo(() => {
    if (socketState === "closed") return "offline" as const;
    if (socketState === "connecting") {
      return snapshot?.state ? "stale" as const : "connecting" as const;
    }
    if (!snapshot?.state) return "connecting" as const;
    if (snapshot.stale || staleByClock || !snapshot.online) return "stale" as const;
    return "online" as const;
  }, [snapshot, socketState, staleByClock]);

  return {
    snapshot,
    connection,
    ageMs,
    apiReachable,
    health,
    roundTripMs,
    refresh,
  };
}
