import { useState } from "react";

import { CockpitHeader } from "./components/header/CockpitHeader";
import { ClosedLoopDeck } from "./components/deck/ClosedLoopDeck";
import { TelemetryDock } from "./components/telemetry/TelemetryDock";
import { DebugDrawer } from "./components/debug/DebugDrawer";
import type { StageId } from "./types/ui";

export function App() {
  const [activeStage, setActiveStage] = useState<StageId>("sense");

  return (
    <div className="app-shell" data-connection="offline">
      <CockpitHeader />
      <main className="cockpit-main">
        <ClosedLoopDeck
          activeStage={activeStage}
          onStageChange={setActiveStage}
        />
        <TelemetryDock />
        <DebugDrawer />
      </main>
    </div>
  );
}
