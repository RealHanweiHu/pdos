"use client";

import { useRouter, useSearchParams } from "next/navigation";
import type { IssueTransitionExtra } from "./project-work-item-api";
import { useEffect, useEffectEvent, useRef, useState } from "react";

import { useFirstScreenSample } from "@/components/diagnostics/use-first-screen-sample";

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
  openProjectGateRound,
  requestProjectDocuments,
  requestProjectGates,
  signProjectGateRound,
  uploadProjectDocument,
} from "./project-gate-document-api";
import type { ProjectDocument, ProjectGate } from "./project-gate-document-types";
import {
  createComplaint,
  requestComplaints,
  requestNcrDetail,
  requestNcrs,
  triageComplaint,
  transitionComplaint,
} from "@/components/quality/quality-api";
import type { ComplaintTransition } from "@/components/quality/complaint-lifecycle";
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
} from "./project-work-item-types";
import { ProjectWorkspaceError, ProjectWorkspaceLoading } from "./project-workspace-state";
import {
  ProjectWorkspaceView,
  resolveTab,
  type ProjectWorkspaceTab,
  type WorkItemLoadState,
} from "./project-workspace-view";
import type { Project } from "./project-types";
import type { ProjectWorkKind } from "./project-work-queue";
import { useProjectActions } from "./use-project-actions";

type LoadState = "loading" | "ready" | "error" | "redirecting";
const workItemRoles = ["owner", "admin", "project_manager", "engineer", "quality"];
const productEngineeringEditRoles = ["owner", "admin", "project_manager", "engineer"];
function messageFrom(error: unknown) {
  return error instanceof Error ? error.message : "工作项操作失败，请稍后重试。";
}

function pushProjectLocation(projectId: string, tab: ProjectWorkspaceTab, workKind?: ProjectWorkKind) {
  const params = new URLSearchParams();
  params.set("project", projectId);
  params.set("tab", tab);
  if (tab === "work-items" && workKind) params.set("view", workKind);
  const target = `/projects?${params.toString()}`;
  if (`${window.location.pathname}${window.location.search}${window.location.hash}` !== target) {
    window.history.pushState(null, "", target);
  }
  return `${window.location.search}${window.location.hash}`;
}

async function qualityLanding(projectId: string, ncrId: string | null) {
  const [items, detail] = await Promise.all([
    requestComplaints(projectId),
    ncrId ? requestNcrDetail(projectId, ncrId) : Promise.resolve(null),
  ]);
  const selected = detail ? items.find(item => item.id === detail.ncr.complaint_id) ?? null : null;
  if (detail && !selected) throw new Error("原 NCR 质量来源不可用，请重新读取原记录");
  return { items, detail, selected };
}

