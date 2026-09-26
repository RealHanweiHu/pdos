"use client";

import dynamic from "next/dynamic";
import { DeferredPanelLoading, withDeferredPanelBoundary } from "@/components/deferred-panel-loading";

import { useRef, useState } from "react";
import { Button } from "@/components/ui/button";
import { requestProjectList } from "@/components/projects/project-api";
import type { Project } from "@/components/projects/project-types";
import { requestMyWork, type MyWorkQuery } from "./my-work-api";
import type { MyWork, MyWorkCollection, MyWorkIdDesign } from "./my-work-types";
import { workSearchEntries, workKindLabels, searchEntryTitle, searchEntryKey, searchEntryDate, type WorkSearchEntry } from "./work-search-entries";
import { workDate } from "./work-dates";

const WorkSearchCard = withDeferredPanelBoundary(dynamic(() => import("./work-search-card").then(module => module.WorkSearchCard), { loading: DeferredPanelLoading }));

const focusLabels = { all: "全部", overdue: "已逾期", today: "今日到期", blocked: "已阻塞", high: "高优先／严重", confirm: "待审阅／确认" };
export function WorkSearch({ today, handoffs, onChanged }: { today: string; handoffs: MyWorkIdDesign[]; onChanged: () => Promise<void> }) {
  const [projects, setProjects] = useState<Project[]>([]), [projectsLoaded, setProjectsLoaded] = useState(false);
  const [projectError, setProjectError] = useState<string | null>(null), [projectBusy, setProjectBusy] = useState(false);
  const [project, setProject] = useState(""), [search, setSearch] = useState("");
  const [focus, setFocus] = useState<NonNullable<MyWorkQuery["focus"]>>("all"), [kind, setKind] = useState<MyWorkCollection | "">("");
  const [result, setResult] = useState<MyWork | null>(null), [applied, setApplied] = useState<MyWorkQuery | null>(null);
  const [busy, setBusy] = useState(false), [error, setError] = useState<string | null>(null), [notice, setNotice] = useState<string | null>(null);
  const [opened, setOpened] = useState<WorkSearchEntry[]>([]);
  const sequence = useRef(0);
  async function loadProjects() {
    if (projectBusy) return;
    setProjectBusy(true); setProjectError(null);
    try { const list = await requestProjectList(); if (!list) throw new Error("登录已失效"); setProjects(list); setProjectsLoaded(true); }
    catch (failure) { setProjectError(failure instanceof Error ? failure.message : "项目选项读取失败；可先按标题或项目名称查找。"); }
    finally { setProjectBusy(false); }
  }
  async function run(query: MyWorkQuery) {
    const request = ++sequence.current;
    setBusy(true); setError(null);
    try {
      const value = await requestMyWork(query);
      if (!value) throw new Error("登录已失效，请重新登录。");
      if (request === sequence.current) { setResult(value); setApplied(query); }
    } catch (failure) { if (request === sequence.current) setError(failure instanceof Error ? failure.message : "查找失败，之前结果保留。"); }
    finally { if (request === sequence.current) setBusy(false); }
  }
  async function more(collection: MyWorkCollection) {
    const cursor = result?.pages?.[collection];
    if (!result || !applied || busy || !cursor || cursor.next_offset === null) return;
    const request = ++sequence.current;
    setBusy(true); setError(null);
    try {
      const value = await requestMyWork({ ...applied, collection, offset: cursor.next_offset, expected_revision: cursor.revision, limit: 50 });
      if (!value) throw new Error("登录已失效，请重新登录。");
      const received = value.pages?.[collection];
      if (!received || received.revision !== cursor.revision || received.offset !== (result[collection] ?? []).length) throw new Error("筛选结果已变化，请重新查找后继续。");
      if (request === sequence.current) setResult({ ...result, [collection]: [...(result[collection] ?? []), ...(value[collection] ?? [])], pages: { ...result.pages, [collection]: received }, counts: { ...result.counts, [collection]: value.counts[collection] ?? 0 } });
    } catch (failure) { if (request === sequence.current) setError(failure instanceof Error ? failure.message : "更多结果加载失败"); }
    finally { if (request === sequence.current) setBusy(false); }
  }
  async function recorded() {
    const request = sequence.current;
    const query = applied;
    await onChanged();
    setNotice("已刷新待办。打开的办理表单保留，请按其中的当前状态和回执继续。");
    if (query && request === sequence.current) await run(query);
  }
  const entries = result ? workSearchEntries(result) : [];
  const total = result ? Object.values(result.counts).reduce((sum, count) => sum + (count ?? 0), 0) : 0;
  return <details className="mt-4 rounded-lg border bg-card p-4" onToggle={event => { if (event.currentTarget.open && !projectsLoaded && !projectBusy) void loadProjects(); }}>
    <summary className="cursor-pointer font-semibold">查找完整待办范围</summary>
    <div className="mt-3 space-y-3">
      <p className="text-xs text-muted-foreground">在本人可见的全部待办中筛选，包含首页尚未加载的记录。日期按 Asia/Shanghai、{today} 判断；高优先筛选仅使用任务优先级和问题严重度。切换筛选不会关闭下面已打开的表单。</p>
      <form onSubmit={event => { event.preventDefault(); void run({ ...(project ? { project_id: project } : {}), ...(kind ? { collection: kind } : {}), search: search.trim(), focus, as_of_date: today, limit: 20 }); }}>
        <fieldset disabled={busy} className="flex flex-wrap items-end gap-3 text-sm">
          <label>项目<select value={project} onChange={event => setProject(event.target.value)} className="ml-2 max-w-full rounded-md border bg-background p-2"><option value="">全部可见项目</option>{projects.map(value => <option value={value.id} key={value.id}>{value.code} · {value.name}</option>)}</select></label>
          <label>类型<select value={kind} onChange={event => setKind(event.target.value as MyWorkCollection | "")} className="ml-2 rounded-md border bg-background p-2"><option value="">全部类型</option>{Object.entries(workKindLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
          <label>优先事项<select value={focus} onChange={event => setFocus(event.target.value as typeof focus)} className="ml-2 rounded-md border bg-background p-2">{Object.entries(focusLabels).map(([key, label]) => <option value={key} key={key}>{label}</option>)}</select></label>
          <label className="min-w-0 flex-1">标题或项目<input className="mt-1 w-full rounded-md border bg-background p-2" value={search} maxLength={200} onChange={event => setSearch(event.target.value)} placeholder="输入标题、项目名称或项目编号"/></label>
          <Button type="submit">{busy ? "正在查找…" : "查找全部待办"}</Button>
        </fieldset>
      </form>
      {projectError && <div className="text-xs text-destructive">{projectError}<Button size="sm" variant="ghost" disabled={projectBusy} onClick={() => void loadProjects()}>重读项目选项</Button></div>}
      {error && <p role="alert" className="text-sm text-destructive">{error} 之前读取的结果和表单保留。</p>}
      {notice && <p role="status" className="text-sm">{notice}</p>}
      {result && applied && <section className="space-y-3" aria-label="完整待办筛选结果">
        <p className="text-sm">已提交条件：{applied.project_id ? projects.find(value => value.id === applied.project_id)?.name ?? "指定项目" : "全部可见项目"} · {applied.collection ? workKindLabels[applied.collection] : "全部类型"} · {focusLabels[applied.focus ?? "all"]}{applied.search ? ` · “${applied.search}”` : ""} · 共 {total} 条匹配，已加载 {entries.length} 条。</p>
        {total === 0 && <p className="text-sm text-muted-foreground">当前权限和筛选条件下没有匹配待办。</p>}
        {(Object.keys(workKindLabels) as MyWorkCollection[]).filter(collection => (result.counts[collection] ?? 0) > 0).map(collection => <section className="rounded-md border" key={collection} aria-label={`${workKindLabels[collection]}查找结果`}><h3 className="border-b p-2 text-sm font-medium">{workKindLabels[collection]} · {result.counts[collection]} 条</h3><ol className="divide-y">{entries.filter(entry => entry.kind === collection).map(entry => { const due = searchEntryDate(entry); return <li className="flex flex-wrap items-center gap-2 p-2 text-sm" key={searchEntryKey(entry)}><span className="min-w-0 flex-1 break-words">{searchEntryTitle(entry)}</span><span className="text-xs text-muted-foreground">{entry.item.project.code}{due ? ` · ${workDate(due)}` : ""}</span><Button size="sm" variant="outline" onClick={() => { const key = searchEntryKey(entry); if (!opened.some(item => searchEntryKey(item) === key)) setOpened(current => [...current, entry]); requestAnimationFrame(() => { const card = document.getElementById(key); card?.scrollIntoView({ block: "start", behavior: "smooth" }); card?.focus({ preventScroll: true }); }); }}>在本页办理</Button></li>; })}</ol>{result.pages?.[collection]?.next_offset != null && <Button className="m-2" size="sm" variant="outline" disabled={busy} onClick={() => void more(collection)}>继续加载本类结果</Button>}</section>)}
      </section>}
      {opened.map(entry => <section className="scroll-mt-6 space-y-3 rounded-md border p-3" id={searchEntryKey(entry)} key={searchEntryKey(entry)} tabIndex={-1} aria-label={`${searchEntryTitle(entry)}办理表单`}><header className="flex flex-wrap items-center gap-2"><h3 className="min-w-0 flex-1 text-sm font-semibold">{entry.item.project.code} · {searchEntryTitle(entry)}</h3><Button size="sm" variant="ghost" onClick={() => setOpened(current => current.filter(item => searchEntryKey(item) !== searchEntryKey(entry)))}>关闭此表单</Button></header><p className="text-xs text-muted-foreground">按表单重新读取的权限、内容和版本办理；筛选结果不代表已批准或已完成。关闭此表单会丢弃其中未提交输入。</p><WorkSearchCard entry={entry} handoffs={handoffs} onChanged={recorded} onNotice={setNotice}/></section>)}
    </div>
  </details>;
}
