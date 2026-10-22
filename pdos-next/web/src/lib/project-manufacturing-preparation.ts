import { mpReading, mpRecord, mpSame, mpUuid, validMpRef, validMpVersion, type MpApi, type MpBody, type MpVersion } from "../components/manufacturing-preparation/manufacturing-preparation-contract";

export type ProjectManufacturingPreparationApi = MpApi;
export type ProjectManufacturingPreparationScope = { categoryId: string; productId: string; projectId: string };
export type ProjectManufacturingPreparationVersion = MpVersion;
export type ProjectManufacturingPreparationOptions = { historyCursor?: string };
export type ProjectManufacturingPreparationDocumentBinding = MpBody["document_bindings"][number];
export type ProjectManufacturingPreparationDocument = {
  baseline: { kind: "manufacturing_baseline"; id: string; revision: number };
  binding: ProjectManufacturingPreparationDocumentBinding;
  document: ProjectManufacturingPreparationVersion;
  /** PreparationView has no body_sha256. The binding retains its saved hash only. */
  bodyHashVerification: "not_returned_by_endpoint";
};
export type ProjectManufacturingPreparation = {
  schemaVersion: "pdos-manufacturing-preparation-v1";
  currentVersions: ProjectManufacturingPreparationVersion[];
  returnedHistory: ProjectManufacturingPreparationVersion[];
  /** Each page contains newly read series heads and one historical page. */
  hasMore: boolean;
  nextCursor: string | null;
  /** This count belongs to this response, not an accumulated project total. */
  unavailableCount: number;
  qualification: "unknown";
  manufacturingRelease: null;
  negativeEnumerationComplete: false;
};

function invalid(): never {
  throw new Error("本项目制造准备资料的固定范围、版本或读取覆盖未能核对，请重新读取；不能用其他项目、当前版本或就绪结论补齐。");
}
function scopeRoot(scope: ProjectManufacturingPreparationScope): string {
  if (!mpRecord(scope) || !mpUuid(scope.categoryId) || !mpUuid(scope.productId) || !mpUuid(scope.projectId)) invalid();
  return `v1/categories/${scope.categoryId}/products/${scope.productId}/manufacturing-preparations`;
}
function historyCursor(value: unknown): value is string {
  if (typeof value !== "string" || !value.trim() || value.length > 2000) return false;
  try { encodeURIComponent(value); return true; } catch { return false; }
}
function fixedVersion(value: unknown, scope: ProjectManufacturingPreparationScope): value is MpVersion {
  return validMpVersion(value) && value.project_id === scope.projectId && /(?:Z|[+-]\d{2}:\d{2})$/.test(value.created_at);
}

/** Draft facts only. Current means a series head, never qualification or release. */
export async function readProjectManufacturingPreparation(
  api: ProjectManufacturingPreparationApi,
  scope: ProjectManufacturingPreparationScope,
  options?: ProjectManufacturingPreparationOptions,
): Promise<ProjectManufacturingPreparation> {
  const root = scopeRoot(scope);
  if (options !== undefined && (!mpRecord(options) || Object.keys(options).some(key => key !== "historyCursor")
    || (options.historyCursor !== undefined && !historyCursor(options.historyCursor)))) invalid();
  const query = new URLSearchParams({ project_id: scope.projectId });
  if (options?.historyCursor !== undefined) query.set("history_cursor", options.historyCursor);
  const raw = await api<unknown>(`${root}?${query}`);
  // mpReading delegates each complete body and fixed relation to validMpVersion.
  const reading = mpReading(raw, scope.projectId);
  if (!reading || !mpRecord(reading.history_page)) invalid();
  const cursor = reading.history_page.next_cursor;
  if (!(cursor === null || historyCursor(cursor)) || reading.has_more !== (cursor !== null)
    || (cursor !== null && cursor === options?.historyCursor)) invalid();
  const versions = new Map<string, MpVersion>(), revisions = new Set<string>(), currentSeries = new Set<string>();
  for (const version of reading.versions) {
    const seriesKey = JSON.stringify([version.kind, version.series_id]);
    const revisionKey = JSON.stringify([version.kind, version.series_id, version.revision]);
    if (versions.has(version.id) || revisions.has(revisionKey)
      || !/(?:Z|[+-]\d{2}:\d{2})$/.test(version.created_at)
      || version.is_current && currentSeries.has(seriesKey)) invalid();
    versions.set(version.id, version); revisions.add(revisionKey);
    if (version.is_current) currentSeries.add(seriesKey);
  }
  for (const version of versions.values()) {
    // A prior version may be on an unread historical page. Never substitute it.
    const previous = version.previous_id === null ? undefined : versions.get(version.previous_id);
    if (previous && (previous.kind !== version.kind || previous.series_id !== version.series_id || previous.revision !== version.previous_revision)) invalid();
  }
  return {
    schemaVersion: reading.schema_version,
    currentVersions: reading.versions.filter(version => version.is_current),
    returnedHistory: reading.versions.filter(version => !version.is_current),
    hasMore: reading.has_more,
    nextCursor: cursor,
    unavailableCount: reading.unavailable_count,
    qualification: reading.qualification,
    manufacturingRelease: reading.manufacturing_release,
    negativeEnumerationComplete: reading.negative_enumeration_complete,
  };
}

/** Resolve only a binding from this exact saved baseline, never a Current child. */
export async function readProjectManufacturingPreparationDocument(
  api: ProjectManufacturingPreparationApi,
  scope: ProjectManufacturingPreparationScope,
  baseline: ProjectManufacturingPreparationVersion,
  binding: ProjectManufacturingPreparationDocumentBinding,
): Promise<ProjectManufacturingPreparationDocument> {
  const root = scopeRoot(scope);
  if (!fixedVersion(baseline, scope) || baseline.kind !== "manufacturing_baseline" || !mpRecord(binding)
    || !["work_instruction", "control_plan"].includes(binding.kind)
    || !validMpRef({ kind: binding.kind, id: binding.id, revision: binding.revision })
    || baseline.body.document_bindings.filter(saved => mpSame(saved, binding)).length !== 1) invalid();
  const raw = await api<unknown>(`${root}/${binding.kind}/${binding.id}?${new URLSearchParams({ revision: String(binding.revision) })}`);
  if (!fixedVersion(raw, scope) || raw.kind !== binding.kind || raw.id !== binding.id || raw.revision !== binding.revision
    || !mpSame(raw.process, baseline.process) || raw.operation_key !== binding.operation_key) invalid();
  return {
    baseline: { kind: "manufacturing_baseline", id: baseline.id, revision: baseline.revision },
    binding,
    document: raw,
    bodyHashVerification: "not_returned_by_endpoint",
  };
}
