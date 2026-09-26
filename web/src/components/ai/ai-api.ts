import { isRecord, responseBody } from "@/components/workspace-api";

import {
  FINDING_STATUSES,
  FINDING_TYPES,
  INBOX_ITEM_KINDS,
  type AgentRunList,
  type AgentRunProgress,
  type AgentRunSummary,
  type AiBrief,
  type AiBriefItem,
  type AiCapability,
  type AiChatResponse,
  type AiChatOperation,
  type AiFinding,
  type AiQualityControl,
  type AiTouchpoint,
  type AiUsage,
  type AiUsageRow,
  type ChatCitation,
  type FindingEvidence,
  type FindingStatus,
  type FindingType,
  type InboxItemKind,
  type ReviewInboxDigest,
  type ReviewInboxGroup,
  type ReviewInboxItem,
  type RiskCandidate,
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

/**
 * Thrown when an item is structurally sound but carries an enum value this
 * frontend build does not know yet (e.g. a newer backend shipped a new
 * finding_type). List endpoints skip such items instead of failing the page;
 * structural breakage still throws.
 */
class UnknownContractValueError extends Error {}

function requireKnownEnums(value: Record<string, unknown>): void {
  if (typeof value.finding_type === "string" && !isFindingType(value.finding_type)) {
    throw new UnknownContractValueError(`unknown finding_type: ${value.finding_type}`);
  }
  const status = "status" in value ? value.status : value.finding_status;
  if (typeof status === "string" && !isFindingStatus(status)) {
    throw new UnknownContractValueError(`unknown finding status: ${status}`);
  }
}

function mapSkippingUnknown<T>(items: unknown[], parse: (value: unknown) => T, label: string): T[] {
  const parsed: T[] = [];
  for (const item of items) {
    try {
      parsed.push(parse(item));
    } catch (error) {
      if (error instanceof UnknownContractValueError) {
        console.warn(`[ai-api] skipped ${label}: ${error.message}`);
        continue;
      }
      throw error;
    }
  }
  return parsed;
}

export function isSafePdosHref(value: unknown): value is string {
  if (typeof value !== "string" || !value.startsWith("/") || value.startsWith("//")) {
    return false;
  }
  try {
    const parsed = new URL(value, "https://pdos.invalid");
    return (
      parsed.origin === "https://pdos.invalid" &&
      ["/projects", "/ai-review", "/knowledge"].includes(parsed.pathname)
    );
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
  if (isRecord(value)) requireKnownEnums(value);
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
  if (isRecord(value)) requireKnownEnums(value);
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
  if (isRecord(value)) requireKnownEnums(value);
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
  return mapSkippingUnknown(body.items, parseFinding, "finding");
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
    quality_controls: mapSkippingUnknown(body.quality_controls, parseQualityControl, "quality control"),
    items: mapSkippingUnknown(body.items, parseBriefItem, "brief item"),
  };
}

function isAgentRun(value: unknown): value is AgentRunSummary {
  return (
    isRecord(value) &&
    typeof value.id === "string" &&
    typeof value.agent_key === "string" &&
    typeof value.status === "string" &&
    typeof value.window_started_at === "string" &&
    typeof value.window_ended_at === "string" &&
    typeof value.event_count === "number" &&
    isStringOrNull(value.started_at) &&
    isStringOrNull(value.completed_at) &&
    isStringOrNull(value.error_code) &&
    typeof value.created_at === "string" &&
    (value.can_cancel === undefined || typeof value.can_cancel === "boolean") &&
    (value.can_pause === undefined || typeof value.can_pause === "boolean") &&
    (value.can_resume === undefined || typeof value.can_resume === "boolean") &&
    (value.input_wait == null || (isRecord(value.input_wait) &&
      typeof value.input_wait.id === "string" && typeof value.input_wait.finding_id === "string" &&
      typeof value.input_wait.owner_user_id === "string" && typeof value.input_wait.summary === "string" &&
      typeof value.input_wait.expires_at === "string" && isStringOrNull(value.input_wait.resolved_at) &&
      isStringOrNull(value.input_wait.resolution) && isStringOrNull(value.input_wait.continuation_run_id) &&
      Array.isArray(value.input_wait.questions) && value.input_wait.questions.every((q) => typeof q === "string")))
  );
}

export async function requestAgentRuns(projectId: string): Promise<AgentRunList> {
  const body = await requireOk(
    await fetch(`/api/ai/projects/${encodeURIComponent(projectId)}/runs`, {
      cache: "no-store",
      credentials: "same-origin",
    }),
    "Agent 运行状态暂不可用",
  );
  if (
    !isRecord(body) ||
    !Array.isArray(body.items) ||
    typeof body.pending_review_findings !== "number"
  ) {
    throw new Error("invalid agent run list");
  }
  return {
    items: body.items.filter((item) => {
      if (isAgentRun(item)) return true;
      console.warn("[ai-api] skipped malformed agent run row");
      return false;
    }) as AgentRunSummary[],
    pending_review_findings: body.pending_review_findings,
  };
}

export async function requestAiChat(
  projectId: string, question: string, requestId: string = crypto.randomUUID(),
): Promise<AiChatResponse | AiChatOperation> {
  const body = await requireOk(
    await fetch("/api/ai/chat", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ project_id: projectId, question, request_id: requestId }),
    }),
    "AI 对话暂不可用",
  );
  return isRecord(body) && "run_id" in body ? parseChatOperation(body) : parseChatResult(body);
}

