import { projectBuildsPath } from "./project-build-scope";
import { proofClockCurrent } from "./proof-clock";
import { sourceLines, type DefinitionSource } from "./product-view";

export type FollowupApi = <T>(path: string, body?: unknown) => Promise<T>;
export const followupOperations = ["quality.issue.root_cause.decide", "quality.capa.actions.complete", "quality.capa.followup.link"] as const;
export type FollowupOperation = typeof followupOperations[number];
export const followupNames: Record<FollowupOperation, string> = { "quality.issue.root_cause.decide": "具名根因决定", "quality.capa.actions.complete": "记录本人措施完成", "quality.capa.followup.link": "保存固定整改输出回链" };
export const followupTier = (operation: FollowupOperation): "T1" | "T2" => operation === "quality.issue.root_cause.decide" ? "T2" : "T1";
export const followupRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
export const followupRevision = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
export const followupUuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
export function followupStable(value: unknown): unknown { return Array.isArray(value) ? value.map(followupStable) : followupRecord(value) ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, row]) => [key, followupStable(row)])) : value; }
export const followupSame = (a: unknown, b: unknown): boolean => JSON.stringify(followupStable(a)) === JSON.stringify(followupStable(b));
export const followupCapability = (value: unknown, operation: string): boolean => followupOperations.includes(operation as FollowupOperation) && followupRecord(value) && value[operation] === true;
export const followupCancelled = (value: unknown): boolean => followupRecord(value) && value.code === "READ_SUPERSEDED";
export const followupSynthetic = (value: unknown): boolean => Array.isArray(value) ? value.some(followupSynthetic) : followupRecord(value) && (value.nature === "synthetic" || value.synthetic === true || Object.values(value).some(followupSynthetic));

export type FollowupRead = { artifact_id: string; expected_revision: number };
export function followupReads(...groups: FollowupRead[][]): FollowupRead[] {
  const refs = new Map<string, FollowupRead>();
  for (const row of groups.flat()) {
    if (!followupRecord(row) || !followupUuid(row.artifact_id) || !followupRevision(row.expected_revision)) throw new Error("来源读集缺少有效身份或固定版本。");
    const previous = refs.get(row.artifact_id);
    if (previous && previous.expected_revision !== row.expected_revision) throw new Error("同一来源不能在一次办理中混用两个版本。");
    refs.set(row.artifact_id, { artifact_id: row.artifact_id, expected_revision: row.expected_revision });
  }
  if (refs.size > 20) throw new Error("完整来源并集超过 20 份，不能截断；请缩小本次办理范围。");
  return [...refs.values()].sort((a, b) => a.artifact_id.localeCompare(b.artifact_id));
}
export type FollowupSource = { id: string; revision: number; kind: "artifact"; position: string };
export type FollowupExactSource = { artifact_id: string; expected_revision: number; line: number; quote: string };
export const validFollowupSource = (value: unknown): value is FollowupSource => followupRecord(value) && followupUuid(value.id) && followupRevision(value.revision) && value.kind === "artifact" && typeof value.position === "string" && /^line:[1-9]\d*;quote_sha256:[0-9a-f]{64}$/.test(value.position);
export const followupSourceKey = (ref: FollowupSource): string => JSON.stringify([ref.id, ref.revision, ref.position]);
export const validFollowupExactSource = (value: unknown): value is FollowupExactSource => followupRecord(value) && followupUuid(value.artifact_id) && followupRevision(value.expected_revision) && followupRevision(value.line) && typeof value.quote === "string" && !!value.quote.trim();
export async function followupSource(source: DefinitionSource, line: number): Promise<{ ref: FollowupSource; exact: FollowupExactSource }> {
  const quote = sourceLines(source.content)[line - 1];
  if (source.status !== "active" || !followupUuid(source.id) || !followupRevision(source.revision) || !followupRevision(line) || typeof quote !== "string" || !quote.trim()) throw new Error("请选择当前有效原文的完整行，不能以局部摘录代替。");
  const hash = [...new Uint8Array(await crypto.subtle.digest("SHA-256", new TextEncoder().encode(quote)))].map(byte => byte.toString(16).padStart(2, "0")).join("");
  return { ref: { id: source.id, revision: source.revision, kind: "artifact", position: `line:${line};quote_sha256:${hash}` }, exact: { artifact_id: source.id, expected_revision: source.revision, line, quote } };
}
export function followupSourceReads(refs: FollowupSource[]): FollowupRead[] { if (!refs.length || !refs.every(validFollowupSource)) throw new Error("每项内容须选有效、可精确核对的来源。"); return followupReads(refs.map(row => ({ artifact_id: row.id, expected_revision: row.revision }))); }
export function followupText(value: string): string { const result = value.trim(); if (!result || result.length > 2000) throw new Error("请填写具体内容，最多 2000 字。"); return result; }
export function followupTime(value: unknown): string | null { return typeof value === "string" && /^\d{4}-\d\d-\d\dT\d\d:\d\d:\d\d(?:\.\d+)?(?:Z|[+-]\d\d:\d\d)$/.test(value) && Number.isFinite(Date.parse(value)) ? value : null; }
export function followupZone(value: string): string { const text = value.trim(); try { if (!text || /^[+-]\d/.test(text)) throw new Error(); new Intl.DateTimeFormat("en", { timeZone: text }).format(); return text; } catch { throw new Error("请填写原 IANA 时区，例如 America/Los_Angeles。"); } }
function timeIdentity(value: unknown): string | null {
  const at = followupTime(value); if (!at) return null;
  const fraction = /\.(\d+)(?=Z|[+-]\d\d:\d\d$)/.exec(at);
  const seconds = fraction ? at.slice(0, fraction.index) + at.slice(fraction.index + fraction[0].length) : at;
  return `${Date.parse(seconds)}:${(fraction?.[1] ?? "").replace(/0+$/, "")}`;
}
function semanticPayload(value: unknown, field = ""): unknown {
  if (Array.isArray(value)) return value.map(row => semanticPayload(row));
  if (followupRecord(value)) return Object.fromEntries(Object.entries(value).map(([key, row]) => [key, semanticPayload(row, key)]));
  return ["occurred_at", "effective_at", "observation_until"].includes(field) && value !== null ? timeIdentity(value) ?? value : value;
}
export type FollowupEvent = { occurred_at: string; original_timezone: string; source: FollowupSource };
export type CompletionDraft = { actionId: string; text: string; occurredAt: string; timezone: string; eventSource: FollowupSource | null; evidence: FollowupSource[] };
export const blankCompletion = (actionId: string): CompletionDraft => ({ actionId, text: "", occurredAt: "", timezone: "", eventSource: null, evidence: [] });
export function completionEvent(value: CompletionDraft, now = Date.now()): FollowupEvent {
  const at = followupTime(value.occurredAt);
  if (!at || Date.parse(at) > now || !validFollowupSource(value.eventSource)) throw new Error("实际完成须填已发生的独立时间与精确事件出处，不补为当前时钟。");
  if (!value.evidence.some(ref => followupSourceKey(ref) === followupSourceKey(value.eventSource!))) throw new Error("实际完成事件出处须同时包含在本项行动证据中。");
  return { occurred_at: at, original_timezone: followupZone(value.timezone), source: { ...value.eventSource } };
}

