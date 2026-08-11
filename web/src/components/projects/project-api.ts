import { isRecord, requestIdentity, responseBody } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import type { Project, ProjectStage, ProjectWorkflow } from "./project-types";

export type LoadedProjects = { identity: WorkspaceIdentity; projects: Project[] };

function isProjectStage(value: unknown): value is ProjectStage {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.code === "string" &&
    typeof value.name === "string" &&
    (typeof value.description === "string" || value.description === null) &&
    typeof value.sequence === "number"
  );
}

function isProjectWorkflow(value: unknown): value is ProjectWorkflow {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.code === "string" &&
    typeof value.name === "string" &&
    (typeof value.description === "string" || value.description === null) &&
    typeof value.version === "number" &&
    typeof value.is_active === "boolean" &&
    Array.isArray(value.stages) &&
    value.stages.every(isProjectStage)
  );
}

export function isProject(value: unknown): value is Project {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.development_case_id === "string" &&
    (typeof value.customer_id === "string" || value.customer_id === null) &&
    isProjectWorkflow(value.workflow) &&
    isProjectStage(value.current_stage) &&
    typeof value.owner_user_id === "string" &&
    typeof value.code === "string" &&
    typeof value.name === "string" &&
    (typeof value.description === "string" || value.description === null) &&
    ["draft", "proposed", "approved", "active", "on_hold", "completed", "archived"].includes(
      String(value.status),
    ) &&
    (typeof value.start_date === "string" || value.start_date === null) &&
    (typeof value.target_date === "string" || value.target_date === null) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

export async function readProject(response: Response): Promise<Project> {
  const body = await responseBody(response);
  if (!isProject(body)) throw new Error("invalid Project response");
  return body;
}

export async function requestProjects(): Promise<LoadedProjects | null> {
  const identity = await requestIdentity();
  if (identity === null) return null;
  const response = await fetch("/api/projects", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("Project workspace unavailable");
  const body = await responseBody(response);
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(isProject)) {
    throw new Error("invalid Project list response");
  }
  return { identity, projects: body.items };
}
