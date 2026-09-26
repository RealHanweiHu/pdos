import dynamic from "next/dynamic";
import { DeferredPanelLoading, withDeferredPanelBoundary } from "@/components/deferred-panel-loading";

import { ContextKnowledge } from "@/components/knowledge/context-knowledge";

import { useRef, useState } from "react";

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
import { QualityResponsibilityLanding, SpecificationResponsibilityLanding } from "@/components/quality/quality-responsibility";

import type {
  Complaint,
  ComplaintCreateInput,
  NcrCreateInput,
  NcrDetail,
} from "@/components/quality/quality-types";

import type { ProjectFormValues, ProjectSubmissionResult } from "./project-form";
import { ProjectList, projectStatusLabels } from "./project-list";
import { ProjectIntake } from "./project-intake";
import { OpenApiAccess } from "./open-api-access";
import { ProjectWebhooks } from "./project-webhooks";
import { ValueMeasurement } from "./value-measurement";
import { AuditEvidenceExports } from "./audit-evidence-exports";
import { CustomerReportPackages } from "./customer-report-packages";
import { ProjectReportExports } from "./project-report-exports";
import { ProjectOverview } from "./project-overview";
import { ProjectProcessGuide } from "./project-process-guide";
import { ProjectTimeline } from "./project-timeline";
import type { Project } from "./project-types";
import type { ProjectActivity } from "./project-activity";

import { CostFreezeLanding } from "./cost-freeze-landing";

import { ProjectIdDesign } from "./project-id-design";
import { IdHandoffLanding } from "./id-handoff-landing";
import { IdFreezeRequestLanding } from "./id-freeze-request-landing";

import { ProjectTemplatePanel } from "./project-template-panel";
import { ProjectCompletionPanel } from "./project-completion-panel";

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

const EngineeringReviewPackages = withDeferredPanelBoundary(dynamic(() => import("@/components/product-engineering/engineering-review-packages").then(module => module.EngineeringReviewPackages), { loading: DeferredPanelLoading }));
const LivingFmea = withDeferredPanelBoundary(dynamic(() => import("@/components/quality/living-fmea").then(module => module.LivingFmea), { loading: DeferredPanelLoading }));
const QualityPanel = withDeferredPanelBoundary(dynamic(() => import("@/components/quality/quality-panel").then(module => module.QualityPanel), { loading: DeferredPanelLoading }));
const ProjectDocumentPanel = withDeferredPanelBoundary(dynamic(() => import("./project-document-panel").then(module => module.ProjectDocumentPanel), { loading: DeferredPanelLoading }));
const ProjectGatePanel = withDeferredPanelBoundary(dynamic(() => import("./project-gate-panel").then(module => module.ProjectGatePanel), { loading: DeferredPanelLoading }));
const ProjectChangePanel = withDeferredPanelBoundary(dynamic(() => import("./project-change-panel").then(module => module.ProjectChangePanel), { loading: DeferredPanelLoading }));
const ProjectCustomerChangePanel = withDeferredPanelBoundary(dynamic(() => import("./project-customer-change-panel").then(module => module.ProjectCustomerChangePanel), { loading: DeferredPanelLoading }));
const ProjectDecisionPanel = withDeferredPanelBoundary(dynamic(() => import("./project-decision-panel").then(module => module.ProjectDecisionPanel), { loading: DeferredPanelLoading }));
const ProjectDeliverableCheckPanel = withDeferredPanelBoundary(dynamic(() => import("./project-deliverable-check-panel").then(module => module.ProjectDeliverableCheckPanel), { loading: DeferredPanelLoading }));
const SupplyImports = withDeferredPanelBoundary(dynamic(() => import("./supply-imports").then(module => module.SupplyImports), { loading: DeferredPanelLoading }));
const CostImports = withDeferredPanelBoundary(dynamic(() => import("./cost-imports").then(module => module.CostImports), { loading: DeferredPanelLoading }));
const CostRollups = withDeferredPanelBoundary(dynamic(() => import("./cost-rollups").then(module => module.CostRollups), { loading: DeferredPanelLoading }));
const CostInputs = withDeferredPanelBoundary(dynamic(() => import("./cost-inputs").then(module => module.CostInputs), { loading: DeferredPanelLoading }));
const SupplierEngineering = withDeferredPanelBoundary(dynamic(() => import("./supplier-engineering").then(module => module.SupplierEngineering), { loading: DeferredPanelLoading }));
const SupplierCompliance = withDeferredPanelBoundary(dynamic(() => import("./supplier-compliance").then(module => module.SupplierCompliance), { loading: DeferredPanelLoading }));
const ToolingRounds = withDeferredPanelBoundary(dynamic(() => import("./tooling-rounds").then(module => module.ToolingRounds), { loading: DeferredPanelLoading }));
const SupplierNoticeWatches = withDeferredPanelBoundary(dynamic(() => import("./supplier-notice-watches").then(module => module.SupplierNoticeWatches), { loading: DeferredPanelLoading }));
const SupplierRecoveryPreparation = withDeferredPanelBoundary(dynamic(() => import("./supplier-recovery-preparation").then(module => module.SupplierRecoveryPreparation), { loading: DeferredPanelLoading }));
const MeetingRecurrences = withDeferredPanelBoundary(dynamic(() => import("./meeting-recurrences").then(module => module.MeetingRecurrences), { loading: DeferredPanelLoading }));
const MeetingRecurrenceRosterLanding = withDeferredPanelBoundary(dynamic(() => import("./meeting-recurrence-roster").then(module => module.MeetingRecurrenceRosterLanding), { loading: DeferredPanelLoading }));
const ProjectMeetings = withDeferredPanelBoundary(dynamic(() => import("./project-retrospectives").then(module => module.ProjectMeetings), { loading: DeferredPanelLoading }));
const ProjectPlanPanel = withDeferredPanelBoundary(dynamic(() => import("./project-plan-panel").then(module => module.ProjectPlanPanel), { loading: DeferredPanelLoading }));
const ProjectNpiPanel = withDeferredPanelBoundary(dynamic(() => import("./project-npi-panel").then(module => module.ProjectNpiPanel), { loading: DeferredPanelLoading }));

