"use client";
import { ProfessionalTargetContext } from "@/components/projects/professional-target";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { useTheme } from "next-themes";
import { ArrowRight, Books, CalendarBlank, CaretRight, ChartBar, ClipboardText, Clock, FileText, Flask, FolderSimple, Gear, GitBranch, MagnifyingGlass, Moon, Package, SlidersHorizontal, Sparkle, SquaresFour, Sun, Target, Users, X, type Icon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { WorkspaceOverview } from "@/components/workspace-overview";
import { defaultWorkspaceLocation, resolveWorkspaceLocation, workspaceAreas, workspaceEntry, workspaceHref, workspaceSections, workspaceTasks, type WorkspaceArea } from "@/lib/workspace-navigation";
import type { WorkspaceTransport } from "@/lib/workspace-api";

export type ExperienceProduct = { id: string; name: string; purpose: string; revision: number };
export type ExperienceData = {
  product: ExperienceProduct;
  sources: { id: string; title: string; status: string }[];
  claims: { id: string; statement: string; availability: string; status: string; source_status: string }[];
  works: { id: string; goal: string; status: string; error_code: string | null }[];
  receipts: { id: string; operation: string; created_at: string; requester_id: string }[];
};
type Props = {
  categoryId: string;
  projectId?: string;
  embeddedPanel?: string;
  auth: "loading" | "signed_out" | "ready"; session: { name: string; principal_id: string } | null;
  products: ExperienceProduct[]; productId: string; data: ExperienceData | null;
  locked: boolean; onProductChange: (id: string) => void; onCreateProduct: () => void;
  api: WorkspaceTransport; children: ReactNode;
};
const PanelContext = createContext("overview");
const areaIcons: Record<WorkspaceArea, Icon> = { products: SquaresFour, projects: FolderSimple, knowledge: Books, settings: Gear };
const entryIcons: Record<string, Icon> = {
  overview: SquaresFour, activity: Clock, research: MagnifyingGlass,
  definition: ClipboardText, variants: GitBranch,
  plan: CalendarBlank, builds: Package, verification: Flask, issues: Target, reviews: Users,
  files: FileText, sources: Books, preferences: SlidersHorizontal, models: Sparkle, originals: FileText,
};

/** Visit on demand, then retain the mounted editor and its unsaved input while switching views. */
export function WorkspacePanel({ name, children }: { name: string; children: ReactNode }) {
  const active = useContext(PanelContext) === name;
  const target = useContext(ProfessionalTargetContext);
  const [visited, setVisited] = useState(active);
  if (active && !visited) setVisited(true);
  if (!active && !visited) return null;
  return <div hidden={!active} className="workspace-panel" data-workspace-panel={name}><ProfessionalTargetContext.Provider value={active ? target : null}>{children}</ProfessionalTargetContext.Provider></div>;
}

type PlannedDescription = { summary: string; items: string[]; next: [WorkspaceArea, string, string?]; action: string };
const plannedDescriptions: Record<string, PlannedDescription> = {
  competitors: { summary: "把竞品放在相同工况与参数口径下比较。当前可先登记资料和来源事实。", items: ["可比参数与工况", "来源、未知与冲突", "对比结论进入定义候选"], next: ["products", "research", "sources"], action: "整理竞品资料" },
  issues: { summary: "将确定失败接入问题分诊、CAPA 与变更。公共工作区正在接入；不确定结果仍需调查。", items: ["失败与原始证据", "分诊、遏制与纠正", "变更、复验及分别关闭"], next: ["projects", "verification", "results"], action: "查看原结果与处置" },
  reviews: { summary: "集中核对交付缺项、专业结论与具名决定。正式评审与交付工作区尚未接入。", items: ["版本与交付缺项", "分别具名评审", "交接与接收记录"], next: ["projects", "verification", "handoff"], action: "查看已实现的样件交接" },
};

function ThemeOptions() {
  const { theme, setTheme } = useTheme();
  return <div className="workspace-theme-options">{([{ value: "light", label: "亮色", Icon: Sun }, { value: "dark", label: "暗色", Icon: Moon }, { value: "system", label: "跟随系统", Icon: SlidersHorizontal }] as const).map(({ value, label, Icon }) => <Button key={value} variant="outline" aria-pressed={theme === value} onClick={() => setTheme(value)}><Icon/>{label}</Button>)}</div>;
}

/** 品类工作台（内嵌于全局外壳）：区段页签 + 面板内容，不再自带侧栏与顶栏。 */
export function WorkspaceExperience({ categoryId, projectId = "", embeddedPanel, auth, session, products, productId, data, locked, onProductChange, onCreateProduct, api, children }: Props) {
  const [location, setLocation] = useState(defaultWorkspaceLocation);
  const [query, setQuery] = useState("");
  const searchDialog = useRef<HTMLDialogElement>(null);
  const searchTrigger = useRef<HTMLElement | null>(null);
  const content = useRef<HTMLDivElement>(null);
  const product = products.find(item => item.id === productId);
  const currentData = data?.product.id === productId ? data : null;
  const section = workspaceSections[location.area].find(item => item.id === location.section) ?? workspaceSections[location.area][0];
  const tasks = workspaceTasks[`${location.area}/${location.section}`];
  const entry = workspaceEntry(location);

  useEffect(() => {
    if (embeddedPanel !== undefined) return;
    const read = () => {
      const next = resolveWorkspaceLocation(window.location.search);
      setLocation(next);
      if (next.productId && products.some(item => item.id === next.productId) && !locked) onProductChange(next.productId);
    };
    read();
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, [products, locked, onProductChange, embeddedPanel]);

  useEffect(() => {
    if (embeddedPanel !== undefined) return;
    const frame = requestAnimationFrame(() => {
      for (const selector of [".workspace-tabs", ".workspace-task-nav"]) {
        document.querySelector(`${selector} [aria-current="page"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [auth, location.area, location.section, location.task, embeddedPanel]);

  useEffect(() => {
    if (embeddedPanel !== undefined || !productId || auth !== "ready") return;
    const next = { ...resolveWorkspaceLocation(window.location.search), productId };
    window.history.replaceState(null, "", workspaceHref(next, window.location.search));
  }, [productId, auth, embeddedPanel]);

  const openSearch = useCallback((trigger: HTMLElement | null) => {
    searchTrigger.current = trigger; setQuery(""); searchDialog.current?.showModal();
  }, []);
  useEffect(() => {
    if (embeddedPanel !== undefined || auth !== "ready") return;
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.shiftKey && !event.altKey && !event.isComposing && event.key.toLowerCase() === "k") {
        // A business confirmation owns focus until the user resolves it.
        if (document.querySelector("dialog[open]")) return;
        event.preventDefault(); openSearch(document.activeElement instanceof HTMLElement ? document.activeElement : null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [auth, openSearch, embeddedPanel]);

  function closeSearch() { searchDialog.current?.close(); searchTrigger.current?.focus(); }
  function navigate(area: WorkspaceArea, view = workspaceSections[area][0].id, task = "", selectedProduct = productId) {
    const next = resolveWorkspaceLocation(workspaceHref({ area, section: view, task, productId: selectedProduct }));
    const params = new URLSearchParams(workspaceHref(next, window.location.search));
    // 全局知识入口只是知识区的快捷方式；切到非知识区段时回到品类工作区上下文。
    if (next.area !== "knowledge") params.set("area", "category");
    if (selectedProduct !== productId) params.delete("project");
    window.history.pushState(null, "", `?${params.toString()}`);
    setLocation(next);
    if (selectedProduct !== productId && !locked) onProductChange(selectedProduct);
    closeSearch();
    window.dispatchEvent(new PopStateEvent("popstate"));
    requestAnimationFrame(() => { content.current?.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); });
  }
  function follow(event: MouseEvent<HTMLAnchorElement>, area: WorkspaceArea, view?: string, task?: string) {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigate(area, view, task);
  }
  function href(area: WorkspaceArea, view = workspaceSections[area][0].id, task = "") {
    return workspaceHref(resolveWorkspaceLocation(workspaceHref({ area, section: view, task, productId })), new URLSearchParams({ area: "category", category: categoryId, ...(projectId ? { project: projectId } : {}) }).toString());
  }
  const searchEntries = workspaceAreas.flatMap(area => workspaceSections[area.id].flatMap(item => [{ area: area.id, section: item.id, task: "", label: `${area.label} / ${item.label}`, planned: item.planned }, ...(workspaceTasks[`${area.id}/${item.id}`] ?? []).map(task => ({ area: area.id, section: item.id, task: task.id, label: `${area.label} / ${item.label} / ${task.label}`, planned: task.planned }))]));
  const matchedEntries = searchEntries.filter(item => item.label.toLowerCase().includes(query.trim().toLowerCase()));
  const matchedProducts = products.filter(item => query.trim() && item.name.toLowerCase().includes(query.trim().toLowerCase()));
  const planned = plannedDescriptions[entry.id];

  if (embeddedPanel !== undefined) return <PanelContext value={embeddedPanel}>{children}</PanelContext>;

  if (auth !== "ready") return <main className="mx-auto max-w-5xl px-4 py-8 sm:px-8">{children}</main>;

  return <PanelContext value={entry.panel ?? ""}>
    <nav className="workspace-tabs" aria-label="品类工作台区">
      {workspaceAreas.map(item => { const Icon = areaIcons[item.id]; return <a key={item.id} href={href(item.id)} aria-current={location.area === item.id ? "page" : undefined} onClick={event => follow(event, item.id)}><Icon size={16} aria-hidden="true"/><span>{item.label}</span></a>; })}
      <span className="workspace-tabs-spacer"/>
      <button type="button" className="workspace-tabs-search" aria-label="快速查找入口或型号" title="当前品类快速查找 · ⌘ / Ctrl Shift K" onClick={event => openSearch(event.currentTarget)}><MagnifyingGlass size={15} aria-hidden="true"/></button>
      <select aria-label="当前型号" value={productId} disabled={locked} onChange={event => navigate(location.area, location.section, location.task, event.target.value)}>{products.length === 0 && <option value="">尚无型号</option>}{products.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select>
    </nav>
    <nav className="workspace-sections" aria-label={`${workspaceAreas.find(item => item.id === location.area)?.label}视图`}>
      {workspaceSections[location.area].map(item => { const Icon = entryIcons[item.id] ?? SquaresFour; return <a key={item.id} href={href(location.area, item.id)} aria-current={location.section === item.id ? "page" : undefined} onClick={event => follow(event, location.area, item.id)}><Icon size={15} aria-hidden="true"/><span>{item.label}</span>{item.planned && <span className="workspace-planned-dot" aria-label="尚未接入"/>}</a>; })}
    </nav>
    <div ref={content} className="workspace-bench" tabIndex={-1}>
      <div className="workspace-page-heading"><div className="min-w-0"><h1>{location.area === "products" && location.section === "overview" ? product?.name ?? "型号" : section.label}</h1><p>{location.area === "products" && location.section === "overview" ? product?.purpose : location.area === "settings" ? "个人外观与低频运行管理。" : `当前范围：${product?.name ?? "请选择型号"}`}</p></div>{location.area === "products" && <Button variant="outline" disabled={locked} onClick={onCreateProduct}><SquaresFour/>新建型号</Button>}</div>
      {tasks && <nav className="workspace-task-nav" aria-label="当前办理步骤">{tasks.map(item => <a key={item.id} href={href(location.area, location.section, item.id)} aria-current={location.task === item.id ? "page" : undefined} onClick={event => follow(event, location.area, location.section, item.id)}>{item.label}{item.planned && <span className="workspace-planned-dot" aria-label="尚未接入"/>}</a>)}</nav>}
      {entry.planned && planned && <section className="workspace-future" aria-label={`${entry.label}接入状态`}><div className="workspace-future-heading">{(() => { const Icon = entryIcons[entry.id] ?? (entry.id === "competitors" ? ChartBar : Users); return <Icon size={24} aria-hidden="true"/>; })()}<h2>{entry.label}</h2><span className="workspace-state">{entry.id === "issues" ? "正在接入" : "尚未接入"}</span></div><p>{planned.summary}</p><ul>{planned.items.map(item => <li key={item}><CaretRight size={14} aria-hidden="true"/>{item}</li>)}</ul><Button variant="outline" onClick={() => navigate(...planned.next)}>{planned.action}<ArrowRight/></Button></section>}
      {location.area === "knowledge" && <p className="workspace-scope-note"><Books size={16} aria-hidden="true"/>当前显示此型号中已授权的来源与原件。跨型号知识检索尚未接入。</p>}
      {location.area === "settings" && location.section === "preferences" && <section className="workspace-preferences"><h2>界面外观</h2><div className="workspace-preference-row"><div><p>主题</p><p className="subtle">选择适合当前工作环境的显示方式</p></div><ThemeOptions/></div></section>}
      {children}
      {location.section === "overview" && ["products", "projects"].includes(location.area) && currentData && <WorkspaceOverview key={`${session?.principal_id}:${productId}:${location.area}`} area={location.area as "products" | "projects"} data={currentData} api={api} navigate={navigate}/>}
      {["products", "projects", "knowledge"].includes(location.area) && (!productId || !currentData) && <div className="workspace-empty" role="status"><Package size={24} aria-hidden="true"/><p>{productId ? "正在读取当前型号…" : "从一个型号开始组织资料与研发工作。"}</p>{!productId && <Button variant="outline" disabled={locked} onClick={onCreateProduct}>新建型号</Button>}</div>}
    </div>
    <dialog ref={searchDialog} className="workspace-command-dialog" aria-label="快速查找入口或型号" onCancel={event => { event.preventDefault(); closeSearch(); }}><form onSubmit={event => { event.preventDefault(); const first = matchedEntries[0]; if (first) navigate(first.area, first.section, first.task); else if (matchedProducts[0] && !locked) navigate("products", "overview", "", matchedProducts[0].id); }}><div className="workspace-command-input"><MagnifyingGlass size={20} aria-hidden="true"/><input autoFocus aria-label="查找入口或型号" placeholder="查找入口或型号…" value={query} onChange={event => setQuery(event.target.value)}/><Button variant="ghost" size="icon" type="button" aria-label="关闭快速查找" onClick={closeSearch}><X/></Button></div></form><div className="workspace-command-results"><p className="workspace-nav-group">工作区入口</p>{matchedEntries.map(item => { const Icon = areaIcons[item.area]; return <button key={`${item.area}/${item.section}/${item.task}`} type="button" onClick={() => navigate(item.area, item.section, item.task)}><Icon size={17} aria-hidden="true"/><span>{item.label}</span>{item.planned && <span className="subtle ml-auto">尚未接入</span>}</button>; })}{matchedProducts.length > 0 && <p className="workspace-nav-group">型号</p>}{matchedProducts.map(item => <button key={item.id} type="button" disabled={locked} onClick={() => navigate("products", "overview", "", item.id)}><Package size={17} aria-hidden="true"/>{item.name}</button>)}{matchedEntries.length === 0 && matchedProducts.length === 0 && <p className="workspace-command-empty">没有匹配的入口或型号。可以换一个名称查找。</p>}</div><p className="workspace-command-footer">仅查找已授权的型号与工作区入口<span>Esc 关闭</span></p></dialog>
  </PanelContext>;
}
