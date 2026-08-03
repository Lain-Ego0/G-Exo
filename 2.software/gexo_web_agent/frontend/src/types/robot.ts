export type RobotMode = "assist" | "damping";

export type ConnectionState = "connecting" | "online" | "stale" | "offline";

export interface AloopExtension {
  connected?: boolean;
  capabilities?: string[];
  [key: string]: unknown;
}

export interface RobotExtensions {
  aloop?: AloopExtension;
  [key: string]: unknown;
}

export interface RobotState {
  mode?: RobotMode;
  assist_ratio?: number;
  is_stationary?: boolean;
  joint_position?: number[];
  joint_velocity?: number[];
  command_torque?: number[];
  estimated_torque?: number[];
  actual_torque?: number[];
  motor_temperature?: number[];
  bus_voltage?: number;
  bus_current?: number;
  battery_percent?: number;
  imu_online?: boolean[];
  imu_calibrated?: boolean[];
  can_online?: boolean;
  emergency_stop?: boolean;
  fault_code?: string;
  fault_message?: string;
  extensions?: RobotExtensions;
  [key: string]: unknown;
}

export interface StateEnvelope {
  online: boolean;
  stale: boolean;
  state: RobotState | null;
  last_update_ms: number | null;
}

export interface HealthResponse {
  status: string;
  transport: string | null;
  stateOnline: boolean | null;
}

export interface RobotSocketView {
  snapshot: StateEnvelope | null;
  connection: ConnectionState;
  ageMs: number | null;
  apiReachable: boolean;
  health: HealthResponse | null;
  roundTripMs: number | null;
  refresh: () => Promise<void>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function finiteNumber(value: unknown): number | undefined {
  return typeof value === "number" && Number.isFinite(value) ? value : undefined;
}

function numberArray(value: unknown): number[] | undefined {
  if (!Array.isArray(value) || !value.every((item) => finiteNumber(item) !== undefined)) {
    return undefined;
  }
  return value as number[];
}

function booleanArray(value: unknown): boolean[] | undefined {
  if (!Array.isArray(value) || !value.every((item) => typeof item === "boolean")) {
    return undefined;
  }
  return value as boolean[];
}

function parseExtensions(value: unknown): RobotExtensions | undefined {
  if (!isRecord(value)) return undefined;

  const extensions: RobotExtensions = { ...value };
  if (isRecord(value.aloop)) {
    extensions.aloop = {
      ...value.aloop,
      connected:
        typeof value.aloop.connected === "boolean" ? value.aloop.connected : undefined,
      capabilities: Array.isArray(value.aloop.capabilities)
        ? value.aloop.capabilities.filter(
            (capability): capability is string => typeof capability === "string",
          )
        : undefined,
    };
  }
  return extensions;
}

function parseRobotState(value: unknown): RobotState | null {
  if (!isRecord(value)) return null;

  const state: RobotState = { ...value };
  state.mode = value.mode === "assist" || value.mode === "damping" ? value.mode : undefined;
  state.assist_ratio = finiteNumber(value.assist_ratio);
  state.is_stationary =
    typeof value.is_stationary === "boolean" ? value.is_stationary : undefined;
  state.joint_position = numberArray(value.joint_position);
  state.joint_velocity = numberArray(value.joint_velocity);
  state.command_torque = numberArray(value.command_torque);
  state.estimated_torque = numberArray(value.estimated_torque);
  state.actual_torque = numberArray(value.actual_torque);
  state.motor_temperature = numberArray(value.motor_temperature);
  state.bus_voltage = finiteNumber(value.bus_voltage);
  state.bus_current = finiteNumber(value.bus_current);
  state.battery_percent = finiteNumber(value.battery_percent);
  state.imu_online = booleanArray(value.imu_online);
  state.imu_calibrated = booleanArray(value.imu_calibrated);
  state.can_online = typeof value.can_online === "boolean" ? value.can_online : undefined;
  state.emergency_stop =
    typeof value.emergency_stop === "boolean" ? value.emergency_stop : undefined;
  state.fault_code = typeof value.fault_code === "string" ? value.fault_code : undefined;
  state.fault_message =
    typeof value.fault_message === "string" ? value.fault_message : undefined;
  state.extensions = parseExtensions(value.extensions);
  return state;
}

export function parseStateEnvelope(value: unknown): StateEnvelope | null {
  if (!isRecord(value) || typeof value.online !== "boolean" || typeof value.stale !== "boolean") {
    return null;
  }

  const lastUpdate = finiteNumber(value.last_update_ms);
  return {
    online: value.online,
    stale: value.stale,
    state: value.state === null ? null : parseRobotState(value.state),
    last_update_ms: lastUpdate ?? null,
  };
}

export function parseHealthResponse(value: unknown): HealthResponse | null {
  if (!isRecord(value) || typeof value.status !== "string") return null;
  return {
    status: value.status,
    transport: typeof value.transport === "string" ? value.transport : null,
    stateOnline: typeof value.state_online === "boolean" ? value.state_online : null,
  };
}
