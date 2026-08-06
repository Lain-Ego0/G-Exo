import type { ReactNode } from "react";

/**
 * GradientText (React Bits style): animated gradient clipped to text.
 */
export function GradientText({
  children,
  className,
}: {
  children: ReactNode;
  className?: string;
}) {
  return <span className={`gradient-text ${className ?? ""}`}>{children}</span>;
}
