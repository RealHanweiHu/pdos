"use client";

import { RiskResultEvidence, type EvidenceFile } from "./risk-result-evidence";
import Link from "next/link";
import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
const row = (value: unknown): Row => isRecord(value) ? value : {};
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: unknown) => value == null ? "" : String(value);
const key = (item: Row) => `${text(item.kind)}:${text(item.id)}`;
const input = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const outcomes: Record<string, string> = { unaffected: "核对后不受影响", handled: "已按原流程处理", needs_work: "仍需继续处理" };
const actions: Record<string, string> = { submitted: "已提交待接收", accepted: "已接收", returned: "已退回" };
type Answer = { outcome: string; explanation: string; evidence: string; document_ids: string[] };
class ResultError extends Error { constructor(message: string, public status: number) { super(message); } }
export function RiskFollowupResults({ projectId, riskId, taskId, onRecorded }: { projectId: string; riskId: string; taskId: string; onRecorded?: () => void }) {
  const [replacementReceiver, setReplacementReceiver] = useState(""), [replacementReason, setReplacementReason] = useState("");
  const [files, setFiles] = useState<Record<string, EvidenceFile>>({});
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [answers, setAnswers] = useState<Record<string, Answer>>({}), [summary, setSummary] = useState(""), [receiver, setReceiver] = useState(""), [comment, setComment] = useState("");
  const [preview, setPreview] = useState<Row | null>(null), [pending, setPending] = useState<Row | null>(null), [saved, setSaved] = useState<Row | null>(null), [lookup, setLookup] = useState("");
  const base = `/api/projects/${projectId}/risks/${riskId}/follow-up/${taskId}/results`;
  async function request(body?: Row, requestId?: string): Promise<Row> {
    const response = await fetch(base + (requestId ? `?request_id=${encodeURIComponent(requestId)}` : ""), { method: body ? "POST" : "GET", cache: "no-store", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: body ? JSON.stringify(body) : undefined });
    const value = await responseBody(response);
    if (!response.ok) throw new ResultError(text(row(row(value).detail).message) || "未取得结果，请保留原请求编号回查", response.status);
    if (!isRecord(value)) throw new Error("结果格式不完整");
    return value;
  }
  async function load() {
    setBusy(true); setError(""); setPreview(null);
    try {
      const value = await request();
      if (typeof value.digest !== "string" || !isRecord(value.basis) || !Array.isArray(value.basis.references) || !Array.isArray(value.history)) throw new Error("结果资料不完整，请刷新");
      setData(value);
      const payload = row(row(value.submission).payload);
      setAnswers(old => { const next = { ...old }; for (const answer of rows(payload.references)) { if (!next[key(answer)]) next[key(answer)] = { outcome: text(answer.outcome), explanation: text(answer.explanation), evidence: text(answer.evidence), document_ids: Array.isArray(answer.document_ids) ? answer.document_ids.filter((id): id is string => typeof id === "string") : [] }; } return next; });
      setFiles(old => {
        const next = { ...old };
        for (const evidence of rows(payload.evidence)) {
          if (!isRecord(evidence.snapshot) || next[text(evidence.document_id)]) continue;
          next[text(evidence.document_id)] = { document: { ...evidence.snapshot, digest: evidence.expected_digest, changed: evidence.changed }, correspondence: text(evidence.correspondence) };
        }
        return next;
      });
      setSummary(old => old || text(payload.summary));
      setReceiver(old => old || text(row(value.submission).receiver_user_id));
    } catch (e) { setData(null); setError(e instanceof Error ? e.message : "读取失败"); }
    finally { setBusy(false); }
  }
  async function save(body: Row, replay = false) {
    setPending(body); setLookup(text(body.request_id)); setBusy(true); setError("");
    try {
      const value = await request(body);
      if (typeof value.id !== "string" || value.request_id !== body.request_id) throw new Error("回执不完整，请回查原请求");
      setSaved(value); setPending(null); setPreview(null); setData(null); setComment(""); setReplacementReceiver(""); setReplacementReason(""); onRecorded?.();
      await load();
    } catch (e) {
      if (e instanceof ResultError && (replay ? [409, 422] : [400, 401, 403, 404, 409, 422]).includes(e.status)) { setPending(null); setPreview(null); setData(null); }
      setError(e instanceof Error ? e.message : "办理未完成");
    } finally { setBusy(false); }
  }
  async function recover() {
    const requestId = text(pending?.request_id) || lookup.trim();
    if (!requestId) return;
    setBusy(true); setError("");
    try {
      const value = await request(undefined, requestId);
      if (typeof value.id !== "string" || value.request_id !== requestId) throw new Error("回执不完整");
      setSaved(value);
      if (pending?.request_id === requestId) { setPending(null); setPreview(null); setData(null); onRecorded?.(); await load(); }
    } catch (e) { setError(`${e instanceof Error ? e.message : "回查失败"}；未查到不代表未提交，可稍后继续回查。`); }
    finally { setBusy(false); }
  }
  const basis = row(data?.basis), task = row(basis.task), references = rows(basis.references), latest = row(data?.latest), submission = row(data?.submission), payload = row(submission.payload);
  const unresolved = rows(payload.references).some(ref => ref.outcome === "needs_work");
  const validFiles = Object.keys(files).length > 0 && Object.values(files).every(file => file.correspondence.trim() && file.document.changed !== true)
    && references.every(ref => { const answer = answers[key(ref)]; return answer && answer.document_ids.every(id => !!files[id]) && (answer.outcome === "needs_work" || answer.document_ids.length > 0); });
  function changeFiles(next: Record<string, EvidenceFile>) {
    setFiles(next);
    setAnswers(old => Object.fromEntries(Object.entries(old).map(([id, answer]) => [id, { ...answer, document_ids: answer.document_ids.filter(documentId => !!next[documentId]) }])));
  }
  function resultView(item: Row) {
    const p = row(item.payload), originalRefs = rows(row(item.basis).references);
    return <div className="space-y-2 rounded-lg border p-3" key={text(item.id)}>
      <p className="font-medium">第 {text(item.revision)} 版 · {actions[text(item.action)] ?? text(item.action)} · {text(p.actor_name)}</p>
      {isRecord(p.receiver_change) ? <p className="rounded-md border p-2">接收人由 {text(p.receiver_change.previous_receiver_name) || text(p.receiver_change.previous_receiver_user_id)} 更换为 {text(p.receiver_name)}，沿用第 {text(p.receiver_change.previous_revision)} 版结果与证据。变更原因：{text(p.receiver_change.reason)}</p> : null}
      <p>{text(p.summary)}</p><p className="text-muted-foreground">指定接收人：{text(p.receiver_name)} · {text(item.created_at)}</p>
      {rows(p.evidence).map(file => <div className="rounded-lg border p-2" key={text(file.document_id)}>{isRecord(file.snapshot) ? <><Link className="text-primary underline" href={`/projects?project=${projectId}&tab=documents&entity_id=${text(file.document_id)}`}>{text(file.snapshot.filename)}</Link><p className="break-all text-muted-foreground">原文件摘要：{text(file.snapshot.sha256)}</p></> : <p>原证据文件当前不可读取</p>}<p>{text(file.correspondence)}</p>{file.changed === true ? <p className="text-destructive">文件已变化或不可读取，原结果保留，接收前需重新核对。</p> : null}</div>)}
      {item.action === "submitted" && !rows(p.evidence).length ? <p className="text-destructive">此历史提交未固定项目原文件，新接收前需补充后重新提交。</p> : null}
      {rows(p.references).map(ref => { const source = originalRefs.find(r => key(r) === key(ref)); return <p key={key(ref)}><strong>{text(row(source?.current).title) || text(row(source?.original).title)}</strong>：{outcomes[text(ref.outcome)]}；{text(ref.explanation)}；证据：{text(ref.evidence)}；所用文件：{Array.isArray(ref.document_ids) ? ref.document_ids.map(id => { const file = rows(p.evidence).find(f => f.document_id === id); return text(row(file?.snapshot).filename) || "原文件当前不可读"; }).join("、") || "历史记录未绑定文件" : "历史记录未绑定文件"}</p>; })}
    </div>;
  }
  return <details className="mt-3 rounded-lg border p-3 text-xs" onToggle={e => { if (e.target === e.currentTarget && e.currentTarget.open && !data && !busy && !pending) void load(); }}>
    <summary className="cursor-pointer font-medium">逐引用处理结果 / 具名接收</summary>
    <div className="mt-3 space-y-3">
      <p className="text-muted-foreground">任务完成后，由当前负责人逐项说明结果，另一位具名成员接收或退回。接收仅确认本次处理结果，风险关闭及原会议/Gate决定继续走原流程。</p>
      <Button type="button" size="sm" variant="outline" disabled={busy || !!pending} onClick={() => void load()}>刷新当前资料（保留输入）</Button>
      {error ? <p role="alert" className="text-destructive">{error}</p> : null}
      {data ? <>
        <p>任务：{text(task.title)} · 完成证据：{text(task.completion_evidence_ref) || "尚未登记"}</p>
        <p>当前结果：{latest.action ? actions[text(latest.action)] : "尚未提交"}{data.source_changed ? "；提交后的来源或任务已变化，须重新核对" : ""}</p>
        {submission.id ? resultView(submission) : null}
        {data.can_change_receiver === true ? <fieldset className="space-y-2 rounded-lg border p-3" disabled={busy || !!pending || !!preview}><legend className="font-medium">更换当前待接收结果的接收人</legend><p className="text-muted-foreground">保留原处理结论与文件证据，生成新版本交给另一位成员独立接收。这里不使用下方未提交的内容修改，原接收人及历次回执保留。</p><label className="block">新接收人<select required className={input} value={replacementReceiver} onChange={e => setReplacementReceiver(e.target.value)}><option value="">选择另一位有效项目成员</option>{rows(data.people).filter(person => person.id !== data.actor_id && person.id !== submission.receiver_user_id).map(person => <option key={text(person.id)} value={text(person.id)}>{text(person.display_name)}</option>)}</select></label><label className="block">人员变更原因<textarea className={input} maxLength={4000} value={replacementReason} onChange={e => setReplacementReason(e.target.value)}/></label><Button type="button" size="sm" variant="outline" disabled={!replacementReceiver || !replacementReason.trim()} onClick={() => setPreview({ request_id: crypto.randomUUID(), expected_digest: data.digest, action: "submitted", receiver_user_id: replacementReceiver, summary: payload.summary, references: rows(payload.references).map(ref => ({ kind: ref.kind, id: ref.id, outcome: ref.outcome, explanation: ref.explanation, evidence: ref.evidence, document_ids: ref.document_ids ?? [] })), evidence: rows(payload.evidence).map(file => ({ document_id: file.document_id, expected_digest: file.expected_digest, correspondence: file.correspondence })), receiver_change: { previous_submission_id: submission.id, reason: replacementReason.trim() } })}>预览接收人变更</Button></fieldset> : null}
        {data.can_submit === true ? <form className="space-y-3" onSubmit={e => { e.preventDefault(); setPreview({ request_id: crypto.randomUUID(), expected_digest: data.digest, action: "submitted", receiver_user_id: receiver, summary,
          references: references.map(ref => ({ kind: ref.kind, id: ref.id, ...answers[key(ref)] })), evidence: Object.values(files).map(file => ({ document_id: file.document.id, expected_digest: file.document.digest, correspondence: file.correspondence.trim() })) }); }}>
          <fieldset className="space-y-3" disabled={busy || !!pending || !!preview}>
            <label className="block">总处理结果和剩余事项<textarea required maxLength={10000} className={input} value={summary} onChange={e => setSummary(e.target.value)} /></label>
            <label className="block">独立接收人<select required className={input} value={receiver} onChange={e => setReceiver(e.target.value)}><option value="">选择另一位项目成员</option>{rows(data.people).filter(p => p.id !== data.actor_id).map(p => <option value={text(p.id)} key={text(p.id)}>{text(p.display_name)}</option>)}</select></label>
            <RiskResultEvidence base={base} files={files} onChange={changeFiles} disabled={busy || !!pending || !!preview} />
            {references.map(ref => { const id = key(ref), answer = answers[id] ?? { outcome: "", explanation: "", evidence: "", document_ids: [] }; const change = (patch: Partial<Answer>) => setAnswers(old => ({ ...old, [id]: { ...answer, ...patch } })); return <div className="rounded-lg border p-3" key={id}>
              <p className="font-medium">{text(ref.label)} · {text(row(ref.current).title) || text(row(ref.original).title)}</p>
              <p className="text-muted-foreground">{!ref.original ? "安排后新增引用" : !ref.current ? "原引用当前已解除，仍须说明处理结果" : "原引用及当前状态已固定到本次提交"}</p>
              <label className="block">结论<select required className={input} value={answer.outcome} onChange={e => change({ outcome: e.target.value })}><option value="">逐项核对后选择</option>{Object.entries(outcomes).map(([v, label]) => <option key={v} value={v}>{label}</option>)}</select></label>
              <label className="block">实际处理或不受影响的依据<textarea required maxLength={4000} className={input} value={answer.explanation} onChange={e => change({ explanation: e.target.value })} /></label>
              <fieldset className="mt-2 space-y-1"><legend>本项所用文件</legend>{Object.entries(files).map(([documentId, file]) => <label className="flex items-center gap-2" key={documentId}><input type="checkbox" checked={answer.document_ids.includes(documentId)} onChange={e => change({ document_ids: e.target.checked ? [...answer.document_ids, documentId] : answer.document_ids.filter(id => id !== documentId) })} />{text(file.document.filename)}</label>)}</fieldset>
              <label className="block">对应证据 / 原业务办理记录<textarea required maxLength={4000} className={input} value={answer.evidence} onChange={e => change({ evidence: e.target.value })} /></label>
            </div>; })}
            <Button type="submit" size="sm" disabled={!validFiles}>预览本次结果</Button>
          </fieldset>
        </form> : <p className="text-muted-foreground">只有当前任务负责人在完成任务并登记证据后可以提交结果。</p>}
        {data.can_review === true ? <div className="space-y-2 rounded-lg border p-3"><label className="block">接收意见 / 退回原因<textarea className={input} maxLength={10000} value={comment} disabled={busy || !!pending || !!preview} onChange={e => setComment(e.target.value)} /></label>
          <div className="flex gap-2">{["accepted", "returned"].map(action => <Button type="button" size="sm" variant={action === "returned" ? "outline" : "default"} key={action} disabled={busy || !!pending || !!preview || !comment.trim() || (action === "accepted" && (data.source_changed === true || data.evidence_changed === true || unresolved))} onClick={() => setPreview({ request_id: crypto.randomUUID(), expected_digest: data.digest, action, submission_id: latest.id, summary: comment })}>{action === "accepted" ? "预览接收" : "预览退回"}</Button>)}</div>
          {data.evidence_changed === true ? <p>项目证据缺失、版本变化或不可读取，请退回补充后再接收。</p> : null}
          {unresolved ? <p>仍有需要继续处理的引用，请退回补齐。</p> : null}
        </div> : null}
        {rows(data.history).length ? <details><summary className="cursor-pointer">结果与接收历史（最近20条）</summary><div className="mt-2 space-y-2">{rows(data.history).map(resultView)}</div>{data.has_more ? <p>还有更早历史，原记录继续保留。</p> : null}</details> : null}
      </> : null}
      {preview ? <div className="space-y-2 rounded-lg border border-primary/40 p-3" aria-label="结果办理预览"><p className="font-medium">{preview.receiver_change ? "保留原结果和证据，更换接收人后重新提交" : preview.action === "submitted" ? `提交 ${rows(preview.references).length} 项引用结果供独立接收` : preview.action === "accepted" ? "确认接收本次处理结果" : "退回处理人补齐"}</p>{preview.action === "submitted" ? <p>接收人：{text(rows(data?.people).find(person => person.id === preview.receiver_user_id)?.display_name) || text(preview.receiver_user_id)}</p> : null}{preview.receiver_change ? <p>原接收人：{text(payload.receiver_name)} · 变更原因：{text(row(preview.receiver_change).reason)}</p> : null}<p>{text(preview.summary)}</p>{rows(preview.evidence).map(file => <p key={text(file.document_id)}>固定文件：{text(preview.receiver_change ? row(rows(payload.evidence).find(original => original.document_id === file.document_id)?.snapshot).filename : files[text(file.document_id)]?.document.filename)} · {text(file.correspondence)}</p>)}{rows(preview.references).map(ref => <p key={key(ref)}>{outcomes[text(ref.outcome)]} · {text(ref.explanation)} · {text(ref.evidence)}</p>)}<div className="flex gap-2"><Button type="button" size="sm" disabled={busy || !!pending} onClick={() => void save(preview)}>确认办理</Button><Button type="button" size="sm" variant="outline" disabled={busy || !!pending} onClick={() => setPreview(null)}>返回修改</Button></div></div> : null}
      {pending ? <div className="space-y-2"><p>原请求 {text(pending.request_id)} 的结果待确认</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void recover()}>回查原请求</Button><Button type="button" size="sm" disabled={busy} onClick={() => void save(pending, true)}>用原请求重试</Button></div> : null}
      {saved ? <div><p className="mb-2">本次回执（原请求 {text(saved.request_id)}）</p>{resultView(saved)}</div> : null}
      <div className="flex gap-2"><input aria-label="本人结果请求编号" className={input} value={lookup} disabled={busy || !!pending} onChange={e => setLookup(e.target.value)} /><Button type="button" size="sm" variant="outline" disabled={busy || !lookup.trim()} onClick={() => void recover()}>回查</Button></div>
    </div>
  </details>;
}
