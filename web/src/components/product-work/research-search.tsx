"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { request, type SearchObservation } from "./product-work-api";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const statuses: Record<string, string> = { running: "搜索中 / 等待结果", completed: "已返回候选", partial: "结果不完整", no_results: "本次查询无命中", unavailable: "来源暂不可用", not_configured: "搜索未配置", denied: "查询被拒绝", failed: "搜索未完成" };

export function ResearchSearch({ base, lineId, configured, canSearch, onPick }: { base: string; lineId: string | null; configured: boolean; canSearch: boolean; onPick: (url: string, title: string) => void }) {
  const [history, setHistory] = useState<SearchObservation[]>([]);
  const [selected, setSelected] = useState<SearchObservation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const last = useRef({ body: "", requestId: "" });
  const load = async () => { const value = await request<{ items: SearchObservation[] }>(`${base}/searches`); setHistory(value.items); return value.items; };
  useEffect(() => {
    let live = true;
    void request<{ items: SearchObservation[] }>(`${base}/searches`).then((value) => { if (live) setHistory(value.items); }).catch((failure) => { if (live) setError(failure.message); });
    return () => { live = false; };
  }, [base]);
  const submit = async (form: FormData) => {
    const body = { query: String(form.get("query")).trim(), language: String(form.get("language")), time_range: form.get("time_range") || null, result_limit: 5, product_line_id: lineId };
    const fingerprint = JSON.stringify(body);
    if (last.current.body !== fingerprint) last.current = { body: fingerprint, requestId: crypto.randomUUID() };
    setBusy(true); setError(null);
    try {
      const result = await request<SearchObservation>(`${base}/searches`, "POST", { ...body, request_id: last.current.requestId }); setSelected(result); await load();
      // A deliberate later search makes a new observation; a failed transport retains the original request identity.
      if (result.status !== "running") last.current = { body: "", requestId: "" };
    } catch (failure) { setError(failure instanceof Error ? failure.message : "搜索暂不可用"); }
    finally { setBusy(false); }
  };
  const visible = history.filter((item) => item.product_line_id === lineId);
  return <section className="space-y-3 rounded-md border p-3"><h4 className="font-medium">搜索研究来源</h4><p className="text-xs text-muted-foreground">{configured ? "搜索服务已配置。" : "尚未配置搜索服务，可直接采集已知公开页面。"}查询词会发送给搜索服务；候选摘要仅作线索，采集为快照后才能用于研究引用。</p>
    {canSearch && <form className="grid gap-2 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); void submit(new FormData(event.currentTarget)); }}><label className="text-sm sm:col-span-2">研究问题 / 关键词<input required name="query" maxLength={512} className={field} placeholder="请输入适合公开搜索的关键词" /></label><label className="text-sm">结果语言<select name="language" className={field}><option value="auto">搜索服务默认</option><option value="zh-CN">中文</option><option value="en">英文</option></select></label><label className="text-sm">时间范围<select name="time_range" className={field}><option value="">不限</option><option value="day">近一天</option><option value="month">近一月</option><option value="year">近一年</option></select></label><Button disabled={busy || !configured} className="justify-self-start">{busy ? "正在搜索…" : "搜索来源"}</Button></form>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex flex-wrap items-center gap-2"><label className="min-w-0 flex-1 text-sm">此范围的近期查询<select value={selected?.id ?? ""} className={field} onChange={(event) => setSelected(history.find((item) => item.id === event.target.value) ?? null)}><option value="">选择一条查询</option>{visible.map((item) => <option key={item.id} value={item.id}>{new Date(item.started_at).toLocaleString()} · {item.query} · {statuses[item.status]}</option>)}</select></label><Button size="sm" variant="outline" disabled={busy} onClick={() => { setBusy(true); setError(null); void load().then((items) => { if (selected) setSelected(items.find((item) => item.id === selected.id) ?? null); }).catch((failure) => setError(failure.message)).finally(() => setBusy(false)); }}>刷新结果</Button></div>
    {selected && <div className="space-y-2"><p className="text-sm font-medium">{statuses[selected.status]} · {selected.query}</p><p className="text-xs text-muted-foreground">{new Date(selected.finished_at ?? selected.started_at).toLocaleString()} · {selected.provider_key}{selected.time_range ? " · 时间筛选以各搜索引擎支持情况为准" : ""}</p>{selected.error_message && <p className="text-sm text-destructive">{selected.error_message}</p>}{selected.warnings.map((warning, i) => <p key={i} className="text-sm text-muted-foreground">{warning}</p>)}<ul className="space-y-2">{selected.hits.map((hit) => <li key={hit.url} className="space-y-1 rounded-md bg-muted p-3"><p className="text-sm font-medium">{hit.title}</p><p className="text-sm">{hit.snippet}</p><p className="break-all text-xs text-muted-foreground">{hit.url}</p><Button size="sm" variant="outline" onClick={() => onPick(hit.url, hit.title)}>用于页面采集</Button></li>)}</ul></div>}
  </section>;
}
