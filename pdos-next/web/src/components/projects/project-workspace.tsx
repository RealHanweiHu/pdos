"use client";

import { useState, type ReactNode } from "react";
import { ArrowClockwise, ArrowLeft, ArrowRight, CalendarBlank, ClipboardText, Flag, Info, NotePencil, Package, Warning } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { dueState, projectStateLabel, type PortfolioProject } from "@/lib/portfolio-reads";
import { formatProjectDate, projectForecast, projectOwner } from "@/lib/project-presentation";
import { projectWorkbenchHref } from "@/lib/global-navigation";
import type { browserApi } from "@/lib/browser-api";
import { ProjectBuildSummary } from "./project-build-summary";
import { ProjectCommitments } from "./project-commitments";
import { ProjectActivity } from "./project-activity";
import { ProjectManufacturingPreparation } from "./project-manufacturing-preparation";
import { ProjectBuildEngineering } from "./project-build-engineering";
import { ProjectReleasePackages } from "./project-release-packages";
import { ProjectPilots } from "./project-pilots";
import { ProjectExternalHandoffs } from "./project-external-handoffs";
import styles from "./project-views.module.css";

type Props = {
  api: typeof browserApi; onRefresh?: () => void; readAt?: string | null; readVersion?: number;
  entry: PortfolioProject; session: { name: string; principal_id: string }; today: string;
  onBack: () => void;
  onOpenWorkbench: (categoryId: string, productId: string, projectId: string) => void;
};
const visibilityLabels: Record<string, string> = { private: "私有", category: "品类共享", audience: "指定受众" };
const tabs = [
  { id: "now", label: "现在" }, { id: "gates", label: "阶段与门禁" },
  { id: "plan", label: "工作与计划" }, { id: "builds", label: "Builds" },
  { id: "prep", label: "工程与制造准备" }, { id: "issues", label: "问题与变更" },
  { id: "review", label: "评审与交接" }, { id: "docs", label: "资料" },
] as const;
type Tab = typeof tabs[number]["id"];
function workHref(entry: PortfolioProject, view: string, task = "") {
  const params = new URLSearchParams(projectWorkbenchHref(entry.category.id, entry.product.id, entry.project.id));
  params.set("view", view);
  if (task) params.set("task", task);
  return `?${params}`;
}
function Section({ title, icon, tail, children, className = "" }: { title: string; icon?: ReactNode; tail?: ReactNode; children: ReactNode; className?: string }) {
  return <section className={`${styles.section} ${className}`} aria-label={title}><h2>{icon}{title}{tail && <span>{tail}</span>}</h2>{children}</section>;
}