export const outputKinds = ["definition", "bom", "engineering_configuration", "manufacturing_configuration", "build", "actual_configuration", "build_lot", "sample", "verification_preparation", "verification_request", "verification_run"] as const;
export type FollowupOutputRef = { kind: typeof outputKinds[number]; id: string; revision: number; key: string | null };
export const validOutputRef = (value: unknown): value is FollowupOutputRef => followupRecord(value) && outputKinds.includes(value.kind as FollowupOutputRef["kind"]) && followupUuid(value.id) && followupRevision(value.revision) && (value.key === null || (["bom", "manufacturing_configuration"].includes(String(value.kind)) && typeof value.key === "string" && !!value.key && value.key.length <= 120));
export const followupOutputKey = (ref: FollowupOutputRef): string => JSON.stringify([ref.kind, ref.id, ref.revision, ref.key]);
export type FollowupCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: FollowupOperation; payload: Record<string, unknown>; source_read_set: FollowupRead[] };
export function followupCommand(product: { id: string; revision: number }, operation: FollowupOperation, payload: Record<string, unknown>, reads: FollowupRead[], id: string, key: string): FollowupCommand {
  if (!followupUuid(product.id) || !followupRevision(product.revision) || !followupOperations.includes(operation) || !followupUuid(id) || !followupUuid(key)) throw new Error("当前型号版本、操作或原请求标识不完整。");
  return { command_id: id, idempotency_key: key, product_id: product.id, expected_revision: product.revision, operation, payload, source_read_set: followupReads(reads) };
}
export type FollowupPreview = { command: FollowupCommand; expires_at: string | null; review: Record<string, unknown> & { before: unknown; after: unknown; effect: string }; write_tier?: "T2"; named_decision?: boolean };
export function validFollowupPreview(value: unknown, original: FollowupCommand, now = Date.now()): value is FollowupPreview {
  if (!followupRecord(value) || !followupRecord(value.command) || !followupRecord(value.command.payload) || !followupRecord(value.review) || !("before" in value.review) || !("after" in value.review) || typeof value.review.effect !== "string" || !value.review.effect.trim() || !proofClockCurrent(followupTier(original.operation), value.expires_at, now)) return false;
  const command = value.command, payload = command.payload as Record<string, unknown>, field = followupTier(original.operation) === "T2" ? "approval_token" : "confirmation_token", other = field === "approval_token" ? "confirmation_token" : "approval_token";
  if (field === "approval_token" && (value.write_tier !== "T2" || value.named_decision !== true)) return false;
  if (!["command_id", "idempotency_key", "product_id", "expected_revision", "operation"].every(key => command[key] === original[key as keyof FollowupCommand]) || typeof payload[field] !== "string" || payload[field].length < 20 || other in payload) return false;
  const clean = Object.fromEntries(Object.entries(payload).filter(([key]) => key !== field));
  if (!followupSame(semanticPayload(clean), semanticPayload(original.payload)) || !followupSame(command.source_read_set, original.source_read_set)) return false;
  if (original.operation !== "quality.capa.followup.link") {
    const target = String(original.payload.issue_id), before = value.review.before, after = value.review.after;
    if (!followupRecord(before) || !followupRecord(after) || !followupRecord(before[target]) || !followupRecord(after[target])) return false;
    return before[target].id === target && before[target].revision === original.payload.expected_issue_revision && after[target].id === target && after[target].revision === Number(original.payload.expected_issue_revision) + 1;
  }
  return true;
}
export type FollowupInputs = { operation: FollowupOperation; allowed: boolean; required_source_read_set: FollowupRead[]; authority?: unknown; review?: unknown; blockers?: unknown[] };
export function validFollowupInputs(value: unknown, command: FollowupCommand): value is FollowupInputs { if (!followupRecord(value) || value.operation !== command.operation || typeof value.allowed !== "boolean" || !Array.isArray(value.required_source_read_set)) return false; try { followupReads(value.required_source_read_set as FollowupRead[]); return true; } catch { return false; } }

