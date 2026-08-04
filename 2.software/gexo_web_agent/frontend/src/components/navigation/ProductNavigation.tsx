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
    <nav className="product-navigation" aria-label="产品导航">
      <div className="product-navigation-brand">
        <span className="product-navigation-kicker">G-EXO 系统 / G-EXO SYSTEM</span>
        <span className="product-navigation-title">集成控制台 / INTEGRATED CONSOLE</span>
      </div>
      <div className="product-navigation-tabs" role="tablist" aria-label="Product views">
        <button
          aria-label="戒指座舱"
          className="product-navigation-tab"
          data-active={activeView === "ring"}
          onClick={() => onNavigate("ring")}
          role="tab"
          aria-selected={activeView === "ring"}
          type="button"
        >
          <CircleDot aria-hidden="true" size={16} strokeWidth={1.8} />
          <span><b>戒指座舱</b><small aria-hidden="true">ALLOOP RING COCKPIT</small></span>
        </button>
        <button
          aria-label="外骨骼座舱"
          className="product-navigation-tab"
          data-active={activeView === "cockpit"}
          onClick={() => onNavigate("cockpit")}
          role="tab"
          aria-selected={activeView === "cockpit"}
          type="button"
        >
          <Bot aria-hidden="true" size={16} strokeWidth={1.8} />
          <span><b>外骨骼座舱</b><small aria-hidden="true">G-EXO COCKPIT</small></span>
        </button>
      </div>
    </nav>
  );
}
