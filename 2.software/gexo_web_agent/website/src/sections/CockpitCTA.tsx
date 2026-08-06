import { ArrowUpRight } from "lucide-react";

import { FadeContent } from "../components/bits/FadeContent";
import { GradientText } from "../components/bits/GradientText";
import dict, { t, useLang } from "../i18n";

const COCKPIT_URL = (import.meta.env.VITE_COCKPIT_URL as string | undefined) ?? "http://localhost:8000/cockpit";

export function CockpitCTA() {
  const { lang } = useLang();

  return (
    <section className="section cta-section" id="cockpit">
      <FadeContent className="cta-panel">
        <p className="section-kicker">{t(dict.cta.kicker, lang)}</p>
        <h2>
          <GradientText>{t(dict.cta.title, lang)}</GradientText>
        </h2>
        <p className="section-desc">{t(dict.cta.desc, lang)}</p>
        <a className="btn-primary" href={COCKPIT_URL} rel="noreferrer" target="_blank">
          {t(dict.cta.button, lang)}
          <ArrowUpRight aria-hidden="true" size={17} />
        </a>
        <small>{t(dict.cta.note, lang)}</small>
      </FadeContent>
    </section>
  );
}
