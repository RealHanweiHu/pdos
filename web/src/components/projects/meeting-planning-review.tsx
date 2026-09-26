"use client";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
type Agenda = { original_number: number | null; title: string; detail: string; expected_output: string; owner_user_id: string | null };
type Person = { user_id: string; participation: "required" | "optional" };
type Draft = { title: string; meeting_type: string; purpose: string; timezone: string; scheduled_start_at: string; scheduled_end_at: string; participants: Person[]; agenda: Agenda[]; question_responses: string[] };
type Pending = { action: "review" | "apply"; body: Row; id: string };
const list = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const text = (value: unknown) => value == null ? "" : String(value);
const record = (value: unknown): Row => isRecord(value) ? value : {};
const types: Record<string, string> = { weekly: "项目周例会", material: "物料会", special: "专题会", technical_review: "技术评审", decision_checkpoint: "决策检查点", pilot_review: "试制评审", project_retrospective: "项目复盘" };
const fieldNames: Record<string, string> = { title: "标题", meeting_type: "会议类型", purpose: "目的", participants: "参会名单", schedule: "时间安排", agenda: "议题" };
const local = (value: unknown) => { if (!value) return ""; const date = new Date(String(value)); if (!Number.isFinite(date.getTime())) return ""; return new Date(date.getTime() - date.getTimezoneOffset() * 60000).toISOString().slice(0, 16); };
const strings = (value: unknown): string[] => Array.isArray(value) ? value.map(String) : [];

function initial(data: Row): Draft {
  const finding = record(data.finding), payload = record(finding.proposed_payload), assessment = record(payload.assessment), plan = record(assessment.plan), source = record(data.source);
  return { title: text(plan.title), meeting_type: text(plan.meeting_type), purpose: text(plan.purpose), timezone: Intl.DateTimeFormat().resolvedOptions().timeZone, scheduled_start_at: local(source.proposed_start_at), scheduled_end_at: local(source.proposed_end_at), participants: list(plan.participants).filter(p => p.user_id !== source.author_id).map(p => ({ user_id: text(p.user_id), participation: p.participation === "optional" ? "optional" : "required" })), agenda: list(plan.agenda).map((a, i) => ({ original_number: i + 1, title: text(a.title), detail: text(a.detail), expected_output: text(a.expected_output), owner_user_id: a.suggested_owner_id ? text(a.suggested_owner_id) : null })), question_responses: strings(assessment.open_questions).map(() => "") };
}
function serialize(draft: Draft): Draft {
  const start = new Date(draft.scheduled_start_at), end = new Date(draft.scheduled_end_at);
  if (!Number.isFinite(start.getTime()) || !Number.isFinite(end.getTime())) throw new Error("请填写正式开始和结束时间");
  return { ...draft, scheduled_start_at: start.toISOString(), scheduled_end_at: end.toISOString() };
}

