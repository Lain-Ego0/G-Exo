import { useRef, type MouseEvent, type ReactNode } from "react";

/**
 * SpotlightCard (React Bits style): radial glow follows the cursor.
 */
export function SpotlightCard({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  const ref = useRef<HTMLDivElement>(null);

  const onMove = (event: MouseEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    const rect = el.getBoundingClientRect();
    el.style.setProperty("--spot-x", `${event.clientX - rect.left}px`);
    el.style.setProperty("--spot-y", `${event.clientY - rect.top}px`);
  };

  return (
    <div ref={ref} className={`spotlight-card ${className ?? ""}`} onMouseMove={onMove}>
      {children}
    </div>
  );
}
