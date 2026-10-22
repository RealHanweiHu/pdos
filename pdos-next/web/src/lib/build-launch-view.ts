import type { DefinitionReference, DefinitionSource } from "@/lib/product-view";
import type { SourceRead } from "@/lib/project-plan-view";
import type { ProfessionalAuthority } from "@/lib/verification-professional";
import { exactHandoffRef, handoffEventSource, handoffReads, handoffRefKey, handoffStable, handoffTime, handoffZone, validHandoffRef } from "./build-handoff-view";

export type LaunchApi = <T>(path: string, body?: unknown) => Promise<T>;
export const launchOperations = ["test.run.plan", "verification.schedule.promise", "test.run.start"] as const;
export type LaunchOperation = typeof launchOperations[number];
export const launchNames: Record<LaunchOperation, string> = { "test.run.plan": "固定完整测试计划", "verification.schedule.promise": "品质具名承诺", "test.run.start": "具名实际开测" };
export const launchCapabilityKeys: Record<LaunchOperation, string> = { "test.run.plan": "run_plan", "verification.schedule.promise": "schedule_promise", "test.run.start": "run_start" };
export const launchRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
export const launchCapability = (value: unknown, key: string): boolean => launchRecord(value) && value[key] === true;
export function launchAuthority(value: unknown, operation: LaunchOperation): unknown { if (!launchRecord(value)) return undefined; const scoped = value[launchCapabilityKeys[operation]]; return launchRecord(scoped) && scoped.operation === operation ? scoped : value.operation === operation ? value : undefined; }
export const launchSyntheticAuthority = (value: unknown): boolean => launchRecord(value) && (value.synthetic === true || Object.values(value).some(row => launchRecord(row) && row.synthetic === true));
export const launchStable = handoffStable;
export const launchReads = handoffReads;
export const launchRefKey = handoffRefKey;
export const launchReference = (source: DefinitionSource, line: number, quote: string): DefinitionReference => exactHandoffRef(source, line, quote);
export const launchRefReads = (refs: DefinitionReference[]): SourceRead[] => launchReads(refs.map(ref => ({ artifact_id: ref.artifact_id, expected_revision: ref.expected_revision })));
export const launchRefs = (value: unknown): value is DefinitionReference[] => Array.isArray(value) && value.every(validHandoffRef);
export const launchRevision = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
export const launchHash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
export function launchReason(value: string): string { const reason = value.trim(); if (!reason || reason.length > 2000) throw new Error("请填写本次具名核对原因，最多 2000 字。"); return reason; }

export type LaunchEventDraft = { occurredAt: string; timezone: string; reference: DefinitionReference | null };
export const blankLaunchEvent = (): LaunchEventDraft => ({ occurredAt: "", timezone: "", reference: null });
export type LaunchEvent = { occurred_at: string; original_timezone: string; source: { id: string; revision: number; kind: "artifact"; position: string }; effective_at: null };
export async function launchEvent(value: LaunchEventDraft, future: boolean, now = Date.now()): Promise<LaunchEvent> {
  const occurred = handoffTime(value.occurredAt.trim());
  if (!occurred || !value.reference || !validHandoffRef(value.reference)) throw new Error("请明确填写带时区的独立事件时间，并采用精确原文依据。");
  if (!future && Date.parse(occurred) > now) throw new Error("实际开测须已经发生，不能从计划窗口或当前时钟补造。");
  return { occurred_at: occurred, original_timezone: handoffZone(value.timezone), source: await handoffEventSource(value.reference), effective_at: null };
}

export type LaunchPair = { sample_id: string; item_id: string };
export const launchPairKey = (pair: LaunchPair): string => JSON.stringify([pair.sample_id, pair.item_id]);
export function launchExactCoverage(pairs: unknown): LaunchPair[] {
  if (!Array.isArray(pairs) || !pairs.length || pairs.some(pair => !launchRecord(pair) || typeof pair.sample_id !== "string" || !pair.sample_id || typeof pair.item_id !== "string" || !pair.item_id)) throw new Error("尚未取得明确非空的逐件测试范围，不能创建计划。");
  const result = pairs as LaunchPair[];
  if (new Set(result.map(launchPairKey)).size !== result.length) throw new Error("固定测试范围存在重复，请刷新核对。");
  return result.map(pair => ({ sample_id: pair.sample_id, item_id: pair.item_id })).sort((a, b) => launchPairKey(a).localeCompare(launchPairKey(b)));
}

