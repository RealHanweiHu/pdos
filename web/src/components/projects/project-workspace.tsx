"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import type { WorkspaceIdentity } from "@/components/workspace-types";
import {
  createDevelopmentBom,
  createSpecification,
  requestProductEngineering,
} from "@/components/product-engineering/product-engineering-api";
import type {
  DevelopmentBomCreateInput,
  ProductEngineeringRegister,
  SpecificationCreateInput,
} from "@/components/product-engineering/product-engineering-types";
import { requestProjectActivity, type ProjectActivity } from "./project-activity";
import {
  requestProjectDocuments,
  requestProjectGates,
  uploadProjectDocument,
} from "./project-gate-document-api";
import type { ProjectDocument, ProjectGate } from "./project-gate-document-types";
import {
  createComplaint,
  requestComplaints,
  requestNcrDetail,
  requestNcrs,
  triageComplaint,
} from "@/components/quality/quality-api";
import type {
  Complaint,
  ComplaintCreateInput,
  NcrCreateInput,
  NcrDetail,
} from "@/components/quality/quality-types";

import { requestProjects } from "./project-api";
import {
  createIssue,
  createRisk,
  createTask,
  requestProjectWorkItems,
  transitionIssue,
  transitionRisk,
  transitionTask,
  updateTask,
} from "./project-work-item-api";
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
  TaskUpdateInput,
} from "./project-work-item-types";
import { ProjectWorkspaceError, ProjectWorkspaceLoading } from "./project-workspace-state";
import {
  ProjectWorkspaceView,
  type ProjectWorkspaceTab,
  type WorkItemLoadState,
} from "./project-workspace-view";
import type { Project } from "./project-types";
import { useProjectActions } from "./use-project-actions";

type LoadState = "loading" | "ready" | "error" | "redirecting";
const workItemRoles = ["owner", "admin", "project_manager", "engineer", "quality"];
const productEngineeringEditRoles = ["owner", "admin", "project_manager", "engineer"];
const deepLinkTabs = new Set<ProjectWorkspaceTab>([
  "overview",
  "timeline",
  "tasks",
  "issues",
  "risks",
  "resources",
  "product-engineering",
  "gates",
  "documents",
  "quality",
  "ai-chat",
]);

function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : "工作项操作失败，请稍后重试。";
}

