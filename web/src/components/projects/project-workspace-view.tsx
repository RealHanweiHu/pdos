import { WorkspaceShell } from "@/components/workspace-shell";
import type { WorkspaceIdentity } from "@/components/workspace-types";
import { Button } from "@/components/ui/button";
import { cn } from "@/lib/utils";
import { ProjectAiChat } from "@/components/ai/project-ai-chat";
import {
  ProductEngineeringPanel,
  type ProductEngineeringLoadState,
} from "@/components/product-engineering/product-engineering-panel";
import type {
  DevelopmentBomCreateInput,
  ProductEngineeringRegister,
  SpecificationCreateInput,
} from "@/components/product-engineering/product-engineering-types";
import { QualityPanel } from "@/components/quality/quality-panel";
import type {
  Complaint,
  ComplaintCreateInput,
  NcrCreateInput,
  NcrDetail,
} from "@/components/quality/quality-types";

import type { ProjectFormValues, ProjectSubmissionResult } from "./project-form";
import { ProjectList, projectStatusLabels } from "./project-list";
import { ProjectOverview } from "./project-overview";
import { ProjectTimeline } from "./project-timeline";
import type { Project } from "./project-types";
import type { ProjectActivity } from "./project-activity";
import { ProjectDocumentPanel } from "./project-document-panel";
import { ProjectGatePanel } from "./project-gate-panel";
import type { ProjectDocument, ProjectGate } from "./project-gate-document-types";
import { IssuePanel, RiskPanel, TaskPanel } from "./project-work-items";
import type {
  IssueCreateInput,
  IssueStatus,
  ProjectIssue,
  ProjectRisk,
  ProjectTask,
  ProjectWorkItems,
  RiskCreateInput,
  RiskStatus,
  TaskCreateInput,
  TaskTransitionInput,
} from "./project-work-item-types";

export type ProjectWorkspaceTab =
  | "overview"
  | "timeline"
  | "tasks"
  | "issues"
  | "risks"
  | "product-engineering"
  | "gates"
  | "documents"
  | "quality"
  | "ai-chat";
export type WorkItemLoadState = "idle" | "loading" | "ready" | "error";

type ProductEngineeringWorkspaceProps = {
  busy: boolean;
  canEdit: boolean;
  error: string | null;
  loadState: ProductEngineeringLoadState;
  onCreateBom: (input: DevelopmentBomCreateInput) => Promise<boolean>;
  onCreateSpecification: (input: SpecificationCreateInput) => Promise<boolean>;
  onRetry: () => void;
  register: ProductEngineeringRegister | null;
  status: string | null;
};

const tabs: { key: ProjectWorkspaceTab; label: string; internalOnly?: boolean }[] = [
  { key: "overview", label: "概览" },
  { key: "timeline", label: "时间线" },
  { key: "tasks", label: "任务", internalOnly: true },
  { key: "issues", label: "问题", internalOnly: true },
  { key: "risks", label: "风险", internalOnly: true },
  { key: "product-engineering", label: "产品工程", internalOnly: true },
  { key: "gates", label: "Gate", internalOnly: true },
  { key: "documents", label: "文档", internalOnly: true },
  { key: "quality", label: "质量 / CAPA", internalOnly: true },
  { key: "ai-chat", label: "AI 对话", internalOnly: true },
];

function WorkItemState({ onRetry, state }: { onRetry: () => void; state: WorkItemLoadState }) {
  if (state === "loading" || state === "idle") {
    return <div className="rounded-lg border bg-card px-4 py-10 text-center text-sm text-muted-foreground">正在加载项目工作项…</div>;
  }
  if (state === "error") {
    return (
      <div className="rounded-lg border border-destructive/30 bg-destructive/5 px-4 py-8 text-center">
        <h3 className="font-semibold">工作项暂不可用</h3>
        <p className="mt-1 text-sm text-muted-foreground">读取失败不会被记作零任务或零风险。</p>
        <Button className="mt-4 h-11" onClick={onRetry} variant="outline">重新加载工作项</Button>
      </div>
    );
  }
  return null;
}

