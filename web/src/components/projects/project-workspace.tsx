"use client";

import { useRouter } from "next/navigation";
import { useEffect, useRef, useState } from "react";

import type { WorkspaceIdentity } from "@/components/workspace-types";
import { requestProjectActivity, type ProjectActivity } from "./project-activity";

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
  type ProjectWorkspaceTab,
  type WorkItemLoadState,
} from "./project-workspace-view";
import type { Project } from "./project-types";
import { useProjectActions } from "./use-project-actions";

type LoadState = "loading" | "ready" | "error" | "redirecting";
const workItemRoles = ["owner", "admin", "project_manager", "engineer", "quality"];
const deepLinkTabs = new Set<ProjectWorkspaceTab>(["overview", "timeline", "tasks", "issues", "risks", "ai-chat"]);

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
  const [highlightedEntityId, setHighlightedEntityId] = useState<string | null>(null);
  const [highlightedEventId, setHighlightedEventId] = useState<number | null>(null);
  const requestSequence = useRef(0);

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
        }
      },
      () => {
        if (active) setLoadState("error");
      },
    );
    return () => { active = false; };
  }, [replace, setProjects, setSelectedProjectId]);

  const canViewWorkItems = identity !== null && workItemRoles.includes(identity.user.role);

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

  function selectProject(project: Project) {
    actions.selectProject(project);
    setActiveTab("overview");
    setWorkItemError(null);
    setWorkItemStatus(null);
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

  if (loadState === "redirecting") return null;
  if (loadState === "loading") return <ProjectWorkspaceLoading />;
  if (loadState === "error" || identity === null) {
    return <ProjectWorkspaceError onRetry={() => { setLoadState("loading"); void retryLoad(); }} />;
  }
  const canEdit = ["owner", "admin", "project_manager"].includes(identity.user.role);
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
      onRetryWorkItems={() => { if (actions.selectedProject) void loadWorkItems(actions.selectedProject.id); }}
      onSelect={selectProject}
      onStageTransition={(project, stageId) => void actions.transitionStage(project, stageId)}
      onStatusTransition={(project, status) => void actions.transitionStatus(project, status)}
      onTabChange={setActiveTab}
      onTransitionIssue={moveIssue}
      onTransitionRisk={moveRisk}
      onTransitionTask={moveTask}
      onUpdate={actions.updateProject}
      projects={actions.projects}
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
