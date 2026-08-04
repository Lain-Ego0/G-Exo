import { useCallback, useEffect, useRef, useState } from "react";

import { quaternionToEuler, type EulerAngles } from "../lib/imu";
import type {
  ConnectionState,
  ImuTelemetryEnvelope,
  JointId,
  QuaternionData,
  Vector3Data,
} from "../types/robot";

const BUFFER_WINDOW_MS = 60_000;
const MAX_POINTS = 1_200;

export interface BufferedImu {
  orientation: QuaternionData | null;
  euler: EulerAngles | null;
  angularVelocity: Vector3Data | null;
  linearAcceleration: Vector3Data | null;
}

export interface TelemetryPoint {
  timestamp: number;
  gap: boolean;
  imus: Partial<Record<JointId, BufferedImu>>;
}

export interface TelemetryBufferView {
  points: TelemetryPoint[];
  paused: boolean;
  setPaused: (paused: boolean) => void;
}

function statePoint(snapshot: ImuTelemetryEnvelope): TelemetryPoint {
  const imus: Partial<Record<JointId, BufferedImu>> = {};
  for (const imu of snapshot.imus) {
    if (imu.status !== "online") continue;
    imus[imu.joint] = {
      orientation: imu.orientation,
      euler: quaternionToEuler(imu.orientation),
      angularVelocity: imu.angular_velocity,
      linearAcceleration: imu.linear_acceleration,
    };
  }
  return { timestamp: snapshot.generated_at_ms, gap: false, imus };
}

export function useTelemetryBuffer(
  snapshot: ImuTelemetryEnvelope | null,
  connection: ConnectionState,
): TelemetryBufferView {
  const bufferRef = useRef<TelemetryPoint[]>([]);
  const lastTimestampRef = useRef<number | null>(null);
  const gapOpenRef = useRef(false);
  const pausedRef = useRef(false);
  const [points, setPoints] = useState<TelemetryPoint[]>([]);
  const [paused, setPausedState] = useState(false);

  const append = useCallback((point: TelemetryPoint) => {
    const cutoff = point.timestamp - BUFFER_WINDOW_MS;
    bufferRef.current = [...bufferRef.current, point]
      .filter((candidate) => candidate.timestamp >= cutoff)
      .slice(-MAX_POINTS);
    if (!pausedRef.current) setPoints([...bufferRef.current]);
  }, []);

  useEffect(() => {
    if (!snapshot || snapshot.generated_at_ms === lastTimestampRef.current) return;
    if (lastTimestampRef.current !== null && snapshot.generated_at_ms < lastTimestampRef.current) return;
    lastTimestampRef.current = snapshot.generated_at_ms;
    gapOpenRef.current = false;
    append(statePoint(snapshot));
  }, [append, snapshot]);

  useEffect(() => {
    if (connection === "online" || bufferRef.current.length === 0 || gapOpenRef.current) return;
    gapOpenRef.current = true;
    append({ timestamp: Date.now(), gap: true, imus: {} });
  }, [append, connection]);

  const setPaused = useCallback((nextPaused: boolean) => {
    pausedRef.current = nextPaused;
    setPausedState(nextPaused);
    if (!nextPaused) setPoints([...bufferRef.current]);
  }, []);

  return { points, paused, setPaused };
}
