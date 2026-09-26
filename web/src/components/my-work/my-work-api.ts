import { isRecord, responseBody } from "@/components/workspace-api";

import type {
  MyNotification,
  MyNotifications,
  MyWork,
  MyWorkCounts,
  MyWorkCollection,
  MyWorkProjectRef,
} from "./my-work-types";

export class MyWorkForbiddenError extends Error {}

function isProjectRef(value: unknown): value is MyWorkProjectRef {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.code === "string" &&
    typeof value.name === "string"
  );
}

function hasStrings(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every((key) => typeof value[key] === "string");
}

function hasNullableStrings(value: Record<string, unknown>, keys: readonly string[]): boolean {
  return keys.every((key) => typeof value[key] === "string" || value[key] === null);
}

const itemGuards: Record<MyWorkCollection, (value: unknown) => boolean> = {
  tasks: (value) =>
    isRecord(value) &&
    isProjectRef(value.project) &&
    hasStrings(value, ["id", "title", "status", "priority"]) &&
    hasNullableStrings(value, ["due_date"]),
  issues: (value) =>
    isRecord(value) &&
    isProjectRef(value.project) &&
    hasStrings(value, ["id", "title", "status", "severity"]) &&
    hasNullableStrings(value, ["target_date"]),
  risks: (value) =>
    isRecord(value) &&
    isProjectRef(value.project) &&
    hasStrings(value, ["id", "title", "status"]) &&
    typeof value.likelihood === "number" &&
    typeof value.impact === "number" &&
    hasNullableStrings(value, ["target_date"]),
  capa_actions: (value) =>
    isRecord(value) &&
    isProjectRef(value.project) &&
    hasStrings(value, ["id", "ncr_id", "action_type", "description", "status", "due_date"]),
  gate_signoffs: (value) =>
    isRecord(value) &&
    isProjectRef(value.project) &&
    hasStrings(value, ["id", "gate_id", "gate_code", "gate_name", "slot", "requirement"]) &&
    typeof value.round_number === "number" &&
    hasNullableStrings(value, ["review_due_at"]),
  cost_freeze_approvals: value => isRecord(value) && isProjectRef(value.project) && hasStrings(value, ["id", "title", "created_at"]),
  task_takeover_actions: value => isRecord(value) && isProjectRef(value.project) &&
    hasStrings(value, ["id", "task_id", "title", "priority", "status", "created_at"]) &&
    hasNullableStrings(value, ["due_date"]) &&
    (value.mode === "review" || value.mode === "revise") &&
    typeof value.revision === "number" && Number.isSafeInteger(value.revision) && value.revision > 0,
  risk_followup_actions: value => isRecord(value) && isProjectRef(value.project) &&
    hasStrings(value, ["id", "risk_id", "task_id", "title", "created_at"]) &&
    (value.mode === "review" || value.mode === "submit"),
  change_execution_confirmations: value => isRecord(value) && isProjectRef(value.project) &&
    hasStrings(value,["id","binding_id","ecr_id","task_id","ecr_code","title","created_at"]) &&
    ["retest","rereview","recertification","coordination"].includes(String(value.action)) &&
    typeof value.revision_number === "number" && Number.isSafeInteger(value.revision_number) && value.revision_number > 0,
  id_design_actions: (value) =>
    isRecord(value) &&
    isProjectRef(value.project) &&
    hasStrings(value, ["id", "revision_id", "title", "created_at"]) &&
    hasNullableStrings(value, ["freeze_id"]) &&
    (value.kind === "freeze" || value.kind === "handoff"),
  cross_schedule_approvals: (value) =>
    isRecord(value) &&
    isProjectRef(value.project) &&
    hasStrings(value, ["id", "title", "created_at"]) &&
    (value.operation === "add" || value.operation === "remove" || value.operation === "replace"),
  findings: (value) =>
    isRecord(value) &&
    isProjectRef(value.project) &&
    hasStrings(value, ["id", "finding_type", "title", "created_at"]) &&
    (value.status === undefined || value.status === "pending_review" || value.status === "accepted"),
};

const countKeys: readonly (keyof MyWorkCounts)[] = [
  "tasks",
  "issues",
  "risks",
  "capa_actions",
  "gate_signoffs",
  "findings",
];

function isNotification(value: unknown): value is MyNotification {
  return (
    isRecord(value) &&
    isProjectRef(value.project) &&
    hasStrings(value, ["id", "policy_key", "target_entity", "target_entity_id", "title", "status", "fire_at"]) &&
    typeof value.escalation_level === "number" &&
    hasNullableStrings(value, ["fired_at", "acknowledged_at"])
  );
}