/**
 * Project workspace tabs (D9/D31): nine manufacturing business domains rather
 * than one tab per database table. Links minted before this regrouping still
 * work through LEGACY_TAB_ALIASES.
 */
export type ProjectWorkspaceTab =
  | "overview"
  | "plan"
  | "work-items"
  | "materials"
  | "engineering"
  | "decisions"
  | "gates"
  | "quality"
  | "documents";

export const LEGACY_TAB_ALIASES: Record<string, ProjectWorkspaceTab> = {
  timeline: "overview",
  "ai-chat": "overview",
  tasks: "work-items",
  issues: "work-items",
  risks: "work-items",
  "product-engineering": "engineering",
};

export function resolveTab(raw: string | null, search?: URLSearchParams, hash = ""): ProjectWorkspaceTab | null {
  // Old receipts and shared links keep their original object selectors.
  // An explicit different business tab always wins over these legacy hints.
  if ((raw === null || raw === "overview") && (
    ["forecast", "commitment_node", "cross_proposal", "schedule_responsibility_node", "resource_allocation_id", "resource_reservation_id", "reservation_node_id", "reservation_owner_id"].some(key => !!search?.get(key)) ||
    (["execution", "baseline"].includes(search?.get("approval_request_kind") ?? "") && !!search?.get("approval_request_id")) ||
    (["execution", "baseline", "commitment"].includes(search?.get("approval_policy_kind") ?? "") && !!search?.get("approval_policy_id")) ||
    ["#schedule-forecasts", "#schedule-commitments", "#resource-reservations", "#cross-proposal-landing"].includes(hash) || /^#reservation-[0-9a-f-]{36}$/i.test(hash)
  )) return "plan";
  if (raw === null) return null;
  if (TAB_KEYS.has(raw as ProjectWorkspaceTab)) return raw as ProjectWorkspaceTab;
  return LEGACY_TAB_ALIASES[raw] ?? null;
}
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
  { key: "overview", label: "概览·控制塔" },
  { key: "plan", label: "计划·资源", internalOnly: true },
  { key: "work-items", label: "工作项", internalOnly: true },
  { key: "materials", label: "物料·供应", internalOnly: true },
  { key: "engineering", label: "工程·变更", internalOnly: true },
  { key: "decisions", label: "例会·决策", internalOnly: true },
  { key: "gates", label: "Gate·交付物", internalOnly: true },
  { key: "quality", label: "试制·测试·质量", internalOnly: true },
  { key: "documents", label: "文档·知识", internalOnly: true },
];

