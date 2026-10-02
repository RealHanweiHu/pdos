"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { AiIssueEventRuns } from "./ai-issue-event-runs";

type Item = { id: string; event: number; title: string; status: string; reason: string; current: boolean };
type Page = { items: Item[]; next: string | null };
function parse(value: unknown): Page {
  if (!isRecord(value) || !Array.isArray(value.items) || (value.next_before_id !== null && typeof value.next_before_id !== "string")) throw new Error("例外清单不完整，请刷新核对");
  return { next: value.next_before_id, items: value.items.map(row => {
    if (!isRecord(row) || typeof row.run_id !== "string" || typeof row.event_row_id !== "number" || !Number.isSafeInteger(row.event_row_id) || row.event_row_id < 1 || typeof row.source_title !== "string" || typeof row.status !== "string" || typeof row.sources_current !== "boolean") throw new Error("例外记录不完整，请刷新核对");
    const execution = isRecord(row.write_execution) ? row.write_execution : null;
    return { id: row.run_id, event: row.event_row_id, title: row.source_title, status: row.status, current: row.sources_current, reason: typeof execution?.reason_label === "string" ? execution.reason_label : row.status === "succeeded" ? "请核对原建议及办理条件。" : "本次运行未完成，请查看原回执及恢复条件。" };
  }) };
}

export function AiIssueAttention(props: { projectId: string; onIssueChanged?: (ids: string[]) => Promise<void> }) {
  return <Attention key={props.projectId} {...props} />;
}
function Attention({ projectId, onIssueChanged }: { projectId: string; onIssueChanged?: (ids: string[]) => Promise<void> }) {
  const [data, setData] = useState<Page | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [selected, setSelected] = useState<Item | null>(null);
  const active = useRef(true), pending = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function load(older = false) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(null);
    if (!older) setSelected(null);
    try {
      const query = new URLSearchParams({ attention: "true" });
      if (older && data?.next) query.set("before_id", data.next);
      const response = await fetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-event-runs?${query}`, { cache: "no-store" });
      const body: unknown = await responseBody(response).catch(() => null);
      if (!response.ok) {
        if (active.current && [401, 403, 404].includes(response.status)) { setData(null); setSelected(null); }
        throw new Error(isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "例外清单暂不可用，请稍后重试");
      }
      const page = parse(body);
      if (active.current) setData(current => older && current ? { ...page, items: [...current.items, ...page.items.filter(item => !current.items.some(old => old.id === item.id))] } : page);
    } catch (failure) { if (active.current) { if (!older) setData(null); setError(failure instanceof Error ? failure.message : "例外读取失败"); } }
    finally { pending.current = false; if (active.current) setBusy(false); }
  }
  async function changed(ids: string[]) { await onIssueChanged?.(ids); if (active.current) await load(); }
  return <details className="min-w-0 rounded-lg border p-2 sm:p-3" onToggle={event => { if (event.target === event.currentTarget && event.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer text-sm font-medium">需要核对的 AI 异常</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p className="leading-5 text-muted-foreground">集中查看本人发起事件和请求中尚待确认、证据不足或运行失败的最新记录。已办理和已不采纳的建议保留在原历史；自动完成不增加待办。</p>
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新待核对记录</Button>
      {busy && <p role="status">正在读取待核对记录…</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
      {data?.items.length === 0 && <p className="text-muted-foreground">当前没有需要核对的运行记录；这不代表所有来源已自动处理。</p>}
      {data?.items.map(item => <article key={item.id} className="min-w-0 space-y-2 border-t pt-3">
        <p className="break-words font-medium">{item.title} · {item.status === "succeeded" ? "待核对建议" : "运行未完成"}</p>
        <p className="break-words leading-5">{item.reason}</p>
        {!item.current && <p className="text-primary">来源已变化或不可核对，请先复核原记录。</p>}
        <Button size="sm" variant="outline" onClick={() => setSelected(item)}>查看与办理</Button>
        {selected?.id === item.id && <AiIssueEventRuns projectId={projectId} eventRowId={item.event} initialRunId={item.id} onIssueChanged={changed} />}
      </article>)}
      {data?.next && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>更早的待核对记录</Button>}
    </div>
  </details>;
}
