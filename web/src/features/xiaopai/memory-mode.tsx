"use client";

import { useEffect, useRef, useState } from "react";
import { Brain } from "@phosphor-icons/react";
import styles from "./pai-conversation.module.css";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
type Mode = { version: "memory-session-mode/v1"; session_id: string; revision: number; memory_off: boolean; effect: string };
const EFFECT = "不读你以往的记录，也不留下这次对话的情景记录；团队备忘与审计照常。";

/** New conversation: the choice is sent once with the first message (P85 第 5 项). */
export function MemoryOffStart({ checked, onChange, disabled = false }: { checked: boolean; onChange: (value: boolean) => void; disabled?: boolean }) {
  return <details className={styles.objectPicker}>
    <summary title={checked ? "本会话不进记忆" : "记忆设置"}><Brain size={13} aria-hidden="true"/>{checked ? "不进记忆" : "记忆"}</summary>
    <div className={styles.objectOptions}>
      <label><input type="checkbox" checked={checked} disabled={disabled} onChange={event => onChange(event.target.checked)}/>本会话不进记忆</label>
      <p className="text-muted-foreground">{EFFECT}</p>
    </div>
  </details>;
}

/** Existing conversation: the owner's switch, a new server version per change. */
export function MemoryModeToggle({ api, root, sessionId, disabled = false }: { api: Api; root: string; sessionId: string; disabled?: boolean }) {
  const resource = `${root.replace(/agent-runs$/, "agent-sessions")}/${sessionId}/memory-mode`;
  const [state, setState] = useState<{ resource: string; value?: Mode; error?: string }>({ resource });
  const [busy, setBusy] = useState(false);
  const [refresh, setRefresh] = useState(0);
  const [pendingOff, setPendingOff] = useState<boolean | null>(null);
  const original = useRef<{ expected_revision: number; request_key: string; memory_off: boolean } | null>(null);
  useEffect(() => {
    let live = true;
    void api<Mode>(resource).then(value => {
      if (!live) return;
      if (value?.version !== "memory-session-mode/v1" || value.session_id !== sessionId) setState({ resource, error: "记忆设置暂不可读。" });
      else setState({ resource, value });
    }).catch(() => { if (live) setState({ resource, error: "记忆设置暂不可读。" }); });
    return () => { live = false; };
  }, [api, resource, sessionId, refresh]);
  const value = state.resource === resource ? state.value : undefined;
  async function change(memoryOff: boolean) {
    if (!value || busy) return;
    setBusy(true);
    const request = original.current ?? { expected_revision: value.revision, request_key: crypto.randomUUID(), memory_off: memoryOff };
    original.current = request; setPendingOff(request.memory_off);
    try {
      const saved = await api<Mode>(resource, request);
      original.current = null; setPendingOff(null);
      setState({ resource, value: saved });
    } catch (failure) {
      const status = (failure as { status?: number }).status;
      if (status === 409 || status === 404 || status === 422 || status === 403) { original.current = null; setPendingOff(null); setRefresh(count => count + 1); }
      setState({ resource, value, error: status === 409 ? "记忆设置已变化，已重新读取。" : "记忆设置待核对，请重试。" });
    } finally { setBusy(false); }
  }
  if (!value) return state.error ? <p role="status" className={styles.lookupNote}>{state.error}</p> : null;
  return <details className={styles.objectPicker}>
    <summary title={value.memory_off ? "本会话不进记忆" : "记忆设置"}><Brain size={13} aria-hidden="true"/>{value.memory_off ? "不进记忆" : "记忆"}</summary>
    <div className={styles.objectOptions}>
      <label><input type="checkbox" checked={pendingOff ?? value.memory_off} disabled={disabled || busy} onChange={event => void change(event.target.checked)}/>本会话不进记忆</label>
      <p className="text-muted-foreground">{value.memory_off ? value.effect : EFFECT}</p>
      {state.error && <p role="alert">{state.error}</p>}
    </div>
  </details>;
}
