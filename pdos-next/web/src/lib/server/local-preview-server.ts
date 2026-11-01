import "server-only";
import { readFile } from "node:fs/promises";
import type { PreviewCatalog, PreviewRole } from "./local-preview-types";

type PrivateCatalog = Omit<PreviewCatalog, "roles"> & { roles: (PreviewRole & { token: string })[]; workspace?: { roleId: string } };
/** One server-selected persona for the whole product, never selected by a page's scope. */
export function workspacePreview(value: PrivateCatalog) {
  if (!value.workspace) return null;
  const role = value.roles.find(item => item.id === value.workspace?.roleId);
  const scope = value.cases.find(item => item.id === role?.caseId && item.roleIds.includes(role.id));
  if (!role || !scope) throw new Error("产品预览身份尚未配置。");
  return { role, href: `/?${new URLSearchParams({ area: "work", category: scope.categoryId })}` };
}
export function localPreviewHost(host: string | null): boolean {
  return /^(localhost|127\.0\.0\.1)(:\d+)?$/.test(host ?? "");
}
export async function loadLocalPreview(host: string | null): Promise<PrivateCatalog | null> {
  const path = process.env.PDOS_NEXT_PREVIEW_CONFIG;
  if (!localPreviewHost(host) || !path) return null;
  const value = JSON.parse(await readFile(path, "utf8")) as PrivateCatalog;
  if (value.version !== 1 || !Array.isArray(value.cases) || !Array.isArray(value.roles) || !Number.isFinite(Date.parse(value.expires_at)) || Date.parse(value.expires_at) <= Date.now()) throw new Error("预览会话已到期，请重新准备本地演示环境。");
  return value;
}
/** Explicit allowlist: private runtime fields and tokens never become page props. */
export function publicPreview(value: PrivateCatalog): PreviewCatalog {
  return {
    version: 1, created_at: value.created_at, expires_at: value.expires_at,
    cases: value.cases.map(({ id, title, summary, limit, categoryId, productId, projectId, projectName, roleIds, entries, counts }) => ({ id, title, summary, limit, categoryId, productId, projectId, projectName, roleIds, entries, counts })),
    roles: value.roles.map(({ id, caseId, label, name, principalId, tenantId }) => ({ id, caseId, label, name, principalId, tenantId })),
  };
}
