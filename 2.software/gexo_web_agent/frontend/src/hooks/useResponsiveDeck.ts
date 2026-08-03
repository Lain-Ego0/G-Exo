import { useEffect, useState } from "react";

import type { StageId } from "../types/ui";

const MOBILE_QUERY = "(max-width: 767px)";

export function useResponsiveDeck(initialStage: StageId = "sense") {
  const [activeStage, setActiveStage] = useState<StageId>(initialStage);
  const [isMobile, setIsMobile] = useState(() => window.matchMedia(MOBILE_QUERY).matches);

  useEffect(() => {
    const media = window.matchMedia(MOBILE_QUERY);
    const update = () => setIsMobile(media.matches);
    update();
    media.addEventListener("change", update);
    return () => media.removeEventListener("change", update);
  }, []);

  return { activeStage, setActiveStage, isMobile };
}
