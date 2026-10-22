import { mpDecimal, mpRecord, mpRevision, mpSame, mpUuid } from "@/components/manufacturing-preparation/manufacturing-preparation-contract";
import { validQualitySource } from "@/lib/build-quality-loop-view";
import type { SourceRead } from "@/lib/project-plan-view";
import type { ReleaseApi, ReleaseDetail, ReleaseRef, ReleaseScope } from "@/lib/releases";

export const handoffOperations = ["integration.handoff.authorize", "integration.receipt.record"] as const;
export type HandoffOperation = typeof handoffOperations[number];
export type HandoffScope = ReleaseScope;
export type HandoffApi = ReleaseApi;
export type HandoffRef = ReleaseRef;
export type HandoffPayload = Record<string, unknown> & { reason: string };
export type HandoffCommand = { category_id: string; product_id: string; expected_revision: number; command_id: string; idempotency_key: string; operation: HandoffOperation; source_read_set: SourceRead[]; payload: HandoffPayload };
export type HandoffInputs = { operation: HandoffOperation; payload: HandoffPayload; candidate: Record<string, unknown>; required_source_read_set: SourceRead[]; authority: Record<string, unknown>; diagnostics: unknown[] };
export type HandoffPending = { stage: "inputs" | "review" | "preview" | "execute"; command: HandoffCommand; inputs?: HandoffInputs };
export type HandoffPrepared = { command: HandoffCommand; expires_at: string | null; review: Record<string, unknown>; inputs: HandoffInputs };
export type HandoffActionReceipt = { id: string; subject_id: string; subject_revision: number; subject_type: "external_handoff" | "external_receipt"; operation: HandoffOperation };
export type HandoffStage = { stage: "sent" | "accepted" | "effective"; state: "not_recorded" | "succeeded" | "partial" | "unknown" | "rejected" | "failed" | "conflict"; active: HandoffRef[]; covered_scopes: Record<string, unknown>[]; mismatches: string[] };
export type HandoffReading = { status: "authorized" | "sent" | "acknowledged" | "reconciled"; sent: HandoffStage; accepted: HandoffStage; effective: HandoffStage; delivery_unknown: boolean; rejected: boolean; failed: boolean; conflict: boolean; network_send: false };
export type HandoffWatermark = { id: string; handoff: HandoffRef; intent: HandoffRef; receipt_count: number; latest_receipt: HandoffRef | null; epoch: number; projection_sha256: string };
export type HandoffHeader = Record<string, unknown> & { id: string; revision: number; project_id: string; purpose: string; package: HandoffRef; receipt_id: string; as_of: HandoffWatermark; reading: HandoffReading; network_send: false };
export type HandoffDetail = HandoffHeader & { authorization: Record<string, unknown>; authority: Record<string, unknown>; intent: HandoffRef & { packet: Record<string, unknown> }; applicability: "current" | "needs_recheck" };
export type HandoffHistory = HandoffRef & { sequence: number; original: Record<string, unknown>; source: Record<string, unknown>; issuer: Record<string, unknown>; mismatches: string[]; receipt_id: string; received_at: string };
export type HandoffSelection = { selected: HandoffRef | null; intent: HandoffRef | null; package: HandoffRef | null; engineering: HandoffRef | null; manufacturing: HandoffRef | null };
export type HandoffLocal = HandoffSelection & { schema_version: 1; scope: HandoffScope; operation: HandoffOperation; drafts: Record<string, string>; pending: HandoffPending | null; receipt: HandoffActionReceipt | null; completed: HandoffCommand | null };

