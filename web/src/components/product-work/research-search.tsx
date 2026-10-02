"use client";

import { useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { ProductRequestError, request, type SearchObservation } from "./product-work-api";

const field = "mt-1 w-full rounded-md border bg-background p-2 text-sm";
const statuses: Record<string, string> = { running: "搜索中 / 等待结果", completed: "已返回候选", partial: "结果不完整", no_results: "本次查询无命中", unavailable: "来源暂不可用", not_configured: "搜索未配置", denied: "查询被拒绝", failed: "搜索未完成" };

type ResearchSearchProps = { base: string; lineId: string | null; configured: boolean | null; canSearch: boolean; onPick: (url: string, title: string) => void };

export function ResearchSearch(props: ResearchSearchProps) {
  // Scope changes discard request identities and pending responses together with visible evidence.
  return <ScopedResearchSearch key={JSON.stringify([props.base, props.lineId])} {...props} />;
}

function ScopedResearchSearch({ base, lineId, configured, canSearch, onPick }: ResearchSearchProps) {
  const [history, setHistory] = useState<SearchObservation[]>([]);
  const [selected, setSelected] = useState<SearchObservation | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const last = useRef({ body: "", requestId: "" });
  const historyVersion = useRef(0);
  const load = async () => {
    const version = ++historyVersion.current;
    const value = await request<{ items: SearchObservation[] }>(`${base}/searches`);
    if (version !== historyVersion.current) return { items: [], recovered: undefined };
    setHistory(value.items);
    const recovered = value.items.find(item => item.request_id === last.current.requestId && item.product_line_id === lineId);
    if (recovered) {
      setSelected(recovered);
      if (recovered.status !== "running") last.current = { body: "", requestId: "" };
    }
    return { items: value.items, recovered };
  };
  function failed(failure: unknown, fallback = "搜索暂不可用") {
    if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) {
      historyVersion.current += 1;
      setHistory([]); setSelected(null); last.current = { body: "", requestId: "" };
    }
    setError(failure instanceof Error ? failure.message : fallback);
  }
  useEffect(() => {
    let live = true;
    const version = ++historyVersion.current;
    void request<{ items: SearchObservation[] }>(`${base}/searches`).then((value) => { if (live && version === historyVersion.current) setHistory(value.items); }).catch((failure) => { if (live && version === historyVersion.current) setError(failure.message); });
    return () => { live = false; };
  }, [base]);
  const submit = async (form: FormData) => {
    const body = { query: String(form.get("query")).trim(), language: String(form.get("language")), time_range: form.get("time_range") || null, result_limit: 5, product_line_id: lineId };
    const fingerprint = JSON.stringify(body);
    if (last.current.body !== fingerprint) last.current = { body: fingerprint, requestId: crypto.randomUUID() };
    historyVersion.current += 1;
    setBusy(true); setError(null); setSelected(null);
    try {
      const result = await request<SearchObservation>(`${base}/searches`, "POST", { ...body, request_id: last.current.requestId }); setSelected(result);
      // A deliberate later search makes a new observation; a failed transport retains the original request identity.
      if (result.status !== "running") last.current = { body: "", requestId: "" };
      try { await load(); } catch (failure) {
        if (failure instanceof ProductRequestError && [401, 403].includes(failure.status)) failed(failure);
        else setError(`搜索已返回，查询列表刷新失败：${failure instanceof Error ? failure.message : "请稍后刷新"}`);
      }
    } catch (failure) { failed(failure); }
    finally { setBusy(false); }
  };
  const visible = history.filter((item) => item.product_line_id === lineId);
  return <section className="space-y-3 rounded-md border p-3"><h4 className="font-medium">搜索研究来源</h4><p className="text-xs text-muted-foreground">{configured === null ? "搜索服务配置尚未确认。" : configured ? "搜索服务已配置。" : "尚未配置搜索服务，可直接采集已知公开页面。"}查询词会发送给搜索服务；候选摘要仅作线索，采集为快照后才能用于研究引用。</p>
    {canSearch && <form className="grid gap-2 sm:grid-cols-2" onSubmit={(event) => { event.preventDefault(); void submit(new FormData(event.currentTarget)); }}><label className="text-sm sm:col-span-2">研究问题 / 关键词<input required name="query" maxLength={512} className={field} placeholder="请输入适合公开搜索的关键词" /></label><label className="text-sm">结果语言<select name="language" className={field}><option value="auto">搜索服务默认</option><option value="zh-CN">中文</option><option value="en">英文</option></select></label><label className="text-sm">时间范围<select name="time_range" className={field}><option value="">不限</option><option value="day">近一天</option><option value="month">近一月</option><option value="year">近一年</option></select></label><Button disabled={busy || !configured} className="justify-self-start">{busy ? "正在搜索…" : "搜索来源"}</Button></form>}
    {error && <p role="alert" className="text-sm text-destructive">{error}</p>}
    <div className="flex flex-wrap items-center gap-2"><label className="min-w-0 flex-1 text-sm">此范围的近期查询<select value={selected?.id ?? ""} className={field} onChange={(event) => setSelected(visible.find((item) => item.id === event.target.value) ?? null)}><option value="">选择一条查询</option>{visible.map((item) => <option key={item.id} value={item.id}>{new Date(item.started_at).toLocaleString()} · {item.query} · {statuses[item.status]}</option>)}</select></label><Button size="sm" variant="outline" disabled={busy} onClick={() => { setBusy(true); setError(null); void load().then(({ items, recovered }) => { if (selected && !recovered) setSelected(items.find((item) => item.id === selected.id) ?? null); }).catch((failure) => failed(failure)).finally(() => setBusy(false)); }}>刷新结果</Button></div>
    {selected && <div className="space-y-2"><p className="text-sm font-medium">{statuses[selected.status]} · {selected.query}</p><p className="text-xs text-muted-foreground">{new Date(selected.finished_at ?? selected.started_at).toLocaleString()} · {selected.provider_key}{selected.time_range ? " · 时间筛选以各搜索引擎支持情况为准" : ""}</p>{selected.error_message && <p className="text-sm text-destructive">{selected.error_message}</p>}{selected.warnings.map((warning, i) => <p key={i} className="text-sm text-muted-foreground">{warning}</p>)}<ul className="space-y-2">{selected.hits.map((hit) => <li key={hit.url} className="space-y-1 rounded-md bg-muted p-3"><p className="text-sm font-medium">{hit.title}</p><p className="text-sm">{hit.snippet}</p><p className="break-all text-xs text-muted-foreground">{hit.url}</p><Button size="sm" variant="outline" onClick={() => onPick(hit.url, hit.title)}>用于页面采集</Button></li>)}</ul></div>}
  </section>;
}
