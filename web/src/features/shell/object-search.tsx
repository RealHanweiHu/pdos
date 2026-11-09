"use client";

import { useEffect, useRef, useState, type KeyboardEvent as ReactKeyboardEvent } from "react";
import { ArrowRight, MagnifyingGlass, Plus, X } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import type { WorkspaceTransport } from "@/lib/workspace-api";
import { searchHref, searchKinds, type SearchItem, type SearchKind, type SearchPage } from "@/features/shell/lib/object-search";
import { commandHref, filterCommands, managedCategories, memberCanWrite, noSignals, paletteCommands, type PaletteCommand, type PaletteSignals } from "@/features/shell/lib/command-palette";

const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i;
type ProjectEntry = { category: { id: string }; product: { id: string }; project: { id: string; name: string } };

/** 打开面板时按服务器当前权限读取命令信号；任何一项读不回都只少显示命令，不会多显示。 */
async function readSignals(api: WorkspaceTransport): Promise<{ signals: PaletteSignals; incomplete: boolean }> {
  const location = new URLSearchParams(window.location.search);
  const projectId = location.get("project") ?? "", categoryId = location.get("category") ?? "";
  const inProject = location.get("area") === "cockpit" && uuid.test(projectId);
  const [categories, session, page] = await Promise.allSettled([
    api<unknown>("v1/categories"),
    inProject ? api<{ principal_id: string }>("v1/session") : Promise.resolve(null),
    inProject ? api<{ items: ProjectEntry[] }>(`v1/personal/projects/${projectId}`) : Promise.resolve(null),
  ]);
  let incomplete = categories.status === "rejected", project: PaletteSignals["project"] = null;
  const entry = page.status === "fulfilled" ? page.value?.items.find(item => item.project.id === projectId) : undefined;
  if (inProject && (session.status === "rejected" || page.status === "rejected")) incomplete = true;
  if (entry && (!categoryId || entry.category.id === categoryId) && session.status === "fulfilled" && session.value) {
    const scope = { category: entry.category.id, product: entry.product.id, project: entry.project.id };
    let canWrite = false;
    if ([scope.category, scope.product, scope.project].every(value => uuid.test(value))) {
      try {
        const work = await api<{ project?: { id?: unknown }; members?: unknown }>(`v1/categories/${scope.category}/products/${scope.product}/project-work?project_id=${encodeURIComponent(scope.project)}`);
        canWrite = work.project?.id === scope.project && memberCanWrite(work.members, session.value.principal_id);
      } catch { incomplete = true; }
    }
    project = { categoryId: scope.category, projectId: scope.project, name: entry.project.name, canWrite };
  }
  return { signals: { productManagement: categories.status === "fulfilled" ? managedCategories(categories.value) : [], project }, incomplete };
}

