import {
  Bot,
  BrainCircuit,
  CheckCircle2,
  Cpu,
  MessageSquareText,
  Network,
  Send,
  ShieldCheck,
  WifiOff,
} from "lucide-react";

const FLOW = [
  { label: "User Intent", detail: "DATA UNAVAILABLE", icon: MessageSquareText },
  { label: "LLM Intent Parsing", detail: "DATA UNAVAILABLE", icon: BrainCircuit },
  { label: "Safety Validation", detail: "DATA UNAVAILABLE", icon: ShieldCheck },
  { label: "ROS2 Service", detail: "DATA UNAVAILABLE", icon: Network },
  { label: "Controller", detail: "DATA UNAVAILABLE", icon: Cpu },
];

function SafetyGuardFlow() {
  return (
    <section className="module-section reason-flow-section" aria-labelledby="safety-flow-title">
      <div className="section-heading">
        <div>
          <span className="section-index">R.02</span>
          <h3 id="safety-flow-title">SafetyGuard flow</h3>
        </div>
        <span className="section-meta">EVENT API / UNAVAILABLE</span>
      </div>
      <ol className="safety-flow">
        {FLOW.map(({ label, detail, icon: Icon }) => (
          <li className="flow-node" data-state="unavailable" key={label}>
            <span className="flow-icon"><Icon aria-hidden="true" size={17} /></span>
            <div><strong>{label}</strong><span>{detail}</span></div>
            <CheckCircle2 className="flow-result" aria-hidden="true" size={16} />
          </li>
        ))}
      </ol>
    </section>
  );
}

export function ReasonPanel({ active }: { active: boolean }) {
  return (
    <article className="stage-panel reason-panel" data-stage="reason" data-mobile-active={active}>
      <header className="stage-panel-header">
        <div>
          <span className="stage-kicker">02 / DECISION PATH</span>
          <h2>REASON</h2>
        </div>
        <span className="stage-state" data-state="offline">
          <WifiOff aria-hidden="true" size={14} />
          NOT CONNECTED
        </span>
      </header>

      <section className="module-section agent-identity" aria-labelledby="agent-title">
        <div className="agent-mark"><Bot aria-hidden="true" size={24} /></div>
        <div>
          <span className="section-index">R.01 / LOCAL AGENT</span>
          <h3 id="agent-title">Qwen Local Agent</h3>
          <p>Model ID / DATA UNAVAILABLE</p>
        </div>
        <span className="inline-state" data-state="offline">UNAVAILABLE</span>
      </section>

      <SafetyGuardFlow />

      <section className="module-section event-detail" aria-labelledby="event-title">
        <div className="section-heading">
          <div>
            <span className="section-index">R.03</span>
            <h3 id="event-title">Tool event detail</h3>
          </div>
        </div>
        <dl>
          <div><dt>INTENT</dt><dd>DATA UNAVAILABLE</dd></div>
          <div><dt>REQUEST ID</dt><dd>--</dd></div>
          <div><dt>SAFETY DECISION</dt><dd>DATA UNAVAILABLE</dd></div>
          <div><dt>ACKNOWLEDGEMENT</dt><dd>-- ms</dd></div>
        </dl>
      </section>

      <section className="module-section command-surface" aria-labelledby="command-title">
        <div className="section-heading">
          <div>
            <span className="section-index">R.04</span>
            <h3 id="command-title">Agent command</h3>
          </div>
        </div>
        <div className="command-input">
          <input aria-label="Agent command" disabled placeholder="Agent unavailable" />
          <button aria-label="Send command" disabled title="Send command" type="button">
            <Send aria-hidden="true" size={18} />
          </button>
        </div>
        <p className="section-note">No command is sent until the backend is connected.</p>
      </section>
    </article>
  );
}
