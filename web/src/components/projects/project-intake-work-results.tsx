"use client";

import { DecisionIntakeReferences } from "./decision-intake-references";
import { ReferenceReviewHistory, type ReferenceReviewDraft } from "./issue-intake-references";
import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
type Evidence = { document_id: string; expected_digest: string; correspondence: string; filename: string };
const text = (v: unknown) => v == null ? "未提供" : String(v);
const rows = (v: unknown): Row[] => Array.isArray(v) ? v.filter(isRecord) : [];
const obj = (v: unknown): Row => isRecord(v) ? v : {};
const labels: Record<string, string> = { progress: "记录进展", addressed: "本项已核对完成", no_change_needed: "本项无需修改", follow_up: "仍需后续处理" };
const field = "w-full rounded-md border bg-background p-2 text-sm";

function BusinessBasis({ value }: { value: Row }) {
  return <div className="space-y-1 whitespace-pre-wrap"><p>{text(value.title)} · {text(value.status ?? value.outcome)}</p>{["description", "outcome", "rationale", "consequence"].filter(key => typeof value[key] === "string").map(key => <p key={key}>{text(value[key])}</p>)}</div>;
}

export function ProjectIntakeWorkResults({ projectId, bindingId }: { projectId: string; bindingId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const [outcome, setOutcome] = useState("progress"), [summary, setSummary] = useState(""), [criteria, setCriteria] = useState(""), [remaining, setRemaining] = useState(""), [reviewed, setReviewed] = useState(false);
  const [query, setQuery] = useState(""), [documents, setDocuments] = useState<Row | null>(null), [evidence, setEvidence] = useState<Evidence[]>([]);
  const [businessReviews, setBusinessReviews] = useState<ReferenceReviewDraft[]>([]), [readingReferences, setReadingReferences] = useState(false);
  const requestRef = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/intake`, path = `/work/${bindingId}/results`;
  async function request(suffix: string, payload?: unknown): Promise<Row> {
    const response = await fetch(base + suffix, payload ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(payload) } : { cache: "no-store" });
    const body: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(body)) throw new Error(isRecord(body) && typeof body.detail === "string" ? body.detail : "暂未取得回执，请保留输入后重试或刷新");
    return body;
  }
  async function load(more = false) {
    setBusy(true); setError(null);
    try {
      const value = await request(path + (more && data?.next_revision ? `?before_revision=${data.next_revision}` : ""));
      setData(old => more ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); setReviewed(false);
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  async function findDocuments(more = false) {
    setBusy(true); setError(null);
    try { const value = await request(`/sources?search=${encodeURIComponent(query)}${more && documents?.next_id ? `&before_id=${documents.next_id}` : ""}`); setDocuments(old => more ? { ...value, items: [...rows(old?.items), ...rows(value.items)] } : value); }
    catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  async function save() {
    if (!data) return;
    setBusy(true); setError(null); setNotice(null);
    const body = { expected_revision: data.result_revision, expected_context_digest: data.context_digest, outcome, summary, criteria_response: criteria, remaining, evidence: evidence.map(({ document_id, expected_digest, correspondence }) => ({ document_id, expected_digest, correspondence })), business_reviews: businessReviews.map(item => ({ kind: item.reference.kind, id: item.reference.id, path_id: item.reference.path_id, expected_digest: item.reference.digest, result: item.result, explanation: item.explanation })), reviewed };
    const signature = JSON.stringify(body);
    if (requestRef.current?.signature !== signature) requestRef.current = { signature, id: crypto.randomUUID() };
    try {
      const result = await request(path, { ...body, request_id: requestRef.current.id });
      setNotice(`结果版本 ${text(result.revision)} 已登记，原任务及业务记录保留。`);
      setReviewed(false);
      setData(await request(path));
      requestRef.current = null;
    } catch (e) { setError(e instanceof Error ? e.message : "登记失败"); } finally { setBusy(false); }
  }
  const context = obj(data?.context), task = obj(context.task), business = obj(context.business_source), original = obj(data?.original_business_source);
  const complete = outcome === "addressed" || outcome === "no_change_needed";
  return <details className="rounded-md border p-3 text-xs" onToggle={e => { if (e.currentTarget === e.target && e.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer font-medium">办理结果与证据</summary>
    <div className="mt-2 space-y-3">
      <p>按实际任务登记具名结果。完成结论需要任务已完成、实际文件证据及逐项交付要求回应；本项结果不代表整个项目或全部下游影响已处理。</p>
      <Button type="button" variant="outline" size="sm" disabled={busy} onClick={() => void load()}>刷新任务、来源与结果</Button>
      {data && <>
        <p><a className="text-primary underline" href={text(task.href)}>{text(task.title)}</a> · 当前任务状态 {text(task.status)}</p>
        <p className="whitespace-pre-wrap">当前交付要求：{text(task.expected_output)}</p>
        {Object.keys(original).length > 0 && <p>原业务依据：<a className="text-primary underline" href={text(original.href)}>{text(original.title)}</a></p>}
        {Object.keys(business).length > 0 && <details><summary className="cursor-pointer">核对原安排与当前业务记录</summary><p>原安排依据</p><BusinessBasis value={original}/><p className="mt-2">当前业务记录</p><BusinessBasis value={business}/></details>}
        {data.business_source_changed === true && <p className="text-destructive">业务来源或历史关联已变化，请核对原安排与当前记录。本次结果固定当前资料，旧结果保留。</p>}
        {context.source_available === false && <p className="text-destructive">原业务来源当前不可核对，只能记录进展或后续要求。</p>}
        {rows(context.original_sources).map(source => { const snapshot = obj(source.snapshot), document = obj(snapshot.document); return <details key={text(source.key)}><summary className="cursor-pointer">{text(document.filename)} · {text(snapshot.locator)} · {source.current === true ? "原文依据一致" : "原文依据需重核"}</summary><p className="whitespace-pre-wrap">{text(snapshot.quote)}</p></details>; })}
        <fieldset disabled={busy} className="space-y-2" onChange={() => { setReviewed(false); setNotice(null); }}>
          <label className="block">结果<select className={field} value={outcome} onChange={e => setOutcome(e.target.value)}>{Object.entries(labels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
          <label className="block">实际办理说明<textarea className={field} rows={3} maxLength={10000} value={summary} onChange={e => setSummary(e.target.value)}/></label>
          <label className="block">交付要求逐项回应<textarea className={field} rows={3} maxLength={10000} value={criteria} onChange={e => setCriteria(e.target.value)}/></label>
          <label className="block">剩余事项与后续安排（无则说明依据）<textarea className={field} rows={3} maxLength={10000} value={remaining} onChange={e => setRemaining(e.target.value)}/></label>
          <details><summary className="cursor-pointer">选择实际项目文件证据（最多10份）</summary><div className="my-2 space-y-2"><input aria-label="证据文件名关键词" className={field} value={query} onChange={e => { setQuery(e.target.value); setDocuments(null); }}/><Button type="button" size="sm" variant="outline" onClick={() => void findDocuments()}>查找文件</Button>{rows(documents?.items).map(document => <div key={text(document.id)} className="flex items-center justify-between gap-2"><a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&document_id=${document.id}`}>{text(document.filename)}</a><Button type="button" size="sm" variant="outline" disabled={evidence.length >= 10 || evidence.some(item => item.document_id === document.id)} onClick={() => { setEvidence(old => [...old, { document_id: text(document.id), expected_digest: text(document.digest), correspondence: "", filename: text(document.filename) }]); setReviewed(false); }}>选择</Button></div>)}{documents?.next_id != null && <Button type="button" size="sm" variant="outline" onClick={() => void findDocuments(true)}>更多文件</Button>}</div></details>
          {evidence.map(item => <div key={item.document_id} className="space-y-1 rounded-md border p-2"><p>{item.filename}</p><label className="block">页码／位置及支持结论的具体依据<textarea className={field} maxLength={4000} value={item.correspondence} onChange={e => setEvidence(old => old.map(value => value.document_id === item.document_id ? { ...value, correspondence: e.target.value } : value))}/></label><Button type="button" size="sm" variant="outline" onClick={() => { setEvidence(old => old.filter(value => value.document_id !== item.document_id)); setReviewed(false); }}>移除此选择</Button></div>)}
          {business.kind === "decision" && typeof business.id === "string" && <DecisionIntakeReferences projectId={projectId} decisionId={business.id} reviews={businessReviews} onChange={value => { setBusinessReviews(value); setReviewed(false); }} disabled={busy} onBusy={setReadingReferences}/>}
        </fieldset>
        <label className="flex items-start gap-2"><input type="checkbox" disabled={busy || readingReferences} checked={reviewed} onChange={e => setReviewed(e.target.checked)}/>我已核对当前任务、业务来源、原文依据和所选证据，以上说明是本次实际办理结果。</label>
        {complete && <p>请先在实际任务完成办理；无需修改的结论允许任务已完成或按原流程跳过。来源不可核对时保留进展并补齐依据。</p>}
        <Button type="button" size="sm" disabled={busy || readingReferences || businessReviews.some(item => !item.explanation.trim() || (complete && item.result === "follow_up")) || !reviewed || !summary.trim() || !criteria.trim() || !remaining.trim() || evidence.some(item => !item.correspondence.trim()) || (complete && !evidence.length)} onClick={() => void save()}>登记不可变结果版本</Button>
        {rows(data.items).map(result => <article key={text(result.id)} className="space-y-1 border-t pt-2"><p>结果 {text(result.revision)} · {labels[text(result.outcome)] ?? text(result.outcome)} · {text(result.actor_name)} · {text(result.created_at)}</p>{result.current !== true && <p className="text-destructive">需要重核：{Array.isArray(result.recheck_reasons) ? result.recheck_reasons.join("；") : "当前依据已变化"}</p>}<p className="whitespace-pre-wrap">{text(result.summary)}</p><p className="whitespace-pre-wrap">交付回应：{text(result.criteria_response)}</p><p className="whitespace-pre-wrap">后续事项：{text(result.remaining)}</p><details><summary className="cursor-pointer">登记时的任务与业务依据</summary><p>任务：{text(obj(obj(result.context_snapshot).task).title)} · {text(obj(obj(result.context_snapshot).task).status)}</p><p className="whitespace-pre-wrap">交付要求：{text(obj(obj(result.context_snapshot).task).expected_output)}</p>{isRecord(obj(result.context_snapshot).business_source) && <BusinessBasis value={obj(obj(result.context_snapshot).business_source)}/>}</details><ReferenceReviewHistory items={rows(result.business_reviews)}/>{rows(result.evidence).map(item => <p className="whitespace-pre-wrap" key={text(item.document_id)}><a className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&document_id=${item.document_id}`}>{text(obj(rows(result.evidence_snapshot).find(original => original.document_id === item.document_id)?.current).filename ?? obj(item.current).filename)}</a> · {text(item.correspondence)}{item.changed === true ? " · 证据已变化，请重核" : ""}</p>)}</article>)}
        {!rows(data.items).length && <p>尚无办理结果记录。</p>}
        {data.next_revision != null && <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load(true)}>读取更早结果</Button>}
      </>}
      {notice && <p role="status">{notice}</p>}{error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
