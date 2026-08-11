import type {
  CustomerSummary,
  Requirement,
  WorkspaceIdentity,
} from "./requirement-types";

export type LoadedPool = {
  identity: WorkspaceIdentity;
  requirements: Requirement[];
  customers: CustomerSummary[];
};

function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

function isWorkspaceIdentity(value: unknown): value is WorkspaceIdentity {
  if (!isRecord(value) || !isRecord(value.tenant) || !isRecord(value.user)) return false;
  return (
    typeof value.tenant.id === "string" &&
    typeof value.tenant.slug === "string" &&
    typeof value.tenant.name === "string" &&
    typeof value.user.id === "string" &&
    typeof value.user.tenant_id === "string" &&
    typeof value.user.username === "string" &&
    typeof value.user.display_name === "string" &&
    typeof value.user.role === "string" &&
    (typeof value.user.email === "string" || value.user.email === null) &&
    typeof value.user.is_active === "boolean"
  );
}

function isCustomer(value: unknown): value is CustomerSummary {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.code === "string" &&
    typeof value.name === "string" &&
    (value.status === "active" || value.status === "inactive")
  );
}

function isRequirement(value: unknown): value is Requirement {
  if (!isRecord(value)) return false;
  return (
    typeof value.id === "string" &&
    typeof value.code === "string" &&
    typeof value.title === "string" &&
    (typeof value.description === "string" || value.description === null) &&
    (typeof value.source === "string" || value.source === null) &&
    ["draft", "proposed", "approved", "rejected", "converted"].includes(
      String(value.status),
    ) &&
    ["low", "medium", "high", "critical"].includes(String(value.priority)) &&
    Array.isArray(value.acceptance_criteria) &&
    value.acceptance_criteria.every((criterion) => typeof criterion === "string") &&
    (value.customer === null || isCustomer(value.customer)) &&
    (typeof value.created_by_user_id === "string" || value.created_by_user_id === null) &&
    typeof value.created_at === "string" &&
    typeof value.updated_at === "string"
  );
}

async function responseBody(response: Response): Promise<unknown> {
  return response.json();
}

async function itemList<T>(
  response: Response,
  guard: (value: unknown) => value is T,
): Promise<T[]> {
  const body = await responseBody(response);
  if (!isRecord(body) || !Array.isArray(body.items) || !body.items.every(guard)) {
    throw new Error("invalid list response");
  }
  return body.items;
}

export async function readRequirement(response: Response): Promise<Requirement> {
  const body = await responseBody(response);
  if (!isRequirement(body)) throw new Error("invalid requirement response");
  return body;
}

export async function requestPool(): Promise<LoadedPool | null> {
  const identityResponse = await fetch("/api/session/me", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (identityResponse.status === 401) return null;
  if (!identityResponse.ok) throw new Error("identity unavailable");
  const identityBody = await responseBody(identityResponse);
  if (!isWorkspaceIdentity(identityBody)) throw new Error("invalid identity response");

  const [requirementsResponse, customersResponse] = await Promise.all([
    fetch("/api/requirements", { cache: "no-store", credentials: "same-origin" }),
    fetch("/api/customers", { cache: "no-store", credentials: "same-origin" }),
  ]);
  if (requirementsResponse.status === 401 || customersResponse.status === 401) return null;
  if (!requirementsResponse.ok || !customersResponse.ok) {
    throw new Error("requirement pool unavailable");
  }
  const [requirements, customers] = await Promise.all([
    itemList(requirementsResponse, isRequirement),
    itemList(customersResponse, isCustomer),
  ]);
  return { identity: identityBody, requirements, customers };
}
