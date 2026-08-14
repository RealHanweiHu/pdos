import type { WorkspaceIdentity } from "./workspace-types";

export function isRecord(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value);
}

export async function responseBody(response: Response): Promise<unknown> {
  return response.json();
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

export async function requestIdentity(): Promise<WorkspaceIdentity | null> {
  const response = await fetch("/api/session/me", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("identity unavailable");
  const body = await responseBody(response);
  if (!isWorkspaceIdentity(body)) throw new Error("invalid identity response");
  return body;
}
