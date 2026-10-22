import { mpDecimal, mpRecord, mpRevision, mpSame, mpUuid } from "@/components/manufacturing-preparation/manufacturing-preparation-contract";
import { validQualitySource } from "@/lib/build-quality-loop-view";
import type { SourceRead } from "@/lib/project-plan-view";

export const releaseOperations = ["release.package.assemble", "release.engineering.approve", "release.manufacturing.approve"] as const;
export type ReleaseOperation = typeof releaseOperations[number];
export type ReleaseScope = { categoryId: string; productId: string; projectId: string; principalId: string };
export type ReleaseRef = { id: string; revision: number };
export type ReleasePayload = Record<string, unknown> & { purpose: string; reason: string; sources: Record<string, unknown>[]; release_scope: Record<string, unknown> };
export type ReleaseCommand = { category_id: string; product_id: string; expected_revision: number; command_id: string; idempotency_key: string; operation: ReleaseOperation; source_read_set: SourceRead[]; payload: ReleasePayload };
export type ReleaseAssessment = { discipline: "engineering" | "manufacturing"; state: "BLOCKED" | "UNKNOWN" | "READY_WITH_CONDITIONS" | "READY"; checks: Record<string, unknown>[]; blocked: string[]; unknown: string[]; conditions: ReleaseRef[] };
export type ReleaseInputs = { operation: ReleaseOperation; payload: ReleasePayload; required_source_read_set: SourceRead[]; candidate: Record<string, unknown>; assessments: ReleaseAssessment[]; authority: Record<string, unknown>; diagnostics: unknown[] };
export type ReleasePending = { stage: "inputs" | "review" | "preview" | "execute"; command: ReleaseCommand; inputs?: ReleaseInputs };
export type ReleasePrepared = { command: ReleaseCommand; review: Record<string, unknown>; expires_at: string | null; inputs: ReleaseInputs };
export type ReleaseReceipt = { id: string; subject_id: string; subject_revision: number; subject_type: "release_package" | "release_decision"; operation: ReleaseOperation };
export type ReleaseHeader = Record<string, unknown> & { id: string; revision: number; project_id: string; purpose?: string; receipt_id: string; applicability: "current" | "needs_recheck" | "not_checked"; current: { id: string; version: ReleaseRef; epoch: number } };
export type ReleaseDetail = ReleaseHeader & { applicability: "current" | "needs_recheck"; package: Record<string, unknown>; assessments: ReleaseAssessment[] | { engineering: ReleaseAssessment; manufacturing: ReleaseAssessment }; decisions: Record<string, unknown>[] };
export type ReleaseApi = <T>(path: string, body?: unknown) => Promise<T>;
export type ReleaseLocal = { schema_version: 1; scope: ReleaseScope; selected: ReleaseRef | null; operation: ReleaseOperation; drafts: Record<string, string>; pending: ReleasePending | null; receipt: ReleaseReceipt | null; completed: ReleaseCommand | null };
const clone = <T,>(v: T): T => structuredClone(v);
const version = (v: unknown): v is ReleaseRef & Record<string, unknown> => mpRecord(v) && mpUuid(v.id) && mpRevision(v.revision);
const hash = (v: unknown) => typeof v === "string" && /^[a-f0-9]{64}$/.test(v);
const token = (v: unknown) => typeof v === "string" && v.length >= 20 && v.length <= 128;
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
function reads(v: unknown): v is SourceRead[] { return Array.isArray(v) && v.length > 0 && v.every(r => mpRecord(r) && mpUuid(r.artifact_id) && mpRevision(r.expected_revision)) && new Set(v.map(r => r.artifact_id)).size === v.length; }
function releaseRange(v: unknown): v is Record<string, unknown> {
  if (!mpRecord(v) || ((v.quantity == null) !== (v.unit == null))) return false;
  if (v.quantity != null && (!text(v.unit) || !Number.isFinite(Number(v.quantity)) || Number(v.quantity) <= 0)) return false;
  return ["lots", "lines"].every(k => v[k] == null || (Array.isArray(v[k]) && v[k].every(version) && new Set(v[k].map(r => r.id)).size === v[k].length)) && (v.regions == null || (Array.isArray(v.regions) && v.regions.every(text) && new Set(v.regions).size === v.regions.length)) && (v.site == null || text(v.site));
}
function sourced(v: unknown) { return mpRecord(v) && text(v.text) && Array.isArray(v.sources) && v.sources.length > 0 && v.sources.every(validQualitySource); }
function subject(v: unknown) { return mpRecord(v) && ["definition", "engineering_configuration", "manufacturing_configuration"].every(k => version(v[k])); }
function rangeSemantic(v: Record<string, unknown>) { const result: Record<string, unknown> = { quantity: null, unit: null, lots: null, site: null, lines: null, regions: null, ...clone(v) }; if (result.quantity != null) result.quantity = mpDecimal(String(result.quantity)); return result; }
function instant(value: string) { const match = /\.(\d{1,6})(?:Z|[+-]\d{2}:\d{2})$/.exec(value), fraction = (match?.[1] ?? "").padEnd(6, "0"); return `${new Date(value).toISOString().slice(0, 19)}${Number(fraction) ? `.${fraction}` : ""}Z`; }
export function releaseSemantic(operation: ReleaseOperation, payload: Record<string, unknown>): Record<string, unknown> {
  const result: Record<string, unknown> = operation === releaseOperations[0] ? { manufacturing_publication: null, verifications: [], pilots: [], residuals: [], exceptions: [], documents: [], limits: [], visibility: "private", previous: null, ...clone(payload) } : { limits: [], expiry: null, ...clone(payload) };
  delete (result as Record<string, unknown>).approval_token;
  if (mpRecord(result.release_scope)) result.release_scope = rangeSemantic(result.release_scope);
  if (typeof result.expiry === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(result.expiry) && Number.isFinite(Date.parse(result.expiry))) result.expiry = instant(result.expiry);
  return result;
}
export function parseReleasePayload(raw: string | unknown, operation: ReleaseOperation, scope: ReleaseScope, selected: ReleaseRef | null = null): ReleasePayload {
  let value: unknown;
  try { value = typeof raw === "string" ? JSON.parse(raw) : clone(raw); } catch { throw new Error("请粘贴完整、有效的发布材料 JSON。"); }
  if (!mpRecord(value) || !text(value.purpose) || value.purpose !== value.purpose.trim() || !text(value.reason) || !releaseRange(value.release_scope) || !Array.isArray(value.sources) || !value.sources.length || !value.sources.every(validQualitySource) || !Array.isArray(value.limits ?? []) || !(value.limits as unknown[] | undefined ?? []).every(sourced)) throw new Error("须提供精确用途、范围、理由与真实原件完整行引用；未知范围明确留空。");
  if (operation === releaseOperations[0]) {
    if (value.project_id !== scope.projectId || !subject(value.subject_config) || !["private", "category", "audience"].includes(String(value.visibility ?? "private")) || (value.manufacturing_publication != null && !version(value.manufacturing_publication)) || (value.previous != null && !version(value.previous))) throw new Error("固定包须属于当前项目并引用精确定义与工程/制造配置版本。");
    for (const key of ["verifications", "pilots", "exceptions"]) if (!Array.isArray(value[key] ?? []) || !(value[key] as unknown[] | undefined ?? []).every(version)) throw new Error("测试、试产和例外须使用精确固定版本。");
    for (const key of ["residuals", "documents"]) if (!Array.isArray(value[key] ?? []) || !(value[key] as unknown[] | undefined ?? []).every(v => version(v) && mpRecord(v) && typeof v.kind === "string" && (key !== "residuals" || ["issue", "change"].includes(v.kind)))) throw new Error("遗留项须为真实问题或变更，文档须声明固定对象类型与版本。");
  } else if (!version(value.package) || !selected || !mpSame(value.package, selected) || (value.expiry != null && (typeof value.expiry !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value.expiry) || !Number.isFinite(Date.parse(value.expiry))))) throw new Error("具名决定须对应明确选中的包版本，期限须为带时区的真实时间或空。");
  return value as ReleasePayload;
}
export function releasePayloadReads(payload: ReleasePayload): SourceRead[] {
  const found = new Map<string, number>();
  function walk(v: unknown) { if (Array.isArray(v)) v.forEach(walk); else if (mpRecord(v)) { if (validQualitySource(v)) { const old = found.get(v.id); if (old !== undefined && old !== v.revision) throw new Error("同一原件不能固定两个版本。"); found.set(v.id, v.revision); } else Object.values(v).forEach(walk); } }
  walk(payload); return [...found].sort(([a], [b]) => a.localeCompare(b)).map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision }));
}
export function newReleaseCommand(scope: ReleaseScope, revision: number, operation: ReleaseOperation, payload: ReleasePayload): ReleaseCommand {
  parseReleasePayload(payload, operation, scope, operation === releaseOperations[0] ? null : payload.package as ReleaseRef);
  if (!mpRevision(revision)) throw new Error("须使用当前实际型号版本。");
  return { category_id: scope.categoryId, product_id: scope.productId, expected_revision: revision, operation, command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), source_read_set: releasePayloadReads(payload), payload: clone(payload) };
}
export function validReleaseCommand(v: unknown, scope: ReleaseScope): v is ReleaseCommand {
  if (!mpRecord(v) || v.category_id !== scope.categoryId || v.product_id !== scope.productId || !mpUuid(v.command_id) || !mpUuid(v.idempotency_key) || !mpRevision(v.expected_revision) || !releaseOperations.includes(v.operation as ReleaseOperation) || !reads(v.source_read_set) || !mpRecord(v.payload)) return false;
  try { parseReleasePayload(v.payload, v.operation as ReleaseOperation, scope, v.operation === releaseOperations[0] ? null : v.payload.package as ReleaseRef); return true; } catch { return false; }
}
export function releaseAssessments(value: unknown): ReleaseAssessment[] | null {
  const rows = Array.isArray(value) ? value : mpRecord(value) ? [value.engineering, value.manufacturing].filter(v => v != null) : null;
  if (!rows || !rows.every(v => mpRecord(v) && ["engineering", "manufacturing"].includes(String(v.discipline)) && ["BLOCKED", "UNKNOWN", "READY_WITH_CONDITIONS", "READY"].includes(String(v.state)) && Array.isArray(v.checks) && v.checks.every(mpRecord) && Array.isArray(v.blocked) && v.blocked.every(text) && Array.isArray(v.unknown) && v.unknown.every(text) && Array.isArray(v.conditions) && v.conditions.every(version)) || new Set(rows.map(v => v.discipline)).size !== rows.length) return null;
  return rows as ReleaseAssessment[];
}
export function releaseDiscipline(operation: ReleaseOperation) { return operation === releaseOperations[1] ? "engineering" : operation === releaseOperations[2] ? "manufacturing" : null; }
export function releaseReady(candidate: Record<string, unknown>, assessment: ReleaseAssessment | undefined): boolean { return !!assessment && ["READY", "READY_WITH_CONDITIONS"].includes(assessment.state) && !assessment.blocked.length && !assessment.unknown.length && text(candidate.policy_version ?? (mpRecord(candidate.policy) ? candidate.policy.version : null)); }
export function releaseAuthorityReady(authority: unknown, command: ReleaseCommand, scope: ReleaseScope): boolean { return mpRecord(authority) && authority.subject_id === scope.principalId && authority.operation === command.operation && authority.purpose === command.payload.purpose && authority.authorized === true && authority.qualified === true && Array.isArray(authority.roles) && authority.roles.includes(releaseDiscipline(command.operation)) && mpRecord(authority.scope) && authority.scope.product_id === scope.productId && authority.scope.project_id === scope.projectId; }
function validCandidate(v: unknown, command: ReleaseCommand, scope: ReleaseScope): v is Record<string, unknown> {
  if (!mpRecord(v) || v.structural_only !== true || v.status !== "unexecuted_candidate" || !mpRecord(v.scope) || v.scope.product_id !== scope.productId || v.scope.project_id !== scope.projectId || v.category_id !== scope.categoryId || !hash(v.evidence_digest)) return false;
  if (command.operation === releaseOperations[0]) return mpRecord(v.declaration) && mpSame(releaseSemantic(command.operation, v.declaration), releaseSemantic(command.operation, command.payload)) && subject(v.declaration.subject_config) && Array.isArray(v.objects) && v.objects.length > 0 && v.objects.every(o => mpRecord(o) && version(o.ref) && hash(o.sha256)) && hash(v.body_sha256) && (v.policy === null || (mpRecord(v.policy) && text(v.policy.version) && Array.isArray(v.policy.sources) && v.policy.sources.length > 0));
  return v.operation === command.operation && v.discipline === releaseDiscipline(command.operation) && mpSame(v.package, command.payload.package) && hash(v.package_sha256) && subject(v.subject_config) && releaseRange(v.release_scope) && mpSame(rangeSemantic(v.release_scope), rangeSemantic(command.payload.release_scope)) && v.purpose === command.payload.purpose && Array.isArray(v.limits) && v.limits.every(sourced) && ((command.payload.limits ?? []) as unknown[]).every(limit => (v.limits as unknown[]).some(actual => mpSame(actual, limit))) && mpRecord(v.input_snapshot) && mpSame(releaseSemantic(command.operation, v.input_snapshot), releaseSemantic(command.operation, command.payload)) && mpSame(releaseSemantic(command.operation, { expiry: v.expiry }).expiry, releaseSemantic(command.operation, command.payload).expiry) && Array.isArray(v.signers) && v.signers.length === 1 && v.signers[0] === scope.principalId && v.customer_acceptance === null && v.external_received === false && v.external_effective === false && mpRecord(v.assessment) && v.assessment.discipline === v.discipline && releaseAssessments([v.assessment]) !== null;
}
export function releaseInputs(value: unknown, command: ReleaseCommand, scope: ReleaseScope): ReleaseInputs | null {
  if (!mpRecord(value) || value.operation !== command.operation || !mpRecord(value.payload) || !mpSame(releaseSemantic(command.operation, value.payload), releaseSemantic(command.operation, command.payload)) || !reads(value.required_source_read_set) || !command.source_read_set.every(r => (value.required_source_read_set as SourceRead[]).some(v => mpSame(v, r))) || !validCandidate(value.candidate, command, scope) || !Array.isArray(value.diagnostics)) return null;
  const assessments = releaseAssessments(value.assessments); return assessments ? { operation: command.operation, payload: value.payload as ReleasePayload, candidate: value.candidate, required_source_read_set: value.required_source_read_set, assessments, authority: mpRecord(value.authority) ? value.authority : {}, diagnostics: value.diagnostics } : null;
}
function sameCommand(a: ReleaseCommand, b: ReleaseCommand) { return (["category_id", "product_id", "command_id", "idempotency_key", "operation", "expected_revision"] as const).every(k => a[k] === b[k]) && mpSame(a.source_read_set, b.source_read_set) && mpSame(releaseSemantic(a.operation, a.payload), releaseSemantic(b.operation, b.payload)); }
export function releasePrepared(value: unknown, pending: ReleasePending, scope: ReleaseScope, now = Date.now()): ReleasePrepared | null {
  const original = pending.command;
  if (original.operation === releaseOperations[0] || !pending.inputs || !mpRecord(value) || value.write_tier !== "T2" || value.named_decision !== true || !validReleaseCommand(value.command, scope) || !token(value.command.payload.approval_token) || (value.approval_token != null && value.approval_token !== value.command.payload.approval_token) || !sameCommand(value.command, original) || !(value.expires_at === null || (typeof value.expires_at === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(value.expires_at) && Number.isFinite(Date.parse(value.expires_at)) && Date.parse(value.expires_at) > now)) || !mpRecord(value.review)) return null;
  const review = value.review, authority = review.authority, candidate = review.after;
  if (review.operation !== original.operation || !validCandidate(candidate, value.command, scope) || candidate.package_sha256 !== pending.inputs.candidate.package_sha256 || candidate.evidence_digest !== pending.inputs.candidate.evidence_digest || candidate.policy_version !== pending.inputs.candidate.policy_version || !mpSame(candidate.subject_config, pending.inputs.candidate.subject_config) || !mpSame(candidate.limits, pending.inputs.candidate.limits) || !releaseAuthorityReady(authority, original, scope) || !mpSame(review.required_source_read_set, original.source_read_set)) return null;
  const assessments = releaseAssessments(review.assessments), discipline = releaseDiscipline(original.operation);
  if (!assessments || !discipline || !releaseReady(candidate, releaseAssessments([candidate.assessment])?.[0])) return null;
  return { command: value.command, review, expires_at: value.expires_at as string | null, inputs: { ...pending.inputs, candidate, assessments, authority: authority as Record<string, unknown> } };
}
export function releaseReceipt(v: unknown, command: ReleaseCommand): v is ReleaseReceipt { return mpRecord(v) && mpUuid(v.id) && mpUuid(v.subject_id) && mpRevision(v.subject_revision) && v.operation === command.operation && v.subject_type === (command.operation === releaseOperations[0] ? "release_package" : "release_decision") && (command.operation !== releaseOperations[0] || v.subject_revision === (version(command.payload.previous) ? command.payload.previous.revision + 1 : 1)); }
export async function runReleaseRequest(api: ReleaseApi, pending: ReleasePending, scope: ReleaseScope, onStage: (v: ReleasePending) => void, active: () => boolean) {
  if (!validReleaseCommand(pending.command, scope) || !["inputs", "review", "preview", "execute"].includes(pending.stage) || (pending.command.operation === releaseOperations[0] ? pending.command.payload.approval_token != null : pending.stage === "execute" ? !token(pending.command.payload.approval_token) : pending.command.payload.approval_token != null)) throw new Error("原发布包请求的范围、身份或阶段不一致。");
  let step = pending; if (!active()) return null;
  if (step.stage === "inputs") {
    const raw = await api<unknown>(`v1/products/${scope.productId}/release/inputs`, step.command); if (!active()) return null;
    const inputs = releaseInputs(raw, step.command, scope); if (!inputs) throw new Error("服务器未返回与原请求一致的固定材料及专业检查。");
    const command = { ...step.command, source_read_set: clone(inputs.required_source_read_set) }, discipline = releaseDiscipline(command.operation);
    step = { stage: discipline && releaseReady(inputs.candidate, releaseAssessments([inputs.candidate.assessment])?.[0]) && releaseAuthorityReady(inputs.authority, command, scope) ? "preview" : "review", command, inputs }; onStage(step);
  }
  if (step.stage === "review") { if (!step.inputs) throw new Error("原核对材料缺失，请重新读取同一原请求。"); return { stage: "review" as const, inputs: step.inputs, command: step.command }; }
  if (step.stage === "preview") { const raw = await api<unknown>("v1/commands/preview", step.command); if (!active()) return null; const prepared = releasePrepared(raw, step, scope); if (!prepared) throw new Error("尚未取得本人、本包版本及实际范围一致的具名预览。"); return { stage: "preview" as const, prepared }; }
  const raw = await api<unknown>("v1/commands", step.command); if (!active()) return null; if (!releaseReceipt(raw, step.command)) throw new Error("原提交结果尚未核实，请保留原请求。"); return { stage: "saved" as const, receipt: raw };
}
export function releaseHeader(v: unknown, projectId: string): v is ReleaseHeader { return mpRecord(v) && version(v) && v.project_id === projectId && mpUuid(v.receipt_id) && ["current", "needs_recheck", "not_checked"].includes(String(v.applicability)) && mpRecord(v.current) && mpUuid(v.current.id) && version(v.current.version) && mpRevision(v.current.epoch); }
export function releaseDetail(v: unknown, scope: ReleaseScope): v is ReleaseDetail { return releaseHeader(v, scope.projectId) && v.applicability !== "not_checked" && mpRecord(v.package) && v.package.structural_only === true && mpRecord(v.package.scope) && v.package.scope.product_id === scope.productId && v.package.scope.project_id === scope.projectId && v.package.category_id === scope.categoryId && mpRecord(v.package.declaration) && v.package.declaration.project_id === scope.projectId && subject(v.package.declaration.subject_config) && releaseRange(v.package.declaration.release_scope) && Array.isArray(v.package.objects) && hash(v.package.evidence_digest) && releaseAssessments(v.assessments) !== null && Array.isArray(v.decisions) && v.decisions.every(d => mpRecord(d) && version(d) && ["engineering", "manufacturing"].includes(String(d.discipline)) && mpSame(d.package, { id: v.id, revision: v.revision }) && mpRecord(d.decision) && mpUuid(d.receipt_id) && ["current", "needs_recheck"].includes(String(d.applicability))); }
export function releaseDraftKey(operation: ReleaseOperation, selected: ReleaseRef | null) { return `${operation}:${operation === releaseOperations[0] ? "new" : selected ? `${selected.id}:${selected.revision}` : "unselected"}`; }
export function blankReleaseLocal(scope: ReleaseScope): ReleaseLocal { return { schema_version: 1, scope: clone(scope), selected: null, operation: releaseOperations[0], drafts: {}, pending: null, receipt: null, completed: null }; }
export function restoreReleaseLocal(value: unknown, scope: ReleaseScope): ReleaseLocal | null {
  if (!mpRecord(value) || value.schema_version !== 1 || !mpSame(value.scope, scope) || !(value.selected === null || version(value.selected)) || !releaseOperations.includes(value.operation as ReleaseOperation) || !mpRecord(value.drafts) || !Object.values(value.drafts).every(v => typeof v === "string")) return null;
  const local = value as ReleaseLocal;
  if (local.pending !== null) {
    const p = local.pending;
    if (!mpRecord(p) || !validReleaseCommand(p.command, scope) || p.command.operation !== local.operation || !["inputs", "review", "preview", "execute"].includes(p.stage) || local.receipt !== null || local.completed !== null || (p.command.operation !== releaseOperations[0] && !mpSame(p.command.payload.package, local.selected))) return null;
    try { const draft = parseReleasePayload(local.drafts[releaseDraftKey(local.operation, local.selected)], local.operation, scope, local.selected); if (!mpSame(releaseSemantic(local.operation, draft), releaseSemantic(local.operation, p.command.payload))) return null; } catch { return null; }
    if (p.command.operation === releaseOperations[0] ? p.command.payload.approval_token != null : p.stage === "execute" ? !token(p.command.payload.approval_token) : p.command.payload.approval_token != null) return null;
    if (["review", "preview"].includes(p.stage) && (!p.inputs || !releaseInputs(p.inputs, p.command, scope) || !mpSame(p.inputs.required_source_read_set, p.command.source_read_set))) return null;
  }
  if (local.receipt !== null && (!local.completed || local.pending !== null || !validReleaseCommand(local.completed, scope) || !releaseReceipt(local.receipt, local.completed))) return null;
  return clone(local);
}
export function approvalDraft(detail: ReleaseDetail): string { const p = detail.package.declaration as Record<string, unknown>; return JSON.stringify({ package: { id: detail.id, revision: detail.revision }, release_scope: clone(p.release_scope), purpose: p.purpose, limits: p.limits ?? [], expiry: null, sources: clone(p.sources), reason: "" }, null, 2); }