export function ProjectWorkspace({ entry, api, session, today, onBack, onOpenWorkbench, onRefresh, readAt, readVersion = 0 }: Props) {
  const [tab, setTab] = useState<Tab>("now");
  const { project, category, product } = entry;
  const open = entry.openItems.filter(item => !["done", "closed", "cancelled"].includes(item.status));
  const forecast = projectForecast(entry);
  const owner = project.owner_id === session.principal_id ? `${session.name}（本人）` : projectOwner(entry);
  const plan = <Section title="计划与四时间" icon={<CalendarBlank size={15}/>} tail={project.plan ? `计划 v${project.plan.revision}` : project.plan_state === "unavailable" ? "暂不可读" : "尚无计划"}><div className={styles.sectionBox}>{["基线", "预测", "承诺", "实际"].map(label => <div className={styles.timeRow} key={label}><span className={styles.timeLabel}>{label}</span><span className={styles.unknown}>{label === "预测" ? `${formatProjectDate(forecast.earliest)} — ${formatProjectDate(forecast.latest)}` : "未知"}</span></div>)}<p className={styles.noteInline}>预测为计划完成范围，不代表门禁日期。</p><Button size="sm" variant="outline" onClick={() => onOpenWorkbench(category.id, product.id, project.id)}>进入工作与计划<ArrowRight size={13}/></Button></div></Section>;
  const build = <Section title="下一 Build" icon={<Package size={15}/> }><div className={styles.sectionBox}><p className={styles.unknown}>总览尚未提供项目轮次的执行优先级。</p><dl className={styles.buildFacts}><dt>产品定义</dt><dd>{project.definition.title} · 固定 v{project.definition.revision}</dd><dt>制造配置</dt><dd className={styles.unknown}>待选择本项目 Build 后核对</dd><dt>数量与样件</dt><dd className={styles.unknown}>待读取 Build 记录</dd><dt>验证范围</dt><dd className={styles.unknown}>待读取轮次验证准备</dd></dl><div className={styles.rowActions}><a className={styles.outlineLink} href={workHref(entry, "builds", "prepare")}>查看本项目 Builds<ArrowRight size={13}/></a><a className={styles.outlineLink} href={workHref(entry, "verification", "handoff")}>交样与接收</a></div></div></Section>;
  const scope = <Section title="项目范围"><div className={styles.sectionBox}><dl><dt>用途</dt><dd>{project.purpose}</dd><dt>开发范围</dt><dd>{project.scope}</dd><dt>立项定义</dt><dd>{project.definition.title} · 固定 v{project.definition.revision}{project.source_status !== "current" ? " · 来源需重核" : ""}</dd><dt>可见范围</dt><dd>{visibilityLabels[project.visibility] ?? project.visibility}</dd></dl></div></Section>;

  return <div className={`${styles.workspace} project-canvas`}>
    <div className={styles.workspaceHead}><div className={styles.workspaceTools}><button type="button" className={styles.back} onClick={onBack} aria-label="返回项目"><ArrowLeft size={16}/></button><span className={styles.workspaceToolsSpacer}/>{onRefresh && <button type="button" className={styles.refresh} aria-label="刷新项目资料" onClick={onRefresh}><ArrowClockwise size={14}/></button>}<Button size="sm" variant="outline" onClick={() => onOpenWorkbench(category.id, product.id, project.id)}><NotePencil size={14}/>写状态更新</Button></div><div className={styles.workspaceTitle}><h1>{project.name}</h1><span className={styles.tag}>{projectStateLabel(entry)}</span><span className={styles.tag}>健康度未知</span></div>
      <dl className={styles.attributes}><div><dt>型号</dt><dd>{product.name}</dd></div><div><dt>品类</dt><dd>{category.name}</dd></div><div><dt>项目负责人</dt><dd>{owner}</dd></div><div><dt>下一门禁</dt><dd className={styles.unknown}>承诺 / 预测待提供</dd></div></dl>
      <button type="button" className={styles.stageRail} onClick={() => setTab("gates")}><Flag size={15}/><span>阶段记录待接入<small>阶段模板与门禁规则结果尚未提供</small></span><ArrowRight size={13}/></button>
    </div>
    <div className={styles.tabs} role="tablist" aria-label="项目工作区视图" onKeyDown={event => { if (!["ArrowLeft", "ArrowRight", "Home", "End"].includes(event.key)) return; event.preventDefault(); const index = tabs.findIndex(item => item.id === tab), next = event.key === "Home" ? tabs[0] : event.key === "End" ? tabs[tabs.length - 1] : tabs[(index + (event.key === "ArrowRight" ? 1 : -1) + tabs.length) % tabs.length]; setTab(next.id); requestAnimationFrame(() => document.getElementById(`project-tab-${next.id}`)?.focus()); }}>{tabs.map(item => <button type="button" role="tab" key={item.id} id={`project-tab-${item.id}`} aria-controls={`project-panel-${item.id}`} tabIndex={tab === item.id ? 0 : -1} aria-selected={tab === item.id} onClick={() => setTab(item.id)}>{item.label}</button>)}</div>
    <div id={`project-panel-${tab}`} role="tabpanel" aria-labelledby={`project-tab-${tab}`} className={styles.workspaceBody}>
      {tab === "now" && <div className={styles.workspaceGrid}><div>{build}<Section title="需要办理" icon={<ClipboardText size={15}/>} tail={entry.openItemsError ? "暂不可读" : `${open.length} 项任务 / 风险`}>
        {entry.openItemsError ? <p role="status" className="workspace-read-error">{entry.openItemsError}</p> : open.length === 0 ? <p className={styles.panelEmpty}>当前没有未结任务或风险。</p> : open.map(item => <div className={styles.action} key={item.id}>{item.kind === "risk" ? <Warning size={15} aria-hidden="true"/> : <ClipboardText size={15} aria-hidden="true"/>}<div className={styles.actionBody}><p>{item.title}</p><small>{item.kind === "risk" ? "风险" : "任务"} · {item.owner_id === session.principal_id ? "本人负责" : item.owner_name ?? "负责人姓名暂不可读"}</small></div><span className={styles.tag} data-overdue={dueState(item, today) === "overdue"}>{dueState(item, today) === "overdue" ? "已逾期 · " : ""}{item.due_date ?? "期限未知"}</span><Button size="sm" variant="ghost" onClick={() => onOpenWorkbench(category.id, product.id, project.id)}>办理<ArrowRight size={12}/></Button></div>)}<p className={styles.panelFoot}>接收、验证与待决定事项尚未汇入本总览。</p></Section></div>
        <div><ProjectCommitments api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} readVersion={readVersion}/><div className={styles.updatePrompt}><span className={styles.avatar}>{session.name.slice(0, 1)}</span><button type="button" onClick={() => onOpenWorkbench(category.id, product.id, project.id)}>写具名状态更新</button></div><div className={styles.activitySlot}><ProjectActivity api={api} scope={{ categoryId: category.id, productId: product.id, projectId: project.id, principalId: session.principal_id }} readVersion={readVersion}/></div>{plan}</div></div>}
      {tab === "gates" && <><Section title="阶段与出口条件"><div className={styles.sectionBox}><p className={styles.unknown}>尚未取得本项目类型的阶段模板与门禁规则结果。</p><p className={styles.noteInline}>已有计划和任务数量不能代替阶段决定。</p></div></Section><div className={styles.maturity}>{["产品验证", "制造", "交付适用性"].map(label => <Section key={label} title={label}><p className={styles.panelEmpty}>未知 · 对应证据尚未读取</p></Section>)}</div><div className={styles.workspaceGrid}><Section title="下一阶段进入条件"><p className={styles.panelEmpty}>待阶段模板提供；下一阶段的条件不自动成为本阶段阻塞。</p></Section><Section title="冻结点与阶段历史"><p className={styles.panelEmpty}>冻结点与具名阶段决定尚未接入。</p></Section></div></>}
      {tab === "plan" && <div className={styles.workspaceGrid}><div>{plan}</div><div>{scope}</div></div>}
      {tab === "builds" && <ProjectBuildSummary categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} readVersion={readVersion} api={api}/>}
      {tab === "prep" && <><ProjectBuildEngineering api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} readVersion={readVersion}/><Section title="工程与制造准备办理"><div className={styles.sectionBox}><p>从本项目 Build 选择固定引用的工程与制造配置，再核对准备缺项。</p><p className={styles.noteInline}>工程与制造配置按型号共享，轮次准备按项目核对；下面的制造准备草稿不代替当前准备度或正式发布。</p><a className={styles.outlineLink} href={workHref(entry, "builds", "prepare")}>配置、制造与试产办理<ArrowRight size={13}/></a></div></Section><ProjectManufacturingPreparation api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} readVersion={readVersion}/><ProjectPilots api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} readVersion={readVersion}/></>}
      {tab === "issues" && <Section title="问题与变更"><div className={styles.sectionBox}><p>进入本项目固定失败、问题、CAPA 与工程 / 制造双线影响核对。</p><p className={styles.noteInline}>本总览尚未汇入问题计数和状态，不以任务或风险数代替。</p><a className={styles.outlineLink} href={workHref(entry, "issues")}>办理本项目问题与变更<ArrowRight size={13}/></a></div></Section>}
      {tab === "review" && <><ProjectReleasePackages api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} readVersion={readVersion}/><ProjectExternalHandoffs api={api} categoryId={category.id} productId={product.id} projectId={project.id} principalId={session.principal_id} readVersion={readVersion}/><Section title="评审与交接办理"><div className={styles.sectionBox}><p className={styles.unknown}>阶段正式评审读集尚未接入；发布包与专业决定按各自固定范围读取。</p><div className={styles.rowActions}><a className={styles.outlineLink} href={workHref(entry, "builds", "prepare")}>发布包、专业决定与外部移交办理</a><a className={styles.outlineLink} href={workHref(entry, "verification", "handoff")}>样件交接与接收</a><a className={styles.outlineLink} href={workHref(entry, "verification", "results")}>测试结果与处置</a></div></div></Section></>}
      {tab === "docs" && <div className={styles.workspaceGrid}><div>{scope}</div><Section title="资料"><div className={styles.sectionBox}><p>项目资料包尚未汇入总览。</p><p className={styles.noteInline}>现有原件在型号范围共享，进入后仍按当前权限读取。</p><a className={styles.outlineLink} href={workHref(entry, "files")}>查看型号共享原件<ArrowRight size={13}/></a></div></Section></div>}
    </div>
    <p className={styles.note}><Info size={14}/>项目阶段、健康度和具名更新只按对应记录展示。</p>
    {readAt && <p className={styles.readTime}>读取于 <time dateTime={readAt}>{new Date(readAt).toLocaleString()}</time></p>}
  </div>;
}
