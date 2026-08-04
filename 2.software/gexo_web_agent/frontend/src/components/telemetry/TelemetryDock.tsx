import { useMemo, useState } from "react";
import { Pause, Play } from "lucide-react";

import { formatMeasurement, formatPercent } from "../../lib/format";
import type { TelemetryBufferView, TelemetryPoint } from "../../hooks/useTelemetryBuffer";
import { JOINTS } from "../../types/ui";
import { TelemetryChart, type TelemetrySeries } from "./TelemetryChart";

const CHARTS = [
  { id: "angle", label: "关节角度 ANGLE" },
  { id: "torque", label: "扭矩 TORQUE" },
  { id: "temperature", label: "温度 TEMP" },
  { id: "battery", label: "电量 / 母线 BATTERY / BUS" },
] as const;

const JOINT_COLORS = ["#23d8f2", "#8edde8", "#ad8fff", "#ff778b"];
type ChartId = (typeof CHARTS)[number]["id"];

function lastDataPoint(points: TelemetryPoint[]): TelemetryPoint | null {
  for (let index = points.length - 1; index >= 0; index -= 1) {
    if (!points[index].gap) return points[index];
  }
  return null;
}

export function TelemetryDock({ buffer }: { buffer: TelemetryBufferView }) {
  const [activeChart, setActiveChart] = useState<ChartId>("angle");
  const [rangeSeconds, setRangeSeconds] = useState<15 | 30 | 60>(60);
  const [selectedJoint, setSelectedJoint] = useState(0);
  const [cursorMs, setCursorMs] = useState<number | null>(null);
  const [pausedAt, setPausedAt] = useState<number | null>(null);
  const endMs = pausedAt ?? Date.now();
  const startMs = endMs - rangeSeconds * 1_000;
  const latest = lastDataPoint(buffer.points);
  const hasActual = latest?.actualTorque.some((value) => value !== null) === true;

  const angleSeries = useMemo<TelemetrySeries[]>(
    () => JOINTS.map((joint, index) => ({
      id: joint.id,
      label: joint.short,
      color: JOINT_COLORS[index],
      value: (point) => point.jointPosition[index],
    })),
    [],
  );
  const temperatureSeries = useMemo<TelemetrySeries[]>(
    () => JOINTS.map((joint, index) => ({
      id: joint.id,
      label: joint.short,
      color: JOINT_COLORS[index],
      value: (point) => point.motorTemperature[index],
    })),
    [],
  );
  const torqueSeries = useMemo<TelemetrySeries[]>(
    () => [
      {
        id: "command",
        label: "CMD",
        color: "#ffc424",
        value: (point) => point.commandTorque[selectedJoint],
      },
      {
        id: hasActual ? "actual" : "estimated",
        label: hasActual ? "ACT" : "EST",
        color: "#ad8fff",
        value: (point) => hasActual
          ? point.actualTorque[selectedJoint]
          : point.estimatedTorque[selectedJoint],
        dashed: !hasActual,
      },
    ],
    [hasActual, selectedJoint],
  );
  const batterySeries = useMemo<TelemetrySeries[]>(
    () => [{
      id: "battery",
      label: "BATTERY",
      color: "#49d8a0",
      value: (point) => point.batteryPercent,
    }],
    [],
  );

  const togglePaused = () => {
    const next = !buffer.paused;
    setPausedAt(next ? Date.now() : null);
    buffer.setPaused(next);
  };

  return (
    <section className="telemetry-dock" aria-labelledby="telemetry-title">
      <header className="telemetry-toolbar">
        <div>
          <span className="section-index">实时缓存 / LIVE BUFFER · 60 SECONDS</span>
          <h2 id="telemetry-title"><span>实时遥测</span><small aria-hidden="true">LIVE TELEMETRY</small></h2>
        </div>
        <nav className="chart-tabs" aria-label="Telemetry chart">
          {CHARTS.map((chart) => (
            <button
              aria-selected={activeChart === chart.id}
              onClick={() => setActiveChart(chart.id)}
              role="tab"
              type="button"
              key={chart.id}
            >
              {chart.label}
            </button>
          ))}
        </nav>
        <div className="telemetry-tools">
          <label className="joint-select">
            <span>扭矩关节 TORQUE JOINT</span>
            <select
              aria-label="Torque joint"
              onChange={(event) => setSelectedJoint(Number(event.target.value))}
              value={selectedJoint}
            >
              {JOINTS.map((joint, index) => (
                <option key={joint.id} value={index}>{joint.short}</option>
              ))}
            </select>
          </label>
          <div className="range-segment" aria-label="Telemetry range">
            {([15, 30, 60] as const).map((range) => (
              <button
                aria-pressed={rangeSeconds === range}
                onClick={() => setRangeSeconds(range)}
                type="button"
                key={range}
              >
                {range}
              </button>
            ))}
          </div>
          <button
            className="icon-button"
            aria-label={buffer.paused ? "Resume telemetry" : "Pause telemetry"}
            disabled={buffer.points.length === 0}
            onClick={togglePaused}
            title={buffer.paused ? "Resume telemetry" : "Pause telemetry"}
            type="button"
          >
            {buffer.paused ? <Play aria-hidden="true" size={17} /> : <Pause aria-hidden="true" size={17} />}
          </button>
        </div>
      </header>

      <div className="telemetry-summary" aria-label="Latest battery bus values">
        <span>电量 BATTERY <strong>{formatPercent(latest?.batteryPercent ?? undefined)}</strong></span>
        <span>母线电压 BUS VOLTAGE <strong>{formatMeasurement(latest?.busVoltage ?? undefined, 1, "V")}</strong></span>
        <span>母线电流 BUS CURRENT <strong>{formatMeasurement(latest?.busCurrent ?? undefined, 1, "A")}</strong></span>
        <span>扭矩来源 TORQUE SOURCE <strong>{hasActual ? "ACTUAL" : "ESTIMATED (EST)"}</strong></span>
      </div>

      <div className="telemetry-grid">
        <div data-mobile-active={activeChart === "angle"}>
          <TelemetryChart
            cursorMs={cursorMs}
            endMs={endMs}
            id="angle"
            onCursorChange={setCursorMs}
            points={buffer.points}
            series={angleSeries}
            startMs={startMs}
            title="Joint angle"
            unit="rad"
          />
        </div>
        <div data-mobile-active={activeChart === "torque"}>
          <TelemetryChart
            cursorMs={cursorMs}
            endMs={endMs}
            id="torque"
            onCursorChange={setCursorMs}
            points={buffer.points}
            series={torqueSeries}
            startMs={startMs}
            title={`${JOINTS[selectedJoint].short} torque · ${hasActual ? "ACT" : "EST"}`}
            unit="Nm"
          />
        </div>
        <div data-mobile-active={activeChart === "temperature"}>
          <TelemetryChart
            cursorMs={cursorMs}
            endMs={endMs}
            id="temperature"
            onCursorChange={setCursorMs}
            points={buffer.points}
            series={temperatureSeries}
            startMs={startMs}
            title="Motor temperature"
            unit="°C"
          />
        </div>
        <div data-mobile-active={activeChart === "battery"}>
          <TelemetryChart
            cursorMs={cursorMs}
            domain={[0, 100]}
            endMs={endMs}
            id="battery"
            onCursorChange={setCursorMs}
            points={buffer.points}
            series={batterySeries}
            startMs={startMs}
            title="Battery"
            unit="%"
          />
        </div>
      </div>
    </section>
  );
}
