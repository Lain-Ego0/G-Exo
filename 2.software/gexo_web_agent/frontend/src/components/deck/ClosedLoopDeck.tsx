import { Activity, BrainCircuit, Zap } from "lucide-react";

import { ActPanel } from "../act/ActPanel";
import { ReasonPanel } from "../reason/ReasonPanel";
import { SensePanel } from "../sense/SensePanel";
import { ClosedLoopSpine } from "./ClosedLoopSpine";
import type { AgentEventsView } from "../../hooks/useAgentEvents";
import type { RobotCommandView } from "../../hooks/useRobotCommand";
import type { RobotSocketView } from "../../types/robot";
import { STAGES, STAGE_LABELS, type StageId } from "../../types/ui";

const ICONS = {
  sense: Activity,
  reason: BrainCircuit,
  act: Zap,
};

export function ClosedLoopDeck({
  activeStage,
  agentEvents,
  commands,
  onStageChange,
  robot,
}: {
  activeStage: StageId;
  agentEvents: AgentEventsView;
  commands: RobotCommandView;
  onStageChange: (stage: StageId) => void;
  robot: RobotSocketView;
}) {
  return (
    <section className="closed-loop-deck" aria-label="G-Exo closed loop workspace">
      <nav className="mobile-stage-tabs" aria-label="Cockpit stages">
        {STAGES.map((stage) => {
          const Icon = ICONS[stage];
          return (
            <button
              className="stage-tab"
              data-stage={stage}
              aria-selected={activeStage === stage}
              onClick={() => onStageChange(stage)}
              role="tab"
              type="button"
              key={stage}
            >
              <Icon aria-hidden="true" size={16} strokeWidth={1.8} />
              {STAGE_LABELS[stage]}
            </button>
          );
        })}
      </nav>

      <ClosedLoopSpine
        activeStage={agentEvents.activeLoopStage ?? (robot.connection === "online" ? "sense" : undefined)}
        connection={robot.connection}
      />

      <div className="stage-grid">
        <SensePanel active={activeStage === "sense"} robot={robot} />
        <ReasonPanel
          active={activeStage === "reason"}
          agentEvents={agentEvents}
          commands={commands}
          robot={robot}
        />
        <ActPanel active={activeStage === "act"} commands={commands} robot={robot} />
      </div>
    </section>
  );
}
