import type { Build } from "./build-preparation-view";

export type ProjectBuildApi = <T>(path: string, body?: unknown) => Promise<T>;
export type ProjectBuildScope = { categoryId: string; productId: string; projectId: string };
export type ProjectBuildSourceStatus = "current" | "needs_recheck";
export type ProjectBuildRecord = Build & { project_revision: number; source_status: ProjectBuildSourceStatus };
export type ProjectBuildList = { items: ProjectBuildRecord[]; unavailableCount: number; hasMore: boolean };
export type ProjectBuildResult = "pending" | "pass" | "fail" | "indeterminate" | "invalid";
export type ProjectBuildRunStatus = "planned" | "running" | "results_pending" | "reviewed" | "disposed";
export type ProjectBuildPair = { sample_id: string; item_id: string };
export type ProjectBuildClock = Record<string, unknown> & { occurred_at: string; original_timezone: string; effective_at: string | null; received_at: string };
export type ProjectBuildMeasurement = Record<string, unknown> & { id: string; coverage: ProjectBuildPair; raw_value: string | null; unit: string | null; observed_at: string | null; observed_timezone: string | null };
export type ProjectBuildComputed = { coverage: ProjectBuildPair; result: ProjectBuildResult; measurement_id: string | null; reasons: string[] };
export type ProjectBuildRunSnapshot = Record<string, unknown> & {
  id: string; revision: number; status: ProjectBuildRunStatus; result: ProjectBuildResult;
  coverage: ProjectBuildPair[]; measurements: ProjectBuildMeasurement[]; computed_results: ProjectBuildComputed[];
  partial_returns: Record<string, unknown>[]; actual_start: ProjectBuildClock | null; actual_end: ProjectBuildClock | null;
  final_result: ProjectBuildClock | null; professional_conclusion: Record<string, unknown> | null; disposition: Record<string, unknown> | null;
};
export type ProjectBuildRunSummary = {
  runId: string; versionId: string; revision: number; requestRevision: number; status: ProjectBuildRunStatus; result: ProjectBuildResult;
  sourceStatus: ProjectBuildSourceStatus; createdAt: string;
  request: { id: string; versionId: string; revision: number; title: string; status: string; sourceStatus: ProjectBuildSourceStatus };
  coverage: { sampleCount: number; itemCount: number; pairCount: number; measuredPairCount: number; missingPairCount: number };
  currentProjection: null | { id: string; revision: number; basisSha256: string; result: ProjectBuildResult; runVersionId: string; runRevision: number; sourceStatus: ProjectBuildSourceStatus };
  runSnapshot: ProjectBuildRunSnapshot;
};
export type ProjectBuildTestSummary = { build: ProjectBuildRecord; runs: ProjectBuildRunSummary[]; unavailableCount: number; hasMore: boolean; unindexedRunCount: number };

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const revision = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const text = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const nullableText = (value: unknown) => value === null || typeof value === "string";
const hash = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const sourceStatus = (value: unknown): value is ProjectBuildSourceStatus => value === "current" || value === "needs_recheck";
const result = (value: unknown): value is ProjectBuildResult => typeof value === "string" && ["pending", "pass", "fail", "indeterminate", "invalid"].includes(value);
const runStatus = (value: unknown): value is ProjectBuildRunStatus => typeof value === "string" && ["planned", "running", "results_pending", "reviewed", "disposed"].includes(value);
const iso = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const nullableIso = (value: unknown) => value === null || iso(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === "string");
function invalid(): never { throw new Error("项目轮次、当前测试索引或固定版本无法核对，请刷新后重新选择 Build。"); }
const pairKey = (pair: ProjectBuildPair) => JSON.stringify([pair.sample_id, pair.item_id]);

