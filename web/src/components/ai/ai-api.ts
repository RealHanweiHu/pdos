import { isRecord, responseBody } from "@/components/workspace-api";

import {
  FINDING_STATUSES,
  FINDING_TYPES,
  type AiBrief,
  type AiBriefItem,
  type AiChatResponse,
  type AiFinding,
  type AiQualityControl,
  type ChatCitation,
  type FindingEvidence,
  type FindingStatus,
  type FindingType,
} from "./ai-types";

function isStringOrNull(value: unknown): value is string | null {
  return typeof value === "string" || value === null;
}

function isFindingType(value: unknown): value is FindingType {
  return typeof value === "string" && FINDING_TYPES.includes(value as FindingType);
}

function isFindingStatus(value: unknown): value is FindingStatus {
  return typeof value === "string" && FINDING_STATUSES.includes(value as FindingStatus);
}

export function isSafePdosHref(value: unknown): value is string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) {
    return false;
  }
  try {
    const parsed = new URL(value, "https://pdos.invalid");
    return parsed.origin === "https://pdos.invalid" && ["/projects", "/ai-review"].includes(parsed.pathname);
  } catch {
    return false;
  }
}

function parseEvidence(value: unknown): FindingEvidence {
  if (
    !isRecord(value) ||
    typeof value.event_row_id !== "number" ||
    !Number.isSafeInteger(value.event_row_id) ||
    typeof value.label !== "string" ||
    !isSafePdosHref(value.href)
  ) {
    throw new Error("invalid Finding evidence");
  }
  return { event_row_id: value.event_row_id, label: value.label, href: value.href };
}

function parseFinding(value: unknown): AiFinding {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.project_id !== "string" ||
    typeof value.run_id !== "string" ||
    typeof value.model_invocation_id !== "string" ||
    typeof value.agent_key !== "string" ||
    !isFindingType(value.finding_type) ||
    typeof value.origin_key !== "string" ||
    !isFindingStatus(value.status) ||
    typeof value.title !== "string" ||
    typeof value.summary !== "string" ||
    !isRecord(value.proposed_payload) ||
    !(isRecord(value.accepted_payload) || value.accepted_payload === null) ||
    !Array.isArray(value.evidence_event_ids) ||
    !value.evidence_event_ids.every((item) => typeof item === "number" && Number.isSafeInteger(item)) ||
    !Array.isArray(value.evidence) ||
    typeof value.confidence_basis_points !== "number" ||
    !Number.isSafeInteger(value.confidence_basis_points) ||
    typeof value.preflight_version !== "string" ||
    !isStringOrNull(value.reviewed_by_user_id) ||
    !isStringOrNull(value.reviewed_at) ||
    !isStringOrNull(value.review_comment) ||
    !isStringOrNull(value.applied_by_user_id) ||
    !isStringOrNull(value.applied_at) ||
    !isStringOrNull(value.applied_entity_type) ||
    !isStringOrNull(value.applied_entity_id) ||
    typeof value.created_at !== "string" ||
    typeof value.updated_at !== "string"
  ) {
    throw new Error("invalid Finding response");
  }
  return {
    ...(value as Omit<AiFinding, "evidence" | "finding_type" | "status">),
    finding_type: value.finding_type,
    status: value.status,
    evidence: value.evidence.map(parseEvidence),
  };
}

function parseBriefItem(value: unknown): AiBriefItem {
  if (
    !isRecord(value) ||
    typeof value.finding_id !== "string" ||
    typeof value.project_id !== "string" ||
    !isFindingType(value.finding_type) ||
    !isFindingStatus(value.finding_status) ||
    typeof value.title !== "string" ||
    typeof value.summary !== "string" ||
    !Array.isArray(value.evidence) ||
    typeof value.created_at !== "string" ||
    !isSafePdosHref(value.href)
  ) {
    throw new Error("invalid AI brief item");
  }
  return {
    finding_id: value.finding_id,
    project_id: value.project_id,
    finding_type: value.finding_type,
    finding_status: value.finding_status,
    title: value.title,
    summary: value.summary,
    evidence: value.evidence.map(parseEvidence),
    created_at: value.created_at,
    href: value.href,
  };
}

function parseCitation(value: unknown): ChatCitation {
  if (
    !isRecord(value) ||
    typeof value.reference_id !== "string" ||
    typeof value.entity !== "string" ||
    typeof value.entity_id !== "string" ||
    typeof value.label !== "string" ||
    !isSafePdosHref(value.href) ||
    typeof value.excerpt !== "string"
  ) {
    throw new Error("invalid chat citation");
  }
  return value as ChatCitation;
}

