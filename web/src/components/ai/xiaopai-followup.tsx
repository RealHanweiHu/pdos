"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { isRecord, responseBody } from "@/components/workspace-api";

type Row = Record<string, unknown>;
type Workspace = { delegations: Row[]; followups: Row[]; receipts: Row[]; calendars: Row[] };
const rows = (value: unknown): Row[] => Array.isArray(value) ? value.filter(isRecord) : [];
const labels: Record<string, string> = { active: "持续跟进中", paused: "已暂停", stopped: "已结束", completed: "已到期或项目结束", blocked: "需要协助", pending: "等待送达", waiting_reply: "等待回复", waiting_progress: "等待下一检查点", no_reply: "未回复，待升级处理", no_progress: "未推进，待升级处理", resolved: "本次观察已有变化", cancelled: "已取消" };
export async function paiRequest(path: string, body?: object): Promise<Row> {
  const response = await fetch(path, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined });
  const value: unknown = await responseBody(response);
  if (!response.ok || !isRecord(value)) throw new Error(isRecord(value) && isRecord(value.detail) && typeof value.detail.message === "string" ? value.detail.message : "小Pai暂时无法连接，请稍后重试");
  return value;
}
function Result({ value }: { value: unknown }) {
  if (!isRecord(value)) return null;
  return <div className="space-y-3 text-sm">{[["completed", "已完成"], ["in_progress", "进行中"], ["unfinished", "未完成"]].map(([key, label]) => {
    const items = Array.isArray(value[key]) ? value[key] : [];
    return <div key={key}><p className="font-medium">{label}</p>{items.length ? <ul className="mt-1 space-y-1">{items.map((item, index) => <li key={index} className="break-words text-muted-foreground">{isRecord(item) ? `${item.title ? `${String(item.title)} · ` : ""}${String(item.reason ?? item.action ?? "")}${item.escalation ? ` · ${String(item.escalation)}` : ""}` : String(item)}</li>)}</ul> : <p className="text-muted-foreground">暂无</p>}</div>;
  })}</div>;
}
function Reply({ item, onReply, busy }: { item: Row; onReply: (id: string, body: string, checkpoint: string) => Promise<void>; busy: boolean }) {
  const [body, setBody] = useState("");
  const [checkpoint, setCheckpoint] = useState("");
  return <form className="mt-2 space-y-2" onSubmit={e => { e.preventDefault(); void onReply(String(item.id), body, checkpoint).then(() => setBody("")).catch(() => {}); }}>
    <textarea aria-label={`回复${String(item.title)}的进展`} className="min-h-20 w-full rounded-lg border bg-background p-2 text-sm" value={body} onChange={e => setBody(e.target.value)} maxLength={2000} placeholder="补充进展、阻塞或需要的协助…" required />
    <label className="block text-xs">下一检查点（留空为下一工作日）<input className="mt-1 block w-full rounded-lg border bg-background p-2" type="datetime-local" value={checkpoint} onChange={e => setCheckpoint(e.target.value)} /></label>
    <Button size="sm" disabled={busy || !body.trim()}>回复进展</Button>
  </form>;
}
export function XiaopaiFollowup({ projectId, userId, conversationId, onConversationReady, requestedGoal }: { requestedGoal?: string; projectId: string; userId: string; conversationId?: string; onConversationReady: (id: string) => void }) {
  const [data, setData] = useState<Workspace | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [goal, setGoal] = useState("持续跟进项目交付：发现延期时预警、重算预计排程、询问进展并升级未回复或未推进的事项，每日提供摘要。");
  const [timezone, setTimezone] = useState(() => Intl.DateTimeFormat().resolvedOptions().timeZone);
  const [calendar, setCalendar] = useState("");
  const [expires, setExpires] = useState("");
  useEffect(() => { if (!requestedGoal) return; const timer = window.setTimeout(() => setGoal(requestedGoal), 0); return () => window.clearTimeout(timer); }, [requestedGoal]);
  const forecastId = useRef<string | null>(null);
  const requestId = useRef<string | null>(null);
  const createConversationRequest = useRef<string | null>(null);
  const operation = useRef<{ signature: string; id: string } | null>(null);
  const base = `/api/projects/${projectId}/xiaopai`;
  const refresh = useCallback(async () => { const v = await paiRequest(base); const result = rows(v.delegations)[0]?.result; const forecast = isRecord(result) && isRecord(result.forecast) ? String(result.forecast.record_id) : null; if (forecast && forecast !== forecastId.current) { forecastId.current = forecast; window.dispatchEvent(new Event("pdos:forecast-updated")); } setData({ delegations: rows(v.delegations), followups: rows(v.followups), receipts: rows(v.receipts), calendars: rows(v.calendars) }); }, [base]);
  useEffect(() => { let active = true; const read = () => { if (active) void refresh().catch(e => { if (active) setError(e instanceof Error ? e.message : "委托状态读取失败"); }); }; read(); const timer = window.setInterval(read, 30000); return () => { active = false; window.clearInterval(timer); }; }, [refresh]);
  const act = async (work: () => Promise<void>) => { setBusy(true); setError(null); try { await work(); await refresh(); } catch (e) { setError(e instanceof Error ? e.message : "办理未完成，请查看原回执再重试"); throw e; } finally { setBusy(false); } };
  const mutate = async (path: string, body: object) => { const signature = JSON.stringify([path, body]); if (operation.current?.signature !== signature) operation.current = { signature, id: crypto.randomUUID() }; const value = await paiRequest(path, { ...body, request_id: operation.current.id }); operation.current = null; return value; };
  const active = data?.delegations.find(d => ["active", "paused", "blocked"].includes(String(d.status)));
  return <section className="space-y-4 rounded-lg border p-4" aria-label="项目持续跟进">
    <div className="flex items-center justify-between gap-2"><h3 className="font-medium">项目持续跟进</h3><Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(refresh).catch(() => {})}>刷新</Button></div>
    <p className="text-xs text-muted-foreground">项目成员共享。关闭对话后仍会继续；实际进展与未完成事项保存在这里。</p>
    {active ? <div className="space-y-3"><p className="text-sm">{String(active.goal)}</p><p className="text-xs font-medium">{labels[String(active.status)] ?? String(active.status)}{active.checked_at ? ` · 最近检查 ${new Date(String(active.checked_at)).toLocaleString()}` : " · 等待后台首次检查"}</p><Result value={active.result}/><a className="text-sm text-primary underline" href={`/projects?project=${projectId}&tab=plan`}>查看预计排程和影响原因</a><div className="flex flex-wrap gap-2">{active.can_manage === true && <><Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { await mutate(`${base}/delegations/${String(active.id)}/state`, { expected_version: active.version, status: active.status === "active" ? "paused" : "active" }); }).catch(() => {})}>{active.status === "active" ? "暂停跟进" : "恢复跟进"}</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => void act(async () => { await mutate(`${base}/delegations/${String(active.id)}/state`, { expected_version: active.version, status: "stopped" }); }).catch(() => {})}>结束委托</Button></>}</div></div> : data && <details open={!!requestedGoal}><summary className="cursor-pointer text-sm font-medium text-primary">交给小Pai持续跟进</summary><form className="mt-3 space-y-3" onSubmit={e => { e.preventDefault(); void act(async () => {
      let cid = conversationId;
      if (!cid) { createConversationRequest.current ??= crypto.randomUUID(); const created = await paiRequest("/api/conversations", { project_id: projectId, visibility: "project", request_id: createConversationRequest.current }); cid = String(created.id); onConversationReady(cid); }
      requestId.current ??= crypto.randomUUID();
      await paiRequest(`${base}/delegations`, { request_id: requestId.current, conversation_id: cid, goal, timezone, ...(calendar ? { calendar_version_id: calendar } : {}), ...(expires ? { expires_at: new Date(expires).toISOString() } : {}) }); requestId.current = null;
    }).catch(() => {}); }}>
      <textarea aria-label="持续跟进目标" className="min-h-24 w-full rounded-lg border bg-background p-3 text-sm" value={goal} onChange={e => { setGoal(e.target.value); requestId.current = null; }} maxLength={2000} required />
      <label className="block text-xs">跟进使用的工作日历<select className="mt-1 block w-full rounded-lg border bg-background p-2" value={calendar} onChange={e => { setCalendar(e.target.value); requestId.current = null; }}><option value="">周一至周五，无额外节假日</option>{data.calendars.map(row => <option key={String(row.id)} value={String(row.id)}>{isRecord(row.definition) && isRecord(row.definition.calendar) ? `${String(row.definition.calendar.timezone)} · 日历 ${String(row.definition.calendar.version)}` : String(row.id)}</option>)}</select></label>
      {!calendar && <label className="block text-xs">项目时区<input aria-label="项目时区" className="mt-1 block w-full rounded-lg border bg-background p-2" value={timezone} onChange={e => { setTimezone(e.target.value); requestId.current = null; }} required /></label>}
      <label className="block text-xs">结束时间（留空则持续至项目结束或主动停止）<input type="datetime-local" className="mt-1 block w-full rounded-lg border bg-background p-2" value={expires} onChange={e => { setExpires(e.target.value); requestId.current = null; }}/></label>
      <p className="text-xs text-muted-foreground">每日09:00提供摘要。询问送达后1个工作日未回复则升级到项目负责人；已回复但到检查点未推进也会升级。</p>
      <Button disabled={busy || !goal.trim()}>开始持续跟进</Button>
    </form></details>}
    {data?.followups.filter(f => f.delegation_id === active?.id && !["resolved", "cancelled"].includes(String(f.status))).map(f => <div key={String(f.id)} className="border-t pt-3"><a className="text-sm font-medium text-primary" href={`/projects?project=${projectId}&tab=work-items&task=${String(f.task_id)}`}>{String(f.title)}</a><p className="mt-1 text-xs">{labels[String(f.status)]}</p>{f.reply ? <p className="mt-1 whitespace-pre-wrap text-sm text-muted-foreground">最近回复：{String(f.reply)}</p> : null}{f.recipient_user_id === userId && active?.status === "active" && <Reply item={f} busy={busy} onReply={(id, body, checkpoint) => act(async () => { await mutate(`${base}/followups/${id}/reply`, { body, ...(checkpoint ? { checkpoint_at: new Date(checkpoint).toISOString() } : {}) }); })}/>}</div>)}
    {data?.delegations.filter(d => ["completed", "stopped"].includes(String(d.status))).map(d => <details key={String(d.id)} className="border-t pt-3"><summary className="cursor-pointer text-sm">{labels[String(d.status)]} · {String(d.goal)}</summary><div className="mt-3"><p className="text-xs text-muted-foreground">以下为停止前的最后检查；剩余业务事项未自动关闭。</p><Result value={d.result}/></div></details>)}
    {data?.receipts.filter(r => r.kind === "daily_digest").map(r => <details key={String(r.id)} className="border-t pt-3"><summary className="cursor-pointer text-sm">项目摘要 · {String(r.request_key).startsWith("daily:") ? String(r.request_key).slice(6) : new Date(String(r.created_at)).toLocaleDateString()}</summary><div className="mt-3"><Result value={r.content}/></div></details>)}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
  </section>;
}
