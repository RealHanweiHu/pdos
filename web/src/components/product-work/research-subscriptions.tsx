"use client";

import { useEffect, useRef, useState } from "react";
import { useSearchParams } from "next/navigation";
import { WorkResponsibility } from "./work-responsibility";
import { Button } from "@/components/ui/button";
import { command, request, type ResearchSource } from "./product-work-api";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const frequencies: Record<string, string> = { daily: "每天", weekly: "每周", monthly: "每月" };
const statuses: Record<string, string> = { active: "已启用", paused: "已暂停", quarantined: "需处理后恢复" };
const runStatuses: Record<string, string> = { running: "正在采集", completed: "已保存", failed: "采集失败", timed_out: "执行超时", cancelled: "已取消" };
type Subscription = { id: string; product_line_id: string | null; source_id: string; url: string; status: string; frequency: string; freshness_days: number | null; next_due_at: string | null; last_success_at: string | null; last_snapshot_id: string | null; lease_token: string | null; consecutive_failures: number; last_error_code: string | null; last_error_message: string | null; version: number; payload_digest: string; can_manage: boolean };
type CollectionRun = { id: string; subscription_id: string; status: string; started_at: string; finished_at: string | null; snapshot_id: string | null; content_changed: boolean | null; error_message: string | null };
type Queue = { items: Subscription[]; runs: CollectionRun[]; worker_enabled: boolean };

