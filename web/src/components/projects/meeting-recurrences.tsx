"use client";

import { useState } from "react";
import { MeetingAutoGeneration } from "./meeting-auto-generation";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { TimingFields, Occurrences, cadenceLabel, hhmm, type Timing, type Occurrence } from "./meeting-schedule-fields";
import { MeetingScheduleRevision, ScheduleReview, type ScheduleReviewValue } from "./meeting-schedule-revision";

type Person = { id: string; display_name: string };
type Participant = { user_id: string; participation: "required" | "optional" };
type Agenda = { title: string; detail: string | null; owner_user_id: string | null; item_kind: "topic" | "review" | "decision" | "information" | "exception" };
type Schedule = Timing & { meeting_type: string; title: string };
type Create = Schedule & { request_id: string; participants: Participant[]; agenda: Agenda[]; reason: string };
type Recurrence = Schedule & { id: string; status: string; effective_start_date: string; default_participants: Participant[]; agenda_template: Agenda[] };
type Data = { items: Recurrence[]; next_before: string | null; members: Person[]; templates: Record<string, { label: string; topics: string[] }>; can_manage: boolean };

type Preview = { items: Occurrence[]; retained_items: Occurrence[]; timezone: string; expected_digest: string; preview_digest: string; record: Recurrence };
type Generate = { request_id: string; since: string; through: string; expected_digest: string; preview_digest: string; reason: string };
type Receipt = { request_id: string; audit_id: number; recurrence_id: string; items?: Occurrence[]; retained_items?: Occurrence[] };
type History = { id: number; timestamp: string; action: string; context: { reason: string; actor_name: string; people?: Record<string, string> }; after_snapshot: { items?: Occurrence[]; record?: Recurrence; since?: string; through?: string; timezone?: string; retained_items?: Occurrence[]; review?: ScheduleReviewValue } };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
class RequestError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(path: string, body?: object) {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response);
  if (!response.ok) throw new RequestError(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "请核对日期、人员和必填内容后重试", response.status);
  if (!isRecord(value)) throw new Error("未取得完整回执，请重试原请求");
  return value;
}
function known(error: unknown) { return error instanceof RequestError && [400, 401, 403, 404, 409, 422].includes(error.status); }
function message(error: unknown) { return error instanceof Error ? error.message : "办理结果暂未确认，请重试原请求"; }
function localDate() { const now = new Date(); return `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`; }
function addDays(date: string, days: number) { const d = new Date(`${date}T12:00:00Z`); d.setUTCDate(d.getUTCDate() + days); return d.toISOString().slice(0, 10); }
function rosterLink(projectId: string, id: string) { return `/projects?project=${projectId}&tab=decisions&meeting_recurrence=${id}`; }
function RosterSummary({ record, members }: { record: Pick<Recurrence, "default_participants" | "agenda_template">; members: Person[] }) {
  const name = (id: string | null) => members.find(p => p.id === id)?.display_name ?? id ?? "未指定";
  return <div className="space-y-1"><p>默认参会：{record.default_participants.map(p => `${name(p.user_id)}（${p.participation === "required" ? "必需" : "可选"}）`).join("、") || "未另列人员"}</p>{record.agenda_template.map((item, i) => <p key={i}>议题 {i + 1}：{item.title} · {name(item.owner_user_id)}{item.detail ? ` · ${item.detail}` : ""}</p>)}</div>;
}
export function MeetingRecurrences({ projectId }: { projectId: string }) {
  const path = `/api/projects/${projectId}/meetings/recurrences`;
  const [open, setOpen] = useState(false), [data, setData] = useState<Data | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [creating, setCreating] = useState(false), [selected, setSelected] = useState<Recurrence | null>(null);
  async function load(before?: string) {
    setBusy(true); setError("");
    try { const value = await request(path + (before ? `?before=${before}` : "")); if (!Array.isArray(value.items) || !Array.isArray(value.members) || !isRecord(value.templates)) throw new Error("周期配置未完整载入"); const next = value as Data; setData(prior => before && prior ? { ...next, items: [...prior.items, ...next.items] } : next); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  return <section className="my-4 space-y-3 rounded-md border p-4 text-sm"><Button variant="outline" disabled={busy || creating || !!selected} onClick={() => { setOpen(!open); if (!data && !open) void load(); }}>{open ? "收起周期会议" : "周期会议配置与生成"}</Button>{open && <><p>按固定起始日和时区预览排程，确认后生成本地场次。默认人员可独立调整或暂停；已生成会议保留原时间、名单和议程，可到原会议准备议程或取消。</p>{error && <p role="alert" className="text-destructive">{error}</p>}{busy && <p role="status">正在读取…</p>}<Button size="sm" variant="ghost" disabled={busy || creating || !!selected} onClick={() => void load()}>刷新配置</Button>
    {data && <>{!creating && !selected && data.can_manage && <Button size="sm" onClick={() => setCreating(true)}>新增周期配置</Button>}
      {!creating && !selected && <div className="space-y-2">{!data.items.length && <p>本项目尚无周期配置。</p>}{data.items.map(row => <div key={row.id} className="space-y-1 rounded-md border p-3"><p className="font-medium">{row.title} · {row.status === "active" ? "启用" : "暂停"}</p><p>{cadenceLabel[row.cadence]} · {row.cadence === "monthly" ? `${row.day_of_month}日` : `星期${["", "一", "二", "三", "四", "五", "六", "日"][row.day_of_week ?? 1]}`} {hhmm(row.start_minute_of_day)} · {row.duration_minutes}分钟 · {row.timezone} · 起始 {row.effective_start_date}{!row.start_date ? "（沿用当地创建日）" : ""}</p><div className="flex flex-wrap gap-3"><Button size="sm" variant="outline" onClick={() => setSelected(row)}>查看排程与生成历史</Button><a className="text-primary underline" href={rosterLink(projectId, row.id)}>默认人员与暂停/恢复</a></div></div>)}{data.next_before && <Button variant="outline" size="sm" disabled={busy} onClick={() => void load(data.next_before!)}>更多配置</Button>}</div>}
      {creating && <CreateForm projectId={projectId} data={data} onClose={() => { setCreating(false); void load(); }}/>}
      {selected && <Generation key={selected.id} projectId={projectId} record={selected} data={data} onClose={() => { setSelected(null); void load(); }}/>}</>}
    </>}</section>;
}
function CreateForm({ projectId, data, onClose }: { projectId: string; data: Data; onClose: () => void }) {
  const path = `/api/projects/${projectId}/meetings/recurrences`;
  const [draft, setDraft] = useState<Create>(() => ({ request_id: crypto.randomUUID(), title: "", meeting_type: "weekly", cadence: "weekly", start_date: localDate(), day_of_week: 1, day_of_month: null, start_minute_of_day: 540, duration_minutes: 60, timezone: "Asia/Shanghai", participants: [], agenda: [], reason: "" }));
  const [preview, setPreview] = useState<Occurrence[] | null>(null), [busy, setBusy] = useState(false), [pending, setPending] = useState(false), [error, setError] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null);
  async function act(save: boolean) {
    setBusy(true); setError(""); if (save) setPending(true);
    try { const value = await request(path + (save ? "" : "/preview"), draft);
      if (save) { if (value.request_id !== draft.request_id || typeof value.audit_id !== "number" || typeof value.recurrence_id !== "string") throw new Error("尚未取得完整创建回执，请重试原请求"); setReceipt(value as Receipt); setPending(false); }
      else { if (!Array.isArray(value.items)) throw new Error("日期预览不完整"); setPreview(value.items as Occurrence[]); }
    } catch (error) { setError(message(error)); if (save && known(error)) { setPending(false); setPreview(null); } } finally { setBusy(false); }
  }
  return <div className="space-y-3"><h4 className="font-medium">新增周期会议</h4>{error && <p role="alert" className="text-destructive">{error}</p>}{receipt ? <><p role="status">配置已保存，尚未生成任何场次。审计回执 #{receipt.audit_id}</p><a className="text-primary underline" href={rosterLink(projectId, receipt.recurrence_id)}>查看默认配置</a><Button size="sm" onClick={onClose}>返回列表并选择生成范围</Button></> : <>
    <fieldset disabled={busy || !!preview || pending} className="space-y-3"><div className="grid gap-3 sm:grid-cols-2"><label>标题<input className={field} maxLength={240} value={draft.title} onChange={e => setDraft({ ...draft, title: e.target.value })}/></label><label>会议类型<select className={field} value={draft.meeting_type} onChange={e => setDraft({ ...draft, meeting_type: e.target.value })}>{Object.entries(data.templates).map(([key, value]) => <option key={key} value={key}>{value.label}</option>)}</select></label></div><TimingFields value={draft} onChange={timing => setDraft({ ...draft, ...timing })}/>
    <p className="text-xs text-muted-foreground">双周从起始日期之后的首个指定星期算起，每隔14天。每月仅支持1–28日。遇夏令时跳过或重复的时刻须另选时间。实际发起生成人成为各场组织者。</p>
    <details><summary>默认参会人（{draft.participants.length}）</summary>{data.members.map(person => <label className="flex items-center justify-between gap-2 py-1" key={person.id}>{person.display_name}<select className="rounded-md border bg-background p-1" value={draft.participants.find(p => p.user_id === person.id)?.participation ?? ""} onChange={e => setDraft({ ...draft, participants: [...draft.participants.filter(p => p.user_id !== person.id), ...(e.target.value ? [{ user_id: person.id, participation: e.target.value as Participant["participation"] }] : [])] })}><option value="">不列入</option><option value="required">必需</option><option value="optional">可选</option></select></label>)}</details>
    <div className="space-y-2"><p>默认议题（可在单场会前继续准备）</p><Button size="sm" variant="outline" disabled={draft.agenda.length + (data.templates[draft.meeting_type]?.topics.length ?? 0) > 100} onClick={() => setDraft({ ...draft, agenda: [...draft.agenda, ...(data.templates[draft.meeting_type]?.topics ?? []).map(title => ({ title, detail: null, owner_user_id: null, item_kind: "topic" as const }))] })}>追加所选会议模板议题</Button>{draft.agenda.map((item, index) => <div className="space-y-2 rounded-md border p-2" key={index}><label>议题 {index + 1}<input className={field} maxLength={256} value={item.title} onChange={e => setDraft({ ...draft, agenda: draft.agenda.map((p, i) => i === index ? { ...p, title: e.target.value } : p) })}/></label><label className="block">说明<textarea className={field} maxLength={10000} value={item.detail ?? ""} onChange={e => setDraft({ ...draft, agenda: draft.agenda.map((p, i) => i === index ? { ...p, detail: e.target.value || null } : p) })}/></label><label className="block">负责人<select className={field} value={item.owner_user_id ?? ""} onChange={e => setDraft({ ...draft, agenda: draft.agenda.map((p, i) => i === index ? { ...p, owner_user_id: e.target.value || null } : p) })}><option value="">未指定</option>{data.members.map(p => <option key={p.id} value={p.id}>{p.display_name}</option>)}</select></label><Button size="sm" variant="ghost" onClick={() => setDraft({ ...draft, agenda: draft.agenda.filter((_, i) => i !== index) })}>移除此议题</Button></div>)}<Button size="sm" variant="outline" disabled={draft.agenda.length >= 100} onClick={() => setDraft({ ...draft, agenda: [...draft.agenda, { title: "", detail: null, owner_user_id: null, item_kind: "topic" }] })}>添加议题</Button></div>
    <label className="block">配置依据<textarea className={field} maxLength={2048} value={draft.reason} onChange={e => setDraft({ ...draft, reason: e.target.value })}/></label><Button size="sm" disabled={!draft.title.trim() || !draft.start_date || !draft.reason.trim()} onClick={() => void act(false)}>预览起始日起94天的日期</Button><Button size="sm" variant="ghost" onClick={onClose}>取消新增</Button></fieldset>
    {preview && <div className="space-y-3 rounded-md border p-3"><h5 className="font-medium">{draft.title} · {cadenceLabel[draft.cadence]}</h5><RosterSummary record={{ default_participants: draft.participants, agenda_template: draft.agenda }} members={data.members}/><p>{draft.reason}</p><Occurrences items={preview} timezone={draft.timezone} projectId={projectId}/><p>确认保存周期配置后，再选择范围生成会议。当前步骤不会预约外部会议或通知参会人。</p><Button size="sm" disabled={busy} onClick={() => void act(true)}>{pending ? "按原请求重试保存" : "确认保存配置"}</Button>{!pending && <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button>}</div>}
    </>}</div>;
}
function Generation({ projectId, record, data, onClose }: { projectId: string; record: Recurrence; data: Data; onClose: () => void }) {
  const path = `/api/projects/${projectId}/meetings/recurrences/${record.id}`;
  const [editingSchedule, setEditingSchedule] = useState(false);
  const [since, setSince] = useState(localDate()), [through, setThrough] = useState(() => addDays(localDate(), 30)), [reason, setReason] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null), [command, setCommand] = useState<Generate | null>(null), [pending, setPending] = useState(false), [busy, setBusy] = useState(false), [error, setError] = useState("");
  const [receipt, setReceipt] = useState<Receipt | null>(null), [history, setHistory] = useState<History[]>([]), [cursor, setCursor] = useState<number | null>(null), [historyLoaded, setHistoryLoaded] = useState(false);
  async function showPreview() {
    setBusy(true); setError("");
    try { const value = await request(`${path}/preview`, { since, through }); if (!Array.isArray(value.items) || typeof value.preview_digest !== "string" || typeof value.expected_digest !== "string" || !isRecord(value.record)) throw new Error("生成预览不完整"); setPreview(value as Preview); setCommand({ request_id: crypto.randomUUID(), since, through, reason, expected_digest: value.expected_digest, preview_digest: value.preview_digest }); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  async function generate() {
    if (!command) return;
    setBusy(true); setPending(true); setError("");
    try { const value = await request(`${path}/generate`, command); if (value.request_id !== command.request_id || typeof value.audit_id !== "number" || value.recurrence_id !== record.id || !Array.isArray(value.items)) throw new Error("尚未取得完整生成回执，请重试原请求"); setReceipt(value as Receipt); setPending(false); setCommand(null); }
    catch (error) { setError(message(error)); if (known(error)) { setPending(false); setPreview(null); setCommand(null); } } finally { setBusy(false); }
  }
  async function loadHistory(before?: number) {
    setBusy(true); setError("");
    try { const value = await request(`${path}/history${before ? `?before_id=${before}` : ""}`); if (!Array.isArray(value.items)) throw new Error("历史未完整载入"); setHistory(rows => before ? [...rows, ...value.items as History[]] : value.items as History[]); setCursor(typeof value.next_before_id === "number" ? value.next_before_id : null); setHistoryLoaded(true); }
    catch (error) { setError(message(error)); } finally { setBusy(false); }
  }
  if (editingSchedule) return <MeetingScheduleRevision projectId={projectId} recurrenceId={record.id} onClose={onClose}/>;
  return <div className="space-y-3"><h4 className="font-medium">{record.title}</h4><RosterSummary record={preview?.record ?? record} members={data.members}/><a className="text-primary underline" href={rosterLink(projectId, record.id)}>默认人员与暂停/恢复</a>{error && <p role="alert" className="text-destructive">{error}</p>}
    {data.can_manage && <Button size="sm" variant="outline" disabled={busy || pending || !!preview} onClick={() => setEditingSchedule(true)}>修订后续周期时间</Button>}
    {data.can_manage && record.status === "active" && !receipt && <fieldset className="space-y-3" disabled={busy || !!preview || pending}><div className="grid gap-3 sm:grid-cols-2"><label>生成范围开始（{record.timezone}日期）<input type="date" className={field} value={since} onChange={e => setSince(e.target.value)}/></label><label>范围结束（含当天）<input type="date" className={field} value={through} onChange={e => setThrough(e.target.value)}/></label></div><label className="block">生成依据<textarea className={field} maxLength={2048} value={reason} onChange={e => setReason(e.target.value)}/></label><Button size="sm" disabled={!since || !through || !reason.trim()} onClick={() => void showPreview()}>预览所选范围</Button></fieldset>}
    {record.status !== "active" && <p>当前配置已暂停；恢复后才可生成新场次。</p>}
    {preview && !receipt && <div className="space-y-3 rounded-md border p-3"><Occurrences items={preview.items} timezone={preview.timezone} projectId={projectId}/><div><h5>保留的不在当前周期中的已有场次</h5><Occurrences items={preview.retained_items ?? []} timezone={preview.timezone} projectId={projectId}/></div><p>将创建 {preview.items.filter(p => !p.meeting_id).length} 场。当前发起人为新场次组织者。已有场次（含取消或归档）保留，不重新创建。本次只生成本地会议，外部会议链接和邀请通知须另行办理。</p><p>{reason}</p><Button size="sm" disabled={busy || (!pending && preview.items.every(p => !!p.meeting_id))} onClick={() => void generate()}>{pending ? "按原请求重试生成" : "确认生成本地会议"}</Button>{!pending && <Button size="sm" variant="ghost" disabled={busy} onClick={() => { setPreview(null); setCommand(null); }}>返回修改范围</Button>}</div>}
    {receipt && <div className="space-y-2 rounded-md border p-3"><p role="status">本次生成已记账，审计回执 #{receipt.audit_id}。</p><Occurrences items={receipt.items ?? []} timezone={preview?.timezone ?? record.timezone} projectId={projectId}/>{!!receipt.retained_items?.length && <details><summary>同时保留的其他已有场次</summary><Occurrences items={receipt.retained_items} timezone={preview?.timezone ?? record.timezone} projectId={projectId}/></details>}</div>}
    <div className="space-y-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void loadHistory()}>读取配置创建与生成历史</Button>{historyLoaded && history.length === 0 && <p>尚无此入口的创建或生成回执；历史已有会议保留。</p>}{history.map(row => <details key={row.id} className="rounded-md border p-3"><summary>{new Date(row.timestamp).toLocaleString()} · {row.action === "meeting_recurrence.created" ? "创建配置" : row.action === "meeting_recurrence.schedule_changed" ? "修订周期时间" : "生成场次"} · {row.context.actor_name}</summary><p>{row.context.reason}</p>{row.after_snapshot.record && <><p>原配置：{row.after_snapshot.record.title} · {row.after_snapshot.record.timezone} · 起始 {row.after_snapshot.record.start_date}</p><RosterSummary record={row.after_snapshot.record} members={Object.entries(row.context.people ?? {}).map(([id, display_name]) => ({ id, display_name }))}/></>}{row.after_snapshot.review && <ScheduleReview value={row.after_snapshot.review} projectId={projectId}/>} {row.after_snapshot.items && <><p>当时范围：{row.after_snapshot.since} 至 {row.after_snapshot.through}</p><Occurrences items={row.after_snapshot.items} timezone={row.after_snapshot.timezone ?? record.timezone} projectId={projectId}/>{!!row.after_snapshot.retained_items?.length && <details><summary>当时保留的其他已有场次</summary><Occurrences items={row.after_snapshot.retained_items} timezone={row.after_snapshot.timezone ?? record.timezone} projectId={projectId}/></details>}</>}</details>)}{cursor && <Button size="sm" variant="outline" disabled={busy} onClick={() => void loadHistory(cursor)}>加载更早回执</Button>}</div>
    <MeetingAutoGeneration projectId={projectId} recurrenceId={record.id}/>
    <Button size="sm" variant="ghost" disabled={busy || pending} onClick={onClose}>返回周期列表</Button>
  </div>;
}
