import { Globe, MessageSquareText, ShieldCheck, Telescope } from "lucide-react";

import { FadeContent } from "../components/bits/FadeContent";
import { SpotlightCard } from "../components/bits/SpotlightCard";
import dict, { t, useLang } from "../i18n";

const FEATURE_ICONS = [MessageSquareText, ShieldCheck, Telescope, Globe] as const;

export function Features() {
  const { lang } = useLang();

  return (
    <section className="section" id="features">
      <FadeContent className="section-head">
        <p className="section-kicker">{t(dict.features.kicker, lang)}</p>
        <h2>{t(dict.features.title, lang)}</h2>
      </FadeContent>

      <div className="features-grid">
        {dict.features.cards.map((card, index) => {
          const Icon = FEATURE_ICONS[index];
          return (
            <FadeContent delay={index * 100} key={card.zh.title}>
              <SpotlightCard className="feature-card">
                <Icon aria-hidden="true" size={22} />
                <h3>{card[lang].title}</h3>
                <p>{card[lang].desc}</p>
              </SpotlightCard>
            </FadeContent>
          );
        })}
      </div>
    </section>
  );
}
