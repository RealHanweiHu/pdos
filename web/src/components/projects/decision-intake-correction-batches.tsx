"use client";

import { useRef, useState } from "react";
import { DecisionIntakeTarget, type IntakeTargetChoice } from "@/components/ai/decision-intake-targets";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
type Draft = { action: "withdraw" | "reassign"; reason: string; impact: string; decision?: IntakeTargetChoice; issue?: IntakeTargetChoice };
const obj = (value: unknown): Row => isRecord(value) ? value : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: unknown) => value == null ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value);
const field = "w-full rounded-md border bg-background p-2 text-xs";
export function DecisionIntakeCorrectionBatches({ projectId, batchId, onChanged }: { projectId: string; batchId: string; onChanged: () => Promise<void> }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [reading, setReading] = useState<Record<string, boolean>>({});
  const [drafts, setDrafts] = useState<Record<string, Draft>>({}), [reason, setReason] = useState(""), [impact, setImpact] = useState(""), [reviewed, setReviewed] = useState(false), [receipt, setReceipt] = useState<Row | null>(null);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/intake/decision-batches/${batchId}/corrections`, working = busy || Object.values(reading).some(Boolean);
  async function request(query = "", body?: Row) {
    const response = await fetch(base + query, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && typeof obj(value.detail).message === "string" ? text(obj(value.detail).message) : "本批暂未取得保存回执，请保留输入并刷新历史核对");
    return value;
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "批量纠错未完成"); } finally { setBusy(false); } }
  async function load(offset = Number(data?.offset ?? 0), moreHistory = false) {
    const value = await request(`?offset=${offset}${moreHistory && data?.next_id ? `&before_id=${data.next_id}` : ""}`);
    setData(old => moreHistory ? { ...value, batches: [...rows(old?.batches), ...rows(value.batches)] } : value); setReviewed(false);
  }
  function update(id: string, patch: Partial<Draft>) { setDrafts(old => ({ ...old, [id]: { ...old[id], ...patch } })); setReviewed(false); }
  function currentChoice(value: unknown, digest: unknown): IntakeTargetChoice | undefined { const target = obj(value); return typeof target.id === "string" && typeof digest === "string" ? { target: { ...target, id: target.id, digest }, reason: "" } : undefined; }
  const entries = rows(data?.entries), selected = entries.filter(entry => !!drafts[text(obj(entry.source).id)]);
  const valid = data?.can_edit === true && reviewed && !!reason.trim() && selected.length > 0 && selected.every(entry => {
    const draft = drafts[text(obj(entry.source).id)];
    return !!(draft.impact.trim() || impact.trim()) && (draft.action === "withdraw" ? entry.state === "active" : !!draft.decision?.target && (!draft.issue || !!draft.issue.target) && (draft.decision.target.id !== entry.current_decision_id || (draft.issue?.target?.id ?? null) !== entry.current_issue_id));
  });
  async function save() {
    if (!valid) return;
    const entryBodies = selected.map(entry => { const source = obj(entry.source), d = drafts[text(source.id)]; return { source_row_id: source.id, expected_revision: entry.revision, expected_digest: entry.digest, action: d.action, reason: d.reason.trim() || reason.trim(), impact_note: d.impact.trim() || impact.trim(), target_decision_id: d.action === "reassign" ? d.decision?.target?.id : null, expected_decision_digest: d.action === "reassign" ? d.decision?.target?.digest : null, target_issue_id: d.action === "reassign" ? d.issue?.target?.id ?? null : null, expected_issue_digest: d.action === "reassign" ? d.issue?.target?.digest ?? null : null }; });
    const body = { reason: reason.trim(), entries: entryBodies, acknowledge_history: true }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const result = await request("", { ...body, request_id: pending.current.id });
    setReceipt(result); pending.current = null; setReviewed(false);
    setDrafts(old => Object.fromEntries(Object.entries(old).filter(([key]) => !entryBodies.some(item => item.source_row_id === key))));
    await load(); await onChanged();
  }
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget === e.target && e.currentTarget.open && !data && !busy) void act(() => load()); }}>
    <summary className="cursor-pointer font-medium">批量纠正本批已登记的来源关系</summary>
    <div className="mt-2 space-y-3">
      <p>每组最多50条，逐条选择撤回、改关联或恢复，统一确认后保存。任一行版本冲突则整批不保存；原决策、问题、任务及历史回执保留，业务后果继续通过原流程办理。</p>
      <Button type="button" size="sm" variant="outline" disabled={working} onClick={() => void act(() => load())}>刷新当前组及纠错历史</Button>
      {data && <>
        <p>本批共 {text(data.total)} 条已登记来源；当前从第 {Number(data.offset) + 1} 条读取，当前组选择 {selected.length} 条。</p>
        <div className="flex gap-2">{Number(data.offset) > 0 && <Button type="button" size="sm" variant="outline" disabled={working} onClick={() => void act(() => load(Math.max(0, Number(data.offset) - 50)))}>上一组来源</Button>}{data.next_offset != null && <Button type="button" size="sm" variant="outline" disabled={working} onClick={() => void act(() => load(Number(data.next_offset)))}>下一组来源</Button>}</div>
        {data.can_edit === true && <>
          <fieldset disabled={working} className="space-y-2"><label className="block">本批共同纠错依据（各行可覆盖）<textarea className={field} maxLength={2000} value={reason} onChange={e => { setReason(e.target.value); setReviewed(false); }}/></label><label className="block">共同影响及后续处理（各行可覆盖）<textarea className={field} maxLength={4000} value={impact} onChange={e => { setImpact(e.target.value); setReviewed(false); }}/></label></fieldset>
          {entries.map(entry => {
            const source = obj(entry.source), id = text(source.id), snapshot = obj(source.source_snapshot), original = obj(obj(snapshot.row).values), d = drafts[id], current = obj(entry.current_decision), issue = obj(entry.current_issue);
            return <article key={id} className="space-y-2 rounded-md border p-3">
              <label className="flex gap-2"><input type="checkbox" checked={!!d} disabled={working} onChange={e => { if (e.target.checked) setDrafts(old => ({ ...old, [id]: { action: entry.state === "active" ? "withdraw" : "reassign", reason: "", impact: "" } })); else setDrafts(old => Object.fromEntries(Object.entries(old).filter(([key]) => key !== id))); setReviewed(false); }}/>{text(snapshot.filename)} · {text(source.locator)} · 来源修订 {text(entry.revision)}</label>
              <p>当前决策：{text(current.title)} · 当前问题：{text(issue.title)}{entry.state === "withdrawn" ? " · 当前来源已撤回" : ""}</p>
              <details><summary className="cursor-pointer">核对原文与当前业务内容</summary><div className="space-y-2">{[["原文字段", obj(obj(snapshot.row).original)], ["当前决策", current], ["当前问题", issue]].map(([label, value]) => <section key={String(label)}><p className="font-medium">{String(label)}</p>{Object.entries(obj(value)).map(([key, content]) => <p key={key} className="whitespace-pre-wrap break-words">{key}：{text(content)}</p>)}</section>)}</div></details>
              {d && <>
                <label className="block">本行处理<select className={field} disabled={working} value={d.action} onChange={e => update(id, { action: e.target.value as Draft["action"] })}><option value="withdraw">撤回当前来源关联</option><option value="reassign">修改或恢复决策/问题关联</option></select></label>
                {d.action === "reassign" && <><Button type="button" size="sm" variant="outline" disabled={working} onClick={() => update(id, { decision: currentChoice(entry.current_decision, entry.current_decision_digest), issue: currentChoice(entry.current_issue, entry.current_issue_digest) })}>载入当前关联后修改</Button><p>必须选择目标决策；取消问题选择会清除本来源的问题关联。</p>{(["decision", "issue"] as const).map(kind => <DecisionIntakeTarget key={kind} base={`/api/projects/${projectId}/decision-intake-sources/${id}`} kind={kind} operation="correct" showReason={false} original={original} value={d[kind]} disabled={busy} onBusyChange={value => setReading(old => ({ ...old, [`${id}/${kind}`]: value }))} onChange={value => update(id, { [kind]: value })}/>)}</>}
                <fieldset disabled={working} className="space-y-2"><label className="block">本行另有纠错依据<textarea className={field} maxLength={2000} value={d.reason} onChange={e => update(id, { reason: e.target.value })}/></label><label className="block">本行另有影响及处理说明<textarea className={field} maxLength={4000} value={d.impact} onChange={e => update(id, { impact: e.target.value })}/></label></fieldset>
                <p>保存后：{d.action === "withdraw" ? "撤回本来源的决策和问题关联，业务保留" : `决策「${text(d.decision?.target?.title)}」；问题「${d.issue?.target ? text(d.issue.target.title) : "无关联问题"}」`}。</p>
                <p className="whitespace-pre-wrap">纠错依据：{d.reason.trim() || reason.trim() || "待填写"}<br/>影响及处理：{d.impact.trim() || impact.trim() || "待填写"}</p>
                {d.action === "withdraw" && entry.state !== "active" && <p className="text-destructive">本来源已经撤回，请取消此行或选择恢复关联。</p>}
              </>}
            </article>;
          })}
          <label className="flex gap-2"><input type="checkbox" disabled={working} checked={reviewed} onChange={e => setReviewed(e.target.checked)}/>已核对当前组所选 {selected.length} 行的前后关系、实际版本和已办影响，确认保存具名修订，原业务继续保留。</label>
          <Button type="button" size="sm" disabled={working || !valid} onClick={() => void act(save)}>统一保存当前组所选来源修订</Button>
        </>}
        {receipt && <p role="status">已保存纠错批次 {text(receipt.id)}，共 {rows(receipt.results).length} 条来源修订。请刷新后续办理汇总核对影响。</p>}
        <details><summary className="cursor-pointer">本导入批次已有的批量纠错回执</summary><div className="mt-2 space-y-2">{rows(data.batches).map(batch => <details key={text(batch.id)} className="rounded-md border p-2"><summary className="cursor-pointer">{text(batch.created_at)} · {text(batch.actor_name)} · {rows(batch.results).length} 条</summary><p className="whitespace-pre-wrap">{text(batch.reason)}</p>{rows(batch.results).map(item => <div key={text(item.source_row_id)} className="space-y-1 border-t pt-2"><p>来源 {text(item.source_row_id)} · 修订 {text(item.revision)} · {item.action === "withdraw" ? "撤回" : "修改关联"}</p><p>决策：{text(obj(obj(item.before_snapshot).decision).title)} → {text(obj(obj(item.after_snapshot).decision).title)}<br/>问题：{text(obj(obj(item.before_snapshot).issue).title)} → {text(obj(obj(item.after_snapshot).issue).title)}</p><p className="whitespace-pre-wrap">依据：{text(item.reason)}<br/>影响及处理：{text(item.impact_note)}</p>{[item.previous_decision_id, item.target_decision_id].filter((value, index, all) => typeof value === "string" && all.indexOf(value) === index).map(id => <a key={String(id)} className="mr-3 text-primary underline" href={`/projects?project=${projectId}&tab=decisions#decision-${id}`}>查看实际决策与后续工作</a>)}</div>)}</details>)}{!rows(data.batches).length && <p>尚无批量纠错回执，原逐条修订仍可在来源页查看。</p>}{data.next_id != null && <Button type="button" size="sm" variant="outline" disabled={working} onClick={() => void act(() => load(Number(data.offset), true))}>继续读取纠错回执</Button>}</div></details>
      </>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
