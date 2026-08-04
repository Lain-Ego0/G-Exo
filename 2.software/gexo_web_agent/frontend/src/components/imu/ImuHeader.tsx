import { Activity, Clock3, Radio, WifiOff } from "lucide-react";

import { formatAge } from "../../lib/format";
import type { ImuSocketView } from "../../types/robot";

function statusLabel(status: string | undefined): string {
  if (status === "online") return "ONLINE";
  if (status === "degraded") return "DEGRADED";
  if (status === "offline") return "OFFLINE";
  return "WAITING";
}

export function ImuHeader({ robot }: { robot: ImuSocketView }) {
  const overall = robot.snapshot?.overall_status;
  const Icon = robot.connection === "online" ? Radio : WifiOff;
  return (
    <header className="imu-header">
      <div className="imu-title-block">
        <span className="imu-kicker">G-EXO / SENSOR TELEMETRY</span>
        <h1>四路 IMU 遥测 <small>READ-ONLY ROS 2 HUMBLE</small></h1>
      </div>
      <div className="imu-header-rail" aria-label="Telemetry health">
        <span data-state={overall ?? robot.connection}>
          <Activity aria-hidden="true" size={15} />
          <b>{statusLabel(overall)}</b>
        </span>
        <span data-state={robot.connection}>
          <Icon aria-hidden="true" size={15} />
          <b>{robot.apiReachable ? "API ONLINE" : "API OFFLINE"}</b>
        </span>
        <span>
          <Clock3 aria-hidden="true" size={15} />
          <b>{formatAge(robot.ageMs)}</b>
        </span>
      </div>
    </header>
  );
}
