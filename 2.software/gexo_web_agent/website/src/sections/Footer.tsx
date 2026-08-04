import dict, { t, useLang } from "../i18n";

export function Footer() {
  const { lang } = useLang();

  return (
    <footer className="site-footer">
      <span className="brand-wordmark">G-EXO</span>
      <p>{t(dict.footer.line, lang)}</p>
      <small>{t(dict.footer.sub, lang)}</small>
    </footer>
  );
}
