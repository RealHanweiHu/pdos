"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { IntakeCompensationSummary, IssueIntakeCompensations } from "./issue-intake-compensations";

type Row = Record<string, unknown>;
const statuses: Record<string, string> = { unassigned: "尚未安排任务", result_missing: "待登记办理结果", recheck: "需要重新核对", follow_up: "仍有后续处理", recorded: "已有当前核对结果" };
function obj(value: unknown): Row { if (!isRecord(value)) throw new Error("补偿汇总资料不完整"); return value; }
function rows(value: unknown): Row[] { if (!Array.isArray(value)) throw new Error("补偿清单不完整"); return value.map(obj); }
function text(value: unknown): string { return value == null ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
export function IssueIntakeBatchProgress({ projectId, batchId }: { projectId: string; batchId: string }) {
  const [data, setData] = useState<Row | null>(null), [items, setItems] = useState<Row[]>([]), [next, setNext] = useState<Row | null>(null), [filter, setFilter] = useState("all");
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load(more = false) {
    setBusy(true); setError(null);
    try {
      const query = new URLSearchParams(); if (more && next) for (const [key, value] of Object.entries(next)) query.set(key, text(value));
      const response = await fetch(`/api/projects/${projectId}/issue-intake-sources/batches/${batchId}/progress${query.size ? `?${query}` : ""}`, { cache: "no-store" }), value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "补偿汇总暂不可用，请稍后刷新");
      const result = obj(value), entries = rows(result.items);
      setItems(old => more ? [...old, ...entries.filter(item => !old.some(prior => obj(prior.source).id === obj(item.source).id && obj(prior.issue).id === obj(item.issue).id))] : entries);
      setData(result); setNext(isRecord(result.next) ? result.next : null);
    } catch (e) { setError(e instanceof Error ? e.message : "读取补偿汇总失败"); } finally { setBusy(false); }
  }
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer font-medium">查看本批业务补偿进展与待办缺口</summary>
    <div className="mt-3 space-y-3 text-xs">
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新本批实际进展</Button>
      {data && <><p>{text(data.scope_note)}</p><p>本批范围共 {text(data.scope_total)} 项来源与问题关系：已有任务 {text(data.assigned_total)} 项，尚未安排 {text(data.unassigned_total)} 项。</p><p className="text-muted-foreground">{text(data.completion_note)}</p><p>已读 {items.length} 项，各页按读取时实际状态展示。最近读取：{text(data.read_at)}；办理后请刷新。</p>
        <label>筛选已读条目<select className="ml-2 rounded-md border bg-background p-2" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部已读（{items.length}）</option>{Object.entries(statuses).map(([key, label]) => <option key={key} value={key}>{label}（{items.filter(item => item.status === key).length}）</option>)}</select></label>
      </>}
      {items.filter(item => filter === "all" || item.status === filter).map(item => {
        const source = obj(item.source), issue = obj(item.issue), state = obj(item.current_source), result = isRecord(item.result) ? item.result : null, binding = isRecord(item.binding) ? item.binding : null;
        return <article key={`${text(source.id)}:${text(issue.id)}`} className="space-y-2 rounded-md border p-3">
          <p className="font-medium">{statuses[text(item.status)] ?? text(item.status)} · {text(issue.title)}</p>
          <p>原资料 {text(obj(source.source_snapshot).filename)} · {text(source.locator)} · 本批来源版本 {text(item.batch_source_revision)} / 当前 {text(state.revision)}</p>
          {state.revision !== item.batch_source_revision && <p className="text-destructive">此来源在本批之后另有纠错，处理时须核对最新影响和新关联问题。</p>}
          {Array.isArray(item.reasons) && item.reasons.map((reason, index) => <p key={index} className={item.status === "recheck" ? "text-destructive" : "text-muted-foreground"}>{text(reason)}</p>)}
          <a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${text(issue.id)}`}>进入原问题</a>
          {result && <div className="space-y-1 rounded-md bg-muted/40 p-2"><p>最近办理：第 {text(result.revision)} 次 · {text(result.actor_name)} · {text(result.created_at)}</p><p className="whitespace-pre-wrap">结果：{text(result.summary)}<br/>验收回应：{text(result.criteria_response)}<br/>剩余影响及处理：{text(result.remaining)}</p></div>}
          {binding && <IntakeCompensationSummary value={binding}/>}
          {(!binding || Number(binding.binding_count) > 1) && <div className="space-y-2"><p>{binding ? `此来源与问题共有 ${text(binding.binding_count)} 次任务安排，旧任务与结果保留，可展开查看。` : "可按来源当前纠错版本安排实际任务；请核对该来源的全部相关问题。"}</p><IssueIntakeCompensations projectId={projectId} sourceIds={[text(source.id)]}/></div>}
        </article>;
      })}
      {data && !items.filter(item => filter === "all" || item.status === filter).length && <p>已读取范围中没有此类条目。</p>}
      {next && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>继续读取本批剩余条目</Button>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
