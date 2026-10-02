import { notifyProductWorkChanged } from "./product-work-scope";

export type SourceRef = { tenant_id: string; project_id?: string | null; kind: string; ref_id: string; as_of: string; digest: string; locator?: string | null };
export type Space = { id: string; code: string; title: string; lifecycle: string; version: number; payload_digest: string; owner_user_id: string; user_groups: string[]; regions: string[]; use_scenarios: string[]; research_questions: string[] };
export type Member = { id: string; display_name: string; access: string };
export type Research = { id: string; source_finding_id?: string | null; market_space_id: string; product_line_id: string | null; owner_user_id: string; version: number; payload_digest: string; question: string; state: string; method: string; expected_decision: string; time_scope: string; stop_conditions: string[]; conclusion: string | null; cancellation_reason?: string | null; findings: string[]; unresolved: string[]; sources: SourceRef[] };
export type WorkItem = { id: string; market_space_id: string; product_line_id: string | null; title: string; version: number; payload_digest: string; state: string; owner_user_id: string | null; receiver_user_id: string | null; action_type: string; acceptance_required: boolean; expected_output: string; completion_criteria: string; result_note: string | null; due_at: string | null; evidence: SourceRef[] };
export type Evidence = { id: string; name: string; url: string | null; captured_at: string; source_version?: string | null; taint: string; is_stale: boolean; superseded: boolean; has_conflict: boolean; reference: SourceRef };
export type Workspace = { space: Space; research: Research[]; work_items: WorkItem[]; members: Member[]; available_members: Member[]; can_manage: boolean; can_collect: boolean; can_manage_sources: boolean; can_restore: boolean; can_contribute: boolean; current_user_id: string };
export class ProductRequestError extends Error {
  constructor(message: string, readonly status: number, readonly code?: string) { super(message); this.name = "ProductRequestError"; }
}
export async function request<T>(path: string, method: "GET" | "POST" | "PUT" = "GET", body?: unknown): Promise<T> {
  const response = await fetch(`/api/product-work/${path}`, { method, cache: "no-store", ...(body ? { headers: { "Content-Type": "application/json" }, body: JSON.stringify(body) } : {}) });
  if (response.status === 204) { changed(); return undefined as T; }
  const value = await response.json().catch(() => {
    if (!response.ok) throw new ProductRequestError("产品工作暂不可用，请重试", response.status);
    throw new Error("产品工作回执暂不可读，请查询原记录或重试原请求");
  });
  if (!response.ok) throw new ProductRequestError(value?.detail?.message ?? "产品工作暂不可用，请重试", response.status, value?.detail?.code);
  changed();
  return value;
  function changed() {
    const match = path.match(/^spaces\/([^/]+)\/(.+)$/);
    if (method === "GET" || !match) return;
    const writes = /^(?:research|work-items|competitors|market-segments|opportunities|experiments|strategies|definitions|products|members)(?:\/[0-9a-f-]{36}(?:\/(?:actions|changes|start|conclude|cancel|reviews|lifecycle|members(?:\/[0-9a-f-]{36})?))?)?$/i;
    if (writes.test(match[2]) || /^(?:research|evidence)-ai-(?:review|apply)$/.test(match[2]) || /^(?:rfq-ai-confirm|product-ai-runs|product-ai-cancel)$/.test(match[2])) notifyProductWorkChanged(`spaces/${match[1]}`);
  }
}
export function command(record: { version: number; payload_digest: string }) {
  return { expected_version: record.version, payload_digest: record.payload_digest, idempotency_key: crypto.randomUUID() };
}
export const stateLabels: Record<string, string> = { draft: "待开始", active: "研究中", pending_assignment: "待分派", ready: "可开始", in_progress: "办理中", submitted: "待接收", completed: "已完成", cancelled: "已取消" };
export const actionLabels: Record<string, string> = { evidence_collection: "资料补证", discipline_review: "专业评审", constraint_review: "约束审查", experiment_preparation: "实验准备", handoff_preparation: "交接准备" };

export type ProductNode = { id: string; market_space_id: string; product_line_id: string; parent_id: string | null; code: string; name: string; level: string; lifecycle: string; owner_user_id: string; regions: string[]; channels: string[]; version: number; payload_digest: string };
export type ProductCatalog = { nodes: ProductNode[]; members: { product_line_id: string; user_id: string; access: string; display_name: string }[]; can_create_line: boolean; line_access: Record<string, { can_manage: boolean; can_contribute: boolean }> };

export type ResearchSource = { id: string; name: string; base_url: string; source_type: string; allowed_use: string; license_note: string | null; trust_tier: string; status: string; collection_frequency: string; retention_policy: string };
export type EvidenceContent = { snapshot_id: string; content: string; content_digest: string; byte_size: number; stored_at: string; taint: string; content_language: string };

export type SearchObservation = { id: string; request_id: string; product_line_id: string | null; query: string; language: string; time_range: string | null; status: string; started_at: string; finished_at: string | null; provider_key: string; provider_protocol_version: string; response_digest: string | null; error_code: string | null; error_message: string | null; hits: { title: string; url: string; snippet: string }[]; warnings: string[] };
