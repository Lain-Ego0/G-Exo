import { Activity, BrainCircuit, Zap } from "lucide-react";

import { ActPanel } from "../act/ActPanel";
import { ReasonPanel } from "../reason/ReasonPanel";
import { SensePanel } from "../sense/SensePanel";
import { ClosedLoopSpine } from "./ClosedLoopSpine";
import { STAGES, STAGE_LABELS, type StageId } from "../../types/ui";

const ICONS = {
  sense: Activity,
  reason: BrainCircuit,
  act: Zap,
};

export function ClosedLoopDeck({
  activeStage,
  onStageChange,
}: {
  activeStage: StageId;
  onStageChange: (stage: StageId) => void;
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

      <ClosedLoopSpine />

      <div className="stage-grid">
        <SensePanel active={activeStage === "sense"} />
        <ReasonPanel active={activeStage === "reason"} />
        <ActPanel active={activeStage === "act"} />
      </div>
    </section>
  );
}
