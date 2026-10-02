"use client";

import Link from "next/link";
import { useState } from "react";
import { ArrowRightIcon, CheckIcon, CircleIcon, RowsIcon, SquaresFourIcon } from "@phosphor-icons/react";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import type { Project, ProjectStage } from "./project-types";
import type { ProjectIssue, ProjectTask, ProjectWorkItems } from "./project-work-item-types";

type Item = { id: string; title: string; stageId: string | null; kind: "task" | "action" | "issue"; status: string; date: string | null; closed: boolean; blocked: boolean; dependencies: string[] };
const taskLabels: Record<string, string> = { todo: "待开始", in_progress: "进行中", blocked: "已阻塞", done: "已完成", skipped: "已跳过", pending_approval: "待批准" };
const issueLabels: Record<string, string> = { open: "待分析", analysis: "分析中", action: "整改中", verification: "待验证", closed: "已关闭" };
const lanes = [{ key: "task", label: "项目任务", caption: "开发与交付" }, { key: "action", label: "协同行动", caption: "会议、变更与整改" }, { key: "issue", label: "问题闭环", caption: "分析、整改与验证" }] as const;
function taskItem(task: ProjectTask): Item {
  return { id: task.id, title: task.title, stageId: task.stage_id, kind: task.kind === "task" ? "task" : "action", status: task.readiness === "waiting" && task.status === "todo" ? "等待前置" : taskLabels[task.status] ?? task.status, date: task.due_date, closed: ["done", "skipped"].includes(task.status), blocked: task.status === "blocked" || task.readiness === "blocked", dependencies: task.dependency_task_ids };
}
function issueItem(issue: ProjectIssue): Item {
  return { id: issue.id, title: issue.title, stageId: issue.stage_id, kind: "issue", status: issueLabels[issue.status] ?? issue.status, date: issue.target_date, closed: issue.status === "closed", blocked: false, dependencies: [] };
}
function itemHref(projectId: string, item: Item) {
  return `/projects?${new URLSearchParams({ project: projectId, tab: "work-items", entity_id: item.id })}`;
}
function stageState(project: Project, stage: ProjectStage) {
  if (stage.id === project.current_stage.id) return "当前阶段";
  return stage.sequence < project.current_stage.sequence ? "已走过" : "后续阶段";
}

