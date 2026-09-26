"use client";

import { useRef, useState } from "react";
import { IssueIntakeCorrectionBatches } from "./issue-intake-correction-batches";
import { IssueIntakeReferences } from "./issue-intake-references";
import { IssueIntakeCompensations } from "./issue-intake-compensations";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { IssueIntakeReuse, type IssueReuseChoice, type IntakeSourceRow } from "@/components/ai/issue-intake-reuse";

type Detail = { source: Record<string, unknown>; revision: number; state: string; current_issue: Record<string, unknown> | null; original_issue: Record<string, unknown> | null; history: Record<string, unknown>[]; next_before_revision: number | null };
function parse(value: unknown): Detail {
  if (!isRecord(value) || !isRecord(value.source) || typeof value.revision !== "number" || typeof value.state !== "string" || !Array.isArray(value.history) || !value.history.every(isRecord)) throw new Error("来源纠错资料不完整");
  return { source: value.source, revision: value.revision, state: value.state, current_issue: isRecord(value.current_issue) ? value.current_issue : null, original_issue: isRecord(value.original_issue) ? value.original_issue : null, history: value.history, next_before_revision: typeof value.next_before_revision === "number" ? value.next_before_revision : null };
}
async function request(path: string, body?: object): Promise<unknown> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined }), value: unknown = await responseBody(response).catch(() => null);
  if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "来源办理未完成，请刷新原回执");
  return value;
}
const show = (value: unknown): string => value == null || value === "" ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value);
export function IssueSourceCorrection({ projectId, sourceId, onChanged }: { projectId: string; sourceId: string; onChanged: () => Promise<void> }) {
  const [data, setData] = useState<Detail | null>(null), [busy, setBusy] = useState(false), [reading, setReading] = useState(false), [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"withdraw" | "reassign">("withdraw"), [reason, setReason] = useState(""), [impact, setImpact] = useState(""), [ack, setAck] = useState(false);
  const [choice, setChoice] = useState<IssueReuseChoice>({ target: null, reason: "" }), [receipt, setReceipt] = useState<Record<string, unknown> | null>(null);
  const pending = useRef<{ signature: string; id: string } | null>(null), base = `/api/projects/${projectId}/issue-intake-sources/${sourceId}`;
  async function load(more = false) {
    const next = parse(await request(`${base}${more && data?.next_before_revision ? `?before_revision=${data.next_before_revision}` : ""}`));
    setData(old => more && old ? { ...next, history: [...old.history, ...next.history.filter(item => !old.history.some(prior => prior.id === item.id))] } : next); setAck(false);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "来源办理未完成"); } finally { setBusy(false); } }
  async function save() {
    if (!data) return;
    const body = { expected_revision: data.revision, expected_current_updated_at: data.current_issue?.updated_at ?? null, action: mode, target_issue_id: mode === "reassign" ? choice.target?.id : null, expected_target_updated_at: mode === "reassign" ? choice.target?.updated_at : null, reason: mode === "reassign" ? choice.reason.trim() : reason.trim(), impact_note: impact.trim(), acknowledge_history: true }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const value = await request(`${base}/corrections`, { ...body, request_id: pending.current.id });
    if (!isRecord(value) || !isRecord(value.receipt)) throw new Error("处理回执不完整，请刷新查询");
    setReceipt(value.receipt); pending.current = null; setAck(false); await load(); await onChanged();
  }
  const source = data && isRecord(data.source.source_snapshot) ? data.source.source_snapshot : {}, raw = isRecord(source.row) ? source.row : {};
  const row: IntakeSourceRow = { row: Number(raw.row ?? 1), errors: [], proposed: isRecord(raw.proposed) ? Object.fromEntries(Object.entries(raw.proposed).map(([key, value]) => [key, value == null ? null : String(value)])) : {}, historical_state: raw.historical_state == null ? null : String(raw.historical_state), external_ref: raw.external_ref == null ? null : String(raw.external_ref) };
  const valid = data && impact.trim() && ack && (mode === "withdraw" ? data.state === "active" && reason.trim() : choice.target && choice.reason.trim() && choice.target.id !== data.current_issue?.id);
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => load()); }}>
    <summary className="cursor-pointer font-medium">来源关联纠错与历史</summary>
    <div className="mt-3 space-y-3 text-xs">
      <Button size="sm" variant="outline" disabled={busy || reading} onClick={() => void act(() => load())}>刷新当前关联与问题内容</Button>
      {data && <>
        <p>当前关联：{data.state === "withdrawn" ? "已撤回" : show(data.current_issue?.title)} · 来源处理版本 {data.revision}</p>
        {data.current_issue && <details><summary className="cursor-pointer">核对当前问题内容</summary><dl className="mt-2 space-y-2">{Object.entries({ title: "标题", status: "状态", description: "说明", root_cause: "原因", resolution: "处理记录", closure_criteria: "关闭条件", closure_evidence_ref: "关闭证据", target_date: "目标日期" }).map(([key, label]) => <div key={key}><dt className="font-medium">{label}</dt><dd className="whitespace-pre-wrap break-words">{show(data.current_issue?.[key])}</dd></div>)}</dl></details>}
        <p className="text-muted-foreground">本操作纠正来源关联并保留历史，不删除原文件或问题，也不撤销已执行的验证、关闭和其他业务操作。若原文件内容已经录入业务字段，请进入原问题及后续业务处理，并在下方记录影响和处理情况。</p>
        {data.original_issue && <a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${String(data.original_issue.id)}`}>办理最初登记或关联的问题</a>}
        <IssueIntakeReferences projectId={projectId} sourceId={sourceId}/>
        <label className="block">本次处理<select className="ml-2 rounded-md border bg-background p-2" value={mode} disabled={busy || reading} onChange={e => { setMode(e.target.value as "withdraw" | "reassign"); setAck(false); }}><option value="withdraw">撤回当前来源关联</option><option value="reassign">重新关联已有问题</option></select></label>
        {mode === "withdraw" ? <label className="block">撤回依据<textarea className="mt-1 min-h-20 w-full rounded-md border bg-background p-2" disabled={busy || reading} maxLength={2000} value={reason} onChange={e => { setReason(e.target.value); setAck(false); }}/></label> : <IssueIntakeReuse base={base} row={row} value={choice} allowNew={false} disabled={busy} onBusyChange={setReading} onChange={value => { setChoice(value ?? { target: null, reason: "" }); setAck(false); }}/>}
        <label className="block">对已办业务的影响与处理说明<textarea className="mt-1 min-h-24 w-full rounded-md border bg-background p-2" disabled={busy || reading} maxLength={4000} value={impact} onChange={e => { setImpact(e.target.value); setAck(false); }} placeholder="说明原值是否已被使用、相关办理记录及已采取或仍待办理的纠正；不要把仅撤回来源写成业务已撤销"/></label>
        <label className="flex gap-2"><input type="checkbox" disabled={busy || reading} checked={ack} onChange={e => setAck(e.target.checked)}/>已核对当前关联、问题内容及影响，确认追加此次来源纠错记录；原业务记录及历史保留。</label>
        <Button size="sm" disabled={busy || reading || !valid} onClick={() => void act(save)}>确认{mode === "withdraw" ? "撤回来源关联" : "重新关联来源"}</Button>
        {receipt && <p role="status">来源处理已保存：版本 {String(receipt.revision)} · {receipt.action === "withdraw" ? "撤回关联" : "重新关联"}。业务对象保留。</p>}
        {data.history.map(item => <details key={String(item.id)} className="rounded-md border p-2"><summary>版本 {String(item.revision)} · {item.action === "withdraw" ? "撤回关联" : "重新关联"} · {String(item.actor_name)} · {new Date(String(item.created_at)).toLocaleString("zh-CN")}</summary><p className="mt-2 whitespace-pre-wrap">依据：{show(item.reason)}<br/>影响与处理：{show(item.impact_note)}</p><div className="mt-2 grid gap-3 sm:grid-cols-2">{["before_snapshot", "after_snapshot"].map(key => { const snapshot = isRecord(item[key]) ? item[key] : {}; return <div key={key}><p className="font-medium">{key === "before_snapshot" ? "原关联当时内容" : "新关联当时内容"}</p><p>{show(snapshot.title)} · {show(snapshot.status)}</p><p className="whitespace-pre-wrap break-words">{show(snapshot.description)}</p></div>; })}</div></details>)}
        <IssueIntakeCorrectionBatches projectId={projectId} sourceIds={[sourceId]} historyOnly disabled={busy || reading} onChanged={async () => { await load(); await onChanged(); }}/>
        {data.revision > 0 && <IssueIntakeCompensations projectId={projectId} sourceIds={[sourceId]}/>}
        {data.next_before_revision && <Button size="sm" variant="outline" disabled={busy || reading} onClick={() => void act(() => load(true))}>更早来源处理</Button>}
      </>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
