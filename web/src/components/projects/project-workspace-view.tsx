import dynamic from "next/dynamic";
import { DeferredPanelLoading, withDeferredPanelBoundary } from "@/components/deferred-panel-loading";

import { useRef, useState } from "react";
import { Gear } from "@phosphor-icons/react";

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
import { ProjectOverview } from "./project-overview";
import { ProjectStatusActions } from "./project-status-actions";
import { ProjectTimeline } from "./project-timeline";
import { ProjectStageBoard } from "./project-stage-board";
import { ProjectManagementPanel } from "./project-management-panel";
import type { Project } from "./project-types";
import type { ProjectActivity } from "./project-activity";

import { CostFreezeLanding } from "./cost-freeze-landing";

import { ProjectIdDesign } from "./project-id-design";
import { IdHandoffLanding } from "./id-handoff-landing";
import { IdFreezeRequestLanding } from "./id-freeze-request-landing";


import type { ProjectDocument, ProjectGate } from "./project-gate-document-types";
import { ProjectWorkQueue, type ProjectWorkKind } from "./project-work-queue";
import { ProjectTaskWorkspace } from "./project-task-workspace";
import { configuredProjectTab, useWorkPerspective } from "@/components/workspace-experience";
import { ExternalProjectResponses } from "./external-project-responses";
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
 * Daily navigation follows the project workflow. Domain routes remain stable
 * for object receipts and contextual work; background services aren't tabs.
 */
export type ProjectWorkspaceTab =
  | "overview"
  | "stages"
  | "plan"
  | "work-items"
  | "materials"
  | "engineering"
  | "decisions"
  | "gates"
  | "quality"
  | "documents"
  | "management"
  | "conversation";

export const LEGACY_TAB_ALIASES: Record<string, ProjectWorkspaceTab> = {
  timeline: "stages",
  "ai-chat": "conversation",
  tasks: "work-items",
  issues: "work-items",
  risks: "work-items",
  "product-engineering": "engineering",
  npi: "quality",
};

