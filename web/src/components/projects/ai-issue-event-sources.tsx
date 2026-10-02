"use client";

import { useEffect, useRef, useState } from "react";
import { AiIssueAttention } from "./ai-issue-attention";
import { AiIssueScope } from "./ai-issue-scope";
import { AiIssueTrialProtocols } from "./ai-issue-trial-protocols";
import { AiIssueTrialObservations } from "./ai-issue-trial-observations";
import { AiIssueEventRuns } from "./ai-issue-event-runs";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

const statuses: Record<string, string> = { current: "来源已核对", changed: "来源已有变化", unavailable: "来源暂不可核对" };
const issueStatuses: Record<string, string> = { open: "待分析", analysis: "分析中", action: "行动中", verification: "待验证", closed: "已关闭" };
const eventTypes: Record<string, string> = { TEST_FAILED: "测试失败", NPI_RECORD_CHANGED: "物料异常核对" };
function text(value: unknown): string { if (typeof value !== "string") throw new Error("异常来源资料不完整，请刷新重试"); return value; }
function positive(value: unknown): number { if (typeof value !== "number" || !Number.isSafeInteger(value) || value < 1) throw new Error("来源分页资料不完整，请刷新重试"); return value; }
function href(value: unknown): string | null {
  if (value === null) return null;
  const path = text(value);
  if (!path.startsWith("/") || path.startsWith("//") || path.includes("\\")) return null;
  try { return new URL(path, "https://pdos.invalid").origin === "https://pdos.invalid" ? path : null; } catch { return null; }
}
function parse(value: unknown) {
  if (!isRecord(value) || !Array.isArray(value.items)) throw new Error("异常来源清单不完整，请刷新重试");
  return { notice: text(value.notice), next: value.next_before === null ? null : positive(value.next_before), items: value.items.map(row => {
    if (!isRecord(row) || !Array.isArray(row.summary) || (row.existing_issue !== null && !isRecord(row.existing_issue))) throw new Error("异常来源记录不完整，请刷新重试");
    const kind = text(row.source_kind), status = text(row.source_status);
    if (!["test_failure", "material_exception"].includes(kind) || !statuses[status]) throw new Error("异常来源类别不完整，请刷新重试");
    return { id: positive(row.event_row_id), title: text(row.title), event: text(row.event_type), time: text(row.event_at), kind, status, reason: text(row.reason), sourceHref: href(row.source_href), summary: row.summary.map(item => { if (!isRecord(item)) throw new Error("来源要点不完整"); return { label: text(item.label), value: text(item.value) }; }), issue: row.existing_issue === null ? null : { id: text(row.existing_issue.id), title: text(row.existing_issue.title), status: text(row.existing_issue.status), href: href(row.existing_issue.href) } };
  }) };
}
type Page = ReturnType<typeof parse>;
class ReadError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(path: string) {
  const response = await fetch(path, { cache: "no-store" });
  const body: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new ReadError(isRecord(body) && typeof body.detail === "string" ? body.detail : isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string" ? body.detail.message : "异常来源暂不可用，请稍后重试", response.status);
  return parse(body);
}

export function AiIssueEventSources(props: { projectId: string; onIssueChanged?: (withdrawnIssueIds: string[]) => Promise<void> }) { return <Sources key={props.projectId} {...props} />; }
function Sources({ projectId, onIssueChanged }: { projectId: string; onIssueChanged?: (withdrawnIssueIds: string[]) => Promise<void> }) {
  const [withdrawnIssueIds, setWithdrawnIssueIds] = useState<string[]>([]);
  async function issueChanged(ids: string[]) {
    if (active.current) setWithdrawnIssueIds(current => [...new Set([...current, ...ids])]);
    await onIssueChanged?.(ids);
  }
  const [data, setData] = useState<Page | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const active = useRef(true), pending = useRef(false);
  useEffect(() => { active.current = true; return () => { active.current = false; }; }, []);
  async function load(older = false) {
    if (pending.current) return;
    pending.current = true; setBusy(true); setError(null);
    try {
      const page = await request(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-event-sources?limit=20${older && data?.next ? `&before=${data.next}` : ""}`);
      if (active.current) setData(previous => older && previous ? { ...page, items: [...previous.items, ...page.items.filter(row => !previous.items.some(old => old.id === row.id))] } : page);
    } catch (failure) {
      if (active.current) { setError(failure instanceof Error ? failure.message : "异常来源读取失败"); if (!older || (failure instanceof ReadError && [401, 403].includes(failure.status))) setData(null); }
    } finally { pending.current = false; if (active.current) setBusy(false); }
  }
  return <details className="min-w-0 rounded-lg border bg-background p-2 sm:p-3" onToggle={event => { if (event.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer text-sm font-medium">异常来源与已有问题</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs leading-5 text-muted-foreground">核对测试失败和物料异常，沿已有问题继续办理，避免重复建单。</p>
      <AiIssueAttention projectId={projectId} onIssueChanged={issueChanged} />
      <AiIssueScope projectId={projectId} />
      <AiIssueTrialProtocols projectId={projectId} />
      <AiIssueTrialObservations projectId={projectId} />
      <Button size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新异常来源</Button>
      {busy && <p role="status" className="text-xs text-muted-foreground">正在核对来源…</p>}
      {error && <p role="alert" className="text-xs text-destructive">{error}</p>}
      {data?.notice && <p className="text-xs leading-5 text-muted-foreground">{data.notice}</p>}
      {data?.items.length === 0 && <p className="text-xs text-muted-foreground">暂无可回查的异常来源。</p>}
      {data?.items.map(item => <article key={item.id} className="min-w-0 space-y-2 rounded-lg border p-2 sm:p-3">
        <div className="flex flex-wrap items-start justify-between gap-2"><h4 className="min-w-0 break-words text-sm font-medium">{item.title}</h4><span className={`text-xs ${item.status === "current" ? "text-muted-foreground" : "text-primary"}`}>{statuses[item.status]}</span></div>
        <p className="text-xs text-muted-foreground">{eventTypes[item.event] ?? (item.kind === "test_failure" ? "测试失败事件" : "物料异常事件")} · <time dateTime={item.time}>{new Date(item.time).toLocaleString("zh-CN")}</time></p>
        <p className="whitespace-pre-wrap break-words text-xs leading-5">{item.reason}</p>
        {item.summary.length > 0 && <details><summary className="cursor-pointer text-xs text-muted-foreground">来源要点</summary><dl className="mt-2 grid gap-2 text-xs sm:grid-cols-2">{item.summary.map((point, index) => <div key={index} className="min-w-0"><dt className="text-muted-foreground">{point.label}</dt><dd className="mt-1 whitespace-pre-wrap break-words">{point.value}</dd></div>)}</dl></details>}
        <div className="flex flex-wrap gap-x-4 gap-y-2 text-xs">{item.sourceHref && <a className="text-primary underline underline-offset-2" href={item.sourceHref}>查看来源记录</a>}{item.issue?.href && <a className="text-primary underline underline-offset-2" href={item.issue.href}>{withdrawnIssueIds.includes(item.issue.id) ? "查看已撤回问题历史：" : "继续办理已有问题："}{item.issue.title}</a>}</div>
        {item.issue ? <p className="text-xs text-muted-foreground">{withdrawnIssueIds.includes(item.issue.id) ? "原问题已撤回，不可继续办理" : `已有问题 · ${issueStatuses[item.issue.status] ?? "状态待核对"}`}</p> : <p className="text-xs text-muted-foreground">尚未关联已有问题，请先核对来源。</p>}
        <AiIssueEventRuns projectId={projectId} eventRowId={item.id} onIssueChanged={issueChanged} withdrawnIssueIds={withdrawnIssueIds} />
      </article>)}
      {data?.next && <Button size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>更早的异常来源</Button>}
    </div>
  </details>;
}