function parseChatResult(body: unknown): AiChatResponse {
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

function isSafeCount(value: unknown): value is number {
  return typeof value === "number" && Number.isSafeInteger(value);
}

function isInboxKind(value: unknown): value is InboxItemKind {
  return typeof value === "string" && INBOX_ITEM_KINDS.includes(value as InboxItemKind);
}

function parseInboxItem(value: unknown): ReviewInboxItem {
  if (
    !isRecord(value) ||
    !isInboxKind(value.kind) ||
    typeof value.id !== "string" ||
    typeof value.title !== "string" ||
    !isStringOrNull(value.agent_key) ||
    !isStringOrNull(value.finding_type) ||
    !(value.confidence_basis_points === null || isSafeCount(value.confidence_basis_points)) ||
    !(
      value.quality_acceptance_basis_points === null ||
      isSafeCount(value.quality_acceptance_basis_points)
    ) ||
    !isSafePdosHref(value.href) ||
    typeof value.created_at !== "string"
  ) {
    throw new Error("invalid review inbox item");
  }
  return value as ReviewInboxItem;
}

function parseInboxGroup(value: unknown): ReviewInboxGroup {
  if (
    !isRecord(value) ||
    typeof value.project_id !== "string" ||
    typeof value.project_name !== "string" ||
    !Array.isArray(value.items)
  ) {
    throw new Error("invalid review inbox group");
  }
  return {
    project_id: value.project_id,
    project_name: value.project_name,
    items: value.items.map(parseInboxItem),
  };
}

function parseChatOperation(body: unknown): AiChatOperation {
  if (!isRecord(body) || typeof body.run_id !== "string" || typeof body.project_id !== "string"
    || typeof body.request_id !== "string" || !isStringOrNull(body.error_code)
    || !["queued", "running", "succeeded", "degraded", "failed", "cancelled"].includes(String(body.status))) {
    throw new Error("invalid Chat operation response");
  }
  return { run_id: body.run_id, project_id: body.project_id, request_id: body.request_id,
    status: body.status as AiChatOperation["status"], error_code: body.error_code,
    result: body.result === null ? null : parseChatResult(body.result) };
}

export async function requestChatOperation(runId: string, cancel = false): Promise<AiChatOperation> {
  return parseChatOperation(await requireOk(await fetch(
    `/api/ai/chat/requests/${encodeURIComponent(runId)}${cancel ? "/cancel" : ""}`,
    { method: cancel ? "POST" : "GET", cache: "no-store", credentials: "same-origin",
      ...(cancel ? { headers: { "Content-Type": "application/json" }, body: "{}" } : {}) },
  ), "暂时无法查询请求，请稍后重试"));
}

export async function requestReviewInbox(): Promise<ReviewInboxDigest> {
  const body = await requireOk(
    await fetch("/api/ai/review-inbox", { cache: "no-store", credentials: "same-origin" }),
    "Review 收件箱摘要暂不可用",
  );
  if (
    !isRecord(body) ||
    !Array.isArray(body.groups) ||
    !["finding_count", "risk_candidate_count", "import_batch_count", "archived_count"].every(
      (key) => isSafeCount(body[key]),
    )
  ) {
    throw new Error("invalid review inbox digest");
  }
  return {
    groups: body.groups.map(parseInboxGroup),
    finding_count: body.finding_count as number,
    risk_candidate_count: body.risk_candidate_count as number,
    import_batch_count: body.import_batch_count as number,
    archived_count: body.archived_count as number,
  };
}

export async function archiveStaleFindings(): Promise<AiFinding[]> {
  const body = await requireOk(
    await fetch("/api/ai/findings/archive-stale", {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({}),
    }),
    "归档过期 Finding 失败",
  );
  if (!isRecord(body) || !Array.isArray(body.archived)) {
    throw new Error("invalid archive response");
  }
  return mapSkippingUnknown(body.archived, parseFinding, "archived finding");
}

export async function restoreFinding(findingId: string): Promise<AiFinding> {
  const body = await requireOk(
    await fetch(`/api/ai/findings/${encodeURIComponent(findingId)}/restore`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
    }),
    "Finding 恢复失败",
  );
  return parseFinding(body);
}