export type FollowupWork = { rootText: string; rootSources: FollowupSource[]; completions: CompletionDraft[]; linkActionId: string; outputKeys: string[]; linkReason: string; linkSources: FollowupExactSource[] };
export const blankFollowupWork = (): FollowupWork => ({ rootText: "", rootSources: [], completions: [], linkActionId: "", outputKeys: [], linkReason: "", linkSources: [] });
export type FollowupPending = { stage: "inputs" | "preview" | "execute"; command: FollowupCommand; reconfirmation?: true };
export function followupExpiredRepreview(waiting: FollowupPending, failure: unknown, recovered: boolean, committed = false): FollowupPending | null {
  if (committed || !recovered || waiting.stage !== "execute" || !followupRecord(failure) || failure.status !== 409 || failure.code !== "FOLLOWUP_CONFIRMATION_EXPIRED" || !followupRecord(failure.recovery) || failure.recovery.state !== "not_saved_expired_proof" || !allowedKeys(failure.recovery, ["state", "command"])) return null;
  const token = followupTier(waiting.command.operation) === "T2" ? "approval_token" : "confirmation_token", other = token === "approval_token" ? "confirmation_token" : "approval_token";
  if (typeof waiting.command.payload[token] !== "string" || waiting.command.payload[token].length < 20 || other in waiting.command.payload) return null;
  const command = { ...waiting.command, payload: Object.fromEntries(Object.entries(waiting.command.payload).filter(([key]) => !["approval_token", "confirmation_token"].includes(key))) };
  // Recovery echoes the ORIGINAL fields, not DTO defaults or normalized clocks.
  // This comparison intentionally does not normalize times, sort arrays or replace reads.
  if (!followupSame(failure.recovery.command, command)) return null;
  return { stage: "preview", command, reconfirmation: true };
}
export type FollowupLocal = { selectedBuildId: string; selectedIssueId: string; selectedVersionId: string; work: FollowupWork; drafts: Record<string, FollowupWork>; pending: FollowupPending | null };
export const blankFollowupLocal = (): FollowupLocal => ({ selectedBuildId: "", selectedIssueId: "", selectedVersionId: "", work: blankFollowupWork(), drafts: {}, pending: null });
const allowedKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).every(key => keys.includes(key));
function validWork(value: unknown): value is FollowupWork {
  return followupRecord(value) && allowedKeys(value, ["rootText", "rootSources", "completions", "linkActionId", "outputKeys", "linkReason", "linkSources"]) && typeof value.rootText === "string" && value.rootText.length <= 2000 && Array.isArray(value.rootSources) && value.rootSources.every(validFollowupSource) && Array.isArray(value.completions) && value.completions.every(row => followupRecord(row) && allowedKeys(row, ["actionId", "text", "occurredAt", "timezone", "eventSource", "evidence"]) && followupUuid(row.actionId) && typeof row.text === "string" && row.text.length <= 2000 && typeof row.occurredAt === "string" && typeof row.timezone === "string" && (row.eventSource === null || validFollowupSource(row.eventSource)) && Array.isArray(row.evidence) && row.evidence.every(validFollowupSource)) && new Set(value.completions.map(row => row.actionId)).size === value.completions.length && typeof value.linkActionId === "string" && (value.linkActionId === "" || followupUuid(value.linkActionId)) && Array.isArray(value.outputKeys) && value.outputKeys.every(key => typeof key === "string") && typeof value.linkReason === "string" && value.linkReason.length <= 2000 && Array.isArray(value.linkSources) && value.linkSources.every(validFollowupExactSource);
}
function validCommand(value: unknown, productId: string, principalId: string, stage: FollowupPending["stage"]): value is FollowupCommand {
  if (!followupRecord(value) || !allowedKeys(value, ["command_id", "idempotency_key", "product_id", "expected_revision", "operation", "payload", "source_read_set"]) || !followupUuid(value.command_id) || !followupUuid(value.idempotency_key) || value.product_id !== productId || !followupRevision(value.expected_revision) || !followupOperations.includes(value.operation as FollowupOperation) || !followupRecord(value.payload) || !Array.isArray(value.source_read_set)) return false;
  try { followupReads(value.source_read_set as FollowupRead[]); } catch { return false; }
  const payload = value.payload, field = followupTier(value.operation as FollowupOperation) === "T2" ? "approval_token" : "confirmation_token";
  if (stage === "execute" && (typeof payload[field] !== "string" || payload[field].length < 20)) return false;
  if (stage !== "execute" && field in payload) return false;
  if (!followupUuid(payload.issue_id) || !followupRevision(payload.expected_issue_revision)) return false;
  const keys = ["issue_id", "expected_issue_revision", ...(stage === "execute" ? [field] : [])];
  if (value.operation === "quality.issue.root_cause.decide") return allowedKeys(payload, [...keys, "text", "sources"]) && typeof payload.text === "string" && !!payload.text.trim() && payload.text.length <= 2000 && Array.isArray(payload.sources) && payload.sources.length > 0 && payload.sources.every(validFollowupSource);
  if (value.operation === "quality.capa.actions.complete") return allowedKeys(payload, [...keys, "completions"]) && Array.isArray(payload.completions) && payload.completions.length > 0 && payload.completions.every(row => validCompletionPayload(row, principalId)) && new Set(payload.completions.map(row => row.id)).size === payload.completions.length;
  return allowedKeys(payload, [...keys, "capa_id", "action_id", "output_refs", "sources", "reason"]) && followupUuid(payload.capa_id) && followupUuid(payload.action_id) && Array.isArray(payload.output_refs) && payload.output_refs.length > 0 && payload.output_refs.every(validOutputRef) && new Set(payload.output_refs.map(followupOutputKey)).size === payload.output_refs.length && Array.isArray(payload.sources) && payload.sources.every(validFollowupExactSource) && typeof payload.reason === "string" && !!payload.reason.trim() && payload.reason.length <= 2000;
}
function validCompletionPayload(row: unknown, principalId: string): boolean {
  if (!followupRecord(row) || !allowedKeys(row, ["id", "text", "executor_id", "evidence", "at"]) || !followupUuid(row.id) || row.executor_id !== principalId || typeof row.text !== "string" || !row.text.trim() || row.text.length > 2000 || !Array.isArray(row.evidence) || !row.evidence.length || !row.evidence.every(validFollowupSource) || !followupRecord(row.at)) return false;
  const at = row.at;
  if (!allowedKeys(at, ["occurred_at", "original_timezone", "source", "effective_at"]) || !followupTime(at.occurred_at) || typeof at.original_timezone !== "string" || !validFollowupSource(at.source) || ("effective_at" in at && at.effective_at !== null)) return false;
  try { followupZone(at.original_timezone); } catch { return false; }
  return row.evidence.some(ref => followupSourceKey(ref) === followupSourceKey(at.source as FollowupSource));
}
export function restoreFollowupLocal(value: unknown, productId: string, principalId: string, projectId = ""): FollowupLocal | null {
  if (!followupRecord(value) || value.schema_version !== 1 || (value.project_id ?? "") !== projectId || value.product_id !== productId || value.principal_id !== principalId || typeof value.selectedIssueId !== "string" || (value.selectedIssueId && !followupUuid(value.selectedIssueId)) || typeof value.selectedVersionId !== "string" || (value.selectedVersionId && !followupUuid(value.selectedVersionId)) || !validWork(value.work) || !followupRecord(value.drafts) || !Object.values(value.drafts).every(validWork)) return null;
  if (value.selectedBuildId !== undefined && (typeof value.selectedBuildId !== "string" || (value.selectedBuildId && !followupUuid(value.selectedBuildId)))) return null;
  if (value.pending !== null && (!followupRecord(value.pending) || !allowedKeys(value.pending, ["stage", "command", "reconfirmation"]) || !["inputs", "preview", "execute"].includes(String(value.pending.stage)) || ("reconfirmation" in value.pending && (value.pending.reconfirmation !== true || value.pending.stage !== "preview")) || !validCommand(value.pending.command, productId, principalId, value.pending.stage as FollowupPending["stage"]))) return null;
  const pending = value.pending as FollowupPending | null, target = pending ? String(pending.command.payload.issue_id) : value.selectedIssueId;
  if (pending && value.selectedIssueId && value.selectedIssueId !== target) return null;
  const selectedBuildId = typeof value.selectedBuildId === "string" ? value.selectedBuildId : "", drafts = { ...value.drafts as Record<string, FollowupWork>, ...(target ? { [target]: value.work } : {}) };
  return { selectedBuildId, selectedIssueId: selectedBuildId || pending ? target : "", selectedVersionId: selectedBuildId || pending ? value.selectedVersionId : "", work: selectedBuildId || pending ? value.work : blankFollowupWork(), drafts, pending };
}
export function selectFollowupBuild(local: FollowupLocal, buildId: string): FollowupLocal {
  if (local.pending) throw new Error("原请求回执尚待核对，不能切换轮次另造操作。");
  if (buildId && !followupUuid(buildId)) throw new Error("请选择服务器实际返回的试制轮次。");
  if (buildId === local.selectedBuildId) return local;
  return { ...local, selectedBuildId: buildId, selectedIssueId: "", selectedVersionId: "", work: blankFollowupWork(), drafts: { ...local.drafts, ...(local.selectedIssueId ? { [local.selectedIssueId]: local.work } : {}) } };
}
export function selectFollowupIssue(local: FollowupLocal, issueId: string, versionId = ""): FollowupLocal {
  if (local.pending) throw new Error("原请求回执尚待核对，不能切换办理范围另造操作。");
  if ((issueId && !followupUuid(issueId)) || (versionId && !followupUuid(versionId))) throw new Error("请选择服务器实际返回的问题和版本。");
  const drafts = { ...local.drafts, ...(local.selectedIssueId ? { [local.selectedIssueId]: local.work } : {}) };
  return { ...local, selectedIssueId: issueId, selectedVersionId: versionId, work: issueId === local.selectedIssueId ? local.work : drafts[issueId] ?? blankFollowupWork(), drafts };
}
export function followupError(value: unknown, reading = false): { status?: number; message: string } {
  const status = followupRecord(value) && typeof value.status === "number" ? value.status : undefined;
  return { status, message: reading ? "当前整改、固定输出或复验事实读取失败，请刷新核对；本次读取未发起操作。" : status === 401 || status === 403 ? "当前范围、来源、职责或专业资格不可用，请重新核对。" : [400, 404, 409, 410, 422].includes(status ?? 0) ? "固定版本、来源、专业或事件依据已变化，请刷新查看明确缺项。" : "尚未取得确定回执，请保留同一命令、载荷与原标识恢复，不另造一次操作。" };
}
export function followupFailureRecovery(committed: boolean, status?: number): { clearPrivate: boolean; mode: "saved_read_failed" | "scope_rejected" | "original_request" } {
  const clearPrivate = status === 401 || status === 403;
  return { clearPrivate, mode: committed ? "saved_read_failed" : clearPrivate ? "scope_rejected" : "original_request" };
}
export const followupStates: Record<string, string> = { actioning: "措施办理中", awaiting_verification: "等待独立验证，尚未决定有效性", open: "待具名分诊", triaged: "已具名分诊", closed: "保留已关闭历史", current: "当前来源已核对", needs_recheck: "来源或专业依据需重新核对", not_evaluated_historical: "历史固定版本，当前资格未评估", indeterminate: "不确定，保留复验缺项", unknown: "未知，不能当作已证实", pass: "固定范围数值通过", fail: "确定性判定失败", invalid: "已知无效", draft: "研究草稿，未批准发布", planned: "计划已保存，实际事件未补造", observed: "已有实物观察事实", performed: "已有实际执行事实", real: "真实事实", synthetic: "本地合成演练", server_on_save: "仅在保存时由服务器记录", INTEGRATION_REQUIRED: "所需可信证据接口尚未接入" };

