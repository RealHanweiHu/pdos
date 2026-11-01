"use client";

import { useCallback, useRef, useState } from "react";

/** A 202 acknowledges an input; the durable Run can still expose its old interrupt. */
export function useAnswerResume() {
  const [pending, setPending] = useState<Record<string, string>>({});
  const current = useRef<Record<string, string>>({});
  const accepted = useCallback((runId: string, inputIdentity: string) => {
    const next = { ...current.current, [runId]: inputIdentity };
    current.current = next; setPending(next);
  }, []);
  const observe = useCallback((runId: string, status: string, reverted: boolean, inputIdentity: string | null) => {
    const original = current.current[runId];
    if (!original || !reverted && status === "waiting_input" && original === inputIdentity) return false;
    const next = { ...current.current }; delete next[runId];
    current.current = next; setPending(next); return true;
  }, []);
  const waiting = useCallback((runId: string) => !!current.current[runId], []);
  const clear = useCallback(() => { current.current = {}; setPending({}); }, []);
  return { pending, accepted, observe, waiting, clear };
}
