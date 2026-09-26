"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Kind = "invite" | "update" | "cancel";
type Person = { id: string; display_name: string; participation: string; eligible: boolean; binding_id: string | null; dingtalk_skip?: string | null };
type Snapshot = { standing_authority?: { policy: { recurrence_id: string; version: number }; approval_audit_id: number }; conference_request_id?: string | null; kind: Kind; actor_name: string; reason: string; dingtalk: boolean; delivery_enabled: boolean; title: string; text: string | null; recipients: Person[]; meeting: { title: string; status: string; scheduled_start_at: string; scheduled_end_at: string } };
type RecipientReceipt = { user_id: string; name: string; in_app: { status: string; acknowledged_at: string | null } | null; dingtalk: { id: string; status: string; attempt_count: number; last_error_code: string | null; remote_reference: string | null } | null; dingtalk_skip: string | null };
type Receipt = { id: string; sequence: number; created_at: string; snapshot: Snapshot; receipts: RecipientReceipt[] };
type Data = { can_manage: boolean; meeting?: Snapshot["meeting"]; participants: Person[]; delivery_enabled: boolean; items: Receipt[]; next_before_id: number | null };
type Draft = { request_id: string; kind: Kind; recipient_user_ids: string[]; dingtalk: boolean; reason: string };
type Preview = { draft: Draft; snapshot: Snapshot; preview_digest: string };
const kinds: Record<Kind, string> = { invite: "参会通知", update: "安排更新", cancel: "取消通知" };
const statuses: Record<string, string> = { pending: "等待投递", sending: "正在投递", retry_wait: "等待重试", succeeded: "提供方已接收", failed: "未投递成功", uncertain: "结果不明，需核对原投递", manual: "等待人工处理或启用通道" };
const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
function shown(value: string) { return new Date(value).toLocaleString("zh-CN", { timeZoneName: "short" }); }
class RequestError extends Error { constructor(message: string, readonly status: number) { super(message); } }
async function request(path: string, body?: object) {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response);
  if (!response.ok) throw new RequestError(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "请核对当前权限、会议安排及收件人", response.status);
  if (!isRecord(value)) throw new Error("尚未取得完整回执，请核对原请求");
  return value;
}

