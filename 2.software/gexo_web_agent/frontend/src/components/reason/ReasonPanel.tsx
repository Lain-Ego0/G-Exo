import { useState, type FormEvent } from "react";
import {
  Bot,
  BrainCircuit,
  CheckCircle2,
  Circle,
  Clock3,
  Cpu,
  History,
  MessageSquareText,
  Network,
  PauseCircle,
  Send,
  ShieldCheck,
  WifiOff,
  XCircle,
} from "lucide-react";

import type {
  AgentEventsView,
  AgentStageId,
  AgentStageStatus,
} from "../../hooks/useAgentEvents";
import type { RobotCommandView } from "../../hooks/useRobotCommand";
import type { RobotSocketView } from "../../types/robot";

const FLOW_ICONS: Record<AgentStageId, typeof MessageSquareText> = {
  intent: MessageSquareText,
  parsing: BrainCircuit,
  safety: ShieldCheck,
  ros2: Network,
  controller: Cpu,
};

function FlowResult({ status }: { status: AgentStageStatus }) {
  if (status === "passed") return <CheckCircle2 aria-label="Passed" size={16} />;
  if (status === "active") return <Clock3 aria-label="Active" size={16} />;
  if (status === "awaiting_confirmation") {
    return <PauseCircle aria-label="Awaiting confirmation" size={16} />;
  }
  if (status === "rejected" || status === "failed") {
    return <XCircle aria-label={status === "rejected" ? "Rejected" : "Failed"} size={16} />;
  }
  return <Circle aria-label={status === "idle" ? "Idle" : "Unavailable"} size={14} />;
}

function SafetyGuardFlow({ agentEvents }: { agentEvents: AgentEventsView }) {
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
        {agentEvents.stages.map((stage) => {
          const Icon = FLOW_ICONS[stage.id];
          return (
            <li className="flow-node" data-state={stage.status} key={stage.id}>
              <span className="flow-icon"><Icon aria-hidden="true" size={17} /></span>
              <div>
                <strong>{stage.label}</strong>
                <span>{stage.detail}</span>
              </div>
              <span className="flow-result">
                <FlowResult status={stage.status} />
                {stage.durationMs === null ? null : <small>{stage.durationMs} ms</small>}
              </span>
            </li>
          );
        })}
      </ol>
    </section>
  );
}

function MessageView({
  message,
}: {
  message: RobotCommandView["messages"][number];
}) {
  return (
    <article className="agent-message" data-role={message.role}>
      <span>{message.role === "user" ? "USER" : "AGENT"}</span>
      <p>{message.text}</p>
      {message.sources.length > 0 ? (
        <ul aria-label="Sources">
          {message.sources.map((source, index) => (
            <li key={`${source.file}-${index}`}>
              {source.file}{source.section ? ` / ${source.section}` : ""}
            </li>
          ))}
        </ul>
      ) : null}
    </article>
  );
}

function AgentCommandSurface({
  commands,
  robot,
}: {
  commands: RobotCommandView;
  robot: RobotSocketView;
}) {
  const [text, setText] = useState("");
  const recentMessages = commands.messages.slice(-2);
  const historyMessages = commands.messages.slice(0, -2);
  const available = robot.apiReachable;

  const submit = (event: FormEvent) => {
    event.preventDefault();
    const value = text.trim();
    if (!value || commands.busy || !available) return;
    setText("");
    void commands.sendChat(value);
  };

  return (
    <section className="module-section command-surface" aria-labelledby="command-title">
      <div className="section-heading">
        <div>
          <span className="section-index">R.04</span>
          <h3 id="command-title">Agent command</h3>
        </div>
        <span className="section-meta">{available ? "API REACHABLE" : "NOT CONNECTED"}</span>
      </div>

      <div className="latest-messages" aria-live="polite">
        {recentMessages.length > 0
          ? recentMessages.map((message) => <MessageView key={message.id} message={message} />)
          : <p className="empty-message">NO AGENT MESSAGE</p>}
      </div>

      <form className="command-input" onSubmit={submit}>
        <input
          aria-label="Agent command"
          disabled={!available || commands.busy}
          maxLength={2000}
          onChange={(event) => setText(event.target.value)}
          placeholder={available ? "Enter an intent or document question" : "Agent API not connected"}
          value={text}
        />
        <button
          aria-label="Send command"
          disabled={!available || commands.busy || !text.trim()}
          title="Send command"
          type="submit"
        >
          <Send aria-hidden="true" size={18} />
        </button>
      </form>

      {historyMessages.length > 0 ? (
        <details className="conversation-drawer">
          <summary><History aria-hidden="true" size={14} />Conversation history</summary>
          <div>{historyMessages.map((message) => <MessageView key={message.id} message={message} />)}</div>
        </details>
      ) : null}
    </section>
  );
}

export function ReasonPanel({
  active,
  agentEvents,
  commands,
  robot,
}: {
  active: boolean;
  agentEvents: AgentEventsView;
  commands: RobotCommandView;
  robot: RobotSocketView;
}) {
  return (
    <article className="stage-panel reason-panel" data-stage="reason" data-mobile-active={active}>
      <header className="stage-panel-header">
        <div>
          <span className="stage-kicker">02 / DECISION PATH</span>
          <h2>REASON</h2>
        </div>
        <span className="stage-state" data-state="unavailable">
          <WifiOff aria-hidden="true" size={14} />
          EVENT DATA UNAVAILABLE
        </span>
      </header>

      <section className="module-section agent-identity" aria-labelledby="agent-title">
        <div className="agent-mark"><Bot aria-hidden="true" size={24} /></div>
        <div>
          <span className="section-index">R.01 / LOCAL AGENT</span>
          <h3 id="agent-title">Qwen Local Agent</h3>
          <p>Model ID / DATA UNAVAILABLE</p>
        </div>
        <span className="inline-state" data-state="unavailable">STATUS UNAVAILABLE</span>
      </section>

      <SafetyGuardFlow agentEvents={agentEvents} />

      <section className="module-section event-detail" aria-labelledby="event-title">
        <div className="section-heading">
          <div>
            <span className="section-index">R.03</span>
            <h3 id="event-title">Tool event detail</h3>
          </div>
        </div>
        <dl>
          <div><dt>INTENT</dt><dd>{agentEvents.intent ?? "DATA UNAVAILABLE"}</dd></div>
          <div><dt>REQUEST ID</dt><dd>{agentEvents.requestId ?? "--"}</dd></div>
          <div><dt>SAFETY DECISION</dt><dd>{agentEvents.safetyDecision ?? "DATA UNAVAILABLE"}</dd></div>
          <div><dt>ACKNOWLEDGEMENT</dt><dd>{agentEvents.acknowledgementMs === null ? "-- ms" : `${agentEvents.acknowledgementMs} ms`}</dd></div>
        </dl>
      </section>

      <AgentCommandSurface commands={commands} robot={robot} />
    </article>
  );
}
