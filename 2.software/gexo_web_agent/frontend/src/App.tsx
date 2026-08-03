import { CockpitHeader } from "./components/header/CockpitHeader";
import { ClosedLoopDeck } from "./components/deck/ClosedLoopDeck";
import { TelemetryDock } from "./components/telemetry/TelemetryDock";
import { DebugDrawer } from "./components/debug/DebugDrawer";
import { ModeConfirmDialog } from "./components/dialog/ModeConfirmDialog";
import { useAgentEvents } from "./hooks/useAgentEvents";
import { useResponsiveDeck } from "./hooks/useResponsiveDeck";
import { useRobotCommand } from "./hooks/useRobotCommand";
import { useRobotSocket } from "./hooks/useRobotSocket";
import { useTelemetryBuffer } from "./hooks/useTelemetryBuffer";

export function App() {
  const robot = useRobotSocket();
  const telemetry = useTelemetryBuffer(robot.snapshot, robot.connection);
  const commands = useRobotCommand(robot.refresh);
  const agentEvents = useAgentEvents(commands.activity);
  const { activeStage, setActiveStage } = useResponsiveDeck();

  return (
    <div className="app-shell" data-connection={robot.connection}>
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
      <ModeConfirmDialog commands={commands} robot={robot} />
    </div>
  );
}
