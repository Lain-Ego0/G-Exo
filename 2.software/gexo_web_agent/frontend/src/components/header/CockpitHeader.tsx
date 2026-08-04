import {
  Activity,
  AlertTriangle,
  Cable,
  CircleStop,
  Clock3,
  Cpu,
  RadioTower,
  type LucideIcon,
} from "lucide-react";

import { formatAge, missingLabel } from "../../lib/format";
import type { RobotSocketView } from "../../types/robot";

type RailState = "healthy" | "warning" | "critical" | "unavailable";

function RailItem({
  icon: Icon,
  label,
  state,
  value,
}: {
  icon: LucideIcon;
  label: string;
  state: RailState;
  value: string;
}) {
  return (
    <div className="rail-item" data-state={state}>
      <Icon aria-hidden="true" size={14} strokeWidth={1.8} />
      <span className="rail-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function CockpitHeader({ robot }: { robot: RobotSocketView }) {
  const state = robot.snapshot?.state ?? null;
  const unavailable = missingLabel(Boolean(state));
  const faultActive = Boolean(state?.fault_code);
  const eStopActive = state?.emergency_stop === true;
  const mode = state?.mode === "assist"
    ? "ASSIST"
    : state?.mode === "damping"
      ? "DAMPING"
      : unavailable;
  const motion = state?.is_stationary === true
    ? "STATIONARY"
    : state?.is_stationary === false
      ? "MOVING"
      : unavailable;
  const emergencyStop = state?.emergency_stop === true
    ? "ACTIVE"
    : state?.emergency_stop === false
      ? "SAFE"
      : unavailable;
  const fault = state?.fault_code
    ? state.fault_code
    : state?.fault_code === ""
      ? "NONE"
      : unavailable;
  const can = state?.can_online === true
    ? "ONLINE"
    : state?.can_online === false
      ? "OFFLINE"
      : unavailable;
  const transport = robot.health?.transport?.toUpperCase() ?? "DATA UNAVAILABLE";
  const latency = robot.roundTripMs === null ? "--" : `${robot.roundTripMs} ms`;

  const alert = eStopActive
    ? { title: "E-STOP ACTIVE", detail: "All write controls are blocked." }
    : faultActive
      ? {
          title: `FAULT ${state?.fault_code}`,
          detail: state?.fault_message || "Controller fault is active. All write controls are blocked.",
        }
      : null;

  return (
    <header className="cockpit-header" data-alert={alert ? "critical" : undefined}>
      <div className="identity-block" aria-label="G-Exo Physical AI Cockpit">
        <span className="wordmark">G-EXO</span>
        <span className="product-label">物理智能座舱 / PHYSICAL AI COCKPIT</span>
      </div>

      <div className="robot-safety-rail" aria-label="Robot safety status">
        <RailItem
          icon={Activity}
          label="模式 MODE"
          state={state?.mode ? "healthy" : "unavailable"}
          value={mode}
        />
        <RailItem
          icon={RadioTower}
          label="运动 MOTION"
          state={state?.is_stationary === false ? "warning" : state ? "healthy" : "unavailable"}
          value={motion}
        />
        <RailItem
          icon={CircleStop}
          label="急停 E-STOP"
          state={eStopActive ? "critical" : state ? "healthy" : "unavailable"}
          value={emergencyStop}
        />
        <RailItem
          icon={AlertTriangle}
          label="故障 FAULT"
          state={faultActive ? "critical" : state ? "healthy" : "unavailable"}
          value={fault}
        />
        <RailItem
          icon={Cable}
          label="CAN"
          state={state?.can_online === false ? "critical" : state ? "healthy" : "unavailable"}
          value={can}
        />
        <RailItem
          icon={Clock3}
          label="状态时效 STATE AGE"
          state={robot.connection === "online" ? "healthy" : robot.snapshot ? "warning" : "unavailable"}
          value={formatAge(robot.ageMs)}
        />
      </div>

      <div className="connection-block" data-state={robot.apiReachable ? "online" : "offline"}>
        <Cpu aria-hidden="true" size={18} strokeWidth={1.8} />
        <div>
          <strong>{robot.apiReachable ? "K3 已连接 CONNECTED" : "K3 未连接 NOT CONNECTED"}</strong>
          <span>{transport} / {latency}</span>
        </div>
      </div>

      {alert ? (
        <div className="safety-alert-band" role="alert">
          <AlertTriangle aria-hidden="true" size={17} />
          <strong>{alert.title}</strong>
          <span>{alert.detail}</span>
        </div>
      ) : null}
    </header>
  );
}
