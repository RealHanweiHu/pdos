"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Meeting = { id: string; title: string; status: string; scheduled_start_at: string; scheduled_end_at: string; external_provider: string | null; external_meeting_id: string | null; external_join_url: string | null; recurrence_id: string | null; occurrence_date: string | null; archived_at: string | null; deleted_at: string | null };
type History = { id: number; timestamp: string; action: string; context: { actor_name: string; reason: string }; before_snapshot: Meeting; after_snapshot: { record: Meeting; confirmation?: { evidence: string } } };
type Data = { record: Meeting; digest: string; can_manage: boolean; external: { state: string; confirmation: History | null }; history: History[]; next_before_id: number | null };
type Command = { path: "schedule"; body: { request_id: string; expected_digest: string; scheduled_start_at: string; scheduled_end_at: string; reason: string } } | { path: "external-schedule-confirmation"; body: { request_id: string; expected_digest: string; external_handled: true; evidence: string; reason: string } };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
class RequestError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(path: string, body?: object) {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response);
  if (!response.ok) throw new RequestError(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "请核对日期、权限和必填内容后重试", response.status);
  if (!isRecord(value)) throw new Error("未取得完整回执，请重试原请求");
  return value;
}
function localInput(value: string) { const d = new Date(value); return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(d.getDate()).padStart(2, "0")}T${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`; }
function shown(value: string) { return new Date(value).toLocaleString("zh-CN", { timeZoneName: "short" }); }
export function MeetingRescheduling({ projectId, meetingId, onChanged }: { projectId: string; meetingId: string; onChanged: () => Promise<void> }) {
  const path = `/api/projects/${projectId}/meetings/${meetingId}`;
  const [data, setData] = useState<Data | null>(null), [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [pending, setPending] = useState(false), [error, setError] = useState("");
  const [start, setStart] = useState(""), [end, setEnd] = useState(""), [reason, setReason] = useState(""), [evidence, setEvidence] = useState(""), [ack, setAck] = useState(false);
  const [command, setCommand] = useState<Command | null>(null), [receipt, setReceipt] = useState<number | null>(null);
  async function load(before?: number) {
    setBusy(true); setError("");
    try { const value = await request(`${path}/schedule${before ? `?before_id=${before}` : ""}`); if (!isRecord(value.record) || typeof value.digest !== "string" || !Array.isArray(value.history) || !isRecord(value.external)) throw new Error("改期资料未完整载入"); const next = value as Data; setData(prior => before && prior ? { ...next, history: [...prior.history, ...next.history] } : next); if (!before) { setStart(localInput(next.record.scheduled_start_at)); setEnd(localInput(next.record.scheduled_end_at)); setAck(false); } }
    catch (error) { setError(error instanceof Error ? error.message : "读取失败"); } finally { setBusy(false); }
  }
  function preview(kind: Command["path"]) {
    if (!data) return;
    setError(""); setReceipt(null);
    if (kind === "schedule") {
      const from = new Date(start), to = new Date(end);
      if (!Number.isFinite(from.getTime()) || !Number.isFinite(to.getTime()) || localInput(from.toISOString()) !== start || localInput(to.toISOString()) !== end) { setError("请选择有效的当地日期和时刻；夏令时跳过的时刻不能使用。"); return; }
      if (to.getTime() - from.getTime() < 300000 || to.getTime() - from.getTime() > 43200000) { setError("会议时长须在5分钟至12小时之间。"); return; }
      setCommand({ path: kind, body: { request_id: crypto.randomUUID(), expected_digest: data.digest, scheduled_start_at: from.toISOString(), scheduled_end_at: to.toISOString(), reason } });
    } else setCommand({ path: kind, body: { request_id: crypto.randomUUID(), expected_digest: data.digest, external_handled: true, evidence, reason } });
  }
  async function save() {
    if (!command) return;
    setBusy(true); setPending(true); setError("");
    try { const value = await request(`${path}/${command.path}`, command.body); if (value.request_id !== command.body.request_id || typeof value.audit_id !== "number" || value.meeting_id !== meetingId) throw new Error("尚未取得完整回执，请重试原请求"); setReceipt(value.audit_id); setPending(false); setCommand(null); setReason(""); setEvidence(""); await load(); try { await onChanged(); } catch { setError("办理已保存，会议清单刷新失败，请稍后刷新。"); } }
    catch (error) { setError(error instanceof Error ? error.message : "办理结果待确认"); if (error instanceof RequestError && [400, 401, 403, 404, 409, 422].includes(error.status)) { setPending(false); setCommand(null); } } finally { setBusy(false); }
  }
  const editable = data?.can_manage && !data.record.archived_at && !data.record.deleted_at;
  return <section className="space-y-3 rounded-md border p-3 text-sm"><Button size="sm" variant="outline" disabled={busy || pending} onClick={() => { setOpen(!open); if (!open && !data) void load(); }}>{open ? "收起改期与外部会议核对" : "单场改期、外部会议核对与历史"}</Button>{open && <>{error && <p role="alert" className="text-destructive">{error}</p>}{receipt && <p role="status">办理已保存，审计回执 #{receipt}。</p>}<Button size="sm" variant="ghost" disabled={busy || !!command} onClick={() => void load()}>刷新当前安排</Button>{data && <>
    <p>当前计划：{shown(data.record.scheduled_start_at)} — {shown(data.record.scheduled_end_at)}</p>{data.record.recurrence_id && <p>源于周期日期 {data.record.occurrence_date}；本次改期保留该来源，重复生成时复用本场会议。<a className="ml-2 text-primary underline" href={`/projects?project=${projectId}&tab=decisions&meeting_recurrence=${data.record.recurrence_id}`}>查看周期配置</a></p>}
    {data.record.external_provider ? <div className="space-y-2 rounded-md border p-3"><p>已绑定 {data.record.external_provider} · {data.record.external_meeting_id}</p>{data.record.external_join_url?.startsWith("https://") && <a className="text-primary underline" href={data.record.external_join_url} target="_blank" rel="noreferrer">打开原外部会议</a>}<p>{data.external.state === "provider_confirmed" ? "会议提供方已返回当前安排的办理成功回执，可在外部预约记录查看。" : data.external.state === "request_manually_confirmed" ? "原请求发起人已人工核对外部结果，可在外部预约记录查看。" : data.external.state === "manually_confirmed" ? "具名人员已核对当前安排；这是人工回执。" : data.record.status === "cancelled" ? "本地已取消；外部会议取消和必要通知尚未登记核对。" : "当前时间与外部会议安排尚未登记核对。"}</p>{data.external.confirmation && <p>{data.external.confirmation.context.actor_name} · {shown(data.external.confirmation.timestamp)} · {data.external.confirmation.after_snapshot.confirmation?.evidence}</p>}<p>此入口不会修改外部会议或发送邀请。请在原提供方办理后登记依据；本地时间或绑定再次变化时需要重新核对。</p></div> : <p>当前未绑定外部会议，本地改期不会自动预约会议室或发送邀请。</p>}
    <fieldset disabled={busy || !!command || pending} className="space-y-3">{editable && data.record.status === "scheduled" && <><h5 className="font-medium">调整本场时间</h5><div className="grid gap-3 sm:grid-cols-2"><label>新开始（本机时区）<input type="datetime-local" className={field} value={start} onChange={e => setStart(e.target.value)}/></label><label>新结束（本机时区）<input type="datetime-local" className={field} value={end} onChange={e => setEnd(e.target.value)}/></label></div></>}
    {editable && data.record.external_provider && ["scheduled", "in_progress", "cancelled"].includes(data.record.status) && <><label className="block">外部办理依据（原提供方回执或人工核对说明）<textarea className={field} maxLength={2048} value={evidence} onChange={e => setEvidence(e.target.value)}/></label><label className="flex items-start gap-2"><input type="checkbox" checked={ack} onChange={e => setAck(e.target.checked)}/>{data.record.status === "cancelled" ? "我已在原提供方核对本场取消，并处理必要通知。" : "我已在原提供方核对当前已保存的开始/结束时间，并处理必要通知。"}</label></>}
    {editable && ["scheduled", "in_progress", "cancelled"].includes(data.record.status) && <label className="block">本次办理依据<textarea className={field} maxLength={2048} value={reason} onChange={e => setReason(e.target.value)}/></label>}
    {editable && data.record.status === "scheduled" && <Button size="sm" disabled={!start || !end || !reason.trim()} onClick={() => preview("schedule")}>预览本地改期</Button>}
    {editable && data.record.external_provider && ["scheduled", "in_progress", "cancelled"].includes(data.record.status) && <Button size="sm" variant="outline" disabled={!ack || !reason.trim() || !evidence.trim()} onClick={() => preview("external-schedule-confirmation")}>预览外部核对回执</Button>}</fieldset>
    {command && <div className="space-y-2 rounded-md border p-3">{command.path === "schedule" ? <><h5 className="font-medium">本场改期预览</h5><p>原时间：{shown(data.record.scheduled_start_at)} — {shown(data.record.scheduled_end_at)}</p><p>新时间：{shown(command.body.scheduled_start_at)} — {shown(command.body.scheduled_end_at)}</p><p className="text-xs">UTC：{command.body.scheduled_start_at} — {command.body.scheduled_end_at}</p><p>原会议标识、周期日期、议程和行动任务保持；外部安排须独立核对。</p></> : <><h5 className="font-medium">记录人工核对</h5><p>{data.record.external_provider} · {data.record.external_meeting_id} · {data.record.status === "cancelled" ? "核对取消" : "核对当前已保存时间"}</p><p>核对时间：{shown(data.record.scheduled_start_at)} — {shown(data.record.scheduled_end_at)}</p><p>{command.body.evidence}</p></>}<p>{command.body.reason}</p><Button size="sm" disabled={busy} onClick={() => void save()}>{pending ? "按原请求重试" : "确认保存"}</Button>{!pending && <Button size="sm" variant="ghost" disabled={busy} onClick={() => setCommand(null)}>返回修改</Button>}</div>}
    <details><summary>改期及外部核对历史</summary>{!data.history.length && <p>暂无本入口办理历史。</p>}{data.history.map(row => <article key={row.id} className="my-2 space-y-1 rounded-md border p-2"><p>{shown(row.timestamp)} · {row.context.actor_name} · {row.action === "meeting.rescheduled" ? "本地改期" : "人工核对外部安排"}</p><p>{row.context.reason}</p>{row.action === "meeting.rescheduled" ? <><p>原时间：{shown(row.before_snapshot.scheduled_start_at)} — {shown(row.before_snapshot.scheduled_end_at)}</p><p>新时间：{shown(row.after_snapshot.record.scheduled_start_at)} — {shown(row.after_snapshot.record.scheduled_end_at)}</p></> : <><p>核对的会议：{row.after_snapshot.record.external_provider} · {row.after_snapshot.record.external_meeting_id} · {row.after_snapshot.record.status === "cancelled" ? "取消" : "原排程"}</p><p>当时时间：{shown(row.after_snapshot.record.scheduled_start_at)} — {shown(row.after_snapshot.record.scheduled_end_at)}</p><p>{row.after_snapshot.confirmation?.evidence}</p></>}</article>)}{data.next_before_id && <Button size="sm" variant="outline" disabled={busy || !!command} onClick={() => void load(data.next_before_id ?? undefined)}>读取更早历史</Button>}</details>
    </>}</>}</section>;
}
