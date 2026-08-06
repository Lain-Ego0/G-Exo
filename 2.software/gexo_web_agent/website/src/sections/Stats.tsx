import { CountUp } from "../components/bits/CountUp";
import { FadeContent } from "../components/bits/FadeContent";
import dict, { useLang } from "../i18n";

export function Stats() {
  const { lang } = useLang();

  return (
    <section className="stats" id="stats">
      {dict.stats.items.map((item, index) => (
        <FadeContent delay={index * 90} key={item.zh}>
          <div className="stat-cell">
            <strong>
              <CountUp prefix={"prefix" in item ? (item as { prefix?: string }).prefix ?? "" : ""} suffix={item.suffix} to={item.value} />
            </strong>
            <span>{item[lang]}</span>
          </div>
        </FadeContent>
      ))}
    </section>
  );
}