function parseTouchpoint(value: unknown): AiTouchpoint {
  if (
    !isRecord(value) ||
    typeof value.key !== "string" ||
    typeof value.label !== "string" ||
    !["enabled", "degraded", "disabled"].includes(String(value.state)) ||
    !isStringOrNull(value.reason_code) ||
    typeof value.manual_alternative !== "string"
  ) {
    throw new Error("invalid AI touchpoint");
  }
  return value as AiTouchpoint;
}

export async function requestTouchpoints(): Promise<AiTouchpoint[]> {
  const body = await requireOk(
    await fetch("/api/ai/touchpoints", { cache: "no-store", credentials: "same-origin" }),
    "AI 触点状态暂不可用",
  );
  if (!isRecord(body) || !Array.isArray(body.items)) throw new Error("invalid touchpoint list");
  return body.items.map(parseTouchpoint);
}

function parseUsageRow(value: unknown): AiUsageRow {
  if (
    !isRecord(value) ||
    typeof value.agent_key !== "string" ||
    typeof value.prompt_version !== "string" ||
    !isSafeCount(value.invocation_count) ||
    !isSafeCount(value.succeeded_count) ||
    !isSafeCount(value.total_tokens)
  ) {
    throw new Error("invalid AI usage row");
  }
  return value as AiUsageRow;
}

export async function requestAiUsage(): Promise<AiUsage> {
  const body = await requireOk(
    await fetch("/api/ai/usage", { cache: "no-store", credentials: "same-origin" }),
    "AI 用量暂不可用",
  );
  if (
    !isRecord(body) ||
    typeof body.budget_exhausted !== "boolean" ||
    !Array.isArray(body.rows) ||
    !["daily_token_budget", "used_tokens_today", "remaining_tokens_today"].every(
      (key) => body[key] === null || isSafeCount(body[key]),
    )
  ) {
    throw new Error("invalid AI usage response");
  }
  return {
    daily_token_budget: body.daily_token_budget as number | null,
    used_tokens_today: body.used_tokens_today as number | null,
    remaining_tokens_today: body.remaining_tokens_today as number | null,
    budget_exhausted: body.budget_exhausted,
    rows: body.rows.map(parseUsageRow),
  };
}

function parseCapability(value: unknown): AiCapability {
  if (
    !isRecord(value) ||
    typeof value.capability_key !== "string" ||
    typeof value.agent_key !== "string" ||
    !["free", "confirm", "hard_gate"].includes(String(value.zone)) ||
    !["live", "shadow"].includes(String(value.rollout)) ||
    typeof value.prompt_version !== "string" ||
    !Array.isArray(value.finding_types) ||
    !Array.isArray(value.projections) ||
    !Array.isArray(value.tools) ||
    typeof value.quality_control !== "string" ||
    !Array.isArray(value.controls)
  ) {
    throw new Error("invalid AI capability");
  }
  return {
    ...(value as Omit<AiCapability, "controls">),
    controls: mapSkippingUnknown(value.controls, parseQualityControl, "capability control"),
  };
}

