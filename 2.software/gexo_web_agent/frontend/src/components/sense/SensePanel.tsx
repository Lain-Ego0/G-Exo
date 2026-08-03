import {
  BatteryMedium,
  Cable,
  Gauge,
  Radio,
  Thermometer,
  WifiOff,
} from "lucide-react";

import {
  arrayValue,
  formatAge,
  formatMeasurement,
  formatPercent,
  maximum,
  missingLabel,
} from "../../lib/format";
import type { RobotSocketView, RobotState } from "../../types/robot";
import { JOINTS } from "../../types/ui";

function connectionLabel(robot: RobotSocketView): string {
  if (robot.connection === "online") return "LIVE";
  if (robot.connection === "stale") return `STALE ${formatAge(robot.ageMs)}`;
  if (robot.connection === "connecting") return "WAITING";
  return robot.snapshot?.state ? "DISCONNECTED" : "NOT CONNECTED";
}

function JointMap({ state }: { state: RobotState | null }) {
  const fallback = missingLabel(Boolean(state));
  const canOnline = state?.can_online === true;

  return (
    <section className="module-section joint-map-section" aria-labelledby="joint-map-title">
      <div className="section-heading">
        <div>
          <span className="section-index">S.01</span>
          <h3 id="joint-map-title">Four-joint body map</h3>
        </div>
        <span className="section-meta">ANGLE / TEMPERATURE</span>
      </div>
      <div className="joint-map" data-state={canOnline ? "online" : "offline"}>
        <img
          src="/gexo-exoskeleton.png"
          alt="G-Exo lower-limb exoskeleton front view"
        />
        {JOINTS.map((joint, index) => {
          const position = arrayValue(state?.joint_position, index);
          const temperature = arrayValue(state?.motor_temperature, index);
          const status = state ? (canOnline ? "ONLINE" : "CAN OFFLINE") : fallback;
          return (
            <div
              className={`joint-node joint-node-${joint.id}`}
              data-state={canOnline ? "online" : "offline"}
              key={joint.id}
              title={`${joint.name}: ${status}`}
            >
              <span className="joint-node-dot" />
              <strong>{joint.short} / {status}</strong>
              <span>
                {formatMeasurement(position, 2, "rad", "-- rad")} / {formatMeasurement(temperature, 1, "°C", "-- °C")}
              </span>
            </div>
          );
        })}
        <span className="map-offline-label">
          {state ? (canOnline ? "LIVE JOINT STATE" : "CAN OFFLINE") : "WAITING FOR JOINT STATE"}
        </span>
      </div>
    </section>
  );
}

function ImuArray({ state }: { state: RobotState | null }) {
  const fallback = missingLabel(Boolean(state));
  return (
    <section className="module-section" aria-labelledby="imu-title">
      <div className="section-heading">
        <div>
          <span className="section-index">S.02</span>
          <h3 id="imu-title">IMU array</h3>
        </div>
        <Radio aria-hidden="true" size={16} />
      </div>
      <div className="imu-array">
        {[0, 1, 2, 3].map((index) => {
          const online = arrayValue(state?.imu_online, index);
          const calibrated = arrayValue(state?.imu_calibrated, index);
          const onlineLabel = online === true ? "ONLINE" : online === false ? "OFFLINE" : fallback;
          const calibrationLabel = calibrated === true
            ? "CALIBRATED"
            : calibrated === false
              ? "CALIBRATION REQUIRED"
              : "DATA UNAVAILABLE";
          return (
            <div className="imu-row" data-state={online ? "online" : "offline"} key={index}>
              <span className="hardware-id">IMU {String(index + 1).padStart(2, "0")}</span>
              <span className="inline-state" data-state={online ? "healthy" : "offline"}>{onlineLabel}</span>
              <span className="mono-value">{calibrationLabel}</span>
            </div>
          );
        })}
      </div>
      <p className="section-note">Sample age / DATA UNAVAILABLE</p>
    </section>
  );
}

