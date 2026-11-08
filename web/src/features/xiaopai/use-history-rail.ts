"use client";

import { useCallback, useEffect, useState } from "react";

/** The session rail shows beside the conversation only on a wide full page. */
export const HISTORY_RAIL_QUERY = "(min-width: 1000px)";

function wide() {
  return typeof window !== "undefined" && typeof window.matchMedia === "function"
    && window.matchMedia(HISTORY_RAIL_QUERY).matches;
}

/**
 * D42: follow the viewport and the full-page state instead of reading the width once.
 * Crossing the breakpoint or switching panel/full page resets the default; a manual
 * toggle holds until the next change.
 */
export function useHistoryRail(fullPage: boolean) {
  const [open, setOpen] = useState(() => fullPage && wide());
  const [shownFor, setShownFor] = useState(fullPage);
  if (shownFor !== fullPage) {
    setShownFor(fullPage);
    setOpen(fullPage && wide());
  }
  useEffect(() => {
    if (typeof window === "undefined" || typeof window.matchMedia !== "function") return;
    const media = window.matchMedia(HISTORY_RAIL_QUERY);
    const follow = () => setOpen(fullPage && media.matches);
    media.addEventListener("change", follow);
    return () => media.removeEventListener("change", follow);
  }, [fullPage]);
  const reset = useCallback(() => setOpen(fullPage && wide()), [fullPage]);
  return [open, setOpen, reset] as const;
}