export function resolveTab(raw: string | null, search?: URLSearchParams, hash = ""): ProjectWorkspaceTab | null {
  if (raw === "timeline" && (search?.get("event_id") || search?.get("entity_id") || /^#event-\d+$/.test(hash))) return "overview";
  // Old receipts and shared links keep their original object selectors.
  // An explicit different business tab always wins over these legacy hints.
  if ((raw === null || raw === "overview") && (
    ["forecast", "commitment_node", "cross_proposal", "schedule_responsibility_node", "resource_allocation_id", "resource_reservation_id", "reservation_node_id", "reservation_owner_id"].some(key => !!search?.get(key)) ||
    (["execution", "baseline"].includes(search?.get("approval_request_kind") ?? "") && !!search?.get("approval_request_id")) ||
    (["execution", "baseline", "commitment"].includes(search?.get("approval_policy_kind") ?? "") && !!search?.get("approval_policy_id")) ||
    ["#schedule-forecasts", "#schedule-commitments", "#resource-reservations", "#cross-proposal-landing"].includes(hash) || /^#reservation-[0-9a-f-]{36}$/i.test(hash)
  )) return "plan";
  if ((raw === null || raw === "overview") && ["completion_item", "intake_proposal", "intake_decision"].some(key => !!search?.get(key))) return "management";
  if ((raw === null || raw === "overview") && ["id_handoff", "id_freeze_request", "id_revision", "specification_owner_id"].some(key => !!search?.get(key))) return "engineering";
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
  { key: "overview", label: "总览" },
  { key: "stages", label: "项目阶段" },
  { key: "work-items", label: "工作项", internalOnly: true },
  { key: "plan", label: "计划", internalOnly: true },
  { key: "engineering", label: "工程·变更", internalOnly: true },
  { key: "quality", label: "试制·测试·质量", internalOnly: true },
  { key: "materials", label: "物料·供应", internalOnly: true },
  { key: "gates", label: "评审与交付", internalOnly: true },
  { key: "documents", label: "资料与协作", internalOnly: true },
  { key: "decisions", label: "例会与决策", internalOnly: true },
];
const workViews: { key: ProjectWorkspaceTab; label: string }[] = [
  { key: "work-items", label: "工作清单" },
  { key: "engineering", label: "工程·变更" },
  { key: "quality", label: "试制·测试·质量" },
  { key: "materials", label: "物料·供应" },
];
const collaborationViews: { key: ProjectWorkspaceTab; label: string }[] = [
  { key: "documents", label: "项目资料" },
  { key: "decisions", label: "例会与决策" },
];
const perspectiveTabOrder: Record<string, ProjectWorkspaceTab[]> = {
  personal: ["work-items", "overview", "stages", "gates", "documents", "plan"],
  product: ["overview", "engineering", "gates", "work-items", "documents", "stages"],
  project: ["overview", "stages", "plan", "work-items", "gates", "decisions"],
  engineering: ["work-items", "engineering", "quality", "documents", "gates", "stages"],
  quality: ["work-items", "quality", "gates", "engineering", "documents", "stages"],
  introduction: ["work-items", "quality", "materials", "engineering", "documents", "gates"],
  supply: ["materials", "work-items", "plan", "quality", "documents", "gates"],
  portfolio: ["overview", "stages", "work-items", "plan", "gates", "documents"],
  administration: ["overview", "stages", "documents", "work-items", "plan", "gates"],
};
const TAB_KEYS = new Set<ProjectWorkspaceTab>([...tabs.map(tab => tab.key), "materials", "engineering", "quality", "decisions", "management", "conversation"]);

export function primaryProjectTab(tab: ProjectWorkspaceTab): ProjectWorkspaceTab | null {
  if (workViews.some(view => view.key === tab)) return "work-items";
  if (collaborationViews.some(view => view.key === tab)) return "documents";
  return tab === "management" || tab === "conversation" ? null : tab;
}

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
  onIssueChanged,
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
  workKind,
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
  onIssueChanged?: () => Promise<void>;
  onCreateRisk: (input: RiskCreateInput) => Promise<boolean>;
  onCreateTask: (input: TaskCreateInput) => Promise<boolean>;
  onLogout: () => void;
  onRetryWorkItems: () => void;
  onSelect: (project: Project, tab?: ProjectWorkspaceTab) => void;
  onStageTransition: (project: Project, stageId: string) => void;
  onStatusTransition: (project: Project, status: Project["status"]) => void;
  onTabChange: (tab: ProjectWorkspaceTab, workKind?: ProjectWorkKind) => void;
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
    onNavigate: (tab: ProjectWorkspaceTab, kind?: ProjectWorkKind) => void;
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
  workKind?: ProjectWorkKind;
}) {
  const [projectListExpanded, setProjectListExpanded] = useState(false);
  const tabButtons = useRef<Partial<Record<ProjectWorkspaceTab, HTMLButtonElement | null>>>({});
  const { perspective } = useWorkPerspective(identity);
  const permittedTabs = tabs.filter(tab => !tab.internalOnly || canViewWorkItems);
  const orderedKeys = perspectiveTabOrder[perspective.id] ?? perspectiveTabOrder.personal;
  const preferredTabs = orderedKeys.flatMap(key => permittedTabs.filter(tab => tab.key === key));
  const visibleTabs = canViewWorkItems ? [...preferredTabs, ...permittedTabs.filter(tab => tab.key === activeTab && !orderedKeys.includes(tab.key))] : permittedTabs;
  const moreTabs = permittedTabs.filter(tab => !orderedKeys.includes(tab.key));
  const workItemUnavailable = canViewWorkItems && workItemState !== "ready";
  const primaryTab = permittedTabs.some(tab => tab.key === activeTab) ? activeTab : null;

  return (
    <WorkspaceShell active="projects" identity={identity} loggingOut={loggingOut} onLogout={onLogout}>
      {statusMessage ? <p className="mb-4 rounded-lg border border-success/30 bg-success/10 px-3 py-2 text-sm text-success" role="status">{statusMessage}</p> : null}
      {errorMessage ? <p className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{errorMessage}</p> : null}
      <div className="flex flex-wrap items-start justify-between gap-3 pb-5">
        <div className="min-w-0 flex-1">
          <p className="text-xs text-muted-foreground">项目工作区{selectedProject && <> / {selectedProject.code}</>}</p>
          <div className="mt-2 flex flex-wrap items-center gap-3"><h1 className="min-w-0 break-words text-xl font-semibold tracking-tight">{selectedProject?.name ?? "项目工作区"}</h1>{selectedProject && <><span className="rounded-md bg-muted px-2 py-1 text-xs text-muted-foreground">{projectStatusLabels[selectedProject.status]}</span><span className="rounded-md bg-accent px-2 py-1 text-xs text-primary">{selectedProject.current_stage.name}</span></>}</div>
          {!selectedProject && <p className="mt-2 text-sm text-muted-foreground">选择一个项目，查看阶段进展和待办工作。</p>}
        </div>
        {selectedProject && <div className="flex items-center gap-2"><Button aria-controls="project-list-panel" aria-expanded={projectListExpanded} onClick={() => setProjectListExpanded(current => !current)} variant="outline">{projectListExpanded ? "收起项目列表" : `切换项目（${projects.length}）`}</Button><Button className="min-h-11 min-w-11" aria-label={canViewWorkItems ? "项目设置" : "客户回应"} aria-pressed={activeTab === "management"} onClick={() => onTabChange("management")} size="icon" variant="ghost"><Gear aria-hidden="true" size={18}/></Button></div>}
      </div>
      {(!selectedProject || projectListExpanded) && <div className="mb-5" id="project-list-panel"><ProjectList onSelect={project => { setProjectListExpanded(false); const moduleTab = configuredProjectTab(identity, new URLSearchParams(window.location.search).get("module")); onSelect(project, canViewWorkItems ? moduleTab ?? perspective.primaryProjectTab : "overview"); }} projects={projects} selectedId={selectedProject?.id ?? null}/></div>}

      {selectedProject ? (
        <section aria-label="项目详情" className="min-w-0">
          <div className="sticky top-12 z-20 flex min-w-0 items-center gap-2 border-b border-t bg-background">
            <div className="min-w-0 flex-1 overflow-x-auto" role="tablist" aria-label="项目工作区标签"><div className="flex min-w-max">
              {visibleTabs.map((tab, index) => (
                <button
                  aria-controls={`project-panel-${tab.key}`}
                  aria-selected={primaryTab === tab.key}
                  className={cn(
                    "min-h-11 border-b-2 border-transparent px-3 text-sm text-muted-foreground focus-visible:outline-none focus-visible:ring-3 focus-visible:ring-ring/20",
                    primaryTab === tab.key && "border-primary font-medium text-primary",
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
                  tabIndex={primaryTab === tab.key || primaryTab === null && index === 0 ? 0 : -1}
                  type="button"
                >
                  {tab.label}
                </button>
              ))}
            </div></div>
            {canViewWorkItems && moreTabs.length > 0 && <label className="shrink-0 py-1 text-xs"><span className="sr-only">更多项目工作</span><select aria-label="更多项目工作" className="min-h-11 max-w-28 rounded-lg border bg-background px-2 text-xs focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring" value={moreTabs.some(tab => tab.key === activeTab) ? activeTab : ""} onChange={event => { if (event.target.value) onTabChange(event.target.value as ProjectWorkspaceTab); }}><option value="">更多工作</option>{moreTabs.map(tab => <option key={tab.key} value={tab.key}>{tab.label}</option>)}</select></label>}
          </div>
          <div
            aria-labelledby={primaryTab ? `project-tab-${primaryTab}` : undefined}
            aria-label={primaryTab ? undefined : activeTab === "management" ? "项目设置" : "项目对话"}
            className="min-w-0 bg-background py-5"
            id={`project-panel-${primaryTab ?? activeTab}`}
            role={primaryTab ? "tabpanel" : "region"}
          >
            {workItemError ? <p className="mb-4 rounded-lg border border-destructive/30 bg-destructive/10 px-3 py-2 text-sm text-destructive" role="alert">{workItemError}</p> : null}
            {["overview", "stages"].includes(activeTab) && canViewWorkItems && workItemState === "error" ? <WorkItemState onRetry={onRetryWorkItems} state={workItemState} /> : null}
            {activeTab === "overview" ? (
              <ProjectOverview
                canEdit={canEdit}
                canViewWorkItems={canViewWorkItems}
                key={`ProjectOverview:${selectedProject.id}`}
                onUpdate={(values) => onUpdate(selectedProject, values)}
                project={selectedProject}
                saving={saving}
                workItems={workItemState === "ready" ? workItems : null}
              />
            ) : null}
            {activeTab === "overview" && <div className="mt-5 space-y-5">
              {canViewWorkItems && <ProjectTimeline activities={activities} activityError={activityError} loading={activityLoading} onRetry={onRetryActivity} highlightedEntityId={highlightedEntityId} highlightedEventId={highlightedEventId} project={selectedProject}/>}
            </div>}
            {activeTab === "stages" && <div className="space-y-5">
              <ProjectStageBoard key={selectedProject.id} project={selectedProject} workItems={workItemState === "ready" ? workItems : null} canViewWorkItems={canViewWorkItems} loading={workItemState === "loading" || workItemState === "idle"} onPlan={() => onTabChange("plan")}/>
              {canEdit && <details className="border-t pt-3 text-sm"><summary className="cursor-pointer py-2 font-medium">项目状态与阶段操作</summary><div className="max-w-xl"><p className="mt-2 text-xs text-muted-foreground">当前状态：{projectStatusLabels[selectedProject.status]}。阶段推进仍须满足原有评审条件。</p><ProjectStatusActions busy={saving} onStageTransition={stageId => onStageTransition(selectedProject, stageId)} onStatusTransition={status => onStatusTransition(selectedProject, status)} project={selectedProject}/></div></details>}
            </div>}
            {activeTab === "management" && (canViewWorkItems ? <ProjectManagementPanel key={selectedProject.id} external={false} project={selectedProject} userId={identity.user.id} canManage={["owner", "admin", "project_manager"].includes(identity.user.role)}/> : <ExternalProjectResponses key={selectedProject.id} projectId={selectedProject.id} role={identity.user.role}/>)}
            {activeTab === "conversation" && canViewWorkItems && <ProjectAiChat key={selectedProject.id} projectId={selectedProject.id}/>}
            {activeTab === "plan" && canViewWorkItems && <ProjectPlanPanel key={selectedProject.id} projectId={selectedProject.id} userId={identity.user.id}/>}
            {activeTab === "work-items" && workItemUnavailable ? <WorkItemState onRetry={onRetryWorkItems} state={workItemState} /> : null}
            {activeTab === "work-items" && workItems ? (
              <ProjectWorkQueue key={`${selectedProject.id}:${highlightedEntityId ?? ""}`} project={selectedProject} workItems={workItems} focusedEntityId={highlightedEntityId} initialKind={workKind} busy={workItemBusy} onCreateTask={onCreateTask} onCreateIssue={onCreateIssue} onCreateRisk={onCreateRisk} onTransitionTask={onTransitionTask} onTransitionIssue={onTransitionIssue} onTransitionRisk={onTransitionRisk} onIssueChanged={onIssueChanged} onKindChange={kind => onTabChange("work-items", kind)}/>
            ) : null}
            {activeTab === "materials" ? (
              <ProjectTaskWorkspace label="物料与供应办理" sections={[
                { id: "supply-readiness", title: "核对供给与齐套", description: "核对原件、库存快照和Build需求，查看实际短缺。", hashPrefixes: ["supply-", "material-"], children: <SupplyImports key={`SupplyImports:${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} /> },
                { id: "supplier-recovery-work", title: "办理短缺与恢复", description: "从异常核对恢复方案、实际到货和原问题复核。", hashPrefixes: ["supplier-recovery"], children: <SupplierRecoveryPreparation key={`supplier-recovery-${selectedProject.id}`} projectId={selectedProject.id} /> },
                { id: "cost-import-work", title: "核对成本资料", description: "保留原成本依据，预览后按原确认规则录入。", hashPrefixes: ["cost-import"], children: <CostImports key={`cost-import-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} /> },
                { id: "cost-input-work", title: "维护成本输入", description: "核对计价单位、假设与有效输入。", hashPrefixes: ["cost-input"], children: <CostInputs key={`cost-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} /> },
                { id: "cost-control", title: "核对计算与冻结", description: "比较计算结果和正式版本，按当前具名授权办理冻结。", queryKeys: ["cost_freeze_request"], hashPrefixes: ["cost-rollup", "cost-freeze", "cost-"], children: <><CostFreezeLanding projectId={selectedProject.id} canEdit={productEngineering.canEdit} /><CostRollups key={`cost-rollup-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} /></> },
                { id: "supplier-coordination", title: "核对供方工程与回复", description: "核对供方能力、样件、工程资料与内部回复。", hashPrefixes: ["supplier-engineering"], children: <SupplierEngineering key={`engineering-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} /> },
                { id: "supplier-qualification", title: "核对准入与合规", description: "查看准入与合规依据，未知和待批准事项保留。", hashPrefixes: ["supplier-compliance"], children: <SupplierCompliance key={`compliance-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} /> },
                { id: "tooling-handoff", title: "跟进工装与试样", description: "核对工装轮次、样件和实际回执。", hashPrefixes: ["tooling-"], children: <ToolingRounds key={`tooling-${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} /> },
                { id: "supplier-notice-work", title: "跟进供方通知", description: "查看站内通知与当前跟进；外发仍按原边界办理。", hashPrefixes: ["supplier-notice"], children: <SupplierNoticeWatches key={`supplier-notices-${selectedProject.id}`} projectId={selectedProject.id} /> },
              ]} />
            ) : null}
            {activeTab === "engineering" ? (
              <ProjectTaskWorkspace label="设计与变更办理" defaultOpen={["engineering-specifications"]} sections={[
                { id: "engineering-definition", title: "设计修订与交付", description: "查看ID设计版本、接口、冻结和具名交付接收。", queryKeys: ["id_handoff", "id_freeze_request", "id_revision"], hashPrefixes: ["id-"], children: <><IdHandoffLanding projectId={selectedProject.id}/><IdFreezeRequestLanding projectId={selectedProject.id}/><ProjectIdDesign key={`id-design:${selectedProject.id}`} projectId={selectedProject.id}/></> },
                { id: "engineering-specifications", title: "规格与研发 BOM", description: "核对规格、研发物料和专业责任，不复制PLM正式真值。", queryKeys: ["specification_owner_id"], hashPrefixes: ["specification-", "development-bom"], children: <><SpecificationResponsibilityLanding projectId={selectedProject.id}/><ProductEngineeringPanel {...productEngineering} /></> },
                { id: "engineering-changes", title: "工程变更与执行", description: "核对影响与有效批准，跟踪整改、复测和变更实施。", queryKeys: ["ecr"], hashPrefixes: ["ecr-", "change-"], children: <ProjectChangePanel key={`ProjectChangePanel:${selectedProject.id}`} canApprove={CHANGE_APPROVER_ROLES.has(identity.user.role)} canEdit={canEdit} projectId={selectedProject.id} /> },
                { id: "customer-requirement-changes", title: "客户新要求与回复", description: "核对客户要求、回复及内部工程变更，分别办理相应确认。", queryKeys: ["ccr"], hashPrefixes: ["ccr-", "customer-change"], children: <ProjectCustomerChangePanel key={`ccr-${selectedProject.id}`} canApprove={CHANGE_APPROVER_ROLES.has(identity.user.role)} canEdit={canEdit} currentUserId={identity.user.id} projectId={selectedProject.id} /> },
                { id: "engineering-reviews", title: "准备工程评审", description: "核对本轮资料包、输入版本和专业评审缺项。", queryKeys: ["engineering_review_id"], hashPrefixes: ["engineering-review"], children: <EngineeringReviewPackages key={`EngineeringReviewPackages:${selectedProject.id}`} projectId={selectedProject.id} canEdit={productEngineering.canEdit} /> },
              ]} />
            ) : null}
            {activeTab === "decisions" ? (
              <ProjectTaskWorkspace label="例会与决策办理" defaultOpen={["meeting-actions"]} sections={[
                { id: "meeting-actions", title: "准备例会与跟进行动", description: "围绕本轮资料、参会责任与行动项办理，记录实际回执。", hashPrefixes: ["meeting-"], children: <ProjectMeetings key={`retrospectives:${selectedProject.id}`} projectId={selectedProject.id} canManage={["owner", "admin", "project_manager"].includes(identity.user.role)} canUpload={["owner", "admin", "product_manager", "project_manager", "engineer", "quality"].includes(identity.user.role)} /> },
                { id: "decision-followup", title: "记录决策与核对依据", description: "核对决策依据、当前责任与后续动作，正式批准仍由具名授权办理。", hashPrefixes: ["decision-"], children: <ProjectDecisionPanel key={`ProjectDecisionPanel:${selectedProject.id}`} canEdit={canEdit} projectId={selectedProject.id} /> },
                { id: "meeting-rhythm", title: "维护例会节奏与名单", description: "维护例会安排和参会责任，再回到当前轮次执行。", queryKeys: ["meeting_recurrence_id", "meeting_roster_id"], hashPrefixes: ["recurrence-", "meeting-roster"], children: <><MeetingRecurrences key={`recurrences:${selectedProject.id}`} projectId={selectedProject.id}/><MeetingRecurrenceRosterLanding projectId={selectedProject.id}/></> },
              ]}/>
            ) : null}
            {activeTab === "gates" ? (
              <ProjectTaskWorkspace label="评审与交付办理" sections={[
                { id: "gate-review", title: "核对评审条件与办理签核", description: "查看当前轮次、实际阻塞和具名签核，依原批准条件办理。", queryKeys: ["gate_id", "gate_round_id", "gate_signoff_id"], hashPrefixes: ["gate-", "signoff-"], children: <ProjectGatePanel {...gateSurface} actorUserId={identity.user.id} projectId={selectedProject.id} state={gateSurface.loadState} /> },
                { id: "deliverable-readiness", title: "准备交付物与核对缺项", description: "核对交付清单、实际资料与责任；评审结论另行办理。", queryKeys: ["deliverable_id", "check_item_id"], hashPrefixes: ["deliverable-", "check-item-"], children: <ProjectDeliverableCheckPanel key={`ProjectDeliverableCheckPanel:${selectedProject.id}`} canManage={gateSurface.canManage} projectId={selectedProject.id} /> },
              ]}/>
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
              <ProjectNpiPanel key={`ProjectNpiPanel:${selectedProject.id}`} initialTask={perspective.id === "quality" ? "test-execution" : "trial-verification"} canEdit={canEdit} canRecordTests={["owner", "admin", "project_manager", "engineer", "quality"].includes(identity.user.role)} canEditMaterials={productEngineering.canEdit} projectId={selectedProject.id} additionalSections={[
                { id: "quality-closure", title: "调查问题与验证整改", description: "核对质量来源、根因、CAPA和独立有效性验证。", queryKeys: ["quality_owner_id", "ncr"], hashPrefixes: ["ncr-", "complaint-", "capa-", "quality-"], children: <><QualityResponsibilityLanding projectId={selectedProject.id}/><QualityPanel {...qualitySurface} identityUserId={identity.user.id} /></> },
                { id: "failure-prevention", title: "核对失效预防", description: "维护FMEA与风险控制依据，回查实施和验证证据。", hashPrefixes: ["fmea-"], children: <LivingFmea key={`fmea:${selectedProject.id}`} projectId={selectedProject.id}/> },
              ]}/>
            ) : null}

          </div>
        </section>
      ) : null}
    </WorkspaceShell>
  );
}
