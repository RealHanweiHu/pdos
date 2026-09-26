"use client";

import { useRef, useState } from "react";
import { IssueIntakeBatchProgress } from "./issue-intake-batch-progress";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { IssueIntakeReuse, type IssueReuseChoice, type IntakeSourceRow } from "@/components/ai/issue-intake-reuse";
import { IssueIntakeReferences } from "./issue-intake-references";
import { IssueIntakeCompensations } from "./issue-intake-compensations";

type Row = Record<string, unknown>;
type Draft = { action: "withdraw" | "reassign"; reason: string; impact: string; choice: IssueReuseChoice };
const field = "w-full rounded-md border bg-background p-2 text-sm";
function obj(value: unknown): Row { if (!isRecord(value)) throw new Error("批量来源资料不完整"); return value; }
function rows(value: unknown): Row[] { if (!Array.isArray(value)) throw new Error("来源清单不完整"); return value.map(obj); }
function text(value: unknown): string { return value == null ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
function originalRow(source: Row): IntakeSourceRow {
  const snapshot = obj(source.source_snapshot), row = isRecord(snapshot.row) ? snapshot.row : {};
  return { row: Number(row.row ?? 1), errors: [], proposed: isRecord(row.proposed) ? Object.fromEntries(Object.entries(row.proposed).map(([key, value]) => [key, value == null ? null : String(value)])) : {}, historical_state: row.historical_state == null ? null : String(row.historical_state), external_ref: row.external_ref == null ? null : String(row.external_ref) };
}
export function IssueIntakeCorrectionBatches({ projectId, sourceIds, disabled = false, historyOnly = false, onChanged }: { projectId: string; sourceIds: string[]; disabled?: boolean; historyOnly?: boolean; onChanged: () => Promise<void> }) {
  const [data, setData] = useState<Row | null>(null), [group, setGroup] = useState(0), [drafts, setDrafts] = useState<Record<string, Draft>>({});
  const [history, setHistory] = useState<Row[]>([]), [nextHistory, setNextHistory] = useState<Row | null>(null);
  const [reason, setReason] = useState(""), [impact, setImpact] = useState(""), [reviewed, setReviewed] = useState(false), [receipt, setReceipt] = useState<Row | null>(null);
  const [busy, setBusy] = useState(false), [reading, setReading] = useState<Record<string, boolean>>({}), [error, setError] = useState<string | null>(null);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const ordered = [...new Set(sourceIds)].sort(), base = `/api/projects/${projectId}/issue-intake-sources/batches`;
  const working = busy || disabled || Object.values(reading).some(Boolean);
  async function request(path: string, body?: object) {
    const response = await fetch(`${base}${path}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" }), value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "本批未能确认，请保留输入并读取原回执后重试");
    return obj(value);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "批量来源办理暂不可用"); } finally { setBusy(false); } }
  async function load(nextGroup = group) {
    const ids = ordered.slice(nextGroup * 50, nextGroup * 50 + 50); if (!ids.length) return;
    const value = await request("/preview", { source_ids: ids }); setData(value); setGroup(nextGroup); setHistory(rows(value.batches)); setNextHistory(isRecord(value.next) ? value.next : null); setReviewed(false);
  }
  async function moreHistory() {
    if (!nextHistory) return;
    const value = await request("/preview", { source_ids: ordered.slice(group * 50, group * 50 + 50), ...nextHistory });
    setHistory(old => [...old, ...rows(value.batches).filter(item => !old.some(prior => prior.id === item.id))]); setNextHistory(isRecord(value.next) ? value.next : null);
  }
  const entries = data ? rows(data.entries) : [], selected = entries.filter(entry => drafts[text(obj(entry.source).id)]);
  const valid = !!data && selected.length > 0 && !!reason.trim() && reviewed && selected.every(entry => {
    const source = obj(entry.source), state = obj(entry.current_source), d = drafts[text(source.id)], current = isRecord(entry.current_issue) ? entry.current_issue : null;
    return !!(d.impact.trim() || impact.trim()) && (d.action === "withdraw" ? state.state === "active" : !!d.choice.target && d.choice.target.id !== current?.id);
  });
  function update(id: string, patch: Partial<Draft>) { setDrafts(old => ({ ...old, [id]: { ...old[id], ...patch } })); setReviewed(false); }
  async function apply() {
    if (!valid) return;
    const entries = selected.map(entry => { const source = obj(entry.source), state = obj(entry.current_source), d = drafts[text(source.id)], current = isRecord(entry.current_issue) ? entry.current_issue : null;
      return { source_row_id: source.id, expected_revision: state.revision, expected_current_updated_at: current?.updated_at ?? null, action: d.action,
        target_issue_id: d.action === "reassign" ? d.choice.target?.id : null, expected_target_updated_at: d.action === "reassign" ? d.choice.target?.updated_at : null,
        reason: (d.action === "reassign" ? d.choice.reason.trim() : d.reason.trim()) || reason.trim(), impact_note: d.impact.trim() || impact.trim() };
    });
    const body = { reason: reason.trim(), acknowledge_history: true, entries }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const result = await request("", { ...body, request_id: pending.current.id }); pending.current = null; setReceipt(result);
    setDrafts(old => Object.fromEntries(Object.entries(old).filter(([key]) => !entries.some(entry => entry.source_row_id === key)))); setReviewed(false);
    await load(); await onChanged();
  }
  if (!ordered.length) return null;
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => load()); }}>
    <summary className="cursor-pointer font-medium">{historyOnly ? "查看本来源的纠错批次与补偿进展" : "批量纠正已导入的来源关联"}</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p>{historyOnly ? "可读取包含本来源的原纠错批次，核对批内问题、补偿任务和当前办理结果。" : "逐行选择撤回或重新关联，统一保存本批及每行回执。任一行版本冲突则整批不保存；刷新保留编辑内容，核对后可再次提交。原文件、问题及已办业务保留，业务影响通过后续补偿处理。"}</p>
      <Button type="button" size="sm" variant="outline" disabled={working} onClick={() => void act(() => load())}>刷新本组来源及原问题</Button>
      {ordered.length > 50 && <div className="flex items-center gap-2"><Button type="button" size="sm" variant="outline" disabled={working || group === 0} onClick={() => void act(() => load(group - 1))}>上一组</Button><span>第 {group + 1} / {Math.ceil(ordered.length / 50)} 组，每组最多50条</span><Button type="button" size="sm" variant="outline" disabled={working || (group + 1) * 50 >= ordered.length} onClick={() => void act(() => load(group + 1))}>下一组</Button></div>}
      {data && !historyOnly && <><label className="block">本批共同依据（各行可另填）<textarea maxLength={2000} className={field} disabled={working} value={reason} onChange={e => { setReason(e.target.value); setReviewed(false); }}/></label><label className="block">共同影响与后续处理说明（各行可另填）<textarea maxLength={4000} className={field} disabled={working} value={impact} onChange={e => { setImpact(e.target.value); setReviewed(false); }}/></label>
        {entries.map(entry => { const source = obj(entry.source), state = obj(entry.current_source), id = text(source.id), d = drafts[id], current = isRecord(entry.current_issue) ? entry.current_issue : null;
          return <article key={id} className="space-y-2 rounded-md border p-3">
            <label className="flex gap-2 font-medium"><input type="checkbox" checked={!!d} disabled={working} onChange={e => { if (e.target.checked) setDrafts(old => ({ ...old, [id]: { action: state.state === "active" ? "withdraw" : "reassign", reason: "", impact: "", choice: { target: null, reason: "" } } })); else setDrafts(old => Object.fromEntries(Object.entries(old).filter(([key]) => key !== id))); setReviewed(false); }}/>{text(obj(source.source_snapshot).filename)} · {text(source.locator)}</label>
            <p>来源版本 {text(state.revision)} · {state.state === "withdrawn" ? "当前关联已撤回" : `当前关联：${text(current?.title)}`}</p>
            {current && <a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${text(current.id)}`}>核对原问题当前内容</a>}
            {d && <><label className="block">本行处理<select className="ml-2 rounded-md border bg-background p-2" value={d.action} disabled={working} onChange={e => update(id, { action: e.target.value as Draft["action"] })}><option value="withdraw">撤回当前来源关联</option><option value="reassign">重新关联已有问题</option></select></label>
              {d.action === "withdraw" ? <label className="block">本行另有撤回依据<textarea className={field} maxLength={2000} disabled={working} value={d.reason} onChange={e => update(id, { reason: e.target.value })}/></label> : <IssueIntakeReuse base={`/api/projects/${projectId}/issue-intake-sources/${id}`} row={originalRow(source)} value={d.choice} disabled={busy || disabled} allowNew={false} onBusyChange={value => setReading(old => ({ ...old, [id]: value }))} onChange={value => update(id, { choice: value ?? { target: null, reason: "" } })}/>}
              <label className="block">本行另有影响与处理说明<textarea className={field} maxLength={4000} disabled={working} value={d.impact} onChange={e => update(id, { impact: e.target.value })}/></label>
              <p className="whitespace-pre-wrap">将保存的依据：{(d.action === "reassign" ? d.choice.reason.trim() : d.reason.trim()) || reason.trim() || "待填写"}<br/>将保存的影响及处理：{d.impact.trim() || impact.trim() || "待填写"}</p>
              <p>{text(current?.title)} → {d.action === "withdraw" ? "撤回来源关联，保留原业务" : d.choice.target?.title ?? "待选择新关联问题"}</p>
              {d.action === "withdraw" && state.state !== "active" && <p className="text-destructive">该来源已经撤回，请取消本行或改为重新关联。</p>}
              <IssueIntakeReferences projectId={projectId} sourceId={id} disabled={busy || disabled}/>
            </>}
          </article>;
        })}
        <label className="flex gap-2"><input type="checkbox" disabled={working} checked={reviewed} onChange={e => setReviewed(e.target.checked)}/>已核对本组所选 {selected.length} 行的当前关联、前后变化及影响，确认追加具名纠错记录；后续业务保留并继续办理。</label>
        <Button type="button" disabled={working || !valid} onClick={() => void act(apply)}>统一保存所选 {selected.length} 行纠错</Button>
      </>}
      {data && !history.length && <p>当前来源尚无批量纠错回执，原逐次处理历史仍保留。</p>}
      {history.length > 0 && <details className="rounded-md border p-3"><summary className="cursor-pointer">本组来源已有的纠错批次</summary><div className="mt-2 space-y-2">{history.map(item => <div key={text(item.id)} className="rounded-md border p-2"><p>{text(item.created_at)} · {rows(item.results).length} 行 · {text(item.reason)}</p><Button type="button" size="sm" variant="outline" disabled={working} onClick={() => void act(async () => setReceipt(await request(`/${text(item.id)}`)))}>查看本批回执及后续办理</Button></div>)}{nextHistory && <Button type="button" size="sm" variant="outline" disabled={working} onClick={() => void act(moreHistory)}>更早纠错批次</Button>}</div></details>}
      {receipt && <section className="space-y-2 rounded-md border p-3"><p role="status">批次 {text(receipt.id)} 已保存，共 {rows(receipt.results).length} 行来源纠错；业务记录保留。</p><Button type="button" size="sm" variant="outline" disabled={working} onClick={() => void act(async () => setReceipt(await request(`/${text(receipt.id)}`)))}>重读原批次回执</Button>{rows(receipt.results).map(item => <p key={text(item.source_row_id)}>来源 {text(item.source_row_id)} · 纠错版本 {text(item.revision)} · {item.action === "withdraw" ? "撤回关联" : "重新关联"}</p>)}<IssueIntakeBatchProgress key={text(receipt.id)} projectId={projectId} batchId={text(receipt.id)}/><IssueIntakeCompensations projectId={projectId} sourceIds={rows(receipt.results).map(item => text(item.source_row_id))}/></section>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
