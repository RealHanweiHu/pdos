"use client";

import { useRef, useState } from "react";
import { IssueIntakeCompensationResults } from "@/components/projects/issue-intake-compensation-results";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Draft = { title: string; stage: string; owner: string; start: string; due: string; output: string; criteria: string; description: string; priority: string };
function obj(value: unknown): Record<string, unknown> { if (!isRecord(value)) throw new Error("补偿任务资料不完整"); return value; }
function arr(value: unknown): Record<string, unknown>[] { if (!Array.isArray(value)) throw new Error("补偿任务清单不完整"); return value.map(obj); }
function text(value: unknown): string { return value == null || value === "" ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
const field = "w-full rounded-md border bg-background p-2 text-sm";
const taskStates: Record<string, string> = { todo: "待办", in_progress: "办理中", blocked: "阻塞", done: "任务已完成", skipped: "已跳过", pending_approval: "待批准" };
export function IntakeCompensationSummary({ value }: { value: Record<string, unknown> }) {
  const snapshot = obj(value.snapshot), source = obj(snapshot.source), correction = obj(snapshot.correction), issue = obj(snapshot.issue), task = obj(value.task);
  return <article className="space-y-2 rounded-md border p-3 text-xs">
    <p className="font-medium">导入纠错后续任务 · {text(task.title)}</p>
    <p>{taskStates[text(task.status)] ?? text(task.status)} · 截止 {text(task.due_date)} · 负责人 {text(task.assignee_user_id)}</p>
    <p>原资料：{text(obj(source.source_snapshot).filename)} · {text(source.locator)} · 纠错版本 {text(value.source_revision)} · 相关问题：{text(issue.title)}</p>
    <p className="whitespace-pre-wrap">来源纠错依据：{text(correction.reason)}<br/>原影响与处理说明：{text(correction.impact_note)}<br/>任务验收要求：{text(snapshot.completion_criteria)}</p>
    {typeof task.href === "string" && task.href.startsWith("/projects?") && <a className="text-primary underline" href={task.href}>打开原任务办理</a>}
    {typeof source.document_href === "string" && source.document_href.startsWith("/projects?") && <a className="ml-3 text-primary underline" href={source.document_href}>核对原件</a>}
    <p className="whitespace-pre-wrap">任务已登记的完成依据：{text(task.completion_evidence_ref)}</p>
    {value.source_changed === true && <p className="text-destructive">来源已有后续纠错，请核对本任务是否仍覆盖最新影响。原任务与依据保留。</p>}
    <p className="text-muted-foreground">任务进展单独记录，不自动证明原问题已验证、业务已撤销或全部后继影响已解决。</p>
    <IssueIntakeCompensationResults projectId={text(value.project_id)} bindingId={text(value.id)}/>
  </article>;
}
export function IssueIntakeCompensations({ projectId, sourceIds }: { projectId: string; sourceIds: string[] }) {
  const [data, setData] = useState<Record<string, unknown> | null>(null), [group, setGroup] = useState(0), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const [drafts, setDrafts] = useState<Record<string, Draft>>({}), [reason, setReason] = useState(""), [reviewed, setReviewed] = useState(false);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const ordered = [...new Set(sourceIds)].sort(), groupIds = ordered.slice(group * 50, group * 50 + 50), base = `/api/projects/${projectId}/issue-intake-compensations`;
  async function request(path: string, body: object) {
    const response = await fetch(`${base}${path}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) }), value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "任务安排未完成，请刷新实际任务与回执");
    return obj(value);
  }
  async function load(nextGroup = group) { const ids = ordered.slice(nextGroup * 50, nextGroup * 50 + 50); if (!ids.length) return; const next = await request("/preview", { source_ids: ids }); setData(next); setGroup(nextGroup); setReviewed(false); }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "任务安排暂不可用"); } finally { setBusy(false); } }
  const bindings = data ? arr(data.bindings) : [], entries = data ? arr(data.entries) : [];
  const options = entries.flatMap(entry => { const source = obj(entry.source), state = obj(entry.current_source); return entry.correction ? arr(entry.issues).map(issue => ({ key: `${text(source.id)}:${text(issue.id)}`, source, issue, state, correction: obj(entry.correction), existing: bindings.find(b => b.source_row_id === source.id && b.source_revision === state.revision && b.issue_id === issue.id) })) : []; });
  const selected = options.filter(item => drafts[item.key] && !item.existing);
  const valid = !!data && selected.length > 0 && selected.length <= 50 && !!reason.trim() && reviewed && selected.every(item => { const d = drafts[item.key]; return d.title.trim() && d.stage && d.owner && d.due && d.output.trim() && d.criteria.trim() && d.description.trim() && (!d.start || d.start <= d.due); });
  function update(key: string, patch: Partial<Draft>) { setDrafts(old => ({ ...old, [key]: { ...old[key], ...patch } })); setReviewed(false); }
  async function assign() {
    if (!valid || !data) return;
    const assignments = selected.map(item => { const d = drafts[item.key]; return { source_row_id: item.source.id, issue_id: item.issue.id, completion_criteria: d.criteria.trim(), new_task: { title: d.title.trim(), stage_id: d.stage, assignee_user_id: d.owner, start_date: d.start || null, due_date: d.due, expected_output: d.output.trim(), description: d.description.trim(), priority: d.priority } }; });
    const body = { source_ids: groupIds, expected_digest: data.digest, reason: reason.trim(), assignments }, signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const result = await request("", { ...body, request_id: pending.current.id });
    const results = arr(result.results); pending.current = null;
    setNotice(`批次 ${text(result.id)} 已保存：新建 ${results.filter(r => r.status === "created").length} 项，复用 ${results.filter(r => r.status === "reused").length} 项。可从项目任务或 My Work 继续办理。`);
    setDrafts(old => Object.fromEntries(Object.entries(old).filter(([key]) => !selected.some(item => item.key === key)))); setReviewed(false); await load();
  }
  if (!ordered.length) return null;
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => load()); }}>
    <summary className="cursor-pointer text-sm font-medium">为来源纠错安排实际后续任务</summary>
    <div className="mt-3 space-y-3 text-xs">
      <p className="text-muted-foreground">批量核对原资料及曾关联的问题，再安排具名负责人处理业务影响。这里列出来源关联历史，不代表全部后继引用；测试、品质、变更和其他已办记录仍须沿原业务核对。整批安排与任务回执一并保存。</p>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load())}>刷新来源、问题与已有任务</Button>
      {ordered.length > 50 && <div className="flex items-center gap-2"><Button type="button" size="sm" variant="outline" disabled={busy || group === 0} onClick={() => void act(() => load(group - 1))}>上一组来源</Button><span>第 {group + 1} / {Math.ceil(ordered.length / 50)} 组，每组最多50条；编辑内容保留在本页。</span><Button type="button" size="sm" variant="outline" disabled={busy || (group + 1) * 50 >= ordered.length} onClick={() => void act(() => load(group + 1))}>下一组来源</Button></div>}
      {bindings.map(binding => <IntakeCompensationSummary key={text(binding.id)} value={binding}/>)}
      {data && <form className="space-y-3" onSubmit={e => { e.preventDefault(); if (valid) void act(assign); }}><fieldset disabled={busy} className="space-y-3">
        <p>本组 {entries.length} 条来源，可选择尚未安排的问题；每批最多50项。来源同一处理版本下已有任务会保留。</p>
        {options.filter(item => !item.existing).map(item => { const d = drafts[item.key]; return <article key={item.key} className="space-y-2 rounded-md border p-3">
          <label className="flex gap-2 font-medium"><input type="checkbox" checked={!!d} disabled={!d && selected.length >= 50} onChange={e => { if (e.target.checked) setDrafts(old => ({ ...old, [item.key]: { title: `核对导入纠错影响：${text(item.issue.title)}`.slice(0, 512), stage: "", owner: "", start: "", due: "", output: "", criteria: "", description: "", priority: "medium" } })); else setDrafts(old => Object.fromEntries(Object.entries(old).filter(([key]) => key !== item.key))); setReviewed(false); }}/>来源 {text(item.source.locator)} → {text(item.issue.title)}</label>
          <p>原问题当前状态：{text(item.issue.status)} · 来源处理版本：{text(item.state.revision)}</p><p className="whitespace-pre-wrap">原纠错依据：{text(item.correction.reason)}<br/>影响与处理说明：{text(item.correction.impact_note)}</p>
          <a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${text(item.issue.id)}`}>核对原问题及其办理记录</a>
          {d && <><label className="block">任务标题<input required maxLength={512} className={field} value={d.title} onChange={e => update(item.key, { title: e.target.value })}/></label><div className="grid gap-2 sm:grid-cols-2"><label>阶段<select required className={field} value={d.stage} onChange={e => update(item.key, { stage: e.target.value })}><option value="">选择项目阶段</option>{arr(data.stages).map(stage => <option key={text(stage.id)} value={text(stage.id)}>{text(stage.name)}</option>)}</select></label><label>负责人<select required className={field} value={d.owner} onChange={e => update(item.key, { owner: e.target.value })}><option value="">选择具名项目成员</option>{arr(data.members).map(member => <option key={text(member.id)} value={text(member.id)}>{text(member.display_name)}</option>)}</select></label><label>开始日期<input type="date" className={field} value={d.start} onChange={e => update(item.key, { start: e.target.value })}/></label><label>截止日期<input required type="date" className={field} value={d.due} onChange={e => update(item.key, { due: e.target.value })}/></label></div><label className="block">具体处理要求<textarea required maxLength={10000} className={field} value={d.description} onChange={e => update(item.key, { description: e.target.value })}/></label><label className="block">应交付的结果<textarea required maxLength={10000} className={field} value={d.output} onChange={e => update(item.key, { output: e.target.value })}/></label><label className="block">如何核验处理完成<textarea required maxLength={10000} className={field} value={d.criteria} onChange={e => update(item.key, { criteria: e.target.value })}/></label></>}
        </article>; })}
        <label className="block">本批安排依据<textarea maxLength={4000} className={field} value={reason} onChange={e => { setReason(e.target.value); setReviewed(false); }}/></label>
        <label className="flex gap-2"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/>已核对所选 {selected.length} 项的来源、当前问题、负责人、日期及验收要求，确认创建实际后续任务。</label>
        <Button disabled={busy || !valid}>确认安排本批 {selected.length} 项任务</Button>
      </fieldset></form>}
      {notice && <p role="status" className="break-all">{notice}</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
