import { restoreProjectDraft, type LocalProjectDraft } from "@/lib/project-plan-view";

export const projectCreationMoved = "独立项目创建入口已迁至立项提案的 G0 决定。已清除旧创建请求，其他计划输入仍保留。";

/** Retire only the obsolete command before validating the retained plan draft. */
export function restorePlanningDraft(value: unknown, productId: string, projectId = ""): (LocalProjectDraft & { retiredCreation: boolean }) | null {
  if (!value || typeof value !== "object" || Array.isArray(value)) return null;
  const record = value as Record<string, unknown>;
  const pending = record.pending;
  const command = pending && typeof pending === "object" && "command" in pending ? pending.command : null;
  const retiredCreation = !!command && typeof command === "object" && "operation" in command && command.operation === "project.create";
  const local = restoreProjectDraft(retiredCreation ? { ...record, pending: null } : record, productId);
  if (local && projectId && (local.draft.projectId !== projectId || (local.pending && (!("project_id" in local.pending.command.payload) || local.pending.command.payload.project_id !== projectId)))) return null;
  return local ? { ...local, retiredCreation } : null;
}

export function planningStorageKey(principalId: string, productId: string, projectId = ""): string {
  return `pdos-next:project-plan:${principalId}:${productId}${projectId ? `:${projectId}` : ""}`;
}
