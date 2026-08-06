import { AlertTriangle, Gauge, Radio } from "lucide-react";

import { formatAge, formatMeasurement } from "../../lib/format";
import { radiansToDegrees, quaternionToEuler } from "../../lib/imu";
import { JOINT_IDS, type ImuSocketView, type ImuTelemetry, type JointId } from "../../types/robot";

const LABELS: Record<JointId, { name: string; short: string }> = {
  left_hip: { name: "左髋", short: "LH" },
  left_knee: { name: "左膝", short: "LK" },
  right_hip: { name: "右髋", short: "RH" },
  right_knee: { name: "右膝", short: "RK" },
};

function vectorText(value: { x: number; y: number; z: number } | null, unit: string): string {
  if (!value) return "暂无数据";
  return `${value.x.toFixed(3)} / ${value.y.toFixed(3)} / ${value.z.toFixed(3)} ${unit}`;
}

function quaternionText(imu: ImuTelemetry): string {
  const q = imu.orientation;
  if (!q) return "暂无数据";
  return `${q.x.toFixed(4)} / ${q.y.toFixed(4)} / ${q.z.toFixed(4)} / ${q.w.toFixed(4)}`;
}

function eulerText(imu: ImuTelemetry): string {
  const euler = quaternionToEuler(imu.orientation);
  if (!euler) return "暂无数据";
  return `R ${radiansToDegrees(euler.x).toFixed(1)}°  P ${radiansToDegrees(euler.y).toFixed(1)}°  Y ${radiansToDegrees(euler.z).toFixed(1)}°`;
}

function ImuCard({ imu, joint }: { imu: ImuTelemetry | undefined; joint: JointId }) {
  const label = LABELS[joint];
  const status = imu?.status ?? "offline";
  return (
    <article className="imu-card" data-status={status}>
      <header>
        <div>
          <span className="imu-card-index">{label.short}</span>
          <h2>{label.name} IMU</h2>
        </div>
        <span className="imu-status"><Radio aria-hidden="true" size={14} /> {status.toUpperCase()}</span>
      </header>
      <div className="imu-source">
        <span>{imu?.topic ?? "--"}</span>
        <span>{imu?.frame_id ?? "frame unavailable"}</span>
      </div>
      <div className="imu-readout-grid">
        <div><small>QUATERNION XYZW</small><strong>{imu ? quaternionText(imu) : "暂无数据"}</strong></div>
        <div><small>EULER DISPLAY / DEG</small><strong>{imu ? eulerText(imu) : "暂无数据"}</strong></div>
        <div><small>ANGULAR VELOCITY / RAD/S</small><strong>{vectorText(imu?.angular_velocity ?? null, "rad/s")}</strong></div>
        <div><small>LINEAR ACCELERATION / M/S²</small><strong>{vectorText(imu?.linear_acceleration ?? null, "m/s²")}</strong></div>
      </div>
      <footer>
        <span>AGE <b>{formatAge(imu?.age_ms ?? null)}</b></span>
        <span>RATE <b>{formatMeasurement(imu?.frequency_hz ?? undefined, 1, "Hz", "--")}</b></span>
        <span>LATENCY <b>{formatMeasurement(imu?.latency_ms ?? undefined, 1, "ms", "--")}</b></span>
      </footer>
      {!imu?.mapping_valid && imu?.frame_id ? (
        <p className="imu-warning"><AlertTriangle aria-hidden="true" size={14} /> Frame mapping mismatch: expected {imu.expected_frame_id}</p>
      ) : null}
      {imu && !imu.orientation_covariance_known ? (
        <p className="imu-note">姿态协方差未知 / COVARIANCE UNKNOWN</p>
      ) : null}
    </article>
  );
}

export function ImuDashboard({ robot }: { robot: ImuSocketView }) {
  const byJoint = new Map(robot.snapshot?.imus.map((imu) => [imu.joint, imu]) ?? []);
  return (
    <section className="imu-dashboard" aria-label="Four IMU telemetry">
      <header className="imu-dashboard-heading">
        <div><span className="section-index">S.01 / LIVE SENSORS</span><h2>传感器阵列 <small>IMU ARRAY</small></h2></div>
        <span><Gauge aria-hidden="true" size={16} /> 200 HZ SOURCE / 20 HZ WEB STREAM</span>
      </header>
      <div className="imu-cards">
        {JOINT_IDS.map((joint) => <ImuCard key={joint} joint={joint} imu={byJoint.get(joint)} />)}
      </div>
      <p className="imu-disclaimer">绝对姿态不是精确关节角。膝关节相对角与髋关节角需安装变换、铰链轴和零位校准后单独计算。</p>
    </section>
  );
}
