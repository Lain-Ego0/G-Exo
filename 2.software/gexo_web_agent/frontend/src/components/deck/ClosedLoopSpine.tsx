import type { StageId } from "../../types/ui";
import { STAGES, STAGE_LABELS } from "../../types/ui";
import type { ConnectionState } from "../../types/robot";

export function ClosedLoopSpine({
  activeStage,
  connection,
}: {
  activeStage?: StageId;
  connection: ConnectionState;
}) {
  return (
    <div className="closed-loop-spine" aria-label="Closed loop status">
      <span className="spine-caption">
        CLOSED LOOP / {connection === "online" ? "LIVE TELEMETRY" : connection.toUpperCase()}
      </span>
      <div className="spine-track" aria-hidden="true">
        {STAGES.map((stage) => (
          <div
            className="spine-stage"
            data-stage={stage}
            data-active={activeStage === stage || undefined}
            key={stage}
          >
            <span className="spine-node" />
            <span>{STAGE_LABELS[stage]}</span>
          </div>
        ))}
      </div>
      <div className="spine-return" aria-hidden="true">
        <span>TELEMETRY TIME AXIS</span>
      </div>
    </div>
  );
}
