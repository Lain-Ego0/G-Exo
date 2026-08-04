import { useInView } from "./useInView";

/**
 * BlurText (React Bits style): words sharpen from a blur with stagger.
 */
export function BlurText({
  text,
  className,
  delay = 90,
}: {
  text: string;
  className?: string;
  delay?: number;
}) {
  const [ref, inView] = useInView<HTMLSpanElement>(0.4);
  const words = text.split(" ");

  return (
    <span ref={ref} className={`blur-text ${className ?? ""}`} aria-label={text}>
      {words.map((word, index) => (
        <span
          aria-hidden="true"
          className="blur-text-word"
          data-visible={inView || undefined}
          style={{ transitionDelay: `${index * delay}ms` }}
          key={`${word}-${index}`}
        >
          {word}
          {index < words.length - 1 ? " " : ""}
        </span>
      ))}
    </span>
  );
}
