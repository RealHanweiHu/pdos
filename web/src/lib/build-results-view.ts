import { proofClockCurrent } from "./proof-clock";
import { projectBuildsPath } from "./project-build-scope";
import { sourceLines, type DefinitionReference, type DefinitionSource } from "./product-view";
import type { SourceRead } from "./project-plan-view";
import type { Build } from "./build-preparation-view";
import { handoffEventSource, handoffReads, handoffRefKey, handoffStable, handoffTime, handoffZone, validHandoffRef } from "./build-handoff-view";

export type ResultsApi = <T>(path: string, body?: unknown) => Promise<T>;
export const resultsOperations = ["test.results.import", "test.result.compute", "test.run.review", "test.disposition.decide"] as const;
export type ResultsOperation = typeof resultsOperations[number];
export const resultsNames: Record<ResultsOperation, string> = { "test.results.import": "原报告结果返回", "test.result.compute": "固定结果确定性判定", "test.run.review": "品质具名专业复核", "test.disposition.decide": "具名结果处置" };
export const resultsTier = (operation: ResultsOperation): "T0" | "T1" | "T2" => operation === "test.results.import" ? "T1" : operation === "test.result.compute" ? "T0" : "T2";
export const resultsRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
export const resultsRevision = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
export const resultsHash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
export const resultsStable = handoffStable;
export const resultsSame = (left: unknown, right: unknown): boolean => JSON.stringify(resultsStable(left)) === JSON.stringify(resultsStable(right));
export const resultsReads = handoffReads;
export const resultsRefKey = handoffRefKey;
export const resultsLines = sourceLines;
export function resultsReference(source: DefinitionSource, line: number, quote: string): DefinitionReference {
  if (source.status !== "active" || !Number.isSafeInteger(line) || line < 1 || !quote.trim() || quote.length > 4000 || !sourceLines(source.content)[line - 1]?.includes(quote)) throw new Error("请选择当前有效原文行，并保留可精确核对的摘录。");
  return { artifact_id: source.id, expected_revision: source.revision, line, quote };
}
export const resultsRefs = (value: unknown): value is DefinitionReference[] => Array.isArray(value) && value.every(validHandoffRef);
export const resultsRefReads = (refs: DefinitionReference[]): SourceRead[] => resultsReads(refs.map(ref => ({ artifact_id: ref.artifact_id, expected_revision: ref.expected_revision })));
export const resultsCapability = (value: unknown, key: string): boolean => resultsRecord(value) && value[key] === true;
export const resultsCapabilityKeys: Record<ResultsOperation, string> = { "test.results.import": "results_import", "test.result.compute": "result_compute", "test.run.review": "run_review", "test.disposition.decide": "disposition_decide" };
export function resultsAuthority(value: unknown, operation: ResultsOperation): unknown { if (!resultsRecord(value)) return undefined; const scoped = value[resultsCapabilityKeys[operation]]; return resultsRecord(scoped) && scoped.operation === operation ? scoped : value.operation === operation ? value : undefined; }
export const resultsSynthetic = (value: unknown): boolean => resultsRecord(value) && (value.synthetic === true || value.nature === "synthetic" || Object.values(value).some(row => resultsRecord(row) && (row.synthetic === true || row.nature === "synthetic")));
export function resultsReason(value: string): string { const text = value.trim(); if (!text || text.length > 2000) throw new Error("请填写本次具名办理原因，最多 2000 字。"); return text; }
export function resultsRaw(value: unknown): string { return value === null || value === undefined ? "原报告未提供" : typeof value === "string" ? value : "原值类型待核对"; }
export function resultsVerdict(value: unknown): string { return ({ pending: "尚未形成判定", pass: "固定范围数值判定通过", fail: "固定范围数值判定未通过", indeterminate: "原值、元数据或判据缺项，不能确定", invalid: "已明确记录为无效" } as Record<string, string>)[String(value)] ?? "判定尚待核对"; }

