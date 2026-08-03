import { useCallback, useEffect, useRef, useState } from "react";

import { arrayValue, isFiniteNumber } from "../lib/format";
import type { ConnectionState, StateEnvelope } from "../types/robot";

const BUFFER_WINDOW_MS = 60_000;
const MAX_POINTS = 320;

export interface TelemetryPoint {
  timestamp: number;
  gap: boolean;
  jointPosition: Array<number | null>;
  commandTorque: Array<number | null>;
  estimatedTorque: Array<number | null>;
  actualTorque: Array<number | null>;
  motorTemperature: Array<number | null>;
  batteryPercent: number | null;
  busVoltage: number | null;
  busCurrent: number | null;
}

export interface TelemetryBufferView {
  points: TelemetryPoint[];
  paused: boolean;
  setPaused: (paused: boolean) => void;
}

function nullable(value: number | undefined): number | null {
  return isFiniteNumber(value) ? value : null;
}

function fourValues(values: number[] | undefined): Array<number | null> {
  return [0, 1, 2, 3].map((index) => nullable(arrayValue(values, index)));
}

function statePoint(snapshot: StateEnvelope): TelemetryPoint | null {
  if (!snapshot.state || !snapshot.last_update_ms) return null;
  const state = snapshot.state;
  return {
    timestamp: snapshot.last_update_ms,
    gap: false,
    jointPosition: fourValues(state.joint_position),
    commandTorque: fourValues(state.command_torque),
    estimatedTorque: fourValues(state.estimated_torque),
    actualTorque: fourValues(state.actual_torque),
    motorTemperature: fourValues(state.motor_temperature),
    batteryPercent: nullable(state.battery_percent),
    busVoltage: nullable(state.bus_voltage),
    busCurrent: nullable(state.bus_current),
  };
}

function gapPoint(timestamp: number): TelemetryPoint {
  return {
    timestamp,
    gap: true,
    jointPosition: [null, null, null, null],
    commandTorque: [null, null, null, null],
    estimatedTorque: [null, null, null, null],
    actualTorque: [null, null, null, null],
    motorTemperature: [null, null, null, null],
    batteryPercent: null,
    busVoltage: null,
    busCurrent: null,
  };
}

export function useTelemetryBuffer(
  snapshot: StateEnvelope | null,
  connection: ConnectionState,
): TelemetryBufferView {
  const bufferRef = useRef<TelemetryPoint[]>([]);
  const lastTimestampRef = useRef<number | null>(null);
  const gapOpenRef = useRef(false);
  const pausedRef = useRef(false);
  const [points, setPoints] = useState<TelemetryPoint[]>([]);
  const [paused, setPausedState] = useState(false);

  const publish = useCallback(() => {
    if (!pausedRef.current) setPoints([...bufferRef.current]);
  }, []);

  const append = useCallback(
    (point: TelemetryPoint) => {
      const cutoff = point.timestamp - BUFFER_WINDOW_MS;
      bufferRef.current = [...bufferRef.current, point]
        .filter((candidate) => candidate.timestamp >= cutoff)
        .slice(-MAX_POINTS);
      publish();
    },
    [publish],
  );

  useEffect(() => {
    if (!snapshot) return;
    const point = statePoint(snapshot);
    if (!point || point.timestamp === lastTimestampRef.current) return;
    if (lastTimestampRef.current !== null && point.timestamp < lastTimestampRef.current) return;
    lastTimestampRef.current = point.timestamp;
    gapOpenRef.current = false;
    append(point);
  }, [append, snapshot]);

  useEffect(() => {
    if (connection === "online") {
      gapOpenRef.current = false;
      return;
    }
    if (bufferRef.current.length === 0 || gapOpenRef.current) return;
    gapOpenRef.current = true;
    append(gapPoint(Date.now()));
  }, [append, connection]);

  const setPaused = useCallback((nextPaused: boolean) => {
    pausedRef.current = nextPaused;
    setPausedState(nextPaused);
    if (!nextPaused) setPoints([...bufferRef.current]);
  }, []);

  return { points, paused, setPaused };
}
