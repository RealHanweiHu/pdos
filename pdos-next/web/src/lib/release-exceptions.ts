import { mpDecimal, mpRecord, mpRevision, mpSame, mpUuid } from "@/components/manufacturing-preparation/manufacturing-preparation-contract";
import { validQualitySource } from "@/lib/build-quality-loop-view";
import { handoffRange, handoffRef } from "@/lib/external-handoffs";
import type { SourceRead } from "@/lib/project-plan-view";
import type { ReleaseApi, ReleaseDetail, ReleaseRef, ReleaseScope } from "@/lib/releases";

export const exceptionOperations = ["release.exception.decide", "release.exception.withdraw"] as const;
export type ExceptionOperation = typeof exceptionOperations[number];
export type ExceptionScope = ReleaseScope;
export type ExceptionApi = ReleaseApi;
export type ExceptionRef = ReleaseRef;
export type ExceptionPayload = Record<string, unknown> & { reason: string };
export type ExceptionCommand = { category_id: string; product_id: string; expected_revision: number; command_id: string; idempotency_key: string; operation: ExceptionOperation; source_read_set: SourceRead[]; payload: ExceptionPayload };
export type ExceptionPlan = Record<string, unknown> & { operation: ExceptionOperation; action: "approved" | "withdrawn"; discipline: "engineering" | "manufacturing"; purpose: string; state: "READY" | "UNKNOWN" | "BLOCKED"; unknown: string[]; blocked: string[]; selected_checks: Record<string, unknown>[] };
export type ExceptionInputs = { operation: ExceptionOperation; payload: ExceptionPayload; required_source_read_set: SourceRead[]; candidate: ExceptionPlan; authority: Record<string, unknown>; diagnostics: unknown[] };
export type ExceptionPending = { stage: "inputs" | "review" | "preview" | "execute"; command: ExceptionCommand; inputs?: ExceptionInputs };
export type ExceptionPrepared = { command: ExceptionCommand; review: Record<string, unknown>; expires_at: string | null; inputs: ExceptionInputs };
export type ExceptionReceipt = { id: string; subject_id: string; subject_revision: 1; subject_type: "release_exception"; operation: ExceptionOperation };
export type ExceptionWatermark = { decision: ExceptionRef; epoch: number; action: "approved" | "withdrawn" };
export type ExceptionHeader = Record<string, unknown> & { id: string; revision: 1; project_id: string; purpose: string; discipline: "engineering" | "manufacturing"; action: "approved" | "withdrawn"; basis_package: ExceptionRef; series_id: string; visibility: "private" | "category" | "audience"; expiry: string | null; created_at: string; receipt_id: string; as_of: ExceptionWatermark };
export type ExceptionDetail = ExceptionHeader & { decision: ExceptionPlan; authority: Record<string, unknown>; applicability: "current" | "needs_recheck"; current: ExceptionWatermark };
export type ExceptionSelection = { selected: ExceptionRef | null; package: ExceptionRef | null };
export type ExceptionLocal = ExceptionSelection & { schema_version: 1; scope: ExceptionScope; operation: ExceptionOperation; drafts: Record<string, string>; pending: ExceptionPending | null; receipt: ExceptionReceipt | null; completed: ExceptionCommand | null };

