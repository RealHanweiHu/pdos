import { mpRecord, mpRevision, mpSame, mpUuid } from "../components/manufacturing-preparation/manufacturing-preparation-contract";
import { validQualitySource } from "./build-quality-loop-view";
import { handoffDetail, handoffHeader, handoffHistoryPage, parseHandoffPayload, type HandoffApi, type HandoffDetail, type HandoffHeader, type HandoffHistory, type HandoffRef, type HandoffScope, type HandoffWatermark } from "./external-handoffs";

export type ProjectExternalHandoffScope = HandoffScope;
export type ProjectExternalHandoffApi = HandoffApi;
export type ProjectExternalHandoffList = { items: HandoffHeader[]; nextCursor: string | null };
export type ProjectExternalHandoffReceipts = { asOf: HandoffWatermark; items: HandoffHistory[]; beforeSequence: number | null };

const text = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const instant = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const hash = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const uuidOrder = (id: string) => id.replaceAll("-", "").toLowerCase();
function invalid(): never { throw new Error("本项目移交、固定版本或原回执水位不完整，请刷新后重新选择；不能用旧材料或当前状态补齐。"); }
function scopeRoot(scope: ProjectExternalHandoffScope): string {
  if (!mpRecord(scope) || ![scope.categoryId, scope.productId, scope.projectId, scope.principalId].every(mpUuid)) invalid();
  return `v1/categories/${scope.categoryId}/products/${scope.productId}/external-handoffs`;
}
function header(value: unknown, scope: ProjectExternalHandoffScope): value is HandoffHeader {
  return handoffHeader(value, scope.projectId) && ["private", "category", "audience"].includes(String(value.visibility)) && instant(value.created_at);
}
function detail(value: unknown, scope: ProjectExternalHandoffScope): value is HandoffDetail {
  if (!handoffDetail(value, scope) || !header(value, scope)) return false;
  const authorization = value.authorization, packet = value.intent.packet, declaration = authorization.declaration;
  if (!mpRecord(declaration) || !mpRecord(authorization.scope) || !mpUuid(authorization.scope.tenant_id)
    || authorization.structural_only !== true || authorization.status !== "unexecuted_candidate" || authorization.operation !== "integration.handoff.authorize"
    || !["READY", "UNKNOWN", "BLOCKED"].includes(String(authorization.state)) || !instant(authorization.prepared_at)
    || declaration.purpose !== value.purpose || declaration.visibility !== value.visibility
    || authorization.external_received !== false || authorization.external_effective !== false
    || !["package_sha256", "manifest_sha256", "mappings_sha256", "content_sha256"].every(key => hash(authorization[key]))
    || !["unknown", "blocked"].every(key => Array.isArray(authorization[key]) && authorization[key].every(text))
    || !Array.isArray(authorization.signers) || !authorization.signers.length || !authorization.signers.every(mpUuid)
    || !Array.isArray(authorization.sources) || !authorization.sources.every(validQualitySource)
    || !Array.isArray(authorization.required_source_read_set) || !authorization.required_source_read_set.every(row => mpRecord(row) && mpUuid(row.artifact_id) && mpRevision(row.expected_revision))
    || !Array.isArray(authorization.limits) || !authorization.limits.every(row => mpRecord(row) && text(row.text) && Array.isArray(row.sources) && row.sources.length > 0 && row.sources.every(validQualitySource))) return false;
  try { parseHandoffPayload(declaration, "integration.handoff.authorize", scope); } catch { return false; }
  // These are the fixed packet fields copied by delivery_intent_snapshot. A raw
  // external receipt may disagree with them; that disagreement remains a fact.
  return ["package", "engineering_decision", "manufacturing_decision", "subject_config", "release_scope", "purpose", "destination", "external_id", "manifest", "mappings"]
    .every(key => mpSame(packet[key], declaration[key]))
    && ["manifest_sha256", "mappings_sha256", "content_sha256"].every(key => packet[key] === authorization[key]);
}

/** Returned project rows only. The UUID cursor is not an applicability decision. */
export async function readProjectExternalHandoffs(api: ProjectExternalHandoffApi, scope: ProjectExternalHandoffScope, cursor?: string): Promise<ProjectExternalHandoffList> {
  const root = scopeRoot(scope);
  if (cursor !== undefined && !mpUuid(cursor)) invalid();
  const query = new URLSearchParams({ project_id: scope.projectId });
  if (cursor !== undefined) query.set("history_cursor", cursor);
  const value = await api<unknown>(`${root}?${query}`);
  if (!mpRecord(value) || !Array.isArray(value.items) || value.items.length > 20 || !value.items.every(row => header(row, scope))
    || !(value.next_cursor === null || mpUuid(value.next_cursor))) invalid();
  const rows = value.items as HandoffHeader[];
  if (new Set(rows.map(row => row.id)).size !== rows.length
    || rows.some((row, index) => (cursor !== undefined && uuidOrder(row.id) >= uuidOrder(cursor)) || (index > 0 && uuidOrder(rows[index - 1].id) <= uuidOrder(row.id)))
    || (value.next_cursor !== null && (rows.length !== 20 || value.next_cursor !== rows.at(-1)?.id))) invalid();
  return { items: rows, nextCursor: value.next_cursor };
}

/** An explicit immutable authorization and packet; it never sends anything. */
export async function readProjectExternalHandoff(api: ProjectExternalHandoffApi, scope: ProjectExternalHandoffScope, selected: HandoffRef): Promise<HandoffDetail> {
  const root = scopeRoot(scope);
  if (!mpRecord(selected) || !mpUuid(selected.id) || !mpRevision(selected.revision)) invalid();
  const value = await api<unknown>(`${root}/${selected.id}`);
  if (!detail(value, scope) || value.id !== selected.id || value.revision !== selected.revision) invalid();
  return value;
}

/** A separate GET snapshot must still match the chosen detail's full watermark. */
export async function readProjectExternalHandoffReceipts(api: ProjectExternalHandoffApi, scope: ProjectExternalHandoffScope, selected: HandoffDetail, beforeSequence?: number): Promise<ProjectExternalHandoffReceipts> {
  const root = scopeRoot(scope);
  if (!detail(selected, scope) || (beforeSequence !== undefined && !mpRevision(beforeSequence))) invalid();
  const query = beforeSequence === undefined ? "" : `?${new URLSearchParams({ before_sequence: String(beforeSequence) })}`;
  const value = await api<unknown>(`${root}/${selected.id}/receipts${query}`);
  if (!handoffHistoryPage(value, selected) || value.items.length > 20
    || value.items.some(row => !instant(row.received_at) || !instant(row.original.occurred_at) || (beforeSequence !== undefined && row.sequence >= beforeSequence))
    || (value.before_sequence !== null && value.items.length !== 20)) invalid();
  const latest = value.items.find(row => row.sequence === selected.as_of.receipt_count);
  if (latest && !mpSame({ id: latest.id, revision: latest.revision }, selected.as_of.latest_receipt)) invalid();
  return { asOf: value.as_of, items: value.items, beforeSequence: value.before_sequence };
}
