"use client";

import { createContext, useContext, useEffect, useRef, useState } from "react";

export type ProductWorkScope = { scope: string; setScope: (value: string) => void };
export const ProductWorkScopeContext = createContext<ProductWorkScope | null>(null);

export function useProductWorkScope() {
  const shared = useContext(ProductWorkScopeContext);
  const [local, setLocal] = useState("all");
  return { scope: shared?.scope ?? local, setScope: shared?.setScope ?? setLocal, shared: shared !== null };
}

export function notifyProductWorkChanged(base: string) {
  if (typeof window !== "undefined") window.dispatchEvent(new CustomEvent("pdos:product-work-changed", { detail: { base } }));
}

/** Read updates never replace an open editor or an unresolved write. */
export function useProductWorkUpdates(base: string, load: () => Promise<unknown>, options: { paused?: boolean; onError: (failure: unknown) => void }) {
  const latest = useRef({ load, ...options });
  useEffect(() => { latest.current = { load, ...options }; });
  useEffect(() => {
    let active = true, reading = false;
    let scheduled: ReturnType<typeof setTimeout> | undefined;
    async function refresh() {
      if (!active || reading || latest.current.paused || document.visibilityState === "hidden") return;
      reading = true;
      try { await latest.current.load(); }
      catch (failure) { if (active) latest.current.onError(failure); }
      finally { reading = false; }
    }
    const change = (event: Event) => {
      if ((event as CustomEvent<{ base: string }>).detail?.base !== base) return;
      clearTimeout(scheduled); scheduled = setTimeout(() => void refresh(), 250);
    };
    const focus = () => void refresh();
    window.addEventListener("pdos:product-work-changed", change);
    window.addEventListener("focus", focus);
    document.addEventListener("visibilitychange", focus);
    const timer = setInterval(focus, 30_000);
    return () => { active = false; clearTimeout(scheduled); clearInterval(timer); window.removeEventListener("pdos:product-work-changed", change); window.removeEventListener("focus", focus); document.removeEventListener("visibilitychange", focus); };
  }, [base]);
}
