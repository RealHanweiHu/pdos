"use client";

import { useMemo, useState } from "react";
import { ArrowClockwise, ArrowLeft, CaretDown, CaretRight, NotePencil } from "@phosphor-icons/react";
import { projectStateLabel, type PortfolioProject } from "@/lib/portfolio-reads";
import { projectOwner } from "@/features/projects/lib/project-presentation";
import type { browserApi } from "@/lib/browser-api";
import { categoryTransport } from "@/lib/category-transport";
import { ProjectGovernance } from "./project-governance";
import { ProjectPlanResources } from "./project-plan-resources";
import { ProjectWork } from "./project-work";
import { useCreateIntent } from "@/features/shell/use-create-intent";
import { ConnectedProjectPlanning } from "./connected-project-planning";
import { ProjectActivity } from "./project-activity";
import { ProjectDiscussions } from "./project-discussions";
import { ProjectOverviewView } from "./project-overview";
import { ProjectProfessional } from "./project-professional";
import { ProjectTeam } from "./project-team";
import { ScopeNotesSection } from "@/features/scope-notes/scope-notes-section";
import { projectViews as tabs, isProfessionalView, type ProjectViewId, type ProfessionalView } from "@/lib/project-workspace-navigation";
import styles from "./project-views.module.css";

type Props = {
  initialView?: ProjectViewId;
  api: typeof browserApi; onRefresh?: () => void; readAt?: string | null; readVersion?: number;
  entry: PortfolioProject; session: { name: string; principal_id: string }; today: string;
  onBack: () => void;
  onOpenWorkbench: (categoryId: string, productId: string, projectId: string) => void;
  onOpenRun?: (runId: string, categoryId: string) => void;
};
type Tab = ProjectViewId;

