import { ArrowDown, ArrowRight } from "lucide-react";

import { Aurora } from "../components/bits/Aurora";
import { BlurText } from "../components/bits/BlurText";
import { GradientText } from "../components/bits/GradientText";
import { SplitText } from "../components/bits/SplitText";
import dict, { t, useLang } from "../i18n";

const COCKPIT_URL = (import.meta.env.VITE_COCKPIT_URL as string | undefined) ?? "http://localhost:8000/cockpit";

export function Hero() {
  const { lang } = useLang();

  return (
    <section className="hero" id="top">
      <Aurora />
      <div className="hero-inner">
        <p className="hero-kicker">
          <SplitText text={t(dict.hero.kicker, lang)} delay={45} />
        </p>
        <h1 className="hero-title">
          <SplitText as="span" text={t(dict.hero.titleA, lang)} delay={lang === "zh" ? 90 : 45} />
          <br />
          <GradientText>
            <SplitText as="span" text={t(dict.hero.titleB, lang)} delay={lang === "zh" ? 90 : 45} />
          </GradientText>
        </h1>
        <p className="hero-desc">
          <BlurText text={t(dict.hero.desc, lang)} delay={lang === "zh" ? 24 : 55} />
        </p>
        <div className="hero-actions">
          <a className="btn-primary" href={COCKPIT_URL} rel="noreferrer" target="_blank">
            {t(dict.hero.ctaPrimary, lang)}
            <ArrowRight aria-hidden="true" size={17} />
          </a>
          <a className="btn-ghost" href="#loop">
            {t(dict.hero.ctaSecondary, lang)}
          </a>
        </div>
      </div>
      <a aria-label={t(dict.hero.scroll, lang)} className="hero-scroll" href="#stats">
        <ArrowDown aria-hidden="true" size={16} />
      </a>
    </section>
  );
}
