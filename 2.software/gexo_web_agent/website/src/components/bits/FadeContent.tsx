import type { ReactNode } from "react";
import { useInView } from "./useInView";

/**
 * FadeContent (React Bits style): fades + rises into view on scroll.
 */
export function FadeContent({
  children,
  className,
  delay = 0,
  y = 24,
}: {
  children: ReactNode;
  className?: string;
  delay?: number;
  y?: number;
}) {
  const [ref, inView] = useInView<HTMLDivElement>(0.15);

  return (
    <div
      ref={ref}
      className={`fade-content ${className ?? ""}`}
      data-visible={inView || undefined}
      style={{ transitionDelay: `${delay}ms`, ["--fade-y" as string]: `${y}px` }}
    >
      {children}
    </div>
  );
}
