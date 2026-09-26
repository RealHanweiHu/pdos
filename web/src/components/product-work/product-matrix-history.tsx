"use client";

import { useState } from "react";
import { Button } from "@/components/ui/button";
import { request } from "./product-work-api";
import { ProductMatrixDispositions } from "./product-matrix-dispositions";
import { ProductMatrixPreparation } from "./product-matrix-preparation";
import { CoverageResult, type Result } from "./product-matrix-coverage";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
type Summary = { id: string; series_id: string; version: number; title: string; reason: string; created_at: string; actor_name: string };
type History = { items: Summary[]; next_before_id: string | null };
type Detail = Summary & { result: Result; source_changes: string[]; current_source_warnings: string[]; result_digest: string };
type Replay = { matches_saved: boolean; formula_version: string; saved_digest: string; replayed_digest: string; scope: string };
export function ProductMatrixHistory({ base, onRead, onResume }: { base: string; onRead: (id: string) => void; onResume: (id: string) => Promise<void> }) {
  const [search, setSearch] = useState("");
  const [loadedSearch, setLoadedSearch] = useState("");
  const [history, setHistory] = useState<History | null>(null);
  const [series, setSeries] = useState<string | null>(null);
  const [detail, setDetail] = useState<Detail | null>(null);
  const [replay, setReplay] = useState<Replay | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const run = async (work: () => Promise<void>) => { setBusy(true); setError(null); try { await work(); } catch (failure) { setError(failure instanceof Error ? failure.message : "对照历史暂不可用"); } finally { setBusy(false); } };
  const load = async (text: string, seriesId: string | null = null, before: string | null = null) => { const value = await request<History>(`${base}/matrix-record-history`, "POST", { search: text, series_id: seriesId, before_id: before }); setHistory(old => before && old ? { ...value, items: [...old.items, ...value.items] } : value); setLoadedSearch(text); setSeries(seriesId); };
  return <section className="space-y-3 rounded-lg border p-4"><h3 className="font-semibold">已保存的市场覆盖对照</h3><p className="text-sm text-muted-foreground">保存时的需求、定义、判据和结果保持不变。读取时重新核对全部原资料权限；定义撤回后仍可在授权范围内回查历史。</p><form className="flex flex-wrap items-end gap-2" onSubmit={event => { event.preventDefault(); void run(() => load(search)); }}><label className="min-w-64 flex-1 text-sm">名称搜索<input maxLength={256} className={field} value={search} onChange={event => setSearch(event.target.value)}/></label><Button variant="outline" disabled={busy}>查询 / 刷新历史</Button></form>{error && <p role="alert" className="text-sm text-destructive">{error}</p>}{series && <p className="text-xs">当前只看所选对照的版本链。重新查询可返回全部记录。</p>}{history && <div className="space-y-2">{history.items.length === 0 && <p className="text-sm">没有符合条件且当前可访问的保存记录。</p>}{history.items.map(item => <article key={item.id} className="flex flex-wrap items-center justify-between gap-2 rounded-md border p-3"><div><p className="text-sm font-medium">{item.title} · v{item.version}</p><p className="text-xs text-muted-foreground">{item.actor_name} · {new Date(item.created_at).toLocaleString()} · {item.reason}</p></div><div className="flex gap-2"><Button size="sm" variant="outline" disabled={busy} onClick={() => void run(async () => { setReplay(null); setDetail(await request<Detail>(`${base}/matrix-record-read`, "POST", { record_id: item.id })); })}>原输入与结果</Button><Button size="sm" variant="ghost" disabled={busy} onClick={() => void run(() => load("", item.series_id))}>该对照全部版本</Button></div></article>)}{history.next_before_id && <Button size="sm" variant="outline" disabled={busy} onClick={() => void run(() => load(loadedSearch, series, history.next_before_id))}>读取更早记录</Button>}</div>}
    {detail && <section className="space-y-3 rounded-md border p-3"><div className="flex justify-between"><h4 className="font-medium">{detail.title} · v{detail.version} · {detail.actor_name}</h4><Button size="sm" variant="ghost" onClick={() => { setDetail(null); setReplay(null); }}>关闭记录</Button></div>{[...detail.source_changes, ...detail.current_source_warnings].map((text, index) => <p key={index} className="text-sm">{text}</p>)}<div className="flex flex-wrap gap-2"><Button variant="outline" disabled={busy} onClick={() => void run(async () => setReplay(await request<Replay>(`${base}/matrix-record-replay`, "POST", { record_id: detail.id })))}>按原输入与规则重算</Button><Button disabled={busy} onClick={() => void run(() => onResume(detail.id))}>带入当前依据接续修订</Button></div>{replay && <div className="space-y-1 rounded-md bg-muted p-3 text-sm"><p>{replay.matches_saved ? "按原输入重算与保存结果一致。" : "重算与保存结果不一致，请保留原记录并核对规则。"}</p><p>{replay.scope}</p><p className="break-all text-xs">{replay.formula_version} · 原 {replay.saved_digest} · 重算 {replay.replayed_digest}</p></div>}<CoverageResult value={detail.result} onRead={onRead}/><ProductMatrixDispositions key={`disposition:${detail.id}`} base={base} recordId={detail.id}/><ProductMatrixPreparation key={detail.id} base={base} recordId={detail.id}/></section>}
  </section>;
}
