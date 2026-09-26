"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { request, stateLabels } from "./product-work-api";

const labels = { research: "研究任务", work_items: "专业工作", experiments: "实验", strategies: "策略", definitions: "产品定义" };
type Kind = keyof typeof labels;
const kinds = Object.keys(labels) as Kind[];
type Item = { id: string; market_space_id: string; product_line_id: string | null; space_title: string; product_line_name: string | null; state: string; title?: string; question?: string; hypothesis?: string; due_at?: string | null; revision_number?: number };
type Page = { total: number; next_offset: number | null };
type Queue = Record<Kind, Item[]> & { pages?: Partial<Record<Kind, Page>> };

function itemLink(kind: Kind, item: Item) {
  const params = new URLSearchParams({ space: item.market_space_id });
  if (item.product_line_id) params.set("line", item.product_line_id);
  if (!["research", "work_items"].includes(kind)) params.set("tab", kind);
  const prefix = { research: "research", work_items: "work", experiments: "experiment", strategies: "strategy", definitions: "definition" }[kind];
  return `/product-work?${params}#${prefix}-${item.id}`;
}

function itemState(kind: Kind, state: string) {
  if (kind === "research" || kind === "work_items") return stateLabels[state] ?? state;
  if (kind === "experiments") return ({ draft: "待批准", approved: "待开始", running: "执行中" } as Record<string, string>)[state] ?? state;
  return state === "in_review" ? kind === "definitions" ? "待协审 / 发布" : "待审核" : state === "draft" ? "草稿" : state;
}

export function PreProjectWork() {
  const [data, setData] = useState<Queue | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(true);
  const [kind, setKind] = useState<Kind | "all">("all");
  const [shown, setShown] = useState(8);
  const sequence = useRef(0);
  const load = useCallback(async (collection?: Kind, offset = 0) => {
    const current = ++sequence.current;
    setBusy(true); setError(null);
    try {
      const value = await request<Queue>(collection ? `my-work?collection=${collection}&offset=${offset}&limit=100` : "my-work");
      if (current !== sequence.current) return;
      setData(previous => collection && previous ? {
        ...previous,
        [collection]: [...previous[collection], ...value[collection]].filter((item, index, items) => items.findIndex(other => other.id === item.id) === index),
        pages: { ...previous.pages, ...value.pages },
      } : value);
      if (collection) setShown(currentShown => currentShown + 100);
    } catch (failure) {
      if (current !== sequence.current) return;
      setData(null);
      setError(failure instanceof Error ? failure.message : "立项前工作暂不可用");
    } finally { if (current === sequence.current) setBusy(false); }
  }, []);
  useEffect(() => { let active = true; void Promise.resolve().then(() => { if (active) return load(); }); return () => { active = false; sequence.current += 1; }; }, [load]);
  const selectedKinds = kind === "all" ? kinds : [kind];
  const entries = data ? selectedKinds.flatMap(key => data[key].map(item => ({ kind: key, item }))) : [];
  const loaded = data ? kinds.reduce((n, key) => n + data[key].length, 0) : 0;
  const total = data && kinds.every(key => data.pages?.[key]) ? kinds.reduce((n, key) => n + data.pages![key]!.total, 0) : null;
  return <section aria-label="立项前工作" data-preproject-state={error ? "error" : busy ? "loading" : "ready"} className="mt-5 space-y-3 rounded-lg border bg-card p-4">
    <div className="flex flex-wrap items-center justify-between gap-3"><h2 className="font-semibold">立项前研究、专业工作与实验</h2><Button size="sm" variant="outline" disabled={busy} onClick={() => { setShown(8); void load(); }}>刷新立项前工作</Button></div>
    {busy && <p role="status" className="text-sm text-muted-foreground">正在读取立项前工作…</p>}
    {error && <p role="alert" className="text-sm text-destructive">{error}。请刷新重试；项目执行待办仍可办理。</p>}
    {data && <>
      <p className="text-sm text-muted-foreground">{total === null ? `已读取 ${loaded} 项；总数未知` : `共 ${total} 项，已读取 ${loaded} 项`}。按当前职责与读取权限列示，和项目执行待办分开计数。</p>
      {loaded === 0 ? <p className="text-sm text-muted-foreground">当前没有分派给你或等待你接收的立项前工作。</p> : <>
        <label className="block text-sm">立项前工作类型<select className="ml-2 max-w-full rounded-md border bg-background p-2" value={kind} onChange={event => { setKind(event.target.value as Kind | "all"); setShown(8); }}><option value="all">全部类型</option>{kinds.map(key => <option value={key} key={key}>{labels[key]} · {data.pages?.[key]?.total ?? `${data[key].length} 已读取`}</option>)}</select></label>
        <ul className="divide-y">{entries.slice(0, shown).map(({ kind: key, item }) => <li key={`${key}:${item.id}`}><Link className="block rounded-md px-2 py-3 hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" href={itemLink(key, item)}><p className="text-sm font-medium break-words">{item.question ?? item.hypothesis ?? item.title}{item.revision_number ? ` · 修订 ${item.revision_number}` : ""}</p><p className="text-xs text-muted-foreground">{item.space_title}{item.product_line_name ? ` / ${item.product_line_name}` : ""} · {labels[key]} · {itemState(key, item.state)}{item.due_at ? ` · 目标 ${new Date(item.due_at).toLocaleDateString()}` : ""}</p></Link></li>)}</ul>
        {!entries.length && <p className="text-sm text-muted-foreground">当前类型没有待办。</p>}
        {entries.length > shown && <Button size="sm" variant="outline" onClick={() => setShown(value => value + 20)}>显示更多已读取工作（{shown}/{entries.length}）</Button>}
      </>}
      <div className="flex flex-wrap gap-2">{selectedKinds.map(key => data.pages?.[key]?.next_offset != null && <Button key={key} size="sm" variant="outline" disabled={busy} onClick={() => void load(key, data.pages![key]!.next_offset!)}>继续读取{labels[key]}</Button>)}</div>
      {total !== null && total > loaded && <p className="text-xs text-muted-foreground">仍有工作未读取。列表可能随办理变化，刷新可重新核对当前待办。</p>}
    </>}
  </section>;
}
