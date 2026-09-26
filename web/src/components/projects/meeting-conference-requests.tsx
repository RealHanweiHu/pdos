"use client";

import { useState } from "react";
import { AutomaticNoticeSummary, type AutomaticNotice } from "./meeting-notification-scope";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Provider = "dingtalk" | "tencent_meeting";
const providers: Record<Provider, string> = { dingtalk: "钉钉", tencent_meeting: "腾讯会议" };
type Operation = "create" | "update" | "cancel" | "query";
type Meeting = { title: string; scheduled_start_at: string; scheduled_end_at: string; status: string; organizer_user_id: string; external_provider: string | null; external_meeting_id: string | null };
type Snapshot = { standing_authority?: { policy: { recurrence_id: string; version: number; active_from: string; active_until: string }; approval_audit_id: number }; meeting: Meeting; identity: { actor_name: string; corp_id: string; external_user_id?: string; external_display_name?: string }; operation: Operation; reason: string; payload: { scheduleConferenceId?: string; meeting_id?: string } };
type Result = { notification?: AutomaticNotice; method: string; external_meeting_id?: string; join_url?: string; provider_request_id?: string; matches_current_meeting?: boolean; observed_matches_requested_schedule?: boolean; title?: string; startTime?: number; endTime?: number; evidence?: string; confirmed_name?: string; outcome?: string; provider_state?: string; local_binding_error?: string };
type Receipt = { provider: Provider; id: string; sequence: number; actor_user_id: string; operation: Operation; status: string; snapshot: Snapshot; created_at: string; dispatched_at: string | null; completed_at: string | null; result: Result | null; error_code: string | null; digest?: string };
type Data = { selected_provider: Provider; meeting: Meeting; digest: string; can_manage: boolean; enabled: boolean; identity: Snapshot["identity"] | null; configuration_problem: string | null; current_user_id: string; active: Receipt | null; origin: Receipt | null; items: Receipt[]; next_before_id: number | null };
type Draft = { provider: Provider; request_id: string; operation: Operation; expected_digest: string; reason: string };
type Preview = { draft: Draft; snapshot: Snapshot; preview_digest: string; enabled: boolean };
type Resolution = { request_id: string; target_request_id: string; expected_digest: string; outcome: "withdraw" | "not_executed" | "completed"; evidence: string; external_meeting_id: string | null; join_url: string | null; confirmed: true };
const actions: Record<Operation, string> = { create: "创建外部预约", update: "同步当前主题和时间", cancel: "取消原外部预约", query: "查询原预约实际安排" };
const statuses: Record<string, string> = { pending: "等待办理", sending: "已派发，等待回执", succeeded: "提供方已返回回执", failed: "本次未完成", uncertain: "外部结果不明，等待人工核对", withdrawn: "派发前撤回", resolved: "已记录人工核对" };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
function shown(value: string) { return new Date(value).toLocaleString("zh-CN", { timeZoneName: "short" }); }
class RequestError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(path: string, body?: object) {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response);
  if (!response.ok) throw new RequestError(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "请核对当前权限、绑定和必填内容", response.status);
  if (!isRecord(value)) throw new Error("尚未取得完整回执，请重试原请求");
  return value;
}
export function MeetingConferenceRequests({ projectId, meetingId, onChanged }: { projectId: string; meetingId: string; onChanged: () => Promise<void> }) {
  const [provider, setProvider] = useState<Provider>("dingtalk");
  const path = `/api/projects/${projectId}/meetings/${meetingId}`;
  const [open, setOpen] = useState(false), [data, setData] = useState<Data | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [reason, setReason] = useState(""), [preview, setPreview] = useState<Preview | null>(null), [resolution, setResolution] = useState<Resolution | null>(null), [pending, setPending] = useState(false);
  const [outcome, setOutcome] = useState<Resolution["outcome"]>("not_executed"), [evidence, setEvidence] = useState(""), [externalId, setExternalId] = useState(""), [joinUrl, setJoinUrl] = useState("");
  async function load(before?: number, selected: Provider = provider) {
    setBusy(true); setError("");
    try { const value = await request(`${path}/conference-requests?provider=${selected}${before ? `&before_id=${before}` : ""}`); if (!isRecord(value.meeting) || !Array.isArray(value.items) || typeof value.digest !== "string") throw new Error("预约资料尚未完整载入"); const next = value as Data; setProvider(next.selected_provider); setData(prior => before && prior ? { ...next, items: [...prior.items, ...next.items] } : next); }
    catch (error) { setError(error instanceof Error ? error.message : "读取失败"); } finally { setBusy(false); }
  }
  async function prepare(operation: Operation) {
    if (!data) return;
    setBusy(true); setError(""); setNotice("");
    const draft = { provider, request_id: crypto.randomUUID(), operation, expected_digest: data.digest, reason };
    try { const value = await request(`${path}/conference-preview`, draft); if (!isRecord(value.snapshot) || typeof value.preview_digest !== "string") throw new Error("未取得完整预览"); setPreview({ ...value, draft } as Preview); }
    catch (error) { setError(error instanceof Error ? error.message : "预览失败"); } finally { setBusy(false); }
  }
  async function save() {
    if (!preview && !resolution) return;
    setBusy(true); setPending(true); setError("");
    const body = resolution ?? { ...preview!.draft, preview_digest: preview!.preview_digest, authorize_external_operation: true };
    const target = resolution ? "conference-resolution" : "conference-requests";
    try { const value = await request(`${path}/${target}`, body); const expected = resolution?.target_request_id ?? preview!.draft.request_id; if (value.id !== expected || typeof value.status !== "string") throw new Error("办理结果尚未确认，请重试原请求"); setNotice(`已保存：${statuses[value.status] ?? value.status}。`); setPending(false); setPreview(null); setResolution(null); setReason(""); setEvidence(""); setExternalId(""); setJoinUrl(""); await load(); try { await onChanged(); } catch { setError("原请求已保存，会议清单刷新失败，请稍后刷新。"); } }
    catch (error) { setError(error instanceof Error ? error.message : "办理结果待确认"); if (error instanceof RequestError && [400, 401, 403, 404, 409, 422].includes(error.status)) { setPending(false); setPreview(null); setResolution(null); } } finally { setBusy(false); }
  }
  function prepareResolution() {
    const active = data?.active;
    if (!active?.digest) return;
    setResolution({ request_id: crypto.randomUUID(), target_request_id: active.id, expected_digest: active.digest, outcome: active.status === "pending" ? "withdraw" : outcome, evidence, external_meeting_id: externalId.trim() || null, join_url: joinUrl.trim() || null, confirmed: true });
  }
  const frozen = busy || !!preview || !!resolution || pending;
  const mine = data?.origin?.actor_user_id === data?.current_user_id;
  return <section className="space-y-3 rounded-md border p-3 text-sm">
    <Button variant="outline" size="sm" disabled={busy || pending} onClick={() => { setOpen(!open); if (!open && !data) void load(); }}>{open ? "收起外部预约办理" : "钉钉 / 腾讯会议预约与回执"}</Button>
    {open && <>{error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}<Button variant="ghost" size="sm" disabled={frozen} onClick={() => void load()}>刷新办理进度</Button>{data && <>
      <label className="block">会议提供方<select className={field} disabled={frozen || !!data.origin || !!data.active} value={provider} onChange={e => { const next = e.target.value as Provider; setProvider(next); setData(null); void load(undefined, next); }}><option value="dingtalk">钉钉</option><option value="tencent_meeting">腾讯会议</option></select></label>
      {provider === "tencent_meeting" && <a className="text-primary underline" href="/settings/integrations/tencent-meeting">管理本人腾讯会议账号映射</a>}
      {data.identity?.external_user_id && <p>腾讯企业用户：{data.identity.external_display_name} · {data.identity.external_user_id}</p>}
      <p>{data.meeting.title} · {shown(data.meeting.scheduled_start_at)} — {shown(data.meeting.scheduled_end_at)}</p>
      {!data.enabled && <p>外部会议服务未启用。当前可核对预览和已有回执，不能提交外部办理。</p>}
      {data.configuration_problem ? <p>{data.configuration_problem}</p> : data.identity && <p>当前本人账号绑定：{data.identity.actor_name} · 企业 {data.identity.corp_id}</p>}
      <p>创建预约使用组织人本人已确认的账号。后续由原预约人同步或取消；参会邀请沿独立通知入口办理。</p>
      {data.meeting.external_provider && !data.origin && <p>本场由其他入口绑定，请在原提供方办理并登记人工核对。</p>}
      {data.active && <div className="space-y-2 rounded-md border p-3"><p>{providers[data.active.provider]} · {actions[data.active.operation]} · {statuses[data.active.status]} · {data.active.snapshot.identity.actor_name}</p><p>{data.active.snapshot.reason}</p><p>请求 {data.active.id}</p>
        {data.can_manage && data.active.actor_user_id === data.current_user_id && ["pending", "uncertain"].includes(data.active.status) && <fieldset disabled={frozen} className="space-y-2">
          {data.active.status === "uncertain" && <><p>请先在原提供方检查原操作的实际结果。结果不明时不能重复创建或派发。</p><label>核对结论<select className={field} value={outcome} onChange={e => setOutcome(e.target.value as Resolution["outcome"])}><option value="not_executed">已核实原操作未执行</option><option value="completed">已核实原操作完成</option></select></label>{outcome === "completed" && data.active.operation === "create" && <><label className="block">原预约 ID<input className={field} value={externalId} maxLength={256} onChange={e => setExternalId(e.target.value)}/></label><label className="block">原入会地址<input className={field} value={joinUrl} maxLength={1024} onChange={e => setJoinUrl(e.target.value)}/></label></>}</>}
          <label className="block">{data.active.status === "pending" ? "撤回依据" : "核对依据（实际结果、原预约、时间等）"}<textarea className={field} value={evidence} maxLength={2048} onChange={e => setEvidence(e.target.value)}/></label><Button size="sm" disabled={!evidence.trim() || (data.active.status === "uncertain" && outcome === "completed" && data.active.operation === "create" && (!externalId.trim() || !joinUrl.trim()))} onClick={prepareResolution}>{data.active.status === "pending" ? "预览撤回" : "预览人工核对"}</Button>
        </fieldset>}
      </div>}
      {data.can_manage && !data.active && <fieldset disabled={frozen} className="space-y-2"><label className="block">本次办理依据<textarea className={field} value={reason} maxLength={2048} onChange={e => setReason(e.target.value)}/></label><div className="flex flex-wrap gap-2">
        {!data.origin && !data.meeting.external_provider && data.meeting.status === "scheduled" && data.meeting.organizer_user_id === data.current_user_id && <Button size="sm" disabled={!reason.trim() || !data.identity} onClick={() => void prepare("create")}>预览创建预约</Button>}
        {mine && data.meeting.status === "scheduled" && data.meeting.external_provider === provider && <Button size="sm" disabled={!reason.trim() || !data.identity} onClick={() => void prepare("update")}>预览同步主题与时间</Button>}
        {mine && data.meeting.status === "cancelled" && <Button size="sm" disabled={!reason.trim() || !data.identity} onClick={() => void prepare("cancel")}>预览取消原预约</Button>}
        {mine && <Button size="sm" variant="outline" disabled={!reason.trim() || !data.identity} onClick={() => void prepare("query")}>预览查询原预约</Button>}
      </div></fieldset>}
      {preview && <div className="space-y-2 rounded-md border p-3"><h5 className="font-medium">{providers[preview.draft.provider]} · {actions[preview.draft.operation]}</h5><p>{preview.snapshot.meeting.title} · {shown(preview.snapshot.meeting.scheduled_start_at)} — {shown(preview.snapshot.meeting.scheduled_end_at)}</p><p>办理人：{preview.snapshot.identity.actor_name} · 企业 {preview.snapshot.identity.corp_id}</p>{(preview.snapshot.payload.scheduleConferenceId || preview.snapshot.payload.meeting_id) && <p>原预约：{preview.snapshot.payload.scheduleConferenceId || preview.snapshot.payload.meeting_id}</p>}<p>{preview.draft.reason}</p><p>确认后将通过所选提供方办理本次操作；本地时间仍以当前已保存安排为准。</p><Button size="sm" disabled={busy || !data.enabled} onClick={() => void save()}>{pending ? "核对原请求回执" : "确认并提交外部办理"}</Button>{!pending && <Button variant="ghost" size="sm" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button>}</div>}
      {resolution && <div className="space-y-2 rounded-md border p-3"><h5 className="font-medium">{resolution.outcome === "withdraw" ? "派发前撤回" : "登记本人核对结果"}</h5><p>原请求：{resolution.target_request_id}</p><p>{resolution.outcome === "completed" ? "确认原操作已完成" : resolution.outcome === "not_executed" ? "确认原操作未执行" : "仅撤回尚未派发的原请求"}</p><p>{resolution.evidence}</p>{resolution.external_meeting_id && <p>预约 ID：{resolution.external_meeting_id} · {resolution.join_url}</p>}<p>这是人工核对记录。保存后可回查原请求；需要再次办理时须独立预览。</p><Button size="sm" disabled={busy} onClick={() => void save()}>{pending ? "核对原请求回执" : "确认保存"}</Button>{!pending && <Button variant="ghost" size="sm" disabled={busy} onClick={() => setResolution(null)}>返回修改</Button>}</div>}
      <details><summary>预约办理历史</summary>{!data.items.length && <p>暂无本入口办理记录。</p>}{data.items.map(item => <article key={item.id} className="my-2 space-y-1 rounded-md border p-3"><p>{shown(item.created_at)} · {item.snapshot.identity.actor_name} · {providers[item.provider]} · {actions[item.operation]} · {statuses[item.status]}</p><p>{item.snapshot.meeting.title} · {shown(item.snapshot.meeting.scheduled_start_at)} — {shown(item.snapshot.meeting.scheduled_end_at)}</p><p>{item.snapshot.reason}</p>{item.snapshot.standing_authority && <p>源于周期第 {item.snapshot.standing_authority.policy.version} 版具名授权（{item.snapshot.standing_authority.policy.active_from} 至 {item.snapshot.standing_authority.policy.active_until}），授权审计回执 #{item.snapshot.standing_authority.approval_audit_id}。<a className="ml-2 text-primary underline" href={`/projects?project=${projectId}&tab=decisions&meeting_recurrence=${item.snapshot.standing_authority.policy.recurrence_id}`}>查看原周期授权</a></p>}{item.error_code && <p>办理提示：{item.error_code}。请核对原请求、账号权限及提供方结果。</p>}{item.result && <>{item.result.notification && <AutomaticNoticeSummary value={item.result.notification}/>}<p>{item.result.method === "provider_response" ? "提供方回执" : item.result.method === "policy_change" ? `周期授权调整：${item.result.confirmed_name ?? "具名办理人"}` : `人工核对：${item.result.confirmed_name ?? "原发起人"}`}{item.result.external_meeting_id ? ` · ${item.result.external_meeting_id}` : ""}</p>{item.result.join_url?.startsWith("https://") && <a className="text-primary underline" href={item.result.join_url} target="_blank" rel="noreferrer">打开原外部会议</a>}{item.result.matches_current_meeting === false && <p>外部操作已有结果，但本地安排已经变化或绑定未能应用。请回查原预约并继续核对；本地已保存内容保留。</p>}{item.result.observed_matches_requested_schedule !== undefined && <><p>{item.result.observed_matches_requested_schedule ? "查询时主题与起止时间符合本次请求固定的安排。" : "查询结果与本次固定安排不一致或信息不全，请核对原预约。"}</p><p>提供方返回：{item.result.title ?? "主题缺失"} · {typeof item.result.startTime === "number" ? shown(new Date(item.result.startTime).toISOString()) : "开始时间缺失"} — {typeof item.result.endTime === "number" ? shown(new Date(item.result.endTime).toISOString()) : "结束时间缺失"}</p></>}{item.result.provider_state && <p>提供方状态：{item.result.provider_state}</p>}{item.result.evidence && <p>{item.result.evidence}</p>}</>}</article>)}{data.next_before_id && <Button size="sm" variant="outline" disabled={frozen} onClick={() => void load(data.next_before_id ?? undefined)}>更早记录</Button>}</details>
    </>}</>}
  </section>;
}
