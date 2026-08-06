import { useEffect, useState } from "react";

import { ImuDashboard } from "./components/imu/ImuDashboard";
import { ImuHeader } from "./components/imu/ImuHeader";
import { SimulatedModeControl } from "./components/control/SimulatedModeControl";
import { ProductNavigation, type ProductView } from "./components/navigation/ProductNavigation";
import { TelemetryDock } from "./components/telemetry/TelemetryDock";
import { useRobotSocket } from "./hooks/useRobotSocket";
import { useRobotCommand } from "./hooks/useRobotCommand";
import { useSimulatedControl } from "./hooks/useSimulatedControl";
import { useTelemetryBuffer } from "./hooks/useTelemetryBuffer";

export function App() {
  const [activeView, setActiveView] = useState<ProductView>(() => window.location.pathname === "/ring" ? "ring" : "cockpit");
  const robot = useRobotSocket();
  const simulatedControl = useSimulatedControl();
  const commands = useRobotCommand(simulatedControl.refresh);
  const telemetry = useTelemetryBuffer(robot.snapshot, robot.connection);

  const navigate = (view: ProductView) => {
    if (view === activeView) return;
    window.history.pushState({ view }, "", view === "ring" ? "/ring" : "/cockpit");
    setActiveView(view);
  };

  useEffect(() => {
    const handlePopState = () => setActiveView(window.location.pathname === "/ring" ? "ring" : "cockpit");
    window.addEventListener("popstate", handlePopState);
    return () => window.removeEventListener("popstate", handlePopState);
  }, []);

  return (
    <div className="app-shell" data-connection={robot.connection}>
      <ProductNavigation activeView={activeView} onNavigate={navigate} />
      <section className="product-view" data-visible={activeView === "ring"} aria-hidden={activeView !== "ring"}>
        <iframe allow="bluetooth" className="ring-page-frame" title="Alloop Ring Telemetry" src="/alloop/index.html" />
      </section>
      <section className="product-view cockpit-view" data-visible={activeView === "cockpit"} aria-hidden={activeView !== "cockpit"}>
        <ImuHeader robot={robot} />
        <main className="cockpit-main imu-main">
          <SimulatedModeControl commands={commands} robot={simulatedControl} />
          <ImuDashboard robot={robot} />
          <TelemetryDock buffer={telemetry} />
        </main>
      </section>
    </div>
  );
}
