import { Bug } from "lucide-react";
import type { RobotSocketView } from "../../types/robot";

export function DebugDrawer({ robot }: { robot: RobotSocketView }) {
  return (
    <details className="debug-drawer">
      <summary><Bug aria-hidden="true" size={15} />Debug state</summary>
      <div className="debug-content">
        <span>RAW STATE</span>
        <pre>{robot.snapshot ? JSON.stringify(robot.snapshot, null, 2) : "DATA UNAVAILABLE"}</pre>
      </div>
    </details>
  );
}
