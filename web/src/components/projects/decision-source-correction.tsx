"use client";

import { useRef, useState } from "react";
import { DecisionIntakeTarget, type IntakeTargetChoice } from "@/components/ai/decision-intake-targets";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const field = "w-full rounded-md border bg-background p-2 text-xs";
function show(value: unknown): string { return value == null || value === "" ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
function details(value: unknown): Row { if (!isRecord(value) || !isRecord(value.source) || !Array.isArray(value.history) || !value.history.every(isRecord) || typeof value.digest !== "string") throw new Error("来源纠错资料不完整"); return value; }
function history(value: Row): Row[] { return Array.isArray(value.history) ? value.history.filter(isRecord) : []; }
export function DecisionSourceCorrection({ projectId, sourceId, onChanged }: { projectId: string; sourceId: string; onChanged: () => Promise<void> }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [reading, setReading] = useState<Record<string, boolean>>({}), [error, setError] = useState<string | null>(null);
  const [mode, setMode] = useState<"withdraw" | "reassign">("withdraw"), [decision, setDecision] = useState<IntakeTargetChoice | undefined>(), [issue, setIssue] = useState<IntakeTargetChoice | undefined>();
  const [reason, setReason] = useState(""), [impact, setImpact] = useState(""), [ack, setAck] = useState(false), [receipt, setReceipt] = useState<Row | null>(null);
  const pending = useRef<{ signature: string; id: string } | null>(null), base = `/api/projects/${projectId}/decision-intake-sources/${sourceId}`;
  async function request(path: string, body?: object) {
    const response = await fetch(`${base}${path}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" }), value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "来源办理未完成，请查询原回执");
    return value;
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "来源办理未完成"); } finally { setBusy(false); } }
  async function load(more = false) {
    const next = details(await request(more && data?.next_before_revision ? `?before_revision=${data.next_before_revision}` : ""));
    setData(old => more && old ? { ...next, history: [...history(old), ...history(next).filter(item => !history(old).some(prior => prior.id === item.id))] } : next); setAck(false);
  }
  const currentDecision = data && isRecord(data.current_decision) ? data.current_decision : null, currentIssue = data && isRecord(data.current_issue) ? data.current_issue : null;
  function keepCurrent() {
    setDecision(currentDecision && typeof currentDecision.id === "string" && typeof data?.current_decision_digest === "string" ? { target: { ...currentDecision, id: currentDecision.id, digest: data.current_decision_digest }, reason: "" } : undefined);
    setIssue(currentIssue && typeof currentIssue.id === "string" && typeof data?.current_issue_digest === "string" ? { target: { ...currentIssue, id: currentIssue.id, digest: data.current_issue_digest }, reason: "" } : undefined); setAck(false);
  }
  async function save() {
    if (!data) return;
    const body = { action: mode, expected_revision: data.revision, expected_digest: data.digest, target_decision_id: mode === "reassign" ? decision?.target?.id : null, expected_decision_digest: mode === "reassign" ? decision?.target?.digest : null, target_issue_id: mode === "reassign" ? issue?.target?.id ?? null : null, expected_issue_digest: mode === "reassign" ? issue?.target?.digest ?? null : null, reason: reason.trim(), impact_note: impact.trim(), acknowledge_history: true }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const value = await request("/corrections", { ...body, request_id: pending.current.id });
    if (!isRecord(value.receipt)) throw new Error("保存回执不完整，请刷新历史后继续");
    setReceipt(value.receipt); pending.current = null; setAck(false); await load(); await onChanged();
  }
  const source = data && isRecord(data.source) ? data.source : {}, snap = isRecord(source.source_snapshot) ? source.source_snapshot : {}, raw = isRecord(snap.row) ? snap.row : {}, values = isRecord(raw.values) ? raw.values : {};
  const working = busy || Object.values(reading).some(Boolean);
  const changed = decision?.target?.id !== data?.current_decision_id || (issue?.target?.id ?? null) !== data?.current_issue_id;
  const valid = !!data && data.can_edit === true && !!reason.trim() && !!impact.trim() && ack && (mode === "withdraw" ? data.state === "active" : !!decision?.target && (!issue || !!issue.target) && changed);
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => load()); }}><summary className="cursor-pointer font-medium">纠正来源关系与查看修订历史</summary><div className="mt-3 space-y-3 text-xs">
    <Button type="button" size="sm" variant="outline" disabled={working} onClick={() => void act(() => load())}>刷新当前关系与业务内容</Button>
    {data && <>
      <p>来源版本 {show(data.revision)} · {data.state === "withdrawn" ? "已撤回" : "当前有效关联"}<br/>当前决策：{show(currentDecision?.title)}<br/>当前问题：{show(currentIssue?.title)}</p>
      <p>本次追加来源关系修订，保留原文、决策和问题。请记录来源已被使用的情况及后续处理；实际业务字段、批准和执行结果仍由原业务流程办理。</p>
      <details><summary className="cursor-pointer">核对当前决策与问题内容</summary><div className="grid gap-3 sm:grid-cols-2">{[["决策", currentDecision], ["问题", currentIssue]].map(([label, value]) => <dl key={String(label)} className="space-y-2"><dt className="font-medium">{String(label)}</dt>{isRecord(value) && Object.entries(value).map(([key, content]) => <div key={key}><dt>{key}</dt><dd className="max-h-48 overflow-auto whitespace-pre-wrap break-words">{show(content)}</dd></div>)}</dl>)}</div></details>
      {data.can_edit === true && <fieldset disabled={working} className="space-y-3">
        <label>本次处理<select className={field} value={mode} onChange={e => { setMode(e.target.value as "withdraw" | "reassign"); setAck(false); }}><option value="withdraw">撤回当前来源关联</option><option value="reassign">修改或恢复来源对应的决策/问题</option></select></label>
        {mode === "reassign" && <div className="space-y-2"><Button type="button" size="sm" variant="outline" onClick={keepCurrent}>载入当前决策与问题，再修改</Button><p>必须选择一个目标决策。取消问题选择会清除本条来源的实际问题关联。</p>{(["decision", "issue"] as const).map(kind => <DecisionIntakeTarget key={kind} operation="correct" showReason={false} base={base} kind={kind} original={values} value={kind === "decision" ? decision : issue} disabled={busy} onBusyChange={value => setReading(old => ({ ...old, [kind]: value }))} onChange={value => { (kind === "decision" ? setDecision : setIssue)(value); setAck(false); }}/>)}</div>}
        <label className="block">纠错依据<textarea className={field} maxLength={2000} value={reason} onChange={e => { setReason(e.target.value); setAck(false); }}/></label>
        <label className="block">对已办业务的影响及处理说明<textarea className={field} maxLength={4000} value={impact} onChange={e => { setImpact(e.target.value); setAck(false); }}/></label>
        <p>保存后：{mode === "withdraw" ? "撤回本条来源的当前决策和问题关联" : `决策「${show(decision?.target?.title)}」；问题「${issue?.target ? show(issue.target.title) : "无关联问题"}」`}。</p>
        <label className="flex gap-2"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)}/>已核对当前内容、修改前后关系及影响；历史记录保留，实际业务后果另行办理。</label>
        <Button type="button" size="sm" disabled={!valid} onClick={() => void act(save)}>保存来源关系修订</Button>
      </fieldset>}
      {receipt && <p role="status">已保存修订 {show(receipt.revision)} · {receipt.action === "withdraw" ? "撤回关联" : "修改关联"}</p>}
      {history(data).map(item => <details key={String(item.id)} className="rounded-md border p-2"><summary className="cursor-pointer">版本 {show(item.revision)} · {item.action === "withdraw" ? "撤回" : "修改关联"} · {show(item.actor_name)} · {show(item.created_at)}</summary><p className="whitespace-pre-wrap">依据：{show(item.reason)}<br/>影响及处理：{show(item.impact_note)}</p><div className="grid gap-2 sm:grid-cols-2">{["before_snapshot", "after_snapshot"].map(key => { const value = isRecord(item[key]) ? item[key] : {}, decision = isRecord(value.decision) ? value.decision : {}, issue = isRecord(value.issue) ? value.issue : {}; return <div key={key}><p className="font-medium">{key === "before_snapshot" ? "修订前" : "修订后"}</p><p>决策：{show(decision.title)}<br/>问题：{show(issue.title)}</p><details><summary className="cursor-pointer">当时完整记录</summary><pre className="max-h-80 overflow-auto whitespace-pre-wrap break-words">{JSON.stringify(value, null, 2)}</pre></details></div>; })}</div></details>)}
      {!!data.next_before_revision && <Button type="button" size="sm" variant="outline" disabled={working} onClick={() => void act(() => load(true))}>更早修订</Button>}
    </>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
  </div></details>;
}
