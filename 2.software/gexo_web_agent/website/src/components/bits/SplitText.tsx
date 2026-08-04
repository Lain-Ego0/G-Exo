import type { CSSProperties } from "react";
import { useInView } from "./useInView";

/**
 * SplitText (React Bits style): reveals text char-by-char with a
 * staggered rise when it scrolls into view.
 */
export function SplitText({
  text,
  className,
  delay = 30,
  as: Tag = "span",
}: {
  text: string;
  className?: string;
  delay?: number;
  as?: "span" | "h1" | "h2" | "p";
}) {
  const [ref, inView] = useInView<HTMLSpanElement>(0.4);
  const chars = Array.from(text);

  return (
    <Tag ref={ref as never} className={`split-text ${className ?? ""}`} aria-label={text}>
      {chars.map((char, index) => (
        <span
          aria-hidden="true"
          className="split-text-char"
          data-visible={inView || undefined}
          style={{ transitionDelay: `${index * delay}ms` } as CSSProperties}
          key={`${char}-${index}`}
        >
          {char === " " ? " " : char}
        </span>
      ))}
    </Tag>
  );
}
