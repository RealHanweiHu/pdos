import { mpRecord, mpRevision, mpSame, mpUuid, validMpSource, type MpRead, type MpSource, type MpVersion } from "@/components/manufacturing-preparation/manufacturing-preparation-contract";

export const publicationOperation = "npi.manufacturing_baseline.publish" as const;
export type PublicationPayload = {
  project_id: string; baseline: { kind: "manufacturing_baseline"; id: string; revision: number };
  purpose: string; applicability: {
    site: string | null; sources: MpSource[];
    lines?: { kind: "line"; id: string; revision: number }[] | null;
    conditions?: { text: string; sources: MpSource[] } | null;
    valid_from?: string | null; valid_until?: string | null;
  };
  requirements: unknown[]; risk: null; packaging: null; reaction_plan: null;
  previous_id: string | null; expected_previous_revision: number | null;
  visibility: "private" | "category" | "audience"; reason: string; sources: MpSource[]; approval_token?: string;
};
export type PublicationCommand = {
  category_id: string; command_id: string; idempotency_key: string; operation: typeof publicationOperation;
  product_id: string; expected_revision: number; source_read_set: MpRead[]; payload: PublicationPayload;
};
export type PublicationVersion = {
  schema_version: "pdos-manufacturing-publication-v1"; id: string; revision: number; series_id: string;
  project_id: string; owner_id: string; visibility: string; status: "published"; purpose: string;
  body: Record<string, unknown>; gaps: { code: string; detail: string }[];
  baseline: { kind: "manufacturing_baseline"; id: string; revision: number };
  process: { id: string; revision: number }; receipt_id: string; created_at: string;
  is_current: boolean; source_status: "current" | "needs_recheck";
  qualification: "unknown"; manufacturing_release: null;
};
export type PublicationReceipt = { id: string; subject_id: string; subject_revision: number; operation: typeof publicationOperation; subject_type: "manufacturing_publication" };
export type PublicationPrevious = Pick<PublicationVersion, "id" | "revision" | "project_id" | "is_current">;
export type PublicationReview = { operation: string; before: unknown; after: { revision: number; status: "published"; body: Record<string, unknown> }; effect: string; authority: Record<string, unknown>; reason: string; gaps: { code: string; detail: string }[]; required_source_read_set: MpRead[] };
export type PublicationPrepared = { command: PublicationCommand; write_tier: "T2"; named_decision: true; expires_at: string | null; review: PublicationReview };
export type PublicationPending = { stage: "inputs" | "preview" | "execute"; command: PublicationCommand };
export type PublicationApi = <T>(path: string, body?: unknown) => Promise<T>;

