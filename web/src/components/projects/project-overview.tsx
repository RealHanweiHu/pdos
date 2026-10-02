"use client";

import { useState } from "react";
import Link from "next/link";
import { ArrowUpRight } from "@phosphor-icons/react";

import { Button } from "@/components/ui/button";

import { ProjectForm, type ProjectFormValues, type ProjectSubmissionResult } from "./project-form";
import type { Project } from "./project-types";
import type { ProjectWorkItems } from "./project-work-item-types";

export function ProjectOverview({
  canEdit,
  canViewWorkItems,
  onUpdate,
  project,
  saving,
  workItems,
}: {
  canEdit: boolean;
  canViewWorkItems: boolean;
  onUpdate: (values: ProjectFormValues) => Promise<ProjectSubmissionResult>;
  project: Project;
  saving: boolean;
  workItems: ProjectWorkItems | null;
}) {
  const [editing, setEditing] = useState(false);
  const activeTasks = workItems?.tasks.filter((task) => !["done", "skipped"].includes(task.status)).length;
  const openIssues = workItems?.issues.filter((issue) => issue.status !== "closed").length;
  const openRisks = workItems?.risks.filter((risk) => risk.status !== "closed").length;
  const pending = workItems ? [
    ...workItems.tasks.filter(task => !["done", "skipped"].includes(task.status)).map(task => ({ id: task.id, title: task.title, kind: "任务", date: task.due_date, attention: ["blocked", "waiting_approval"].includes(task.readiness) ? 1 : 0, state: task.readiness === "waiting" ? "等待前置" : task.readiness === "blocked" ? "已阻塞" : task.readiness === "waiting_approval" ? "待批准" : task.status === "in_progress" ? "进行中" : "待开始" })),
    ...workItems.issues.filter(issue => issue.status !== "closed").map(issue => ({ id: issue.id, title: issue.title, kind: "问题", date: issue.target_date, attention: ["critical", "high"].includes(issue.severity) ? 1 : 0, state: ({ open: "待分析", analysis: "分析中", action: "整改中", verification: "待验证", closed: "已关闭" })[issue.status] })),
    ...workItems.risks.filter(risk => ["open", "mitigating"].includes(risk.status)).map(risk => ({ id: risk.id, title: risk.title, kind: "风险", date: risk.target_date, attention: risk.score >= 15 ? 1 : 0, state: risk.status === "mitigating" ? "应对中" : "待处理" })),
  ].sort((a, b) => b.attention - a.attention || (a.date ?? "9999").localeCompare(b.date ?? "9999") || a.title.localeCompare(b.title)) : [];
  return (
    <section aria-label="项目概览" className="space-y-3 border-b pb-5">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1"><h3 className="sr-only">项目概览</h3><p className="max-w-3xl text-sm leading-6 text-muted-foreground">{project.description ?? "暂无项目描述"}</p></div>
        {canEdit && <Button size="sm" variant="outline" disabled={saving} onClick={() => setEditing(!editing)}>{editing ? "收起编辑" : "编辑项目"}</Button>}
      </div>
      <dl className="flex flex-wrap gap-x-6 gap-y-3 text-xs">
        <div><dt className="inline text-muted-foreground">开始日期</dt><dd className="ml-2 inline font-medium">{project.start_date ?? "未设置"}</dd></div>
        <div><dt className="inline text-muted-foreground">目标日期</dt><dd className="ml-2 inline font-medium">{project.target_date ?? "未设置"}</dd></div>
        {canViewWorkItems && <><div><dt className="inline text-muted-foreground">未完成任务</dt><dd className="ml-2 inline font-medium" data-metric="task">{activeTasks ?? "—"}</dd></div><div><dt className="inline text-muted-foreground">开放问题</dt><dd className="ml-2 inline font-medium" data-metric="issue">{openIssues ?? "—"}</dd></div><div><dt className="inline text-muted-foreground">开放风险</dt><dd className="ml-2 inline font-medium" data-metric="risk">{openRisks ?? "—"}</dd></div></>}
      </dl>
      {editing && canEdit && <div className="rounded-lg border bg-card p-4"><ProjectForm busy={saving} key={project.id} onCancel={() => setEditing(false)} onSubmit={async values => { const result = await onUpdate(values); if (result.ok) setEditing(false); return result; }} project={project}/></div>}
      {canViewWorkItems && workItems && <section aria-label="待推进事项" className="pt-5">
        <div className="mb-2 flex items-baseline justify-between gap-3"><h2 className="text-sm font-semibold">待推进事项</h2><span className="text-xs text-muted-foreground">{pending.length} 项</span></div>
        {pending.length === 0 ? <p className="py-3 text-sm text-muted-foreground">当前没有待推进事项。</p> : <ul className="divide-y">{pending.slice(0, 6).map(item => <li key={`${item.kind}:${item.id}`}><Link aria-label={`处理${item.kind}：${item.title}`} className="group flex min-h-14 flex-wrap items-center gap-x-4 gap-y-1 rounded-md px-2 py-3 text-sm hover:bg-muted/50 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" href={`/projects?${new URLSearchParams({ project: project.id, tab: "work-items", entity_id: item.id })}`} prefetch={false}><span className="min-w-0 flex-1"><span className="mr-2 text-xs text-muted-foreground">{item.kind}</span><span className="break-words font-medium">{item.title}</span></span><span className="text-xs text-muted-foreground">{item.state}{item.date && <span className="ml-3">{item.date}</span>}</span><ArrowUpRight aria-hidden="true" className="size-4 shrink-0 text-muted-foreground group-hover:text-foreground"/></Link></li>)}</ul>}
      </section>}
      {!canViewWorkItems && <p className="text-xs text-muted-foreground">外部成员仅可查看已授权的项目概览与阶段。</p>}
    </section>
  );
}
