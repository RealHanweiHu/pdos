"use client";

import { createContext, useCallback, useContext, useEffect, useRef, useState, type MouseEvent, type ReactNode } from "react";
import { useTheme } from "next-themes";
import { ArrowRight, Books, CalendarBlank, CaretRight, ChartBar, CirclesFour, ClipboardText, Clock, FileText, Flask, FolderSimple, Gear, GitBranch, Tray, Lightbulb, List, MagnifyingGlass, Moon, Package, SidebarSimple, SlidersHorizontal, Sparkle, SquaresFour, Sun, Target, Users, X, type Icon } from "@phosphor-icons/react";
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
  categoryBanner?: ReactNode;
  auth: "loading" | "signed_out" | "ready"; session: { name: string; principal_id: string } | null;
  products: ExperienceProduct[]; productId: string; data: ExperienceData | null;
  locked: boolean; onProductChange: (id: string) => void; onCreateProduct: () => void; onOpenPai: () => void;
  api: WorkspaceTransport; children: ReactNode;
};
const PanelContext = createContext("work");
const areaIcons: Record<WorkspaceArea, Icon> = { work: Tray, products: SquaresFour, projects: FolderSimple, resources: Users, knowledge: Books, settings: Gear };
const entryIcons: Record<string, Icon> = {
  overview: SquaresFour, activity: Clock, research: MagnifyingGlass, opportunities: Lightbulb,
  definition: ClipboardText, variants: GitBranch, roadmap: ChartBar, feedback: Tray,
  plan: CalendarBlank, builds: Package, verification: Flask, issues: Target, reviews: Users,
  files: FileText, sources: Books, preferences: SlidersHorizontal, models: Sparkle, originals: FileText,
};

/** Visit on demand, then retain the mounted editor and its unsaved input while switching views. */
export function WorkspacePanel({ name, children }: { name: string; children: ReactNode }) {
  const active = useContext(PanelContext) === name;
  const [visited, setVisited] = useState(active);
  if (active && !visited) setVisited(true);
  if (!active && !visited) return null;
  return <div hidden={!active} className="workspace-panel" data-workspace-panel={name}>{children}</div>;
}

type PlannedDescription = { summary: string; items: string[]; next: [WorkspaceArea, string, string?]; action: string };
const plannedDescriptions: Record<string, PlannedDescription> = {
  competitors: { summary: "把竞品放在相同工况与参数口径下比较。当前可先登记资料和来源事实。", items: ["可比参数与工况", "来源、未知与冲突", "对比结论进入定义候选"], next: ["products", "research", "sources"], action: "整理竞品资料" },
  opportunities: { summary: "从研究证据形成机会，再用实验验证假设。机会与实验工作区尚未接入。", items: ["机会与证据", "假设、实验及判据", "结果回到型号定义"], next: ["products", "research", "sources"], action: "查看研究资料" },
  roadmap: { summary: "比较型号覆盖、派生关系与后续方向。矩阵和路线图尚未接入。", items: ["型号与规格覆盖", "派生关系与重叠", "路线与优先级"], next: ["products", "variants"], action: "查看已保存派生" },
  feedback: { summary: "把客户与验证反馈接回型号迭代。统一反馈工作区尚未接入。", items: ["反馈的实际来源", "适用型号与版本", "验证或定义修订"], next: ["projects", "verification", "results"], action: "查看测试结果" },
  issues: { summary: "将确定失败接入问题分诊、CAPA 与变更。公共工作区正在接入；不确定结果仍需调查。", items: ["失败与原始证据", "分诊、遏制与纠正", "变更、复验及分别关闭"], next: ["projects", "verification", "results"], action: "查看原结果与处置" },
  reviews: { summary: "集中核对交付缺项、专业结论与具名决定。正式评审与交付工作区尚未接入。", items: ["版本与交付缺项", "分别具名评审", "交接与接收记录"], next: ["projects", "verification", "handoff"], action: "查看已实现的样件交接" },
  resources: { summary: "跨项目查看投入、优先级与资源冲突。组合工作区尚未接入，当前资源条件在试制和开测时核对。", items: ["项目组合与投入", "共享资源及占用", "冲突与待决定事项"], next: ["projects", "builds", "start"], action: "查看试制资源条件" },
};

