"use client";

import { useEffect, useRef, useState } from "react";
import { MagnifyingGlass, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import { searchHref, searchKinds, type SearchItem, type SearchKind, type SearchPage } from "@/lib/object-search";

export function ObjectSearch({ api, onNavigate }: { api: WorkspaceTransport; onNavigate?: (href: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null), input = useRef<HTMLInputElement>(null);
  const opener = useRef<HTMLElement | null>(null), generation = useRef(0), busy = useRef(false);
  const [query, setQuery] = useState(""), [kind, setKind] = useState<SearchKind>("all");
  const [items, setItems] = useState<SearchItem[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [searched, setSearched] = useState(false), [asOf, setAsOf] = useState("");

  function invalidate() {
    generation.current++; busy.current = false;
    setLoading(false); setError(""); setItems([]); setCursor(null); setSearched(false); setAsOf("");
  }
  function open() {
    if (dialog.current?.open) { input.current?.focus(); return; }
    if (document.querySelector('dialog[open], [role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]')) return;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    invalidate(); dialog.current?.showModal(); input.current?.focus();
  }
  function close() {
    invalidate(); dialog.current?.close(); opener.current?.focus();
  }
  useEffect(() => {
    const lifecycle = generation;
    const keyboard = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && !event.isComposing) {
        event.preventDefault(); open();
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => { lifecycle.current++; window.removeEventListener("keydown", keyboard); };
  // The shortcut uses refs; current input and results are deliberately reset on opening.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  async function search(next?: string) {
    const q = query.trim();
    if (busy.current || !q) return;
    busy.current = true; const own = ++generation.current;
    setLoading(true); setError("");
    if (!next) { setItems([]); setSearched(false); setAsOf(""); setCursor(null); }
    try {
      const params = new URLSearchParams({ q, kind, page_size: "20" });
      if (next) params.set("cursor", next);
      const result = await api<SearchPage>(`v1/personal/search?${params}`);
      if (own !== generation.current) return;
      if (result.query !== q || result.kind !== kind) throw new Error("搜索结果与当前条件不一致，请重新搜索。");
      setItems(old => next ? [...old, ...result.items] : result.items);
      setCursor(result.next_cursor); setAsOf(result.as_of); setSearched(true);
    } catch (failure) {
      if (own === generation.current) setError((failure as Error).message || "搜索暂不可用，请重试。");
    } finally {
      if (own === generation.current) { busy.current = false; setLoading(false); }
    }
  }

  return <>
    <Button variant="ghost" aria-label="搜索对象" aria-keyshortcuts="Meta+K Control+K" title="搜索对象（⌘K / Ctrl K）" onClick={open}><MagnifyingGlass/><span className="hidden sm:inline">搜索</span></Button>
    <dialog ref={dialog} className="m-auto w-[min(42rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)] max-h-[85vh] overflow-auto" aria-label="搜索对象" onCancel={event => { event.preventDefault(); close(); }}>
      <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-semibold">搜索对象</h2><Button size="icon" variant="ghost" aria-label="关闭搜索" onClick={close}><X/></Button></div>
      <p className="subtle mt-2">按名称或完整 ID 查找你当前可读的项目、型号、立项提案和品类。</p>
      <form className="my-4 flex flex-wrap gap-2" onSubmit={event => { event.preventDefault(); void search(); }}>
        <label className="min-w-0 flex-1 basis-full sm:basis-auto"><span className="sr-only">名称或完整 ID</span><input ref={input} autoComplete="off" maxLength={200} value={query} placeholder="输入名称或完整 ID" onChange={event => { invalidate(); setQuery(event.target.value); }}/></label>
        <label className="min-w-0 flex-1 sm:flex-none"><span className="sr-only">对象类型</span><select value={kind} onChange={event => { invalidate(); setKind(event.target.value as SearchKind); }}>{Object.entries(searchKinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <Button type="submit" disabled={loading || !query.trim()}><MagnifyingGlass/>搜索</Button>
      </form>
      {loading && <p role="status" className="subtle">正在搜索当前可读对象…</p>}
      {error && <div role="alert" className="space-y-2"><p>{error}</p><Button variant="outline" disabled={loading} onClick={() => void search()}>重试搜索</Button></div>}
      {!loading && !error && !searched && <p className="subtle">输入名称或完整 ID 后搜索。</p>}
      {searched && items.length === 0 && <p role="status">当前条件下没有找到可读对象。可以调整名称、类型或完整 ID 后重试。</p>}
      <ul className="space-y-2" aria-label="搜索结果">{items.map(item => {
        const href = searchHref(item);
        const content = <><div className="flex flex-wrap gap-x-3 gap-y-1"><span className="text-primary text-xs">{searchKinds[item.kind]}</span><span className="font-medium break-words">{item.title}</span></div><p className="subtle mt-1 break-words">{item.category_name}</p><p className="subtle mt-1 break-all text-xs">{item.id}</p></>;
        return <li key={`${item.kind}:${item.id}`} className="min-w-0">{href ? <a className="block rounded-lg border border-border p-3 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring" href={href.startsWith("?") ? `/${href}` : href} onClick={event => {
          if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          close();
          if (href.startsWith("?") && onNavigate) { event.preventDefault(); onNavigate(href); }
        }}>{content}</a> : <div className="rounded-lg border border-border p-3">{content}<p className="subtle">此条目标识需重新核对。</p></div>}</li>;
      })}</ul>
      {cursor && !error && <Button className="mt-4" variant="outline" disabled={loading} onClick={() => void search(cursor)}>查看更多结果</Button>}
      {asOf && <p className="subtle mt-4 text-xs">按当前权限查询 · {new Date(asOf).toLocaleString("zh-CN")}</p>}
    </dialog>
  </>;
}