export async function requestCapabilities(): Promise<AiCapability[]> {
  const body = await requireOk(
    await fetch("/api/ai/capabilities", { cache: "no-store", credentials: "same-origin" }),
    "AI 能力清单暂不可用",
  );
  if (!isRecord(body) || !Array.isArray(body.items)) throw new Error("invalid capability list");
  return body.items.map(parseCapability);
}

function parseRiskCandidate(value: unknown): RiskCandidate {
  if (
    !isRecord(value) ||
    typeof value.id !== "string" ||
    typeof value.project_id !== "string" ||
    typeof value.title !== "string" ||
    !isStringOrNull(value.description) ||
    !isSafeCount(value.likelihood) ||
    !isSafeCount(value.impact) ||
    !isSafeCount(value.score) ||
    typeof value.created_at !== "string"
  ) {
    throw new Error("invalid risk candidate");
  }
  return {
    id: value.id,
    project_id: value.project_id,
    title: value.title,
    description: value.description,
    likelihood: value.likelihood,
    impact: value.impact,
    score: value.score,
    created_at: value.created_at,
    updated_at: typeof value.updated_at === "string" ? value.updated_at : undefined,
  };
}

export async function requestRiskCandidates(projectId: string): Promise<RiskCandidate[]> {
  const body = await requireOk(
    await fetch(`/api/projects/${encodeURIComponent(projectId)}/risk-candidates`, {
      cache: "no-store",
      credentials: "same-origin",
    }),
    "风险候选暂不可用",
  );
  if (!isRecord(body) || !Array.isArray(body.items)) throw new Error("invalid candidate list");
  return body.items.map(parseRiskCandidate);
}

export async function requestInboxRiskCandidates(): Promise<RiskCandidate[]> {
  const body = await requireOk(
    await fetch("/api/ai/risk-candidates", { cache: "no-store", credentials: "same-origin" }),
    "风险候选汇总暂不可用",
  );
  if (!isRecord(body) || !Array.isArray(body.items)) throw new Error("invalid candidate list");
  return body.items.map(parseRiskCandidate);
}

export async function confirmRiskCandidatesBatch(
  projectId: string,
  riskIds: string[],
): Promise<{ confirmed: string[]; already: string[]; not_found: string[] }> {
  const body = await requireOk(
    await fetch(`/api/projects/${encodeURIComponent(projectId)}/risk-candidates/confirm-batch`, {
      method: "POST",
      cache: "no-store",
      credentials: "same-origin",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ risk_ids: riskIds }),
    }),
    "批量确认失败",
  );
  if (
    !isRecord(body) ||
    !Array.isArray(body.confirmed) ||
    !Array.isArray(body.already) ||
    !Array.isArray(body.not_found)
  ) {
    throw new Error("invalid batch confirm response");
  }
  return body as { confirmed: string[]; already: string[]; not_found: string[] };
}