export type FollowupIssue = { id: string; issue_id: string; revision: number; purpose: string; is_current: boolean; source_status: string; issue: Record<string, unknown> & { title: string; status: string }; required_source_read_set: FollowupRead[]; authority?: unknown; policy?: unknown; [key: string]: unknown };
export type FollowupAction = { action_id: string; executor_id: string; label: string; completion: unknown; can_prepare_completion: boolean; can_complete: boolean; completion_verified?: null; reason_codes: string[] };
export type FollowupOutputOption = { label: string; ref: FollowupOutputRef; logical_id?: string; status: string };
export type FollowupIntegrationMissing = { code: string; detail: string };
export type FollowupData = {
  issue: FollowupIssue; current: { version_id: string; revision: number }; basis: Record<string, unknown> | null;
  operations: Record<string, { allowed: boolean; authority: unknown; reason_codes: string[] }>;
  actions: FollowupAction[]; output_options: FollowupOutputOption[]; links: Record<string, unknown>[]; candidates: Record<string, unknown>[];
  required_source_read_set: FollowupRead[]; source_options: { title: string; source: FollowupSource; quote: string }[]; integration: { effectiveness: false; close: false; missing: FollowupIntegrationMissing[] };
};
export type FollowupBuild = { id: string; revision: number; name: string; source_status?: string };
export type FollowupContext = { builds: FollowupBuild[]; issues: FollowupIssue[]; current_by_issue: Record<string, { issue_version_id: string; revision: number }>; sources: DefinitionSource[]; data: FollowupData | null; has_more: boolean };
export const emptyFollowupContext = (): FollowupContext => ({ builds: [], issues: [], current_by_issue: {}, sources: [], data: null, has_more: false });
function validIssue(value: unknown): value is FollowupIssue { return followupRecord(value) && followupUuid(value.id) && followupUuid(value.issue_id) && followupRevision(value.revision) && typeof value.purpose === "string" && typeof value.is_current === "boolean" && typeof value.source_status === "string" && followupRecord(value.issue) && typeof value.issue.title === "string" && typeof value.issue.status === "string" && Array.isArray(value.required_source_read_set); }
export function normalizeFollowup(value: unknown, issueId: string, revision?: number): FollowupData {
  if (!followupRecord(value) || !validIssue(value.issue) || value.issue.issue_id !== issueId || (revision !== undefined && value.issue.revision !== revision) || !followupRecord(value.current) || !followupUuid(value.current.version_id) || !followupRevision(value.current.revision) || !(value.basis === null || followupRecord(value.basis)) || !followupRecord(value.operations) || !Array.isArray(value.actions) || !Array.isArray(value.output_options) || !Array.isArray(value.links) || !value.links.every(followupRecord) || !Array.isArray(value.candidates) || !value.candidates.every(followupRecord) || !Array.isArray(value.required_source_read_set) || !Array.isArray(value.source_options) || !followupRecord(value.integration) || value.integration.effectiveness !== false || value.integration.close !== false) throw new Error("读取缺少固定问题、历史边界或禁用能力，尚未开放办理。");
  for (const row of Object.values(value.operations)) if (!followupRecord(row) || typeof row.allowed !== "boolean" || !Array.isArray(row.reason_codes) || !row.reason_codes.every(code => typeof code === "string")) throw new Error("尚未取得本操作明确能力与当前缺项。");
  if (!Array.isArray(value.integration.missing) || !value.integration.missing.every(row => followupRecord(row) && typeof row.code === "string" && !!row.code.trim() && typeof row.detail === "string" && !!row.detail.trim())) throw new Error("尚未取得输出证明与独立复验缺项的完整说明，请刷新核对。");
  if (value.actions.some(row => !followupRecord(row) || !followupUuid(row.action_id) || !followupUuid(row.executor_id) || typeof row.label !== "string" || !("completion" in row) || typeof row.can_prepare_completion !== "boolean" || typeof row.can_complete !== "boolean" || !Array.isArray(row.reason_codes) || !row.reason_codes.every(code => typeof code === "string")) || value.output_options.some(row => !followupRecord(row) || typeof row.label !== "string" || !validOutputRef(row.ref) || typeof row.status !== "string") || value.source_options.some(row => !followupRecord(row) || typeof row.title !== "string" || !validFollowupSource(row.source) || typeof row.quote !== "string")) throw new Error("措施、固定输出或精确来源格式不完整，不能推断可办理。");
  followupReads(value.required_source_read_set as FollowupRead[], value.issue.required_source_read_set);
  return value as unknown as FollowupData;
}
export function canFollowup(data: FollowupData | null, operation: string): boolean {
  return !!data && followupOperations.includes(operation as FollowupOperation) && data.issue.id === data.current.version_id && data.issue.revision === data.current.revision && data.issue.is_current === true && data.issue.source_status === "current" && !data.issue.issue.merged_into && data.issue.issue.needs_recheck !== true && data.operations[operation]?.allowed === true;
}
export function rootCausePayload(data: FollowupData, work: FollowupWork): Record<string, unknown> {
  if (!canFollowup(data, "quality.issue.root_cause.decide") || data.issue.issue.status !== "actioning" || data.issue.issue.root_cause != null) throw new Error("当前状态或具名根因能力不允许办理，已有结论不能覆盖。");
  followupSourceReads(work.rootSources);
  const sources = [...new Map(work.rootSources.map(ref => [followupSourceKey(ref), ref])).values()].sort((a, b) => a.kind.localeCompare(b.kind) || a.id.localeCompare(b.id) || a.revision - b.revision || a.position.localeCompare(b.position));
  return { issue_id: data.issue.issue_id, expected_issue_revision: data.issue.revision, text: followupText(work.rootText), sources };
}
export function completionPayload(data: FollowupData, work: FollowupWork, principalId: string, now = Date.now()): Record<string, unknown> {
  if (!canFollowup(data, "quality.capa.actions.complete") || !work.completions.length || new Set(work.completions.map(row => row.actionId)).size !== work.completions.length) throw new Error("请选择一个或多个当前本人可办理的未完成措施。");
  const completions = work.completions.map(row => {
    const action = data.actions.find(action => action.action_id === row.actionId);
    if (!action || action.executor_id !== principalId || action.can_prepare_completion !== true || action.completion !== null) throw new Error("仅原措施执行者本人可准备当前允许的实际完成核对，不能代填或覆盖。");
    followupSourceReads(row.evidence);
    return { id: row.actionId, text: followupText(row.text), executor_id: principalId, evidence: row.evidence.map(ref => ({ ...ref })), at: completionEvent(row, now) };
  }).sort((a, b) => a.id.localeCompare(b.id));
  return { issue_id: data.issue.issue_id, expected_issue_revision: data.issue.revision, completions };
}
export function completesWithoutRoot(data: FollowupData, work: FollowupWork): boolean { const outstanding = data.actions.filter(row => row.completion === null); return data.issue.issue.root_cause == null && outstanding.length > 0 && outstanding.every(row => work.completions.some(draft => draft.actionId === row.action_id)); }
export function linkPayload(data: FollowupData, work: FollowupWork): Record<string, unknown> {
  if (!canFollowup(data, "quality.capa.followup.link") || !data.basis || !followupUuid(data.basis.capa_id) || !data.actions.some(row => row.action_id === work.linkActionId) || !work.outputKeys.length || new Set(work.outputKeys).size !== work.outputKeys.length) throw new Error("请选择当前真实措施和服务器返回的固定输出，不能手造对象。");
  const output_refs = work.outputKeys.map(key => data.output_options.find(row => followupOutputKey(row.ref) === key)?.ref);
  if (output_refs.some(ref => !ref)) throw new Error("固定输出已不可读或未由服务器返回，请刷新核对。");
  return { issue_id: data.issue.issue_id, expected_issue_revision: data.issue.revision, capa_id: data.basis.capa_id, action_id: work.linkActionId, output_refs, sources: work.linkSources, reason: followupText(work.linkReason) };
}
export function followupPayloadReads(payload: Record<string, unknown>): FollowupRead[] {
  const refs: FollowupRead[] = [];
  function visit(value: unknown): void { if (Array.isArray(value)) value.forEach(visit); else if (followupRecord(value)) { if (validFollowupSource(value)) refs.push({ artifact_id: value.id, expected_revision: value.revision }); else if (validFollowupExactSource(value)) refs.push({ artifact_id: value.artifact_id, expected_revision: value.expected_revision }); else Object.values(value).forEach(visit); } }
  visit(payload); return followupReads(refs);
}
export function validFollowupReceipt(value: unknown, command: FollowupCommand): value is { id: string; operation: FollowupOperation; subject_id: string; subject_type: "quality_issue" | "capa_remediation_link" } { return followupRecord(value) && followupUuid(value.id) && value.operation === command.operation && followupUuid(value.subject_id) && value.subject_type === (command.operation === "quality.capa.followup.link" ? "capa_remediation_link" : "quality_issue"); }
export async function readFollowupContext(api: FollowupApi, productId: string, local: FollowupLocal, current: () => boolean, projectId = ""): Promise<FollowupContext | null> {
  const outcomes = await Promise.allSettled([api<unknown>(projectBuildsPath(productId, projectId)), api<unknown>(`v1/products/${productId}/workspace`)]);
  if (!current()) return null;
  const failures = outcomes.filter((row): row is PromiseRejectedResult => row.status === "rejected");
  if (failures.length) { const real = failures.find(row => !followupCancelled(row.reason)); if (real) throw real.reason; return null; }
  const builds = (outcomes[0] as PromiseFulfilledResult<unknown>).value, workspace = (outcomes[1] as PromiseFulfilledResult<unknown>).value;
  if (!followupRecord(builds) || !Array.isArray(builds.items) || !builds.items.every(row => followupRecord(row) && followupUuid(row.id) && followupRevision(row.revision) && typeof row.name === "string") || !followupRecord(workspace) || !Array.isArray(workspace.sources)) throw new Error("轮次索引或来源读取不完整，不能开放后续。");
  const result: FollowupContext = { ...emptyFollowupContext(), builds: builds.items as FollowupBuild[], sources: workspace.sources as DefinitionSource[] };
  return readBuildFollowupIndex(api, productId, local, result, current);
}
export async function readBuildFollowupIndex(api: FollowupApi, productId: string, local: FollowupLocal, context: FollowupContext, current: () => boolean): Promise<FollowupContext | null> {
  const base = { ...context, issues: [], current_by_issue: {}, data: null, has_more: false };
  if (!current()) return null;
  if (!local.selectedBuildId || !context.builds.some(row => row.id === local.selectedBuildId)) return base;
  try {
    const quality = await api<unknown>(`v1/products/${productId}/quality-execution?build_id=${encodeURIComponent(local.selectedBuildId)}`);
    if (!current()) return null;
    if (!followupRecord(quality) || !Array.isArray(quality.issues) || !quality.issues.every(validIssue) || !followupRecord(quality.current_by_issue)) throw new Error("所选轮次问题索引不完整，不能开放后续。");
    const result: FollowupContext = { ...base, issues: quality.issues, current_by_issue: quality.current_by_issue as FollowupContext["current_by_issue"], has_more: quality.has_more === true };
    if (!local.selectedIssueId || !result.issues.some(row => row.issue_id === local.selectedIssueId)) return result;
    return readSelectedFollowup(api, productId, local, result, current);
  } catch (failure) { if (!current() || followupCancelled(failure)) return null; throw failure; }
}
export async function readSelectedFollowup(api: FollowupApi, productId: string, local: FollowupLocal, context: FollowupContext, current: () => boolean): Promise<FollowupContext | null> {
  if (!current()) return null;
  if (!local.selectedIssueId || !context.issues.some(row => row.issue_id === local.selectedIssueId)) return { ...context, data: null };
  const chosen = local.selectedVersionId ? context.issues.find(row => row.issue_id === local.selectedIssueId && row.id === local.selectedVersionId) : undefined;
  if (local.selectedVersionId && !chosen) throw new Error("所选固定问题版本未在当前可读索引中，请重新选择。");
  try {
    const value = await api<unknown>(`v1/products/${productId}/quality-followup?issue_id=${encodeURIComponent(local.selectedIssueId)}${chosen ? `&revision=${chosen.revision}` : ""}`);
    if (!current()) return null;
    const data = normalizeFollowup(value, local.selectedIssueId, chosen?.revision);
    return { ...context, data, issues: [...context.issues.filter(row => row.id !== data.issue.id), data.issue], current_by_issue: { ...context.current_by_issue, [data.issue.issue_id]: { issue_version_id: data.current.version_id, revision: data.current.revision } } };
  } catch (failure) { if (!current() || followupCancelled(failure)) return null; throw failure; }
}
