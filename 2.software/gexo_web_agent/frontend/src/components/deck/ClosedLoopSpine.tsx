import type { StageId } from "../../types/ui";
import { STAGES, STAGE_LABELS } from "../../types/ui";
import type { ConnectionState } from "../../types/robot";

export function ClosedLoopSpine({
  activeStage,
  connection,
  eventKey,
}: {
  activeStage?: StageId;
  connection: ConnectionState;
  eventKey: string | null;
}) {
  return (
    <div className="closed-loop-spine" aria-label="Closed loop status" data-flow={connection === "online" ? "true" : undefined}>
      <span className="spine-caption">
        闭环 / CLOSED LOOP · {connection === "online" ? "实时遥测 / LIVE TELEMETRY" : connection.toUpperCase()}
      </span>
      <div className="spine-track" aria-hidden="true">
        {STAGES.map((stage) => (
          <div
            className="spine-stage"
            data-stage={stage}
            data-active={activeStage === stage || undefined}
            data-pulse={activeStage === stage && eventKey !== null || undefined}
            key={`${stage}-${activeStage === stage ? eventKey ?? "steady" : "idle"}`}
          >
            <span className="spine-node" />
            <span>{STAGE_LABELS[stage]}</span>
          </div>
        ))}
      </div>
      <div className="spine-return" aria-hidden="true">
        <span>遥测时间轴 / TELEMETRY TIME AXIS</span>
      </div>
    </div>
  );
}
