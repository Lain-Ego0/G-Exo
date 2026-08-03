import {
  BatteryMedium,
  Cable,
  Gauge,
  Radio,
  Thermometer,
  WifiOff,
} from "lucide-react";

import { JOINTS } from "../../types/ui";

const UNAVAILABLE = "DATA UNAVAILABLE";

function PanelHeader() {
  return (
    <header className="stage-panel-header">
      <div>
        <span className="stage-kicker">01 / SENSOR BUS</span>
        <h2>SENSE</h2>
      </div>
      <span className="stage-state" data-state="offline">
        <WifiOff aria-hidden="true" size={14} />
        NOT CONNECTED
      </span>
    </header>
  );
}

function JointMap() {
  return (
    <section className="module-section joint-map-section" aria-labelledby="joint-map-title">
      <div className="section-heading">
        <div>
          <span className="section-index">S.01</span>
          <h3 id="joint-map-title">Four-joint body map</h3>
        </div>
        <span className="section-meta">ANGLE / TEMPERATURE</span>
      </div>
      <div className="joint-map" data-state="offline">
        <img
          src="/gexo-exoskeleton.png"
          alt="G-Exo lower-limb exoskeleton front view"
        />
        {JOINTS.map((joint) => (
          <div className={`joint-node joint-node-${joint.id}`} key={joint.id}>
            <span className="joint-node-dot" />
            <strong>{joint.short}</strong>
            <span>-- rad</span>
          </div>
        ))}
        <span className="map-offline-label">WAITING FOR JOINT STATE</span>
      </div>
    </section>
  );
}

function ImuArray() {
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
        {[1, 2, 3, 4].map((index) => (
          <div className="imu-row" key={index}>
            <span className="hardware-id">IMU {String(index).padStart(2, "0")}</span>
            <span className="inline-state" data-state="offline">NOT CONNECTED</span>
            <span className="mono-value">-- ms</span>
          </div>
        ))}
      </div>
      <p className="section-note">Calibration / {UNAVAILABLE}</p>
    </section>
  );
}

function EncoderReadout() {
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
        {JOINTS.map((joint) => (
          <div className="data-row" role="row" key={joint.id}>
            <span><strong>{joint.short}</strong> {joint.name}</span>
            <span className="mono-value">-- rad</span>
            <span className="mono-value">-- rad/s</span>
          </div>
        ))}
      </div>
    </section>
  );
}

function CanMotorHealth() {
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
        <div><Cable aria-hidden="true" /><span>CAN</span><strong>NOT CONNECTED</strong></div>
        <div><Thermometer aria-hidden="true" /><span>MAX TEMP</span><strong>-- °C</strong></div>
        <div><BatteryMedium aria-hidden="true" /><span>BUS</span><strong>-- V / -- A</strong></div>
      </div>
      <p className="section-note">Fault code / {UNAVAILABLE}</p>
    </section>
  );
}

export function SensePanel({ active }: { active: boolean }) {
  return (
    <article className="stage-panel sense-panel" data-stage="sense" data-mobile-active={active}>
      <PanelHeader />
      <JointMap />
      <ImuArray />
      <EncoderReadout />
      <CanMotorHealth />
    </article>
  );
}
