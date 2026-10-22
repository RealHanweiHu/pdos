import type { ProposalViewSource } from "@/components/preproject/proposal-view-contracts";

export type FixedSegment = { entry_id: string; version: number; lineage_id: string | null; label: string | null; status?: "available" | "unavailable"; source_refs: ProposalViewSource[] };
export type CompetitorAssignment = {
  version: "competitor-segment-assignment/v1"; category_id: string; principal_id: string; as_of: string;
  competitor: { id: string; lineage_id: string; version: number; origin: string; writer_id: string | null; run_id: string | null; confirmed_by: string | null; content: Record<string, unknown> | null; regions: string[]; source_refs: ProposalViewSource[] };
  can_edit: boolean; blockers: { code: string; message: string }[]; selected_segments: FixedSegment[]; segments: FixedSegment[]; unavailable_segment_count: number;
};
export type SegmentCommand = { command_id: string; idempotency_key: string; category_id: string; product_id: null; operation: "category.knowledge.add"; expected_revision: number; source_read_set: never[]; payload: { kind: "competitor"; content: Record<string, unknown>; regions: string[]; source_refs: ProposalViewSource[]; supersedes: { lineage_id: string; expected_version: number }; confirmation_token?: string } };
export type SegmentPreview = { command: SegmentCommand; confirmation_token: string; expires_at: string | null; review: { operation: string; effect: string; payload: Record<string, unknown> } };
export type SegmentReceipt = { id: string; category_id: string; product_id: null; operation: string; subject_type: string; subject_id: string; subject_revision: number; result: { lineage_id: string; version: number; entry_id: string } };
type Journal = { version: 1; principal_id: string; category_id: string; lineage_id: string; command: SegmentCommand };
const record = (v: unknown): v is Record<string, unknown> => !!v && typeof v === "object" && !Array.isArray(v);
const uuid = (v: unknown): v is string => typeof v === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(v);
const positive = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(item => typeof item === "string");
const refs = (v: unknown): v is ProposalViewSource[] => Array.isArray(v) && v.every(record);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).length === keys.length && Object.keys(v).every(k => keys.includes(k));
const nullableId = (v: unknown) => v === null || uuid(v);
const fixed = (v: unknown) => record(v) && uuid(v.entry_id) && positive(v.version);
function segment(v: unknown, selected: boolean): boolean {
  if (!fixed(v) || !record(v) || !refs(v.source_refs)) return false;
  if (selected && v.status === "unavailable") return v.lineage_id === null && v.label === null && v.source_refs.length === 0;
  return (!selected || v.status === "available") && uuid(v.lineage_id) && typeof v.label === "string";
}
export function isCompetitorAssignment(v: unknown, categoryId: string, entryId: string): v is CompetitorAssignment {
  if (!record(v) || v.version !== "competitor-segment-assignment/v1" || v.category_id !== categoryId || !uuid(v.principal_id) || typeof v.as_of !== "string" || !Number.isFinite(Date.parse(v.as_of)) || !record(v.competitor)) return false;
  const c = v.competitor;
  return c.id === entryId && uuid(c.id) && uuid(c.lineage_id) && positive(c.version) && typeof c.origin === "string"
    && nullableId(c.writer_id) && nullableId(c.run_id) && nullableId(c.confirmed_by) && (c.content === null || record(c.content)) && strings(c.regions) && refs(c.source_refs)
    && typeof v.can_edit === "boolean" && (!v.can_edit || record(c.content)) && Array.isArray(v.blockers) && v.blockers.every(b => record(b) && typeof b.code === "string" && typeof b.message === "string")
    && Array.isArray(v.selected_segments) && v.selected_segments.every(s => segment(s, true)) && Array.isArray(v.segments) && v.segments.every(s => segment(s, false))
    && Number.isSafeInteger(v.unavailable_segment_count) && Number(v.unavailable_segment_count) >= 0;
}
export const competitorAssignmentPath = (categoryId: string, entryId: string) => `v1/categories/${encodeURIComponent(categoryId)}/competitors/${encodeURIComponent(entryId)}/segment-assignment`;
export const segmentKey = (segment: Pick<FixedSegment, "entry_id" | "version">) => `${segment.entry_id}:${segment.version}`;
export function canonical(v: unknown): string {
  if (Array.isArray(v)) return `[${v.map(canonical).join(",")}]`;
  if (record(v)) return `{${Object.entries(v).sort(([a], [b]) => a.localeCompare(b)).map(([key, child]) => `${JSON.stringify(key)}:${canonical(child)}`).join(",")}}`;
  return JSON.stringify(v);
}
export function segmentCommand(data: CompetitorAssignment, selected: Pick<FixedSegment, "entry_id" | "version">[]): SegmentCommand {
  if (!data.can_edit || !data.competitor.content) throw new Error("当前竞品不可编辑，请重新读取权限与来源。");
  const pairs = new Map([...data.selected_segments, ...data.segments].map(item => [segmentKey(item), item]));
  const seen = new Set<string>();
  for (const item of selected) { const key = segmentKey(item); if (!pairs.has(key) || seen.has(key)) throw new Error("请选择当前读集提供的固定细分版本。"); seen.add(key); }
  return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), category_id: data.category_id, product_id: null, operation: "category.knowledge.add", expected_revision: data.competitor.version, source_read_set: [], payload: {
    kind: "competitor", content: { ...structuredClone(data.competitor.content), segment_refs: selected.map(({ entry_id, version }) => ({ entry_id, version })) }, regions: structuredClone(data.competitor.regions), source_refs: structuredClone(data.competitor.source_refs), supersedes: { lineage_id: data.competitor.lineage_id, expected_version: data.competitor.version },
  } };
}
export function validSegmentPreview(v: unknown, original: SegmentCommand): v is SegmentPreview {
  if (!record(v) || !record(v.command) || !record(v.command.payload) || !record(v.review) || !record(v.review.payload)) return false;
  const { confirmation_token, ...payload } = v.command.payload;
  const review = { ...v.review.payload };
  for (const key of ["prepared_by_run_id", "candidate_digest"]) { if (review[key] !== undefined && review[key] !== null) return false; delete review[key]; }
  delete review.confirmation_token;
  return typeof confirmation_token === "string" && confirmation_token.length >= 20 && v.confirmation_token === confirmation_token
    && (v.expires_at === null || typeof v.expires_at === "string") && canonical({ ...v.command, payload }) === canonical(original)
    && v.review.operation === original.operation && typeof v.review.effect === "string" && canonical(review) === canonical(original.payload);
}
export function validSegmentReceipt(v: unknown, original: SegmentCommand): v is SegmentReceipt {
  return record(v) && uuid(v.id) && v.category_id === original.category_id && v.product_id === null && v.operation === original.operation
    && v.subject_type === "category_knowledge" && v.subject_id === original.payload.supersedes.lineage_id && v.subject_revision === original.expected_revision + 1
    && record(v.result) && v.result.lineage_id === v.subject_id && v.result.version === v.subject_revision && uuid(v.result.entry_id);
}
export const segmentJournalKey = (principalId: string, categoryId: string, lineageId: string) => `pdos:competitor-segments:v1:${principalId}:${categoryId}:${lineageId}`;
export function readSegmentJournal(raw: string, principalId: string, categoryId: string, lineageId: string): SegmentCommand {
  const fail = () => { throw new Error("原保存请求恢复记录不完整或范围不符，已暂停新保存，请保留记录并核对。"); };
  const v: unknown = JSON.parse(raw);
  if (!record(v) || !exact(v, ["version", "principal_id", "category_id", "lineage_id", "command"]) || v.version !== 1 || v.principal_id !== principalId || v.category_id !== categoryId || v.lineage_id !== lineageId || !record(v.command)) return fail();
  const c = v.command, p = c.payload;
  if (!exact(c, ["command_id", "idempotency_key", "category_id", "product_id", "operation", "expected_revision", "source_read_set", "payload"]) || !uuid(c.command_id) || !uuid(c.idempotency_key) || c.category_id !== categoryId || c.product_id !== null || c.operation !== "category.knowledge.add" || !positive(c.expected_revision) || !Array.isArray(c.source_read_set) || c.source_read_set.length || !record(p)) return fail();
  if (!exact(p, ["kind", "content", "regions", "source_refs", "supersedes", "confirmation_token"]) || p.kind !== "competitor" || !record(p.content) || typeof p.content.brand !== "string" || !p.content.brand.trim() || typeof p.content.model !== "string" || !p.content.model.trim() || Object.keys(p.content).some(k => !["brand", "model", "metrics", "features", "prices", "segment_refs"].includes(k)) || !["metrics", "features", "prices"].every(k => refs(p.content && (p.content as Record<string, unknown>)[k])) || !Array.isArray(p.content.segment_refs) || !p.content.segment_refs.every(s => fixed(s) && record(s) && exact(s, ["entry_id", "version"])) || new Set(p.content.segment_refs.map(s => segmentKey(s as FixedSegment))).size !== p.content.segment_refs.length || !strings(p.regions) || !refs(p.source_refs) || !record(p.supersedes) || !exact(p.supersedes, ["lineage_id", "expected_version"]) || p.supersedes.lineage_id !== lineageId || p.supersedes.expected_version !== c.expected_revision || typeof p.confirmation_token !== "string" || p.confirmation_token.length < 20) return fail();
  return c as SegmentCommand;
}
export function persistSegmentJournal(storage: Storage, command: SegmentCommand, principalId: string): void {
  const lineageId = command.payload.supersedes.lineage_id, key = segmentJournalKey(principalId, command.category_id, lineageId);
  const saved: Journal = { version: 1, principal_id: principalId, category_id: command.category_id, lineage_id: lineageId, command }, serialized = JSON.stringify(saved);
  readSegmentJournal(serialized, principalId, command.category_id, lineageId);
  const existing = storage.getItem(key);
  if (existing && canonical(readSegmentJournal(existing, principalId, command.category_id, lineageId)) !== canonical(command)) throw new Error("尚有原保存请求待核对，未发送新请求。");
  storage.setItem(key, serialized);
  if (storage.getItem(key) !== serialized) throw new Error("无法保存原请求，尚未发送；请恢复会话存储后重试。");
}
export function clearSegmentJournal(storage: Storage, command: SegmentCommand, principalId: string): void {
  const key = segmentJournalKey(principalId, command.category_id, command.payload.supersedes.lineage_id), existing = storage.getItem(key);
  if (existing && canonical(readSegmentJournal(existing, principalId, command.category_id, command.payload.supersedes.lineage_id)) !== canonical(command)) throw new Error("另有原请求待核对，已保留恢复记录。");
  storage.removeItem(key);
  if (storage.getItem(key) !== null) throw new Error("成功回执已取得，原请求恢复记录暂未清理。");
}
