import { isRecord, responseBody } from "@/components/workspace-api";

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

const priorities = ["low", "medium", "high", "critical"] as const;
const taskStatuses = ["todo", "in_progress", "blocked", "done", "skipped"] as const;
const readinessValues = ["ready", "waiting", "blocked", "complete", "waiting_approval"] as const;
const issueStatuses = ["open", "analysis", "action", "verification", "closed"] as const;
const riskStatuses = ["open", "mitigating", "watching", "closed"] as const;

function isNullableString(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isStringArray(value: unknown): value is string[] {
  return Array.isArray(value) && value.every((item) => typeof item === "string");
}

function isCommonWorkItem(value: Record<string, unknown>): boolean {
  return (
    typeof value.id === "string" &&
    typeof value.project_id === "string" &&
    typeof value.title === "string" &&
    isNullableString(value.description) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

export function isProjectTask(value: unknown): value is ProjectTask {
  if (!isRecord(value) || !isCommonWorkItem(value)) return false;
  return (
    isNullableString(value.stage_id) &&
    isNullableString(value.parent_task_id) &&
    isNullableString(value.assignee_user_id) &&
    taskStatuses.includes(value.status as (typeof taskStatuses)[number]) &&
    isNullableString(value.blocked_reason) &&
    priorities.includes(value.priority as (typeof priorities)[number]) &&
    isNullableString(value.start_date) &&
    isNullableString(value.due_date) &&
    isNullableString(value.completed_at) &&
    isStringArray(value.dependency_task_ids) &&
    isStringArray(value.unresolved_dependency_ids) &&
    readinessValues.includes(value.readiness as (typeof readinessValues)[number])
  );
}

export function isProjectIssue(value: unknown): value is ProjectIssue {
  if (!isRecord(value) || !isCommonWorkItem(value)) return false;
  return (
    isNullableString(value.stage_id) &&
    isNullableString(value.owner_user_id) &&
    typeof value.reported_by_user_id === "string" &&
    issueStatuses.includes(value.status as (typeof issueStatuses)[number]) &&
    priorities.includes(value.severity as (typeof priorities)[number]) &&
    isNullableString(value.root_cause) &&
    isNullableString(value.resolution) &&
    isNullableString(value.target_date) &&
    isNullableString(value.closed_at)
  );
}

export function isProjectRisk(value: unknown): value is ProjectRisk {
  if (!isRecord(value) || !isCommonWorkItem(value)) return false;
  return (
    isNullableString(value.owner_user_id) &&
    riskStatuses.includes(value.status as (typeof riskStatuses)[number]) &&
    Number.isInteger(value.likelihood) &&
    Number.isInteger(value.impact) &&
    Number.isInteger(value.score) &&
    isNullableString(value.mitigation_plan) &&
    isNullableString(value.contingency_plan) &&
    isNullableString(value.target_date) &&
    isNullableString(value.closed_at)
  );
}

async function errorMessage(response: Response): Promise<string> {
  try {
    const body = await responseBody(response);
    if (isRecord(body) && isRecord(body.detail) && typeof body.detail.message === "string") {
      return body.detail.message.slice(0, 240);
    }
  } catch {
    // The fallback below deliberately keeps opaque upstream failures bounded.
  }
  return `Work-item request failed (${response.status})`;
}

async function readItem<T>(response: Response, guard: (value: unknown) => value is T, label: string) {
  if (!response.ok) throw new Error(await errorMessage(response));
  const body = await responseBody(response);
  if (!guard(body)) throw new Error(`invalid ${label} response`);
  return body;
}

async function readList<T>(response: Response, guard: (value: unknown) => value is T, label: string) {
  if (!response.ok) throw new Error(await errorMessage(response));
  const body = await responseBody(response);
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(guard)) {
    throw new Error(`invalid ${label} list response`);
  }
  return body.items;
}

function collectionUrl(projectId: string, collection: "tasks" | "issues" | "risks") {
  return `/api/projects/${encodeURIComponent(projectId)}/${collection}`;
}

function mutation(body: object): RequestInit {
  return {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(body),
  };
}

export async function requestProjectWorkItems(projectId: string): Promise<ProjectWorkItems> {
  const [tasksResponse, issuesResponse, risksResponse] = await Promise.all([
    fetch(collectionUrl(projectId, "tasks"), { cache: "no-store", credentials: "same-origin" }),
    fetch(collectionUrl(projectId, "issues"), { cache: "no-store", credentials: "same-origin" }),
    fetch(collectionUrl(projectId, "risks"), { cache: "no-store", credentials: "same-origin" }),
  ]);
  const [tasks, issues, risks] = await Promise.all([
    readList(tasksResponse, isProjectTask, "Task"),
    readList(issuesResponse, isProjectIssue, "Issue"),
    readList(risksResponse, isProjectRisk, "Risk"),
  ]);
  return { tasks, issues, risks };
}

export async function requestProjectRisks(projectId: string): Promise<ProjectRisk[]> {
  return readList(
    await fetch(collectionUrl(projectId, "risks"), { cache: "no-store", credentials: "same-origin" }),
    isProjectRisk,
    "Risk",
  );
}

export async function createTask(projectId: string, input: TaskCreateInput) {
  return readItem(await fetch(collectionUrl(projectId, "tasks"), mutation(input)), isProjectTask, "Task");
}

export async function createIssue(projectId: string, input: IssueCreateInput) {
  return readItem(await fetch(collectionUrl(projectId, "issues"), mutation(input)), isProjectIssue, "Issue");
}

export async function createRisk(projectId: string, input: RiskCreateInput) {
  return readItem(await fetch(collectionUrl(projectId, "risks"), mutation(input)), isProjectRisk, "Risk");
}

function transitionUrl(projectId: string, collection: "tasks" | "issues" | "risks", itemId: string) {
  return `${collectionUrl(projectId, collection)}/${encodeURIComponent(itemId)}/transitions`;
}

export async function transitionTask(projectId: string, taskId: string, input: TaskTransitionInput) {
  return readItem(await fetch(transitionUrl(projectId, "tasks", taskId), mutation(input)), isProjectTask, "Task");
}

export async function transitionIssue(projectId: string, issueId: string, toStatus: IssueStatus) {
  return readItem(
    await fetch(transitionUrl(projectId, "issues", issueId), mutation({ to_status: toStatus })),
    isProjectIssue,
    "Issue",
  );
}

export async function transitionRisk(projectId: string, riskId: string, toStatus: RiskStatus) {
  return readItem(
    await fetch(transitionUrl(projectId, "risks", riskId), mutation({ to_status: toStatus })),
    isProjectRisk,
    "Risk",
  );
}
