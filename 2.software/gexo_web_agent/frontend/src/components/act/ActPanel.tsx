import {
  Gauge,
  Minus,
  Plus,
  ShieldAlert,
  SlidersHorizontal,
  WifiOff,
  Zap,
} from "lucide-react";

import { JOINTS } from "../../types/ui";

function JointTorqueMatrix() {
  return (
    <section className="module-section torque-section" aria-labelledby="torque-title">
      <div className="section-heading">
        <div>
          <span className="section-index">A.03</span>
          <h3 id="torque-title">Four-joint torque</h3>
        </div>
        <span className="est-badge">EST</span>
      </div>
      <div className="torque-legend">
        <span><i data-series="command" />COMMAND TORQUE</span>
        <span><i data-series="estimated" />ESTIMATED TORQUE</span>
      </div>
      <div className="torque-matrix">
        {JOINTS.map((joint) => (
          <div className="torque-row" key={joint.id}>
            <div className="torque-joint"><strong>{joint.short}</strong><span>{joint.name}</span></div>
            <div className="torque-values">
              <span><small>CMD</small><strong>-- Nm</strong></span>
              <span><small>EST</small><strong>-- Nm</strong></span>
              <span><small>DELTA</small><strong>-- Nm</strong></span>
            </div>
            <div className="torque-track" aria-hidden="true">
              <span className="torque-zero" />
            </div>
          </div>
        ))}
      </div>
      <div className="integrity-notice">
        <ShieldAlert aria-hidden="true" size={16} />
        <div><strong>Estimated Torque (EST)</strong><span>Backend field unavailable: actual_torque</span></div>
      </div>
    </section>
  );
}

export function ActPanel({ active }: { active: boolean }) {
  return (
    <article className="stage-panel act-panel" data-stage="act" data-mobile-active={active}>
      <header className="stage-panel-header">
        <div>
          <span className="stage-kicker">03 / ACTUATOR OUTPUT</span>
          <h2>ACT</h2>
        </div>
        <span className="stage-state" data-state="offline">
          <WifiOff aria-hidden="true" size={14} />
          NOT CONNECTED
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
          <button disabled type="button"><Zap aria-hidden="true" size={16} />Assist</button>
          <button disabled type="button"><Gauge aria-hidden="true" size={16} />Damping</button>
        </div>
        <p className="section-note">Current mode / DATA UNAVAILABLE</p>
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
          <button aria-label="Decrease assist by 10 percent" disabled title="Decrease assist" type="button">
            <Minus aria-hidden="true" size={20} />
          </button>
          <div className="assist-value"><strong>--</strong><span>%</span></div>
          <button aria-label="Increase assist by 10 percent" disabled title="Increase assist" type="button">
            <Plus aria-hidden="true" size={20} />
          </button>
        </div>
        <div className="assist-scale" aria-hidden="true"><span /><span /><span /><span /><span /><span /><span /><span /></div>
        <p className="section-note">All four joints adjust together.</p>
      </section>

      <JointTorqueMatrix />

      <section className="module-section command-result" aria-labelledby="result-title">
        <div className="section-heading">
          <div>
            <span className="section-index">A.04</span>
            <h3 id="result-title">Command result</h3>
          </div>
        </div>
        <p><span className="status-dot" />DATA UNAVAILABLE</p>
      </section>
    </article>
  );
}
