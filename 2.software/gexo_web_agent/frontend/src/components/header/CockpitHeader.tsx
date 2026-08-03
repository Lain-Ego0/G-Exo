import {
  Activity,
  AlertTriangle,
  Cable,
  CircleStop,
  Clock3,
  Cpu,
  RadioTower,
} from "lucide-react";

function RailItem({
  icon: Icon,
  label,
  value,
}: {
  icon: typeof Activity;
  label: string;
  value: string;
}) {
  return (
    <div className="rail-item" data-state="unavailable">
      <Icon aria-hidden="true" size={14} strokeWidth={1.8} />
      <span className="rail-label">{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

export function CockpitHeader() {
  return (
    <header className="cockpit-header">
      <div className="identity-block" aria-label="G-Exo Physical AI Cockpit">
        <span className="wordmark">G-EXO</span>
        <span className="product-label">PHYSICAL AI COCKPIT</span>
      </div>

      <div className="robot-safety-rail" aria-label="Robot safety status">
        <RailItem icon={Activity} label="MODE" value="DATA UNAVAILABLE" />
        <RailItem icon={RadioTower} label="MOTION" value="DATA UNAVAILABLE" />
        <RailItem icon={CircleStop} label="E-STOP" value="NOT CONNECTED" />
        <RailItem icon={AlertTriangle} label="FAULT" value="DATA UNAVAILABLE" />
        <RailItem icon={Cable} label="CAN" value="NOT CONNECTED" />
        <RailItem icon={Clock3} label="LAST UPDATE" value="--" />
      </div>

      <div className="connection-block" data-state="offline">
        <Cpu aria-hidden="true" size={18} strokeWidth={1.8} />
        <div>
          <strong>K3 NOT CONNECTED</strong>
          <span>TRANSPORT / DATA UNAVAILABLE</span>
        </div>
      </div>
    </header>
  );
}