export function ObjectSearch({ api, onNavigate }: { api: WorkspaceTransport; onNavigate: (href: string) => void }) {
  const dialog = useRef<HTMLDialogElement>(null), input = useRef<HTMLInputElement>(null);
  const opener = useRef<HTMLElement | null>(null), generation = useRef(0), busy = useRef(false), signalGeneration = useRef(0);
  const [query, setQuery] = useState(""), [kind, setKind] = useState<SearchKind>("all");
  const [items, setItems] = useState<SearchItem[]>([]), [cursor, setCursor] = useState<string | null>(null);
  const [loading, setLoading] = useState(false), [error, setError] = useState("");
  const [searched, setSearched] = useState(false), [asOf, setAsOf] = useState("");
  const [signals, setSignals] = useState<PaletteSignals>(noSignals);
  const [signalState, setSignalState] = useState<"loading" | "ready" | "incomplete">("loading");
  const [active, setActive] = useState(-1);
  const commands = filterCommands(paletteCommands(signals), query);
  const groups = (["create", "navigate"] as const).map(group => ({ group, items: commands.filter(command => command.group === group) })).filter(entry => entry.items.length);
  const ordered = groups.flatMap(entry => entry.items);
  const activeCommand = active >= 0 ? ordered[active] : undefined;

  function invalidate() {
    generation.current++; busy.current = false;
    setLoading(false); setError(""); setItems([]); setCursor(null); setSearched(false); setAsOf("");
  }
  async function loadSignals() {
    const own = ++signalGeneration.current;
    setSignals(noSignals); setSignalState("loading");
    const result = await readSignals(api).catch(() => ({ signals: noSignals, incomplete: true }));
    if (own !== signalGeneration.current) return;
    setSignals(result.signals); setSignalState(result.incomplete ? "incomplete" : "ready");
  }
  function open() {
    if (dialog.current?.open) { input.current?.focus(); return; }
    if (document.querySelector('dialog[open], [role="dialog"][data-state="open"], [role="alertdialog"][data-state="open"]')) return;
    opener.current = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    invalidate(); setQuery(""); setActive(-1); dialog.current?.showModal(); input.current?.focus();
    void loadSignals();
  }
  function close() {
    invalidate(); signalGeneration.current++; setActive(-1); dialog.current?.close(); opener.current?.focus();
  }
  function run(command: PaletteCommand) {
    const href = commandHref(command);
    if (!href) return;
    close();
    onNavigate(href);
  }
  useEffect(() => {
    const lifecycle = generation, signalLifecycle = signalGeneration;
    const keyboard = (event: KeyboardEvent) => {
      if (event.key.toLowerCase() === "k" && (event.metaKey || event.ctrlKey) && !event.altKey && !event.shiftKey && !event.isComposing) {
        event.preventDefault(); open();
      }
    };
    window.addEventListener("keydown", keyboard);
    return () => { lifecycle.current++; signalLifecycle.current++; window.removeEventListener("keydown", keyboard); };
  // The shortcut uses refs; current input and results are deliberately reset on opening.
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);
  useEffect(() => { if (activeCommand) document.getElementById(`palette-${activeCommand.id}`)?.scrollIntoView({ block: "nearest" }); }, [activeCommand]);

  function onInputKey(event: ReactKeyboardEvent<HTMLInputElement>) {
    if (event.nativeEvent.isComposing || !ordered.length) return;
    if (event.key === "ArrowDown" || event.key === "ArrowUp") {
      event.preventDefault();
      const step = event.key === "ArrowDown" ? 1 : -1;
      setActive(current => current < 0 ? (step > 0 ? 0 : ordered.length - 1) : (current + step + ordered.length) % ordered.length);
    } else if (event.key === "Home" && active >= 0) { event.preventDefault(); setActive(0); }
    else if (event.key === "End" && active >= 0) { event.preventDefault(); setActive(ordered.length - 1); }
    else if (event.key === "Enter" && activeCommand) { event.preventDefault(); run(activeCommand); }
  }

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

  const groupLabels = { create: "快速创建", navigate: "跳转" } as const;
  return <>
    <Button variant="ghost" aria-label="搜索或执行命令" aria-keyshortcuts="Meta+K Control+K" title="搜索或执行命令（⌘K / Ctrl K）" onClick={open}><MagnifyingGlass/><span className="hidden sm:inline">搜索</span></Button>
    <dialog ref={dialog} className="m-auto w-[min(42rem,calc(100vw-2rem))] max-w-[calc(100vw-2rem)] max-h-[85dvh] overflow-auto max-sm:p-4" aria-label="搜索与命令" onCancel={event => { event.preventDefault(); close(); }}>
      <div className="flex items-center justify-between gap-3"><h2 className="text-lg font-semibold">搜索与命令</h2><Button size="icon" variant="ghost" aria-label="关闭搜索" onClick={close}><X/></Button></div>
      <p className="subtle mt-2">按名称或完整 ID 查找你当前可读的项目、型号、立项提案和品类；也可以选择下方命令。</p>
      <form className="my-4 flex flex-wrap gap-2" onSubmit={event => { event.preventDefault(); void search(); }}>
        <label className="min-w-0 flex-1 basis-full sm:basis-auto"><span className="sr-only">名称、完整 ID 或命令</span><input ref={input} role="combobox" aria-expanded={ordered.length > 0} aria-controls="palette-commands" aria-autocomplete="list" aria-activedescendant={activeCommand ? `palette-${activeCommand.id}` : undefined} autoComplete="off" maxLength={200} value={query} placeholder="输入名称、完整 ID 或命令" onKeyDown={onInputKey} onChange={event => { invalidate(); setActive(-1); setQuery(event.target.value); }}/></label>
        <label className="min-w-0 flex-1 sm:flex-none"><span className="sr-only">对象类型</span><select value={kind} onChange={event => { invalidate(); setKind(event.target.value as SearchKind); }}>{Object.entries(searchKinds).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
        <Button type="submit" disabled={loading || !query.trim()}><MagnifyingGlass/>搜索</Button>
      </form>
      <div role="listbox" id="palette-commands" aria-label="可执行的命令" hidden={!ordered.length} className="mb-4 border-b border-border pb-3">
        {groups.map(entry => <div role="group" key={entry.group} aria-labelledby={`palette-group-${entry.group}`}>
          <p id={`palette-group-${entry.group}`} role="presentation" className="px-2 pt-2 pb-1 text-[11px] text-[var(--text-tertiary)]">{groupLabels[entry.group]}</p>
          {entry.items.map(command => {
            const selected = command === activeCommand;
            return <div role="option" key={command.id} id={`palette-${command.id}`} aria-selected={selected} onMouseMove={() => { const index = ordered.indexOf(command); if (index !== active) setActive(index); }} onMouseDown={event => event.preventDefault()} onClick={() => run(command)} className={`flex min-h-9 cursor-pointer flex-wrap items-center gap-x-2.5 gap-y-0.5 rounded-md px-2 py-1.5 max-sm:min-h-11 ${selected ? "bg-muted" : ""}`}>
              {command.group === "create" ? <Plus size={15} className="shrink-0 text-[var(--text-subtle)]" aria-hidden="true"/> : <ArrowRight size={15} className="shrink-0 text-[var(--text-subtle)]" aria-hidden="true"/>}
              <span className="min-w-0 flex-1 truncate text-[13px]" title={command.label}>{command.label}</span>
              <span className={`text-xs text-[var(--text-subtle)] max-sm:basis-full max-sm:pl-[25px]${command.group === "navigate" ? " max-sm:hidden" : ""}`}>{command.hint}</span>
            </div>;
          })}
        </div>)}
      </div>
      {signalState === "loading" && !query.trim() && <p role="status" className="subtle mb-3">正在按当前权限读取可用命令…</p>}
      {signalState === "incomplete" && <div role="status" className="subtle mb-3 flex flex-wrap items-center gap-2"><span>部分权限暂未读回，相关命令没有显示。</span><Button size="xs" variant="ghost" onClick={() => void loadSignals()}>重新读取</Button></div>}
      {loading && <p role="status" className="subtle">正在搜索当前可读对象…</p>}
      {error && <div role="alert" className="space-y-2"><p>{error}</p><Button variant="outline" disabled={loading} onClick={() => void search()}>重试搜索</Button></div>}
      {!loading && !error && !searched && query.trim() && <p className="subtle">按 Enter 或“搜索”查找可读对象。</p>}
      {searched && items.length === 0 && <p role="status">当前条件下没有找到可读对象。可以调整名称、类型或完整 ID 后重试。</p>}
      <ul className="space-y-2" aria-label="搜索结果">{items.map(item => {
        const href = searchHref(item);
        const content = <><div className="flex flex-wrap gap-x-3 gap-y-1"><span className="text-primary text-xs">{searchKinds[item.kind]}</span><span className="font-medium break-words">{item.title}</span></div><p className="subtle mt-1 break-words">{item.category_name}</p><p className="subtle mt-1 break-all text-xs">{item.id}</p></>;
        return <li key={`${item.kind}:${item.id}`} className="min-w-0">{href ? <a className="block rounded-lg border border-border p-3 hover:bg-accent focus-visible:outline-2 focus-visible:outline-ring" href={href.startsWith("?") ? `/${href}` : href} onClick={event => {
          if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
          close();
          if (href.startsWith("?")) { event.preventDefault(); onNavigate(href); }
        }}>{content}</a> : <div className="rounded-lg border border-border p-3">{content}<p className="subtle">此条目标识需重新核对。</p></div>}</li>;
      })}</ul>
      {cursor && !error && <Button className="mt-4" variant="outline" disabled={loading} onClick={() => void search(cursor)}>查看更多结果</Button>}
      {asOf && <p className="subtle mt-4 text-xs">按当前权限查询 · {new Date(asOf).toLocaleString("zh-CN")}</p>}
      <p className="subtle mt-4 border-t border-border pt-3 text-[11px] max-sm:hidden">↑↓ 选择命令 · Enter 执行命令或搜索 · Esc 关闭 · 命令按你当前的权限列出，保存前仍需在原表单确认</p>
    </dialog>
  </>;
}
