import { Activity, BrainCircuit, Zap } from "lucide-react";

import { FadeContent } from "../components/bits/FadeContent";
import { SpotlightCard } from "../components/bits/SpotlightCard";
import dict, { t, useLang } from "../i18n";

const CARD_ICONS = [Activity, BrainCircuit, Zap] as const;

export function Loop() {
  const { lang } = useLang();

  return (
    <section className="section" id="loop">
      <FadeContent className="section-head">
        <p className="section-kicker">{t(dict.loop.kicker, lang)}</p>
        <h2>{t(dict.loop.title, lang)}</h2>
        <p className="section-desc">{t(dict.loop.desc, lang)}</p>
      </FadeContent>

      <div className="loop-flow" aria-hidden="true">
        <span data-stage="sense">SENSE</span>
        <i />
        <span data-stage="reason">REASON</span>
        <i />
        <span data-stage="act">ACT</span>
      </div>

      <div className="loop-grid">
        {dict.loop.cards.map((card, index) => {
          const Icon = CARD_ICONS[index];
          return (
            <FadeContent delay={index * 120} key={card.key}>
              <SpotlightCard className="loop-card" >
                <span className="loop-card-stage" data-stage={card.key}>0{index + 1}</span>
                <Icon aria-hidden="true" className="loop-card-icon" data-stage={card.key} size={26} />
                <h3>{card[lang].title}</h3>
                <p>{card[lang].desc}</p>
                <small>{card[lang].tag}</small>
              </SpotlightCard>
            </FadeContent>
          );
        })}
      </div>
    </section>
  );
}
