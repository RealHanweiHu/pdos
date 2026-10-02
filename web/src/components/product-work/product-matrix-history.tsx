"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { request, ProductRequestError } from "./product-work-api";
import { ProductMatrixDispositions } from "./product-matrix-dispositions";
import { ProductMatrixPreparation } from "./product-matrix-preparation";
import { CoverageResult, type Result } from "./product-matrix-coverage";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
type Summary = { id: string; series_id: string; version: number; title: string; reason: string; created_at: string; actor_name: string };
type History = { items: Summary[]; next_before_id: string | null };
type Detail = Summary & { product_line_id?: string | null; result: Result; source_changes: string[]; current_source_warnings: string[]; result_digest: string };
type Replay = { matches_saved: boolean; formula_version: string; saved_digest: string; replayed_digest: string; scope: string };
type Props = { base: string; onRead: (id: string) => void; onResume: (id: string) => Promise<void>; initialRecordId?: string; initialRunId?: string };
export function ProductMatrixHistory(props: Props) { return <MatrixHistoryPanel key={JSON.stringify([props.base, props.initialRecordId])} {...props}/>; }
function MatrixHistoryPanel({ base, onRead, onResume, initialRecordId, initialRunId }: Props) {
  const [search, setSearch] = useState("");
  const [loadedSearch, setLoadedSearch] = useState("");
  const [history, setHistory] = useState<History | null>(null);
  const [series, setSeries] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [busy, setBusy] = useState(!!initialRecordId);
  const live = useRef(true), revision = useRef(0);
  const [error, setError] = useState<string | null>(null);
  useEffect(() => {
    live.current = true;
    if (initialRecordId) {
      const current = ++revision.current;
      if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i.test(initialRecordId)) { queueMicrotask(() => { if (live.current && current === revision.current) { setError("矩阵记录编号无效，请从保存记录入口重新打开。"); setBusy(false); } }); }
      else void request<Detail>(`${base}/matrix-record-read`, "POST", { record_id: initialRecordId }).then(value => { if (live.current && current === revision.current) { if (value.id !== initialRecordId) throw new Error("返回的矩阵记录不符"); setDetail(value); } }).catch(failure => { if (live.current && current === revision.current) setError(failure instanceof Error ? failure.message : "原记录暂不可读"); }).finally(() => { if (live.current && current === revision.current) setBusy(false); });
    }
    return () => { live.current = false; revision.current += 1; };
  }, [base, initialRecordId]);
  const recordHref = (id: string) => { const space = base.match(/(?:^|\/)spaces\/([^/]+)/)?.[1]; return space ? `/product-work?${new URLSearchParams({ space, tab: "matrix", record_id: id, ...(detail?.id === id && detail.product_line_id ? { line: detail.product_line_id } : {}) })}` : null; };
  const run = async (work: () => Promise<void>) => { setBusy(true); setError(null); const current = revision.current; try { await work(); } catch (failure) { if (!live.current || current !== revision.current) return; if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) { setHistory(null); setDetail(null); setReplay(null); } setError(failure instanceof Error ? failure.message : "对照历史暂不可用"); } finally { if (live.current && current === revision.current) setBusy(false); } };
  const load = async (text: string, seriesId: string | null = null, before: string | null = null) => { const value = await request<History>(`${base}/matrix-record-history`, "POST", { search: text, series_id: seriesId, before_id: before }); if (!live.current) return; setHistory(old => before && old ? { ...value, items: [...old.items, ...value.items] } : value); setLoadedSearch(text); setSeries(seriesId); };
  return <section className="space-y-3 rounded-lg border p-4"><h3 className="font-semibold">已保存的市场覆盖对照</h3><p className="text-sm text-muted-foreground">保存时的需求、定义、判据和结果保持不变。读取时重新核对全部原资料权限；定义撤回后仍可在授权范围内回查历史。</p><form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); void run(() => load(search)); }}><label className="min-w-64 flex-1 text-sm">名称搜索<input maxLength={256} className={field} value={search} onChange={event => setSearch(event.target.value)}/></label><Button variant="outline" disabled={busy}>查询 / 刷新历史</Button></form>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}{series && <p className="text-xs">当前只看所选对照的版本链。重新查询可返回全部记录。</p>}{history && <div className="space-y-2">{history.items.length === 0 && <p className="text-sm">没有符合条件且当前可访问的保存记录。</p>}{history.items.map(item => <article key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3"><div><p className="text-sm font-medium">{item.title} · v{item.version}</p><p className="text-xs text-muted-foreground">{item.actor_name} · {new Date(item.created_at).toLocaleString()} · {item.reason}</p></div><div className="flex gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void run(async () => { setReplay(null); const value = await request<Detail>(`${base}/matrix-record-read`, "POST", { record_id: item.id }); if (live.current) setDetail(value); })}>原输入与结果</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => load("", item.series_id))}>该对照全部版本</Button></div></article>)}{history.next_before_id && <Button size="sm" variant="outline" disabled={busy} onClick={() => void run(() => load(loadedSearch, series, history.next_before_id))}>读取更早记录</Button>}</div>}
    {detail && <section className="space-y-3 rounded-md border p-3"><div className="flex justify-between"><h4 className="font-medium">{detail.title} · v{detail.version} · {detail.actor_name}</h4><Button size="sm" variant="ghost" onClick={() => { setDetail(null); setReplay(null); }}>关闭记录</Button></div>{[...detail.source_changes, ...detail.current_source_warnings].map((text, index) => <p key={index} className="text-sm">{text}</p>)}<div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void run(async () => setReplay(await request<Replay>(`${base}/matrix-record-replay`, "POST", { record_id: detail.id })))}>按原输入与规则重算</Button><Button disabled={busy} onClick={() => void run(() => onResume(detail.id))}>带入当前依据接续修订</Button></div>{replay && <div className="space-y-1 rounded-md bg-muted p-3 text-sm"><p>{replay.matches_saved ? "按原输入重算与保存结果一致。" : "重算与保存结果不一致，请保留原记录并核对规则。"}</p><p>{replay.scope}</p><p className="break-all text-xs">{replay.formula_version} · 原 {replay.saved_digest} · 重算 {replay.replayed_digest}</p></div>}{recordHref(detail.id) && <div className="flex gap-3 text-sm"><a className="underline" href={recordHref(detail.id)!}>此原矩阵记录的固定入口</a><a className="underline" href={`/ask?${new URLSearchParams({ source: recordHref(detail.id)! })}`}>带此原记录与小Pai对话</a></div>}<CoverageResult value={detail.result} onRead={onRead}/><ProductMatrixDispositions key={`disposition:${detail.id}`} base={base} recordId={detail.id}/><ProductMatrixPreparation initialRunId={initialRunId} key={detail.id} base={base} recordId={detail.id}/></section>}
  </section>;
}
