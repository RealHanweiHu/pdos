"use client";

import { useEffect, useState } from "react";
import styles from "./pai-conversation.module.css";

type Api = <T>(path: string, body?: unknown) => Promise<T>;
export type MemoryUsageValue = {
  version: "memory-usage/v1"; run_id: string; count: number; withheld: number; note: string;
  items: { run_id: string; session_id: string; as_of: string; goal: string; scope: { kind: string; title: string } }[];
  sessions: { session_id: string }[];
  notes?: { note_id: string; zone: string; deleted?: boolean; kind_label?: string; text?: string; changed_since?: boolean }[];
};
const ZONES: Record<string, string> = { constraints: "口径", aliases: "叫法", background: "背景", search: "检索到" };

/** "用到了 N 条记忆" under one finished answer (P85). Background only, never a source. */
export function MemoryUsage({ api, root, runId, status }: { api: Api; root: string; runId: string; status: string }) {
  const finished = status === "completed" || status === "partial";
  const [value, setValue] = useState<{ runId: string; usage: MemoryUsageValue | null } | null>(null);
  useEffect(() => {
    if (!finished) return;
    let live = true;
    void api<MemoryUsageValue>(`${root}/${runId}/memory-usage`).then(usage => {
      if (live) setValue({ runId, usage: usage?.version === "memory-usage/v1" && usage.run_id === runId ? usage : null });
    }).catch(() => { if (live) setValue({ runId, usage: null }); });
    return () => { live = false; };
  }, [api, root, runId, finished]);
  const usage = value?.runId === runId ? value.usage : null;
  if (!finished || !usage || usage.count < 1) return null;
  return <details className={styles.runDetails}>
    <summary>用到了 {usage.count} 条记忆</summary>
    <ul className="space-y-1 text-xs">
      {usage.items.map(item => <li key={item.run_id}><time dateTime={item.as_of}>{item.as_of.slice(0, 10)}</time> · {item.scope.title} · {item.goal}</li>)}
      {(usage.notes ?? []).map(item => <li key={item.note_id}>{item.deleted ? "一条记忆条目（已删除，正文已清除）" : <>{ZONES[item.zone] ?? item.kind_label} · {item.text}{item.changed_since ? "（之后已修改）" : ""}</>}</li>)}
      {usage.sessions.length > 0 && <li>读取了你另外 {usage.sessions.length} 个会话的记录</li>}
      {usage.withheld > 0 && <li>另有 {usage.withheld} 条当前不可读，已隐藏</li>}
    </ul>
    <p className={styles.lookupNote}>{usage.note}</p>
  </details>;
}