export function ProjectWorkspace({ entry, api, session, onBack, onOpenRun, onRefresh, readAt, readVersion = 0, initialView = "tasks" }: Props) {
  const [tab, setTab] = useState<Tab>(initialView);
  const [lastProfessional, setLastProfessional] = useState<ProfessionalView | null>(isProfessionalView(initialView) ? initialView : null);
  const [routeView, setRouteView] = useState(initialView);
  if (routeView !== initialView) {
    setRouteView(initialView); setTab(initialView);
    if (isProfessionalView(initialView)) setLastProfessional(initialView);
  }
  const [writingUpdate, setWritingUpdate] = useState(false);
  // ⌘K 的“写状态更新”打开同一个具名周报编辑区；是否可写仍由编辑区按服务器成员资格判定。
  useCreateIntent("status_update", "ready", () => setWritingUpdate(true));
  const [detailsOpen, setDetailsOpen] = useState(false);
  function chooseTab(next: Tab) {
    setTab(next);
    if (isProfessionalView(next)) setLastProfessional(next);
    if (typeof window !== "undefined") {
      const params = new URLSearchParams(window.location.search);
      params.set("projectView", next); params.delete("panel");
      window.history.replaceState(null, "", `?${params}`);
    }
  }
  const [planView, setPlanView] = useState<"milestones" | "resources" | "commitments">("milestones");
  const { project, category, product } = entry;
  const scoped = useMemo(() => categoryTransport(category.id, api), [category.id, api]);
  const governance = project.governance;
  const owner = project.owner_id === session.principal_id ? `${session.name}（本人）` : projectOwner(entry);
  // 概览的“去办理/查看”只定位到原记录所在的视图，不在概览执行命令。
  function openFromOverview(view: string, panel?: string | null) {
    const next = tabs.find(item => item.id === view)?.id ?? "tasks";
    if (next === "plan") setPlanView(panel === "commitments" ? "commitments" : panel === "resources" ? "resources" : "milestones");
    chooseTab(next);
  }

  return <div className={styles.workspace}>
    <header className={styles.workspaceHead}>
      <div className={styles.workspaceTitle}>
        <button type="button" className={styles.monogram} onClick={onBack} aria-label="返回项目列表" title="返回项目列表">{project.name.slice(0, 2)}</button>
        <div className={styles.projectIdentity}><h1>{project.name}</h1><button type="button" className={styles.stageLink} onClick={() => chooseTab("gates")}><span className={styles.stageUnknown} aria-hidden="true"/>{governance?.current_stage?.name ?? (governance?.completed ? "阶段已完成" : "阶段待确认")}<CaretRight size={12}/></button></div>
        <span className={styles.projectLead}>负责人 {owner}</span>
      </div>
    </header>
    <div className={styles.tabBar}><div className={styles.tabs} role="tablist" aria-label="项目工作区视图" onKeyDown={event => { if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; event.preventDefault(); const visible = tabs.slice(0,4), index = visible.findIndex(item => item.id === tab), next = event.key === "Home" ? visible[0] : event.key === "End" ? visible[visible.length - 1] : visible[(index + (event.key === "ArrowRight" ? 1 : -1) + visible.length) % visible.length]; chooseTab(next.id); requestAnimationFrame(() => document.getElementById(`project-tab-${next.id}`)?.focus()); }}>{tabs.slice(0,4).map(item => <button type="button" role="tab" key={item.id} id={`project-tab-${item.id}`} aria-controls={`project-panel-${item.id}`} tabIndex={tab === item.id || !tabs.slice(0,4).some(t => t.id === tab) && item.id === "now" ? 0 : -1} aria-selected={tab === item.id} onClick={() => chooseTab(item.id)}>{item.label}</button>)}</div><details className={styles.more} onKeyDown={event => { if (event.key === "Escape") { event.currentTarget.open = false; event.currentTarget.querySelector("summary")?.focus(); } }} onBlur={event => { if (!event.currentTarget.contains(event.relatedTarget)) event.currentTarget.open = false; }}><summary aria-label="更多项目视图" id="project-tab-more" data-active={!tabs.slice(0,4).some(t => t.id === tab)}>更多<CaretDown size={12}/></summary><div>{tabs.slice(4).map(item => <button type="button" key={item.id} id={`project-tab-${item.id}`} aria-current={tab === item.id ? "page" : undefined} onClick={event => { chooseTab(item.id); const menu = event?.currentTarget.closest("details"); menu?.removeAttribute("open"); if (menu) requestAnimationFrame(() => menu.querySelector("summary")?.focus()); }}>{item.label}</button>)}</div></details></div>
    <div id={`project-panel-${tab}`} role="tabpanel" aria-labelledby={tabs.slice(0,4).some(t => t.id === tab) ? `project-tab-${tab}` : "project-tab-more"} className={styles.workspaceBody}>
      {tab === "tasks" && <ProjectWork view="tasks" api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} productRevision={0} readVersion={readVersion} onRefresh={onRefresh} onOpenRun={onOpenRun ? id => onOpenRun(id, category.id) : undefined}/>}
      {tab === "now" && <ProjectOverviewView api={api} scope={{ categoryId: category.id, productId: product.id, projectId: project.id }} principalId={session.principal_id} readVersion={readVersion} onOpen={openFromOverview} onWriteUpdate={() => setWritingUpdate(true)}>
        <div className={styles.activitySlot}><ProjectActivity compact api={api} scope={{ categoryId: category.id, productId: product.id, projectId: project.id, principalId: session.principal_id }} readVersion={readVersion} onOpenRun={onOpenRun ? id => onOpenRun(id, category.id) : undefined}/></div>
        <div className={styles.activitySlot}><ProjectDiscussions api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} readVersion={readVersion} initialThread={typeof window === "undefined" ? null : new URLSearchParams(window.location.search).get("thread")} onOpenRun={onOpenRun ? id => onOpenRun(id, category.id) : undefined}/></div>
        <div className={styles.activitySlot}><ScopeNotesSection categoryId={category.id} productId={product.id} anchor={{ kind: "project", id: project.id }} readVersion={readVersion}/></div>
      </ProjectOverviewView>}
      {tab === "team" && <ProjectTeam api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} readVersion={readVersion}/>}
      {tab === "gates" && <ProjectGovernance api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} readVersion={readVersion} onSaved={onRefresh}/>}
      {tab === "plan" && <div className={styles.planView}><header className={styles.planHeading}><h2>计划</h2><p>安排里程碑，协调资源与承诺。</p></header><nav className="workspace-view-tabs" aria-label="计划视图">{([["milestones","里程碑"],["resources","资源需求"],["commitments","承诺与外部等待"]] as const).map(([id,label]) => <button key={id} aria-pressed={planView === id} onClick={() => setPlanView(id)}>{label}</button>)}</nav><div hidden={planView !== "milestones"}><ConnectedProjectPlanning compact api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} onSaved={() => onRefresh?.()}/></div><div hidden={planView === "milestones"}>{planView === "resources" && <ProjectPlanResources api={scoped} productId={product.id} projectId={project.id} readVersion={readVersion}/>}<ProjectWork view="plan" planSection={planView === "resources" ? "resources" : "commitments"} api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} productRevision={0} readVersion={readVersion} onRefresh={onRefresh}/></div></div>}
      {lastProfessional && <div hidden={!isProfessionalView(tab)} className={styles.professionalSlot}><ProjectProfessional onSaved={onRefresh} productName={product.name} view={lastProfessional} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} api={api} readVersion={readVersion} initialPanel={typeof window === "undefined" ? "" : new URLSearchParams(window.location.search).get("panel") ?? ""}/></div>}

    </div>
    {writingUpdate && <section className={styles.updateEditor} aria-label="写项目状态更新"><ProjectWork view="updates" onCloseEditor={() => setWritingUpdate(false)} api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} productRevision={0} readVersion={readVersion} onRefresh={onRefresh}/></section>}
    <details className={styles.projectDetails} open={detailsOpen} onToggle={event => setDetailsOpen(event.currentTarget.open)}><summary>项目资料与更多操作</summary><dl className={styles.attributes}><div><dt>型号</dt><dd>{product.name}</dd></div><div><dt>品类</dt><dd>{category.name}</dd></div><div><dt>项目记录</dt><dd>{projectStateLabel(entry)}</dd></div></dl><div className={styles.rowActions}><button type="button" onClick={onBack}><ArrowLeft size={14}/>返回项目</button>{onRefresh && <button type="button" onClick={onRefresh}><ArrowClockwise size={14}/>刷新项目资料</button>}<button type="button" onClick={() => setWritingUpdate(true)}><NotePencil size={14}/>写状态更新</button></div>{readAt && <p className={styles.readTime}>读取于 <time dateTime={readAt}>{new Date(readAt).toLocaleString()}</time></p>}</details>
  </div>;
}
