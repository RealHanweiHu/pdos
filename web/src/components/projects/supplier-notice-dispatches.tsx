"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { responseBody } from "@/components/workspace-api";

const labels: Record<string, string> = { queued: "待匹配", completed: "已保存匹配回执", blocked: "未完成，待核对", cancelled: "原输入已停止" };
async function call(url: string, body?: Row): Promise<Row> { const response = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined }); const value = obj(await responseBody(response).catch(() => null)); if (!response.ok) throw new Error(text(obj(value.detail).message) || "队列操作未确认，请读取原回执"); return value; }
export function SupplierNoticeDispatches({ projectId, watchId }: { projectId: string; watchId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null);
  const base = `/api/projects/${projectId}/npi/supplier-notices/watches/${watchId}/dispatches`;
  async function load(more = false) { const value = await call(`${base}${more && data?.next_before_id ? `?before_id=${data.next_before_id}` : ""}`); setData(old => more && old ? { ...value, items: [...rows(old.items), ...rows(value.items)] } : value); }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "操作未完成"); } finally { setBusy(false); } }
  return <details className="space-y-2 rounded-md border p-3 text-sm" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => load()); }}><summary className="cursor-pointer font-medium">自动匹配队列</summary>
    <p className="text-xs text-muted-foreground">每次成功采集或保存有效映射后排队，只匹配当时固定的原文。暂停映射会停止旧输入；进程中断保留原请求，失败需核对后重试。</p>
    {data && <p>{data.enabled === true ? "自动匹配已配置启用；实际完成以回执为准。" : "自动匹配尚未启用；排队记录会保留，可手动匹配已有快照。"}</p>}
    {error && <p role="alert" className="text-destructive">{error}</p>}
    <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load())}>刷新队列</Button>
    {data && rows(data.items).length === 0 && <p>暂无可读取的排队记录；需先有成功采集回执和有效映射。</p>}
    {rows(data?.items).map(item => <article key={text(item.id)} className="space-y-1 rounded-md border p-2 text-xs"><p className="font-medium">{labels[text(item.status)] || text(item.status)} · 映射 v{text(item.watch_version)}</p><p>{new Date(text(item.created_at)).toLocaleString()} · 已提交执行 {text(item.attempts)} 次</p><p className="break-all">固定快照：{text(item.snapshot_id)}</p>
      {!!item.last_error_message && <p>{text(item.last_error_message)}{item.status === "queued" ? "（上次记录；本次尚待执行）" : ""}</p>}
      {!!item.scan_id && <p className="break-all">匹配回执：{text(item.scan_id)}；请在匹配历史读取具体命中。候选仍待人审核。</p>}
      {item.can_retry === true && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(async () => { await call(`${base}/${item.id}/retry`, { expected_attempts: item.attempts }); await load(); })}>核对后重试原输入</Button>}
    </article>)}
    {!!data?.next_before_id && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load(true))}>更早20项</Button>}
  </details>;
}