function checkScope(scope: ProjectBuildScope): void {
  if (!record(scope) || !uuid(scope.categoryId) || !uuid(scope.productId) || !uuid(scope.projectId)) invalid();
}
function root(scope: ProjectBuildScope): string {
  return `v1/categories/${scope.categoryId}/products/${scope.productId}`;
}
function fixedConfiguration(value: unknown): boolean {
  return record(value) && uuid(value.id) && revision(value.revision) && text(value.name) && typeof value.status === "string";
}
function buildRecord(value: unknown, scope: ProjectBuildScope): value is ProjectBuildRecord {
  return record(value) && uuid(value.id) && revision(value.revision) && value.project_id === scope.projectId
    && revision(value.project_revision) && text(value.project_name) && text(value.name) && typeof value.purpose === "string"
    && value.status === "planned" && ["prototype", "tool_trial", "pilot"].includes(String(value.type))
    && sourceStatus(value.source_status) && typeof value.planned_quantity === "string" && /^\d+(?:\.\d+)?$/.test(value.planned_quantity) && /[1-9]/.test(value.planned_quantity)
    && text(value.unit) && nullableIso(value.planned_start) && nullableIso(value.planned_end) && iso(value.created_at)
    && (value.previous_build_id === null || uuid(value.previous_build_id)) && uuid(value.owner_id)
    && ["private", "category", "audience"].includes(String(value.visibility)) && Array.isArray(value.required_source_read_set)
    && fixedConfiguration(value.engineering_configuration) && fixedConfiguration(value.manufacturing_configuration);
}

export async function readProjectBuilds(api: ProjectBuildApi, scope: ProjectBuildScope): Promise<ProjectBuildList> {
  checkScope(scope);
  const value = await api<unknown>(`${root(scope)}/builds?${new URLSearchParams({ project_id: scope.projectId })}`);
  if (!record(value) || !Array.isArray(value.items) || !count(value.unavailable_count) || typeof value.has_more !== "boolean") invalid();
  if (value.items.some(item => !record(item) || item.project_id !== scope.projectId)) invalid();
  const rows = value.items;
  if (!rows.every(item => buildRecord(item, scope)) || new Set(rows.map(item => item.id)).size !== rows.length) invalid();
  return { items: rows as ProjectBuildRecord[], unavailableCount: value.unavailable_count, hasMore: value.has_more };
}

function buildBinding(value: unknown, scope: ProjectBuildScope, build: ProjectBuildRecord): boolean {
  return record(value) && value.id === build.id && value.revision === build.revision
    && value.product_id === scope.productId && value.project_id === scope.projectId
    && record(value.engineering_configuration) && value.engineering_configuration.id === build.engineering_configuration.id
    && value.engineering_configuration.revision === build.engineering_configuration.revision
    && record(value.manufacturing_configuration) && value.manufacturing_configuration.id === build.manufacturing_configuration.id
    && value.manufacturing_configuration.revision === build.manufacturing_configuration.revision;
}
function snapshotScope(value: unknown, scope: ProjectBuildScope): boolean {
  return record(value) && uuid(value.tenant_id) && value.product_id === scope.productId && value.project_id === scope.projectId;
}
function pairs(value: unknown, required = false): ProjectBuildPair[] {
  if (!Array.isArray(value) || required && !value.length || value.some(item => !record(item) || !uuid(item.sample_id) || !text(item.item_id))) invalid();
  const rows = value as ProjectBuildPair[];
  if (new Set(rows.map(pairKey)).size !== rows.length) invalid();
  return rows;
}
function clock(value: unknown): value is ProjectBuildClock | null {
  return value === null || record(value) && iso(value.occurred_at) && text(value.original_timezone) && nullableIso(value.effective_at) && iso(value.received_at);
}
function runSnapshot(value: unknown, row: Record<string, unknown>, scope: ProjectBuildScope, build: ProjectBuildRecord): ProjectBuildRunSnapshot {
  if (!record(value) || value.id !== row.run_id || value.revision !== row.revision || value.status !== row.status || value.result !== row.result
    || value.request_id !== row.request_id || value.request_revision !== row.request_revision || !snapshotScope(value.scope, scope) || !buildBinding(value.build, scope, build)
    || !Array.isArray(value.measurements) || !Array.isArray(value.computed_results) || !Array.isArray(value.partial_returns)
    || !clock(value.actual_start) || !clock(value.actual_end) || !clock(value.final_result)
    || !(value.professional_conclusion === null || record(value.professional_conclusion)) || !(value.disposition === null || record(value.disposition))) invalid();
  const coverage = pairs(value.coverage, true), known = new Set(coverage.map(pairKey)), measurementIds = new Set<string>(), measured = new Set<string>();
  for (const item of value.measurements) {
    if (!record(item) || !uuid(item.id) || measurementIds.has(item.id) || !nullableText(item.raw_value) || !nullableText(item.unit) || !nullableIso(item.observed_at) || !nullableText(item.observed_timezone)) invalid();
    const [pair] = pairs([item.coverage]);
    if (!known.has(pairKey(pair)) || measured.has(pairKey(pair))) invalid();
    measurementIds.add(item.id); measured.add(pairKey(pair));
  }
  const computed = new Set<string>();
  for (const item of value.computed_results) {
    if (!record(item) || !result(item.result) || !strings(item.reasons) || !(item.measurement_id === null || uuid(item.measurement_id) && measurementIds.has(item.measurement_id))) invalid();
    const [pair] = pairs([item.coverage]);
    if (!known.has(pairKey(pair)) || computed.has(pairKey(pair))) invalid();
    computed.add(pairKey(pair));
  }
  for (const item of value.partial_returns) {
    if (!record(item) || !clock(item.at) || item.at === null) invalid();
    const returned = pairs(item.returned_coverage), pending = pairs(item.pending_coverage), returnedKeys = new Set(returned.map(pairKey));
    if ([...returned, ...pending].some(pair => !known.has(pairKey(pair))) || pending.some(pair => returnedKeys.has(pairKey(pair)))) invalid();
  }
  if ((row.status === "planned") !== (value.actual_start === null)) invalid();
  const final = ["results_pending", "reviewed", "disposed"].includes(String(row.status));
  if (final !== (value.final_result !== null) || final !== (value.actual_end !== null)) invalid();
  return value as ProjectBuildRunSnapshot;
}

