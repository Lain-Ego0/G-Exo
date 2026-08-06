import { useMemo, useState } from "react";
import { Pause, Play } from "lucide-react";

import { radiansToDegrees } from "../../lib/imu";
import type { TelemetryBufferView, TelemetryPoint } from "../../hooks/useTelemetryBuffer";
import { JOINT_IDS, type JointId } from "../../types/robot";
import { TelemetryChart, type TelemetrySeries } from "./TelemetryChart";

const JOINT_LABELS: Record<JointId, string> = {
  left_hip: "LH / 左髋",
  left_knee: "LK / 左膝",
  right_hip: "RH / 右髋",
  right_knee: "RK / 右膝",
};
const COLORS = ["#23d8f2", "#ad8fff", "#ffc424"];
const CHARTS = [
  { id: "orientation", label: "姿态 RPY" },
  { id: "angular", label: "角速度 XYZ" },
  { id: "acceleration", label: "线加速度 XYZ" },
] as const;
type ChartId = (typeof CHARTS)[number]["id"];

function value(point: TelemetryPoint, joint: JointId, group: "euler" | "angularVelocity" | "linearAcceleration", axis: "x" | "y" | "z"): number | null {
  const reading = point.imus[joint];
  if (!reading) return null;
  const result = reading[group]?.[axis] ?? null;
  return group === "euler" && result !== null ? radiansToDegrees(result) : result;
}

export function TelemetryDock({ buffer }: { buffer: TelemetryBufferView }) {
  const [activeChart, setActiveChart] = useState<ChartId>("orientation");
  const [rangeSeconds, setRangeSeconds] = useState<15 | 30 | 60>(30);
  const [selectedJoint, setSelectedJoint] = useState<JointId>("left_hip");
  const [cursorMs, setCursorMs] = useState<number | null>(null);
  const [pausedAt, setPausedAt] = useState<number | null>(null);
  const endMs = pausedAt ?? Date.now();
  const startMs = endMs - rangeSeconds * 1_000;
  const group = activeChart === "orientation" ? "euler" : activeChart === "angular" ? "angularVelocity" : "linearAcceleration";
  const unit = activeChart === "orientation" ? "deg" : activeChart === "angular" ? "rad/s" : "m/s²";
  const axes = useMemo<TelemetrySeries[]>(() => (["x", "y", "z"] as const).map((axis, index) => ({
    id: axis,
    label: axis.toUpperCase(),
    color: COLORS[index],
    value: (point) => value(point, selectedJoint, group, axis),
  })), [group, selectedJoint]);
  const togglePaused = () => {
    const next = !buffer.paused;
    setPausedAt(next ? Date.now() : null);
    buffer.setPaused(next);
  };

  return (
    <section className="telemetry-dock imu-telemetry-dock" aria-labelledby="telemetry-title">
      <header className="telemetry-toolbar">
        <div><span className="section-index">S.02 / 60 SECOND BUFFER</span><h2 id="telemetry-title">实时曲线 <small>LIVE IMU TELEMETRY</small></h2></div>
        <nav className="chart-tabs" aria-label="IMU chart type">
          {CHARTS.map((chart) => <button key={chart.id} aria-selected={activeChart === chart.id} onClick={() => setActiveChart(chart.id)} role="tab" type="button">{chart.label}</button>)}
        </nav>
        <div className="telemetry-tools">
          <label className="joint-select"><span>关节 / IMU</span><select value={selectedJoint} onChange={(event) => setSelectedJoint(event.target.value as JointId)}>{JOINT_IDS.map((joint) => <option key={joint} value={joint}>{JOINT_LABELS[joint]}</option>)}</select></label>
          <div className="range-segment" aria-label="Telemetry range">{([15, 30, 60] as const).map((range) => <button key={range} aria-pressed={rangeSeconds === range} onClick={() => setRangeSeconds(range)} type="button">{range}s</button>)}</div>
          <button className="icon-button" aria-label={buffer.paused ? "Resume telemetry" : "Pause telemetry"} disabled={!buffer.points.length} onClick={togglePaused} title={buffer.paused ? "Resume telemetry" : "Pause telemetry"} type="button">{buffer.paused ? <Play aria-hidden="true" size={17} /> : <Pause aria-hidden="true" size={17} />}</button>
        </div>
      </header>
      <TelemetryChart cursorMs={cursorMs} endMs={endMs} id={activeChart} onCursorChange={setCursorMs} points={buffer.points} series={axes} startMs={startMs} title={`${JOINT_LABELS[selectedJoint]} ${CHARTS.find((chart) => chart.id === activeChart)?.label ?? "Telemetry"}`} unit={unit} emptyLabel="等待真实 IMU 数据" />
    </section>
  );
}
