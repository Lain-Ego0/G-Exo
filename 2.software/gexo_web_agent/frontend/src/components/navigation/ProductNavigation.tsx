import { Bot, CircleDot } from "lucide-react";

export type ProductView = "ring" | "cockpit";

export function ProductNavigation({
  activeView,
  onNavigate,
}: {
  activeView: ProductView;
  onNavigate: (view: ProductView) => void;
}) {
  return (
    <nav className="product-navigation" aria-label="Product navigation">
      <div className="product-navigation-brand">
        <span className="product-navigation-kicker">G-EXO SYSTEM</span>
        <span className="product-navigation-title">INTEGRATED CONSOLE</span>
      </div>
      <div className="product-navigation-tabs" role="tablist" aria-label="Product views">
        <button
          className="product-navigation-tab"
          data-active={activeView === "ring"}
          onClick={() => onNavigate("ring")}
          role="tab"
          aria-selected={activeView === "ring"}
          type="button"
        >
          <CircleDot aria-hidden="true" size={16} strokeWidth={1.8} />
          <span>Alloop Ring</span>
        </button>
        <button
          className="product-navigation-tab"
          data-active={activeView === "cockpit"}
          onClick={() => onNavigate("cockpit")}
          role="tab"
          aria-selected={activeView === "cockpit"}
          type="button"
        >
          <Bot aria-hidden="true" size={16} strokeWidth={1.8} />
          <span>G-Exo Cockpit</span>
        </button>
      </div>
    </nav>
  );
}
