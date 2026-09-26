"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";
import { TimingFields, TimingSummary, Occurrences, type Timing, type Occurrence } from "./meeting-schedule-fields";

type Draft = Timing & { request_id: string; expected_digest: string; since: string; through: string; reason: string };
type Preview = { before: Timing; after: Timing; old_items: Occurrence[]; old_errors: { date: string; message: string }[]; new_items: Occurrence[]; retained_items: Occurrence[]; since: string; through: string; preview_digest: string };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
class RequestError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(path: string, body?: object) {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response);
  if (!response.ok) throw new RequestError(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "请核对日期和必填内容后重试", response.status);
  if (!isRecord(value)) throw new Error("未取得完整回执，请重试原请求");
  return value;
}
export function ScheduleReview({ value, projectId }: { value: Preview; projectId: string }) {
  return <div className="space-y-3"><p>预览范围：{value.since} 至 {value.through}</p><div className="grid gap-4 lg:grid-cols-2"><div><h5 className="font-medium">原排程</h5><TimingSummary value={value.before}/>{value.old_errors?.map(item => <p key={item.date} className="text-destructive">原规则 {item.date}：{item.message}</p>)}<Occurrences items={value.old_items} timezone={value.before.timezone} projectId={projectId}/></div><div><h5 className="font-medium">修订后排程</h5><TimingSummary value={value.after}/><Occurrences items={value.new_items} timezone={value.after.timezone} projectId={projectId}/></div></div><details open={value.retained_items.length > 0}><summary>保留的已生成场次（{value.retained_items.length}）</summary><p>这些会议保留原时间和周期日期，其中可能有已不符合新周期的场次。需要取消或改期时逐场办理。</p><Occurrences items={value.retained_items} timezone={value.after.timezone} projectId={projectId}/></details></div>;
}
export type ScheduleReviewValue = Preview;
export function MeetingScheduleRevision({ projectId, recurrenceId, onClose }: { projectId: string; recurrenceId: string; onClose: () => void }) {
  const path = `/api/projects/${projectId}/meetings/recurrences/${recurrenceId}`;
  const [draft, setDraft] = useState<Draft | null>(null), [preview, setPreview] = useState<Preview | null>(null), [busy, setBusy] = useState(false), [pending, setPending] = useState(false), [error, setError] = useState("");
  const [receipt, setReceipt] = useState<number | null>(null);
  async function load() {
    setBusy(true); setError("");
    try { const value = await request(`${path}/roster`); if (!isRecord(value.record) || typeof value.digest !== "string" || typeof value.effective_start_date !== "string") throw new Error("原周期配置不完整"); const rec = value.record as Timing; const now = new Date(); const since = `${now.getFullYear()}-${String(now.getMonth() + 1).padStart(2, "0")}-${String(now.getDate()).padStart(2, "0")}`; const end = new Date(`${since}T12:00:00Z`); end.setUTCDate(end.getUTCDate() + 30); setDraft({ cadence: rec.cadence, day_of_week: rec.day_of_week, day_of_month: rec.day_of_month, start_date: value.effective_start_date, start_minute_of_day: rec.start_minute_of_day, duration_minutes: rec.duration_minutes, timezone: rec.timezone, since, through: end.toISOString().slice(0, 10), request_id: crypto.randomUUID(), expected_digest: value.digest, reason: "" }); setPreview(null); }
    catch (error) { setError(error instanceof Error ? error.message : "读取失败"); } finally { setBusy(false); }
  }
  async function act(save: boolean) {
    if (!draft || (save && !preview)) return;
    setBusy(true); setError(""); if (save) setPending(true);
    try { const value = await request(path + (save ? "/schedule" : "/schedule-preview"), save ? { ...draft, preview_digest: preview!.preview_digest } : draft);
      if (save) { if (value.request_id !== draft.request_id || typeof value.audit_id !== "number" || value.recurrence_id !== recurrenceId) throw new Error("修订结果暂未确认，请重试原请求"); setReceipt(value.audit_id); setPending(false); }
      else { if (!Array.isArray(value.old_items) || !Array.isArray(value.new_items) || !Array.isArray(value.retained_items) || typeof value.preview_digest !== "string") throw new Error("修订预览不完整"); setPreview(value as Preview); }
    } catch (error) { setError(error instanceof Error ? error.message : "办理结果待确认"); if (save && error instanceof RequestError && [400, 401, 403, 404, 409, 422].includes(error.status)) { setPending(false); setPreview(null); } } finally { setBusy(false); }
  }
  return <section className="space-y-3 rounded-md border p-3 text-sm"><h4 className="font-medium">修订后续周期时间</h4><p>保存后仅改变尚未生成场次的排程计算。默认人员、议题、启用/暂停状态和已生成会议保留。</p>{error && <p role="alert" className="text-destructive">{error}</p>}{receipt ? <><p role="status">周期时间已修订，回执 #{receipt}。需要生成新场次时重新预览日期范围。</p><Button size="sm" onClick={onClose}>返回周期列表</Button></> : <><Button size="sm" variant="outline" disabled={busy || pending || !!preview} onClick={() => void load()}>{draft ? "放弃编辑并重新读取" : "读取当前配置开始修订"}</Button>{draft && <fieldset disabled={busy || pending || !!preview} className="space-y-3"><TimingFields value={draft} onChange={timing => setDraft({ ...draft, ...timing })}/><p>双周从起始日后的首个指定星期算起。保存不会自动生成、取消或改期现有会议。</p><div className="grid gap-3 sm:grid-cols-2"><label>预览开始<input type="date" className={field} value={draft.since} onChange={e => setDraft({ ...draft, since: e.target.value })}/></label><label>预览结束（最多94天）<input type="date" className={field} value={draft.through} onChange={e => setDraft({ ...draft, through: e.target.value })}/></label></div><label className="block">修订依据<textarea className={field} maxLength={2048} value={draft.reason} onChange={e => setDraft({ ...draft, reason: e.target.value })}/></label><Button size="sm" disabled={!draft.reason.trim() || !draft.start_date || !draft.since || !draft.through} onClick={() => void act(false)}>预览原排程与新排程</Button></fieldset>}{preview && <><ScheduleReview value={preview} projectId={projectId}/><p>{draft?.reason}</p><Button size="sm" disabled={busy} onClick={() => void act(true)}>{pending ? "按原请求重试修订" : "确认修订后续周期时间"}</Button>{!pending && <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button>}</>}<Button size="sm" variant="ghost" disabled={busy || pending} onClick={onClose}>返回周期列表</Button></>}</section>;
}