export function ProjectWorkspace() {
  const { replace } = useRouter();
  const search = useSearchParams().toString();
  const handledLocation = useRef<string | null>(null);
  const [navigationRevision, setNavigationRevision] = useState(0);
  const [navigationError, setNavigationError] = useState<string | null>(null);
  const actions = useProjectActions({ replace });
  const { setProjects, setSelectedProjectId } = actions;
  const [loadState, setLoadState] = useState<LoadState>("loading");
  const [identity, setIdentity] = useState<WorkspaceIdentity | null>(null);
  const [loggingOut, setLoggingOut] = useState(false);
  const [activeTab, setActiveTab] = useState<ProjectWorkspaceTab>("overview");
  const [workKind, setWorkKind] = useState<ProjectWorkKind>();
  const [workItemState, setWorkItemState] = useState<WorkItemLoadState>("idle");
  const [workItems, setWorkItems] = useState<ProjectWorkItems | null>(null);
  const [workItemBusy, setWorkItemBusy] = useState(false);
  const [workItemError, setWorkItemError] = useState<string | null>(null);
  const [workItemStatus, setWorkItemStatus] = useState<string | null>(null);
  const [activities, setActivities] = useState<ProjectActivity[]>([]);
  const [activityError, setActivityError] = useState(false);
  const [activityLoading, setActivityLoading] = useState(false);
  const [activityLoaded, setActivityLoaded] = useState(false);
  const activityRequestSequence = useRef(0);
  const [productEngineeringState, setProductEngineeringState] = useState<WorkItemLoadState>("idle");
  const [productEngineering, setProductEngineering] = useState<ProductEngineeringRegister | null>(null);
  const [productEngineeringBusy, setProductEngineeringBusy] = useState(false);
  const [productEngineeringError, setProductEngineeringError] = useState<string | null>(null);
  const [productEngineeringStatus, setProductEngineeringStatus] = useState<string | null>(null);
  const [gateState, setGateState] = useState<WorkItemLoadState>("idle");
  const [gates, setGates] = useState<ProjectGate[] | null>(null);
  const [gateBusy, setGateBusy] = useState(false);
  const [gateError, setGateError] = useState<string | null>(null);
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
      },
      () => {
        if (active) setLoadState("error");
      },
    );
    return () => { active = false; activityRequestSequence.current += 1; };
  }, [replace, setProjects, setSelectedProjectId]);

  const canViewWorkItems = identity !== null && workItemRoles.includes(identity.user.role);
  const canViewProductEngineering = canViewWorkItems;

  async function loadWorkItems(projectId: string, preserveContext = false) {
    const sequence = requestSequence.current + 1;
    requestSequence.current = sequence;
    if (!preserveContext) { setWorkItemState("loading"); setWorkItems(null); }
    setWorkItemError(null);
    try {
      const loaded = await requestProjectWorkItems(projectId);
      if (requestSequence.current !== sequence) return;
      setWorkItems(loaded);
      setWorkItemState("ready");
    } catch {
      if (requestSequence.current === sequence) {
        if (preserveContext) { setWorkItemError("撤回已记录，但工作项清单刷新失败，请重试读取。"); throw new Error("撤回已记录，但工作项清单刷新失败，请重试读取。"); }
        setWorkItemState("error");
      }
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
    setGateError(null);
    try {
      const items = await requestProjectGates(projectId);
      if (gateRequestSequence.current !== sequence) return;
      setGates(items);
      setGateState("ready");
    } catch {
      if (gateRequestSequence.current === sequence) setGateState("error");
    }
  }

  function replaceGate(updated: ProjectGate) {
    setGates((current) => current?.map((gate) => gate.id === updated.id ? updated : gate) ?? current);
  }

  async function openGateRound(gate: ProjectGate) {
    setGateBusy(true);
    setGateError(null);
    try {
      replaceGate(await openProjectGateRound(gate.project_id, gate.id));
    } catch (error) {
      setGateError(messageFrom(error));
    } finally {
      setGateBusy(false);
    }
  }

  async function signGateRound(
    gate: ProjectGate,
    slot: "product" | "engineering" | "quality",
  ) {
    if (!gate.round) return;
    setGateBusy(true);
    setGateError(null);
    try {
      replaceGate(
        await signProjectGateRound(gate.project_id, gate.id, gate.round.id, slot, { status: "approved", note: null, expected_basis: gate.signing_basis }),
      );
    } catch (error) {
      setGateError(messageFrom(error));
    } finally {
      setGateBusy(false);
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
      const params = new URLSearchParams(window.location.search);
      const { items, detail, selected } = await qualityLanding(projectId, params.get("project") === projectId ? params.get("ncr") : null);
      if (qualityRequestSequence.current !== sequence) return;
      setComplaints(items);
      setSelectedComplaint(selected);
      setQualityDetail(detail);
      setQualityState("ready");
    } catch {
      if (qualityRequestSequence.current === sequence) setQualityState("error");
    }
  }

  function resetDomainData() {
    requestSequence.current += 1;
    setWorkItems(null);
    setWorkItemState("idle");
    setWorkItemError(null);
    setWorkItemStatus(null);
    activityRequestSequence.current += 1;
    setActivities([]);
    setActivityError(false);
    setActivityLoading(false);
    setActivityLoaded(false);
    productRequestSequence.current += 1;
    setProductEngineering(null);
    setProductEngineeringState("idle");
    setProductEngineeringError(null);
    setProductEngineeringStatus(null);
    gateRequestSequence.current += 1;
    setGates(null);
    setGateState("idle");
    setGateError(null);
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
  }

  function selectProject(project: Project) {
    if (actions.selectedProject?.id === project.id) return;
    setNavigationError(null);
    handledLocation.current = pushProjectLocation(project.id, "overview");
    actions.selectProject(project);
    resetDomainData();
    setActiveTab("overview");
    loadTabData("overview", project.id, true);
  }

  async function loadActivity(projectId: string) {
    const sequence = ++activityRequestSequence.current;
    setActivities([]);
    setActivityError(false);
    setActivityLoading(true);
    setActivityLoaded(false);
    try {
      const items = await requestProjectActivity(projectId);
      if (activityRequestSequence.current !== sequence) return;
      setActivities(items);
    } catch {
      if (activityRequestSequence.current === sequence) setActivityError(true);
    } finally {
      if (activityRequestSequence.current === sequence) { setActivityLoading(false); setActivityLoaded(true); }
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

  async function moveIssue(
    issue: ProjectIssue,
    toStatus: IssueStatus,
    extra: IssueTransitionExtra = {},
  ) {
    if (toStatus !== "closed") return mutateWorkItem(
      () => transitionIssue(issue.project_id, issue.id, toStatus, { expected_updated_at: issue.updated_at, ...extra }),
      (items, updated) => ({ ...items, issues: items.issues.map((item) => item.id === issue.id ? updated as ProjectIssue : item) }),
      "问题状态已更新",
    );
    setWorkItemBusy(true); setWorkItemError(null); setWorkItemStatus(null);
    try {
      const updated = await transitionIssue(issue.project_id, issue.id, toStatus, { expected_updated_at: issue.updated_at, ...extra });
      setWorkItems(items => items ? { ...items, issues: items.issues.map(item => item.id === issue.id ? updated : item) } : items);
      setWorkItemStatus("问题状态已更新");
      return true;
    } catch (error) {
      setWorkItemError(messageFrom(error));
      throw error;
    } finally { setWorkItemBusy(false); }
  }

  async function moveRisk(risk: ProjectRisk, toStatus: RiskStatus) {
    return mutateWorkItem(
      () => transitionRisk(risk.project_id, risk.id, toStatus),
      (items, updated) => ({ ...items, risks: items.risks.map((item) => item.id === risk.id ? updated as ProjectRisk : item) }),
      "风险状态已更新",
    );
  }

  /** Each domain loads its own data the first time it is opened. */
  function loadTabData(tab: ProjectWorkspaceTab, projectId: string, force = false) {
    if (["overview", "stages", "work-items"].includes(tab) && canViewWorkItems && (force || workItemState === "idle")) {
      void loadWorkItems(projectId);
    }
    if (tab === "overview" && canViewWorkItems && (force || (!activityLoading && !activityLoaded))) {
      void loadActivity(projectId);
    }
    if (tab === "engineering" && canViewProductEngineering && (force || productEngineeringState === "idle")) {
      void loadProductEngineering(projectId);
    }
    if (tab === "gates" && canViewWorkItems && (force || gateState === "idle")) {
      void loadGates(projectId);
    }
    if (tab === "documents" && canViewWorkItems && (force || documentState === "idle")) {
      void loadDocuments(projectId);
    }
    if (tab === "quality" && canViewWorkItems && (force || qualityState === "idle")) {
      void loadQuality(projectId);
    }
  }

  function changeTab(tab: ProjectWorkspaceTab, workKind?: ProjectWorkKind) {
    if (tab === activeTab && !workKind) return;
    setActiveTab(tab);
    setWorkKind(workKind);
    setHighlightedEventId(null);
    setHighlightedEntityId(null);
    if (actions.selectedProject) {
      handledLocation.current = pushProjectLocation(actions.selectedProject.id, tab, workKind);
      loadTabData(tab, actions.selectedProject.id);
    }
  }

  // Router links, browser history and hash links share the same restoration path.
  // Local tab clicks already loaded their domain and are recorded before pushState.
  const restoreLocation = useEffectEvent(() => {
    if (loadState !== "ready" || !identity) return;
    const location = `${window.location.search}${window.location.hash}`;
    if (handledLocation.current === location) return;
    const restoring = handledLocation.current !== null;
    handledLocation.current = location;
    const params = new URLSearchParams(window.location.search);
    const projectId = params.get("project");
    const project = projectId
      ? actions.projects.find(item => item.id === projectId)
      : params.has("tab") ? actions.selectedProject : null;
    resetDomainData();
    if (restoring) setNavigationRevision(value => value + 1);
    setNavigationError(projectId && !project ? "原链接的项目不存在或当前无权读取，请选择可访问的项目。" : null);
    if (!project) {
      setSelectedProjectId(null);
      setActiveTab("overview");
      return;
    }
    if (!projectId) {
      params.set("project", project.id);
      window.history.replaceState(null, "", `/projects?${params.toString()}${window.location.hash}`);
      handledLocation.current = `${window.location.search}${window.location.hash}`;
    }
    actions.selectProject(project);
    const requestedTab = resolveTab(params.get("tab"), params, window.location.hash) ?? "overview";
    const tab = canViewWorkItems || requestedTab === "stages" || requestedTab === "management" ? requestedTab : "overview";
    setActiveTab(tab);
    const requestedWorkKind = params.get("view") ?? ({ tasks: "tasks", issues: "issues", risks: "risks" } as Record<string, string>)[params.get("tab") ?? ""];
    setWorkKind(["tasks", "issues", "risks"].includes(requestedWorkKind) ? requestedWorkKind as ProjectWorkKind : undefined);
    const eventId = Number(params.get("event_id"));
    setHighlightedEventId(Number.isSafeInteger(eventId) && eventId > 0 ? eventId : null);
    setHighlightedEntityId(params.get("entity_id"));
    loadTabData(tab, project.id, true);
  });

  // Synchronize the external router location and invalidate in-flight domain reads.
  // eslint-disable-next-line react-hooks/set-state-in-effect
  useEffect(() => { restoreLocation(); }, [loadState, search]);
  useEffect(() => {
    const restore = () => restoreLocation();
    window.addEventListener("popstate", restore);
    window.addEventListener("hashchange", restore);
    return () => {
      window.removeEventListener("popstate", restore);
      window.removeEventListener("hashchange", restore);
    };
  }, []);

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
    const projectId = actions.selectedProject.id;
    const sequence = ++qualityRequestSequence.current;
    setSelectedComplaint(complaint);
    setQualityDetail(null);
    setQualityError(null);
    try {
      const ncrs = await requestNcrs(projectId, complaint.id);
      if (qualityRequestSequence.current !== sequence) return;
      if (ncrs.length) {
        const detail = await requestNcrDetail(projectId, ncrs[0]!.id);
        if (qualityRequestSequence.current === sequence) setQualityDetail(detail);
      }
    } catch (error) {
      if (qualityRequestSequence.current === sequence) setQualityError(messageFrom(error));
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

  async function transitionSelected(complaint: Complaint, input: ComplaintTransition) {
    if (!actions.selectedProject) return false;
    const sequence = qualityRequestSequence.current;
    setQualityBusy(true);
    setQualityError(null);
    try {
      const updated = await transitionComplaint(complaint.project_id, complaint.id, input);
      if (qualityRequestSequence.current !== sequence) return true;
      setComplaints(current => current?.map(item => item.id === updated.id ? updated : item) ?? null);
      setSelectedComplaint(current => current?.id === updated.id ? updated : current);
      return true;
    } catch (error) {
      if (qualityRequestSequence.current === sequence) setQualityError(messageFrom(error));
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

  useFirstScreenSample("project", loadState === "ready" && activeTab === "overview"
    && actions.selectedProject !== null && workItemState === "ready" && activityLoaded && !activityError ? "ready"
    : loadState === "error" || workItemState === "error" || activityError || navigationError !== null ? "error" : "loading",
    { projects: actions.projects.length, tasks: workItems?.tasks.length ?? 0,
      issues: workItems?.issues.length ?? 0, risks: workItems?.risks.length ?? 0, activities: activities.length });

  if (loadState === "redirecting") return null;
  if (loadState === "loading") return <ProjectWorkspaceLoading />;
  if (loadState === "error" || identity === null) {
    return <ProjectWorkspaceError onRetry={() => { setLoadState("loading"); void retryLoad(); }} />;
  }
  const canEdit = ["owner", "admin", "project_manager"].includes(identity.user.role);
  const canEditProductEngineering = productEngineeringEditRoles.includes(identity.user.role);
  return (
    <ProjectWorkspaceView
      key={navigationRevision}
      activeTab={activeTab}
      workKind={workKind}
      activities={activities}
      activityError={activityError}
      activityLoading={activityLoading}
      onRetryActivity={() => { if (actions.selectedProject) void loadActivity(actions.selectedProject.id); }}
      canEdit={canEdit}
      canViewWorkItems={canViewWorkItems}
      highlightedEntityId={highlightedEntityId}
      highlightedEventId={highlightedEventId}
      errorMessage={navigationError ?? actions.errorMessage}
      identity={identity}
      loggingOut={loggingOut}
      onCreateIssue={addIssue}
      onIssueChanged={async () => { if (actions.selectedProject) await loadWorkItems(actions.selectedProject.id, true); }}
      onCreateRisk={addRisk}
      onCreateTask={addTask}
      onLogout={() => void logout()}
      onRetryWorkItems={() => { if (actions.selectedProject) void loadWorkItems(actions.selectedProject.id); }}
      onSelect={selectProject}
      onStageTransition={(project, stageId) => void actions.transitionStage(project, stageId)}
      onStatusTransition={(project, status) => void actions.transitionStatus(project, status)}
      onTabChange={changeTab}
      onTransitionIssue={moveIssue}
      onTransitionRisk={moveRisk}
      onTransitionTask={moveTask}
      onUpdate={actions.updateProject}
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
        actorRole: identity.user.role,
        busy: gateBusy,
        canManage: ["owner", "admin", "project_manager"].includes(identity.user.role),
        error: gateError,
        gates,
        loadState: gateState,
        onNavigate: changeTab,
        onOpenRound: (gate) => void openGateRound(gate),
        onRetry: () => { if (actions.selectedProject) void loadGates(actions.selectedProject.id); },
        onSignoff: (gate, slot) => void signGateRound(gate, slot),
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
        canClose: identity.user.role === "quality",
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
        onTransition: transitionSelected,
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
