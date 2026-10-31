import { ProjectForm, type ProjectFormValues, type ProjectSubmissionResult } from "./project-form";
import { ProjectStatusActions } from "./project-status-actions";
import { projectStatusLabels } from "./project-list";
import { ProjectMembersCard } from "./project-members-card";
import { isTaskOpen, isTaskOverdue, localIsoDate } from "./project-task-planning";
import type { Project } from "./project-types";
import type { ProjectMember, ProjectWorkItems } from "./project-work-item-types";

export function ProjectOverview({
  canEdit,
  canManageMembers,
  canViewWorkItems,
  currentUserId,
  onCancelEdit,
  onMembersChange,
  onStageTransition,
  onStatusTransition,
  onUpdate,
  project,
  saving,
  workItems,
}: {
  canEdit: boolean;
  canManageMembers: boolean;
  canViewWorkItems: boolean;
  currentUserId: string;
  onCancelEdit: () => void;
  onMembersChange: (members: ProjectMember[]) => void;
  onStageTransition: (stageId: string) => void;
  onStatusTransition: (status: Project["status"]) => void;
  onUpdate: (values: ProjectFormValues) => Promise<ProjectSubmissionResult>;
  project: Project;
  saving: boolean;
  workItems: ProjectWorkItems | null;
}) {
  const today = localIsoDate();
  const openTasks = workItems?.tasks.filter(isTaskOpen).length;
  const overdueTasks = workItems?.tasks.filter((task) => isTaskOverdue(task, today)).length ?? 0;
  const openIssues = workItems?.issues.filter((issue) => issue.status !== "closed").length;
  const openRisks = workItems?.risks.filter((risk) => risk.status !== "closed").length;
  return (
    <div className="grid items-start gap-4 lg:grid-cols-[minmax(0,1fr)_320px]">
      <section aria-label="项目概览" className="rounded-lg border bg-card p-4">
        <div className="flex flex-wrap items-start justify-between gap-3 border-b pb-4">
          <div>
            <h3 className="font-semibold">项目概览</h3>
            <p className="mt-1 max-w-2xl text-sm text-muted-foreground">{project.description ?? "暂无项目描述"}</p>
          </div>
          <span className="rounded-full border bg-muted px-2 py-1 text-[11px] font-medium text-muted-foreground">{projectStatusLabels[project.status]}</span>
        </div>
        <dl className="grid gap-4 py-4 text-xs sm:grid-cols-3">
          <div><dt className="text-muted-foreground">当前阶段</dt><dd className="mt-1 font-medium">{project.current_stage.name}</dd></div>
          <div><dt className="text-muted-foreground">开始日期</dt><dd className="mt-1 font-mono">{project.start_date ?? "未设置"}</dd></div>
          <div><dt className="text-muted-foreground">目标日期</dt><dd className="mt-1 font-mono">{project.target_date ?? "未设置"}</dd></div>
        </dl>
        {canEdit ? (
          <div className="border-t pt-4">
            <ProjectForm busy={saving} key={project.id} onCancel={onCancelEdit} onSubmit={onUpdate} project={project} />
            <ProjectStatusActions busy={saving} onStageTransition={onStageTransition} onStatusTransition={onStatusTransition} project={project} />
          </div>
        ) : null}
      </section>
      <aside className="space-y-4">
        {canViewWorkItems ? (
          <section aria-label="工作项汇总" className="overflow-hidden rounded-lg border bg-card">
            <h3 className="border-b px-4 py-3 font-semibold">执行快照</h3>
            <div className="grid grid-cols-3 divide-x py-4 text-center">
              <div><strong className="font-mono text-2xl" data-metric="task">{openTasks ?? "—"}</strong><p className="mt-1 text-[11px] text-muted-foreground">未完成任务</p></div>
              <div><strong className="font-mono text-2xl" data-metric="issue">{openIssues ?? "—"}</strong><p className="mt-1 text-[11px] text-muted-foreground">开放问题</p></div>
              <div><strong className="font-mono text-2xl" data-metric="risk">{openRisks ?? "—"}</strong><p className="mt-1 text-[11px] text-muted-foreground">开放风险</p></div>
            </div>
            {overdueTasks > 0 ? (
              <p className="border-t px-4 py-2 text-xs font-medium text-destructive" data-metric="overdue-task">
                其中 {overdueTasks} 项任务已逾期
              </p>
            ) : null}
          </section>
        ) : null}
        {canViewWorkItems && workItems ? (
          <ProjectMembersCard
            canManage={canManageMembers}
            currentUserId={currentUserId}
            members={workItems.members}
            onMembersChange={onMembersChange}
            ownerUserId={project.owner_user_id}
            projectId={project.id}
          />
        ) : null}
        {!canViewWorkItems ? (
          <section className="rounded-lg border bg-card p-4">
            <h3 className="font-semibold">成员视图</h3>
            <p className="mt-1 text-xs leading-5 text-muted-foreground">外部成员仅可查看已授权的项目概览与阶段时间线。</p>
          </section>
        ) : null}
        <section className="rounded-lg border bg-card p-4">
          <h3 className="font-semibold">Workflow</h3>
          <dl className="mt-3 space-y-3 text-xs">
            <div className="flex justify-between gap-4"><dt className="text-muted-foreground">模板</dt><dd className="text-right font-medium">{project.workflow.name}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted-foreground">版本</dt><dd className="font-mono">v{project.workflow.version}</dd></div>
            <div className="flex justify-between gap-4"><dt className="text-muted-foreground">阶段</dt><dd className="font-mono">{project.current_stage.sequence} / {project.workflow.stages.length}</dd></div>
          </dl>
        </section>
      </aside>
    </div>
  );
}