const TAB_KEYS = new Set<ProjectWorkspaceTab>(tabs.map((tab) => tab.key));

/**
 * Mirrors the server's CHANGE_APPROVE grant. Deciding an ECR is separate from
 * editing one so the person who analysed a change cannot also approve it; the
 * server enforces this and the panel simply does not offer what it would refuse.
 */
const CHANGE_APPROVER_ROLES = new Set(["owner", "admin", "project_manager"]);

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
  activityLoading,
  onRetryActivity,
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
  activityLoading: boolean;
  onRetryActivity: () => void;
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
  onTransitionIssue: (
    issue: ProjectIssue,
    toStatus: IssueStatus,
    extra?: { comment?: string; closure_evidence_ref?: string },
  ) => Promise<boolean>;
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
    canClose?: boolean;
    complaints: Complaint[] | null;
    detail: NcrDetail | null;
    error: string | null;
    loadState: WorkItemLoadState;
    onCreate: (input: ComplaintCreateInput) => Promise<boolean>;
    onRetry: () => void;
    onSelect: (complaint: Complaint) => void;
    onTriage: (complaint: Complaint, input: NcrCreateInput) => Promise<boolean>;
    onTransition?: (complaint: Complaint, input: import("@/components/quality/complaint-lifecycle").ComplaintTransition) => Promise<boolean>;
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
  const [projectListExpanded, setProjectListExpanded] = useState(false);
  const tabButtons = useRef<Partial<Record<ProjectWorkspaceTab, HTMLButtonElement | null>>>({});
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

      <div className="mt-6">
        {selectedProject ? (
          <div className="flex items-center justify-between gap-3 rounded-lg border bg-card px-4 py-2">
            <span className="truncate text-sm"><span className="mr-2 font-mono text-xs text-muted-foreground">{selectedProject.code}</span>{selectedProject.name}</span>
            <Button aria-controls="project-list-panel" aria-expanded={projectListExpanded} onClick={() => setProjectListExpanded((current) => !current)} variant="outline">
              {projectListExpanded ? "收起项目列表" : `切换项目（${projects.length}）`}
            </Button>
          </div>
        ) : null}
        {!selectedProject || projectListExpanded ? (
          <div className={selectedProject ? "mt-2" : undefined} id="project-list-panel">
            <ProjectList onSelect={(project) => { setProjectListExpanded(false); onSelect(project); }} projects={projects} selectedId={selectedProject?.id ?? null} />
          </div>
        ) : null}
      </div>

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
              {visibleTabs.map((tab, index) => (
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
                  onKeyDown={(event) => {
                    const nextIndex = event.key === "ArrowRight" ? (index + 1) % visibleTabs.length
                      : event.key === "ArrowLeft" ? (index + visibleTabs.length - 1) % visibleTabs.length
                        : event.key === "Home" ? 0
                          : event.key === "End" ? visibleTabs.length - 1 : null;
                    if (nextIndex === null) return;
                    event.preventDefault();
                    const next = visibleTabs[nextIndex];
                    onTabChange(next.key);
                    tabButtons.current[next.key]?.focus();
                  }}
                  ref={(element) => { tabButtons.current[tab.key] = element; }}
                  role="tab"
                  tabIndex={activeTab === tab.key ? 0 : -1}
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
            {activeTab === "overview" && canViewWorkItems && workItemState === "error" ? <WorkItemState onRetry={onRetryWorkItems} state={workItemState} /> : null}
            {activeTab === "overview" ? (
              <ProjectOverview
                canEdit={canEdit}
                canViewWorkItems={canViewWorkItems}
                key={`ProjectOverview:${selectedProject.id}`}
                onStageTransition={(stageId) => onStageTransition(selectedProject, stageId)}
                onStatusTransition={(status) => onStatusTransition(selectedProject, status)}
                onUpdate={(values) => onUpdate(selectedProject, values)}
                project={selectedProject}
                saving={saving}
                workItems={workItems}
              />
            ) : null}
            {activeTab === "overview" && canViewWorkItems && <section className="flex flex-wrap items-center justify-between gap-3 rounded-lg border bg-card p-4"><div><h3 className="font-semibold">计划与资源</h3><p className="mt-1 text-sm text-muted-foreground">正式计划、实际进展、预测、承诺与资源预约集中办理。</p></div><Button type="button" variant="outline" onClick={() => onTabChange("plan")}>办理计划与资源</Button></section>}
            {activeTab === "overview" && <ProjectReportExports key={`ProjectReportExports:${selectedProject.id}`} projectId={selectedProject.id}/>}
            {activeTab === "overview" && <CustomerReportPackages key={`CustomerReportPackages:${selectedProject.id}`} projectId={selectedProject.id}/>}
            {activeTab === "overview" && <AuditEvidenceExports key={`AuditEvidenceExports:${selectedProject.id}`} projectId={selectedProject.id}/>}
            {activeTab === "overview" && <OpenApiAccess key={`OpenApiAccess:${selectedProject.id}`} projectId={selectedProject.id}/>}
            {activeTab === "overview" && <ProjectWebhooks key={`ProjectWebhooks:${selectedProject.id}`} projectId={selectedProject.id}/>}
            {activeTab === "overview" && canViewWorkItems && <ValueMeasurement key={`ValueMeasurement:${selectedProject.id}`} projectId={selectedProject.id}/>}
            {activeTab === "overview" && canViewWorkItems && <ContextKnowledge key={`ContextKnowledge:${selectedProject.id}`} projectId={selectedProject.id} contextKind="project_kickoff" entityId={selectedProject.id} />}
            {activeTab === "overview" && canViewWorkItems ? (
              <>
                <ProjectIntake key={`intake:${selectedProject.id}`} projectId={selectedProject.id} />
                <ProjectTemplatePanel key={`template:${selectedProject.id}`} projectId={selectedProject.id} stageCode={selectedProject.current_stage.code} canManage={["owner", "admin", "project_manager"].includes(identity.user.role)} />
                <IdHandoffLanding projectId={selectedProject.id} />
                <IdFreezeRequestLanding projectId={selectedProject.id} />
                <ProjectIdDesign key={`id-design:${selectedProject.id}`} projectId={selectedProject.id} />
                <SpecificationResponsibilityLanding projectId={selectedProject.id}/>
                <ProjectCompletionPanel key={`ProjectCompletionPanel:${selectedProject.id}`} projectId={selectedProject.id} userId={identity.user.id} canManage={["owner", "admin", "project_manager"].includes(identity.user.role)} />
                <div className="mt-6">
                  <ProjectProcessGuide project={selectedProject} onOpen={onTabChange} />
                </div>
                <div className="mt-6 border-t pt-6">
                  <ProjectTimeline
                    activities={activities}
                    activityError={activityError}
                    loading={activityLoading}
                    onRetry={onRetryActivity}
                    highlightedEntityId={highlightedEntityId}
                    highlightedEventId={highlightedEventId}
                    project={selectedProject}
                  />
                </div>
                <div className="mt-6 border-t pt-6">
                  <ProjectAiChat key={`ProjectAiChat:${selectedProject.id}`} projectId={selectedProject.id} />
                </div>
              </>
            ) : null}
            {activeTab === "plan" && canViewWorkItems && <ProjectPlanPanel key={selectedProject.id} projectId={selectedProject.id} userId={identity.user.id}/>}
            {activeTab === "work-items" && workItemUnavailable ? <WorkItemState onRetry={onRetryWorkItems} state={workItemState} /> : null}
            {activeTab === "work-items" && workItems ? (
              <div className="space-y-6">
                <TaskPanel key={`${selectedProject.id}:${highlightedEntityId ?? ""}`} busy={workItemBusy} focusedTaskId={highlightedEntityId} onCreate={onCreateTask} onTransition={onTransitionTask} stages={selectedProject.workflow.stages} tasks={workItems.tasks} />
                <IssuePanel busy={workItemBusy} issues={workItems.issues} focusedIssueId={highlightedEntityId} onCreate={onCreateIssue} onTransition={onTransitionIssue} />
                <RiskPanel busy={workItemBusy} onCreate={onCreateRisk} onTransition={onTransitionRisk} risks={workItems.risks} />
              </div>
            ) : null}
            {activeTab === "materials" ? (
              <>
              <CostFreezeLanding projectId={selectedProject.id} canEdit={productEngineering.canEdit} />
              <SupplyImports key={`SupplyImports:${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} />
              <CostImports key={`cost-import-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} />
              <CostInputs key={`cost-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} />
              <CostRollups key={`cost-rollup-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} />
              <SupplierEngineering key={`engineering-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} />
              <SupplierCompliance key={`compliance-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} />
              <ToolingRounds key={`tooling-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} />
              <SupplierRecoveryPreparation key={`supplier-recovery-${selectedProject.id}`} projectId={selectedProject.id} />
              <SupplierNoticeWatches key={`supplier-notices-${selectedProject.id}`} projectId={selectedProject.id} />
              </>
            ) : null}
            {activeTab === "engineering" ? (
              <div className="space-y-8">
                <EngineeringReviewPackages key={`EngineeringReviewPackages:${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} />
                <ProductEngineeringPanel {...productEngineering} />
                {/* The tab is named 「工程·变更」; the ECR chain had been in the
                    backend since V1 with no surface to reach it from. */}
                <ProjectChangePanel
                  key={`ProjectChangePanel:${selectedProject.id}`}
                  canApprove={CHANGE_APPROVER_ROLES.has(identity.user.role)}
                  canEdit={canEdit}
                  projectId={selectedProject.id}
                />
                {/* A customer asking for a change and engineering deciding to
                    change something are different events with different owners,
                    so the CCR list stays its own section. */}
                <ProjectCustomerChangePanel
                  key={`ccr-${selectedProject.id}`}
                  canApprove={CHANGE_APPROVER_ROLES.has(identity.user.role)}
                  canEdit={canEdit}
                  currentUserId={identity.user.id}
                  projectId={selectedProject.id}
                />
              </div>
            ) : null}
            {activeTab === "decisions" ? (
              <>
                <MeetingRecurrences key={`recurrences:${selectedProject.id}`} projectId={selectedProject.id}/>
                <MeetingRecurrenceRosterLanding projectId={selectedProject.id}/>
                <ProjectMeetings key={`retrospectives:${selectedProject.id}`} projectId={selectedProject.id} canManage={["owner", "admin", "project_manager"].includes(identity.user.role)} canUpload={["owner", "admin", "project_manager", "engineer", "quality"].includes(identity.user.role)} />
              <ProjectDecisionPanel
                key={`ProjectDecisionPanel:${selectedProject.id}`}
                canEdit={canEdit}
                projectId={selectedProject.id}
              />
              </>
            ) : null}
            {activeTab === "gates" ? (
              <div className="space-y-8">
                <ProjectGatePanel
                  {...gateSurface}
                  actorUserId={identity.user.id}
                  projectId={selectedProject.id}
                  state={gateSurface.loadState}
                />
                {/* The other half of 「Gate·交付物」: the checklist the gate
                    blockers refer to had no surface of its own. */}
                <ProjectDeliverableCheckPanel
                  key={`ProjectDeliverableCheckPanel:${selectedProject.id}`}
                  canManage={gateSurface.canManage}
                  projectId={selectedProject.id}
                />
              </div>
            ) : null}
            {activeTab === "documents" ? (
              <ProjectDocumentPanel
                key={`${selectedProject.id}:${highlightedEntityId ?? ""}`}
                focusedDocumentId={highlightedEntityId}
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
              <div className="space-y-8">
                <ProjectNpiPanel
                  key={`ProjectNpiPanel:${selectedProject.id}`}
                  canEdit={canEdit}
                  canRecordTests={["owner", "admin", "project_manager", "engineer", "quality"].includes(identity.user.role)}
                  canEditMaterials={productEngineering.canEdit}
                  projectId={selectedProject.id}
                />
                <QualityResponsibilityLanding projectId={selectedProject.id}/>
                <QualityPanel
                  {...qualitySurface}
                  identityUserId={identity.user.id}
                />
                <LivingFmea key={`fmea:${selectedProject.id}`} projectId={selectedProject.id}/>
              </div>
            ) : null}

          </div>
        </section>
      ) : null}
    </WorkspaceShell>
  );
}