type RawRun = Record<string, unknown> & { id: string; run_id: string; revision: number; request_id: string; request_revision: number; status: ProjectBuildRunStatus; result: ProjectBuildResult; source_status: ProjectBuildSourceStatus; is_current: boolean; created_at: string; basis_sha256: string; run_snapshot: ProjectBuildRunSnapshot };
type RawRequest = Record<string, unknown> & { id: string; request_id: string; revision: number; title: string; status: string; source_status: ProjectBuildSourceStatus; is_current: boolean };
function currentRows<T extends Record<string, unknown>>(rows: T[], index: Record<string, unknown>, logical: string, versionKey: string): Map<string, T> {
  const selected = new Map<string, T>();
  for (const [identity, pointer] of Object.entries(index)) {
    if (!uuid(identity) || !record(pointer) || !uuid(pointer[versionKey]) || !revision(pointer.revision)) invalid();
    const matches = rows.filter(row => row[logical] === identity && row.id === pointer[versionKey] && row.revision === pointer.revision && row.is_current === true);
    if (matches.length !== 1) invalid();
    selected.set(identity, matches[0]);
  }
  if (rows.some(row => row.is_current === true && selected.get(String(row[logical])) !== row)) invalid();
  return selected;
}

function summary(value: unknown, scope: ProjectBuildScope, build: ProjectBuildRecord): ProjectBuildTestSummary {
  if (!record(value) || !Array.isArray(value.runs) || !Array.isArray(value.requests) || !Array.isArray(value.projections)
    || !record(value.current_by_run) || !record(value.current_by_request) || !count(value.unavailable_count) || typeof value.has_more !== "boolean") invalid();
  const runs: RawRun[] = [], requests: RawRequest[] = [];
  for (const raw of value.requests) {
    if (!record(raw) || !uuid(raw.id) || !uuid(raw.request_id) || !revision(raw.revision) || !text(raw.title) || typeof raw.status !== "string"
      || !sourceStatus(raw.source_status) || typeof raw.is_current !== "boolean" || raw.project_id !== scope.projectId || !buildBinding(raw.build, scope, build)
      || !record(raw.request_snapshot) || raw.request_snapshot.id !== raw.request_id || raw.request_snapshot.revision !== raw.revision
      || raw.request_snapshot.status !== raw.status
      || !snapshotScope(raw.request_snapshot.scope, scope) || !buildBinding(raw.request_snapshot.build, scope, build)) invalid();
    requests.push(raw as RawRequest);
  }
  for (const raw of value.runs) {
    if (!record(raw) || !uuid(raw.id) || !uuid(raw.run_id) || !uuid(raw.request_id) || !revision(raw.revision) || !revision(raw.request_revision)
      || !runStatus(raw.status) || !result(raw.result) || !sourceStatus(raw.source_status) || typeof raw.is_current !== "boolean" || !iso(raw.created_at)
      || !hash(raw.basis_sha256) || !buildBinding(raw.build, scope, build)) invalid();
    runs.push({ ...raw, run_snapshot: runSnapshot(raw.run_snapshot, raw, scope, build) } as RawRun);
  }
  if (new Set(runs.map(row => row.id)).size !== runs.length || new Set(requests.map(row => row.id)).size !== requests.length) invalid();
  const currentRuns = currentRows(runs, value.current_by_run, "run_id", "run_version_id"), currentRequests = currentRows(requests, value.current_by_request, "request_id", "request_version_id");
  const items: ProjectBuildRunSummary[] = [];
  for (const run of currentRuns.values()) {
    const request = currentRequests.get(run.request_id);
    if (!request) invalid();
    const runScope = run.run_snapshot.scope, requestSnapshot = request.request_snapshot;
    if (!record(runScope) || !record(requestSnapshot) || !record(requestSnapshot.scope) || runScope.tenant_id !== requestSnapshot.scope.tenant_id) invalid();
    let projection: ProjectBuildRunSummary["currentProjection"] = null;
    if (run.current_projection !== null) {
      const pointer = run.current_projection;
      if (!record(pointer) || !uuid(pointer.id) || !revision(pointer.revision) || !hash(pointer.basis_sha256) || pointer.basis_sha256 !== run.basis_sha256 || !result(pointer.result)) invalid();
      const matching = value.projections.filter(row => record(row) && row.id === pointer.id);
      if (matching.length !== 1) invalid();
      const fixed = matching[0];
      if (!record(fixed) || fixed.revision !== pointer.revision || fixed.run_id !== run.run_id || fixed.basis_sha256 !== pointer.basis_sha256 || fixed.result !== pointer.result
        || !uuid(fixed.run_version_id) || !revision(fixed.run_revision) || !sourceStatus(fixed.source_status)
        || !runs.some(row => row.id === fixed.run_version_id && row.run_id === run.run_id && row.revision === fixed.run_revision)) invalid();
      projection = { id: pointer.id, revision: pointer.revision, basisSha256: pointer.basis_sha256, result: pointer.result,
        runVersionId: fixed.run_version_id, runRevision: fixed.run_revision, sourceStatus: fixed.source_status };
    }
    const fixed = run.run_snapshot;
    items.push({ runId: run.run_id, versionId: run.id, revision: run.revision, requestRevision: run.request_revision, status: run.status, result: run.result,
      sourceStatus: run.source_status, createdAt: run.created_at,
      request: { id: request.request_id, versionId: request.id, revision: request.revision, title: request.title, status: request.status, sourceStatus: request.source_status },
      coverage: { sampleCount: new Set(fixed.coverage.map(pair => pair.sample_id)).size, itemCount: new Set(fixed.coverage.map(pair => pair.item_id)).size,
        pairCount: fixed.coverage.length, measuredPairCount: fixed.measurements.length, missingPairCount: fixed.coverage.length - fixed.measurements.length },
      currentProjection: projection, runSnapshot: fixed });
  }
  return { build, runs: items, unavailableCount: value.unavailable_count, hasMore: value.has_more,
    unindexedRunCount: new Set(runs.filter(row => !currentRuns.has(row.run_id)).map(row => row.run_id)).size };
}

export async function readBuildTestSummary(api: ProjectBuildApi, scope: ProjectBuildScope, selectedBuild: ProjectBuildRecord): Promise<ProjectBuildTestSummary> {
  checkScope(scope);
  if (!buildRecord(selectedBuild, scope)) invalid();
  const latest = await readProjectBuilds(api, scope), build = latest.items.find(row => row.id === selectedBuild.id);
  if (!build || build.revision !== selectedBuild.revision) invalid();
  const value = await api<unknown>(`${root(scope)}/verification-results?${new URLSearchParams({ build_id: build.id })}`);
  return summary(value, scope, build);
}