export function MeetingNotifications({ projectId, meetingId }: { projectId: string; meetingId: string }) {
  const path = `/api/projects/${projectId}/meetings/${meetingId}`;
  const [open, setOpen] = useState(false), [busy, setBusy] = useState(false), [data, setData] = useState<Data | null>(null);
  const [error, setError] = useState(""), [notice, setNotice] = useState("");
  const [kind, setKind] = useState<Kind>("invite"), [selected, setSelected] = useState<string[]>([]), [dingtalk, setDingtalk] = useState(false), [reason, setReason] = useState("");
  const [preview, setPreview] = useState<Preview | null>(null), [pending, setPending] = useState(false);
  async function load(before?: number) {
    setBusy(true); setError("");
    try {
      const value = await request(`${path}/notifications${before ? `?before_id=${before}` : ""}`);
      if (!Array.isArray(value.items) || !Array.isArray(value.participants) || typeof value.can_manage !== "boolean") throw new Error("通知资料尚未完整载入");
      const next = value as Data;
      setData(prior => before && prior ? { ...next, items: [...prior.items, ...next.items] } : next);
      if (!before) { setSelected(next.participants.filter(p => p.eligible).slice(0, 100).map(p => p.id)); setKind(next.meeting?.status === "cancelled" ? "cancel" : "invite"); }
    } catch (error) { setError(error instanceof Error ? error.message : "读取失败"); } finally { setBusy(false); }
  }
  async function prepare() {
    setBusy(true); setError(""); setNotice("");
    const draft: Draft = { request_id: crypto.randomUUID(), kind, recipient_user_ids: selected, dingtalk, reason };
    try { const value = await request(`${path}/notification-preview`, draft); if (!isRecord(value.snapshot) || typeof value.preview_digest !== "string") throw new Error("未取得完整预览"); setPreview({ ...value, draft } as Preview); }
    catch (error) { setError(error instanceof Error ? error.message : "预览失败"); } finally { setBusy(false); }
  }
  async function save() {
    if (!preview) return;
    setBusy(true); setPending(true); setError("");
    try {
      const value = await request(`${path}/notifications`, { ...preview.draft, preview_digest: preview.preview_digest, confirmed: true });
      if (value.id !== preview.draft.request_id || !Array.isArray(value.receipts)) throw new Error("通知回执待确认，请重试原请求");
      setPending(false); setPreview(null); setReason(""); setNotice("已登记本次站内通知及所选消息队列。可在下方查看逐人回执。"); await load();
    } catch (error) { setError(error instanceof Error ? error.message : "通知回执待确认"); if (error instanceof RequestError && [400, 401, 403, 404, 409, 422].includes(error.status)) { setPending(false); setPreview(null); } } finally { setBusy(false); }
  }
  const frozen = busy || pending || !!preview;
  return <section className="space-y-3 rounded-md border p-3 text-sm">
    <div className="flex flex-wrap items-center gap-2"><h4 className="font-medium">参会通知</h4><Button size="sm" variant="outline" disabled={frozen} aria-expanded={open} onClick={() => { setOpen(!open); if (!open) void load(); }}>{open ? "收起" : "通知与回执"}</Button>{open && <Button size="sm" variant="ghost" disabled={frozen} onClick={() => void load()}>刷新回执</Button>}</div>
    {open && <>
      {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
      {data && <>
        {data.can_manage && <fieldset disabled={frozen} className="space-y-3">
          <p>按本场实际名单选择收件人。站内通知进入“我的工作”；钉钉消息使用本人免打扰及每日额度。</p>
          <div className="grid gap-3 sm:grid-cols-2"><label>通知类型<select className={field} value={kind} onChange={event => setKind(event.target.value as Kind)}>{(Object.keys(kinds) as Kind[]).map(k => <option key={k} value={k} disabled={k === "cancel" ? data.meeting?.status !== "cancelled" : data.meeting?.status !== "scheduled"}>{kinds[k]}</option>)}</select></label><label>通知说明<input className={field} value={reason} onChange={event => setReason(event.target.value)} placeholder="本次通知原因，保留在办理记录" /></label></div>
          <div className="max-h-60 space-y-2 overflow-auto rounded-md border p-3" aria-label="本次收件人">{!data.participants.length && <p>当前没有参会人。</p>}{data.participants.map(p => <label key={p.id} className="flex items-start gap-2"><input type="checkbox" className="mt-1" checked={selected.includes(p.id)} disabled={!p.eligible || (selected.length >= 100 && !selected.includes(p.id))} onChange={event => setSelected(ids => event.target.checked ? [...ids, p.id] : ids.filter(id => id !== p.id))} /><span>{p.display_name} · {p.participation === "organizer" ? "组织人" : p.participation === "required" ? "必选参会" : "可选参会"}{!p.eligible ? " · 当前无有效项目参会权限" : !p.binding_id ? " · 未绑定钉钉，可收站内通知" : ""}</span></label>)}</div>
          <label className="flex items-center gap-2"><input type="checkbox" checked={dingtalk} onChange={event => setDingtalk(event.target.checked)} />同时向已绑定的参会人发送钉钉个人消息</label>
          {dingtalk && !data.delivery_enabled && <p>当前钉钉投递关闭。确认仅登记待人工处理队列；启用后仍须按原队列办理。</p>}
          <p className="text-xs text-muted-foreground">每次最多100人；原通知不会因改期自动重发。请先保存实际安排，再预览本次更新或取消通知。</p>
          <Button size="sm" variant="outline" disabled={!selected.length || !reason.trim()} onClick={() => void prepare()}>预览 {selected.length} 位收件人</Button>
        </fieldset>}
        {!data.can_manage && <p>当前仅可查看有权读取的通知历史，不能发起新通知。</p>}
        {preview && <div className="space-y-2 rounded-md border p-3"><h5 className="font-medium">{preview.snapshot.title}</h5><p>{shown(preview.snapshot.meeting.scheduled_start_at)} — {shown(preview.snapshot.meeting.scheduled_end_at)}</p><p>办理人：{preview.snapshot.actor_name} · {preview.snapshot.reason}</p><ul className="max-h-60 space-y-1 overflow-auto">{preview.snapshot.recipients.map(p => <li key={p.id}>{p.display_name}：站内通知{preview.snapshot.dingtalk ? p.dingtalk_skip ? `；钉钉跳过：${p.dingtalk_skip}` : preview.snapshot.delivery_enabled ? "；进入钉钉投递队列" : "；钉钉队列等待人工处理" : ""}</li>)}</ul>{preview.snapshot.text && <details><summary>查看本次钉钉消息原文</summary><pre className="whitespace-pre-wrap break-all rounded-md bg-muted p-2">{preview.snapshot.text}</pre></details>}<p>确认后固定本次名单和内容。投递回执表示通道处理结果，参会与出席情况仍需单独核对。</p><Button size="sm" disabled={busy} onClick={() => void save()}>{pending ? "核对原通知请求" : preview.snapshot.dingtalk ? "确认站内通知并授权本次钉钉投递" : "确认发送站内通知"}</Button>{!pending && <Button size="sm" variant="ghost" disabled={busy} onClick={() => setPreview(null)}>返回修改</Button>}</div>}
        <details><summary>通知历史与逐人回执</summary>{!data.items.length && <p className="py-2">暂无通知记录。</p>}{data.items.map(item => <article key={item.id} className="my-2 space-y-2 rounded-md border p-3"><p>{shown(item.created_at)} · {item.snapshot.actor_name} · {kinds[item.snapshot.kind]}</p><p>{item.snapshot.title} · {item.snapshot.reason}</p>{item.snapshot.standing_authority && <p>自动通知依据：<a className="text-primary underline" href={`/projects?project=${projectId}&tab=decisions&meeting_recurrence=${item.snapshot.standing_authority.policy.recurrence_id}`}>周期第 {item.snapshot.standing_authority.policy.version} 版授权</a> · 原审计 #{item.snapshot.standing_authority.approval_audit_id}{item.snapshot.conference_request_id && ` · 预约请求 ${item.snapshot.conference_request_id}`}</p>}<p>当时安排：{shown(item.snapshot.meeting.scheduled_start_at)} — {shown(item.snapshot.meeting.scheduled_end_at)}</p><p className="break-all text-xs text-muted-foreground">通知编号：{item.id}</p><ul className="space-y-2">{item.receipts.map(r => <li key={r.user_id}><p>{r.name}：{r.in_app?.status === "acknowledged" ? "站内已确认阅读" : r.in_app ? "站内已登记" : "站内回执缺失"}{r.in_app?.acknowledged_at && `（${shown(r.in_app.acknowledged_at)}）`}</p>{item.snapshot.dingtalk && <p className="text-xs text-muted-foreground">钉钉：{r.dingtalk ? statuses[r.dingtalk.status] ?? r.dingtalk.status : r.dingtalk_skip ?? "尚未取得投递回执"}{r.dingtalk && ` · 尝试 ${r.dingtalk.attempt_count} 次 · 队列 ${r.dingtalk.id}`}{r.dingtalk?.last_error_code && ` · ${r.dingtalk.last_error_code}`}{r.dingtalk?.remote_reference && ` · 提供方回执 ${r.dingtalk.remote_reference}`}</p>}</li>)}</ul></article>)}{data.next_before_id && <Button size="sm" variant="outline" disabled={frozen} onClick={() => void load(data.next_before_id ?? undefined)}>更早通知</Button>}</details>
      </>}
    </>}
  </section>;
}