export function ResearchSubscriptions({ base, lineId, sources, sourceId, suggestedUrl, canCreate, inspect, onResponsibilityLock }: { base: string; lineId: string | null; sources: ResearchSource[]; sourceId: string; suggestedUrl: string; canCreate: boolean; inspect: (snapshotId: string) => void; onResponsibilityLock: (value: boolean) => void }) {
  const search = useSearchParams();
  const requestedId = search.get("subscription_id") ?? (search.get("responsibility_kind") === "subscription" ? search.get("responsibility_id") : null);
  const targetId = requestedId && /^[0-9a-f-]{36}$/.test(requestedId) ? requestedId : null;
  const queuePath = `${base}/subscriptions${targetId ? `?subscription_id=${targetId}` : ""}`;
  const [ownerLock, setOwnerLock] = useState<string | null>(null);
  const [data, setData] = useState<Queue | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const last = useRef({ body: "", id: "" });
  const load = async () => setData(await request<Queue>(queuePath));
  useEffect(() => { let live = true; void request<Queue>(queuePath).then((value) => { if (live) setData(value); }).catch((failure) => { if (live) setError(failure.message); }); return () => { live = false; }; }, [queuePath]);
  const execute = async (work: () => Promise<unknown>) => { setBusy(true); setError(null); try { await work(); await load(); } catch (failure) { setError(failure instanceof Error ? failure.message : "订阅暂不可用"); } finally { setBusy(false); } };
  const items = data?.items.filter((item) => item.product_line_id === lineId || item.id === targetId) ?? [];
  return <section className="space-y-3 rounded-md border p-3"><div className="flex items-center justify-between gap-2"><h4 className="font-medium">订阅页面变化</h4><Button size="sm" variant="outline" disabled={busy || !!ownerLock} onClick={() => void execute(load)}>刷新采集记录</Button></div>
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    {data && <p className="text-xs text-muted-foreground">{data.worker_enabled ? "按计划交给后台执行，实际进度见采集记录。" : "自动采集尚未开启。已保存的订阅会等待启用。"}连续失败逐步延后重试，5次失败后等待人工处理；暂停保留已有快照。</p>}
    {canCreate && <fieldset disabled={busy || !!ownerLock}><details><summary className="cursor-pointer text-sm">新增页面订阅</summary><form key={`${lineId}:${sourceId}:${suggestedUrl}`} className="mt-3 grid gap-3 sm:grid-cols-2" onSubmit={(event) => {
      event.preventDefault(); const form = new FormData(event.currentTarget);
      const body = { source_id: String(form.get("source")), url: String(form.get("url")).trim(), product_line_id: lineId, frequency: form.get("frequency"), freshness_days: form.get("freshness") ? Number(form.get("freshness")) : null };
      const serialized = JSON.stringify(body); if (last.current.body !== serialized) last.current = { body: serialized, id: crypto.randomUUID() };
      void execute(() => request(`${base}/subscriptions`, "POST", { ...body, request_id: last.current.id }));
    }}><label className="text-sm">公开来源<select name="source" required defaultValue={sourceId} className={field}><option value="">请选择</option>{sources.filter((source) => source.status === "active").map((source) => <option key={source.id} value={source.id}>{source.name}</option>)}</select></label><label className="text-sm">订阅页面<input name="url" type="url" required maxLength={1024} defaultValue={suggestedUrl || sources.find((source) => source.id === sourceId)?.base_url || ""} className={field} /></label><label className="text-sm">采集周期<select name="frequency" defaultValue="weekly" className={field}>{Object.entries(frequencies).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="text-sm">快照建议复查间隔（天）<input name="freshness" type="number" min={1} max={366} className={field} /></label><Button disabled={busy || !!ownerLock} className="justify-self-start">保存订阅</Button></form></details></fieldset>}
    {data && items.length === 0 && <p className="text-sm text-muted-foreground">此范围尚无页面订阅。</p>}
    {items.map((item) => <article id={`subscription-${item.id}`} key={item.id} className="space-y-2 rounded-md border p-3"><WorkResponsibility spaceId={base.split("/")[1]} kind="subscription" recordId={item.id} disabled={busy || (!!ownerLock && ownerLock !== item.id)} onLock={value => { setOwnerLock(value ? item.id : null); onResponsibilityLock(value); }} onChanged={load}/><fieldset key={`${item.id}:${item.version}`} disabled={busy || !!ownerLock} className="space-y-2"><h5 className="text-sm font-medium">{sources.find((source) => source.id === item.source_id)?.name ?? "来源当前不可用"} · {frequencies[item.frequency]} · {statuses[item.status]}</h5><p className="break-all text-xs text-muted-foreground">{item.url}</p><p className="text-xs">{item.lease_token ? "采集执行中" : item.next_due_at ? `下次排期 ${new Date(item.next_due_at).toLocaleString()}` : "当前无排期"}{item.last_success_at ? ` · 最近成功 ${new Date(item.last_success_at).toLocaleString()}` : " · 尚无成功采集"}</p>{item.last_error_message && <p className="text-sm text-destructive">{item.last_error_message} · 连续失败 {item.consecutive_failures} 次</p>}
      {item.last_snapshot_id && <Button size="sm" variant="outline" onClick={() => inspect(item.last_snapshot_id!)}>查看最近快照</Button>}
      {item.can_manage && (item.status === "active" || canCreate) && <form className="flex flex-wrap items-end gap-2" onSubmit={(event) => { event.preventDefault(); const form = new FormData(event.currentTarget); const action = String(form.get("action")); void execute(() => request(`${base}/subscriptions/${item.id}/actions`, "POST", { ...command(item), action, reason: String(form.get("reason")).trim(), ...(action === "reschedule" ? { frequency: form.get("frequency"), freshness_days: form.get("freshness") ? Number(form.get("freshness")) : null } : {}) })); }}><label className="text-sm">操作<select name="action" className={field}>{item.status === "active" ? <option value="pause">暂停</option> : <option value="resume" disabled={!canCreate}>恢复采集</option>}<option value="reschedule" disabled={!canCreate}>调整周期</option></select></label><label className="text-sm">新周期<select name="frequency" defaultValue={item.frequency} className={field}>{Object.entries(frequencies).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label><label className="text-sm">复查间隔（天）<input name="freshness" type="number" min={1} max={366} defaultValue={item.freshness_days ?? ""} className={field} /></label><label className="text-sm">原因<input name="reason" required maxLength={2048} className={field} /></label><Button size="sm" disabled={busy || !!ownerLock}>确认操作</Button></form>}
      <details><summary className="cursor-pointer text-xs">近期采集记录</summary><ul className="mt-2 space-y-2 text-xs">{data?.runs.filter((run) => run.subscription_id === item.id).map((run) => <li key={run.id} className="rounded border p-2"><p>{new Date(run.started_at).toLocaleString()} · {runStatuses[run.status]}{run.content_changed === true ? " · 新增或正文有变化" : run.content_changed === false ? " · 正文未变化" : ""}</p>{run.error_message && <p>{run.error_message}</p>}{run.snapshot_id && <button type="button" className="mt-1 underline" onClick={() => inspect(run.snapshot_id!)}>查看本次快照</button>}</li>)}</ul></details>
    </fieldset></article>)}
  </section>;
}
