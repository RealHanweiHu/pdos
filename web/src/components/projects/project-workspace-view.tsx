import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import { ProjectForm, type ProjectFormValues, type ProjectSubmissionResult } from "./project-form";
import { ProjectList } from "./project-list";
import { ProjectStatusActions } from "./project-status-actions";
import { ProjectTimeline } from "./project-timeline";
import type { Project } from "./project-types";

export function ProjectWorkspaceView({
  canEdit,
  errorMessage,
  identity,
  loggingOut,
  onCancelEdit,
  onLogout,
  onSelect,
  onStageTransition,
  onStatusTransition,
  onUpdate,
  projects,
  saving,
  selectedProject,
  statusMessage,
}: {
  canEdit: boolean;
  errorMessage: string | null;
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onCancelEdit: () => void;
  onLogout: () => void;
  onSelect: (project: Project) => void;
  onStageTransition: (project: Project, stageId: string) => void;
  onStatusTransition: (project: Project, status: Project["status"]) => void;
  onUpdate: (project: Project, values: ProjectFormValues) => Promise<ProjectSubmissionResult>;
  projects: Project[];
  saving: boolean;
  selectedProject: Project | null;
  statusMessage: string | null;
}) {
  return (
    <WorkspaceShell active="projects" identity={identity} loggingOut={loggingOut} onLogout={onLogout}>
      {statusMessage ? <p className="mb-4 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success" role="status">{statusMessage}</p> : null}
      {errorMessage ? <p className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{errorMessage}</p> : null}
      <div className="border-b pb-4">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">Execution</p>
        <h1 className="mt-1 text-lg font-semibold">项目工作区</h1>
        <p className="mt-1 text-sm text-muted-foreground">以项目状态与七阶段 Workflow 组织研发执行上下文。</p>
      </div>
      {selectedProject ? <div className="mt-6"><ProjectTimeline project={selectedProject} /></div> : null}
      <div className="mt-6 grid items-start gap-6 lg:grid-cols-[minmax(0,1fr)_384px]">
        <ProjectList onSelect={onSelect} projects={projects} selectedId={selectedProject?.id ?? null} />
        {selectedProject ? (
          <section aria-label="项目详情" className="rounded-lg border bg-card p-4">
            {canEdit && selectedProject.status !== "archived" ? (
              <ProjectForm busy={saving} key={selectedProject.id} onCancel={onCancelEdit} onSubmit={(values) => onUpdate(selectedProject, values)} project={selectedProject} />
            ) : (
              <div>
                <h2 className="font-semibold">{selectedProject.code} · {selectedProject.name}</h2>
                <p className="mt-2 text-sm text-muted-foreground">{selectedProject.description ?? "暂无项目描述"}</p>
                <dl className="mt-4 grid grid-cols-2 gap-3 text-xs">
                  <div><dt className="text-muted-foreground">当前阶段</dt><dd className="mt-1 font-medium">{selectedProject.current_stage.name}</dd></div>
                  <div><dt className="text-muted-foreground">目标日期</dt><dd className="mt-1 font-medium">{selectedProject.target_date ?? "未设置"}</dd></div>
                </dl>
              </div>
            )}
            {canEdit ? <ProjectStatusActions busy={saving} onStageTransition={(stageId) => onStageTransition(selectedProject, stageId)} onStatusTransition={(status) => onStatusTransition(selectedProject, status)} project={selectedProject} /> : null}
          </section>
        ) : null}
      </div>
    </WorkspaceShell>
  );
}
