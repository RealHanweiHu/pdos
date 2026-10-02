"use client";

import { useState } from "react";
import { cn } from "@/lib/utils";
import type { Project } from "./project-types";
import type { IssueTransitionExtra } from "./project-work-item-api";
import { IssuePanel, RiskPanel, TaskPanel } from "./project-work-items";
import type { IssueCreateInput, IssueStatus, ProjectIssue, ProjectRisk, ProjectTask, ProjectWorkItems, RiskCreateInput, RiskStatus, TaskCreateInput, TaskTransitionInput } from "./project-work-item-types";

export type ProjectWorkKind = "tasks" | "issues" | "risks";

export function ProjectWorkQueue({ project, workItems, focusedEntityId, initialKind, busy, onCreateTask, onCreateIssue, onCreateRisk, onTransitionTask, onTransitionIssue, onTransitionRisk, onIssueChanged }: {
  project: Project;
  workItems: ProjectWorkItems;
  focusedEntityId: string | null;
  initialKind?: ProjectWorkKind;
  busy: boolean;
  onCreateTask: (input: TaskCreateInput) => Promise<boolean>;
  onCreateIssue: (input: IssueCreateInput) => Promise<boolean>;
  onCreateRisk: (input: RiskCreateInput) => Promise<boolean>;
  onTransitionTask: (task: ProjectTask, input: TaskTransitionInput) => Promise<boolean>;
  onTransitionIssue: (issue: ProjectIssue, status: IssueStatus, extra?: IssueTransitionExtra) => Promise<boolean>;
  onTransitionRisk: (risk: ProjectRisk, status: RiskStatus) => Promise<boolean>;
  onIssueChanged?: () => Promise<void>;
}) {
  // A receipt or swimlane link opens the matching list without another choice.
  // Withdrawn Issues leave the current list. Their history reader verifies a
  // receipt ID with the server and quietly rejects IDs belonging to other kinds.
  const [kind, setKind] = useState<ProjectWorkKind>(() => workItems.issues.some(item => item.id === focusedEntityId) ? "issues" : workItems.risks.some(item => item.id === focusedEntityId) ? "risks" : workItems.tasks.some(item => item.id === focusedEntityId) ? "tasks" : initialKind ?? (focusedEntityId ? "issues" : "tasks"));
  const views: { key: ProjectWorkKind; label: string }[] = [{ key: "tasks", label: "任务" }, { key: "issues", label: "问题" }, { key: "risks", label: "风险" }];
  return <div className="space-y-4">
    <div aria-label="工作项类型" className="flex flex-wrap gap-1" role="group">{views.map(view => <button aria-label={`${view.label}，${workItems[view.key].length}项`} aria-pressed={kind === view.key} className={cn("min-h-11 rounded-md px-3 text-sm text-muted-foreground hover:bg-muted focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring", kind === view.key && "bg-muted font-medium text-foreground")} key={view.key} onClick={() => setKind(view.key)} type="button">{view.label}<span className="ml-2 tabular-nums">{workItems[view.key].length}</span></button>)}</div>
    {kind === "tasks" && <TaskPanel busy={busy} focusedTaskId={focusedEntityId} onCreate={onCreateTask} onTransition={onTransitionTask} stages={project.workflow.stages} tasks={workItems.tasks}/>}
    {kind === "issues" && <IssuePanel projectId={project.id} busy={busy} issues={workItems.issues} focusedIssueId={focusedEntityId} onCreate={onCreateIssue} onTransition={onTransitionIssue} onIssueChanged={onIssueChanged}/>}
    {kind === "risks" && <RiskPanel busy={busy} focusedRiskId={focusedEntityId} onCreate={onCreateRisk} onTransition={onTransitionRisk} risks={workItems.risks}/>}
  </div>;
}