export function ProjectWorkspace() {
  const { replace } = useRouter();
  const actions = useProjectActions({ replace });
  const { setProjects, setSelectedProjectId } = actions;
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [activeTab, setActiveTab] = useState<ProjectWorkspaceTab>("overview");
  const [workItemState, setWorkItemState] = useState<WorkItemLoadState>("idle");
  const [workItems, setWorkItems] = useState<ProjectWorkItems | null>(null);
  const [workItemBusy, setWorkItemBusy] = useState(false);
  const [workItemError, setWorkItemError] = useState<string | null>(null);
  const [workItemStatus, setWorkItemStatus] = useState<string | null>(null);
  const [activities, setActivities] = useState<ProjectActivity[]>([]);
  const [activityError, setActivityError] = useState(false);
  const [productEngineeringState, setProductEngineeringState] = useState<WorkItemLoadState>("idle");
  const [productEngineering, setProductEngineering] = useState<ProductEngineeringRegister | null>(null);
  const [productEngineeringBusy, setProductEngineeringBusy] = useState(false);
  const [productEngineeringError, setProductEngineeringError] = useState<string | null>(null);
  const [productEngineeringStatus, setProductEngineeringStatus] = useState<string | null>(null);
  const [gateState, setGateState] = useState<WorkItemLoadState>("idle");
  const [gates, setGates] = useState<ProjectGate[] | null>(null);
  const [documentState, setDocumentState] = useState<WorkItemLoadState>("idle");
  const [documents, setDocuments] = useState<ProjectDocument[] | null>(null);
  const [documentBusy, setDocumentBusy] = useState(false);
  const [documentError, setDocumentError] = useState<string | null>(null);
  const [qualityState, setQualityState] = useState<WorkItemLoadState>("idle");
  const [complaints, setComplaints] = useState<Complaint[] | null>(null);
  const [selectedComplaint, setSelectedComplaint] = useState<Complaint | null>(null);
  const [qualityDetail, setQualityDetail] = useState<NcrDetail | null>(null);
  const [qualityBusy, setQualityBusy] = useState(false);
  const [qualityError, setQualityError] = useState<string | null>(null);
  const [highlightedEntityId, setHighlightedEntityId] = useState<string | null>(null);
  const [highlightedEventId, setHighlightedEventId] = useState<number | null>(null);
  const requestSequence = useRef(0);
  const productRequestSequence = useRef(0);
  const gateRequestSequence = useRef(0);
  const documentRequestSequence = useRef(0);
  const qualityRequestSequence = useRef(0);

  useEffect(() => {
    let active = true;
    requestProjects().then(
      (loaded) => {
        if (!active) return;
        if (loaded === null) {
          setLoadState("redirecting");
          replace("/login");
          return;
        }
        setIdentity(loaded.identity);
        setProjects(loaded.projects);
        setLoadState("ready");
        const deepLinkedId = new URLSearchParams(window.location.search).get("project");
        const deepLinkedTab = new URLSearchParams(window.location.search).get("tab") as ProjectWorkspaceTab | null;
        const deepLinkedEvent = Number(new URLSearchParams(window.location.search).get("event_id"));
        const deepLinkedEntity = new URLSearchParams(window.location.search).get("entity_id");
        const deepLinkedProject = loaded.projects.find((project) => project.id === deepLinkedId);
        if (deepLinkedProject) {
          setSelectedProjectId(deepLinkedProject.id);
          if (deepLinkedTab && deepLinkTabs.has(deepLinkedTab)) setActiveTab(deepLinkedTab);
          setHighlightedEventId(Number.isSafeInteger(deepLinkedEvent) && deepLinkedEvent > 0 ? deepLinkedEvent : null);
          setHighlightedEntityId(deepLinkedEntity);
          requestProjectActivity(deepLinkedProject.id).then(
            (items) => { if (active) { setActivities(items); setActivityError(false); } },
            () => { if (active) { setActivities([]); setActivityError(true); } },
          );
          if (workItemRoles.includes(loaded.identity.user.role)) {
            const sequence = requestSequence.current + 1;
            requestSequence.current = sequence;
            setWorkItemState("loading");
            requestProjectWorkItems(deepLinkedProject.id).then(
              (items) => {
                if (!active || requestSequence.current !== sequence) return;
                setWorkItems(items);
                setWorkItemState("ready");
              },
              () => {
                if (active && requestSequence.current === sequence) setWorkItemState("error");
              },
            );
          }
          if (
            deepLinkedTab === "product-engineering" &&
            workItemRoles.includes(loaded.identity.user.role)
          ) {
            const sequence = productRequestSequence.current + 1;
            productRequestSequence.current = sequence;
            setProductEngineeringState("loading");
            requestProductEngineering(deepLinkedProject.id).then(
              (register) => {
                if (!active || productRequestSequence.current !== sequence) return;
                setProductEngineering(register);
                setProductEngineeringState("ready");
              },
              () => {
                if (active && productRequestSequence.current === sequence) {
                  setProductEngineeringState("error");
                }
              },
            );
          }
          if (deepLinkedTab === "gates" && workItemRoles.includes(loaded.identity.user.role)) {
            const sequence = gateRequestSequence.current + 1;
            gateRequestSequence.current = sequence;
            setGateState("loading");
            requestProjectGates(deepLinkedProject.id).then(
              (items) => { if (active && gateRequestSequence.current === sequence) { setGates(items); setGateState("ready"); } },
              () => { if (active && gateRequestSequence.current === sequence) setGateState("error"); },
            );
          }
          if (deepLinkedTab === "documents" && workItemRoles.includes(loaded.identity.user.role)) {
            const sequence = documentRequestSequence.current + 1;
            documentRequestSequence.current = sequence;
            setDocumentState("loading");
            requestProjectDocuments(deepLinkedProject.id).then(
              (items) => { if (active && documentRequestSequence.current === sequence) { setDocuments(items); setDocumentState("ready"); } },
              () => { if (active && documentRequestSequence.current === sequence) setDocumentState("error"); },
            );
          }
          if (deepLinkedTab === "quality" && workItemRoles.includes(loaded.identity.user.role)) {
            const sequence = qualityRequestSequence.current + 1;
            qualityRequestSequence.current = sequence;
            setQualityState("loading");
            requestComplaints(deepLinkedProject.id).then(
              (items) => {
                if (active && qualityRequestSequence.current === sequence) {
                  setComplaints(items);
                  setQualityState("ready");
                }
              },
              () => {
                if (active && qualityRequestSequence.current === sequence) {
                  setQualityState("error");
                }
              },
            );
          }
        }
      },
      () => {
        if (active) setLoadState("error");
      },
    );
    return () => { active = false; };
  }, [replace, setProjects, setSelectedProjectId]);

  const canViewWorkItems = identity !== null && workItemRoles.includes(identity.user.role);
  const canViewProductEngineering = canViewWorkItems;

  async function loadWorkItems(projectId: string) {
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    setWorkItemState("loading");
    setWorkItems(null);
    setWorkItemError(null);
    try {
      const loaded = await requestProjectWorkItems(projectId);
      if (requestSequence.current !== sequence) return;
      setWorkItems(loaded);
      setWorkItemState("ready");
    } catch {
      if (requestSequence.current === sequence) setWorkItemState("error");
    }
  }

  async function loadProductEngineering(projectId: string) {
    const sequence = productRequestSequence.current + 1;
    productRequestSequence.current = sequence;
    setProductEngineeringState("loading");
    setProductEngineering(null);
    setProductEngineeringError(null);
    try {
      const loaded = await requestProductEngineering(projectId);
      if (productRequestSequence.current !== sequence) return;
      setProductEngineering(loaded);
      setProductEngineeringState("ready");
    } catch {
      if (productRequestSequence.current === sequence) setProductEngineeringState("error");
    }
  }

  async function loadGates(projectId: string) {
    const sequence = gateRequestSequence.current + 1;
    gateRequestSequence.current = sequence;
    setGateState("loading");
    setGates(null);
    try {
      const items = await requestProjectGates(projectId);
      if (gateRequestSequence.current !== sequence) return;
      setGates(items);
      setGateState("ready");
    } catch {
      if (gateRequestSequence.current === sequence) setGateState("error");
    }
  }

  async function loadDocuments(projectId: string) {
    const sequence = documentRequestSequence.current + 1;
    documentRequestSequence.current = sequence;
    setDocumentState("loading");
    setDocuments(null);
    setDocumentError(null);
    try {
      const items = await requestProjectDocuments(projectId);
      if (documentRequestSequence.current !== sequence) return;
      setDocuments(items);
      setDocumentState("ready");
    } catch {
      if (documentRequestSequence.current === sequence) setDocumentState("error");
    }
  }

  async function loadQuality(projectId: string) {
    const sequence = qualityRequestSequence.current + 1;
    qualityRequestSequence.current = sequence;
    setQualityState("loading");
    setComplaints(null);
    setSelectedComplaint(null);
    setQualityDetail(null);
    setQualityError(null);
    try {
      const items = await requestComplaints(projectId);
      if (qualityRequestSequence.current !== sequence) return;
      setComplaints(items);
      setQualityState("ready");
    } catch {
      if (qualityRequestSequence.current === sequence) setQualityState("error");
    }
  }

  function selectProject(project: Project) {
    actions.selectProject(project);
    setActiveTab("overview");
    setWorkItemError(null);
    setWorkItemStatus(null);
    productRequestSequence.current += 1;
    setProductEngineering(null);
    setProductEngineeringState("idle");
    setProductEngineeringError(null);
    setProductEngineeringStatus(null);
    gateRequestSequence.current += 1;
    setGates(null);
    setGateState("idle");
    documentRequestSequence.current += 1;
    setDocuments(null);
    setDocumentState("idle");
    setDocumentError(null);
    qualityRequestSequence.current += 1;
    setQualityState("idle");
    setComplaints(null);
    setSelectedComplaint(null);
    setQualityDetail(null);
    setQualityError(null);
    setHighlightedEventId(null);
    setHighlightedEntityId(null);
    requestProjectActivity(project.id).then(
      (items) => { setActivities(items); setActivityError(false); },
      () => { setActivities([]); setActivityError(true); },
    );
    if (canViewWorkItems) {
      void loadWorkItems(project.id);
    } else {
      requestSequence.current += 1;
      setWorkItems(null);
      setWorkItemState("idle");
    }
  }

  async function retryLoad() {
    try {
      const loaded = await requestProjects();
      if (loaded === null) {
        setLoadState("redirecting");
        replace("/login");
        return;
      }
      setIdentity(loaded.identity);
      setProjects(loaded.projects);
      setLoadState("ready");
    } catch {
      setLoadState("error");
    }
  }

  async function logout() {
    setLoggingOut(true);
    try {
      await fetch("/api/session/logout", { method: "POST", credentials: "same-origin" });
    } finally {
      replace("/login");
    }
  }

  async function mutateWorkItem<T>(
    operation: () => Promise<T>,
    apply: (items: ProjectWorkItems, updated: T) => ProjectWorkItems,
    success: string,
  ) {
    setWorkItemBusy(true);
    setWorkItemError(null);
    setWorkItemStatus(null);
    try {
      const updated = await operation();
      setWorkItems((current) => current === null ? current : apply(current, updated));
      setWorkItemStatus(success);
      return true;
    } catch (error) {
      setWorkItemError(messageFrom(error));
      return false;
    } finally {
      setWorkItemBusy(false);
    }
  }

  async function addTask(input: TaskCreateInput) {
    if (!actions.selectedProject) return false;
    return mutateWorkItem(
      () => createTask(actions.selectedProject!.id, input),
      (items, task) => ({ ...items, tasks: [task as ProjectTask, ...items.tasks] }),
      "任务已创建",
    );
  }

  async function editTask(task: ProjectTask, input: TaskUpdateInput) {
    return mutateWorkItem(
      () => updateTask(task.project_id, task.id, input),
      (items, updated) => ({ ...items, tasks: items.tasks.map((item) => item.id === task.id ? updated as ProjectTask : item) }),
      "任务已更新",
    );
  }

  async function addIssue(input: IssueCreateInput) {
    if (!actions.selectedProject) return false;
    return mutateWorkItem(
      () => createIssue(actions.selectedProject!.id, input),
      (items, issue) => ({ ...items, issues: [issue as ProjectIssue, ...items.issues] }),
      "问题已创建",
    );
  }

  async function addRisk(input: RiskCreateInput) {
    if (!actions.selectedProject) return false;
    return mutateWorkItem(
      () => createRisk(actions.selectedProject!.id, input),
      (items, risk) => ({ ...items, risks: [risk as ProjectRisk, ...items.risks] }),
      "风险已创建",
    );
  }

  async function moveTask(task: ProjectTask, input: TaskTransitionInput) {
    setWorkItemBusy(true);
    setWorkItemError(null);
    setWorkItemStatus(null);
    try {
      await transitionTask(task.project_id, task.id, input);
      setWorkItems(await requestProjectWorkItems(task.project_id));
      setWorkItemStatus("任务状态已更新");
      return true;
    } catch (error) {
      setWorkItemError(messageFrom(error));
      return false;
    } finally {
      setWorkItemBusy(false);
    }
  }

  async function moveIssue(issue: ProjectIssue, toStatus: IssueStatus) {
    return mutateWorkItem(
      () => transitionIssue(issue.project_id, issue.id, toStatus),
      (items, updated) => ({ ...items, issues: items.issues.map((item) => item.id === issue.id ? updated as ProjectIssue : item) }),
      "问题状态已更新",
    );
  }

  async function moveRisk(risk: ProjectRisk, toStatus: RiskStatus) {
    return mutateWorkItem(
      () => transitionRisk(risk.project_id, risk.id, toStatus),
      (items, updated) => ({ ...items, risks: items.risks.map((item) => item.id === risk.id ? updated as ProjectRisk : item) }),
      "风险状态已更新",
    );
  }

  function changeTab(tab: ProjectWorkspaceTab) {
    setActiveTab(tab);
    if (
      tab === "product-engineering" &&
      canViewProductEngineering &&
      actions.selectedProject &&
      productEngineeringState === "idle"
    ) {
      void loadProductEngineering(actions.selectedProject.id);
    }
    if (tab === "gates" && canViewWorkItems && actions.selectedProject && gateState === "idle") {
      void loadGates(actions.selectedProject.id);
    }
    if (tab === "documents" && canViewWorkItems && actions.selectedProject && documentState === "idle") {
      void loadDocuments(actions.selectedProject.id);
    }
    if (tab === "quality" && canViewWorkItems && actions.selectedProject && qualityState === "idle") {
      void loadQuality(actions.selectedProject.id);
    }
  }

  async function addComplaint(input: ComplaintCreateInput) {
    if (!actions.selectedProject) return false;
    setQualityBusy(true);
    setQualityError(null);
    try {
      const created = await createComplaint(actions.selectedProject.id, input);
      setComplaints((current) => [created, ...(current ?? [])]);
      setSelectedComplaint(created);
      setQualityDetail(null);
      return true;
    } catch (error) {
      setQualityError(messageFrom(error));
      return false;
    } finally {
      setQualityBusy(false);
    }
  }

  async function selectComplaint(complaint: Complaint) {
    if (!actions.selectedProject) return;
    setSelectedComplaint(complaint);
    setQualityDetail(null);
    setQualityError(null);
    try {
      const ncrs = await requestNcrs(actions.selectedProject.id, complaint.id);
      if (ncrs.length) {
        setQualityDetail(await requestNcrDetail(actions.selectedProject.id, ncrs[0]!.id));
      }
    } catch (error) {
      setQualityError(messageFrom(error));
    }
  }

  async function triageSelected(complaint: Complaint, input: NcrCreateInput) {
    if (!actions.selectedProject) return false;
    setQualityBusy(true);
    setQualityError(null);
    try {
      const result = await triageComplaint(actions.selectedProject.id, complaint.id, input);
      setComplaints((current) =>
        current?.map((item) => (item.id === complaint.id ? result.complaint : item)) ?? null,
      );
      setSelectedComplaint(result.complaint);
      setQualityDetail(await requestNcrDetail(actions.selectedProject.id, result.ncr.id));
      return true;
    } catch (error) {
      setQualityError(messageFrom(error));
      return false;
    } finally {
      setQualityBusy(false);
    }
  }

  async function uploadDocument(file: File, classification: string) {
    if (!actions.selectedProject) return false;
    setDocumentBusy(true);
    setDocumentError(null);
    try {
      const document = await uploadProjectDocument(actions.selectedProject.id, file, classification);
      setDocuments((current) => current ? [document, ...current] : [document]);
      return true;
    } catch (error) {
      setDocumentError(messageFrom(error));
      return false;
    } finally {
      setDocumentBusy(false);
    }
  }

  async function addSpecification(input: SpecificationCreateInput) {
    if (!actions.selectedProject) return false;
    setProductEngineeringBusy(true);
    setProductEngineeringError(null);
    setProductEngineeringStatus(null);
    try {
      const created = await createSpecification(actions.selectedProject.id, input);
      setProductEngineering((current) =>
        current ? { ...current, specifications: [created, ...current.specifications] } : current,
      );
      setProductEngineeringStatus("规格已创建");
      return true;
    } catch (error) {
      setProductEngineeringError(messageFrom(error));
      return false;
    } finally {
      setProductEngineeringBusy(false);
    }
  }

  async function addDevelopmentBom(input: DevelopmentBomCreateInput) {
    if (!actions.selectedProject) return false;
    setProductEngineeringBusy(true);
    setProductEngineeringError(null);
    setProductEngineeringStatus(null);
    try {
      const created = await createDevelopmentBom(actions.selectedProject.id, input);
      setProductEngineering((current) =>
        current ? { ...current, boms: [created, ...current.boms] } : current,
      );
      setProductEngineeringStatus("BOM 已创建");
      return true;
    } catch (error) {
      setProductEngineeringError(messageFrom(error));
      return false;
    } finally {
      setProductEngineeringBusy(false);
    }
  }

  if (loadState === "redirecting") return null;
  if (loadState === "loading") return <ProjectWorkspaceLoading />;
  if (loadState === "error" || identity === null) {
    return <ProjectWorkspaceError onRetry={() => { setLoadState("loading"); void retryLoad(); }} />;
  }
  const canEdit = ["owner", "admin", "project_manager"].includes(identity.user.role);
  const canEditProductEngineering = productEngineeringEditRoles.includes(identity.user.role);
  return (
    <ProjectWorkspaceView
      activeTab={activeTab}
      activities={activities}
      activityError={activityError}
      canEdit={canEdit}
      canViewWorkItems={canViewWorkItems}
      highlightedEntityId={highlightedEntityId}
      highlightedEventId={highlightedEventId}
      errorMessage={actions.errorMessage}
      identity={identity}
      loggingOut={loggingOut}
      onCancelEdit={actions.clearSelection}
      onCreateIssue={addIssue}
      onCreateRisk={addRisk}
      onCreateTask={addTask}
      onLogout={() => void logout()}
      onMembersChange={(members) => setWorkItems((current) => current === null ? current : { ...current, members })}
      onRetryWorkItems={() => { if (actions.selectedProject) void loadWorkItems(actions.selectedProject.id); }}
      onSelect={selectProject}
      onStageTransition={(project, stageId) => void actions.transitionStage(project, stageId)}
      onStatusTransition={(project, status, reason) => void actions.transitionStatus(project, status, reason)}
      onTabChange={changeTab}
      onTransitionIssue={moveIssue}
      onTransitionRisk={moveRisk}
      onTransitionTask={moveTask}
      onUpdate={actions.updateProject}
      onUpdateStagePlan={actions.updateStagePlan}
      onUpdateTask={editTask}
      projects={actions.projects}
      productEngineering={{
        busy: productEngineeringBusy,
        canEdit: canEditProductEngineering,
        error: productEngineeringError,
        loadState: productEngineeringState,
        onCreateBom: addDevelopmentBom,
        onCreateSpecification: addSpecification,
        onRetry: () => {
          if (actions.selectedProject) void loadProductEngineering(actions.selectedProject.id);
        },
        register: productEngineering,
        status: productEngineeringStatus,
      }}
      gateSurface={{
        gates,
        loadState: gateState,
        onRetry: () => { if (actions.selectedProject) void loadGates(actions.selectedProject.id); },
      }}
      documentSurface={{
        busy: documentBusy,
        canUpload: canViewWorkItems,
        documents,
        error: documentError,
        loadState: documentState,
        onRetry: () => { if (actions.selectedProject) void loadDocuments(actions.selectedProject.id); },
        onUpload: uploadDocument,
      }}
      qualitySurface={{
        busy: qualityBusy,
        canCreate: workItemRoles.includes(identity.user.role),
        canManage: ["owner", "admin", "quality"].includes(identity.user.role),
        complaints,
        detail: qualityDetail,
        error: qualityError,
        loadState: qualityState,
        onCreate: addComplaint,
        onRetry: () => {
          if (actions.selectedProject) void loadQuality(actions.selectedProject.id);
        },
        onSelect: (complaint) => void selectComplaint(complaint),
        onTriage: triageSelected,
        selectedComplaint,
      }}
      saving={actions.saving}
      selectedProject={actions.selectedProject}
      statusMessage={workItemStatus ?? actions.statusMessage}
      workItemBusy={workItemBusy}
      workItemError={workItemError}
      workItemState={workItemState}
      workItems={workItems}
    />
  );
}