export async function unconfirmRiskCandidate(projectId: string, riskId: string, expectedUpdatedAt?: string): Promise<void> {
  await requireOk(
    await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/risks/${encodeURIComponent(riskId)}/unconfirm`,
      { method: "POST", cache: "no-store", credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: expectedUpdatedAt ? JSON.stringify({ expected_updated_at: expectedUpdatedAt }) : undefined },
    ),
    "撤销确认失败",
  );
}

export async function dismissRiskCandidate(projectId: string, riskId: string): Promise<void> {
  await requireOk(
    await fetch(
      `/api/projects/${encodeURIComponent(projectId)}/risks/${encodeURIComponent(riskId)}/dismiss`,
      { method: "POST", cache: "no-store", credentials: "same-origin" },
    ),
    "忽略候选失败",
  );
}


export async function cancelAgentRun(runId: string): Promise<void> {
  await requireOk(await fetch(`/api/ai/runs/${encodeURIComponent(runId)}/cancel`, {
    method: "POST", credentials: "same-origin",
    headers: { "Content-Type": "application/json" }, body: "{}",
  }), "暂时无法取消，请重试");
}


export async function requestAgentRunProgress(projectId: string, runId: string): Promise<AgentRunProgress> {
  const body = await requireOk(await fetch(`/api/ai/projects/${encodeURIComponent(projectId)}/runs/${encodeURIComponent(runId)}`, { cache: "no-store", credentials: "same-origin" }), "运行详情暂不可用");
  return parseAgentRunProgress(body);
}

export function parseAgentRunProgress(body: unknown): AgentRunProgress {
  const number = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value >= 0;
  if (!isRecord(body) || typeof body.run_id !== "string" || typeof body.status !== "string" || typeof body.phase !== "string" || typeof body.as_of !== "string" || !isStringOrNull(body.stop_code) || !isStringOrNull(body.last_tool)
    || !["saved_tool_steps", "tool_dispatches", "observations", "model_receipts", "saved_results"].every((key) => number(body[key]))) throw new Error("运行详情格式不可读");
  const b = body.budget;
  if (b !== null && (!isRecord(b) || typeof b.lineage_id !== "string" || typeof b.absolute_deadline !== "string" || typeof b.model_cost_complete !== "boolean"
    || !["token_limit", "charged_tokens", "held_tokens", "remaining_tokens", "unresolved_calls", "active_limit_seconds", "priced_model_cost_microusd"].every((key) => number(b[key]))
    || !["active_seconds", "remaining_active_seconds"].every((key) => b[key] === null || number(b[key])))) throw new Error("运行额度格式不可读");
  return body as AgentRunProgress;
}


export async function controlAgentPause(runId: string, action: "pause" | "resume") {
  return requireOk(await fetch(`/api/ai/runs/${encodeURIComponent(runId)}/${action}`, {
    method: "POST", credentials: "same-origin", headers: { "Content-Type": "application/json" }, body: "{}",
  }), action === "pause" ? "暂时无法暂停任务" : "当前任务无法继续，请查看运行详情中的原因和截止时间");
}

export async function requestFinding(findingId: string): Promise<AiFinding> {
  return parseFinding(await requireOk(await fetch(`/api/ai/findings/${encodeURIComponent(findingId)}`, { cache: "no-store", credentials: "same-origin" }), "候选暂不可用，请刷新"));
}

export type FindingBatchRequest = {
  request_id: string; action: "accepted" | "rejected" | "applied" | "review_undone"; comment: string;
  items: { finding_id: string; expected_updated_at: string; edited_payload?: Record<string, unknown> }[];
};
export type FindingBatchResult = {
  receipt: { id: string; request_id: string; action: string; created_at: string; request: FindingBatchRequest; results: { finding_id: string; status: string; applied_entity_type: string | null; applied_entity_id: string | null }[] };
  items: AiFinding[]; replayed: boolean;
};
export class FindingBatchError extends Error {
  constructor(message: string, public readonly status: number) { super(message); }
}
export async function requestFindingBatch(input: FindingBatchRequest | string): Promise<FindingBatchResult> {
  const response = await fetch(`/api/ai/findings/batch${typeof input === "string" ? `/${encodeURIComponent(input)}` : ""}`, {
    method: typeof input === "string" ? "GET" : "POST", cache: "no-store", credentials: "same-origin",
    ...(typeof input === "string" ? {} : { headers: { "Content-Type": "application/json" }, body: JSON.stringify(input) }),
  });
  let body: unknown;
  try { body = await requireOk(response, "整组办理未确认，请读取原请求回执后再继续"); }
  catch (error) { throw new FindingBatchError(error instanceof Error ? error.message : "批次结果未确认", response.status); }
  if (!isRecord(body) || !isRecord(body.receipt) || !Array.isArray(body.items) || !Array.isArray(body.receipt.results)) throw new Error("invalid Finding batch receipt");
  return { receipt: body.receipt as FindingBatchResult["receipt"], items: body.items.map(parseFinding), replayed: body.replayed === true };
}
