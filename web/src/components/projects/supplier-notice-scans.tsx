"use client";

import { useRef, useState } from "react";
import { SupplierNoticeReviews } from "./supplier-notice-reviews";
import { SupplierNoticeDispatches } from "./supplier-notice-dispatches";
import { Button } from "@/components/ui/button";
import { obj, rows, text, type Row } from "@/components/quality/fmea-sources";
import { responseBody } from "@/components/workspace-api";

async function call(url: string, body?: Row): Promise<Row> { const response = await fetch(url, { method: body ? "POST" : "GET", cache: "no-store", headers: body ? { "Content-Type": "application/json" } : undefined, body: body ? JSON.stringify(body) : undefined }); const value = obj(await responseBody(response).catch(() => null)); if (!response.ok) throw new Error(text(obj(value.detail).message) || "匹配结果暂未确认，请读取原回执"); return value; }
function Source({ value }: { value: Row }) { const snap = obj(value.snapshot), source = obj(obj(value.watch_source).source), part = obj(obj(value.watch_source).bom_item); return <div className="space-y-1 text-xs"><p>{text(value.manufacturer)} · {text(value.part_number)} · 原BOM {text(part.bom_code)} v{text(part.bom_version)}</p><p>公开来源：{text(source.name)} · {text(snap.url)}</p><p>原采集时间：{new Date(text(snap.captured_at)).toLocaleString()} · {snap.freshness_expires_at ? `复查期限 ${new Date(text(snap.freshness_expires_at)).toLocaleString()}` : "未设复查期限"}</p><p>使用范围：{text(source.allowed_use)} · {text(source.license_note) || "无补充许可说明"}</p></div>; }
export function SupplierNoticeScans({ projectId, watchId }: { projectId: string; watchId: string }) {
  const [data, setData] = useState<Row | null>(null), [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState("");
  const attempts = useRef(new Map<string, string>());
  const base = `/api/projects/${projectId}/npi/supplier-notices/watches/${watchId}/scans`;
  async function load(more = false) { const result = await call(`${base}${more && data?.next_before_id ? `?before_id=${data.next_before_id}` : ""}`); setData(old => more && old ? { ...result, items: [...rows(old.items), ...rows(result.items)] } : result); }
  async function act(work: () => Promise<void>) { setBusy(true); setError(null); try { await work(); } catch (e) { setError(e instanceof Error ? e.message : "操作未完成"); } finally { setBusy(false); } }
  async function scan() { const command = { expected_version: data?.watch_version, snapshot_id: obj(obj(data?.current).snapshot).id }; const key = JSON.stringify(command); let id = attempts.current.get(key); if (!id) { id = crypto.randomUUID(); attempts.current.set(key, id); } const result = await call(base, { ...command, request_id: id }); setNotice(result.outcome === "matched" ? "已保存原文命中与候选关联，重复片段复用原候选。" : result.truncated === true ? "已保存本次局部检查，尚未发现邻近通告线索；完整范围仍须核对。" : "已保存本次检查，未发现完整料号与邻近通告词同时命中。仍需注意覆盖限制。"); await load(); }
  return <details className="space-y-3 rounded-md border p-3 text-sm" onToggle={e => { if (e.currentTarget.open && !data && !busy) void act(() => load()); }}><summary className="cursor-pointer font-medium">匹配已有通告快照与查看待审线索</summary>
    <p className="text-xs text-muted-foreground">只读取原订阅已成功保存的公开文字，不发起外部检索。完整料号旁出现通告词仅形成候选，厂商真实性、适用性、日期及影响仍待人审。</p>
    <SupplierNoticeDispatches projectId={projectId} watchId={watchId}/>
    {error && <p role="alert" className="text-destructive">{error}</p>}{notice && <p role="status">{notice}</p>}
    <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load())}>读取当前快照与匹配历史</Button>
    {!!data?.current_error && <p className="text-xs">{text(data.current_error)}</p>}{data?.current != null && <Source value={obj(data.current)}/>}
    {data?.can_scan === true && <Button size="sm" disabled={busy} onClick={() => void act(scan)}>按当前已保存快照匹配</Button>}
    {rows(data?.items).map(s => <details className="space-y-2 rounded-md border p-3" key={text(s.id)}><summary className="cursor-pointer">{new Date(text(s.created_at)).toLocaleString()} · {s.content_available === false ? "原来源停用，原文暂不可读取" : s.outcome === "matched" ? `${rows(s.matches).length} 处通告线索` : s.truncated === true ? "局部未发现线索" : "未发现线索"}</summary><Source value={obj(s.source_snapshot)}/><p>{s.scope_current === true ? "在用范围当前一致" : "在用范围或来源已变化／不可用，请重新核对"} · {s.snapshot_current === true ? "原订阅当前快照" : "历史快照"}</p><p className="whitespace-pre-wrap text-xs">{text(s.coverage)}</p><p className="text-xs">已检查完整料号命中：{text(s.full_part_hits)}{s.truncated === true ? "；已达到本轮上限，尚有范围未检查。" : "。"}</p>
      {rows(s.matches).map((m, index) => <article className="space-y-1 border-l pl-3" key={`${text(m.candidate_id)}:${index}`}><h5 className="font-medium">{text(m.part)} · {text(m.marker)} · 通告线索</h5><p className="text-xs">{m.created === true ? "首次保存候选" : "复用已有候选，本次保留新命中位置"}</p>{rows(m.quotes).map((q, i) => <blockquote className="rounded-md bg-muted/40 p-2 text-xs" key={i}><p>原文字符 {Number(q.start)+1}—{text(q.end)}</p><p className="whitespace-pre-wrap break-words">{text(q.text)}</p></blockquote>)}<SupplierNoticeReviews projectId={projectId} candidateId={text(m.candidate_id)}/></article>)}
    </details>)}
    {!!data?.next_before_id && <Button size="sm" variant="outline" disabled={busy} onClick={() => void act(() => load(true))}>更早20次匹配</Button>}
  </details>;
}
