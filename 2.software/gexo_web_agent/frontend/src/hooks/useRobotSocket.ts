import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import {
  parseImuHealthResponse,
  parseImuTelemetryEnvelope,
  type ImuHealthResponse,
  type ImuSocketView,
  type ImuTelemetryEnvelope,
} from "../types/robot";

const CLIENT_STALE_AFTER_MS = 1_000;
const MAX_RETRY_MS = 15_000;

export function useRobotSocket(): ImuSocketView {
  const [snapshot, setSnapshot] = useState<ImuTelemetryEnvelope | null>(null);
  const [socketState, setSocketState] = useState<"connecting" | "open" | "closed">("connecting");
  const [apiReachable, setApiReachable] = useState(false);
  const [health, setHealth] = useState<ImuHealthResponse | null>(null);
  const [roundTripMs, setRoundTripMs] = useState<number | null>(null);
  const [clock, setClock] = useState(() => Date.now());
  const mountedRef = useRef(true);

  const probeHealth = useCallback(async () => {
    const started = performance.now();
    try {
      const response = await fetch("/health", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      const parsed = parseImuHealthResponse(await response.json());
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
      const response = await fetch("/api/telemetry", { cache: "no-store" });
      if (!response.ok) throw new Error(String(response.status));
      const parsed = parseImuTelemetryEnvelope(await response.json());
      if (!parsed) throw new Error("invalid telemetry response");
      if (!mountedRef.current) return;
      setSnapshot(parsed);
      setApiReachable(true);
      setClock(Date.now());
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
          const parsed = parseImuTelemetryEnvelope(JSON.parse(String(event.data)));
          if (!parsed || stopped) return;
          setSnapshot(parsed);
          setApiReachable(true);
          setClock(Date.now());
        } catch {
          // Preserve the last valid snapshot.
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
    const timer = window.setInterval(() => setClock(Date.now()), 250);
    return () => {
      stopped = true;
      mountedRef.current = false;
      window.clearInterval(timer);
      if (retryTimer !== undefined) window.clearTimeout(retryTimer);
      socket?.close();
    };
  }, [probeHealth, refresh]);

  const ageMs = snapshot ? Math.max(0, clock - snapshot.generated_at_ms) : null;
  const connection = useMemo(() => {
    if (socketState === "closed") return "offline" as const;
    if (socketState === "connecting") return snapshot ? "stale" as const : "connecting" as const;
    if (!snapshot || (ageMs !== null && ageMs > CLIENT_STALE_AFTER_MS)) return "stale" as const;
    return "online" as const;
  }, [ageMs, snapshot, socketState]);

  return { snapshot, connection, ageMs, apiReachable, health, roundTripMs, refresh };
}
