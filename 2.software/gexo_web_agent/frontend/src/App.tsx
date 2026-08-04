import { useEffect, useState } from "react";

import { CockpitHeader } from "./components/header/CockpitHeader";
import { ClosedLoopDeck } from "./components/deck/ClosedLoopDeck";
import { TelemetryDock } from "./components/telemetry/TelemetryDock";
import { DebugDrawer } from "./components/debug/DebugDrawer";
import { ModeConfirmDialog } from "./components/dialog/ModeConfirmDialog";
import { ProductNavigation, type ProductView } from "./components/navigation/ProductNavigation";
import { useAgentEvents } from "./hooks/useAgentEvents";
import { useResponsiveDeck } from "./hooks/useResponsiveDeck";
import { useRobotCommand } from "./hooks/useRobotCommand";
import { useRobotSocket } from "./hooks/useRobotSocket";
import { useTelemetryBuffer } from "./hooks/useTelemetryBuffer";

export function App() {
  const [activeView, setActiveView] = useState<ProductView>(() =>
    window.location.pathname === "/ring" ? "ring" : "cockpit",
  );
  const robot = useRobotSocket();
  const telemetry = useTelemetryBuffer(robot.snapshot, robot.connection);
  const commands = useRobotCommand(robot.refresh);
  const agentEvents = useAgentEvents(commands.activity);
  const { activeStage, setActiveStage } = useResponsiveDeck();

  const navigate = (view: ProductView) => {
    if (view === activeView) return;
    const path = view === "ring" ? "/ring" : "/cockpit";
    window.history.pushState({ view }, "", path);
    setActiveView(view);
  };

  useEffect(() => {
    const handlePopState = () =>
      setActiveView(window.location.pathname === "/ring" ? "ring" : "cockpit");
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  return (
    <div className="app-shell" data-connection={robot.connection}>
      <ProductNavigation activeView={activeView} onNavigate={navigate} />
      <section className="product-view" data-visible={activeView === "ring"} aria-hidden={activeView !== "ring"}>
        <iframe
          className="ring-page-frame"
          title="Alloop Ring"
          src="/alloop/index.html"
        />
      </section>
      <section className="product-view cockpit-view" data-visible={activeView === "cockpit"} aria-hidden={activeView !== "cockpit"}>
        <CockpitHeader robot={robot} />
        <main className="cockpit-main">
          <ClosedLoopDeck
            activeStage={activeStage}
            agentEvents={agentEvents}
            commands={commands}
            onStageChange={setActiveStage}
            robot={robot}
          />
          <TelemetryDock buffer={telemetry} />
          <DebugDrawer robot={robot} />
        </main>
      </section>
      {activeView === "cockpit" ? <ModeConfirmDialog commands={commands} robot={robot} /> : null}
    </div>
  );
}