export function MeetingPlanningReview({ projectId, findingId }: { projectId: string; findingId: string }) {
  const [data, setData] = useState<Row | null>(null), [draft, setDraft] = useState<Draft | null>(null), [preview, setPreview] = useState<Row | null>(null);
  const [comment, setComment] = useState(""), [confirmed, setConfirmed] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [pendingState, setPendingState] = useState(false);
  const pending = useRef<Pending | null>(null);
  const base = `/api/projects/${projectId}/meetings/planning-findings/${findingId}`;
  async function request(action = "", body?: object): Promise<Row> {
    const response = await fetch(`${base}${action ? `/${action}` : ""}`, body ? { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : { cache: "no-store" });
    const value: unknown = await responseBody(response).catch(() => null);
    if (!response.ok || !isRecord(value)) { const error = new Error(isRecord(value) && isRecord(value.detail) ? text(value.detail.message) || "输入未通过核对，请检查表单" : response.status === 422 ? "请检查必填内容、议题负责人及时间后重试" : "回执尚未读取成功，请核对原请求"); if ([400, 401, 403, 404, 409, 422].includes(response.status)) Object.assign(error, { rejectedInput: true }); throw error; }
    return value;
  }
  async function load() {
    setBusy(true); setError(null);
    try {
      const value = await request();
      if (record(value.finding).id !== findingId) throw new Error("核对回执不匹配，请重读");
      setData(value); setDraft(prior => prior ?? initial(value));
      if (pending.current && list(value.actions).some(a => record(a.detail).request_id === pending.current?.id)) { pending.current = null; setPendingState(false); }
    } catch (e) { setError(e instanceof Error ? e.message : "读取失败"); } finally { setBusy(false); }
  }
  function edit(value: Partial<Draft>) { setDraft(prior => prior ? { ...prior, ...value } : prior); setPreview(null); setConfirmed(false); }
  async function showPreview() {
    if (!draft) return;
    setBusy(true); setError(null);
    try { setPreview(await request("preview", serialize(draft))); } catch (e) { setError(e instanceof Error ? e.message : "预览失败"); } finally { setBusy(false); }
  }
  async function submit(action: "review" | "apply", decision?: "accepted" | "rejected") {
    setBusy(true); setError(null);
    try {
      if (!pending.current) {
        const id = crypto.randomUUID();
        const body: Row = action === "apply" ? { request_id: id, accepted_digest: data?.accepted_digest, confirmed: true } : { request_id: id, decision, comment, ...(decision === "accepted" && draft ? { edited: serialize(draft), preview_digest: preview?.preview_digest } : {}) };
        pending.current = { action, body, id }; setPendingState(true);
      }
      const original = pending.current;
      const value = await request(original.action, original.body);
      if (record(value.finding).id !== findingId || !list(value.actions).some(a => record(a.detail).request_id === original.id)) throw new Error("原请求回执尚未完整返回，请读取后沿原请求核对");
      pending.current = null; setPendingState(false); setConfirmed(false); setPreview(null);
      setData(prior => ({ ...prior, ...value }));
    } catch (e) { if (e instanceof Error && "rejectedInput" in e) { pending.current = null; setPendingState(false); } setError(e instanceof Error ? e.message : "操作未完成"); } finally { setBusy(false); }
  }
  const finding = record(data?.finding), source = record(data?.source), assessment = record(record(finding.proposed_payload).assessment);
  const people = list(source.participants), names = Object.fromEntries(people.map(p => [text(p.id), text(p.display_name)]));
  const questions = strings(assessment.open_questions), accepted = record(finding.accepted_payload), plan = record(accepted.plan);
  const editable = finding.status === "pending_review" && data?.source_current === true && !busy && !pendingState;
  const inputClass = "w-full rounded-md border bg-background px-2 py-1 text-sm";
  function describe(value: unknown): string {
    if (value == null) return "无";
    if (typeof value === "string") return names[value] || types[value] || value;
    if (Array.isArray(value)) return value.map(describe).join("；");
    if (isRecord(value)) {
      if (value.user_id) return `${names[text(value.user_id)] ?? text(value.user_id)}（${value.participation === "required" ? "必需" : "可选"}）`;
      return Object.entries(value).filter(([k]) => k !== "citations").map(([key, v]) => `${({ detail: "讨论内容", expected_output: "产出", owner_user_id: "负责人", suggested_owner_id: "负责人", start: "开始", end: "结束", timezone: "时区", ...fieldNames } as Record<string, string>)[key] ?? key}：${describe(v)}`).join("\n");
    }
    return String(value);
  }
  return <details className="rounded-md border p-3" onToggle={e => { if (e.currentTarget.open && !data && !busy) void load(); }}>
    <summary className="cursor-pointer font-medium">人工核对与独立创建会议</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs text-muted-foreground">先核对并接受人工稿，再单独创建项目会议。创建会保存目的和议程；预约与通知在实际会议中另行办理。</p>
      <Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void load()}>读取核对与创建回执</Button>
      {data?.source_current === false && <p className="text-xs text-destructive">{text(data.source_reason)}。已有回执保留。</p>}
      {data && <details><summary>原 AI 建议与逐字引用</summary><p className="whitespace-pre-wrap">{text(record(assessment.plan).title)} · {text(record(assessment.plan).purpose)}</p>{list(record(assessment.plan).agenda).map((a, i) => <div key={i} className="my-2 rounded-md border p-2"><p className="whitespace-pre-wrap">原议题 {i + 1}：{text(a.title)}<br/>{text(a.detail)}<br/>期望产出：{text(a.expected_output)}</p>{list(a.citations).map((citation, n) => <blockquote key={n} className="my-2 whitespace-pre-wrap border-l-2 pl-2">{text(citation.reference_id)} · 字符 {Number(citation.start) + 1}–{text(citation.end)}<br/>{text(citation.exact_quote)}</blockquote>)}</div>)}</details>}
      {finding.status === "pending_review" && draft && <fieldset disabled={!editable} className="space-y-3 disabled:opacity-70">
        <div className="grid gap-3 sm:grid-cols-2"><label className="space-y-1">会议标题<input className={inputClass} value={draft.title} maxLength={240} onChange={e => edit({ title: e.target.value })}/></label><label className="space-y-1">会议类型<select className={inputClass} value={draft.meeting_type} onChange={e => edit({ meeting_type: e.target.value })}>{Object.entries(types).map(([key, label]) => <option key={key} value={key}>{label}</option>)}</select></label></div>
        <label className="block space-y-1">会议目的<textarea className={inputClass} value={draft.purpose} maxLength={3000} onChange={e => edit({ purpose: e.target.value })}/></label>
        <p>组织者：{text(source.author_name)}（原发起人）。时间按 {draft.timezone} 输入；请自行核对参会人的实际可用时间。</p>
        <div className="grid gap-3 sm:grid-cols-2"><label>正式开始<input type="datetime-local" className={inputClass} value={draft.scheduled_start_at} onChange={e => edit({ scheduled_start_at: e.target.value })}/></label><label>正式结束<input type="datetime-local" className={inputClass} value={draft.scheduled_end_at} onChange={e => edit({ scheduled_end_at: e.target.value })}/></label></div>
        <div className="space-y-1"><p className="font-medium">正式参会名单</p>{people.filter(p => p.id !== source.author_id).map(p => { const selected = draft.participants.find(x => x.user_id === p.id); return <label key={text(p.id)} className="flex items-center justify-between gap-2"><span>{text(p.display_name)}</span><select className="rounded-md border bg-background p-1" value={selected?.participation ?? "excluded"} onChange={e => { const others = draft.participants.filter(x => x.user_id !== p.id); edit({ participants: e.target.value === "excluded" ? others : [...others, { user_id: text(p.id), participation: e.target.value as Person["participation"] }] }); }}><option value="excluded">不参加</option><option value="required">必需</option><option value="optional">可选</option></select></label>; })}</div>
        {draft.agenda.map((a, i) => <div key={i} className="space-y-2 rounded-md border p-2"><p>议题 {i + 1} · {a.original_number ? `对应原 AI 议题 ${a.original_number}` : "人工新增"}</p><label className="block">标题<input className={inputClass} value={a.title} maxLength={256} onChange={e => edit({ agenda: draft.agenda.map((v, n) => n === i ? { ...v, title: e.target.value } : v) })}/></label><label className="block">讨论内容<textarea className={inputClass} value={a.detail} maxLength={5000} onChange={e => edit({ agenda: draft.agenda.map((v, n) => n === i ? { ...v, detail: e.target.value } : v) })}/></label><label className="block">期望产出<textarea className={inputClass} value={a.expected_output} maxLength={2000} onChange={e => edit({ agenda: draft.agenda.map((v, n) => n === i ? { ...v, expected_output: e.target.value } : v) })}/></label><label className="block">议题负责人<select className={inputClass} value={a.owner_user_id ?? ""} onChange={e => edit({ agenda: draft.agenda.map((v, n) => n === i ? { ...v, owner_user_id: e.target.value || null } : v) })}><option value="">待分派</option>{people.map(p => <option key={text(p.id)} value={text(p.id)}>{text(p.display_name)}</option>)}</select></label><Button type="button" size="sm" variant="ghost" onClick={() => edit({ agenda: draft.agenda.filter((_, n) => n !== i) })}>移除此议题</Button></div>)}
        <Button type="button" size="sm" variant="outline" disabled={draft.agenda.length >= 12} onClick={() => edit({ agenda: [...draft.agenda, { original_number: null, title: "", detail: "", expected_output: "", owner_user_id: null }] })}>新增人工议题</Button>
        {questions.map((q, i) => <label key={i} className="block space-y-1">待确认 {i + 1}：{q}<textarea className={inputClass} value={draft.question_responses[i] ?? ""} maxLength={2000} onChange={e => edit({ question_responses: draft.question_responses.map((v, n) => n === i ? e.target.value : v) })}/></label>)}
        <Button type="button" size="sm" variant="outline" onClick={() => void showPreview()}>预览与原 AI 建议的差异</Button>
      </fieldset>}
      {preview && <div className="space-y-2 rounded-md border p-3"><p className="font-medium">接受前差异预览</p>{list(preview.changes).map((change, i) => <details key={i}><summary>{fieldNames[text(change.field)] ?? text(change.field)} {change.original_number != null ? `原第 ${text(change.original_number)} 项` : ""} {({ added: "人工新增", modified: "已修改", retained: "保留", removed: "移除" } as Record<string, string>)[text(change.action)]}</summary><div className="grid gap-2 sm:grid-cols-2"><p className="whitespace-pre-wrap">原建议／拟议安排：{describe(change.before)}</p><p className="whitespace-pre-wrap">人工安排：{describe(change.after)}</p></div></details>)}<details><summary>将写入正式会议的完整议程</summary>{list(preview.meeting_agenda).map((a, i) => <p className="whitespace-pre-wrap" key={i}>{i + 1}. {text(a.title)}<br/>{text(a.detail)}</p>)}</details></div>}
      {finding.status === "pending_review" && <div className="space-y-2"><label className="block">核对意见（包括修改、移除或拒绝理由）<textarea className={inputClass} disabled={busy || pendingState} maxLength={5000} value={comment} onChange={e => setComment(e.target.value)}/></label><div className="flex gap-2"><Button type="button" size="sm" disabled={!editable || !preview || !comment.trim()} onClick={() => void submit("review", "accepted")}>接受此人工稿</Button><Button type="button" size="sm" variant="outline" disabled={busy || pendingState || !comment.trim()} onClick={() => void submit("review", "rejected")}>拒绝原建议</Button></div></div>}
      {["accepted", "applied"].includes(text(finding.status)) && <div className="space-y-2 rounded-md border p-3"><p className="font-medium">已接受人工稿：{text(plan.title)}</p><p>核对时间：{text(finding.reviewed_at)} · {text(finding.review_comment)}</p><p className="whitespace-pre-wrap">{text(plan.purpose)}</p><p>{types[text(plan.meeting_type)]} · {text(plan.scheduled_start_at)} 至 {text(plan.scheduled_end_at)} · 原输入时区 {text(plan.timezone)}</p><p>组织者：{names[text(accepted.organizer_user_id)] ?? text(source.author_name)}；参会：{describe(plan.participants)}</p>{list(plan.agenda).map((a, i) => <p className="whitespace-pre-wrap" key={i}>{i + 1}. {text(a.title)} · {a.original_number ? `原议题 ${text(a.original_number)}` : "人工新增"}<br/>{text(a.detail)}<br/>期望产出：{text(a.expected_output)} · 负责人：{a.owner_user_id ? names[text(a.owner_user_id)] ?? text(a.owner_user_id) : "待分派"}</p>)}{strings(plan.question_responses).map((answer, i) => <p key={i}>待确认 {i + 1} 核对结果：{answer}</p>)}<p>实际会议仅包含此人工目的、正式名单、时间和议程；原私人资料及 AI 引用在本页保留。</p></div>}
      {finding.status === "accepted" && <div className="space-y-2"><label className="flex items-start gap-2"><input type="checkbox" checked={confirmed} disabled={busy || pendingState || data?.source_current !== true} onChange={e => setConfirmed(e.target.checked)}/>已核对上述正式安排，同意创建此项目会议</label><Button type="button" size="sm" disabled={!confirmed || busy || pendingState || data?.source_current !== true} onClick={() => void submit("apply")}>独立创建会议</Button></div>}
      {finding.status === "rejected" && <p>已拒绝 · {text(finding.review_comment)} · {text(finding.reviewed_at)}</p>}
      {typeof data?.meeting_href === "string" && <a className="inline-block text-primary underline" href={data.meeting_href}>查看已创建的实际会议与议程</a>}
      {list(data?.actions).map(a => <p key={text(a.id)} className="text-xs text-muted-foreground">{({ accepted: "接受回执", rejected: "拒绝回执", applied: "创建回执" } as Record<string, string>)[text(a.action)]} · {text(a.created_at)} · 请求 {text(record(a.detail).request_id)}</p>)}
      {pendingState && <div className="space-y-2"><p>原请求尚待核对，当前内容已固定。可先读取回执，再沿同一请求核对。</p><Button type="button" size="sm" variant="outline" disabled={busy} onClick={() => void submit("review")}>核对原提交请求</Button></div>}
      {error && <p role="alert" className="text-destructive">{error}</p>}
    </div>
  </details>;
}