export type ResultsEventDraft = { occurredAt: string; timezone: string; reference: DefinitionReference | null };
export const blankResultsEvent = (): ResultsEventDraft => ({ occurredAt: "", timezone: "", reference: null });
export type ResultsEvent = { occurred_at: string; original_timezone: string; source: { id: string; revision: number; kind: "artifact"; position: string }; effective_at: null };
export async function resultsEvent(draft: ResultsEventDraft, now = Date.now()): Promise<ResultsEvent> {
  const occurred = handoffTime(draft.occurredAt);
  if (!occurred || !validHandoffRef(draft.reference)) throw new Error("请填写已经发生的独立时间、原 IANA 时区和精确事件出处，不能补为当前时钟。");
  if (Date.parse(occurred) > now) throw new Error("结果返回、实际结束、专业复核和处置须已经发生，不能使用未来时间。");
  return { occurred_at: occurred, original_timezone: handoffZone(draft.timezone), source: await handoffEventSource(draft.reference), effective_at: null };
}
export type ResultsCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: ResultsOperation; payload: Record<string, unknown>; source_read_set: SourceRead[] };
export type ResultsPreview = { command: ResultsCommand; expires_at: string | null; write_tier?: "T1" | "T2"; confirmation_token?: string; approval_token?: string; review: Record<string, unknown> & { before: unknown; after: unknown; effect: string } };
export function makeResultsCommand(product: { id: string; revision: number }, operation: ResultsOperation, payload: Record<string, unknown>, reads: SourceRead[], id: string, key: string): ResultsCommand {
  if (!product.id || !resultsRevision(product.revision) || !resultsOperations.includes(operation) || !id || !key) throw new Error("型号、固定版本或原请求标识尚不完整。");
  return { command_id: id, idempotency_key: key, product_id: product.id, expected_revision: product.revision, operation, payload, source_read_set: resultsReads(reads) };
}
function normalizedPayload(value: unknown, field = ""): unknown {
  if (Array.isArray(value)) return value.map(row => normalizedPayload(row));
  if (!resultsRecord(value)) return ["occurred_at", "effective_at", "observed_at", "valid_until", "start", "finish"].includes(field) && value !== null ? handoffTime(value) : value;
  return Object.fromEntries(Object.entries(value).map(([key, row]) => [key, normalizedPayload(row, key)]));
}
function intentPayload(value: Record<string, unknown>): unknown { const { confirmation_token: _confirmation, approval_token: _approval, ...intent } = value; void _confirmation; void _approval; return normalizedPayload(intent); }
export function validResultsPreview(value: unknown, original: ResultsCommand, now = Date.now()): value is ResultsPreview {
  if (resultsTier(original.operation) === "T0" || !resultsRecord(value) || !resultsRecord(value.command) || !resultsRecord(value.command.payload) || !resultsRecord(value.review) || !("before" in value.review) || !("after" in value.review) || typeof value.review.effect !== "string" || !value.review.effect || !proofClockCurrent(resultsTier(original.operation), value.expires_at, now)) return false;
  const command = value.command, payload = command.payload as Record<string, unknown>, tier = resultsTier(original.operation), token = tier === "T2" ? "approval_token" : "confirmation_token";
  if (!(["command_id", "idempotency_key", "product_id", "expected_revision", "operation"].every(key => command[key] === original[key as keyof ResultsCommand])
    && typeof payload[token] === "string" && payload[token].length >= 20
    && (tier !== "T2" || value.write_tier === "T2" && value.approval_token === payload.approval_token)
    && resultsSame(intentPayload(payload), intentPayload(original.payload)) && resultsSame(command.source_read_set, original.source_read_set)
    && (value.review.operation === undefined || value.review.operation === original.operation))) return false;
  const before = value.review.before, after = value.review.after;
  if (!resultsRecord(before) || !resultsRecord(after) || !resultsRecord(before.request) || !resultsRecord(before.run) || !resultsRecord(after.request) || !resultsRecord(after.run)
    || before.request.request_id !== original.payload.request_id || before.request.revision !== original.payload.expected_request_revision || after.request.request_id !== original.payload.request_id
    || before.run.run_id !== original.payload.run_id || before.run.revision !== original.payload.expected_run_revision || after.run.run_id !== original.payload.run_id || after.run.revision !== Number(original.payload.expected_run_revision) + 1
    || after.occupancy_effect !== "none_retain_original_start_and_consumption") return false;
  if (original.operation === "test.results.import") return Array.isArray(after.observations) && ["append_verified_original_values", "none"].includes(String(after.measurement_effect)) && after.run.status === (original.payload.final === true ? "results_pending" : "running");
  return resultsRecord(before.projection) && before.projection.id === original.payload.projection_id && before.projection.revision === original.payload.expected_projection_revision && before.projection.basis_sha256 === original.payload.expected_basis_sha256
    && after.measurement_effect === "none" && after.run.status === (original.operation === "test.run.review" ? "reviewed" : "disposed");
}
export type ResultsInputs = Record<string, unknown> & { operation: ResultsOperation; run_id: string; allowed: boolean; required_source_read_set: SourceRead[] };
export function validResultsInputs(value: unknown, command: ResultsCommand): value is ResultsInputs {
  if (!resultsRecord(value) || value.operation !== command.operation || value.run_id !== command.payload.run_id || value.request_id !== command.payload.request_id || typeof value.allowed !== "boolean" || !Array.isArray(value.required_source_read_set)) return false;
  try { resultsReads(value.required_source_read_set as SourceRead[]); } catch { return false; }
  return true;
}
export function resultsError(failure: unknown, readOnly = false): { status?: number; message: string } {
  const value = resultsRecord(failure) ? failure : {}, status = typeof value.status === "number" ? value.status : undefined;
  return { status, message: readOnly ? "当前运行、原报告、结果或专业事实读取失败，请刷新核对；本次读取没有发起提交。" : status === 401 || status === 403 ? "当前范围、具名职责或专业资格不可用，请刷新核对。" : [400, 404, 409, 410, 422].includes(status ?? 0) ? "当前版本、原报告、精确位置、结果依据或专业资格已不符合办理条件，请刷新查看具体缺项。" : "尚未取得确定回执，请保留原请求、原标识与完整载荷核对，不另造一次操作。" };
}