function EncoderReadout({ state }: { state: RobotState | null }) {
  const fallback = missingLabel(Boolean(state));
  return (
    <section className="module-section" aria-labelledby="encoder-title">
      <div className="section-heading">
        <div>
          <span className="section-index">S.03</span>
          <h3 id="encoder-title">Encoder state</h3>
        </div>
        <Gauge aria-hidden="true" size={16} />
      </div>
      <div className="data-table encoder-table" role="table" aria-label="Encoder state">
        <div className="data-row data-head" role="row">
          <span>JOINT</span><span>POSITION</span><span>VELOCITY</span>
        </div>
        {JOINTS.map((joint, index) => (
          <div className="data-row" role="row" key={joint.id}>
            <span><strong>{joint.short}</strong> {joint.name}</span>
            <span className="mono-value">
              {formatMeasurement(arrayValue(state?.joint_position, index), 2, "rad", fallback)}
            </span>
            <span className="mono-value">
              {formatMeasurement(arrayValue(state?.joint_velocity, index), 2, "rad/s", fallback)}
            </span>
          </div>
        ))}
      </div>
    </section>
  );
}

function CanMotorHealth({ state }: { state: RobotState | null }) {
  const fallback = missingLabel(Boolean(state));
  const maxTemperature = maximum(state?.motor_temperature);
  return (
    <section className="module-section" aria-labelledby="motor-health-title">
      <div className="section-heading">
        <div>
          <span className="section-index">S.04</span>
          <h3 id="motor-health-title">CAN &amp; motor health</h3>
        </div>
        <Cable aria-hidden="true" size={16} />
      </div>
      <div className="hardware-metrics">
        <div><Cable aria-hidden="true" /><span>CAN</span><strong>{state?.can_online === true ? "ONLINE" : state?.can_online === false ? "OFFLINE" : fallback}</strong></div>
        <div><Thermometer aria-hidden="true" /><span>MAX TEMP</span><strong>{formatMeasurement(maxTemperature, 1, "°C", fallback)}</strong></div>
        <div><BatteryMedium aria-hidden="true" /><span>BATTERY</span><strong>{formatPercent(state?.battery_percent, fallback)}</strong></div>
        <div><BatteryMedium aria-hidden="true" /><span>BUS</span><strong>{formatMeasurement(state?.bus_voltage, 1, "V", fallback)} / {formatMeasurement(state?.bus_current, 1, "A", fallback)}</strong></div>
      </div>
      <div className="motor-temperature-strip" aria-label="Motor temperatures">
        {JOINTS.map((joint, index) => (
          <span key={joint.id}>
            <small>{joint.short}</small>
            <strong>{formatMeasurement(arrayValue(state?.motor_temperature, index), 1, "°C", "-- °C")}</strong>
          </span>
        ))}
      </div>
      <p className="section-note">
        Fault / {state?.fault_code ? `${state.fault_code}${state.fault_message ? ` · ${state.fault_message}` : ""}` : state?.fault_code === "" ? "NONE" : fallback}
      </p>
    </section>
  );
}

export function SensePanel({
  active,
  robot,
}: {
  active: boolean;
  robot: RobotSocketView;
}) {
  const state = robot.snapshot?.state ?? null;
  return (
    <article className="stage-panel sense-panel" data-stage="sense" data-mobile-active={active}>
      <header className="stage-panel-header">
        <div>
          <span className="stage-kicker">01 / SENSOR BUS</span>
          <h2>SENSE</h2>
        </div>
        <span className="stage-state" data-state={robot.connection}>
          {robot.connection === "online" ? <Radio aria-hidden="true" size={14} /> : <WifiOff aria-hidden="true" size={14} />}
          {connectionLabel(robot)}
        </span>
      </header>
      <JointMap state={state} />
      <ImuArray state={state} />
      <EncoderReadout state={state} />
      <CanMotorHealth state={state} />
    </article>
  );
}
