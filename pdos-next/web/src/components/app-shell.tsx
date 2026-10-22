"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTheme } from "next-themes";
import { ArrowClockwise, BookOpen, Books, CaretDown, CaretRight, ChartBar, CheckSquare, FileText, Gear, Kanban, Layout, List, ListChecks, MagnifyingGlass, Moon, Plus, SidebarSimple, Sparkle, Sun, Tag, X, type Icon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import { defaultGlobalLocation, globalAreas, globalHref, normalizeGlobalSearch, productManagementCategories, productManagementHref, projectWorkbenchHref, resolveGlobalLocation, type GlobalArea, type GlobalLocation } from "@/lib/global-navigation";
import { ConnectedAutomationRules } from "@/components/automation-rules";
import { MyWork } from "@/components/my-work";
import { ProjectList } from "@/components/projects/project-list";
import { ProjectCockpit } from "@/components/projects/project-cockpit";
import { CategoryArea } from "@/components/category-workspace";
import { KnowledgeLibrary } from "@/components/knowledge/knowledge-library";
import { PaiRail, type PaiContext } from "@/components/pai-rail";
import { ObjectSearch } from "@/components/object-search";
import styles from "./app-shell.module.css";

type Session = { name: string; principal_id: string };
type Category = { id: string; name: string; purpose: string; capabilities?: { product_management?: boolean } };
type NavigationProject = { category: { id: string }; project: { id: string; name: string; status: string } };
type NavigationProjectPage = { items: NavigationProject[]; next_cursor: string | null };

const areaIcons: Record<GlobalArea, Icon> = {
  work: ListChecks, cockpit: Kanban, projects: Kanban, programs: Layout,
  category: Tag, knowledge: BookOpen, settings: Gear,
};

function ThemeOptions() {
  const { theme, setTheme: apply } = useTheme();
  return <div className="workspace-theme-options">{([{ value: "light", label: "亮色", Icon: Sun }, { value: "dark", label: "暗色", Icon: Moon }, { value: "system", label: "跟随系统", Icon: SidebarSimple }] as const).map(({ value, label, Icon }) => <Button key={value} variant="outline" aria-pressed={theme === value} onClick={() => apply(value)}><Icon/>{label}</Button>)}</div>;
}

export function AppShell({ children, documentPage }: { children?: ReactNode; documentPage?: { categoryId: string } } = {}) {
  const documentCategoryId = documentPage?.categoryId ?? "";
  const documentMode = Boolean(documentCategoryId);
  const pageHref = (href: string) => documentMode && href.startsWith("?") ? `/${href}` : href;
  const [auth, setAuth] = useState<"loading" | "signed_out" | "ready">("loading");
  const [session, setSession] = useState<Session | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [categoriesError, setCategoriesError] = useState("");
  const [navigationProjects, setNavigationProjects] = useState<NavigationProject[]>([]);
  const [projectsError, setProjectsError] = useState("");
  const [entryError, setEntryError] = useState("");
  const [location, setLocation] = useState<GlobalLocation>(defaultGlobalLocation);
  const [collapsed, setCollapsed] = useState(false);
  const [paiOpen, setPaiOpen] = useState(false);
  const [paiContext, setPaiContext] = useState<PaiContext | null>(null);
  const [focusRun, setFocusRun] = useState<{ runId: string; categoryId: string } | null>(null);
  const mobileDialog = useRef<HTMLDialogElement>(null);
  const mobileTrigger = useRef<HTMLButtonElement>(null);
  const searchControl = useRef<HTMLDivElement>(null);
  const { resolvedTheme, setTheme } = useTheme();

  const load = useCallback(async () => {
    try {
      const who = await browserApi<Session>("v1/session");
      const [list, projects] = await Promise.allSettled([
        browserApi<Category[]>("v1/categories"),
        browserApi<NavigationProjectPage>("v1/personal/projects?page_size=6"),
      ]);
      setSession(who);
      setCategories(list.status === "fulfilled" ? list.value : []);
      setCategoriesError(list.status === "rejected" ? (list.reason as Error).message : "");
      setNavigationProjects(projects.status === "fulfilled" ? projects.value.items : []);
      setProjectsError(projects.status === "rejected" ? (projects.reason as Error).message : "");
      setAuth("ready");
    } catch (failure) {
      if ((failure as { status?: number }).status === 401) setAuth("signed_out");
      else { setEntryError((failure as Error).message); setAuth("signed_out"); }
    }
  }, []);
  useEffect(() => { let active = true; void Promise.resolve().then(() => { if (active) return load(); }); return () => { active = false; }; }, [load]);

  useEffect(() => {
    if (documentCategoryId) { void Promise.resolve().then(() => setLocation({ area: "category", categoryId: documentCategoryId, projectId: "" })); return; }
    const normalized = normalizeGlobalSearch(window.location.search);
    if (normalized.changed) window.history.replaceState(null, "", normalized.search);
    const read = () => setLocation(resolveGlobalLocation(window.location.search));
    read();
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, [documentCategoryId]);

  useEffect(() => {
    if (!session) return;
    let active = true;
    void Promise.resolve().then(() => {
      if (!active) return;
      try {
        setCollapsed(localStorage.getItem(`pdos-next:sidebar:${session.principal_id}`) === "collapsed");
        setPaiOpen(localStorage.getItem(`pdos-next:pai-rail:${session.principal_id}`) === "open");
      } catch { /* Appearance is optional. */ }
    });
    return () => { active = false; };
  }, [session]);

  useEffect(() => {
    if (auth !== "ready" || location.area !== "category" || new URLSearchParams(window.location.search).get("focus") !== "proposals") return;
    const frame = requestAnimationFrame(() => {
      const section = document.querySelector<HTMLElement>('section[aria-label="立项提案"]');
      if (!section) return;
      section.tabIndex = -1;
      section.scrollIntoView({ block: "start" });
      section.focus({ preventScroll: true });
    });
    return () => cancelAnimationFrame(frame);
  }, [auth, location]);

  function pushAndApply(href: string) {
    if (documentMode) { window.location.assign(pageHref(href)); return; }
    window.history.pushState(null, "", href);
    setLocation(resolveGlobalLocation(href));
    // 内嵌工作台与全局外壳共用 popstate 感知 URL 变化；pushState 自身不触发。
    window.dispatchEvent(new PopStateEvent("popstate"));
    requestAnimationFrame(() => window.scrollTo({ top: 0 }));
  }
  function navigate(area: GlobalArea, extras: { categoryId?: string; projectId?: string } = {}) {
    const categoryId = extras.categoryId ?? location.categoryId;
    const projectId = extras.projectId ?? "";
    let href = globalHref({ area, categoryId, projectId }, window.location.search);
    if (area === "knowledge" && categoryId) {
      const params = new URLSearchParams(href);
      if (!params.get("bench")) { params.set("bench", "knowledge"); params.set("view", "sources"); }
      href = `?${params.toString()}`;
    }
    pushAndApply(href);
    closeMobile();
  }
  function openWorkbench(categoryId: string, productId: string, projectId: string) {
    pushAndApply(projectWorkbenchHref(categoryId, productId, projectId));
  }
  function openProductManagement(view: "categories" | "proposals") {
    const managed = productManagementCategories(categories);
    const categoryId = view === "categories" ? "" : managed.find(item => item.id === location.categoryId)?.id ?? managed[0]?.id ?? "";
    pushAndApply(productManagementHref(categoryId, view));
    closeMobile();
  }
  function selectCategory(id: string) {
    const params = new URLSearchParams(window.location.search);
    if (id) params.set("category", id); else params.delete("category");
    params.delete("bench"); params.delete("view"); params.delete("task"); params.delete("product");
    pushAndApply(`?${params.toString()}`);
  }
  function toggleSidebar() {
    const next = !collapsed; setCollapsed(next);
    try { if (session) localStorage.setItem(`pdos-next:sidebar:${session.principal_id}`, next ? "collapsed" : "expanded"); } catch { /* optional */ }
  }
  function togglePai() {
    const next = !paiOpen; setPaiOpen(next);
    try { if (session) localStorage.setItem(`pdos-next:pai-rail:${session.principal_id}`, next ? "open" : "closed"); } catch { /* optional */ }
  }
  function closeMobile() { const open = mobileDialog.current?.open; mobileDialog.current?.close(); if (open) mobileTrigger.current?.focus(); }
  function openSearch(mobile = false) {
    if (mobile) closeMobile();
    requestAnimationFrame(() => searchControl.current?.querySelector<HTMLButtonElement>("button")?.click());
  }
  function showPai() { if (!paiOpen) togglePai(); closeMobile(); }
  function openRun(runId: string, categoryId: string) {
    setFocusRun({ runId, categoryId });
    if (categoryId !== location.categoryId) selectCategory(categoryId);
    setPaiOpen(true);
  }

  if (auth === "loading") return <main className="mx-auto max-w-5xl px-4 py-16"><p role="status">正在载入你的工作区…</p></main>;
  if (auth === "signed_out") return <>
    <header className="workspace-public-header"><span className={styles.brandMark} aria-hidden="true">P</span><span className="font-semibold">PDOS</span><Button className="ml-auto" size="icon" variant="ghost" aria-label="切换明暗主题" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>{resolvedTheme === "dark" ? <Sun/> : <Moon/>}</Button></header>
    <main className="mx-auto max-w-lg px-4 py-16"><div className="panel">
      <p className="subtle">独立新工程 · 合成预览</p>
      <h1 className="mt-3 text-2xl font-semibold">PDOS 研发工作区</h1>
      <p className="my-5">从我的工作开始，办理项目、查看组合与资源、查找知识。小Pai 对所有岗位开放，产品管理入口按本人品类权限显示。此环境只用于合成资料演练。</p>
      {entryError && <p role="alert" className="mb-4">{entryError}</p>}
      <Button onClick={async () => { setEntryError(""); try { await browserApi("local-session", {}); await load(); } catch (failure) { setEntryError((failure as Error).message); } }}>进入本地合成环境</Button>
    </div></main>
  </>;

  const category = categories.find(item => item.id === location.categoryId);
  const managedCategories = productManagementCategories(categories);
  const managementError = categoriesError || (categories.some(item => typeof item.capabilities?.product_management !== "boolean") ? "品类产品管理权限尚未提供，请刷新重试。" : "");
  const areaEntry = globalAreas.find(item => item.id === location.area) ?? globalAreas[0];
  const search = new URLSearchParams(window.location.search);
  const proposalFocus = documentMode || location.area === "category" && search.get("focus") === "proposals";
  const projectWorkbench = location.area === "category" && (search.get("bench") === "projects" || Boolean(location.projectId));
  const knowledgeWorkbench = location.area === "knowledge" && search.get("bench") === "knowledge" && Boolean(search.get("product"));
  const activeProject = navigationProjects.find(entry => entry.project.id === location.projectId);
  const today = new Date();
  const dateLabel = `${today.toLocaleDateString("sv-SE")} ${today.toLocaleDateString("zh-CN", { weekday: "short" })}`;
  function navigation(mobile = false) {
    return <>
      <div className="workspace-brand"><span className={styles.brandMark} aria-hidden="true">P</span><span className="workspace-nav-label font-bold">PDOS</span><Button size="icon" variant="ghost" className="workspace-brand-toggle" aria-label={mobile ? "关闭导航" : collapsed ? "展开侧栏" : "收起侧栏"} onClick={mobile ? closeMobile : toggleSidebar}>{mobile ? <X/> : <SidebarSimple/>}</Button></div>
      <div className={styles.quickActions}>
        <details className={styles.quickCreate} onKeyDown={event => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); } }} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false; }}>
          <summary className={styles.createTrigger} aria-label="新建：选择办理入口"><Plus size={16} aria-hidden="true"/><span className="workspace-nav-label">新建</span><CaretDown size={13} className={`workspace-nav-label ${styles.createCaret}`} aria-hidden="true"/></summary>
          <div className={styles.createMenu} aria-label="创建与办理入口"><p className={styles.menuNote}>选择办理入口</p>
            <button type="button" onClick={event => { event.currentTarget.closest("details")?.removeAttribute("open"); showPai(); }}><Sparkle size={16} aria-hidden="true"/><span>通过小Pai办理<small>描述目标，核对后继续</small></span></button>
            <button type="button" onClick={event => { event.currentTarget.closest("details")?.removeAttribute("open"); navigate("projects"); }}><CheckSquare size={16} aria-hidden="true"/><span>任务、问题与交接<small>先选择项目，再进入办理</small></span></button>
            {managedCategories.length > 0 && <><hr/><button type="button" onClick={event => { event.currentTarget.closest("details")?.removeAttribute("open"); openProductManagement("proposals"); if (!paiOpen) togglePai(); }}><FileText size={16} aria-hidden="true"/><span>立项提案<small>进入品类小Pai起草</small></span><span className={styles.scopeBadge}>PM</span></button></>}
          </div>
        </details>
        <button type="button" className={styles.commandTrigger} aria-label="搜索对象" title="搜索对象（⌘K / Ctrl K）" onClick={() => openSearch(mobile)}><MagnifyingGlass size={15} aria-hidden="true"/><kbd className="workspace-nav-label">⌘K</kbd></button>
      </div>
      <nav aria-label={mobile ? "移动工作区导航" : "工作区导航"} className="workspace-navigation">
        <p className="workspace-nav-group workspace-nav-label">日常</p>
        {globalAreas.filter(item => item.group === "main").map(item => {
          const Icon = areaIcons[item.id];
          return <div key={item.id}>
            <a href={pageHref(globalHref({ area: item.id, categoryId: location.categoryId, projectId: "" }, window.location.search))} className={`workspace-nav-item ${styles.primaryLink}`} aria-current={location.area === item.id ? "page" : item.id === "projects" && (location.area === "cockpit" || projectWorkbench) ? "location" : undefined} aria-label={item.label} title={item.label} onClick={event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate(item.id); }}><Icon size={18} aria-hidden="true"/><span className="workspace-nav-label">{item.label}</span>{item.planned && <span className="workspace-nav-label subtle ml-auto text-[10px]">尚未接入</span>}</a>
            {item.id === "projects" && <div className={`workspace-nav-label ${styles.projects}`} aria-label="最近的在办项目">
              {navigationProjects.filter(entry => entry.project.status === "active").map(entry => <a key={entry.project.id} href={pageHref(globalHref({ area: "cockpit", categoryId: entry.category.id, projectId: entry.project.id }))} className={styles.projectLink} aria-current={location.projectId === entry.project.id ? "page" : undefined} title={`${entry.project.name} · 阶段尚未提供`} onClick={event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate("cockpit", { categoryId: entry.category.id, projectId: entry.project.id }); }}><span className={styles.projectMark} aria-hidden="true"/><span className={styles.projectName}>{entry.project.name}</span><span className={styles.projectStage} aria-label="阶段尚未提供">—</span></a>)}
              {projectsError && <div className={styles.readNotice}><p role="status">项目导航暂不可读</p><button type="button" onClick={() => void load()} className={styles.retry} title={projectsError}>重新读取</button></div>}
            </div>}
          </div>;
        })}
        {managedCategories.length > 0 && <div>
          <p className="workspace-nav-group workspace-nav-label">产品管理</p>
          <a href={pageHref(productManagementHref())} className="workspace-nav-item" title="品类开发" aria-label="品类开发" aria-current={location.area === "category" && !proposalFocus && !projectWorkbench ? "page" : undefined} onClick={event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); openProductManagement("categories"); }}><Tag size={18} aria-hidden="true"/><span className="workspace-nav-label">品类开发</span><span className={`workspace-nav-label ${styles.scopeBadge}`}>立项前</span></a>
          <a href={pageHref(productManagementHref(managedCategories.find(item => item.id === location.categoryId)?.id ?? managedCategories[0].id, "proposals"))} className="workspace-nav-item" title="立项提案" aria-label="立项提案" aria-current={proposalFocus ? "page" : undefined} onClick={event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); openProductManagement("proposals"); }}><FileText size={18} aria-hidden="true"/><span className="workspace-nav-label">立项提案</span></a>
          <p className={`workspace-nav-label ${styles.groupNote}`}>按你在各品类的产品管理权限显示。</p>
        </div>}
        {managementError && <div className={styles.readNotice}><p className="workspace-nav-label" role="status">品类权限读取未完成</p><button type="button" className={`workspace-nav-item w-full ${styles.retry}`} title={managementError} aria-label="重新读取品类权限" onClick={() => void load()}><ArrowClockwise size={16} aria-hidden="true"/><span className="workspace-nav-label">重新读取</span></button></div>}
      </nav>
      <div className="workspace-sidebar-bottom">
        <a href="/plan" className="workspace-nav-item" aria-label="计划执行进度" title="计划执行进度（唯一清单只读投影）"><ChartBar size={18} aria-hidden="true"/><span className="workspace-nav-label">计划进度</span></a>
        <a href={pageHref(globalHref({ area: "settings", categoryId: location.categoryId, projectId: "" }, window.location.search))} className="workspace-nav-item" aria-label="设置" title="设置" aria-current={location.area === "settings" ? "page" : undefined} onClick={event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate("settings"); }}><Gear size={18} aria-hidden="true"/><span className="workspace-nav-label">设置</span></a>
        <button type="button" className="workspace-nav-item w-full" aria-label="切换明暗主题" title="切换明暗主题" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>{resolvedTheme === "dark" ? <Sun size={18} aria-hidden="true"/> : <Moon size={18} aria-hidden="true"/>}<span className="workspace-nav-label">{resolvedTheme === "dark" ? "切换亮色" : "切换暗色"}</span></button>
        <div className="workspace-profile"><span className="workspace-avatar" aria-hidden="true">{session?.name.slice(0, 1) ?? "P"}</span><div className="workspace-nav-label min-w-0"><p className="truncate text-xs font-medium">{session?.name}</p><p className="workspace-environment">本地合成环境</p></div></div>
      </div>
    </>;
  }

  let content: ReactNode;
  if (documentMode) content = children;
  else if (location.area === "work") content = <MyWork api={browserApi} session={session!} onOpenRun={openRun} onOpenProject={(categoryId, projectId) => navigate("cockpit", { categoryId, projectId })} onOpenPai={() => setPaiOpen(true)} />;
  else if (location.area === "projects") content = <ProjectList api={browserApi} principalId={session!.principal_id} onOpenProject={(categoryId, projectId) => navigate("cockpit", { categoryId, projectId })} onOpenWorkbench={openWorkbench} />;
  else if (location.area === "cockpit") content = <ProjectCockpit key={location.projectId} api={browserApi} session={session!} location={location} onOpenProject={(categoryId, projectId) => navigate("cockpit", { categoryId, projectId })} onOpenOverview={() => navigate("projects")} onOpenWorkbench={openWorkbench} onPaiContext={setPaiContext} />;
  else if (location.area === "programs") content = <section className="workspace-future" aria-label="组合与资源接入状态"><div className="workspace-future-heading"><Layout size={24} aria-hidden="true"/><h2>组合与资源</h2><span className="workspace-state">尚未接入</span></div><p>跨项目比较投入、优先级、资源与供应冲突，支持具名取舍。相关组合与资源读集尚未建立，当前可先查看权限内的项目。</p><ul><li>跨项目组合与投入比较</li><li>共享资源占用与冲突</li><li>需决定事项与具名取舍</li></ul><Button variant="outline" onClick={() => navigate("projects")}>查看项目</Button></section>;
  else if ((location.area === "category" || location.area === "knowledge") && categoriesError) content = <section className="workspace-empty"><p role="alert">品类范围与产品管理权限暂未读取完成：{categoriesError}</p><Button variant="outline" onClick={() => void load()}><ArrowClockwise/>重新读取</Button></section>;
  else if (location.area === "knowledge" && !category) content = <><div className="workspace-page-heading"><div><h1>知识</h1><p>按本人可见的品类查阅来源、事实和原始资料。</p></div></div><div className="grid gap-3 sm:grid-cols-2">{categories.map(item => <button key={item.id} className="panel text-left" onClick={() => selectCategory(item.id)}><Books size={20} className="mb-3 text-primary" aria-hidden="true"/><strong>{item.name}</strong><p className="subtle mt-2">{item.purpose}</p></button>)}</div>{categories.length === 0 && <p className="workspace-empty" role="status">当前没有可见的品类知识，请联系相应品类负责人核对访问范围。</p>}</>;
  else if (location.area === "knowledge" && category && !knowledgeWorkbench) content = <KnowledgeLibrary key={`${session!.principal_id}:${category.id}`} api={browserApi} categoryId={category.id} categoryName={category.name} principalId={session!.principal_id} />;
  else if (location.area === "category" && !projectWorkbench && managementError && !managedCategories.some(item => item.id === location.categoryId)) content = <section className="workspace-empty"><p role="status">{managementError}</p><Button variant="outline" onClick={() => void load()}><ArrowClockwise/>重新读取权限</Button></section>;
  else if (location.area === "category" && !projectWorkbench && (!managedCategories.length || Boolean(location.categoryId) && !managedCategories.some(item => item.id === location.categoryId))) content = <section className="workspace-empty"><p>当前范围没有产品管理权限。你可以从我的工作和项目办理岗位工作，小Pai 仍可使用。</p><Button variant="outline" onClick={() => navigate("projects")}>打开项目</Button></section>;
  else if (location.area === "category" || location.area === "knowledge") content = <CategoryArea area={location.area} projectId={location.projectId} categories={location.area === "category" && !projectWorkbench ? managedCategories : categories} categoryId={location.categoryId} onSelectCategory={selectCategory} onCreated={created => { setCategories(old => [...old.filter(item => item.id !== created.id), created]); selectCategory(created.id); void load(); }} onPaiContext={setPaiContext} onOpenPai={() => setPaiOpen(true)} />;
  else content = <section className="workspace-preferences"><div className="workspace-page-heading"><div className="min-w-0"><h1>设置</h1><p>个人外观与低频运行管理。模型与原件保留设置位于品类工作台的设置区。</p></div></div><h2>界面外观</h2><div className="workspace-preference-row"><div><p>主题</p><p className="subtle">选择适合当前工作环境的显示方式</p></div><ThemeOptions /></div><div className="workspace-preference-row"><div><p>侧栏</p><p className="subtle">按当前用户记住展开或收起状态</p></div><Button variant="outline" onClick={toggleSidebar}><SidebarSimple/>{collapsed ? "展开侧栏" : "收起侧栏"}</Button></div><div className="workspace-preference-row"><div><p>小Pai 工作栏</p><p className="subtle">按当前用户记住右侧工作栏开关</p></div><Button variant="outline" aria-pressed={paiOpen} onClick={togglePai}><Sparkle/>{paiOpen ? "关闭小Pai 工作栏" : "打开小Pai 工作栏"}</Button></div><div className="mt-8 min-w-0">{location.categoryId ? <ConnectedAutomationRules key={`automation:${session!.principal_id}:${location.categoryId}`} api={browserApi} principalId={session!.principal_id} categoryId={location.categoryId} onOpenRun={openRun} /> : <p className="subtle">请先选择品类，再管理本人小Pai 规则。</p>}</div></section>;

  return <div className={`workspace-frame${collapsed ? " workspace-collapsed" : ""}${paiOpen ? " workspace-pai-open" : ""}`}>
    <a href="#workspace-content" className="workspace-skip">跳到工作内容</a>
    <aside className="workspace-sidebar">{navigation()}</aside>
    <dialog ref={mobileDialog} className="workspace-mobile-navigation" aria-label="工作区导航" onCancel={event => { event.preventDefault(); closeMobile(); }}>{navigation(true)}</dialog>
    <div className="workspace-body">
      <header className="workspace-header">
        <Button ref={mobileTrigger} size="icon" variant="ghost" className="workspace-mobile-trigger" aria-label="打开导航" onClick={() => mobileDialog.current?.showModal()}><List/></Button>
        <div className="workspace-breadcrumb">{(location.area === "cockpit" && location.projectId || projectWorkbench) && <><a href={pageHref(globalHref({ area: "projects", categoryId: "", projectId: "" }))} onClick={event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate("projects"); }}>项目</a><CaretRight size={12} aria-hidden="true"/></>}<span className="font-medium truncate">{projectWorkbench || location.area === "cockpit" && location.projectId ? activeProject?.project.name ?? "项目工作区" : proposalFocus ? "立项提案" : areaEntry.label}</span>{category && (location.area === "category" && !projectWorkbench || location.area === "knowledge") && <><CaretRight size={12} aria-hidden="true"/><span className="truncate">{category.name}</span></>}</div>
        <div className="workspace-header-actions">
          {location.area === "work" && <time className={styles.headerDate} dateTime={today.toLocaleDateString("sv-SE")}>{dateLabel}</time>}
          <div ref={searchControl} className={styles.searchAction}><ObjectSearch api={browserApi} onNavigate={href => { pushAndApply(href); requestAnimationFrame(() => document.getElementById("workspace-content")?.focus()); }} /></div>
        </div>
      </header>
      <main id="workspace-content" tabIndex={-1} className={`workspace-content ${styles.content}`}>{content}</main>
    </div>
    {!paiOpen && !documentMode && <button type="button" className={styles.fab} onClick={showPai} title="在当前范围打开小Pai" aria-label="打开小Pai工作栏"><Sparkle size={18} aria-hidden="true"/>小Pai</button>}
    <PaiRail expectedProjectId={["cockpit", "category"].includes(location.area) ? location.projectId : undefined} open={paiOpen} onClose={togglePai} categoryId={location.categoryId} categoryName={category?.name ?? ""} paiContext={paiContext} focusRun={focusRun} session={session!} onCreated={created => { setCategories(old => [...old.filter(item => item.id !== created.id), created]); selectCategory(created.id); void load(); }} />
  </div>;
}
