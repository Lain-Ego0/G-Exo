import { Languages, Menu, X } from "lucide-react";
import { useState } from "react";

import dict, { t, useLang } from "../i18n";

const COCKPIT_URL = (import.meta.env.VITE_COCKPIT_URL as string | undefined) ?? "http://localhost:8000/cockpit";

export function Nav() {
  const { lang, toggle } = useLang();
  const [open, setOpen] = useState(false);

  const links = [
    { href: "#loop", label: t(dict.nav.loop, lang) },
    { href: "#features", label: t(dict.nav.features, lang) },
    { href: "#specs", label: t(dict.nav.specs, lang) },
    { href: "#cockpit", label: t(dict.nav.cockpit, lang) },
  ];

  return (
    <header className="site-nav">
      <a className="site-nav-brand" href="#top">
        <svg aria-hidden="true" className="brand-loop" viewBox="0 0 24 24">
          <path d="M12 4.5a7.5 7.5 0 1 1-7.3 5.6" fill="none" stroke="currentColor" strokeLinecap="round" strokeWidth="2.2" />
          <path d="M3.6 7.2l1.5 4 3.6-1.6z" fill="currentColor" />
        </svg>
        <span className="brand-wordmark">G-EXO</span>
      </a>

      <nav aria-label="Primary" className="site-nav-links" data-open={open || undefined}>
        {links.map((link) => (
          <a href={link.href} key={link.href} onClick={() => setOpen(false)}>
            {link.label}
          </a>
        ))}
        <a className="site-nav-cta mobile-only" href={COCKPIT_URL} rel="noreferrer" target="_blank">
          {t(dict.nav.launch, lang)}
        </a>
      </nav>

      <div className="site-nav-actions">
        <button aria-label="Switch language" className="icon-button" onClick={toggle} type="button">
          <Languages size={17} />
          <span>{lang === "zh" ? "EN" : "中"}</span>
        </button>
        <a className="site-nav-cta desktop-only" href={COCKPIT_URL} rel="noreferrer" target="_blank">
          {t(dict.nav.launch, lang)}
        </a>
        <button
          aria-expanded={open}
          aria-label="Menu"
          className="icon-button mobile-only"
          onClick={() => setOpen((v) => !v)}
          type="button"
        >
          {open ? <X size={19} /> : <Menu size={19} />}
        </button>
      </div>
    </header>
  );
}
