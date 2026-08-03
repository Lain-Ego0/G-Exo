import { useEffect, useState } from "react";
import { Bug } from "lucide-react";

import {
  getDebugScenario,
  setDebugScenario,
  type DebugScenarioView,
} from "../../lib/api";
import type { RobotSocketView } from "../../types/robot";

export function DebugDrawer({ robot }: { robot: RobotSocketView }) {
  const [debug, setDebug] = useState<DebugScenarioView | null>(null);
  const [changing, setChanging] = useState(false);

  useEffect(() => {
    let active = true;
    void getDebugScenario()
      .then((value) => { if (active) setDebug(value); })
      .catch(() => { if (active) setDebug(null); });
    return () => { active = false; };
  }, [robot.apiReachable]);

  const changeScenario = async (scenario: string) => {
    if (!debug || !debug.available.includes(scenario)) return;
    setChanging(true);
    try {
      await setDebugScenario(scenario);
      setDebug({ ...debug, scenario });
      await robot.refresh();
    } finally {
      setChanging(false);
    }
  };

  return (
    <details className="debug-drawer">
      <summary><Bug aria-hidden="true" size={15} />Debug state</summary>
      <div className="debug-content">
        {debug ? (
          <label className="debug-scenario">
            <span>MOCK SCENARIO</span>
            <select
              disabled={changing}
              onChange={(event) => void changeScenario(event.target.value)}
              value={debug.scenario}
            >
              {debug.available.map((scenario) => (
                <option key={scenario} value={scenario}>{scenario}</option>
              ))}
            </select>
          </label>
        ) : null}
        <span>RAW STATE</span>
        <pre>{robot.snapshot ? JSON.stringify(robot.snapshot, null, 2) : "DATA UNAVAILABLE"}</pre>
      </div>
    </details>
  );
}