export type LaunchRow = Record<string, unknown> & { id: string; revision: number; source_status?: string; is_current?: boolean; capabilities?: Record<string, boolean>; authority?: Record<string, ProfessionalAuthority>; required_source_read_set: SourceRead[] };
export type LaunchPlan = { window: { start: string; finish: string; original_timezone: string }; executor_id: string; equipment: DefinitionReference; calibration: DefinitionReference; environment: string; conditions: string; resource_fact_id: string; expected_resource_fact_revision: number };
export type LaunchRequest = LaunchRow & { request_id: string; title: string; purpose: string; build: { id: string; revision: number }; accepted_coverage: LaunchPair[]; items: Record<string, unknown>[]; documents: Record<string, unknown>[]; request_snapshot: Record<string, unknown> };
export type LaunchPromise = { id: string; at: LaunchEvent; recorded_at: string; sources: DefinitionReference[]; reason: string };
export type LaunchRun = LaunchRow & { run_id: string; request_id: string; build: { id: string; revision: number }; status: string; execution_plan: LaunchPlan; plan_sha256: string; run_snapshot: Record<string, unknown>; promise: LaunchPromise | null };
export type LaunchResourceFact = LaunchRow & { binding: Record<string, unknown>; current?: boolean; nature?: string; state?: string };
export type LaunchList = { requests: LaunchRequest[]; runs: LaunchRun[]; resource_facts: LaunchResourceFact[]; current_by_request: Record<string, { request_version_id: string; revision: number }>; current_by_run: Record<string, { run_version_id: string; revision: number }>; runs_by_request: Record<string, string[]>; sample_usage: Record<string, unknown>[]; reference_samples: Record<string, unknown>[]; blockers: unknown[]; has_more: boolean; unavailable_count: number };
export const emptyLaunch: LaunchList = { requests: [], runs: [], resource_facts: [], current_by_request: {}, current_by_run: {}, runs_by_request: {}, sample_usage: [], reference_samples: [], blockers: [], has_more: false, unavailable_count: 0 };
export function normalizeLaunch(value: unknown, buildId: string): LaunchList {
  if (!buildId || !launchRecord(value) || !Array.isArray(value.requests) || !Array.isArray(value.runs) || !Array.isArray(value.resource_facts) || !launchRecord(value.current_by_request) || !launchRecord(value.current_by_run) || !launchRecord(value.runs_by_request)) throw new Error("尚未取得已选轮次的完整请求、运行及固定资源事实，请刷新核对。");
  if (value.requests.some(row => !launchRecord(row) || typeof row.id !== "string" || typeof row.request_id !== "string" || !launchRevision(row.revision) || !launchRecord(row.build) || row.build.id !== buildId || !Array.isArray(row.accepted_coverage) || !Array.isArray(row.items) || !Array.isArray(row.documents) || !launchRecord(row.request_snapshot) || !Array.isArray(row.required_source_read_set))
    || value.runs.some(row => !launchRecord(row) || typeof row.id !== "string" || typeof row.run_id !== "string" || typeof row.request_id !== "string" || !launchRevision(row.revision) || !launchRecord(row.build) || row.build.id !== buildId || !launchRecord(row.run_snapshot) || !validLaunchPlan(row.execution_plan) || !launchHash(row.plan_sha256) || !Array.isArray(row.required_source_read_set) || !validLaunchPromise(row.promise))
    || value.resource_facts.some(row => !launchRecord(row) || typeof row.id !== "string" || !launchRevision(row.revision) || !launchRecord(row.binding) || row.binding.build_id !== buildId || !Array.isArray(row.required_source_read_set))) throw new Error("固定请求、运行或资源事实缺少版本或不属于已选轮次，未开放操作。");
  const runsByRequest = value.runs_by_request as Record<string, unknown>;
  if (Object.entries(runsByRequest).some(([requestId, ids]) => !Array.isArray(ids) || ids.some(id => typeof id !== "string" || !id) || new Set(ids).size !== ids.length || ids.some(id => !(value.runs as LaunchRun[]).some(row => row.run_id === id && row.request_id === requestId)))
    || (value.runs as LaunchRun[]).some(row => !Array.isArray(runsByRequest[row.request_id]) || !(runsByRequest[row.request_id] as string[]).includes(row.run_id))) throw new Error("请求与各固定测试运行的对应尚不完整，请刷新核对；不会默认采用另一运行。");
  return { ...(value as unknown as LaunchList), sample_usage: Array.isArray(value.sample_usage) ? value.sample_usage : [], reference_samples: Array.isArray(value.reference_samples) ? value.reference_samples : [], blockers: Array.isArray(value.blockers) ? value.blockers : [], has_more: value.has_more === true, unavailable_count: typeof value.unavailable_count === "number" ? value.unavailable_count : 0 };
}
export async function readLaunchBuild(api: LaunchApi, productId: string, buildId: string, readableBuilds: { id: string }[], isCurrent: () => boolean): Promise<LaunchList | null> {
  if (!isCurrent()) return null;
  if (!buildId || !readableBuilds.some(row => row.id === buildId)) return emptyLaunch;
  const result = await api<unknown>(`v1/products/${productId}/verification-launch?build_id=${encodeURIComponent(buildId)}`);
  return isCurrent() ? normalizeLaunch(result, buildId) : null;
}
export type LaunchCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: LaunchOperation; payload: Record<string, unknown>; source_read_set: SourceRead[] };
export type PendingLaunch = { stage: "inputs" | "preview" | "execute"; command: LaunchCommand };
export type LaunchPreview = { command: LaunchCommand; expires_at: string; review: Record<string, unknown> & { before: unknown; after: Record<string, unknown>; effect: string } };
export function makeLaunchCommand(product: { id: string; revision: number }, operation: LaunchOperation, payload: Record<string, unknown>, reads: SourceRead[], commandId: string, key: string): LaunchCommand {
  if (!launchOperations.includes(operation) || !product.id || !launchRevision(product.revision) || !commandId || !key) throw new Error("操作、型号范围或原请求标识尚不完整。");
  return { command_id: commandId, idempotency_key: key, product_id: product.id, expected_revision: product.revision, operation, payload, source_read_set: launchReads(reads) };
}
function normalizedPayload(value: unknown, field = ""): unknown {
  if (Array.isArray(value)) return value.map(row => normalizedPayload(row));
  if (!launchRecord(value)) return ["occurred_at", "effective_at", "start", "finish"].includes(field) && value !== null ? handoffTime(value) : value;
  return Object.fromEntries(Object.entries(value).filter(([key]) => key !== "confirmation_token").map(([key, row]) => [key, normalizedPayload(row, key)]));
}
export const launchSame = (left: unknown, right: unknown): boolean => JSON.stringify(launchStable(left)) === JSON.stringify(launchStable(right));
export function validLaunchPreview(value: unknown, command: LaunchCommand, now = Date.now()): value is LaunchPreview {
  if (!launchRecord(value) || !launchRecord(value.command) || !launchRecord(value.command.payload) || !launchRecord(value.review) || !launchRecord(value.review.after) || typeof value.review.effect !== "string" || !value.review.effect || typeof value.expires_at !== "string" || !handoffTime(value.expires_at) || Date.parse(value.expires_at) <= now) return false;
  const returned = value.command, payload = returned.payload as Record<string, unknown>;
  if (!["command_id", "idempotency_key", "product_id", "expected_revision", "operation"].every(key => returned[key] === command[key as keyof LaunchCommand])
    || typeof payload.confirmation_token !== "string" || payload.confirmation_token.length < 20 || !launchSame(normalizedPayload(payload), normalizedPayload(command.payload)) || !launchSame(returned.source_read_set, command.source_read_set)) return false;
  const before = value.review.before, after = value.review.after;
  if (!launchRecord(before) || !launchRecord(before.request) || !launchRecord(after.request) || !launchRecord(after.run) || before.request.request_id !== command.payload.request_id || before.request.revision !== command.payload.expected_request_revision || after.request.request_id !== command.payload.request_id || after.run.run_id !== command.payload.run_id) return false;
  if (command.operation === "test.run.plan") return before.run === null && after.run.revision === 1 && after.run.status === "planned" && after.occupancy_effect === "none" && launchRecord(after.run.run_snapshot) && launchSame(after.run.run_snapshot.coverage, command.payload.coverage) && launchSame(normalizedPayload(after.run.execution_plan), normalizedPayload(command.payload.execution_plan));
  if (!launchRecord(before.run) || before.run.run_id !== command.payload.run_id || before.run.revision !== command.payload.expected_run_revision || before.run.plan_sha256 !== command.payload.expected_plan_sha256 || after.run.plan_sha256 !== command.payload.expected_plan_sha256) return false;
  return command.operation === "verification.schedule.promise"
    ? launchRecord(after.proposed_promise) && after.proposed_promise.run_id === command.payload.run_id && launchSame(normalizedPayload(after.proposed_promise.at), normalizedPayload(command.payload.at)) && after.proposed_promise.reason === command.payload.reason && after.run.revision === command.payload.expected_run_revision && after.request.revision === Number(command.payload.expected_request_revision) + 1 && after.request.status === (before.request.status === "executing" ? "executing" : "scheduled") && after.occupancy_effect === "none"
    : after.run.revision === Number(command.payload.expected_run_revision) + 1 && after.run.status === "running" && after.request.revision === Number(command.payload.expected_request_revision) + 1 && after.request.status === "executing" && after.occupancy_effect === "stage_formal_and_sample_use_in_caller_uow";
}
export function launchError(failure: unknown, readOnly = false): { status?: number; message: string } {
  const value = launchRecord(failure) ? failure : {}, status = typeof value.status === "number" ? value.status : undefined;
  return { status, message: readOnly ? "当前测试范围、资源或专业事实读取失败，请刷新核对；尚未发起新的提交。" : status === 401 || status === 403 ? "此操作的范围、具名职责或专业资格当前不可用，请刷新核对。" : [400, 404, 409, 410, 422].includes(status ?? 0) ? "当前请求、计划、来源、资格或资源窗口已不符合办理条件，请刷新后核对缺项。" : "尚未取得确定回执，请保留原命令、原标识与载荷核对，不另造一次操作。" };
}
export type LaunchWork = { resourceFactId: string; planReason: string; references: DefinitionReference[] };
export const blankLaunchWork = (): LaunchWork => ({ resourceFactId: "", planReason: "", references: [] });
export type LaunchRunWork = { promiseReason: string; startReason: string; promiseEvent: LaunchEventDraft; startEvent: LaunchEventDraft; references: DefinitionReference[] };
export const blankLaunchRunWork = (): LaunchRunWork => ({ promiseReason: "", startReason: "", promiseEvent: blankLaunchEvent(), startEvent: blankLaunchEvent(), references: [] });
export function launchRunDraftKey(buildId: string, requestId: string, runId: string): string { return JSON.stringify([buildId, requestId, runId]); }
function validRunDraftKey(value: string): boolean { try { const ids = JSON.parse(value); return Array.isArray(ids) && ids.length === 3 && ids.every(id => typeof id === "string" && !!id) && JSON.stringify(ids) === value; } catch { return false; } }
export type LocalLaunch = { selectedBuildId: string; selectedRequestId: string; selectedRequestVersionId: string; selectedRunId: string; selectedRunVersionId: string; drafts: Record<string, LaunchWork>; runDrafts: Record<string, LaunchRunWork>; pending: PendingLaunch | null };
export const blankLocalLaunch = (): LocalLaunch => ({ selectedBuildId: "", selectedRequestId: "", selectedRequestVersionId: "", selectedRunId: "", selectedRunVersionId: "", drafts: {}, runDrafts: {}, pending: null });
function validEvent(value: unknown): boolean { return launchRecord(value) && typeof value.occurredAt === "string" && typeof value.timezone === "string" && (value.reference === null || validHandoffRef(value.reference)); }
function validEventPayload(value: unknown): boolean { return launchRecord(value) && !!handoffTime(value.occurred_at) && typeof value.original_timezone === "string" && launchRecord(value.source) && typeof value.source.id === "string" && launchRevision(value.source.revision) && value.source.kind === "artifact" && typeof value.source.position === "string" && /^line:[1-9]\d*;quote_sha256:[0-9a-f]{64}$/.test(value.source.position) && value.effective_at === null; }
function validLaunchPromise(value: unknown): boolean { return value === null || (launchRecord(value) && typeof value.id === "string" && !!value.id && validEventPayload(value.at) && typeof value.recorded_at === "string" && !!handoffTime(value.recorded_at) && launchRefs(value.sources) && typeof value.reason === "string" && !!value.reason.trim()); }
export function validLaunchPlan(value: unknown): value is LaunchPlan { return launchRecord(value) && launchRecord(value.window) && !!handoffTime(value.window.start) && !!handoffTime(value.window.finish) && Date.parse(String(value.window.finish)) > Date.parse(String(value.window.start)) && typeof value.window.original_timezone === "string" && typeof value.executor_id === "string" && !!value.executor_id && validHandoffRef(value.equipment) && validHandoffRef(value.calibration) && typeof value.environment === "string" && !!value.environment && typeof value.conditions === "string" && !!value.conditions && typeof value.resource_fact_id === "string" && launchRevision(value.expected_resource_fact_revision); }
export function launchFactPlan(fact: LaunchResourceFact): LaunchPlan {
  const binding = fact.binding;
  const result = { window: binding.window, executor_id: binding.executor_id, equipment: binding.equipment, calibration: binding.calibration, environment: binding.environment, conditions: binding.conditions, resource_fact_id: fact.id, expected_resource_fact_revision: fact.revision };
  if (!validLaunchPlan(result)) throw new Error("所选资源事实尚未提供完整窗口、执行者、设备校准及实际条件，不能补造计划。");
  return { ...result, window: { ...result.window }, equipment: { ...result.equipment }, calibration: { ...result.calibration } };
}
export function launchFactCoverage(fact: LaunchResourceFact): LaunchPair[] {
  if (!Array.isArray(fact.binding.pairs)) throw new Error("资源事实尚无明确逐件测试范围。");
  return launchExactCoverage(fact.binding.pairs.map(row => launchRecord(row) && launchRecord(row.sample) ? { sample_id: row.sample.id, item_id: row.item_id } : null));
}
export function launchFactMatches(request: LaunchRequest, fact: LaunchResourceFact): boolean {
  if (fact.source_status !== "current" || fact.current !== true || fact.state !== "active" || fact.binding.request_id !== request.request_id || fact.binding.build_id !== request.build.id || fact.binding.accepted_request_id !== request.id || fact.binding.accepted_request_revision !== request.revision) return false;
  try { const accepted = new Set(launchExactCoverage(request.accepted_coverage).map(launchPairKey)); return launchFactCoverage(fact).every(pair => accepted.has(launchPairKey(pair))); } catch { return false; }
}
export function launchPlanPayload(request: LaunchRequest, fact: LaunchResourceFact, reason: string, sources: DefinitionReference[]): Record<string, unknown> {
  if (!request.is_current || request.source_status !== "current" || !launchFactMatches(request, fact) || typeof fact.binding.run_id !== "string" || !fact.binding.run_id) throw new Error("当前正式请求、资源事实固定范围或版本绑定已变化，请刷新重核。");
  if (!launchRefs(sources)) throw new Error("本次精确来源范围不完整。");
  return { request_id: request.request_id, expected_request_revision: request.revision, run_id: fact.binding.run_id, coverage: launchFactCoverage(fact), execution_plan: launchFactPlan(fact), sources: sources.map(ref => ({ ...ref })), reason: launchReason(reason) };
}
export function launchRunPayload(request: LaunchRequest, run: LaunchRun, at: LaunchEvent, reason: string, sources: DefinitionReference[]): Record<string, unknown> {
  if (!request.is_current || request.source_status !== "current" || !run.is_current || run.source_status !== "current" || run.request_id !== request.request_id || run.build.id !== request.build.id || !launchHash(run.plan_sha256) || !launchRevision(run.revision) || !launchRefs(sources)) throw new Error("当前正式请求或固定运行计划需重核，历史版本不能继续办理。");
  return { request_id: request.request_id, expected_request_revision: request.revision, run_id: run.run_id, expected_run_revision: run.revision, expected_plan_sha256: run.plan_sha256, at, sources: sources.map(ref => ({ ...ref })), reason: launchReason(reason) };
}
export function validLaunchInputs(value: unknown, command: LaunchCommand): value is Record<string, unknown> & { allowed: boolean; required_source_read_set: SourceRead[] } {
  if (!launchRecord(value) || value.operation !== command.operation || value.request_id !== command.payload.request_id || value.run_id !== command.payload.run_id || typeof value.allowed !== "boolean" || !Array.isArray(value.required_source_read_set)) return false;
  try { launchReads(value.required_source_read_set as SourceRead[]); return true; } catch { return false; }
}
export function restoreLaunch(value: unknown, productId: string, principalId: string): LocalLaunch | null {
  if (!launchRecord(value) || !(value.schema_version === 1 || value.schema_version === 2) || value.product_id !== productId || value.principal_id !== principalId || !["selectedBuildId", "selectedRequestId", "selectedRequestVersionId", "selectedRunId", "selectedRunVersionId"].every(key => typeof value[key] === "string") || !launchRecord(value.drafts)) return null;
  if (Object.values(value.drafts).some(draft => !launchRecord(draft) || !["resourceFactId", "planReason"].every(key => typeof draft[key] === "string") || !launchRefs(draft.references))) return null;
  const drafts = Object.fromEntries(Object.entries(value.drafts).map(([id, draft]) => { const row = draft as Record<string, unknown>; return [id, { resourceFactId: row.resourceFactId as string, planReason: row.planReason as string, references: row.references as DefinitionReference[] }]; }));
  const validRunWork = (draft: unknown): draft is LaunchRunWork => launchRecord(draft) && ["promiseReason", "startReason"].every(key => typeof draft[key] === "string") && validEvent(draft.promiseEvent) && validEvent(draft.startEvent) && launchRefs(draft.references);
  let runDrafts: Record<string, LaunchRunWork> = {};
  if (value.schema_version === 2) {
    if (!launchRecord(value.runDrafts) || Object.entries(value.runDrafts).some(([key, draft]) => !validRunDraftKey(key) || !validRunWork(draft))) return null;
    runDrafts = value.runDrafts as Record<string, LaunchRunWork>;
  } else if (value.selectedBuildId && value.selectedRequestId && value.selectedRunId) {
    const old = value.drafts[value.selectedRequestId as string];
    // The old screen sometimes inferred its Run; only an explicitly persisted identity is safe to migrate.
    if (validRunWork(old)) runDrafts[launchRunDraftKey(String(value.selectedBuildId), String(value.selectedRequestId), String(value.selectedRunId))] = { promiseReason: old.promiseReason, startReason: old.startReason, promiseEvent: old.promiseEvent, startEvent: old.startEvent, references: old.references };
  }
  if (value.pending !== null) {
    const pending = value.pending;
    if (!launchRecord(pending) || !["inputs", "preview", "execute"].includes(String(pending.stage)) || !launchRecord(pending.command)) return null;
    const command = pending.command;
    if (command.product_id !== productId || !launchOperations.includes(command.operation as LaunchOperation) || typeof command.command_id !== "string" || !command.command_id || typeof command.idempotency_key !== "string" || !command.idempotency_key || !launchRevision(command.expected_revision) || !Array.isArray(command.source_read_set) || command.source_read_set.some(row => !launchRecord(row) || typeof row.artifact_id !== "string" || !launchRevision(row.expected_revision)) || !launchRecord(command.payload)) return null;
    const payload = command.payload;
    if (typeof payload.request_id !== "string" || !launchRevision(payload.expected_request_revision) || typeof payload.run_id !== "string" || typeof payload.reason !== "string" || !payload.reason.trim() || !launchRefs(payload.sources)) return null;
    if (command.operation === "test.run.plan") { try { launchExactCoverage(payload.coverage); } catch { return null; } if (!validLaunchPlan(payload.execution_plan)) return null; }
    else if (!launchRevision(payload.expected_run_revision) || !launchHash(payload.expected_plan_sha256) || !validEventPayload(payload.at)) return null;
    if (pending.stage === "execute" && (typeof payload.confirmation_token !== "string" || payload.confirmation_token.length < 20)) return null;
  }
  return { selectedBuildId: value.selectedBuildId as string, selectedRequestId: value.selectedRequestId as string, selectedRequestVersionId: value.selectedRequestVersionId as string, selectedRunId: value.selectedRunId as string, selectedRunVersionId: value.selectedRunVersionId as string, drafts, runDrafts, pending: value.pending as PendingLaunch | null };
}
export const launchReceiptTypes: Record<LaunchOperation, string> = { "test.run.plan": "test_run", "verification.schedule.promise": "verification_request", "test.run.start": "test_run" };
export function validLaunchReceipt(value: unknown, command: LaunchCommand): value is { id: string; subject_id: string; subject_type: string } { return launchRecord(value) && typeof value.id === "string" && !!value.id && typeof value.subject_id === "string" && !!value.subject_id && value.operation === command.operation && value.subject_type === launchReceiptTypes[command.operation]; }