const clone = <T,>(value: T): T => structuredClone(value);
const text = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(text);
const uniqueStrings = (value: unknown): value is string[] => strings(value) && value.length > 0 && new Set(value).size === value.length;
const fields = (value: Record<string, unknown>, allowed: string[]) => Object.keys(value).every(key => allowed.includes(key));
const source = (value: unknown): value is Record<string, unknown> => validQualitySource(value) && mpUuid(value.id);
const sources = (value: unknown) => Array.isArray(value) && value.length > 0 && value.every(source);
const sourced = (value: unknown) => mpRecord(value) && fields(value, ["text", "sources"]) && text(value.text) && sources(value.sources);
const sourcedItems = (value: unknown) => Array.isArray(value) && value.length > 0 && value.every(sourced);
const timestamp = (value: unknown): value is string => typeof value === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const token = (value: unknown) => typeof value === "string" && value.length >= 20 && value.length <= 128;
const discipline = (value: unknown) => value === "engineering" || value === "manufacturing";
const ref = handoffRef;
function reads(value: unknown): value is SourceRead[] { return Array.isArray(value) && value.length > 0 && value.every(row => mpRecord(row) && mpUuid(row.artifact_id) && mpRevision(row.expected_revision)) && new Set(value.map(row => row.artifact_id)).size === value.length; }
function subject(value: unknown) { return mpRecord(value) && ["definition", "engineering_configuration", "manufacturing_configuration"].every(key => ref(value[key])); }
function rangeSemantic(value: Record<string, unknown>) { const result: Record<string, unknown> = { quantity: null, unit: null, lots: null, site: null, lines: null, regions: null, ...clone(value) }; if (result.quantity != null) result.quantity = mpDecimal(String(result.quantity)); return result; }
function instant(value: string) { const fraction = (/\.(\d{1,6})(?:Z|[+-]\d{2}:\d{2})$/.exec(value)?.[1] ?? "").padEnd(6, "0"); return `${new Date(value).toISOString().slice(0, 19)}${Number(fraction) ? `.${fraction}` : ""}Z`; }
export function exceptionSemantic(operation: ExceptionOperation, payload: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = operation === exceptionOperations[0] ? { expiry: null, ...clone(payload) } : clone(payload);
  delete result.approval_token;
  if (mpRecord(result.release_scope)) result.release_scope = rangeSemantic(result.release_scope);
  if (timestamp(result.expiry)) result.expiry = instant(result.expiry);
  return result;
}
export function parseExceptionPayload(raw: unknown, operation: ExceptionOperation, selection?: ExceptionSelection): ExceptionPayload {
  let value: unknown;
  try { value = typeof raw === "string" ? JSON.parse(raw) : clone(raw); } catch { throw new Error("请粘贴完整、有效的例外材料 JSON。"); }
  if (!mpRecord(value) || !text(value.reason) || !sources(value.sources)) throw new Error("须说明本次办理理由，并引用真实原件的固定版本及完整行。");
  if (operation === exceptionOperations[0]) {
    if (!fields(value, ["basis_package", "discipline", "release_scope", "purpose", "check_keys", "limits", "risk_controls", "expiry", "sources", "reason", "approval_token"]) || !ref(value.basis_package) || !discipline(value.discipline) || !handoffRange(value.release_scope) || !text(value.purpose) || value.purpose !== value.purpose.trim() || !uniqueStrings(value.check_keys) || !sourcedItems(value.limits) || !sourcedItems(value.risk_controls) || !(value.expiry == null || timestamp(value.expiry))) throw new Error("例外须固定实际包、专业、用途范围和唯一检查项，填写有来源的限制与风险控制；期限可留空。不得自行声明项目、可见范围或签发资格。");
    if (selection && !mpSame(value.basis_package, selection.package)) throw new Error("例外材料须对应明确选择的实际发布包版本。");
  } else if (operation !== exceptionOperations[1] || !fields(value, ["exception", "sources", "reason", "approval_token"]) || !ref(value.exception) || (selection && !mpSame(value.exception, selection.selected))) throw new Error("撤回须明确引用所选原例外决定、实际原件和理由。");
  if (value.approval_token != null && !token(value.approval_token)) throw new Error("原共同确认凭据格式不完整。");
  return value as ExceptionPayload;
}
export function exceptionPayloadReads(payload: ExceptionPayload): SourceRead[] {
  const found = new Map<string, number>();
  function walk(value: unknown) { if (Array.isArray(value)) value.forEach(walk); else if (mpRecord(value)) { if (source(value)) { const previous = found.get(value.id as string); if (previous !== undefined && previous !== value.revision) throw new Error("同一原件不能固定两个版本。"); found.set(value.id as string, value.revision as number); } else Object.values(value).forEach(walk); } }
  walk(payload); return [...found].sort(([a], [b]) => a.localeCompare(b)).map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision }));
}
export function newExceptionCommand(scope: ExceptionScope, revision: number, operation: ExceptionOperation, payload: ExceptionPayload): ExceptionCommand {
  parseExceptionPayload(payload, operation);
  if (!mpRevision(revision) || payload.approval_token != null) throw new Error("须使用当前型号版本；批准凭据只能来自本次共同预览。");
  return { category_id: scope.categoryId, product_id: scope.productId, expected_revision: revision, command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation, source_read_set: exceptionPayloadReads(payload), payload: clone(payload) };
}
export function validExceptionCommand(value: unknown, scope: ExceptionScope): value is ExceptionCommand {
  if (!mpRecord(value) || value.category_id !== scope.categoryId || value.product_id !== scope.productId || !mpRevision(value.expected_revision) || !mpUuid(value.command_id) || !mpUuid(value.idempotency_key) || !exceptionOperations.includes(value.operation as ExceptionOperation) || !reads(value.source_read_set)) return false;
  try { parseExceptionPayload(value.payload, value.operation as ExceptionOperation); return true; } catch { return false; }
}
function check(value: unknown): value is Record<string, unknown> { return mpRecord(value) && text(value.key) && ["engineering", "manufacturing", "both"].includes(String(value.discipline)) && ["applicable", "required", "non_waivable"].every(key => typeof value[key] === "boolean") && ["satisfied", "unknown", "blocked"].includes(String(value.state)) && text(value.detail) && sources(value.sources) && (value.release_scope == null || handoffRange(value.release_scope)) && (value.exception == null || ref(value.exception)); }
function plan(value: unknown, scope: ExceptionScope, reviewed = false): value is ExceptionPlan {
  if (!mpRecord(value) || value.structural_only !== true || value.status !== "unexecuted_candidate" || !exceptionOperations.includes(value.operation as ExceptionOperation) || value.action !== (value.operation === exceptionOperations[0] ? "approved" : "withdrawn") || !mpRecord(value.scope) || value.scope.product_id !== scope.productId || value.scope.project_id !== scope.projectId || value.category_id !== scope.categoryId || !mpUuid(value.owner_id) || !["private", "category", "audience"].includes(String(value.visibility)) || !discipline(value.discipline) || !ref(value.basis_package) || !(value.policy_fact === null || ref(value.policy_fact)) || !(value.policy_version === null || text(value.policy_version)) || !subject(value.subject_config) || !handoffRange(value.release_scope) || !text(value.purpose) || !uniqueStrings(value.check_keys) || !Array.isArray(value.selected_checks) || !value.selected_checks.every(check) || !sourcedItems(value.limits) || !sourcedItems(value.risk_controls) || !(value.expiry === null || timestamp(value.expiry)) || !sources(value.sources) || !reads(value.required_source_read_set) || !Array.isArray(value.signers) || value.signers.length !== 1 || !mpUuid(value.signers[0]) || !(timestamp(value.prepared_at) || (reviewed && value.prepared_at === null)) || !text(value.reason) || !["READY", "UNKNOWN", "BLOCKED"].includes(String(value.state)) || !strings(value.unknown) || !strings(value.blocked) || !(value.previous === null || ref(value.previous)) || !mpRecord(value.declaration)) return false;
  try { parseExceptionPayload(value.declaration, value.operation as ExceptionOperation); } catch { return false; }
  if (value.operation === exceptionOperations[0]) {
    const declaration = exceptionSemantic(value.operation, value.declaration), projected = exceptionSemantic(value.operation, Object.fromEntries(["basis_package", "discipline", "release_scope", "purpose", "check_keys", "limits", "risk_controls", "expiry", "reason"].map(key => [key, value[key]])));
    delete declaration.sources;
    if (!mpSame(declaration, projected) || value.previous !== null) return false;
  } else if (!mpSame(value.previous, value.declaration.exception) || value.reason !== value.declaration.reason) return false;
  return new Set(value.selected_checks.map(row => row.key)).size === value.selected_checks.length && value.selected_checks.every(row => (value.check_keys as string[]).includes(row.key as string));
}
function candidate(value: unknown, command: ExceptionCommand, scope: ExceptionScope, reviewed = false): value is ExceptionPlan { return plan(value, scope, reviewed) && value.operation === command.operation && mpSame(exceptionSemantic(command.operation, value.declaration as Record<string, unknown>), exceptionSemantic(command.operation, command.payload)) && (value.signers as string[])[0] === scope.principalId; }
export function exceptionReady(value: ExceptionInputs): boolean { return value.candidate.state === "READY" && !value.candidate.unknown.length && !value.candidate.blocked.length && ref(value.candidate.policy_fact) && text(value.candidate.policy_version) && value.candidate.selected_checks.length === (value.candidate.check_keys as string[]).length; }
export function exceptionAuthorityReady(value: unknown, command: ExceptionCommand, scope: ExceptionScope, candidate: ExceptionPlan): boolean { return mpRecord(value) && value.subject_id === scope.principalId && value.operation === command.operation && value.purpose === candidate.purpose && value.authorized === true && value.qualified === true && Array.isArray(value.roles) && value.roles.some(role => ["engineering", "manufacturing", "quality"].includes(String(role))) && mpRecord(value.scope) && value.scope.product_id === scope.productId && value.scope.project_id === scope.projectId; }
export function exceptionInputs(value: unknown, command: ExceptionCommand, scope: ExceptionScope): ExceptionInputs | null {
  if (!mpRecord(value) || value.operation !== command.operation || !mpRecord(value.payload) || !mpSame(exceptionSemantic(command.operation, value.payload), exceptionSemantic(command.operation, command.payload)) || !reads(value.required_source_read_set) || !command.source_read_set.every(row => (value.required_source_read_set as SourceRead[]).some(actual => mpSame(actual, row))) || !candidate(value.candidate, command, scope) || !mpSame(value.candidate.required_source_read_set, value.required_source_read_set) || !Array.isArray(value.diagnostics)) return null;
  return { operation: command.operation, payload: value.payload as ExceptionPayload, candidate: value.candidate, required_source_read_set: value.required_source_read_set, authority: mpRecord(value.authority) ? value.authority : {}, diagnostics: value.diagnostics };
}
const normalizedPlan = (value: ExceptionPlan) => ({ ...clone(value), prepared_at: null });
function sameCommand(a: ExceptionCommand, b: ExceptionCommand) { return (["category_id", "product_id", "expected_revision", "command_id", "idempotency_key", "operation"] as const).every(key => a[key] === b[key]) && mpSame(a.source_read_set, b.source_read_set) && mpSame(exceptionSemantic(a.operation, a.payload), exceptionSemantic(b.operation, b.payload)); }
export function exceptionPrepared(value: unknown, pending: ExceptionPending, scope: ExceptionScope, now = Date.now()): ExceptionPrepared | null {
  if (!pending.inputs || !mpRecord(value) || value.write_tier !== "T2" || value.named_decision !== true || !validExceptionCommand(value.command, scope) || !sameCommand(value.command, pending.command) || !token(value.command.payload.approval_token) || (value.approval_token != null && value.approval_token !== value.command.payload.approval_token) || !(value.expires_at === null || (timestamp(value.expires_at) && Date.parse(value.expires_at) > now)) || !mpRecord(value.review) || value.review.operation !== pending.command.operation || !candidate(value.review.after, value.command, scope, true) || !mpSame(normalizedPlan(value.review.after), normalizedPlan(pending.inputs.candidate)) || !mpSame(value.review.required_source_read_set, pending.command.source_read_set) || !exceptionAuthorityReady(value.review.authority, pending.command, scope, value.review.after)) return null;
  const inputs = { ...pending.inputs, candidate: value.review.after, authority: value.review.authority as Record<string, unknown> };
  return exceptionReady(inputs) ? { command: value.command, review: value.review, expires_at: value.expires_at as string | null, inputs } : null;
}
export function exceptionPreviewCurrent(value: ExceptionPrepared, now = Date.now()) { return value.expires_at === null || Date.parse(value.expires_at) > now; }
export function exceptionReceipt(value: unknown, command: ExceptionCommand): value is ExceptionReceipt { return mpRecord(value) && mpUuid(value.id) && mpUuid(value.subject_id) && value.subject_revision === 1 && value.subject_type === "release_exception" && value.operation === command.operation && (command.operation !== exceptionOperations[1] || !mpRecord(command.payload.exception) || value.subject_id !== command.payload.exception.id); }
export async function runExceptionRequest(api: ExceptionApi, pending: ExceptionPending, scope: ExceptionScope, onStage: (pending: ExceptionPending) => void, active: () => boolean) {
  if (!validExceptionCommand(pending.command, scope) || !["inputs", "review", "preview", "execute"].includes(pending.stage) || (pending.stage === "execute" ? !token(pending.command.payload.approval_token) : pending.command.payload.approval_token != null)) throw new Error("原例外请求的范围、身份或确认阶段不一致。");
  let step = pending; if (!active()) return null;
  if (step.stage === "inputs") { const raw = await api<unknown>(`v1/products/${scope.productId}/release-exception/inputs`, step.command); if (!active()) return null; const inputs = exceptionInputs(raw, step.command, scope); if (!inputs) throw new Error("服务器未返回与原请求一致的实际例外材料。"); const command = { ...step.command, source_read_set: clone(inputs.required_source_read_set) }; step = { stage: exceptionReady(inputs) && exceptionAuthorityReady(inputs.authority, command, scope, inputs.candidate) ? "preview" : "review", command, inputs }; onStage(step); }
  if (step.stage === "review") { if (!step.inputs || !exceptionInputs(step.inputs, step.command, scope)) throw new Error("原核对材料缺失，请重新读取同一原请求。"); return { stage: "review" as const, inputs: step.inputs }; }
  if (step.stage === "preview") { const raw = await api<unknown>("v1/commands/preview", step.command); if (!active()) return null; const prepared = exceptionPrepared(raw, step, scope); if (!prepared) throw new Error("尚未取得本人、固定政策与配置范围一致的共同 T2 预览。"); return { stage: "preview" as const, prepared }; }
  const raw = await api<unknown>("v1/commands", step.command); if (!active()) return null; if (!exceptionReceipt(raw, step.command)) throw new Error("原提交结果尚未核实，请保留原请求。"); return { stage: "saved" as const, receipt: raw };
}
function watermark(value: unknown): value is ExceptionWatermark { return mpRecord(value) && ref(value.decision) && value.decision.revision === 1 && mpRevision(value.epoch) && ["approved", "withdrawn"].includes(String(value.action)); }
export function exceptionHeader(value: unknown, projectId: string): value is ExceptionHeader { return mpRecord(value) && ref(value) && value.revision === 1 && value.project_id === projectId && text(value.purpose) && discipline(value.discipline) && ["approved", "withdrawn"].includes(String(value.action)) && ref(value.basis_package) && mpUuid(value.series_id) && ["private", "category", "audience"].includes(String(value.visibility)) && (value.expiry === null || timestamp(value.expiry)) && timestamp(value.created_at) && mpUuid(value.receipt_id) && watermark(value.as_of); }
export function exceptionDetail(value: unknown, scope: ExceptionScope): value is ExceptionDetail { return exceptionHeader(value, scope.projectId) && ["current", "needs_recheck"].includes(String(value.applicability)) && plan(value.decision, scope) && value.decision.action === value.action && value.decision.purpose === value.purpose && value.decision.discipline === value.discipline && value.decision.visibility === value.visibility && mpSame(value.decision.basis_package, value.basis_package) && mpRecord(value.authority) && watermark(value.current) && mpSame(value.current, value.as_of); }
export function exceptionDraftKey(operation: ExceptionOperation, selection: ExceptionSelection) { const selected = operation === exceptionOperations[0] ? selection.package : selection.selected; return `${operation}:${selected ? `${selected.id}:${selected.revision}` : "new"}`; }
export function blankExceptionLocal(scope: ExceptionScope): ExceptionLocal { return { schema_version: 1, scope: clone(scope), selected: null, package: null, operation: exceptionOperations[0], drafts: {}, pending: null, receipt: null, completed: null }; }
export function restoreExceptionLocal(value: unknown, scope: ExceptionScope): ExceptionLocal | null {
  if (!mpRecord(value) || value.schema_version !== 1 || !mpSame(value.scope, scope) || !["selected", "package"].every(key => value[key] === null || ref(value[key])) || !exceptionOperations.includes(value.operation as ExceptionOperation) || !mpRecord(value.drafts) || !Object.values(value.drafts).every(draft => typeof draft === "string")) return null;
  const local = value as ExceptionLocal;
  if (local.pending !== null) { const pending = local.pending; if (!mpRecord(pending) || !validExceptionCommand(pending.command, scope) || pending.command.operation !== local.operation || !["inputs", "review", "preview", "execute"].includes(pending.stage) || local.receipt !== null || local.completed !== null || (pending.stage === "execute" ? !token(pending.command.payload.approval_token) : pending.command.payload.approval_token != null)) return null;
    try { const draft = parseExceptionPayload(local.drafts[exceptionDraftKey(local.operation, local)], local.operation, local); if (!mpSame(exceptionSemantic(local.operation, draft), exceptionSemantic(local.operation, pending.command.payload))) return null; } catch { return null; }
    if (["review", "preview"].includes(pending.stage) && (!pending.inputs || !exceptionInputs(pending.inputs, pending.command, scope) || !mpSame(pending.inputs.required_source_read_set, pending.command.source_read_set))) return null;
  }
  if (local.receipt !== null && (!local.completed || local.pending !== null || !validExceptionCommand(local.completed, scope) || !exceptionReceipt(local.receipt, local.completed))) return null;
  if (local.completed !== null && local.receipt === null) return null;
  return clone(local);
}
export function exceptionDecideDraft(detail: ReleaseDetail) { const declaration = mpRecord(detail.package.declaration) ? detail.package.declaration : {}; return JSON.stringify({ basis_package: { id: detail.id, revision: detail.revision }, discipline: "engineering", release_scope: clone(declaration.release_scope), purpose: declaration.purpose, check_keys: [], limits: [{ text: "", sources: [] }], risk_controls: [{ text: "", sources: [] }], expiry: null, sources: [], reason: "" }, null, 2); }
export function exceptionWithdrawDraft(detail: ExceptionDetail) { return JSON.stringify({ exception: { id: detail.id, revision: detail.revision }, sources: [], reason: "" }, null, 2); }
