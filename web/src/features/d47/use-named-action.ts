"use client";
// D47: one preview → review → submit flow per panel; the prepared command is sent unchanged.
import { useCallback, useEffect, useRef, useState } from "react";
import type { ProjectApi } from "@/lib/project-plan-view";
import { previewCommand, submitPrepared, type NamedCommand, type PreparedCommand, type Tier } from "@/lib/named-command";

export function useNamedAction(api: ProjectApi) {
  const [prepared, setPrepared] = useState<PreparedCommand | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const alive = useRef(true), lock = useRef(false);
  useEffect(() => { alive.current = true; return () => { alive.current = false; }; }, []);
  const start = useCallback(async (build: () => NamedCommand | Promise<NamedCommand>, tier: Tier) => {
    if (lock.current) return;
    lock.current = true; setBusy(true); setError(""); setNotice("");
    try { const command = await build(); const value = await previewCommand(api, command, tier); if (alive.current) setPrepared(value); }
    catch (failure) { if (alive.current) setError((failure as Error).message); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }, [api]);
  const confirm = useCallback(async (subjectType: string, done: string, after?: () => Promise<unknown> | unknown) => {
    if (lock.current || !prepared) return;
    lock.current = true; setBusy(true); setError("");
    try { await submitPrepared(api, prepared, subjectType); if (!alive.current) return; setPrepared(null); setNotice(done); await after?.(); }
    catch (failure) { if (alive.current) setError((failure as Error).message); }
    finally { lock.current = false; if (alive.current) setBusy(false); }
  }, [api, prepared]);
  const cancel = useCallback(() => { setPrepared(null); setError(""); }, []);
  return { prepared, busy, error, notice, start, confirm, cancel, setError };
}
