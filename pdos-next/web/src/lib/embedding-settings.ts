/** Independent embedding metadata and original COMMON T1 request binding. */
import { proofClockCurrent } from "@/lib/proof-clock";

export const embeddingCategories = ["public", "synthetic", "internal", "customer", "customer_original"] as const;
export type EmbeddingCategory = typeof embeddingCategories[number];
export type EmbeddingMetadata = { base_url: string; model: string; model_version: string; dimensions: number; connection_id: string; data_categories: EmbeddingCategory[]; include_customer_original: boolean };
export type EmbeddingProfile = { profile_id: string; profile_version_id: string; revision: number; budget_revision: number; metadata: EmbeddingMetadata; enabled: boolean; credential_status: "bound" | "missing" };
export type EmbeddingCall = { call_id: string; revision: number; batch_id: string; profile_version_id: string; attempt: number; state: string; batch_state: string; last_error: string | null; provider: string | null; data_categories: EmbeddingCategory[]; source_count: number; character_count: number; reserved_micro_usd: number; charged_micro_usd: number; input_tokens: number | null; usage_known: boolean; created_at: string };
export type EmbeddingReading = { category_revision: number; default_retrieval: "keyword"; scope: "current_requester_readable"; budget: { revision: number; limit_micro_usd: number; held_micro_usd: number; spent_micro_usd: number } | null; profiles: EmbeddingProfile[]; profiles_truncated: boolean; batch_counts: Record<string, number>; calls: EmbeddingCall[]; next_cursor: string | null };
export type SaveEmbeddingProfile = { profile_id: string; expected_revision: number; metadata: EmbeddingMetadata; enabled: boolean; expected_budget_revision: number; index_budget_micro_usd: number; confirmation_token?: string };
export type ReconcileEmbeddingCall = { call_id: string; expected_revision: number; input_tokens: number; actual_micro_usd: number; evidence_ref: string; confirmation_token?: string };
export type EmbeddingCommand = { command_id: string; idempotency_key: string; category_id: string; product_id: null; operation: "embedding.profile.save" | "embedding.call.reconcile"; expected_revision: number; source_read_set: []; payload: SaveEmbeddingProfile | ReconcileEmbeddingCall };
export type EmbeddingPreview = { command: EmbeddingCommand; expires_at: string; review: Record<string, unknown> };
const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const integer = (value: unknown, min = 0): value is number => typeof value === "number" && Number.isSafeInteger(value) && value >= min && value <= 2147483647;
const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).every(key => keys.includes(key));
function same(a: unknown, b: unknown): boolean {
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((v, i) => same(v, b[i]));
  if (record(a) && record(b)) return Object.keys(a).length === Object.keys(b).length && Object.keys(a).every(key => key in b && same(a[key], b[key]));
  return a === b;
}
export const embeddingCategoryName = (value: string) => ({ public: "公开资料", synthetic: "合成资料", internal: "内部资料", customer: "客户资料", customer_original: "客户原件" } as Record<string, string>)[value] ?? "未识别类别";
export const embeddingStateName = (value: string) => ({ queued: "待处理", scheduled: "待处理", pending: "待处理", started: "处理中", running: "处理中", completed: "已完成", succeeded: "已完成", failed: "失败", skipped: "已跳过", unavailable: "不可用", unknown: "结果与用量待核对", unknown_usage: "用量待核对", reconciled: "已对账", retired: "已退役", cancelled: "已取消" } as Record<string, string>)[value] ?? "待核对状态";
export function embeddingDollars(value: number) { return (value / 1_000_000).toFixed(6).replace(/\.?0+$/, "") || "0"; }
export function embeddingMicroDollars(value: string): number {
  if (!/^(?:0|[1-9]\d*)(?:\.\d{1,6})?$/.test(value)) throw new Error("费用须为非负 USD 金额，最多六位小数。");
  const [whole, fraction = ""] = value.split(".");
  const amount = Number(whole) * 1_000_000 + Number(fraction.padEnd(6, "0"));
  if (!integer(amount)) throw new Error("费用超出可记录范围。");
  return amount;
}
export function validEmbeddingMetadata(value: unknown): value is EmbeddingMetadata {
  if (!record(value) || !exactKeys(value, ["base_url", "model", "model_version", "dimensions", "connection_id", "data_categories", "include_customer_original"]) || typeof value.base_url !== "string" || value.base_url.length > 500 || !uuid(value.connection_id) || !integer(value.dimensions, 1) || value.dimensions > 2000 || typeof value.include_customer_original !== "boolean") return false;
  try { const url = new URL(value.base_url); if (!url.hostname || url.username || url.password || url.search || url.hash || !(url.protocol === "https:" || url.protocol === "http:" && ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname))) return false; } catch { return false; }
  const name = /^[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}$/;
  return typeof value.model === "string" && name.test(value.model) && typeof value.model_version === "string" && name.test(value.model_version)
    && Array.isArray(value.data_categories) && value.data_categories.length > 0 && value.data_categories.every(item => embeddingCategories.includes(item)) && new Set(value.data_categories).size === value.data_categories.length && value.data_categories.includes("customer_original") === value.include_customer_original;
}
function validPayload(operation: string, value: unknown): value is EmbeddingCommand["payload"] {
  if (!record(value) || !integer(value.expected_revision) || value.confirmation_token !== undefined && (typeof value.confirmation_token !== "string" || value.confirmation_token.length < 20 || value.confirmation_token.length > 128)) return false;
  if (operation === "embedding.profile.save") return exactKeys(value, ["profile_id", "expected_revision", "metadata", "enabled", "expected_budget_revision", "index_budget_micro_usd", "confirmation_token"]) && uuid(value.profile_id) && validEmbeddingMetadata(value.metadata) && typeof value.enabled === "boolean" && integer(value.expected_budget_revision) && integer(value.index_budget_micro_usd);
  return operation === "embedding.call.reconcile" && exactKeys(value, ["call_id", "expected_revision", "input_tokens", "actual_micro_usd", "evidence_ref", "confirmation_token"]) && uuid(value.call_id) && integer(value.expected_revision, 1) && integer(value.input_tokens) && integer(value.actual_micro_usd) && typeof value.evidence_ref === "string" && value.evidence_ref.trim().length >= 3 && value.evidence_ref.length <= 500;
}
export function newEmbeddingCommand(categoryId: string, categoryRevision: number, operation: EmbeddingCommand["operation"], payload: EmbeddingCommand["payload"]): EmbeddingCommand {
  if (!uuid(categoryId) || !integer(categoryRevision, 1) || !validPayload(operation, payload) || payload.confirmation_token !== undefined) throw new Error("配置内容或当前版本无效，请核对端点、模型、维度、独立连接和费用。");
  return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), category_id: categoryId, product_id: null, operation, expected_revision: categoryRevision, source_read_set: [], payload: structuredClone(payload) };
}
export function validEmbeddingPreview(value: unknown, original: EmbeddingCommand, now = Date.now()): value is EmbeddingPreview {
  if (!record(value) || !record(value.command) || !record(value.command.payload) || !record(value.review) || !proofClockCurrent("T1", value.expires_at, now)) return false;
  const command = value.command, confirmedPayload = command.payload as Record<string, unknown>, payload = { ...confirmedPayload }; delete payload.confirmation_token;
  const requested = { ...original.payload }; delete requested.confirmation_token;
  const token = confirmedPayload.confirmation_token;
  if (typeof token !== "string" || token.length < 20 || token.length > 128 || value.confirmation_token !== undefined && value.confirmation_token !== token || !same({ ...command, payload }, { ...original, payload: requested })) return false;
  const review = value.review;
  if (original.operation === "embedding.profile.save" && "profile_id" in original.payload) {
    const request = original.payload;
    return review.profile_id === request.profile_id && review.next_revision === request.expected_revision + 1 && review.next_budget_revision === request.expected_budget_revision + 1 && same(review.metadata, request.metadata) && review.enabled === request.enabled && review.index_budget_micro_usd === request.index_budget_micro_usd && review.estimate_scope === "current_requester_readable" && typeof review.estimate_truncated === "boolean" && ["bound", "missing"].includes(String(review.credential_status))
      && (request.enabled ? typeof review.provider === "string" && /^[A-Za-z0-9][A-Za-z0-9:_.@/-]{0,159}$/.test(review.provider) && integer(review.expected_sources) && integer(review.estimated_cost_micro_usd) && review.credential_status === "bound" : review.expected_sources === null && review.estimated_cost_micro_usd === null);
  }
  return "call_id" in original.payload && review.call_id === original.payload.call_id && ["unknown", "unknown_usage"].includes(String(review.state)) && review.actual_micro_usd === original.payload.actual_micro_usd && review.input_tokens === original.payload.input_tokens && review.evidence_ref === original.payload.evidence_ref && integer(review.charged_micro_usd);
}
export function parseEmbeddingPending(raw: string, categoryId: string): EmbeddingCommand {
  const value: unknown = JSON.parse(raw);
  if (!record(value) || !exactKeys(value, ["command_id", "idempotency_key", "category_id", "product_id", "operation", "expected_revision", "source_read_set", "payload"]) || !uuid(value.command_id) || !uuid(value.idempotency_key) || value.category_id !== categoryId || !uuid(categoryId) || value.product_id !== null || !integer(value.expected_revision, 1) || !Array.isArray(value.source_read_set) || value.source_read_set.length !== 0 || typeof value.operation !== "string" || !validPayload(value.operation, value.payload) || !record(value.payload) || typeof value.payload.confirmation_token !== "string") throw new Error("原 Embedding 请求恢复记录无效，请核对当前配置与回执。");
  return value as EmbeddingCommand;
}
export function embeddingReceiptMatches(value: unknown, command: EmbeddingCommand, principalId: string): boolean {
  return record(value) && uuid(value.id) && value.operation === command.operation && value.category_id === command.category_id && value.writer_id === principalId && value.requester_id === principalId && value.agent_run_id === null && value.subject_revision === command.payload.expected_revision + 1 && value.subject_type === (command.operation === "embedding.profile.save" ? "embedding_profile" : "embedding_call") && ("call_id" in command.payload ? value.subject_id === command.payload.call_id : record(value.result) && value.result.profile_id === command.payload.profile_id && value.result.enabled === command.payload.enabled);
}
export function canReconcileEmbeddingCall(call: EmbeddingCall) { return ["unknown", "unknown_usage"].includes(call.state); }
