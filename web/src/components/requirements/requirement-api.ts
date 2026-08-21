import { isRecord, requestIdentity, responseBody } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import type { CustomerSummary, Requirement } from "./requirement-types";

export type LoadedPool = {
  identity: WorkspaceIdentity;
  requirements: Requirement[];
  customers: CustomerSummary[];
};

export type CustomerCreateInput = { code: string; name: string };

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
  const identity = await requestIdentity();
  if (identity === null) return null;

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
  return { identity, requirements, customers };
}

export async function createCustomer(input: CustomerCreateInput): Promise<CustomerSummary> {
  const response = await fetch("/api/customers", {
    method: "POST",
    credentials: "same-origin",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(input),
  });
  if (!response.ok) throw new Error("客户创建失败，请检查编号是否重复。");
  const body = await responseBody(response);
  if (!isCustomer(body)) throw new Error("invalid customer response");
  return body;
}
