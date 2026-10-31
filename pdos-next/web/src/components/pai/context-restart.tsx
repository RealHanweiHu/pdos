"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { validContinuedSkillExclusions, validSkillSelections } from "@/lib/continued-skills";
import type { RequestedSkill } from "@/lib/run-start-intent";

type Request = {
  goal: string; idempotency_key: string; restart_from_run_id: string; context_revision: number;
  requested_skills?: RequestedSkill[]; excluded_continued_skills?: string[];
};
type Api = <T>(path: string, body?: unknown) => Promise<T>;
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
function restored(value: unknown, runId: string): Request | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const row = value as Record<string, unknown>;
  if (Object.keys(row).some(key => !["goal", "idempotency_key", "restart_from_run_id", "context_revision", "requested_skills", "excluded_continued_skills"].includes(key))
    || row.restart_from_run_id !== runId || typeof row.goal !== "string" || !row.goal.trim() || row.goal.length > 8000
    || typeof row.idempotency_key !== "string" || !uuid.test(row.idempotency_key)
    || !Number.isSafeInteger(row.context_revision) || Number(row.context_revision) < 1
    || row.requested_skills !== undefined && !validSkillSelections(row.requested_skills)
    || row.excluded_continued_skills !== undefined && !validContinuedSkillExclusions(row.excluded_continued_skills)) return null;
  return row as Request;
}

/** This button is the only UI path that starts fresh history with server state. */
export function ContextRestart({ api, root, runId, sessionId, revision, goal, principalId, requested, excluded, disabled, existing, onOpen, onUnavailable, onBusy }: {
  api: Api; root: string; runId: string; sessionId: string; revision: number; goal: string;
  principalId?: string; requested: RequestedSkill[]; excluded: string[]; disabled?: boolean;
  existing?: { run_id: string; session_id: string } | null;
  onOpen: (runId: string, sessionId?: string) => Promise<unknown>; onUnavailable?: () => void;
  onBusy?: (value: boolean) => void;
}) {
  const [pending, setPending] = useState<Request | null>(null), [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const original = useRef<Request | null>(null), lock = useRef(false), generation = useRef(0);
  const storage = principalId ? `pdos:context-restart:${principalId}:${root}:${runId}` : null;
  useEffect(() => {
    const counter = generation, own = ++counter.current;
    void Promise.resolve().then(() => {
      if (generation.current !== own || !storage) return;
      try {
        const saved = restored(JSON.parse(localStorage.getItem(storage) ?? "null"), runId);
        original.current = saved; setPending(saved);
      } catch { /* Server history remains authoritative. */ }
    });
    return () => { if (counter.current === own) counter.current++; };
  }, [storage, runId]);
  function remember(value: Request | null) {
    original.current = value; setPending(value);
    if (storage) try {
      if (value) localStorage.setItem(storage, JSON.stringify(value));
      else localStorage.removeItem(storage);
    } catch { /* Keep the exact original in memory. */ }
  }
  async function send() {
    if (disabled || lock.current) return;
    lock.current = true; setBusy(true); onBusy?.(true); setError("");
    const own = generation.current;
    const request = original.current ?? {
      goal: goal.trim(), idempotency_key: crypto.randomUUID(), restart_from_run_id: runId,
      context_revision: revision,
      ...(requested.length ? { requested_skills: requested } : {}),
      ...(excluded.length ? { excluded_continued_skills: excluded } : {}),
    };
    if (!restored(request, runId)) {
      lock.current = false; setBusy(false); onBusy?.(false); setError("请先填写要继续处理的问题。"); return;
    }
    remember(request);
    try {
      const result = await api<{ run_id: string; session_id: string; continued_from_id: string | null; restarted_from_id: string | null }>(root, request);
      if (own !== generation.current) return;
      if (!uuid.test(result.run_id) || !uuid.test(result.session_id) || result.session_id === sessionId
        || result.continued_from_id !== null || result.restarted_from_id !== runId) throw new Error("新会话受理结果尚未核对，请保留原请求。");
      await onOpen(result.run_id, result.session_id);
      remember(null);
    } catch (failure) {
      if (own !== generation.current) return;
      const value = failure as { status?: number; detail?: { reason?: string; reason_key?: string } };
      const skill = ["requested_skill_unavailable", "requested_skill_version_changed", "continued_skill_selection_invalid"].includes(value.detail?.reason ?? value.detail?.reason_key ?? "");
      if (value.status === 401 || value.status === 403 && !skill) {
        remember(null); onUnavailable?.();
      } else if ([409, 422].includes(value.status ?? 0) || skill) remember(null);
      setError(failure instanceof Error ? failure.message : "新会话受理结果待核对。");
    } finally { lock.current = false; if (own === generation.current) { setBusy(false); onBusy?.(false); } }
  }
  return <div className="space-y-2 rounded-lg border p-3 text-sm">
    <p>本轮上下文已满。可保留当前工作状态另开会话，重新核对来源后继续；旧对话保留在会话记录。</p>
    {error && <p role="alert" className="text-destructive">{error}</p>}
    {pending && <p role="status">恢复请求已保留，重试使用原目标与原携带版本。</p>}
    {existing && !pending ? <Button type="button" variant="outline" size="sm" disabled={disabled || busy} onClick={() => void onOpen(existing.run_id, existing.session_id).catch(failure => setError(failure instanceof Error ? failure.message : "新会话暂不可读。"))}>打开已保存的新会话</Button> : <Button type="button" variant="outline" size="sm" disabled={disabled || busy} onClick={() => void send()}>{busy ? "正在受理…" : pending ? "核对并重试原恢复请求" : "保留工作状态，另开会话继续"}</Button>}
  </div>;
}
