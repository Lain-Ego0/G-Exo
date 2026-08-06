import "@fontsource/barlow-condensed/latin-600.css";
import "@fontsource/barlow-condensed/latin-700.css";
import "@fontsource/ibm-plex-mono/latin-400.css";
import "@fontsource/ibm-plex-mono/latin-600.css";
import "@fontsource/noto-sans-sc/latin-400.css";
import "@fontsource/noto-sans-sc/latin-600.css";
import "@fontsource/noto-sans-sc/chinese-simplified-400.css";
import "@fontsource/noto-sans-sc/chinese-simplified-600.css";
import "./styles/global.css";

import { StrictMode, useState } from "react";
import { createRoot } from "react-dom/client";

import App from "./App";
import { LangContext, type Lang } from "./i18n";

function Root() {
  const [lang, setLang] = useState<Lang>("zh");
  return (
    <StrictMode>
      <LangContext.Provider value={{ lang, toggle: () => setLang((v) => (v === "zh" ? "en" : "zh")) }}>
        <App />
      </LangContext.Provider>
    </StrictMode>
  );
}

createRoot(document.getElementById("root")!).render(<Root />);