export type ResultsRow = Record<string, unknown> & { id: string; revision: number; required_source_read_set: SourceRead[]; source_status?: string; is_current?: boolean };
export type ResultsRequest = ResultsRow & { request_id: string; title: string; purpose: string; build: { id: string; revision: number }; items: Record<string, unknown>[] };
export type ResultsRun = ResultsRow & { run_id: string; request_id: string; build: { id: string; revision: number }; status: string; run_snapshot: Record<string, unknown>; basis_sha256: string; current_projection: null | { id: string; revision: number; basis_sha256: string; result: string }; capabilities: Record<string, boolean>; authority: Record<string, unknown> };
export type ResultsPair = { sample_id: string; item_id: string };
export const resultsPairKey = (pair: ResultsPair): string => JSON.stringify([pair.sample_id, pair.item_id]);
export function resultsPairs(run: ResultsRun): ResultsPair[] {
  const rows = run.run_snapshot.coverage;
  if (!Array.isArray(rows) || !rows.length || rows.some(row => !resultsRecord(row) || typeof row.sample_id !== "string" || !row.sample_id || typeof row.item_id !== "string" || !row.item_id)) throw new Error("尚未取得同一运行的完整固定样件/测试项范围。");
  const pairs = rows.map(row => ({ sample_id: row.sample_id as string, item_id: row.item_id as string }));
  if (new Set(pairs.map(resultsPairKey)).size !== pairs.length) throw new Error("固定运行范围存在重复，请刷新核对。");
  return pairs;
}
export type ObservationSelection = { line: number; sample_id: string; item_id: string };
export type ResultsCaptureInput = { capture_key: string; expected_product_revision: number; request_id: string; expected_request_revision: number; run_id: string; expected_run_revision: number; report_artifact_id: string; expected_report_revision: number; selections: ObservationSelection[]; reason: string };
export type ResultsCapture = ResultsRow & { request_id: string; run_id: string; observations: Record<string, unknown>[]; sources: DefinitionReference[]; results_import_payload: Record<string, unknown>; input_snapshot?: ResultsCaptureInput };
export type PreparedResults = { capture: ResultsCapture; results_import_payload: Record<string, unknown>; required_source_read_set: SourceRead[] };
export type ResultsReport = { artifact_id: string; artifact_revision: number; title: string; source_status: string; original_id: string; original_revision: number; security_epoch: number; lines: { original_line: number; fragment: string }[]; verification: "original_bytes_integrity_checked_format_not_verified"; derived_line_not_assumed: true; has_more: boolean };
export type ResultsList = { requests: ResultsRequest[]; runs: ResultsRun[]; captures: ResultsCapture[]; measurements: Record<string, unknown>[]; projections: Record<string, unknown>[]; actions: Record<string, unknown>[]; current_by_request: Record<string, { request_version_id: string; revision: number }>; current_by_run: Record<string, { run_version_id: string; revision: number }>; reference_samples: Record<string, unknown>[]; report_sources: ResultsReport[]; next_owners: { id: string; label: string }[]; capabilities: Record<string, unknown>; has_more: boolean; unavailable_count: number };
export const emptyResults: ResultsList = { requests: [], runs: [], captures: [], measurements: [], projections: [], actions: [], current_by_request: {}, current_by_run: {}, reference_samples: [], report_sources: [], next_owners: [], capabilities: {}, has_more: false, unavailable_count: 0 };
export function normalizeResults(value: unknown, buildId: string): ResultsList {
  if (!buildId || !resultsRecord(value) || !Array.isArray(value.requests) || !Array.isArray(value.runs) || !Array.isArray(value.captures) || !Array.isArray(value.measurements) || !Array.isArray(value.projections) || !Array.isArray(value.actions) || !resultsRecord(value.current_by_request) || !resultsRecord(value.current_by_run)) throw new Error("尚未取得已选轮次的完整固定运行与结果记录，请刷新核对。");
  if (value.requests.some(row => !resultsRecord(row) || typeof row.id !== "string" || typeof row.request_id !== "string" || !resultsRevision(row.revision) || !resultsRecord(row.build) || row.build.id !== buildId || !Array.isArray(row.items) || !Array.isArray(row.required_source_read_set))
    || value.runs.some(row => !resultsRecord(row) || typeof row.id !== "string" || typeof row.run_id !== "string" || typeof row.request_id !== "string" || !resultsRevision(row.revision) || !resultsRecord(row.build) || row.build.id !== buildId || !resultsRecord(row.run_snapshot) || !resultsHash(row.basis_sha256) || !Array.isArray(row.required_source_read_set))
    || value.captures.some(row => !resultsRecord(row) || typeof row.id !== "string" || typeof row.run_id !== "string" || !resultsRevision(row.revision) || !Array.isArray(row.observations) || !Array.isArray(row.required_source_read_set) || !resultsRecord(row.results_import_payload))) throw new Error("固定运行或原报告候选缺少版本、来源，或不属于本轮，未开放操作。");
  const reportSources = Array.isArray(value.report_sources) ? value.report_sources.filter((row): row is ResultsReport => resultsRecord(row) && typeof row.artifact_id === "string" && resultsRevision(row.artifact_revision) && typeof row.title === "string" && typeof row.original_id === "string" && resultsRevision(row.original_revision) && row.verification === "original_bytes_integrity_checked_format_not_verified" && row.derived_line_not_assumed === true && Array.isArray(row.lines) && row.lines.every(line => resultsRecord(line) && Number.isSafeInteger(line.original_line) && Number(line.original_line) > 0 && typeof line.fragment === "string")) : [];
  return { ...(value as unknown as ResultsList), reference_samples: Array.isArray(value.reference_samples) ? value.reference_samples : [], report_sources: reportSources, next_owners: Array.isArray(value.next_owners) ? value.next_owners.filter(row => resultsRecord(row) && typeof row.id === "string" && typeof row.label === "string") : [], capabilities: resultsRecord(value.capabilities) ? value.capabilities : {}, has_more: value.has_more === true, unavailable_count: typeof value.unavailable_count === "number" ? value.unavailable_count : 0 };
}
export async function readResultsBuild(api: ResultsApi, productId: string, buildId: string, builds: { id: string }[], isCurrent: () => boolean): Promise<ResultsList | null> {
  if (!isCurrent()) return null;
  if (!buildId || !builds.some(row => row.id === buildId)) return emptyResults;
  const value = await api<unknown>(`v1/products/${productId}/verification-results?build_id=${encodeURIComponent(buildId)}`);
  return isCurrent() ? normalizeResults(value, buildId) : null;
}
export type ResultsContext = { builds: Build[]; sources: DefinitionSource[]; data: ResultsList };
export async function readResultsContext(api: ResultsApi, productId: string, buildId: string, isCurrent: () => boolean, projectId = ""): Promise<ResultsContext | null> {
  const outcomes = await Promise.allSettled([api<{ items: Build[] }>(projectBuildsPath(productId, projectId)), api<{ sources: DefinitionSource[] }>(`v1/products/${productId}/workspace`)]);
  if (!isCurrent()) return null;
  // A POST explicitly supersedes old page reads. Only that exact cancellation
  // is silent; a simultaneous genuine read failure must still be reported.
  const failures = outcomes.filter((row): row is PromiseRejectedResult => row.status === "rejected");
  if (failures.some(row => !resultsRecord(row.reason) || row.reason.code !== "READ_SUPERSEDED")) throw new Error(resultsError(null, true).message);
  if (failures.length) return null;
  const [buildResult, sourceResult] = outcomes;
  if (buildResult.status !== "fulfilled" || sourceResult.status !== "fulfilled" || !resultsRecord(buildResult.value) || !resultsRecord(sourceResult.value) || !Array.isArray(buildResult.value.items) || !Array.isArray(sourceResult.value.sources)) throw new Error(resultsError(null, true).message);
  try {
    const data = await readResultsBuild(api, productId, buildId, buildResult.value.items, isCurrent);
    return data && isCurrent() ? { builds: buildResult.value.items, sources: sourceResult.value.sources, data } : null;
  } catch (failure) {
    if (!isCurrent() || resultsRecord(failure) && failure.code === "READ_SUPERSEDED") return null;
    throw new Error(resultsError(failure, true).message);
  }
}
function currentResultsBinding(request: ResultsRequest, run: ResultsRun): Record<string, unknown> {
  if (!request.is_current || !run.is_current || request.source_status !== "current" || run.source_status !== "current" || request.request_id !== run.request_id || request.build.id !== run.build.id || !resultsRevision(run.revision) || !resultsHash(run.basis_sha256)) throw new Error("当前请求、运行版本或固定依据已变化，历史仅供读取，请刷新重核。");
  return { request_id: request.request_id, expected_request_revision: request.revision, run_id: run.run_id, expected_run_revision: run.revision };
}
export function captureResultsInput(productRevision: number, request: ResultsRequest, run: ResultsRun, report: ResultsReport, selections: ObservationSelection[], reason: string, key: string): ResultsCaptureInput {
  const binding = currentResultsBinding(request, run), pairs = new Set(resultsPairs(run).map(resultsPairKey));
  if (run.status !== "running" || report.source_status !== "current" || report.verification !== "original_bytes_integrity_checked_format_not_verified" || report.derived_line_not_assumed !== true || !resultsRevision(report.artifact_revision) || !resultsRevision(productRevision) || key.length < 8 || key.length > 200 || !selections.length) throw new Error("请选择已经实际开测的当前运行、有效原报告和明确原件位置。");
  if (selections.some(row => !Number.isSafeInteger(row.line) || row.line < 1 || !report.lines.some(line => line.original_line === row.line && line.fragment.trim()) || !pairs.has(resultsPairKey(row))) || new Set(selections.map(resultsPairKey)).size !== selections.length || new Set(selections.map(row => row.line)).size !== selections.length) throw new Error("每个原报告位置须对应唯一固定样件/测试项，不能超出、重复或把派生文本行号当原件位置。");
  return { ...(binding as Pick<ResultsCaptureInput, "request_id" | "expected_request_revision" | "run_id" | "expected_run_revision">), capture_key: key, expected_product_revision: productRevision, report_artifact_id: report.artifact_id, expected_report_revision: report.artifact_revision, selections: selections.map(row => ({ line: row.line, sample_id: row.sample_id, item_id: row.item_id })), reason: resultsReason(reason) };
}
export function checkPreparedResults(value: unknown, request: ResultsCaptureInput): value is PreparedResults {
  if (!resultsRecord(value) || !resultsRecord(value.capture) || !resultsRecord(value.results_import_payload) || !Array.isArray(value.required_source_read_set)) return false;
  const capture = value.capture, seed = value.results_import_payload;
  if (typeof capture.id !== "string" || !resultsRevision(capture.revision) || capture.run_id !== request.run_id || !Array.isArray(capture.observations) || seed.request_id !== request.request_id || seed.expected_request_revision !== request.expected_request_revision || seed.run_id !== request.run_id || seed.expected_run_revision !== request.expected_run_revision || seed.capture_id !== capture.id || seed.expected_capture_revision !== capture.revision) return false;
  try { resultsReads(value.required_source_read_set as SourceRead[]); } catch { return false; } return true;
}
export type ResultsWork = { reportId: string; selections: ObservationSelection[]; captureReason: string; captureId: string; final: boolean; incompleteReason: string; nextOwnerId: string; importReason: string; returned: ResultsEventDraft; ended: ResultsEventDraft; computeReason: string; reviewText: string; reviewReason: string; reviewed: ResultsEventDraft; dispositionText: string; dispositionReason: string; disposed: ResultsEventDraft; references: DefinitionReference[] };
export const blankResultsWork = (): ResultsWork => ({ reportId: "", selections: [], captureReason: "", captureId: "", final: false, incompleteReason: "", nextOwnerId: "", importReason: "", returned: blankResultsEvent(), ended: blankResultsEvent(), computeReason: "", reviewText: "", reviewReason: "", reviewed: blankResultsEvent(), dispositionText: "", dispositionReason: "", disposed: blankResultsEvent(), references: [] });
export async function importResultsPayload(request: ResultsRequest, run: ResultsRun, capture: ResultsCapture | undefined, work: ResultsWork, nextOwners: { id: string }[]): Promise<Record<string, unknown>> {
  const binding = currentResultsBinding(request, run), at = await resultsEvent(work.returned), actualEnd = work.final ? await resultsEvent(work.ended) : null;
  if (run.status !== "running" || !work.final && !capture) throw new Error("部分返回必须选择本运行的原报告候选，不能用空记录补造返回。");
  if (capture && (capture.run_id !== run.run_id || capture.source_status !== "current" || capture.results_import_payload.expected_run_revision !== run.revision || capture.results_import_payload.expected_request_revision !== request.revision)) throw new Error("所选原报告候选来源失效或固定版本发生变化，请重新核对原位置。");
  const incomplete = work.incompleteReason.trim(), owner = work.nextOwnerId;
  if (!work.final && (!incomplete || !owner || !nextOwners.some(row => row.id === owner))) throw new Error("部分返回须明确尚未完成原因和服务器列出的下一责任人。");
  if (actualEnd && Date.parse(actualEnd.occurred_at) > Date.parse(at.occurred_at)) throw new Error("实际结束不得晚于本次结果返回时间，两者分别取真实出处。");
  const refs = [...work.references, ...(work.returned.reference ? [work.returned.reference] : []), ...(work.final && work.ended.reference ? [work.ended.reference] : [])];
  const sources = [...new Map(refs.map(ref => [resultsRefKey(ref), ref])).values()]; if (!resultsRefs(sources)) throw new Error("本次精确来源不完整。");
  return { ...binding, capture_id: capture?.id ?? null, expected_capture_revision: capture?.revision ?? null, final: work.final, at, actual_end: actualEnd, incomplete_reason: work.final ? null : resultsReason(incomplete), next_owner_id: work.final ? null : owner, sources, reason: resultsReason(work.importReason) };
}
export function computeResultsPayload(request: ResultsRequest, run: ResultsRun, reason: string): Record<string, unknown> { return { ...currentResultsBinding(request, run), expected_basis_sha256: run.basis_sha256, reason: resultsReason(reason) }; }
export async function professionalResultsPayload(request: ResultsRequest, run: ResultsRun, operation: "test.run.review" | "test.disposition.decide", work: ResultsWork): Promise<Record<string, unknown>> {
  const binding = currentResultsBinding(request, run), projection = run.current_projection;
  if (!projection || !resultsRevision(projection.revision) || projection.basis_sha256 !== run.basis_sha256) throw new Error("当前固定结果投影或完整依据摘要需重新核对，不能沿用旧批准。");
  const draft = operation === "test.run.review" ? work.reviewed : work.disposed, at = await resultsEvent(draft), text = (operation === "test.run.review" ? work.reviewText : work.dispositionText).trim();
  if (!text || text.length > 2000) throw new Error("请明确填写独立专业结论或处置意见，最多 2000 字。");
  const sources = [...new Map([...work.references, ...(draft.reference ? [draft.reference] : [])].map(ref => [resultsRefKey(ref), ref])).values()]; if (!resultsRefs(sources)) throw new Error("本次具名批准的精确来源不完整。");
  return { ...binding, projection_id: projection.id, expected_projection_revision: projection.revision, expected_basis_sha256: run.basis_sha256, text, at, sources, reason: resultsReason(operation === "test.run.review" ? work.reviewReason : work.dispositionReason) };
}
export function validResultsReceipt(value: unknown, command: ResultsCommand): value is { id: string; subject_id: string; subject_type: string; operation: ResultsOperation } { return resultsRecord(value) && typeof value.id === "string" && !!value.id && typeof value.subject_id === "string" && !!value.subject_id && value.operation === command.operation && value.subject_type === (command.operation === "test.result.compute" ? "test_result_projection" : "test_run"); }
export type ResultsPending = { stage: "capture"; request: ResultsCaptureInput } | { stage: "inputs" | "preview" | "execute"; command: ResultsCommand };
export type LocalResults = { selectedBuildId: string; selectedRunId: string; selectedRunVersionId: string; drafts: Record<string, ResultsWork>; pending: ResultsPending | null };
export const blankLocalResults = (): LocalResults => ({ selectedBuildId: "", selectedRunId: "", selectedRunVersionId: "", drafts: {}, pending: null });
function validEventDraft(value: unknown): boolean { return resultsRecord(value) && typeof value.occurredAt === "string" && typeof value.timezone === "string" && (value.reference === null || validHandoffRef(value.reference)); }
export function restoreResults(value: unknown, productId: string, principalId: string): LocalResults | null {
  if (!resultsRecord(value) || value.schema_version !== 1 || value.product_id !== productId || value.principal_id !== principalId || !["selectedBuildId", "selectedRunId", "selectedRunVersionId"].every(key => typeof value[key] === "string") || !resultsRecord(value.drafts)) return null;
  for (const draft of Object.values(value.drafts)) if (!resultsRecord(draft) || !["reportId", "captureReason", "captureId", "incompleteReason", "nextOwnerId", "importReason", "computeReason", "reviewText", "reviewReason", "dispositionText", "dispositionReason"].every(key => typeof draft[key] === "string") || typeof draft.final !== "boolean" || !["returned", "ended", "reviewed", "disposed"].every(key => validEventDraft(draft[key])) || !resultsRefs(draft.references) || !Array.isArray(draft.selections) || draft.selections.some(row => !resultsRecord(row) || !Number.isSafeInteger(row.line) || Number(row.line) < 0 || typeof row.sample_id !== "string" || typeof row.item_id !== "string")) return null;
  if (value.pending != null) {
    const pending = value.pending; if (!resultsRecord(pending)) return null;
    if (pending.stage === "capture") { const input = pending.request; if (!resultsRecord(input) || input.run_id !== value.selectedRunId || typeof input.capture_key !== "string" || input.capture_key.length < 8 || typeof input.report_artifact_id !== "string" || !resultsRevision(input.expected_product_revision) || !resultsRevision(input.expected_run_revision) || !resultsRevision(input.expected_request_revision) || !resultsRevision(input.expected_report_revision) || !Array.isArray(input.selections) || !input.selections.length || input.selections.some(row => !resultsRecord(row) || !Number.isSafeInteger(row.line) || Number(row.line) < 1 || typeof row.sample_id !== "string" || typeof row.item_id !== "string")) return null; }
    else if (["inputs", "preview", "execute"].includes(String(pending.stage))) { const command = pending.command; if (!resultsRecord(command) || command.product_id !== productId || !resultsRevision(command.expected_revision) || !resultsOperations.includes(command.operation as ResultsOperation) || typeof command.command_id !== "string" || typeof command.idempotency_key !== "string" || !resultsRecord(command.payload) || command.payload.run_id !== value.selectedRunId || !Array.isArray(command.source_read_set)) return null; try { resultsReads(command.source_read_set as SourceRead[]); } catch { return null; } if (pending.stage === "execute" && resultsTier(command.operation as ResultsOperation) !== "T0") { const token = resultsTier(command.operation as ResultsOperation) === "T2" ? "approval_token" : "confirmation_token"; if (typeof command.payload[token] !== "string" || command.payload[token].length < 20) return null; } }
    else return null;
  }
  return value as unknown as LocalResults;
}