export function ProjectStageBoard({ project, workItems, canViewWorkItems, loading = false, onPlan }: { project: Project; workItems: ProjectWorkItems | null; canViewWorkItems: boolean; loading?: boolean; onPlan: () => void }) {
  const [view, setView] = useState<"lanes" | "stages">("lanes");
  const [activeOnly, setActiveOnly] = useState(false);
  const [dependencies, setDependencies] = useState(false);
  const stages = [...project.workflow.stages].sort((a, b) => a.sequence - b.sequence);
  const stageIds = new Set(stages.map(stage => stage.id));
  const allItems = canViewWorkItems && workItems ? [...workItems.tasks.map(taskItem), ...workItems.issues.map(issueItem)] : [];
  const items = activeOnly ? allItems.filter(item => !item.closed) : allItems;
  // Missing/retired stage assignments are shown explicitly, never assigned to
  // the current stage by inference and never silently omitted by the filter.
  const unassigned = allItems.some(item => !item.stageId || !stageIds.has(item.stageId));
  const columns = [...stages.map(stage => ({ id: stage.id, name: stage.name, stage })), ...(unassigned ? [{ id: "unassigned", name: "未归阶段", stage: null }] : [])];
  const taskNames = new Map(workItems?.tasks.map(task => [task.id, task.title]) ?? []);
  const risks = canViewWorkItems && workItems ? workItems.risks.filter(risk => risk.status !== "closed") : [];
  const cellItems = (columnId: string, kind?: Item["kind"]) => items.filter(item => (!kind || item.kind === kind) && (columnId === "unassigned" ? !item.stageId || !stageIds.has(item.stageId) : item.stageId === columnId));
  const renderItem = (item: Item) => <li key={item.id}><Link prefetch={false} href={itemHref(project.id, item)} className="block rounded-md border bg-card p-3 transition-colors hover:border-primary/50 hover:bg-accent focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" aria-label={`打开${item.kind === "issue" ? "问题" : "任务"}：${item.title}`} title={item.title}><span className="line-clamp-2 text-left text-sm font-medium leading-5">{item.title}</span><span className="mt-2 flex flex-wrap items-center gap-x-2 gap-y-1 text-xs"><span className={cn("inline-flex items-center gap-1.5", item.blocked ? "text-destructive" : item.closed ? "text-success" : "text-muted-foreground")}>{item.closed ? <CheckIcon aria-hidden="true" size={12}/> : <CircleIcon aria-hidden="true" size={7} weight="fill"/>}{item.status}</span>{item.date && <span className="text-muted-foreground">{item.date.slice(5)} 到期</span>}</span>{dependencies && item.dependencies.length > 0 && <span className="mt-2 block border-t pt-2 text-xs leading-5 text-muted-foreground">前置：{item.dependencies.map(id => taskNames.get(id) ?? "未读取的前置任务").join("、")}</span>}</Link></li>;
  return <section aria-label="项目阶段 Timeline" className="min-w-0 space-y-3">
    <div className="flex flex-wrap items-center justify-between gap-3"><div><h2 className="text-base font-semibold">阶段泳道</h2><p className="mt-1 text-xs text-muted-foreground">{project.workflow.name} · v{project.workflow.version} · 阶段 {project.current_stage.sequence}/{stages.length}</p></div><div className="flex flex-wrap items-center gap-2">{canViewWorkItems && <Button type="button" size="sm" variant="ghost" onClick={onPlan}>办理计划与资源<ArrowRightIcon aria-hidden="true"/></Button>}<div className="flex rounded-md border bg-card p-0.5" role="group" aria-label="阶段展示方式"><Button type="button" size="sm" variant={view === "lanes" ? "secondary" : "ghost"} aria-pressed={view === "lanes"} onClick={() => setView("lanes")}><SquaresFourIcon aria-hidden="true"/>泳道</Button><Button type="button" size="sm" variant={view === "stages" ? "secondary" : "ghost"} aria-pressed={view === "stages"} onClick={() => setView("stages")}><RowsIcon aria-hidden="true"/>阶段列表</Button></div></div></div>
    {canViewWorkItems && <div className="flex flex-wrap items-center gap-x-5 gap-y-2 text-xs text-muted-foreground"><p>横向看阶段，纵向看工作类型</p><label className="inline-flex min-h-8 cursor-pointer items-center gap-2"><input type="checkbox" checked={activeOnly} onChange={e => setActiveOnly(e.target.checked)}/>仅未完成</label><label className="inline-flex min-h-8 cursor-pointer items-center gap-2"><input type="checkbox" checked={dependencies} onChange={e => setDependencies(e.target.checked)}/>显示前置关系</label></div>}
    {view === "lanes" ? <div className="max-h-[560px] overflow-auto rounded-lg border bg-card" tabIndex={0} aria-label="可滚动的阶段泳道"><table className="w-full border-collapse text-left" style={{ minWidth: canViewWorkItems ? 120 + columns.length * 190 : stages.length * 190 }}><caption className="sr-only">真实项目阶段与按归属划分的任务、行动、问题；阶段位置不代表任务完成率。</caption><thead className="sticky top-0 z-20 bg-card"><tr>{canViewWorkItems && <th scope="col" className="sticky left-0 z-30 w-28 border-b border-r bg-card p-3 text-xs font-medium text-muted-foreground">工作类型</th>}{columns.map(column => <th key={column.id} scope="col" className={cn("min-w-44 border-b border-r p-4 last:border-r-0", column.stage?.id === project.current_stage.id && "bg-accent")}><span className="flex items-center justify-between gap-2"><span className="text-sm font-semibold">{column.name}</span>{column.stage && <span className={cn("shrink-0 text-[11px] font-normal", column.stage.id === project.current_stage.id ? "text-primary" : "text-muted-foreground")}>{stageState(project, column.stage)}</span>}</span>{column.stage?.description && <span className="mt-2 block max-w-64 truncate text-xs font-normal text-muted-foreground" title={column.stage.description}>{column.stage.description}</span>}</th>)}</tr></thead>{canViewWorkItems && <tbody>{!workItems ? <tr><td colSpan={columns.length + 1} className="p-8 text-center text-sm text-muted-foreground">{loading ? "正在读取阶段工作项…" : "工作项尚未读取，不能据此判断任务或问题数量。"}</td></tr> : lanes.map(lane => <tr key={lane.key}><th scope="row" className="sticky left-0 z-10 w-28 border-r border-t bg-card p-3 align-top"><span className="block text-xs font-medium">{lane.label}</span><span className="mt-1 block text-[11px] font-normal leading-5 text-muted-foreground">{lane.caption}</span></th>{columns.map(column => { const rows = cellItems(column.id, lane.key); return <td key={column.id} className={cn("border-r border-t p-3 align-top last:border-r-0", column.stage?.id === project.current_stage.id && "bg-accent/30")}><ul className="max-h-64 space-y-2 overflow-y-auto">{rows.map(renderItem)}</ul>{rows.length === 0 && <p className="py-3 text-xs text-muted-foreground">{activeOnly ? "无未完成事项" : "暂无事项"}</p>}</td>; })}</tr>)}</tbody>}</table></div> : <ol className="divide-y rounded-lg border bg-card">{columns.map(column => <li key={column.id} className={cn("flex flex-wrap items-start justify-between gap-3 px-4 py-4", column.stage?.id === project.current_stage.id && "bg-accent")}><div><p className="text-sm font-medium">{column.name}{column.stage && <span className="ml-3 text-xs font-normal text-muted-foreground">{stageState(project, column.stage)}</span>}</p>{column.stage?.description && <p className="mt-1 text-xs text-muted-foreground">{column.stage.description}</p>}</div>{canViewWorkItems && <span className="text-xs text-muted-foreground">{workItems ? `${cellItems(column.id).length} ${activeOnly ? "项未完成" : "项工作"}` : "数量未读取"}</span>}</li>)}</ol>}
    {canViewWorkItems && workItems && <div className="flex flex-wrap items-start gap-x-4 gap-y-2 border-b pb-3 text-xs"><span className="shrink-0 font-medium">跨阶段风险</span>{risks.length === 0 ? <span className="text-muted-foreground">当前无开放风险</span> : <><span className="text-muted-foreground">{risks.length} 项开放</span>{risks.slice(0, 3).map(risk => <Link prefetch={false} key={risk.id} className="max-w-full truncate text-primary underline-offset-4 hover:underline" href={`/projects?${new URLSearchParams({ project: project.id, tab: "work-items", entity_id: risk.id })}`}>{risk.title}</Link>)}</>}</div>}
    <p className="text-xs text-muted-foreground">按真实归属展示；阶段位置不代表完成率。具体排期与资源安排在“计划”中查看。</p>
  </section>;
}
