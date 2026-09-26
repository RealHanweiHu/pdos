"use client";

import { DecisionIntakeCorrectionBatches } from "./decision-intake-correction-batches";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { ProjectIntakeWorkResults } from "./project-intake-work-results";

type Row = Record<string, unknown>;
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const obj = (value: unknown): Row => isRecord(value) ? value : {};
const text = (value: unknown) => value == null ? "未提供" : String(value);
const labels: Record<string, string> = { arrangement_missing: "尚未安排初始化工作", result_missing: "已安排，待登记结果", recheck: "结果需重核", follow_up: "仍需后续处理", recorded: "本项已有有效核对结果" };
export function DecisionIntakeBatchProgress({ projectId, batchId }: { projectId: string; batchId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [filter, setFilter] = useState("all");
  async function load(more = false) {
    setBusy(true); setError(null);
    try {
      const query = new URLSearchParams();
      if (more) Object.entries(obj(data?.next)).forEach(([key, value]) => query.set(key, text(value)));
      const response = await fetch(`/api/projects/${projectId}/intake/decision-batches/${batchId}/progress${query.size ? `?${query}` : ""}`, { cache: "no-store" });
      const value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && typeof obj(value.detail).message === "string" ? text(obj(value.detail).message) : "本批工作暂不可读取，请刷新后继续");
      setData(old => more ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  const counts = obj(data?.counts), visible = rows(data?.items).filter(item => filter === "all" || item.status === filter);
  return <details className="my-2 rounded-md border p-3 text-xs" onToggle={e => { if (e.currentTarget === e.target && e.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer font-medium">本批历史决策的后续办理与补偿进展</summary>
    <div className="mt-2 space-y-3">
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新全部已读范围</Button>
      {data && <>
        <p>{text(data.scope_note)}</p>
        <DecisionIntakeCorrectionBatches projectId={projectId} batchId={batchId} onChanged={() => load()}/>
        <p>来源 {text(counts.sources)} · 历史来源/决策关系 {text(counts.historical_pairs)} · 工作安排 {text(counts.work_arrangements)} · 尚无工作安排的关系 {text(counts.unassigned_pairs)} · 原批未登记行 {text(counts.import_errors)}</p>
        <p>{text(data.completion_note)}</p>
        <label className="block">筛选已读取项<select className="ml-2 rounded-md border bg-background p-2" value={filter} onChange={e => setFilter(e.target.value)}><option value="all">全部已读取项</option>{Object.entries(labels).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
        {visible.map(item => {
          const work = obj(item.work), basis = obj(work.basis), task = obj(obj(basis.context).task), result = obj(work.result), state = obj(item.source_state);
          return <article key={`${item.source_id}/${item.decision_id}/${item.binding_id}`} className="space-y-2 border-t pt-2">
            <p className="font-medium">{labels[text(item.status)]} · <a className="text-primary underline" href={text(item.decision_href)}>{text(item.decision_title)}</a></p>
            <p><a className="text-primary underline" href={text(item.document_href)}>{text(item.filename)}</a> · {text(item.locator)} · 来源修订 {text(state.revision)}</p>
            {item.on_current_decision !== true && <p className="text-destructive">此来源已撤回或改关联，原决策及工作保留。{typeof state.current_decision_href === "string" && <a className="underline" href={state.current_decision_href}>查看当前关联决策</a>}</p>}
            {typeof state.current_issue_href === "string" && <p><a className="text-primary underline" href={state.current_issue_href}>查看当前关联问题及其实际办理</a></p>}
            {typeof item.binding_id === "string" ? <>
              <p>实际任务：<a className="text-primary underline" href={text(task.href)}>{text(task.title)}</a> · {text(task.status)} · 到期 {text(task.due_date)}</p>
              <p className="whitespace-pre-wrap">交付要求：{text(task.expected_output)}</p>
              {Object.keys(result).length > 0 && <><p>最近结果版本 {text(result.revision)} · {text(result.actor_name)} · {text(result.created_at)}</p><p className="whitespace-pre-wrap">{text(result.summary)}<br/>后续事项：{text(result.remaining)}</p>{Array.isArray(result.recheck_reasons) && result.recheck_reasons.map((reason, i) => <p key={i} className="text-destructive">{text(reason)}</p>)}</>}
              <ProjectIntakeWorkResults projectId={projectId} bindingId={item.binding_id}/>
            </> : <a className="text-primary underline" href={`/projects?project=${projectId}&tab=overview&intake_decision=${item.decision_id}#project-intake`}>核对当前记录并准备所需工作</a>}
          </article>;
        })}
        {!visible.length && <p>当前已读取范围没有符合此筛选的条目。</p>}
        {data.next != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>继续读取其余来源与工作</Button>}
        <p className="text-muted-foreground">当前共读取 {rows(data.items).length} 条关系/工作明细；办理后刷新汇总，结果详情保留逐版历史。</p>
      </>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}

export function DecisionSourceBatches({ projectId, sourceId }: { projectId: string; sourceId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  async function load(more = false) {
    setBusy(true); setError(null);
    try {
      const response = await fetch(`/api/projects/${projectId}/intake/decision-sources/${sourceId}/batches${more && data?.next_id ? `?before_id=${data.next_id}` : ""}`, { cache: "no-store" });
      const value: unknown = await responseBody(response).catch(() => null);
      if (!response.ok || !isRecord(value)) throw new Error("来源批次暂不可读取，请刷新后继续");
      setData(old => more ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget === e.target && e.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer">回查本来源的导入批次与后续办理</summary>
    <div className="mt-2 space-y-2"><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>刷新来源批次</Button>
      {rows(data?.items).map(item => <div key={text(item.id)}><p>登记回执时间：{text(item.created_at)}</p><DecisionIntakeBatchProgress projectId={projectId} batchId={text(item.id)}/></div>)}
      {data && !rows(data.items).length && <p>尚无可读取的批次回执。</p>}
      {data?.next_id != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>继续读取批次</Button>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