const clone = <T,>(value: T): T => structuredClone(value);
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
export const handoffRef = (v: unknown): v is HandoffRef & Record<string, unknown> => mpRecord(v) && mpUuid(v.id) && mpRevision(v.revision);
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const token = (v: unknown) => typeof v === "string" && v.length >= 20 && v.length <= 128;
const strings = (v: unknown): v is string[] => Array.isArray(v) && v.every(text);
const keys = (v: Record<string, unknown>, allowed: string[]) => Object.keys(v).every(key => allowed.includes(key));
const source = (v: unknown): v is Record<string, unknown> => validQualitySource(v) && mpUuid(v.id);
function reads(v: unknown): v is SourceRead[] { return Array.isArray(v) && v.length > 0 && v.every(r => mpRecord(r) && mpUuid(r.artifact_id) && mpRevision(r.expected_revision)) && new Set(v.map(r => r.artifact_id)).size === v.length; }
function subject(v: unknown) { return mpRecord(v) && ["definition", "engineering_configuration", "manufacturing_configuration"].every(key => handoffRef(v[key])); }
export function handoffRange(v: unknown): v is Record<string, unknown> {
  if (!mpRecord(v) || ((v.quantity == null) !== (v.unit == null))) return false;
  if (v.quantity != null && (!text(v.unit) || !Number.isFinite(Number(v.quantity)) || Number(v.quantity) <= 0)) return false;
  return ["lots", "lines"].every(key => v[key] == null || (Array.isArray(v[key]) && v[key].every(handoffRef) && new Set(v[key].map(ref => ref.id)).size === v[key].length)) && (v.regions == null || (strings(v.regions) && new Set(v.regions).size === v.regions.length)) && (v.site == null || text(v.site));
}
function destination(v: unknown) { return mpRecord(v) && keys(v, ["system", "recipient_id"]) && text(v.system) && text(v.recipient_id); }
function mappings(v: unknown) { return Array.isArray(v) && v.every(row => mpRecord(row) && keys(row, ["ref", "external_number", "external_version", "sources"]) && handoffRef(row.ref) && mpRecord(row.ref) && ["definition", "engineering_configuration", "process_revision", "part", "bom_revision", "artifact", "work_instruction", "control_plan"].includes(String(row.ref.kind)) && text(row.external_number) && text(row.external_version) && Array.isArray(row.sources) && row.sources.length > 0 && row.sources.every(source)) && new Set(v.map(row => `${row.ref.kind}:${row.ref.id}`)).size === v.length; }
function manifest(v: unknown) { return Array.isArray(v) && v.every(row => mpRecord(row) && keys(row, ["artifact", "logical_name", "content_sha256", "external_number", "external_version", "sources"]) && handoffRef(row.artifact) && text(row.logical_name) && hash(row.content_sha256) && text(row.external_number) && text(row.external_version) && Array.isArray(row.sources) && row.sources.length > 0 && row.sources.every(source)) && new Set(v.map(row => row.logical_name)).size === v.length && new Set(v.map(row => row.artifact.id)).size === v.length; }
function rangeSemantic(value: Record<string, unknown>) { const result = { quantity: null, unit: null, lots: null, site: null, lines: null, regions: null, ...clone(value) } as Record<string, unknown>; if (result.quantity != null) result.quantity = mpDecimal(String(result.quantity)); return result; }
export function handoffSemantic(operation: HandoffOperation, payload: Record<string, unknown>) {
  const result: Record<string, unknown> = operation === handoffOperations[0] ? { visibility: "private", mappings: [], manifest: [], ...clone(payload) } : clone(payload);
  delete result.approval_token;
  if (mpRecord(result.release_scope)) result.release_scope = rangeSemantic(result.release_scope);
  return result;
}
export function parseHandoffPayload(raw: unknown, operation: HandoffOperation, scope: HandoffScope, selected?: HandoffSelection): HandoffPayload {
  let value: unknown;
  try { value = typeof raw === "string" ? JSON.parse(raw) : clone(raw); } catch { throw new Error("请粘贴完整、有效的移交材料 JSON。"); }
  if (!mpRecord(value) || !text(value.reason)) throw new Error("须说明本次实际办理理由。");
  if (operation === handoffOperations[0]) {
    if (!keys(value, ["project_id", "package", "engineering_decision", "manufacturing_decision", "subject_config", "release_scope", "purpose", "visibility", "destination", "external_id", "mappings", "manifest", "sources", "reason", "approval_token"]) || value.project_id !== scope.projectId || !handoffRef(value.package) || !handoffRef(value.engineering_decision) || !handoffRef(value.manufacturing_decision) || mpSame(value.engineering_decision, value.manufacturing_decision) || !subject(value.subject_config) || !handoffRange(value.release_scope) || !text(value.purpose) || value.purpose !== value.purpose.trim() || !["private", "category", "audience"].includes(String(value.visibility ?? "private")) || !destination(value.destination) || !text(value.external_id) || !mappings(value.mappings ?? []) || !manifest(value.manifest ?? []) || !Array.isArray(value.sources) || !value.sources.length || !value.sources.every(source)) throw new Error("授权须固定真实发布包、两项分别决定、定义与双配置、用途范围、收件方、外部编号、manifest和来源。");
    if (selected && (!mpSame(value.package, selected.package) || !mpSame(value.engineering_decision, selected.engineering) || !mpSame(value.manufacturing_decision, selected.manufacturing))) throw new Error("材料须对应明确选择的实际固定包及两项具体决定。");
  } else if (!keys(value, ["handoff", "intent", "source", "reason"]) || !handoffRef(value.handoff) || !handoffRef(value.intent) || !source(value.source) || (selected && (!mpSame(value.handoff, selected.selected) || !mpSame(value.intent, selected.intent)))) throw new Error("回执只引用所选移交、原发送意图与真实原文；发行者由可信宿主核对，不能在材料中指定。");
  return value as HandoffPayload;
}
export function handoffPayloadReads(payload: HandoffPayload): SourceRead[] {
  const found = new Map<string, number>();
  function walk(v: unknown) { if (Array.isArray(v)) v.forEach(walk); else if (mpRecord(v)) { if (source(v)) { const previous = found.get(v.id as string); if (previous !== undefined && previous !== v.revision) throw new Error("同一原件不能固定两个版本。"); found.set(v.id as string, v.revision as number); } else Object.values(v).forEach(walk); } }
  walk(payload); return [...found].sort(([a], [b]) => a.localeCompare(b)).map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision }));
}
export function newHandoffCommand(scope: HandoffScope, revision: number, operation: HandoffOperation, payload: HandoffPayload): HandoffCommand {
  parseHandoffPayload(payload, operation, scope);
  if (!mpRevision(revision) || payload.approval_token != null) throw new Error("须使用当前型号版本，不自行填写批准令牌。");
  return { category_id: scope.categoryId, product_id: scope.productId, expected_revision: revision, operation, command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), source_read_set: handoffPayloadReads(payload), payload: clone(payload) };
}
export function validHandoffCommand(v: unknown, scope: HandoffScope): v is HandoffCommand {
  if (!mpRecord(v) || v.category_id !== scope.categoryId || v.product_id !== scope.productId || !mpUuid(v.command_id) || !mpUuid(v.idempotency_key) || !mpRevision(v.expected_revision) || !handoffOperations.includes(v.operation as HandoffOperation) || !reads(v.source_read_set) || !mpRecord(v.payload)) return false;
  try { parseHandoffPayload(v.payload, v.operation as HandoffOperation, scope); return true; } catch { return false; }
}
function scoped(v: Record<string, unknown>, scope: HandoffScope) { return mpRecord(v.scope) && v.scope.product_id === scope.productId && v.scope.project_id === scope.projectId && v.category_id === scope.categoryId; }
function issuer(v: unknown) { return mpRecord(v) && text(v.key) && text(v.version) && mpRevision(v.epoch) && text(v.system) && text(v.subject_id) && hash(v.proof_sha256); }
function receiptOriginal(v: unknown, handoff?: HandoffRef, intent?: HandoffRef): v is Record<string, unknown> { return mpRecord(v) && v.schema_version === "pdos-external-receipt-v1" && handoffRef(v.handoff) && handoffRef(v.intent) && (!handoff || mpSame(v.handoff, handoff)) && (!intent || mpSame(v.intent, intent)) && destination(v.destination) && text(v.external_id) && hash(v.manifest_sha256) && handoffRange(v.release_scope) && ["sent", "accepted", "effective"].includes(String(v.stage)) && ["succeeded", "unknown", "rejected", "failed"].includes(String(v.outcome)) && text(v.external_receipt_id) && typeof v.occurred_at === "string" && Number.isFinite(Date.parse(v.occurred_at)) && (v.reconciles === null || handoffRef(v.reconciles)); }
function candidate(v: unknown, command: HandoffCommand, scope: HandoffScope): v is Record<string, unknown> {
  if (!mpRecord(v) || !scoped(v, scope) || v.structural_only !== true || v.status !== "unexecuted_candidate" || v.operation !== command.operation || v.network_send !== false || !reads(v.required_source_read_set) || !Array.isArray(v.sources) || !v.sources.every(source) || !strings(v.unknown)) return false;
  if (command.operation === handoffOperations[0]) return mpRecord(v.declaration) && mpSame(handoffSemantic(command.operation, v.declaration), handoffSemantic(command.operation, command.payload)) && hash(v.package_sha256) && hash(v.manifest_sha256) && hash(v.mappings_sha256) && hash(v.content_sha256) && Array.isArray(v.signers) && v.signers.length === 1 && v.signers[0] === scope.principalId && Array.isArray(v.limits) && strings(v.blocked) && ["READY", "UNKNOWN", "BLOCKED"].includes(String(v.state)) && v.external_received === false && v.external_effective === false;
  return receiptOriginal(v.original, command.payload.handoff as HandoffRef, command.payload.intent as HandoffRef) && mpSame(v.source, command.payload.source) && (v.issuer === null || issuer(v.issuer)) && strings(v.mismatches) && ["READY", "UNKNOWN"].includes(String(v.state));
}
export function handoffReady(value: HandoffInputs): boolean { return value.candidate.state === "READY" && Array.isArray(value.candidate.unknown) && !value.candidate.unknown.length && (value.operation === handoffOperations[0] ? Array.isArray(value.candidate.blocked) && !value.candidate.blocked.length : issuer(value.candidate.issuer)); }
export function handoffAuthorityReady(value: unknown, command: HandoffCommand, scope: HandoffScope) { return mpRecord(value) && value.subject_id === scope.principalId && value.operation === command.operation && value.purpose === command.payload.purpose && value.authorized === true && value.qualified === true && Array.isArray(value.roles) && value.roles.some(role => ["engineering", "manufacturing", "quality"].includes(String(role))) && mpRecord(value.scope) && value.scope.product_id === scope.productId && value.scope.project_id === scope.projectId; }
export function handoffInputs(v: unknown, command: HandoffCommand, scope: HandoffScope): HandoffInputs | null {
  if (!mpRecord(v) || v.operation !== command.operation || !mpRecord(v.payload) || !mpSame(handoffSemantic(command.operation, v.payload), handoffSemantic(command.operation, command.payload)) || !reads(v.required_source_read_set) || !command.source_read_set.every(row => (v.required_source_read_set as SourceRead[]).some(read => mpSame(read, row))) || !candidate(v.candidate, command, scope) || !mpSame(v.candidate.required_source_read_set, v.required_source_read_set) || !Array.isArray(v.diagnostics)) return null;
  return { operation: command.operation, payload: v.payload as HandoffPayload, candidate: v.candidate, required_source_read_set: v.required_source_read_set, authority: mpRecord(v.authority) ? v.authority : {}, diagnostics: v.diagnostics };
}
const normalizedCandidate = (value: Record<string, unknown>) => ({ ...clone(value), prepared_at: null, received_at: null });
function sameCommand(a: HandoffCommand, b: HandoffCommand) { return (["category_id", "product_id", "expected_revision", "command_id", "idempotency_key", "operation"] as const).every(key => a[key] === b[key]) && mpSame(a.source_read_set, b.source_read_set) && mpSame(handoffSemantic(a.operation, a.payload), handoffSemantic(b.operation, b.payload)); }
export function handoffPrepared(v: unknown, pending: HandoffPending, scope: HandoffScope, now = Date.now()): HandoffPrepared | null {
  if (pending.command.operation !== handoffOperations[0] || !pending.inputs || !mpRecord(v) || v.write_tier !== "T2" || v.named_decision !== true || !validHandoffCommand(v.command, scope) || !sameCommand(v.command, pending.command) || !token(v.command.payload.approval_token) || (v.approval_token != null && v.approval_token !== v.command.payload.approval_token) || !(v.expires_at === null || (typeof v.expires_at === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(v.expires_at) && Number.isFinite(Date.parse(v.expires_at)) && Date.parse(v.expires_at) > now)) || !mpRecord(v.review) || v.review.operation !== pending.command.operation || !candidate(v.review.after, v.command, scope) || !mpSame(normalizedCandidate(v.review.after), normalizedCandidate(pending.inputs.candidate)) || !mpSame(v.review.required_source_read_set, pending.command.source_read_set) || !handoffAuthorityReady(v.review.authority, pending.command, scope)) return null;
  const inputs = { ...pending.inputs, candidate: v.review.after, authority: v.review.authority as Record<string, unknown> };
  return handoffReady(inputs) ? { command: v.command, review: v.review, expires_at: v.expires_at as string | null, inputs } : null;
}
export function handoffPreviewCurrent(prepared: HandoffPrepared, now = Date.now()) { return prepared.expires_at === null || Date.parse(prepared.expires_at) > now; }
export function handoffActionReceipt(v: unknown, command: HandoffCommand): v is HandoffActionReceipt { return mpRecord(v) && mpUuid(v.id) && mpUuid(v.subject_id) && v.subject_revision === 1 && v.operation === command.operation && v.subject_type === (command.operation === handoffOperations[0] ? "external_handoff" : "external_receipt"); }
export async function runHandoffRequest(api: HandoffApi, pending: HandoffPending, scope: HandoffScope, onStage: (pending: HandoffPending) => void, active: () => boolean) {
  const auth = pending.command.operation === handoffOperations[0];
  if (!validHandoffCommand(pending.command, scope) || !["inputs", "review", "preview", "execute"].includes(pending.stage) || (auth && pending.stage === "execute" ? !token(pending.command.payload.approval_token) : pending.command.payload.approval_token != null) || (!auth && pending.stage === "preview")) throw new Error("原移交请求的范围、身份或阶段不一致。");
  let step = pending; if (!active()) return null;
  if (step.stage === "inputs") { const raw = await api<unknown>(`v1/products/${scope.productId}/external-handoff/inputs`, step.command); if (!active()) return null; const inputs = handoffInputs(raw, step.command, scope); if (!inputs) throw new Error("服务器未返回与原请求一致的实际移交材料。"); const command = { ...step.command, source_read_set: clone(inputs.required_source_read_set) }; step = { stage: auth && handoffReady(inputs) && handoffAuthorityReady(inputs.authority, command, scope) ? "preview" : "review", command, inputs }; onStage(step); }
  if (step.stage === "review") { if (!step.inputs) throw new Error("原核对材料缺失，请重新读取同一原请求。"); return { stage: "review" as const, inputs: step.inputs }; }
  if (step.stage === "preview") { const raw = await api<unknown>("v1/commands/preview", step.command); if (!active()) return null; const prepared = handoffPrepared(raw, step, scope); if (!prepared) throw new Error("尚未取得本人、固定发送包及真实范围一致的共同 T2 预览。"); return { stage: "preview" as const, prepared }; }
  const raw = await api<unknown>("v1/commands", step.command); if (!active()) return null; if (!handoffActionReceipt(raw, step.command)) throw new Error("原提交结果尚未核实，请保留原请求。"); return { stage: "saved" as const, receipt: raw };
}
function reading(v: unknown): v is HandoffReading {
  if (!mpRecord(v) || !["authorized", "sent", "acknowledged", "reconciled"].includes(String(v.status)) || v.network_send !== false || !["delivery_unknown", "rejected", "failed", "conflict"].every(key => typeof v[key] === "boolean")) return false;
  return ["sent", "accepted", "effective"].every(key => { const row = v[key]; return mpRecord(row) && row.stage === key && ["not_recorded", "succeeded", "partial", "unknown", "rejected", "failed", "conflict"].includes(String(row.state)) && Array.isArray(row.active) && row.active.every(handoffRef) && Array.isArray(row.covered_scopes) && row.covered_scopes.every(handoffRange) && strings(row.mismatches); });
}
function watermark(v: unknown, ref: HandoffRef): v is HandoffWatermark { return mpRecord(v) && mpUuid(v.id) && mpSame(v.handoff, ref) && handoffRef(v.intent) && Number.isSafeInteger(v.receipt_count) && Number(v.receipt_count) >= 0 && v.epoch === Number(v.receipt_count) + 1 && (Number(v.receipt_count) === 0 ? v.latest_receipt === null : handoffRef(v.latest_receipt)) && hash(v.projection_sha256); }
export function handoffHeader(v: unknown, projectId: string): v is HandoffHeader { return mpRecord(v) && handoffRef(v) && v.revision === 1 && v.project_id === projectId && text(v.purpose) && handoffRef(v.package) && mpUuid(v.receipt_id) && watermark(v.as_of, { id: v.id, revision: v.revision }) && reading(v.reading) && v.network_send === false; }
export function handoffDetail(v: unknown, scope: HandoffScope): v is HandoffDetail {
  return handoffHeader(v, scope.projectId) && mpRecord(v) && ["current", "needs_recheck"].includes(String(v.applicability)) && mpRecord(v.authorization) && scoped(v.authorization, scope) && mpRecord(v.authorization.declaration) && v.authorization.declaration.project_id === scope.projectId && mpSame(v.authorization.declaration.package, v.package) && subject(v.authorization.declaration.subject_config) && handoffRange(v.authorization.declaration.release_scope) && destination(v.authorization.declaration.destination) && manifest(v.authorization.declaration.manifest) && mappings(v.authorization.declaration.mappings) && v.authorization.network_send === false && mpRecord(v.authority) && handoffRef(v.intent) && mpSame({ id: v.intent.id, revision: v.intent.revision }, v.as_of.intent) && mpRecord(v.intent.packet) && mpSame(v.intent.packet.handoff, { id: v.id, revision: v.revision }) && mpSame(v.intent.packet.manifest, v.authorization.declaration.manifest) && mpSame(v.intent.packet.mappings, v.authorization.declaration.mappings) && v.intent.packet.network_send === false;
}
export function handoffHistoryPage(v: unknown, detail: HandoffDetail): v is { as_of: HandoffWatermark; items: HandoffHistory[]; before_sequence: number | null } {
  if (!mpRecord(v) || !mpSame(v.as_of, detail.as_of) || !Array.isArray(v.items)) return false;
  const rows = v.items;
  return rows.every(row => mpRecord(row) && handoffRef(row) && row.revision === 1 && mpRevision(row.sequence) && row.sequence <= detail.as_of.receipt_count && receiptOriginal(row.original, { id: detail.id, revision: detail.revision }, { id: detail.intent.id, revision: detail.intent.revision }) && source(row.source) && issuer(row.issuer) && strings(row.mismatches) && mpUuid(row.receipt_id) && text(row.received_at)) && rows.every((row, i) => i === 0 || rows[i - 1].sequence > row.sequence) && new Set(rows.map(row => row.id)).size === rows.length && (v.before_sequence === null || (mpRevision(v.before_sequence) && rows.length > 0 && v.before_sequence === rows[rows.length - 1].sequence));
}
export function handoffDraftKey(operation: HandoffOperation, local: HandoffSelection) { const ref = operation === handoffOperations[0] ? local.package : local.selected; return `${operation}:${ref ? `${ref.id}:${ref.revision}` : "new"}`; }
export function blankHandoffLocal(scope: HandoffScope): HandoffLocal { return { schema_version: 1, scope: clone(scope), selected: null, intent: null, package: null, engineering: null, manufacturing: null, operation: handoffOperations[0], drafts: {}, pending: null, receipt: null, completed: null }; }
export function restoreHandoffLocal(v: unknown, scope: HandoffScope): HandoffLocal | null {
  if (!mpRecord(v) || v.schema_version !== 1 || !mpSame(v.scope, scope) || !["selected", "intent", "package", "engineering", "manufacturing"].every(key => v[key] === null || handoffRef(v[key])) || !handoffOperations.includes(v.operation as HandoffOperation) || !mpRecord(v.drafts) || !Object.values(v.drafts).every(value => typeof value === "string")) return null;
  const local = v as HandoffLocal;
  if (local.pending !== null) { const p = local.pending; if (!mpRecord(p) || !validHandoffCommand(p.command, scope) || p.command.operation !== local.operation || !["inputs", "review", "preview", "execute"].includes(p.stage) || local.receipt !== null || local.completed !== null) return null;
    try { const draft = parseHandoffPayload(local.drafts[handoffDraftKey(local.operation, local)], local.operation, scope, local); if (!mpSame(handoffSemantic(local.operation, draft), handoffSemantic(local.operation, p.command.payload))) return null; } catch { return null; }
    if (p.command.operation === handoffOperations[0] && p.stage === "execute" ? !token(p.command.payload.approval_token) : p.command.payload.approval_token != null) return null;
    if (["review", "preview"].includes(p.stage) && (!p.inputs || !handoffInputs(p.inputs, p.command, scope) || !mpSame(p.inputs.required_source_read_set, p.command.source_read_set))) return null;
  }
  if (local.receipt !== null && (!local.completed || local.pending !== null || !validHandoffCommand(local.completed, scope) || !handoffActionReceipt(local.receipt, local.completed))) return null;
  return clone(local);
}
export function authorizationDraft(detail: ReleaseDetail, engineering: HandoffRef | null, manufacturing: HandoffRef | null) { const p = detail.package.declaration as Record<string, unknown>; return JSON.stringify({ project_id: detail.project_id, package: { id: detail.id, revision: detail.revision }, engineering_decision: engineering, manufacturing_decision: manufacturing, subject_config: clone(p.subject_config), release_scope: clone(p.release_scope), purpose: p.purpose, visibility: p.visibility ?? "private", destination: { system: "", recipient_id: "" }, external_id: "", mappings: [], manifest: [], sources: clone(p.sources), reason: "" }, null, 2); }
export function externalReceiptDraft(detail: HandoffDetail) { return JSON.stringify({ handoff: { id: detail.id, revision: detail.revision }, intent: { id: detail.intent.id, revision: detail.intent.revision }, source: null, reason: "" }, null, 2); }
