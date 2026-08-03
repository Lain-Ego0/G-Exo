import { useMemo, type PointerEvent } from "react";

import { isFiniteNumber } from "../../lib/format";
import type { TelemetryPoint } from "../../hooks/useTelemetryBuffer";

const VIEWBOX_WIDTH = 600;
const VIEWBOX_HEIGHT = 144;
const PLOT_TOP = 8;
const PLOT_BOTTOM = 132;

export interface TelemetrySeries {
  id: string;
  label: string;
  color: string;
  value: (point: TelemetryPoint) => number | null;
  dashed?: boolean;
}

interface TelemetryChartProps {
  id: string;
  title: string;
  unit: string;
  points: TelemetryPoint[];
  series: TelemetrySeries[];
  startMs: number;
  endMs: number;
  cursorMs: number | null;
  onCursorChange: (timestamp: number | null) => void;
  domain?: [number, number];
  emptyLabel?: string;
}

function nearestPoint(points: TelemetryPoint[], timestamp: number): TelemetryPoint | null {
  let nearest: TelemetryPoint | null = null;
  let nearestDistance = Number.POSITIVE_INFINITY;
  for (const point of points) {
    if (point.gap) continue;
    const distance = Math.abs(point.timestamp - timestamp);
    if (distance < nearestDistance) {
      nearest = point;
      nearestDistance = distance;
    }
  }
  return nearest;
}

function seriesPath(
  points: TelemetryPoint[],
  series: TelemetrySeries,
  startMs: number,
  endMs: number,
  min: number,
  max: number,
): string {
  const duration = Math.max(1, endMs - startMs);
  const spread = Math.max(1e-6, max - min);
  let drawing = false;
  const commands: string[] = [];

  for (const point of points) {
    const value = series.value(point);
    if (point.gap || !isFiniteNumber(value)) {
      drawing = false;
      continue;
    }
    const x = ((point.timestamp - startMs) / duration) * VIEWBOX_WIDTH;
    const y = PLOT_BOTTOM - ((value - min) / spread) * (PLOT_BOTTOM - PLOT_TOP);
    commands.push(`${drawing ? "L" : "M"}${x.toFixed(2)},${y.toFixed(2)}`);
    drawing = true;
  }
  return commands.join(" ");
}

function displayValue(value: number | null, unit: string): string {
  if (!isFiniteNumber(value)) return "--";
  const digits = Math.abs(value) >= 100 ? 0 : Math.abs(value) >= 10 ? 1 : 2;
  return `${value.toFixed(digits)} ${unit}`;
}

export function TelemetryChart({
  id,
  title,
  unit,
  points,
  series,
  startMs,
  endMs,
  cursorMs,
  onCursorChange,
  domain,
  emptyLabel = "WAITING FOR CONTROLLER TELEMETRY",
}: TelemetryChartProps) {
  const visiblePoints = useMemo(
    () => points.filter((point) => point.timestamp >= startMs && point.timestamp <= endMs),
    [endMs, points, startMs],
  );

  const values = visiblePoints.flatMap((point) =>
    point.gap
      ? []
      : series
          .map((item) => item.value(point))
          .filter((value): value is number => isFiniteNumber(value)),
  );
  const hasData = values.length > 0;
  let min = domain?.[0] ?? Math.min(...values);
  let max = domain?.[1] ?? Math.max(...values);
  if (!hasData) {
    min = 0;
    max = 1;
  } else if (min === max) {
    const padding = Math.max(0.5, Math.abs(min) * 0.1);
    min -= padding;
    max += padding;
  } else if (!domain) {
    const padding = (max - min) * 0.08;
    min -= padding;
    max += padding;
  }

  const selectedPoint = nearestPoint(visiblePoints, cursorMs ?? endMs);
  const cursorX = cursorMs === null
    ? null
    : ((cursorMs - startMs) / Math.max(1, endMs - startMs)) * VIEWBOX_WIDTH;

  const handlePointerMove = (event: PointerEvent<SVGSVGElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    const ratio = Math.min(1, Math.max(0, (event.clientX - rect.left) / rect.width));
    onCursorChange(startMs + ratio * (endMs - startMs));
  };

  return (
    <section className="telemetry-chart" data-chart={id} aria-labelledby={`chart-${id}`}>
      <header>
        <div><h3 id={`chart-${id}`}>{title}</h3></div>
        <span>{unit}</span>
      </header>
      <div className="chart-legend" aria-label={`${title} values`}>
        {series.map((item) => (
          <span key={item.id}>
            <i style={{ backgroundColor: item.color }} />
            <small>{item.label}</small>
            <strong>{displayValue(selectedPoint ? item.value(selectedPoint) : null, unit)}</strong>
          </span>
        ))}
      </div>
      <div className="chart-field" data-has-data={hasData}>
        <svg
          aria-label={`${title} telemetry plot`}
          onPointerLeave={() => onCursorChange(null)}
          onPointerMove={handlePointerMove}
          preserveAspectRatio="none"
          role="img"
          viewBox={`0 0 ${VIEWBOX_WIDTH} ${VIEWBOX_HEIGHT}`}
        >
          <g className="chart-grid-lines" aria-hidden="true">
            {[0, 1, 2, 3, 4].map((line) => {
              const y = PLOT_TOP + ((PLOT_BOTTOM - PLOT_TOP) * line) / 4;
              return <line key={line} x1="0" x2={VIEWBOX_WIDTH} y1={y} y2={y} />;
            })}
          </g>
          {series.map((item) => (
            <path
              className="telemetry-path"
              d={seriesPath(visiblePoints, item, startMs, endMs, min, max)}
              data-dashed={item.dashed || undefined}
              key={item.id}
              stroke={item.color}
            />
          ))}
          {cursorX !== null && cursorX >= 0 && cursorX <= VIEWBOX_WIDTH ? (
            <line className="chart-cursor" x1={cursorX} x2={cursorX} y1={PLOT_TOP} y2={PLOT_BOTTOM} />
          ) : null}
        </svg>
        {!hasData ? <p className="chart-empty-label">{emptyLabel}</p> : null}
        <span className="chart-domain-max">{displayValue(max, unit)}</span>
        <span className="chart-domain-min">{displayValue(min, unit)}</span>
        <span className="chart-time-start">-{Math.round((endMs - startMs) / 1_000)} s</span>
        <span className="chart-time-end">NOW</span>
      </div>
    </section>
  );
}
