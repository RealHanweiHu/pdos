import { isRecord, responseBody } from "@/components/workspace-api";

export type CostType = "material" | "labor" | "tooling" | "logistics" | "other";
export type CostStatus = "estimate" | "approved" | "actual";
export type ResourceType = "person" | "equipment" | "facility" | "capability";
export type ResourceStatus = "planned" | "active" | "released";

export type ProjectCost = {
  id: string;
  project_id: string;
  code: string;
  cost_type: CostType;
  /** Decimal string with two places, e.g. "1200.50". */
  amount: string;
  currency: string;
  status: CostStatus;
  incurred_on: string | null;
  description: string | null;
  created_at: string;
  updated_at: string;
};

export type ProjectResource = {
  id: string;
  project_id: string;
  code: string;
  name: string;
  resource_type: ResourceType;
  assigned_user_id: string | null;
  allocation_percent: string;
  start_date: string | null;
  end_date: string | null;
  status: ResourceStatus;
  /** The assignee's active allocation summed across all tenant projects. */
  assignee_active_allocation_percent: string | null;
  created_at: string;
  updated_at: string;
};

export type CostCreateInput = {
  cost_type: CostType;
  amount: string;
  currency?: string;
  incurred_on?: string;
  description?: string;
};

export type ResourceCreateInput = {
  name: string;
  resource_type: ResourceType;
  assigned_user_id?: string;
  allocation_percent: string;
  start_date?: string;
  end_date?: string;
};

const costTypes = ["material", "labor", "tooling", "logistics", "other"];
const costStatuses = ["estimate", "approved", "actual"];
const resourceTypes = ["person", "equipment", "facility", "capability"];
const resourceStatuses = ["planned", "active", "released"];

const nullableString = (value: unknown) => typeof value === "string" || value === null;

export function isProjectCost(value: unknown): value is ProjectCost {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.project_id === "string" &&
    typeof value.code === "string" &&
    costTypes.includes(String(value.cost_type)) &&
    typeof value.amount === "string" &&
    typeof value.currency === "string" &&
    costStatuses.includes(String(value.status)) &&
    nullableString(value.incurred_on) &&
    nullableString(value.description) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

export function isProjectResource(value: unknown): value is ProjectResource {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.project_id === "string" &&
    typeof value.code === "string" &&
    typeof value.name === "string" &&
    resourceTypes.includes(String(value.resource_type)) &&
    nullableString(value.assigned_user_id) &&
    typeof value.allocation_percent === "string" &&
    nullableString(value.start_date) &&
    nullableString(value.end_date) &&
    resourceStatuses.includes(String(value.status)) &&
    nullableString(value.assignee_active_allocation_percent) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

const errorMessages: Record<string, string> = {
  REGISTER_RECORD_LOCKED: "该记录已不可修改。",
  REGISTER_INVALID_TRANSITION: "状态变更不符合流程，请刷新后重试。",
  REGISTER_ASSIGNEE_NOT_MEMBER: "负责人必须是本项目的内部成员。",
  REGISTER_DATE_ORDER: "结束日期不能早于开始日期。",
  PROJECT_ACCESS_DENIED: "你没有执行该操作的权限。",
};

export class RegisterRequestError extends Error {
  constructor(message: string, readonly status: number) {
    super(message);
  }
}

async function read<T>(response: Response, guard: (value: unknown) => value is T): Promise<T> {
  if (!response.ok) {
    let message = `请求失败（${response.status}），请稍后重试。`;
    try {
      const body = await responseBody(response);
      if (isRecord(body) && isRecord(body.detail) && typeof body.detail.code === "string") {
        message = errorMessages[body.detail.code] ?? message;
      }
    } catch {
      // Keep the bounded generic message.
    }
    throw new RegisterRequestError(message, response.status);
  }
  const body = await responseBody(response);
  if (!guard(body)) throw new Error("invalid register response");
  return body;
}

function url(projectId: string, collection: "costs" | "resources", ...segments: string[]) {
  return [`/api/projects/${encodeURIComponent(projectId)}/${collection}`, ...segments.map(encodeURIComponent)].join("/");
}

function send(method: "POST" | "PATCH", body: object): RequestInit {
  return { method, credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) };
}

function listGuard<T>(guard: (value: unknown) => value is T) {
  return (value: unknown): value is { items: T[] } =>
    isRecord(value) && Array.isArray(value.items) && value.items.every(guard);
}

export async function requestCosts(projectId: string) {
  return (await read(await fetch(url(projectId, "costs"), { cache: "no-store", credentials: "same-origin" }), listGuard(isProjectCost))).items;
}

export async function requestResources(projectId: string) {
  return (await read(await fetch(url(projectId, "resources"), { cache: "no-store", credentials: "same-origin" }), listGuard(isProjectResource))).items;
}

export async function createCost(projectId: string, input: CostCreateInput) {
  return read(await fetch(url(projectId, "costs"), send("POST", input)), isProjectCost);
}

export async function transitionCost(projectId: string, costId: string, toStatus: "approved" | "actual") {
  return read(await fetch(url(projectId, "costs", costId, "transitions"), send("POST", { to_status: toStatus })), isProjectCost);
}

export async function createResource(projectId: string, input: ResourceCreateInput) {
  return read(await fetch(url(projectId, "resources"), send("POST", input)), isProjectResource);
}

export async function transitionResource(projectId: string, resourceId: string, toStatus: "active" | "released") {
  return read(await fetch(url(projectId, "resources", resourceId, "transitions"), send("POST", { to_status: toStatus })), isProjectResource);
}
