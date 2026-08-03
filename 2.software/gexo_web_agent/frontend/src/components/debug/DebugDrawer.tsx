import { Bug } from "lucide-react";

export function DebugDrawer() {
  return (
    <details className="debug-drawer">
      <summary><Bug aria-hidden="true" size={15} />Debug state</summary>
      <div className="debug-content">
        <span>RAW STATE</span>
        <pre>DATA UNAVAILABLE</pre>
      </div>
    </details>
  );
}
