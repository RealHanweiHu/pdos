"use client";

import { useRef, useState } from "react";
import { IssueIntakeReferences, ReferenceReviewHistory, type ReferenceReviewDraft } from "./issue-intake-references";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type RecordValue = Record<string, unknown>;
type Evidence = { document: RecordValue; correspondence: string };
type Cursor = { before_created_at: string; before_id: string };
const fields: Record<string, string> = { title: "标题", description: "问题描述", issue_type: "问题类型", severity: "严重度", root_cause: "根因说明", resolution: "处理措施", target_date: "目标日期" };
const types: Record<string, string> = { engineering: "工程", quality: "品质", supplier: "供应商", test_failure: "测试失败", certification: "认证" };
const severities: Record<string, string> = { low: "低", medium: "中", high: "高", critical: "严重" };
const outcomes: Record<string, string> = { recorded: "登记办理进展", issue_corrected: "已纠正原问题", no_change_needed: "核对后无需改值", needs_follow_up: "仍需后续处理" };
const states: Record<string, string> = { open: "开放", analysis: "分析中", action: "处理中", verification: "验证中", closed: "已关闭" };
const field = "w-full rounded-md border bg-background p-2 text-sm";
function obj(value: unknown): RecordValue { if (!isRecord(value)) throw new Error("补偿结果资料不完整，请重新读取"); return value; }
function arr(value: unknown): RecordValue[] { if (!Array.isArray(value)) throw new Error("补偿记录不完整，请重新读取"); return value.map(obj); }
function text(value: unknown): string { return value == null || value === "" ? "未提供" : typeof value === "object" ? JSON.stringify(value) : String(value); }
function input(value: unknown): string { return value == null ? "" : String(value); }
function shown(key: string, value: unknown): string { return (key === "issue_type" ? types : key === "severity" ? severities : key === "status" ? states : {})[text(value)] ?? text(value); }
function IssueValues({ value }: { value: RecordValue }) {
  return <dl className="grid gap-2 sm:grid-cols-2">{Object.entries(fields).map(([key, label]) => <div key={key}><dt className="text-muted-foreground">{label}</dt><dd className="max-h-48 overflow-auto whitespace-pre-wrap break-words">{shown(key, value[key])}</dd></div>)}</dl>;
}
function ResultHistory({ value, projectId }: { value: RecordValue; projectId: string }) {
  const before = obj(value.before_snapshot), after = obj(value.after_snapshot), context = obj(value.context_snapshot);
  const changed = Object.keys(after).filter(key => key !== "updated_at" && JSON.stringify(after[key]) !== JSON.stringify(before[key]));
  return <details className="rounded-md border p-3">
    <summary className="cursor-pointer">第 {text(value.revision)} 次 · {outcomes[text(value.outcome)] ?? text(value.outcome)} · {text(value.actor_name)} · {text(value.created_at)}</summary>
    <div className="mt-2 space-y-2">
      <p className="whitespace-pre-wrap">办理结果：{text(value.summary)}<br/>验收要求回应：{text(value.criteria_response)}<br/>剩余影响及后续要求：{text(value.remaining)}</p>
      <p>核对的来源纠错版本：{text(value.source_revision)} · 当时任务进展：{text(obj(context.task).status)}</p>
      {(value.source_current !== true || value.issue_current !== true) && <p className="text-destructive">{value.source_current !== true ? "来源已有后续纠错。" : ""}{value.issue_current !== true ? "原问题已有后续变化。" : ""}本次结果保留，请按当前资料重新核对。</p>}
      <p>本次直接修改：{changed.length ? changed.map(key => fields[key] ?? key).join("、") : "无字段改值；已保存当时的实际问题版本"}</p>
      <details><summary className="cursor-pointer">修改前后实际问题值</summary><div className="mt-2 grid gap-3 md:grid-cols-2"><section><p className="mb-2 font-medium">办理前 · {shown("status", before.status)} · {text(before.updated_at)}</p><IssueValues value={before}/></section><section><p className="mb-2 font-medium">办理后 · {shown("status", after.status)} · {text(after.updated_at)}</p><IssueValues value={after}/></section></div></details>
      <ReferenceReviewHistory items={Array.isArray(value.business_references) ? arr(value.business_references) : []}/>
      {arr(value.evidence).map(ref => { const snapshot = obj(ref.snapshot); return <div key={text(ref.document_id)} className="rounded-md border p-2"><a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${text(ref.document_id)}`}>{text(snapshot.filename)}</a><p className="whitespace-pre-wrap">{text(ref.correspondence)}</p><p className="break-all text-muted-foreground">文件摘要：{text(snapshot.sha256)}</p>{ref.changed === true && <p className="text-destructive">该证据文件已变化或当前不可读取，原核对记录保留。</p>}</div>; })}
    </div>
  </details>;
}

export function IssueIntakeCompensationResults({ projectId, bindingId }: { projectId: string; bindingId: string }) {
  const [data, setData] = useState<RecordValue | null>(null), [history, setHistory] = useState<RecordValue[]>([]), [nextRevision, setNextRevision] = useState<number | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("recorded"), [summary, setSummary] = useState(""), [criteria, setCriteria] = useState(""), [remaining, setRemaining] = useState(""), [reviewed, setReviewed] = useState(false);
  const [businessReviews, setBusinessReviews] = useState<ReferenceReviewDraft[]>([]);
  const [patch, setPatch] = useState<Record<string, string>>({}), [selected, setSelected] = useState<Record<string, Evidence>>({});
  const [search, setSearch] = useState(""), [query, setQuery] = useState(""), [documents, setDocuments] = useState<RecordValue[]>([]), [original, setOriginal] = useState<RecordValue | null>(null), [nextDoc, setNextDoc] = useState<Cursor | null>(null);
  const pending = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/issue-intake-compensations/bindings/${bindingId}`;
  async function request(path: string, body?: object) {
    const response = await fetch(`${base}${path}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "办理未完成，请读取原结果并保留本页输入后重试");
    return obj(value);
  }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "补偿办理暂不可用"); } finally { setBusy(false); } }
  async function load() {
    const value = await request("/results"); setData(value); setHistory(arr(value.items)); setNextRevision(typeof value.next_before_revision === "number" ? value.next_before_revision : null); setReviewed(false);
  }
  async function older() {
    if (nextRevision === null) return;
    const value = await request(`/results?before_revision=${nextRevision}`);
    setHistory(old => [...old, ...arr(value.items).filter(item => !old.some(prior => prior.id === item.id))]);
    setNextRevision(typeof value.next_before_revision === "number" ? value.next_before_revision : null);
  }
  async function findDocuments(cursor?: Cursor) {
    const term = cursor ? query : search, params = new URLSearchParams({ search: term });
    if (cursor) { params.set("before_created_at", cursor.before_created_at); params.set("before_id", cursor.before_id); }
    const value = await request(`/evidence?${params}`), items = arr(value.items);
    setDocuments(old => cursor ? [...old, ...items.filter(item => !old.some(prior => prior.id === item.id))] : items);
    setOriginal(value.original ? obj(value.original) : null); setQuery(term);
    setNextDoc(isRecord(value.next) && typeof value.next.before_created_at === "string" && typeof value.next.before_id === "string" ? { before_created_at: value.next.before_created_at, before_id: value.next.before_id } : null);
  }
  const basis = data ? obj(data.basis) : null, issue = basis ? obj(basis.issue) : null, task = basis ? obj(basis.task) : null;
  const source = basis ? obj(basis.current_source) : null, binding = basis ? obj(basis.binding) : null;
  const changes = issue ? Object.fromEntries(Object.entries(patch).map(([key, value]) => [key, value.trim() || null]).filter(([key, value]) => value !== (issue[String(key)] ?? null))) : {};
  const refs = Object.values(selected);
  const valid = !!data && !!summary.trim() && !!criteria.trim() && !!remaining.trim() && reviewed
    && (!Object.keys(changes).length || issue?.status !== "closed")
    && (outcome !== "no_change_needed" || !Object.keys(changes).length)
    && (!["issue_corrected", "no_change_needed"].includes(outcome) || refs.length > 0)
    && refs.every(ref => ref.correspondence.trim())
    && businessReviews.every(review => review.explanation.trim())
    && Object.entries(patch).every(([key, value]) => !["title", "issue_type", "severity"].includes(key) || value.trim());
  function edit(key: string, value: string) { setPatch(old => ({ ...old, [key]: value })); setReviewed(false); }
  async function save() {
    if (!valid || !data) return;
    const body = { expected_digest: data.digest, outcome, summary: summary.trim(), criteria_response: criteria.trim(), remaining: remaining.trim(), changes: Object.keys(changes).length ? changes : null,
      business_references: businessReviews.map(review => ({ kind: review.reference.kind, id: review.reference.id, path_id: review.reference.path_id, expected_digest: review.reference.digest, result: review.result, explanation: review.explanation.trim() })),
      evidence: refs.map(ref => ({ document_id: ref.document.id, expected_digest: ref.document.digest, correspondence: ref.correspondence.trim() })) };
    const signature = JSON.stringify(body);
    if (pending.current?.signature !== signature) pending.current = { signature, id: crypto.randomUUID() };
    const result = await request("/results", { ...body, request_id: pending.current.id }); pending.current = null;
    setNotice(`第 ${text(result.revision)} 次办理结果已保存，可回查实际问题值与所用文件。`);
    setBusinessReviews([]); setPatch({}); setSummary(""); setCriteria(""); setRemaining(""); setSelected({}); setOutcome("recorded"); setReviewed(false);
    await load();
  }
  function choose(document: RecordValue, checked: boolean) {
    const id = text(document.id);
    setSelected(old => checked ? { ...old, [id]: { document, correspondence: "" } } : Object.fromEntries(Object.entries(old).filter(([key]) => key !== id))); setReviewed(false);
  }
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(load); }}>
    <summary className="cursor-pointer font-medium">办理补偿结果与原问题纠正</summary>
    <div className="mt-3 space-y-3 text-xs">
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(load)}>刷新当前问题、来源及结果</Button>
      <p className="text-muted-foreground">刷新保留本页编辑内容，请再次比较当前值。补偿结果具名留档；原问题的关闭、验证与任务完成仍沿原流程办理。</p>
      {basis && issue && task && source && binding && <>
        <p>原问题：<a className="text-primary underline" href={`/projects?project=${projectId}&tab=work-items&entity_id=${text(issue.id)}`}>{text(issue.title)}</a> · {states[text(issue.status)] ?? text(issue.status)} · 当前版本时间 {text(issue.updated_at)}</p>
        <p>当前来源纠错版本 {text(source.revision)} · {source.state === "withdrawn" ? "来源关联已撤回" : "来源当前已关联问题"}{source.current_issue_id && source.current_issue_id !== issue.id ? "；当前关联对象已不同于本任务的问题" : ""} · 任务进展 {text(task.status)}</p>
        {source.revision !== binding.source_revision && <p className="text-destructive">来源在任务安排后再次变化。本次提交将固定当前来源版本，请说明最新影响是否仍由本任务处理。</p>}
        <p className="whitespace-pre-wrap">任务验收要求：{text(obj(binding.snapshot).completion_criteria)}</p>
        <details><summary className="cursor-pointer">比较任务安排时与当前问题</summary><div className="mt-2 grid gap-3 md:grid-cols-2"><section><p className="mb-2 font-medium">任务安排时 · {text(obj(obj(binding.snapshot).issue).updated_at)}</p><IssueValues value={obj(obj(binding.snapshot).issue)}/></section><section><p className="mb-2 font-medium">原问题当前内容</p><IssueValues value={issue}/></section></div></details>
        <IssueIntakeReferences projectId={projectId} sourceId={text(obj(basis.source).id)} issueId={text(issue.id)} reviews={businessReviews} disabled={busy} onReviewsChange={value => { setBusinessReviews(value); setReviewed(false); }}/>
        <fieldset disabled={busy} className="space-y-3">
          <details><summary className="cursor-pointer">需要直接纠正原问题字段</summary><div className="mt-2 space-y-3">
            {issue.status === "closed" && <p className="text-destructive">问题已关闭。需要改值时，请先在原问题中受控重开。</p>}
            {Object.entries(fields).map(([key, label]) => { const enabled = Object.hasOwn(patch, key); return <div key={key} className="space-y-1">
              <label className="flex gap-2"><input type="checkbox" checked={enabled} disabled={issue.status === "closed" && !enabled} onChange={e => { if (e.target.checked) edit(key, input(issue[key])); else { setPatch(old => Object.fromEntries(Object.entries(old).filter(([k]) => k !== key))); setReviewed(false); } }}/>{label}</label>
              {enabled && (key === "issue_type" || key === "severity" ? <select aria-label={`修正${label}`} className={field} value={patch[key]} onChange={e => edit(key, e.target.value)}>{Object.entries(key === "issue_type" ? types : severities).map(([value, name]) => <option key={value} value={value}>{name}</option>)}</select>
                : key === "target_date" || key === "title" ? <input aria-label={`修正${label}`} className={field} type={key === "target_date" ? "date" : "text"} maxLength={key === "title" ? 512 : undefined} value={patch[key]} onChange={e => edit(key, e.target.value)}/>
                : <textarea aria-label={`修正${label}`} className={field} maxLength={20000} value={patch[key]} onChange={e => edit(key, e.target.value)}/>)}
            </div>; })}
          </div></details>
          {Object.keys(changes).length > 0 && <div className="overflow-x-auto"><table className="w-full text-left"><caption className="mb-2 text-left font-medium">本次将提交的字段修改</caption><thead><tr><th>字段</th><th>当前值</th><th>拟改为</th></tr></thead><tbody>{Object.entries(changes).map(([key, value]) => <tr key={key} className="border-t"><td className="p-2 align-top">{fields[key]}</td><td className="max-w-72 whitespace-pre-wrap break-words p-2 align-top">{shown(key, issue[key])}</td><td className="max-w-72 whitespace-pre-wrap break-words p-2 align-top">{value === null ? "清空" : shown(key, value)}</td></tr>)}</tbody></table></div>}
          <label className="block">本次结果<select className={field} value={outcome} onChange={e => { setOutcome(e.target.value); setReviewed(false); }}>{Object.entries(outcomes).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label>
          {outcome === "no_change_needed" && Object.keys(changes).length > 0 && <p className="text-destructive">“无需改值”不能同时提交字段修改，请调整结果或取消所选改值。</p>}
          <label className="block">处理经过与结果<textarea maxLength={10000} className={field} value={summary} onChange={e => { setSummary(e.target.value); setReviewed(false); }}/></label>
          <label className="block">逐项回应任务验收要求<textarea maxLength={10000} className={field} value={criteria} onChange={e => { setCriteria(e.target.value); setReviewed(false); }}/></label>
          <label className="block">剩余影响、后续要求或无需继续处理的理由<textarea maxLength={10000} className={field} value={remaining} onChange={e => { setRemaining(e.target.value); setReviewed(false); }}/></label>
          <details onToggle={e => { if (e.currentTarget.open && !documents.length && !busy) void act(() => findDocuments()); }}><summary className="cursor-pointer font-medium">选择实际证据文件（最多10份）</summary>
            <div className="mt-2 space-y-2"><p>选择本项目内部原件并说明对应关系。“已纠正”或“无需改值”须有实际文件依据。</p>
              <label className="block">按文件名查找<input className={field} maxLength={200} value={search} onChange={e => setSearch(e.target.value)}/></label>
              <Button type="button" size="sm" variant="outline" onClick={() => void act(() => findDocuments())}>查找文件</Button>
              {[...(original ? [original] : []), ...documents.filter(doc => doc.id !== original?.id)].map(doc => <label key={text(doc.id)} className="flex items-start gap-2"><input type="checkbox" checked={!!selected[text(doc.id)]} disabled={!selected[text(doc.id)] && refs.length >= 10} onChange={e => choose(doc, e.target.checked)}/><span><a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${text(doc.id)}`}>{text(doc.filename)}</a>{doc.id === original?.id ? " · 本条导入原件" : ""}<br/><span className="text-muted-foreground">{text(doc.created_at)} · {text(doc.size_bytes)} 字节</span></span></label>)}
              {nextDoc && <Button type="button" size="sm" variant="outline" onClick={() => void act(() => findDocuments(nextDoc))}>继续查找较早文件</Button>}
            </div>
          </details>
          {refs.map(ref => { const id = text(ref.document.id); return <div key={id} className="space-y-2 rounded-md border p-2"><p>已选：{text(ref.document.filename)}</p><p className="break-all text-muted-foreground">原文件摘要：{text(ref.document.sha256)}</p><label className="block">文件中支持本次结果的具体位置与内容<textarea maxLength={4000} className={field} value={ref.correspondence} onChange={e => { const value = e.target.value; setSelected(old => ({ ...old, [id]: { ...old[id], correspondence: value } })); setReviewed(false); }}/></label><Button type="button" size="sm" variant="outline" onClick={() => choose(ref.document, false)}>移除此引用</Button></div>; })}
          <label className="flex gap-2"><input type="checkbox" checked={reviewed} onChange={e => setReviewed(e.target.checked)}/>已核对当前来源、原问题值、上述改值和所选证据，确认登记本次办理结果。</label>
          <Button type="button" disabled={!valid} onClick={() => void act(save)}>保存本次办理结果</Button>
        </fieldset>
      </>}
      {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
      {history.length > 0 && <div className="space-y-2"><p className="font-medium">具名办理历史</p>{history.map(item => <ResultHistory key={text(item.id)} value={item} projectId={projectId}/>)}{nextRevision !== null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void act(older)}>查看更早结果</Button>}</div>}
    </div>
  </details>;
}