export function ProjectWorkspaceView({
  activeTab,
  activities,
  activityError,
  canEdit,
  canViewWorkItems,
  highlightedEntityId,
  highlightedEventId,
  errorMessage,
  identity,
  loggingOut,
  onCreateIssue,
  onCreateRisk,
  onCreateTask,
  onLogout,
  onRetryWorkItems,
  onSelect,
  onStageTransition,
  onStatusTransition,
  onTabChange,
  onTransitionIssue,
  onTransitionRisk,
  onTransitionTask,
  onUpdate,
  projects,
  productEngineering,
  gateSurface,
  documentSurface,
  qualitySurface,
  saving,
  selectedProject,
  statusMessage,
  workItemBusy,
  workItemError,
  workItemState,
  workItems,
}: {
  activeTab: ProjectWorkspaceTab;
  activities: ProjectActivity[];
  activityError: boolean;
  canEdit: boolean;
  canViewWorkItems: boolean;
  highlightedEntityId: string | null;
  highlightedEventId: number | null;
  errorMessage: string | null;
  identity: WorkspaceIdentity;
  loggingOut: boolean;
  onCreateIssue: (input: IssueCreateInput) => Promise<boolean>;
  onCreateRisk: (input: RiskCreateInput) => Promise<boolean>;
  onCreateTask: (input: TaskCreateInput) => Promise<boolean>;
  onLogout: () => void;
  onRetryWorkItems: () => void;
  onSelect: (project: Project) => void;
  onStageTransition: (project: Project, stageId: string) => void;
  onStatusTransition: (project: Project, status: Project["status"]) => void;
  onTabChange: (tab: ProjectWorkspaceTab) => void;
  onTransitionIssue: (issue: ProjectIssue, toStatus: IssueStatus) => Promise<boolean>;
  onTransitionRisk: (risk: ProjectRisk, toStatus: RiskStatus) => Promise<boolean>;
  onTransitionTask: (task: ProjectTask, input: TaskTransitionInput) => Promise<boolean>;
  onUpdate: (project: Project, values: ProjectFormValues) => Promise<ProjectSubmissionResult>;
  projects: Project[];
  productEngineering: ProductEngineeringWorkspaceProps;
  gateSurface: {
    actorRole: string;
    busy: boolean;
    canManage: boolean;
    error: string | null;
    gates: ProjectGate[] | null;
    loadState: WorkItemLoadState;
    onNavigate: (tab: ProjectWorkspaceTab) => void;
    onOpenRound: (gate: ProjectGate) => void;
    onRetry: () => void;
    onSignoff: (gate: ProjectGate, slot: "product" | "engineering" | "quality") => void;
  };
  documentSurface: {
    busy: boolean;
    canUpload: boolean;
    documents: ProjectDocument[] | null;
    error: string | null;
    loadState: WorkItemLoadState;
    onRetry: () => void;
    onUpload: (file: File, classification: string) => Promise<boolean>;
  };
  qualitySurface: {
    busy: boolean;
    canCreate: boolean;
    canManage: boolean;
    complaints: Complaint[] | null;
    detail: NcrDetail | null;
    error: string | null;
    loadState: WorkItemLoadState;
    onCreate: (input: ComplaintCreateInput) => Promise<boolean>;
    onRetry: () => void;
    onSelect: (complaint: Complaint) => void;
    onTriage: (complaint: Complaint, input: NcrCreateInput) => Promise<boolean>;
    selectedComplaint: Complaint | null;
  };
  saving: boolean;
  selectedProject: Project | null;
  statusMessage: string | null;
  workItemBusy: boolean;
  workItemError: string | null;
  workItemState: WorkItemLoadState;
  workItems: ProjectWorkItems | null;
}) {
  const visibleTabs = tabs.filter((tab) => !tab.internalOnly || canViewWorkItems);
  const workItemUnavailable = canViewWorkItems && workItemState !== "ready";
  const currentStageProgress = selectedProject
    ? Math.round((selectedProject.current_stage.sequence / selectedProject.workflow.stages.length) * 100)
    : 0;

  return (
    <WorkspaceShell active="projects" identity={identity} loggingOut={loggingOut} onLogout={onLogout}>
      {statusMessage ? <p className="mb-4 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success" role="status">{statusMessage}</p> : null}
      {errorMessage ? <p className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{errorMessage}</p> : null}
      <div className="border-b pb-4">
        <p className="font-mono text-[11px] font-semibold uppercase tracking-[0.16em] text-primary">Execution</p>
        <h1 className="mt-1 text-lg font-semibold">项目工作区</h1>
        <p className="mt-1 text-sm text-muted-foreground">项目上下文、七阶段 Timeline 与可执行工作项在同一工作区闭环。</p>
      </div>

      <div className="mt-6"><ProjectList onSelect={onSelect} projects={projects} selectedId={selectedProject?.id ?? null} /></div>

      {selectedProject ? (
        <section aria-label="项目详情" className="mt-6 min-w-0 overflow-hidden rounded-lg border bg-card">
          <div className="px-4 pt-4 sm:px-5">
            <div className="flex flex-wrap items-start gap-2">
              <div className="min-w-0 flex-1">
                <p className="font-mono text-[11px] text-primary">{selectedProject.code}</p>
                <h2 className="mt-1 truncate text-lg font-semibold">{selectedProject.name}</h2>
              </div>
              <span className="rounded-full border bg-muted px-2 py-1 text-[11px] text-muted-foreground">{projectStatusLabels[selectedProject.status]}</span>
              <span className="rounded-full border bg-muted px-2 py-1 text-[11px] text-muted-foreground">{selectedProject.current_stage.name}</span>
            </div>
            <div className="mt-4 flex items-center gap-3">
              <div aria-label={`阶段进度 ${currentStageProgress}%`} className="h-1.5 min-w-0 flex-1 overflow-hidden rounded-full bg-muted" role="progressbar" aria-valuemax={100} aria-valuemin={0} aria-valuenow={currentStageProgress}>
                <span className="block h-full rounded-full bg-primary" style={{ width: `${currentStageProgress}%` }} />
              </div>
              <span className="font-mono text-[11px] text-muted-foreground">P{selectedProject.current_stage.sequence}/{selectedProject.workflow.stages.length}</span>
            </div>
          </div>
          <div className="mt-4 overflow-x-auto border-t" role="tablist" aria-label="项目工作区标签">
            <div className="flex min-w-max px-2 sm:px-4">
              {visibleTabs.map((tab) => (
                <button
                  aria-controls={`project-panel-${tab.key}`}
                  aria-selected={activeTab === tab.key}
                  className={cn(
                    "min-h-11 border-b-2 border-transparent px-3 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/20",
                    activeTab === tab.key && "border-primary font-medium text-primary",
                  )}
                  id={`project-tab-${tab.key}`}
                  key={tab.key}
                  onClick={() => onTabChange(tab.key)}
                  role="tab"
                  type="button"
                >
                  {tab.label}
                </button>
              ))}
            </div>
          </div>
          <div
            aria-labelledby={`project-tab-${activeTab}`}
            className="min-w-0 bg-background p-4 sm:p-5"
            id={`project-panel-${activeTab}`}
            role="tabpanel"
          >
            {workItemError ? <p className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{workItemError}</p> : null}
            {activeTab === "overview" ? (
              <ProjectOverview
                canEdit={canEdit}
                canViewWorkItems={canViewWorkItems}
                key={selectedProject.id}
                onStageTransition={(stageId) => onStageTransition(selectedProject, stageId)}
                onStatusTransition={(status) => onStatusTransition(selectedProject, status)}
                onUpdate={(values) => onUpdate(selectedProject, values)}
                project={selectedProject}
                saving={saving}
                workItems={workItems}
              />
            ) : null}
            {activeTab === "timeline" ? <ProjectTimeline activities={activities} activityError={activityError} highlightedEntityId={highlightedEntityId} highlightedEventId={highlightedEventId} project={selectedProject} /> : null}
            {activeTab === "tasks" && workItemUnavailable ? <WorkItemState onRetry={onRetryWorkItems} state={workItemState} /> : null}
            {activeTab === "tasks" && workItems ? <TaskPanel busy={workItemBusy} onCreate={onCreateTask} onTransition={onTransitionTask} stages={selectedProject.workflow.stages} tasks={workItems.tasks} /> : null}
            {activeTab === "issues" && workItemUnavailable ? <WorkItemState onRetry={onRetryWorkItems} state={workItemState} /> : null}
            {activeTab === "issues" && workItems ? <IssuePanel busy={workItemBusy} issues={workItems.issues} onCreate={onCreateIssue} onTransition={onTransitionIssue} /> : null}
            {activeTab === "risks" && workItemUnavailable ? <WorkItemState onRetry={onRetryWorkItems} state={workItemState} /> : null}
            {activeTab === "risks" && workItems ? <RiskPanel busy={workItemBusy} onCreate={onCreateRisk} onTransition={onTransitionRisk} risks={workItems.risks} /> : null}
            {activeTab === "product-engineering" ? (
              <ProductEngineeringPanel {...productEngineering} />
            ) : null}
            {activeTab === "gates" ? (
              <ProjectGatePanel
                {...gateSurface}
                state={gateSurface.loadState}
              />
            ) : null}
            {activeTab === "documents" ? (
              <ProjectDocumentPanel
                busy={documentSurface.busy}
                canUpload={documentSurface.canUpload}
                documents={documentSurface.documents}
                error={documentSurface.error}
                onRetry={documentSurface.onRetry}
                onUpload={documentSurface.onUpload}
                state={documentSurface.loadState}
              />
            ) : null}
            {activeTab === "quality" ? (
              <QualityPanel
                {...qualitySurface}
                identityUserId={identity.user.id}
              />
            ) : null}
            {activeTab === "ai-chat" ? <ProjectAiChat key={selectedProject.id} projectId={selectedProject.id} /> : null}
          </div>
        </section>
      ) : null}
    </WorkspaceShell>
  );
}