function parseQualityControl(value: unknown): AiQualityControl {
  if (
    !isRecord(value) ||
    typeof value.agent_key !== "string" ||
    !isFindingType(value.finding_type) ||
    (value.status !== "active" && value.status !== "narrowed") ||
    ![
      "minimum_review_count",
      "acceptance_threshold_basis_points",
      "reviewed_count",
      "accepted_count",
      "applied_count",
    ].every(
      (key) => typeof value[key] === "number" && Number.isSafeInteger(value[key]),
    ) ||
    !(
      value.acceptance_rate_basis_points === null ||
      (typeof value.acceptance_rate_basis_points === "number" &&
        Number.isSafeInteger(value.acceptance_rate_basis_points))
    ) ||
    !isStringOrNull(value.narrowed_at) ||
    !isStringOrNull(value.narrowed_reason)
  ) {
    throw new Error("invalid AI quality control");
  }
  return value as AiQualityControl;
}

async function requireOk(response: Response, fallback: string): Promise<unknown> {
  if (!response.ok) {
    const body = await responseBody(response).catch(() => null);
    const detail = isRecord(body) && isRecord(body.detail) ? body.detail : null;
    throw new Error(detail && typeof detail.message === "string" ? detail.message : fallback);
  }
  return responseBody(response);
}

export async function requestFindings(filters: {
  projectId?: string;
  status?: FindingStatus;
} = {}): Promise<AiFinding[]> {
  const query = new URLSearchParams();
  if (filters.projectId) query.set("project_id", filters.projectId);
  if (filters.status) query.set("status", filters.status);
  const suffix = query.size > 0 ? `?${query.toString()}` : "";
  const body = await requireOk(
    await fetch(`/api/ai/findings${suffix}`, { cache: "no-store", credentials: "same-origin" }),
    "AI Review 收件箱暂不可用",
  );
  if (!isRecord(body) || !Array.isArray(body.items)) throw new Error("invalid Finding list");
  return body.items.map(parseFinding);
}

export async function reviewFinding(
  findingId: string,
  payload: {
    decision: "accepted" | "rejected";
    edited_payload?: Record<string, unknown>;
    comment?: string;
  },
): Promise<AiFinding> {
  const body = await requireOk(
    await fetch(`/api/ai/findings/${encodeURIComponent(findingId)}/review`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    }),
    "Finding 裁决失败",
  );
  return parseFinding(body);
}

export async function applyFinding(findingId: string): Promise<AiFinding> {
  const body = await requireOk(
    await fetch(`/api/ai/findings/${encodeURIComponent(findingId)}/apply`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
    }),
    "Finding 应用失败",
  );
  if (!isRecord(body)) throw new Error("invalid Finding apply response");
  return parseFinding(body.finding);
}

export async function requestAiBrief(): Promise<AiBrief> {
  const body = await requireOk(
    await fetch("/api/ai/brief", { cache: "no-store", credentials: "same-origin" }),
    "AI 简报暂不可用",
  );
  if (
    !isRecord(body) ||
    (body.status !== "active" && body.status !== "unavailable") ||
    !isStringOrNull(body.error_code) ||
    typeof body.pending_review_count !== "number" ||
    !Number.isSafeInteger(body.pending_review_count) ||
    !isStringOrNull(body.latest_finding_at) ||
    !["reviewed_count", "accepted_count", "applied_count", "narrowed_output_count"].every(
      (key) => typeof body[key] === "number" && Number.isSafeInteger(body[key]),
    ) ||
    !(
      body.acceptance_rate_basis_points === null ||
      (typeof body.acceptance_rate_basis_points === "number" &&
        Number.isSafeInteger(body.acceptance_rate_basis_points))
    ) ||
    !Array.isArray(body.quality_controls) ||
    !Array.isArray(body.items)
  ) {
    throw new Error("invalid AI brief response");
  }
  return {
    status: body.status,
    error_code: body.error_code,
    pending_review_count: body.pending_review_count,
    latest_finding_at: body.latest_finding_at,
    reviewed_count: body.reviewed_count as number,
    accepted_count: body.accepted_count as number,
    applied_count: body.applied_count as number,
    acceptance_rate_basis_points: body.acceptance_rate_basis_points as number | null,
    narrowed_output_count: body.narrowed_output_count as number,
    quality_controls: body.quality_controls.map(parseQualityControl),
    items: body.items.map(parseBriefItem),
  };
}

export async function requestAiChat(projectId: string, question: string): Promise<AiChatResponse> {
  const body = await requireOk(
    await fetch("/api/ai/chat", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, question }),
    }),
    "AI 对话暂不可用",
  );
  if (
    !isRecord(body) ||
    !["answered", "insufficient_evidence", "unavailable"].includes(String(body.status)) ||
    !isStringOrNull(body.answer) ||
    !Array.isArray(body.citations) ||
    !isStringOrNull(body.error_code)
  ) {
    throw new Error("invalid AI chat response");
  }
  return {
    status: body.status as AiChatResponse["status"],
    answer: body.answer,
    citations: body.citations.map(parseCitation),
    error_code: body.error_code,
  };
}
