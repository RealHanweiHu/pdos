import { isRecord, requestIdentity, responseBody } from "@/components/workspace-api";
import type { WorkspaceIdentity } from "@/components/workspace-types";

import { USER_ROLES } from "./user-management-types";
import type { ManagedUser, UserCreate, UserRole, UserUpdate } from "./user-management-types";

const ADMIN_ROLES = new Set(["owner", "admin"]);

function isRole(value: unknown): value is UserRole {
  return typeof value === "string" && USER_ROLES.includes(value as UserRole);
}

function parseManagedUser(value: unknown): ManagedUser {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.tenant_id !== "string" ||
    typeof value.username !== "string" ||
    typeof value.display_name !== "string" ||
    (typeof value.email !== "string" && value.email !== null) ||
    !isRole(value.role) ||
    typeof value.is_active !== "boolean" ||
    (typeof value.last_signed_in_at !== "string" && value.last_signed_in_at !== null) ||
    typeof value.created_at !== "string" ||
    typeof value.updated_at !== "string"
  ) {
    throw new Error("invalid managed user response");
  }
  return {
    id: value.id,
    tenant_id: value.tenant_id,
    username: value.username,
    display_name: value.display_name,
    email: value.email,
    role: value.role,
    is_active: value.is_active,
    last_signed_in_at: value.last_signed_in_at,
    created_at: value.created_at,
    updated_at: value.updated_at,
  };
}

async function managedUserResponse(response: Response): Promise<ManagedUser | null> {
  if (response.status === 401) return null;
  if (!response.ok) throw new Error("user administration unavailable");
  return parseManagedUser(await responseBody(response));
}

async function userListResponse(response: Response): Promise<ManagedUser[] | null> {
  if (response.status === 401) return null;
  const body = await responseBody(response);
  if (!response.ok || !isRecord(body) || !Array.isArray(body.items)) {
    throw new Error("user administration unavailable");
  }
  return body.items.map(parseManagedUser);
}

export type UserManagementBootstrap =
  | { kind: "forbidden"; identity: WorkspaceIdentity }
  | { kind: "ready"; identity: WorkspaceIdentity; users: ManagedUser[] };

export async function requestUserManagementBootstrap(): Promise<UserManagementBootstrap | null> {
  const identity = await requestIdentity();
  if (identity === null) return null;
  if (!ADMIN_ROLES.has(identity.user.role)) return { kind: "forbidden", identity };
  const users = await userListResponse(
    await fetch("/api/admin/users", { cache: "no-store", credentials: "same-origin" }),
  );
  return users === null ? null : { kind: "ready", identity, users };
}

export async function createManagedUser(payload: UserCreate) {
  return managedUserResponse(
    await fetch("/api/admin/users", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function updateManagedUser(userId: string, payload: UserUpdate) {
  return managedUserResponse(
    await fetch(`/api/admin/users/${encodeURIComponent(userId)}`, {
      method: "PATCH",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
  );
}

export async function resetManagedUserPassword(userId: string, password: string) {
  return managedUserResponse(
    await fetch(`/api/admin/users/${encodeURIComponent(userId)}/reset-password`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ password }),
    }),
  );
}