function reads(value: unknown): value is MpRead[] {
  return Array.isArray(value) && value.length > 0 && value.every(v => mpRecord(v) && mpUuid(v.artifact_id) && mpRevision(v.expected_revision)) && new Set(value.map(v => v.artifact_id)).size === value.length;
}
function canonicalApplicability(value: Record<string, unknown>) {
  const result = { ...value };
  // Typed server defaults are equivalent to omission; retain every declared value.
  for (const key of ["lines", "conditions", "valid_from", "valid_until"]) if (result[key] === undefined) result[key] = null;
  return result;
}
function semantic(value: PublicationPayload) { const result = { ...value, applicability: canonicalApplicability(value.applicability) }; delete result.approval_token; return result; }
function sameDeclaration(value: unknown, payload: PublicationPayload) {
  return mpRecord(value) && mpRecord(value.applicability) && mpSame({ ...value, applicability: canonicalApplicability(value.applicability) }, semantic(payload));
}
export function validPublicationCommand(value: unknown): value is PublicationCommand {
  if (!mpRecord(value) || value.operation !== publicationOperation || !mpUuid(value.category_id) || !mpUuid(value.command_id) || !mpUuid(value.idempotency_key) || !mpUuid(value.product_id) || !mpRevision(value.expected_revision) || !reads(value.source_read_set) || !mpRecord(value.payload)) return false;
  const p = value.payload;
  return mpUuid(p.project_id) && mpRecord(p.baseline) && p.baseline.kind === "manufacturing_baseline" && mpUuid(p.baseline.id) && mpRevision(p.baseline.revision) && typeof p.purpose === "string" && !!p.purpose.trim() && typeof p.reason === "string" && !!p.reason.trim() && mpRecord(p.applicability) && Array.isArray(p.applicability.sources) && p.applicability.sources.length > 0 && p.applicability.sources.every(validMpSource) && Array.isArray(p.sources) && p.sources.length > 0 && p.sources.every(validMpSource) && Array.isArray(p.requirements) && ["private", "category", "audience"].includes(String(p.visibility)) && ((p.previous_id === null && p.expected_previous_revision === null) || (mpUuid(p.previous_id) && mpRevision(p.expected_previous_revision))) && (p.approval_token === undefined || (typeof p.approval_token === "string" && p.approval_token.length >= 20));
}
export function newPublicationCommand(categoryId: string, productId: string, productRevision: number, baseline: MpVersion, reason: string, previous: PublicationPrevious | null = null): PublicationCommand {
  if (baseline.kind !== "manufacturing_baseline") throw new Error("请选择一版固定制造基线。");
  if (previous && (!mpUuid(previous.id) || !mpRevision(previous.revision) || previous.project_id !== baseline.project_id || previous.is_current !== true)) throw new Error("请明确选择本项目当前发布版续接。");
  const rawSite = baseline.body.process_snapshot.site;
  return {
    category_id: categoryId, command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(),
    operation: publicationOperation, product_id: productId, expected_revision: productRevision,
    source_read_set: structuredClone(baseline.required_source_read_set),
    payload: { project_id: baseline.project_id, baseline: { kind: "manufacturing_baseline", id: baseline.id, revision: baseline.revision }, purpose: baseline.purpose, applicability: { site: typeof rawSite === "string" ? rawSite : null, sources: structuredClone(baseline.sources) }, requirements: [], risk: null, packaging: null, reaction_plan: null, previous_id: previous?.id ?? null, expected_previous_revision: previous?.revision ?? null, visibility: baseline.visibility as PublicationPayload["visibility"], reason, sources: structuredClone(baseline.sources) },
  };
}
function sameCommand(value: PublicationCommand, original: PublicationCommand, includeReads = true) {
  return (["category_id", "command_id", "idempotency_key", "operation", "product_id", "expected_revision"] as const).every(k => value[k] === original[k]) && mpSame(semantic(value.payload), semantic(original.payload)) && (!includeReads || mpSame(value.source_read_set, original.source_read_set));
}
function review(value: unknown, command: PublicationCommand, principalId: string): value is PublicationReview {
  if (!mpRecord(value) || value.operation !== publicationOperation || value.reason !== command.payload.reason || typeof value.effect !== "string" || !mpRecord(value.after) || value.after.status !== "published" || value.after.revision !== (command.payload.expected_previous_revision ?? 0) + 1 || !mpRecord(value.after.body) || value.after.body.qualification !== "unknown" || value.after.body.manufacturing_release !== null || !sameDeclaration(value.after.body.declaration, command.payload) || !mpRecord(value.authority) || value.authority.subject_id !== principalId || value.authority.operation !== publicationOperation || value.authority.authorized !== true || value.authority.qualified !== true || value.authority.purpose !== command.payload.purpose || !Array.isArray(value.authority.roles) || !value.authority.roles.includes("manufacturing") || !mpRecord(value.authority.scope) || value.authority.scope.project_id !== command.payload.project_id || value.authority.scope.product_id !== command.product_id || !reads(value.required_source_read_set) || !mpSame(value.required_source_read_set, command.source_read_set)) return false;
  return Array.isArray(value.gaps) && value.gaps.every(v => mpRecord(v) && typeof v.code === "string" && typeof v.detail === "string");
}
export function publicationInputs(value: unknown, original: PublicationCommand, principalId: string): PublicationCommand | null {
  if (!mpRecord(value) || !validPublicationCommand(value.command)) return null;
  const command = value.command;
  return command.payload.approval_token === undefined && sameCommand(command, original, false) && review(value.review, command, principalId) && original.source_read_set.every(r => command.source_read_set.some(v => mpSame(v, r))) ? command : null;
}
export function publicationPrepared(value: unknown, original: PublicationCommand, principalId: string, now = Date.now()): PublicationPrepared | null {
  return mpRecord(value) && value.write_tier === "T2" && value.named_decision === true && (value.expires_at === null || (typeof value.expires_at === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value.expires_at) && Number.isFinite(Date.parse(value.expires_at)) && Date.parse(value.expires_at) > now)) && validPublicationCommand(value.command) && !!value.command.payload.approval_token && sameCommand(value.command, original) && review(value.review, value.command, principalId) ? value as PublicationPrepared : null;
}
export function publicationReceipt(value: unknown, command: PublicationCommand): value is PublicationReceipt {
  return mpRecord(value) && value.operation === publicationOperation && value.subject_type === "manufacturing_publication" && mpUuid(value.id) && mpUuid(value.subject_id) && value.subject_revision === (command.payload.expected_previous_revision ?? 0) + 1;
}
export function publicationVersion(value: unknown, projectId: string): value is PublicationVersion {
  return mpRecord(value) && value.schema_version === "pdos-manufacturing-publication-v1" && mpUuid(value.id) && mpRevision(value.revision) && value.project_id === projectId && value.status === "published" && typeof value.is_current === "boolean" && ["current", "needs_recheck"].includes(String(value.source_status)) && value.qualification === "unknown" && value.manufacturing_release === null && typeof value.purpose === "string" && mpRecord(value.body) && value.body.qualification === "unknown" && value.body.manufacturing_release === null && mpRecord(value.baseline) && value.baseline.kind === "manufacturing_baseline" && mpUuid(value.baseline.id) && mpRevision(value.baseline.revision) && mpRecord(value.process) && mpUuid(value.process.id) && mpRevision(value.process.revision) && Array.isArray(value.gaps) && value.gaps.every(v => mpRecord(v) && typeof v.code === "string" && typeof v.detail === "string") && mpUuid(value.receipt_id);
}
export async function runPublicationRequest(api: PublicationApi, pending: PublicationPending, principalId: string, onStage: (next: PublicationPending) => void, active: () => boolean) {
  if (!validPublicationCommand(pending.command) || !["inputs", "preview", "execute"].includes(pending.stage) || (pending.stage === "execute" ? !pending.command.payload.approval_token : pending.command.payload.approval_token !== undefined)) throw new Error("原发布请求的阶段或固定材料不一致。");
  let step = pending;
  if (!active()) return null;
  if (step.stage === "inputs") {
    const result = await api<unknown>(`v1/products/${step.command.product_id}/manufacturing-publications/inputs`, step.command);
    if (!active()) return null;
    const command = publicationInputs(result, step.command, principalId);
    if (!command) throw new Error("服务器未返回与原请求和本人一致的完整发布材料。");
    step = { stage: "preview", command }; onStage(step);
  }
  if (step.stage === "preview") {
    const result = await api<unknown>("v1/commands/preview", step.command);
    if (!active()) return null;
    const prepared = publicationPrepared(result, step.command, principalId);
    if (!prepared) throw new Error("尚未取得本次具名发布的完整预览。");
    return { stage: "preview" as const, prepared };
  }
  const result = await api<unknown>("v1/commands", step.command);
  if (!active()) return null;
  if (!publicationReceipt(result, step.command)) throw new Error("保存结果尚未核实，请保留原请求核对。");
  return { stage: "saved" as const, receipt: result };
}
