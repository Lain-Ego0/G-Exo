import { useState } from "react";
import { BatteryMedium, Pause, Thermometer, Waves, Zap } from "lucide-react";

const CHARTS = [
  { id: "angle", label: "Joint angle", unit: "rad", icon: Waves },
  { id: "torque", label: "Torque", unit: "Nm", icon: Zap },
  { id: "temperature", label: "Temperature", unit: "°C", icon: Thermometer },
  { id: "battery", label: "Battery / Bus", unit: "% / V / A", icon: BatteryMedium },
] as const;

type ChartId = (typeof CHARTS)[number]["id"];

function EmptyChart({ chart }: { chart: (typeof CHARTS)[number] }) {
  const Icon = chart.icon;
  return (
    <section className="telemetry-chart" data-chart={chart.id} aria-labelledby={`chart-${chart.id}`}>
      <header>
        <div><Icon aria-hidden="true" size={16} /><h3 id={`chart-${chart.id}`}>{chart.label}</h3></div>
        <span>{chart.unit}</span>
      </header>
      <div className="chart-field">
        <div className="chart-grid" aria-hidden="true">
          <i /><i /><i /><i />
        </div>
        <p>WAITING FOR CONTROLLER TELEMETRY</p>
        <span className="chart-time-start">-60 s</span>
        <span className="chart-time-end">NOW</span>
      </div>
    </section>
  );
}

export function TelemetryDock() {
  const [activeChart, setActiveChart] = useState<ChartId>("angle");

  return (
    <section className="telemetry-dock" aria-labelledby="telemetry-title">
      <header className="telemetry-toolbar">
        <div>
          <span className="section-index">LIVE BUFFER / 60 SECONDS</span>
          <h2 id="telemetry-title">TELEMETRY</h2>
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
          <div className="range-segment" aria-label="Telemetry range">
            <button disabled type="button">15</button>
            <button disabled type="button">30</button>
            <button aria-pressed="true" disabled type="button">60</button>
          </div>
          <button className="icon-button" aria-label="Pause telemetry" disabled title="Pause telemetry" type="button">
            <Pause aria-hidden="true" size={17} />
          </button>
        </div>
      </header>
      <div className="telemetry-grid">
        {CHARTS.map((chart) => (
          <div data-mobile-active={activeChart === chart.id} key={chart.id}>
            <EmptyChart chart={chart} />
          </div>
        ))}
      </div>
    </section>
  );
}
