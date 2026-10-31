"use client";

import { useCallback, useEffect, useRef, useState } from "react";

const prefix = "pdos-next:pai-composer:";

function keyFor(principalId: string, scope: string, sessionId: string | null) {
  return `${prefix}${principalId}:${scope}:${sessionId ?? "new"}`;
}

export function writePaiComposerDraft(principalId: string, scope: string, sessionId: string | null, value: string) {
  const key = keyFor(principalId, scope, sessionId);
  try {
    if (value) sessionStorage.setItem(key, value);
    else sessionStorage.removeItem(key);
  } catch { /* The original request has its own stronger recovery journal. */ }
}

export function clearPaiComposerDrafts(principalId: string, scope?: string) {
  const root = `${prefix}${principalId}:${scope ? `${scope}:` : ""}`;
  try {
    const keys = Array.from({ length: sessionStorage.length }, (_, index) => sessionStorage.key(index))
      .filter((key): key is string => !!key && key.startsWith(root));
    for (const key of keys) sessionStorage.removeItem(key);
  } catch {
    /* Server-side permission revocation still clears the mounted private state. */
  }
}

export function useSessionDraft(principalId: string | undefined, scope: string, sessionId: string | null) {
  const key = principalId ? keyFor(principalId, scope, sessionId) : "";
  const keyRef = useRef(key);
  const [stored, setStored] = useState({ key: "", value: "" });
  useEffect(() => {
    keyRef.current = key;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      if (!key) { setStored({ key: "", value: "" }); return; }
      let value = "";
      try { value = sessionStorage.getItem(key) ?? ""; } catch { /* In-memory draft remains available. */ }
      setStored({ key, value });
    });
    return () => { active = false; };
  }, [key]);
  const setValue = useCallback((value: string) => {
    const current = keyRef.current;
    if (!current) return;
    setStored({ key: current, value });
    try {
      if (value) sessionStorage.setItem(current, value);
      else sessionStorage.removeItem(current);
    } catch { /* The original request has its own stronger recovery journal. */ }
  }, []);
  const clear = useCallback(() => setValue(""), [setValue]);
  return [stored.key === key ? stored.value : "", setValue, clear] as const;
}
