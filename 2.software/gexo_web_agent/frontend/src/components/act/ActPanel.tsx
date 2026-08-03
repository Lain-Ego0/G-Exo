import {
  Gauge,
  Minus,
  Plus,
  Radio,
  ShieldAlert,
  SlidersHorizontal,
  WifiOff,
  Zap,
} from "lucide-react";

import type { RobotCommandView } from "../../hooks/useRobotCommand";
import {
  arrayValue,
  formatAge,
  formatMeasurement,
  isFiniteNumber,
  missingLabel,
} from "../../lib/format";
import { assistWriteBlocker, modeWriteBlocker } from "../../lib/safety";
import type { RobotSocketView, RobotState } from "../../types/robot";
import { JOINTS } from "../../types/ui";

function torqueScale(state: RobotState | null, useActual: boolean): number {
  const observed = useActual ? state?.actual_torque : state?.estimated_torque;
  const values = [...(state?.command_torque ?? []), ...(observed ?? [])].filter(isFiniteNumber);
  return Math.max(1, ...values.map((value) => Math.abs(value)));
}

function TorqueBar({
  color,
  max,
  value,
}: {
  color: string;
  max: number;
  value: number | undefined;
}) {
  if (!isFiniteNumber(value)) return null;
  const width = Math.min(50, (Math.abs(value) / max) * 50);
  return (
    <span
      className="torque-bar"
      style={{
        backgroundColor: color,
        left: value < 0 ? `${50 - width}%` : "50%",
        width: `${width}%`,
      }}
    />
  );
}

function JointTorqueMatrix({ state }: { state: RobotState | null }) {
  const hasActual = state?.actual_torque?.some(isFiniteNumber) === true;
  const observedValues = hasActual ? state?.actual_torque : state?.estimated_torque;
  const observedLabel = hasActual ? "ACTUAL TORQUE" : "ESTIMATED TORQUE";
  const observedShort = hasActual ? "ACT" : "EST";
  const scale = torqueScale(state, hasActual);
  const fallback = missingLabel(Boolean(state));

  return (
    <section className="module-section torque-section" aria-labelledby="torque-title">
      <div className="section-heading">
        <div>
          <span className="section-index">A.03</span>
          <h3 id="torque-title">Four-joint torque</h3>
        </div>
        <span className="est-badge">{observedShort}</span>
      </div>
      <div className="torque-legend">
        <span><i data-series="command" />COMMAND TORQUE</span>
        <span><i data-series="estimated" />{observedLabel}</span>
        <span className="torque-scale-label">SHARED SCALE ±{scale.toFixed(1)} Nm</span>
      </div>
      <div className="torque-matrix">
        {JOINTS.map((joint, index) => {
          const command = arrayValue(state?.command_torque, index);
          const observed = arrayValue(observedValues, index);
          const delta = isFiniteNumber(command) && isFiniteNumber(observed)
            ? observed - command
            : undefined;
          return (
            <div className="torque-row" key={joint.id}>
              <div className="torque-joint"><strong>{joint.short}</strong><span>{joint.name}</span></div>
              <div className="torque-values">
                <span><small>CMD</small><strong>{formatMeasurement(command, 1, "Nm", fallback)}</strong></span>
                <span><small>{observedShort}</small><strong>{formatMeasurement(observed, 1, "Nm", fallback)}</strong></span>
                <span><small>{hasActual ? "DELTA" : "EST Δ"}</small><strong>{formatMeasurement(delta, 1, "Nm", fallback)}</strong></span>
              </div>
              <div className="torque-track" aria-label={`${joint.name} torque comparison`}>
                <span className="torque-zero" />
                <TorqueBar color="var(--gexo-act)" max={scale} value={command} />
                <TorqueBar color="var(--gexo-reason)" max={scale} value={observed} />
              </div>
            </div>
          );
        })}
      </div>
      {!hasActual ? (
        <div className="integrity-notice">
          <ShieldAlert aria-hidden="true" size={16} />
          <div><strong>Estimated Torque (EST)</strong><span>Backend field unavailable: actual_torque</span></div>
        </div>
      ) : null}
    </section>
  );
}

function connectionLabel(robot: RobotSocketView): string {
  if (robot.connection === "online") return "LIVE";
  if (robot.connection === "stale") return `STALE ${formatAge(robot.ageMs)}`;
  if (robot.connection === "connecting") return "WAITING";
  return robot.snapshot?.state ? "DISCONNECTED" : "NOT CONNECTED";
}

