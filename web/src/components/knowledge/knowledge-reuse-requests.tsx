"use client";

import { useState, type ReactNode } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Entry = { id: string; state: string; created_at: string; input_matches_current: boolean; source_actor_name: string | null };
type Cursor = { before_created_at: string; before_id: string };
const labels: Record<string, string> = { pending: "等待准备", running: "处理中", ready: "已准备推荐", empty: "没有匹配", stale: "原输入或权限已变化", failed: "处理失败", uncertain: "调用回执不完整" };
export function KnowledgeReuseRequests({ projectId, contextKind, entityId, renderJob }: { projectId: string; contextKind: string; entityId: string; renderJob: (id: string) => ReactNode }) {
  const [entries, setEntries] = useState<Entry[] | null>(null), [next, setNext] = useState<Cursor | null>(null);
  const [opened, setOpened] = useState<Entry[]>([]), [busy, setBusy] = useState(false), [error, setError] = useState("");
  async function load(cursor?: Cursor) {
    if (busy) return;
    setBusy(true); setError("");
    try {
      const query = new URLSearchParams({ context_kind: contextKind, context_entity_id: entityId, ...(cursor ?? {}) });
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/knowledge-prepared/requests?${query}`, { cache: "no-store", credentials: "same-origin" });
      const value = await responseBody(response);
      if (!response.ok || !isRecord(value) || !Array.isArray(value.items) || !value.items.every(item => isRecord(item) && ["id", "state", "created_at"].every(key => typeof item[key] === "string") && typeof item.input_matches_current === "boolean" && (item.source_actor_name === null || typeof item.source_actor_name === "string")) || !(value.next === null || isRecord(value.next) && typeof value.next.before_created_at === "string" && typeof value.next.before_id === "string")) throw new Error("历史准备请求暂不可读取，请重新加载");
      const batch = value.items as Entry[];
      setEntries(old => cursor ? [...(old ?? []), ...batch] : batch); setNext(value.next as Cursor | null);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  return <details className="rounded-lg border p-3 text-xs" onToggle={e => { if (e.target === e.currentTarget && e.currentTarget.open && !entries && !busy) void load(); }}>
    <summary className="cursor-pointer font-medium">查看这项工作的历史准备请求</summary>
    <div className="mt-3 space-y-3">
      <p className="text-muted-foreground">按触发时间列出本人收到的准备请求。输入一致仅表示业务检索文本一致，查看或恢复时仍会检查当前权限、办理状态及知识来源。已打开的记录和表单会保留，收起不会清除输入。</p>
      <Button type="button" size="sm" variant="ghost" disabled={busy} onClick={() => void load()}>刷新请求列表</Button>
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      {entries?.length === 0 ? <p>这项工作当前没有向本人发起的准备请求。</p> : null}
      <ol className="space-y-2">{entries?.map(item => <li className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-2" key={item.id}><div><p>{item.created_at} · {item.source_actor_name || "系统"}</p><p>{labels[item.state] ?? item.state} · {item.input_matches_current ? "与当前输入一致" : "历史输入"}</p></div><Button type="button" size="sm" variant="outline" disabled={opened.some(entry => entry.id === item.id)} onClick={() => setOpened(old => [...old, item])}>{opened.some(entry => entry.id === item.id) ? "已在下方打开" : "查看请求与原回执"}</Button></li>)}</ol>
      {next ? <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(next)}>加载更早请求</Button> : null}
      {opened.map(item => <details key={item.id} open className="space-y-2 border-t pt-3"><summary className="cursor-pointer">准备请求 · {item.created_at}</summary>{renderJob(item.id)}</details>)}
    </div>
  </details>;
}
