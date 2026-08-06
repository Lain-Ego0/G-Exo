import { FadeContent } from "../components/bits/FadeContent";
import { TiltedCard } from "../components/bits/TiltedCard";
import dict, { t, useLang } from "../i18n";

const JOINTS = [
  { id: "rh", label: "RH", style: { top: "27%", left: "17%" } },
  { id: "lh", label: "LH", style: { top: "27%", left: "68%" } },
  { id: "rk", label: "RK", style: { top: "70%", left: "17%" } },
  { id: "lk", label: "LK", style: { top: "70%", left: "68%" } },
] as const;

export function Specs() {
  const { lang } = useLang();

  return (
    <section className="section specs-section" id="specs">
      <FadeContent className="section-head">
        <p className="section-kicker">{t(dict.specs.kicker, lang)}</p>
        <h2>{t(dict.specs.title, lang)}</h2>
      </FadeContent>

      <div className="specs-layout">
        <FadeContent>
          <TiltedCard className="specs-figure">
            <img alt="G-EXO exoskeleton" src="/gexo-exoskeleton.png" />
            {JOINTS.map((joint) => (
              <span className="specs-joint" data-joint={joint.id} key={joint.id} style={joint.style}>
                <i />
                {joint.label}
              </span>
            ))}
            <small>{t(dict.specs.caption, lang)}</small>
          </TiltedCard>
        </FadeContent>

        <div className="specs-table">
          {dict.specs.rows.map((row, index) => (
            <FadeContent delay={index * 80} key={row.zh[0]}>
              <div className="specs-row">
                <span>{row[lang][0]}</span>
                <strong>{row[lang][1]}</strong>
              </div>
            </FadeContent>
          ))}
        </div>
      </div>
    </section>
  );
}