export async function requestMyNotifications(): Promise<MyNotifications | null> {
  const response = await fetch("/api/me/notifications", {
    cache: "no-store",
    credentials: "same-origin",
  });
  if (response.status === 401) return null;
  if (response.status === 403) throw new MyWorkForbiddenError("notifications unavailable for this role");
  if (!response.ok) throw new Error(`Notifications request failed (${response.status})`);
  const body = await responseBody(response);
  if (
    !isRecord(body) ||
    !Array.isArray(body.items) ||
    typeof body.unread_count !== "number" ||
    !Array.isArray(body.digest)
  ) {
    throw new Error("invalid notifications response");
  }
  return {
    items: body.items.filter((item) => {
      if (isNotification(item)) return true;
      console.warn("[my-work-api] skipped malformed notification item");
      return false;
    }) as MyNotification[],
    unread_count: body.unread_count,
    digest: body.digest.filter(
      (entry): entry is { policy_key: string; count: number } =>
        isRecord(entry) && typeof entry.policy_key === "string" && typeof entry.count === "number",
    ),
  };
}

export async function acknowledgeNotification(notificationId: string): Promise<void> {
  const response = await fetch(
    `/api/me/notifications/${encodeURIComponent(notificationId)}/ack`,
    { method: "POST", cache: "no-store", credentials: "same-origin" },
  );
  if (!response.ok) throw new Error(`Notification acknowledge failed (${response.status})`);
}

export type MyWorkQuery = { collection?: MyWorkCollection; offset?: number; expected_revision?: string; limit?: number; project_id?: string; search?: string; focus?: "all" | "overdue" | "today" | "blocked" | "high" | "confirm"; as_of_date?: string };
export async function requestMyWork(page?: MyWorkQuery): Promise<MyWork | null> {
  const query = new URLSearchParams();
  if (page) for (const [key, value] of Object.entries(page)) if (value !== undefined) query.set(key, String(value));
  const response = await fetch(`/api/me/work${query.size ? `?${query}` : ""}`, { cache: "no-store", credentials: "same-origin" });
  if (response.status === 401) return null;
  if (response.status === 403) throw new MyWorkForbiddenError("my work is not available for this role");
  if (response.status === 409) throw new Error("待办内容或顺序已变化，请刷新本类工作后继续加载。");
  if (!response.ok) throw new Error(`工作列表读取失败（${response.status}），请重试。`);
  const body = await responseBody(response);
  if (!isRecord(body) || !isRecord(body.counts)) throw new Error("invalid My Work response");
  const counts = body.counts;
  if (!countKeys.every((key) => typeof counts[key] === "number" && Number.isSafeInteger(counts[key]))) {
    throw new Error("invalid My Work counts");
  }
  for (const key of ["id_design_actions", "cross_schedule_approvals", "change_execution_confirmations", "risk_followup_actions", "task_takeover_actions", "cost_freeze_approvals"] as const) {
    if (counts[key] !== undefined &&
        (typeof counts[key] !== "number" || !Number.isSafeInteger(counts[key]))) {
      throw new Error("invalid My Work counts");
    }
  }
  const result: Record<string, unknown> = { counts };
  if (body.pages !== undefined) {
    if (!isRecord(body.pages)) throw new Error("invalid My Work pages");
    for (const [key, value] of Object.entries(body.pages)) {
      if (!(key in itemGuards) || !isRecord(value) ||
          typeof value.offset !== "number" || !Number.isSafeInteger(value.offset) || value.offset < 0 ||
          !(value.next_offset === null || typeof value.next_offset === "number" && Number.isSafeInteger(value.next_offset) && value.next_offset > value.offset) ||
          typeof value.revision !== "string" || !/^[a-f0-9]{32}$/.test(value.revision)) {
        throw new Error("invalid My Work page cursor");
      }
    }
    result.pages = body.pages;
  }
  for (const [section, guard] of Object.entries(itemGuards)) {
    const optional = section === "id_design_actions" || section === "cross_schedule_approvals" || section === "change_execution_confirmations" || section === "risk_followup_actions" || section === "task_takeover_actions" || section === "cost_freeze_approvals";
    const items = optional && body[section] === undefined ? [] : body[section];
    if (!Array.isArray(items)) throw new Error("invalid My Work response");
    const valid = items.filter((item) => {
      if (guard(item)) return true;
      console.warn(`[my-work-api] skipped malformed ${section} item`);
      return false;
    });
    if (body.pages !== undefined && valid.length !== items.length) throw new Error("工作列表包含无法读取的内容，请刷新后重试。");
    result[section] = valid;
  }
  return result as MyWork;
}