function CommandResult({ commands }: { commands: RobotCommandView }) {
  const command = commands.lastCommand;
  const activity = commands.activity;
  if (activity?.phase === "network_error" || activity?.phase === "request_error") {
    return (
      <div className="command-result-view" data-state="failed" role="status">
        <span className="status-dot" />
        <div>
          <strong>{activity.phase === "network_error" ? "NETWORK ERROR" : "REQUEST ERROR"}</strong>
          <span>{activity.error ?? "Backend request failed"}</span>
        </div>
      </div>
    );
  }
  if (commands.busy) {
    return (
      <div className="command-result-view" data-state="pending" role="status">
        <span className="status-dot" />
        <div><strong>COMMAND PENDING</strong><span>Waiting for backend result</span></div>
      </div>
    );
  }
  if (!command) {
    return (
      <div className="command-result-view" data-state="unavailable">
        <span className="status-dot" />
        <div><strong>DATA UNAVAILABLE</strong><span>No command result</span></div>
      </div>
    );
  }
  const duration = command.finished_ms && command.created_ms
    ? Math.max(0, command.finished_ms - command.created_ms)
    : null;
  return (
    <div className="command-result-view" data-state={command.status} role="status">
      <span className="status-dot" />
      <div>
        <strong>{command.status.replaceAll("_", " ").toUpperCase()}</strong>
        <span>{command.message || command.error_code || command.action}</span>
        <small>{command.request_id}{duration === null ? "" : ` / ${duration} ms`}</small>
      </div>
    </div>
  );
}

export function ActPanel({
  active,
  commands,
  robot,
}: {
  active: boolean;
  commands: RobotCommandView;
  robot: RobotSocketView;
}) {
  const state = robot.snapshot?.state ?? null;
  const fallback = missingLabel(Boolean(state));
  const assistPercent = isFiniteNumber(state?.assist_ratio)
    ? Math.round(state.assist_ratio * 100)
    : null;
  const assistModeBlocker = modeWriteBlocker(robot, "assist");
  const dampingModeBlocker = modeWriteBlocker(robot, "damping");
  const decreaseBlocker = assistWriteBlocker(robot, -0.1);
  const increaseBlocker = assistWriteBlocker(robot, 0.1);

  return (
    <article className="stage-panel act-panel" data-stage="act" data-mobile-active={active}>
      <header className="stage-panel-header">
        <div>
          <span className="stage-kicker">03 / ACTUATOR OUTPUT</span>
          <h2>ACT</h2>
        </div>
        <span className="stage-state" data-state={robot.connection}>
          {robot.connection === "online" ? <Radio aria-hidden="true" size={14} /> : <WifiOff aria-hidden="true" size={14} />}
          {connectionLabel(robot)}
        </span>
      </header>

      <section className="module-section mode-section" aria-labelledby="mode-title">
        <div className="section-heading">
          <div>
            <span className="section-index">A.01</span>
            <h3 id="mode-title">Operating mode</h3>
          </div>
          <SlidersHorizontal aria-hidden="true" size={16} />
        </div>
        <div className="mode-segment" aria-label="Operating mode">
          <button
            aria-pressed={state?.mode === "assist"}
            disabled={commands.busy || assistModeBlocker !== null}
            onClick={() => void commands.executeAction("set_mode", { mode: "assist" })}
            title={assistModeBlocker ?? "Switch to Assist mode"}
            type="button"
          ><Zap aria-hidden="true" size={16} />Assist</button>
          <button
            aria-pressed={state?.mode === "damping"}
            disabled={commands.busy || dampingModeBlocker !== null}
            onClick={() => void commands.executeAction("set_mode", { mode: "damping" })}
            title={dampingModeBlocker ?? "Switch to Damping mode"}
            type="button"
          ><Gauge aria-hidden="true" size={16} />Damping</button>
        </div>
        <p className="section-note">
          Current mode / {state?.mode === "assist" ? "ASSIST" : state?.mode === "damping" ? "DAMPING" : fallback}
        </p>
      </section>

      <section className="module-section assist-section" aria-labelledby="assist-title">
        <div className="section-heading">
          <div>
            <span className="section-index">A.02</span>
            <h3 id="assist-title">Global assist ratio</h3>
          </div>
          <span className="section-meta">RANGE 0.3–1.0 / STEP 0.1</span>
        </div>
        <div className="assist-control">
          <button
            aria-label="Decrease assist by 10 percent"
            disabled={commands.busy || decreaseBlocker !== null}
            onClick={() => void commands.executeAction("adjust_assist", { delta: -0.1 })}
            title={decreaseBlocker ?? "Decrease assist"}
            type="button"
          >
            <Minus aria-hidden="true" size={20} />
          </button>
          <div className="assist-value"><strong>{assistPercent ?? "--"}</strong><span>%</span></div>
          <button
            aria-label="Increase assist by 10 percent"
            disabled={commands.busy || increaseBlocker !== null}
            onClick={() => void commands.executeAction("adjust_assist", { delta: 0.1 })}
            title={increaseBlocker ?? "Increase assist"}
            type="button"
          >
            <Plus aria-hidden="true" size={20} />
          </button>
        </div>
        <div className="assist-scale" aria-hidden="true">
          {[0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0].map((step) => (
            <span data-active={isFiniteNumber(state?.assist_ratio) && state.assist_ratio >= step} key={step} />
          ))}
        </div>
        <p className="section-note">All four joints adjust together.</p>
      </section>

      <JointTorqueMatrix state={state} />

      <section className="module-section command-result" aria-labelledby="result-title">
        <div className="section-heading">
          <div>
            <span className="section-index">A.04</span>
            <h3 id="result-title">Command result</h3>
          </div>
        </div>
        <CommandResult commands={commands} />
      </section>
    </article>
  );
}
