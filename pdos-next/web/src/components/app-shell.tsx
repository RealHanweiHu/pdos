"use client";

import { useCallback, useEffect, useRef, useState, type ReactNode } from "react";
import { useTheme } from "next-themes";
import { Books, CaretRight, ChartBar, CirclesFour, FolderSimple, Gear, Kanban, Layout, List, Moon, SidebarSimple, Sparkle, SquaresFour, Sun, Tray, X, type Icon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { browserApi } from "@/lib/browser-api";
import { defaultGlobalLocation, globalAreas, globalHref, normalizeGlobalSearch, resolveGlobalLocation, type GlobalArea, type GlobalLocation } from "@/lib/global-navigation";
import { MyWork } from "@/components/my-work";
import { ProjectList } from "@/components/projects/project-list";
import { ProjectCockpit } from "@/components/projects/project-cockpit";
import { CategoryArea } from "@/components/category-workspace";
import { PaiRail, type PaiContext } from "@/components/pai-rail";

type Session = { name: string; principal_id: string };
type Category = { id: string; name: string; purpose: string };

const areaIcons: Record<GlobalArea, Icon> = {
  work: Tray, cockpit: Kanban, projects: FolderSimple, programs: Layout,
  category: SquaresFour, knowledge: Books, settings: Gear,
};

function ThemeOptions() {
  const { theme, setTheme: apply } = useTheme();
  return <div className="workspace-theme-options">{([{ value: "light", label: "亮色", Icon: Sun }, { value: "dark", label: "暗色", Icon: Moon }, { value: "system", label: "跟随系统", Icon: SidebarSimple }] as const).map(({ value, label, Icon }) => <Button key={value} variant="outline" aria-pressed={theme === value} onClick={() => apply(value)}><Icon/>{label}</Button>)}</div>;
}

export function AppShell() {
  const [auth, setAuth] = useState<"loading" | "signed_out" | "ready">("loading");
  const [session, setSession] = useState<Session | null>(null);
  const [categories, setCategories] = useState<Category[]>([]);
  const [entryError, setEntryError] = useState("");
  const [location, setLocation] = useState<GlobalLocation>(defaultGlobalLocation);
  const [collapsed, setCollapsed] = useState(false);
  const [paiOpen, setPaiOpen] = useState(false);
  const [paiContext, setPaiContext] = useState<PaiContext | null>(null);
  const [focusRun, setFocusRun] = useState<{ runId: string; categoryId: string } | null>(null);
  const mobileDialog = useRef<HTMLDialogElement>(null);
  const mobileTrigger = useRef<HTMLButtonElement>(null);
  const { resolvedTheme, setTheme } = useTheme();

  const load = useCallback(async () => {
    try {
      const who = await browserApi<Session>("v1/session");
      const list = await browserApi<Category[]>("v1/categories").catch(() => [] as Category[]);
      setSession(who); setCategories(list); setAuth("ready");
    } catch (failure) {
      if ((failure as { status?: number }).status === 401) setAuth("signed_out");
      else { setEntryError((failure as Error).message); setAuth("signed_out"); }
    }
  }, []);
  useEffect(() => { let active = true; void Promise.resolve().then(() => { if (active) return load(); }); return () => { active = false; }; }, [load]);

  useEffect(() => {
    const normalized = normalizeGlobalSearch(window.location.search);
    if (normalized.changed) window.history.replaceState(null, "", normalized.search);
    const read = () => setLocation(resolveGlobalLocation(window.location.search));
    read();
    window.addEventListener("popstate", read);
    return () => window.removeEventListener("popstate", read);
  }, []);

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

  function pushAndApply(href: string) {
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
  function openWorkbench(categoryId: string, productId: string) {
    pushAndApply(`?${new URLSearchParams({ area: "category", category: categoryId, bench: "projects", view: "overview", product: productId }).toString()}`);
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
  function closeMobile() { mobileDialog.current?.close(); mobileTrigger.current?.focus(); }
  function openRun(runId: string, categoryId: string) {
    setFocusRun({ runId, categoryId });
    if (categoryId && categoryId !== location.categoryId) selectCategory(categoryId);
    setPaiOpen(true);
  }

  if (auth === "loading") return <main className="mx-auto max-w-5xl px-4 py-16"><p role="status">正在载入你的工作区…</p></main>;
  if (auth === "signed_out") return <>
    <header className="workspace-public-header"><CirclesFour size={22} weight="fill" className="text-primary" aria-hidden="true"/><span className="font-semibold">PDOS</span><Button className="ml-auto" size="icon" variant="ghost" aria-label="切换明暗主题" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>{resolvedTheme === "dark" ? <Sun/> : <Moon/>}</Button></header>
    <main className="mx-auto max-w-lg px-4 py-16"><div className="panel">
      <p className="subtle">独立新工程 · 合成预览</p>
      <h1 className="mt-3 text-2xl font-semibold">PDOS 研发工作区</h1>
      <p className="my-5">我的工作、项目驾驶舱、项目列表、项目集、产品品类工作区、小Pai 与知识共用一个入口。此环境只用于合成资料演练。</p>
      {entryError && <p role="alert" className="mb-4">{entryError}</p>}
      <Button onClick={async () => { setEntryError(""); try { await browserApi("local-session", {}); await load(); } catch (failure) { setEntryError((failure as Error).message); } }}>进入本地合成环境</Button>
    </div></main>
  </>;

  const category = categories.find(item => item.id === location.categoryId);
  const areaEntry = globalAreas.find(item => item.id === location.area) ?? globalAreas[0];
  function navigation(mobile = false) {
    return <>
      <div className="workspace-brand"><CirclesFour size={22} weight="fill" className="text-primary" aria-hidden="true"/><span className="workspace-nav-label font-semibold">PDOS</span><Button size="icon" variant="ghost" className="workspace-brand-toggle" aria-label={mobile ? "关闭导航" : collapsed ? "展开侧栏" : "收起侧栏"} onClick={mobile ? closeMobile : toggleSidebar}>{mobile ? <X/> : <SidebarSimple/>}</Button></div>
      <nav aria-label={mobile ? "移动工作区导航" : "工作区导航"} className="workspace-navigation">
        {globalAreas.filter(item => item.id !== "settings").map(item => {
          const Icon = areaIcons[item.id];
          return <a key={item.id} href={globalHref({ area: item.id, categoryId: location.categoryId, projectId: "" }, window.location.search)} className="workspace-nav-item" aria-current={location.area === item.id ? "page" : undefined} aria-label={item.label} title={item.label} onClick={event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate(item.id); }}><Icon size={18} aria-hidden="true"/><span className="workspace-nav-label">{item.label}</span>{item.planned && <span className="workspace-nav-label subtle ml-auto text-[10px]">尚未接入</span>}</a>;
        })}
        {category && <div className="workspace-nav-scope workspace-nav-label"><p className="workspace-nav-group">当前品类</p><p className="truncate font-medium" title={category.name}>{category.name}</p><p className="subtle mt-1">项目与专业工作按品类范围授权</p></div>}
      </nav>
      <div className="workspace-sidebar-bottom">
        <a href="/plan" className="workspace-nav-item" aria-label="计划执行进度" title="计划执行进度（唯一清单只读投影）"><ChartBar size={18} aria-hidden="true"/><span className="workspace-nav-label">计划进度</span></a>
        <button type="button" className="workspace-nav-item w-full" aria-label="小Pai 工作栏" title="小Pai 工作栏" aria-pressed={paiOpen} onClick={() => { togglePai(); closeMobile(); }}><Sparkle size={18} aria-hidden="true"/><span className="workspace-nav-label">小Pai</span></button>
        <a href={globalHref({ area: "settings", categoryId: location.categoryId, projectId: "" }, window.location.search)} className="workspace-nav-item" aria-label="设置" title="设置" aria-current={location.area === "settings" ? "page" : undefined} onClick={event => { if (event.button || event.metaKey || event.ctrlKey || event.shiftKey || event.altKey) return; event.preventDefault(); navigate("settings"); }}><Gear size={18} aria-hidden="true"/><span className="workspace-nav-label">设置</span></a>
        <div className="workspace-profile"><span className="workspace-avatar" aria-hidden="true">{session?.name.slice(0, 1) ?? "P"}</span><div className="workspace-nav-label min-w-0"><p className="truncate text-xs font-medium">{session?.name}</p><p className="workspace-environment">本地合成环境</p></div></div>
      </div>
    </>;
  }

  let content: ReactNode;
  if (location.area === "work") content = <MyWork api={browserApi} session={session!} onOpenRun={openRun} onOpenProject={(categoryId, projectId) => navigate("cockpit", { categoryId, projectId })} onOpenPai={() => setPaiOpen(true)} />;
  else if (location.area === "projects") content = <ProjectList api={browserApi} onOpenProject={(categoryId, projectId) => navigate("cockpit", { categoryId, projectId })} onOpenWorkbench={openWorkbench} />;
  else if (location.area === "cockpit") content = <ProjectCockpit api={browserApi} session={session!} location={location} onOpenProject={(categoryId, projectId) => navigate("cockpit", { categoryId, projectId })} onOpenList={() => navigate("projects")} onOpenWorkbench={openWorkbench} />;
  else if (location.area === "programs") content = <section className="workspace-future" aria-label="项目集接入状态"><div className="workspace-future-heading"><Layout size={24} aria-hidden="true"/><h2>项目集</h2><span className="workspace-state">尚未接入</span></div><p>项目集用于跨项目组合取舍：投入、优先级、资源与供应冲突、需要管理层决定的事项（v1.1 §796）。项目集领域对象与组合读集尚未建立，当前可在项目驾驶舱查看权限内各项目的风险与到期冲突。</p><ul><li>跨项目组合与投入比较</li><li>共享资源占用与冲突</li><li>需决定事项与具名取舍</li></ul><Button variant="outline" onClick={() => navigate("cockpit")}>查看项目驾驶舱</Button></section>;
  else if (location.area === "category" || location.area === "knowledge") content = <CategoryArea area={location.area} categories={categories} categoryId={location.categoryId} onSelectCategory={selectCategory} onCreated={created => { setCategories(old => [...old.filter(item => item.id !== created.id), created]); selectCategory(created.id); }} onPaiContext={setPaiContext} onOpenPai={() => setPaiOpen(true)} />;
  else content = <section className="workspace-preferences"><div className="workspace-page-heading"><div className="min-w-0"><h1>设置</h1><p>个人外观与低频运行管理。模型与原件保留设置位于品类工作台的设置区。</p></div></div><h2>界面外观</h2><div className="workspace-preference-row"><div><p>主题</p><p className="subtle">选择适合当前工作环境的显示方式</p></div><ThemeOptions /></div><div className="workspace-preference-row"><div><p>侧栏</p><p className="subtle">按当前用户记住展开或收起状态</p></div><Button variant="outline" onClick={toggleSidebar}><SidebarSimple/>{collapsed ? "展开侧栏" : "收起侧栏"}</Button></div><div className="workspace-preference-row"><div><p>小Pai 工作栏</p><p className="subtle">按当前用户记住右侧工作栏开关</p></div><Button variant="outline" aria-pressed={paiOpen} onClick={togglePai}><Sparkle/>{paiOpen ? "关闭小Pai 工作栏" : "打开小Pai 工作栏"}</Button></div></section>;

  return <div className={`workspace-frame${collapsed ? " workspace-collapsed" : ""}${paiOpen ? " workspace-pai-open" : ""}`}>
    <a href="#workspace-content" className="workspace-skip">跳到工作内容</a>
    <aside className="workspace-sidebar">{navigation()}</aside>
    <dialog ref={mobileDialog} className="workspace-mobile-navigation" aria-label="工作区导航" onCancel={event => { event.preventDefault(); closeMobile(); }}>{navigation(true)}</dialog>
    <div className="workspace-body">
      <header className="workspace-header">
        <Button ref={mobileTrigger} size="icon" variant="ghost" className="workspace-mobile-trigger" aria-label="打开导航" onClick={() => mobileDialog.current?.showModal()}><List/></Button>
        <div className="workspace-breadcrumb"><span>PDOS</span><CaretRight size={12} aria-hidden="true"/><span className="font-medium">{areaEntry.label}</span>{category && (location.area === "category" || location.area === "knowledge") && <><CaretRight size={12} aria-hidden="true"/><span className="font-medium truncate">{category.name}</span></>}</div>
        <div className="workspace-header-actions">
          <Button size="icon" variant="ghost" aria-label="小Pai 工作栏" aria-pressed={paiOpen} onClick={togglePai}><Sparkle/></Button>
          <Button size="icon" variant="ghost" aria-label="切换明暗主题" onClick={() => setTheme(resolvedTheme === "dark" ? "light" : "dark")}>{resolvedTheme === "dark" ? <Sun/> : <Moon/>}</Button>
        </div>
      </header>
      <main id="workspace-content" tabIndex={-1} className="workspace-content">{content}</main>
    </div>
    <PaiRail open={paiOpen} onClose={togglePai} categoryId={location.categoryId} categoryName={category?.name ?? ""} paiContext={paiContext} focusRun={focusRun} session={session!} onCreated={created => { setCategories(old => [...old.filter(item => item.id !== created.id), created]); selectCategory(created.id); }} />
  </div>;
}