export function WorkspaceExperience({ categoryId, categoryBanner, auth, session, products, productId, data, locked, onProductChange, onCreateProduct, onOpenPai, api, children }: Props) {
  const [location, setLocation] = useState(defaultWorkspaceLocation);
  const [collapsed, setCollapsed] = useState(false);
  const [query, setQuery] = useState("");
  const searchDialog = useRef<HTMLDialogElement>(null);
  const mobileDialog = useRef<HTMLDialogElement>(null);
  const searchTrigger = useRef<HTMLElement | null>(null);
  const mobileTrigger = useRef<HTMLButtonElement>(null);
  const content = useRef<HTMLElement>(null);
  const { theme, resolvedTheme, setTheme } = useTheme();
  const product = products.find(item => item.id === productId);
  const currentData = data?.product.id === productId ? data : null;
  const section = workspaceSections[location.area].find(item => item.id === location.section) ?? workspaceSections[location.area][0];
  const tasks = workspaceTasks[`${location.area}/${location.section}`];
  const entry = workspaceEntry(location);

  useEffect(() => {
    const read = () => {
      const next = resolveWorkspaceLocation(window.location.search);
      setLocation(next);
      if (next.productId && products.some(item => item.id === next.productId) && !locked) onProductChange(next.productId);
    };
    read();
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, [products, locked, onProductChange]);

  useEffect(() => {
    const frame = requestAnimationFrame(() => {
      for (const selector of [".workspace-tabs", ".workspace-task-nav"]) {
        document.querySelector(`${selector} [aria-current="page"]`)?.scrollIntoView({ block: "nearest", inline: "nearest" });
      }
    });
    return () => cancelAnimationFrame(frame);
  }, [auth, location.area, location.section, location.task]);

  useEffect(() => {
    if (!productId || auth !== "ready") return;
    const next = { ...resolveWorkspaceLocation(window.location.search), productId };
    window.history.replaceState(null, "", workspaceHref(next, window.location.search));
  }, [productId, auth]);

  useEffect(() => {
    if (!session) return;
    let active = true;
    void Promise.resolve().then(() => { if (active) { try { setCollapsed(localStorage.getItem(`pdos-next:sidebar:${session.principal_id}`) === "collapsed"); } catch { /* Appearance is optional. */ } } });
    return () => { active = false; };
  }, [session]);

  const openSearch = useCallback((trigger: HTMLElement | null) => {
    searchTrigger.current = trigger; setQuery(""); searchDialog.current?.showModal();
  }, []);
  useEffect(() => {
    if (auth !== "ready") return;
    const handler = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === "k") {
        // A business confirmation owns focus until the user resolves it.
        if (document.querySelector("dialog[open]")) return;
        event.preventDefault(); openSearch(document.activeElement instanceof HTMLElement ? document.activeElement : null);
      }
    };
    window.addEventListener("keydown", handler);
    return () => window.removeEventListener("keydown", handler);
  }, [auth, openSearch]);

  function closeSearch() { searchDialog.current?.close(); searchTrigger.current?.focus(); }
  function closeMobile() { mobileDialog.current?.close(); mobileTrigger.current?.focus(); }
  function navigate(area: WorkspaceArea, view = workspaceSections[area][0].id, task = "", selectedProduct = productId) {
    const next = resolveWorkspaceLocation(workspaceHref({ area, section: view, task, productId: selectedProduct }));
    window.history.pushState(null, "", workspaceHref(next, window.location.search));
    setLocation(next);
    if (selectedProduct !== productId && !locked) onProductChange(selectedProduct);
    closeMobile(); closeSearch();
    requestAnimationFrame(() => { content.current?.focus({ preventScroll: true }); window.scrollTo({ top: 0 }); });
  }
  function follow(event: MouseEvent<HTMLAnchorElement>, area: WorkspaceArea, view?: string, task?: string) {
    if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return;
    event.preventDefault(); navigate(area, view, task);
  }
  function href(area: WorkspaceArea, view = workspaceSections[area][0].id, task = "") {
    return workspaceHref(resolveWorkspaceLocation(workspaceHref({ area, section: view, task, productId })), new URLSearchParams({ category: categoryId }).toString());
  }
  function toggleSidebar() {
    const next = !collapsed; setCollapsed(next);
    try { if (session) localStorage.setItem(`pdos-next:sidebar:${session.principal_id}`, next ? "collapsed" : "expanded"); } catch { /* Navigation remains available. */ }
  }
  function navigation(mobile = false) {
    return <>
      <div className="workspace-brand"><CirclesFour size={22} weight="fill" className="text-primary" aria-hidden="true"/><span className="workspace-nav-label font-semibold">PDOS</span><Button size="icon" variant="ghost" className="workspace-brand-toggle" aria-label={mobile ? "关闭导航" : collapsed ? "展开侧栏" : "收起侧栏"} onClick={mobile ? closeMobile : toggleSidebar}>{mobile ? <X/> : <SidebarSimple/>}</Button></div>
      <button type="button" className="workspace-search" aria-label="快速查找入口或型号" title="快速查找 · ⌘ / Ctrl K" onClick={event => openSearch(event.currentTarget)}><MagnifyingGlass size={17} aria-hidden="true"/><span className="workspace-nav-label">快速查找</span><kbd className="workspace-nav-label ml-auto">⌘ K</kbd></button>
      <nav aria-label={mobile ? "移动工作区导航" : "工作区导航"} className="workspace-navigation">
        {workspaceAreas.filter(item => item.id !== "settings").map((item, index) => {
          const Icon = areaIcons[item.id];
          return <div key={item.id}>{index === 1 && <p className="workspace-nav-group workspace-nav-label">工作区</p>}<a href={href(item.id)} className="workspace-nav-item" aria-current={location.area === item.id ? "page" : undefined} aria-label={item.label} title={item.label} onClick={event => follow(event, item.id)}><Icon size={18} aria-hidden="true"/><span className="workspace-nav-label">{item.label}</span></a></div>;
        })}
        <div className="workspace-nav-scope workspace-nav-label"><p className="workspace-nav-group">当前型号</p><p className="truncate font-medium" title={product?.name}>{product?.name ?? "尚无型号"}</p><p className="subtle mt-1">专业工作按此型号范围读取</p></div>
      </nav>
      <div className="workspace-sidebar-bottom"><a href="/plan" className="workspace-nav-item" aria-label="计划执行进度" title="计划执行进度（唯一清单只读投影）"><ChartBar size={18} aria-hidden="true"/><span className="workspace-nav-label">计划进度</span></a><a href={href("work")} className="workspace-nav-item" aria-label="小Pai 工作" title="小Pai 工作" onClick={event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate("work"); onOpenPai(); }}><Sparkle size={18} aria-hidden="true"/><span className="workspace-nav-label">小Pai</span></a><a href={href("settings")} className="workspace-nav-item" aria-label="设置" title="设置" aria-current={location.area === "settings" ? "page" : undefined} onClick={event => follow(event, "settings")}><Gear size={18} aria-hidden="true"/><span className="workspace-nav-label">设置</span></a><div className="workspace-profile"><span className="workspace-avatar" aria-hidden="true">{session?.name.slice(0, 1) ?? "P"}</span><div className="workspace-nav-label min-w-0"><p className="truncate text-xs font-medium">{session?.name}</p><p className="workspace-environment">本地合成环境</p></div></div></div>
    </>;
  }
  const searchEntries = workspaceAreas.flatMap(area => workspaceSections[area.id].flatMap(item => [{ area: area.id, section: item.id, task: "", label: `${area.label} / ${item.label}`, planned: item.planned }, ...(workspaceTasks[`${area.id}/${item.id}`] ?? []).map(task => ({ area: area.id, section: item.id, task: task.id, label: `${area.label} / ${item.label} / ${task.label}`, planned: task.planned }))]));
  const matchedEntries = searchEntries.filter(item => item.label.toLowerCase().includes(query.trim().toLowerCase()));
  const matchedProducts = products.filter(item => query.trim() && item.name.toLowerCase().includes(query.trim().toLowerCase()));
  const planned = plannedDescriptions[location.area === "resources" ? "resources" : entry.id];

  if (auth !== "ready") return <><header className="workspace-public-header"><CirclesFour size={22} weight="fill" className="text-primary" aria-hidden="true"/><span className="font-semibold">PDOS</span><Button className="ml-auto" size="icon" variant="ghost" aria-label="切换明暗主题" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>{resolvedTheme === "dark" ? <Sun/> : <Moon/>}</Button></header><main className="mx-auto max-w-5xl px-4 py-8 sm:px-8">{children}</main></>;

  return <PanelContext value={entry.panel ?? ""}>
    <div className={`workspace-frame${collapsed ? " workspace-collapsed" : ""}`}>
      <a href="#workspace-content" className="workspace-skip">跳到工作内容</a>
      <aside className="workspace-sidebar">{navigation()}</aside>
      <dialog ref={mobileDialog} className="workspace-mobile-navigation" aria-label="工作区导航" onCancel={event => { event.preventDefault(); closeMobile(); }}>{navigation(true)}</dialog>
      <div className="workspace-body">
        {categoryBanner}
        <header className="workspace-header"><Button ref={mobileTrigger} size="icon" variant="ghost" className="workspace-mobile-trigger" aria-label="打开导航" onClick={() => mobileDialog.current?.showModal()}><List/></Button><div className="workspace-breadcrumb"><span>{workspaceAreas.find(item => item.id === location.area)?.label}</span><CaretRight size={12} aria-hidden="true"/><span className="font-medium">{section.label}</span></div><div className="workspace-header-actions"><select aria-label="当前型号" value={productId} disabled={locked} onChange={event => navigate(location.area, location.section, location.task, event.target.value)}>{products.length === 0 && <option value="">尚无型号</option>}{products.map(item => <option key={item.id} value={item.id}>{item.name}</option>)}</select><Button size="icon" variant="ghost" aria-label="切换明暗主题" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>{resolvedTheme === "dark" ? <Sun/> : <Moon/>}</Button></div></header>
        <nav className="workspace-tabs" aria-label={`${workspaceAreas.find(item => item.id === location.area)?.label}视图`}>{workspaceSections[location.area].map(item => { const Icon = entryIcons[item.id] ?? SquaresFour; return <a key={item.id} href={href(location.area, item.id)} aria-current={location.section === item.id ? "page" : undefined} onClick={event => follow(event, location.area, item.id)}><Icon size={16} aria-hidden="true"/><span>{item.label}</span>{item.planned && <span className="workspace-planned-dot" aria-label="尚未接入" title="尚未接入"/>}</a>; })}</nav>
        <main ref={content} id="workspace-content" tabIndex={-1} className="workspace-content">
          <div className="workspace-page-heading"><div className="min-w-0"><h1>{location.area === "products" && location.section === "overview" ? product?.name ?? "型号" : section.label}</h1><p>{location.area === "products" && location.section === "overview" ? product?.purpose : location.area === "work" ? "当前品类中由你发起的工作，结果与异常在这里接续。" : location.area === "settings" ? "个人外观与低频运行管理。" : `当前范围：${product?.name ?? "请选择型号"}`}</p></div>{location.area === "products" && <Button variant="outline" disabled={locked} onClick={onCreateProduct}><SquaresFour/>新建型号</Button>}</div>
          {tasks && <nav className="workspace-task-nav" aria-label="当前办理步骤">{tasks.map(item => <a key={item.id} href={href(location.area, location.section, item.id)} aria-current={location.task === item.id ? "page" : undefined} onClick={event => follow(event, location.area, location.section, item.id)}>{item.label}{item.planned && <span className="workspace-planned-dot" aria-label="尚未接入"/>}</a>)}</nav>}
          {entry.planned && planned && <section className="workspace-future" aria-label={`${entry.label}接入状态`}><div className="workspace-future-heading">{(() => { const Icon = entryIcons[entry.id] ?? (entry.id === "competitors" ? ChartBar : Users); return <Icon size={24} aria-hidden="true"/>; })()}<h2>{entry.label}</h2><span className="workspace-state">{entry.id === "issues" ? "正在接入" : "尚未接入"}</span></div><p>{planned.summary}</p><ul>{planned.items.map(item => <li key={item}><CaretRight size={14} aria-hidden="true"/>{item}</li>)}</ul><Button variant="outline" onClick={() => navigate(...planned.next)}>{planned.action}<ArrowRight/></Button></section>}
          {location.area === "work" && location.section === "overview" && currentData && <div className="workspace-work-context"><span><Tray size={16} aria-hidden="true"/>当前品类的运行与待处理事项见下方小Pai。</span><button type="button" onClick={() => navigate("products", "overview")}>查看型号总览<ArrowRight size={14} aria-hidden="true"/></button></div>}
          {location.area === "knowledge" && <p className="workspace-scope-note"><Books size={16} aria-hidden="true"/>当前显示此型号中已授权的来源与原件。跨型号知识检索尚未接入。</p>}
          {location.area === "settings" && location.section === "preferences" && <section className="workspace-preferences"><h2>界面外观</h2><div className="workspace-preference-row"><div><p>主题</p><p className="subtle">选择适合当前工作环境的显示方式</p></div><div className="workspace-theme-options">{([{ value: "light", label: "亮色", Icon: Sun }, { value: "dark", label: "暗色", Icon: Moon }, { value: "system", label: "跟随系统", Icon: SlidersHorizontal }] as const).map(({ value, label, Icon }) => <Button key={value} variant="outline" aria-pressed={theme === value} onClick={() => setTheme(value)}><Icon/>{label}</Button>)}</div></div><div className="workspace-preference-row"><div><p>侧栏</p><p className="subtle">按当前用户记住展开或收起状态</p></div><Button variant="outline" onClick={toggleSidebar}><SidebarSimple/>{collapsed ? "展开侧栏" : "收起侧栏"}</Button></div></section>}
          {children}
          {location.section === "overview" && ["products", "projects"].includes(location.area) && currentData && <WorkspaceOverview key={`${session?.principal_id}:${productId}:${location.area}`} area={location.area as "products" | "projects"} data={currentData} api={api} navigate={navigate}/>}
          {location.area !== "work" && (!productId || !currentData) && <div className="workspace-empty" role="status"><Package size={24} aria-hidden="true"/><p>{productId ? "正在读取当前型号…" : "从一个型号开始组织资料与研发工作。"}</p>{!productId && <Button variant="outline" disabled={locked} onClick={onCreateProduct}>新建型号</Button>}</div>}
        </main>
      </div>
      <dialog ref={searchDialog} className="workspace-command-dialog" aria-label="快速查找入口或型号" onCancel={event => { event.preventDefault(); closeSearch(); }}><form onSubmit={event => { event.preventDefault(); const first = matchedEntries[0]; if (first) navigate(first.area, first.section, first.task); else if (matchedProducts[0] && !locked) navigate("products", "overview", "", matchedProducts[0].id); }}><div className="workspace-command-input"><MagnifyingGlass size={20} aria-hidden="true"/><input autoFocus aria-label="查找入口或型号" placeholder="查找入口或型号…" value={query} onChange={event => setQuery(event.target.value)}/><Button variant="ghost" size="icon" type="button" aria-label="关闭快速查找" onClick={closeSearch}><X/></Button></div></form><div className="workspace-command-results"><p className="workspace-nav-group">工作区入口</p>{matchedEntries.map(item => { const Icon = areaIcons[item.area]; return <button key={`${item.area}/${item.section}/${item.task}`} type="button" onClick={() => navigate(item.area, item.section, item.task)}><Icon size={17} aria-hidden="true"/><span>{item.label}</span>{item.planned && <span className="subtle ml-auto">尚未接入</span>}</button>; })}{matchedProducts.length > 0 && <p className="workspace-nav-group">型号</p>}{matchedProducts.map(item => <button key={item.id} type="button" disabled={locked} onClick={() => navigate("products", "overview", "", item.id)}><Package size={17} aria-hidden="true"/>{item.name}</button>)}{matchedEntries.length === 0 && matchedProducts.length === 0 && <p className="workspace-command-empty">没有匹配的入口或型号。可以换一个名称查找。</p>}</div><p className="workspace-command-footer">仅查找已授权的型号与工作区入口<span>Esc 关闭</span></p></dialog>
    </div>
  </PanelContext>;
}
