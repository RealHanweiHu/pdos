import { mpRecord, mpRevision, mpSame, mpUuid } from "../components/manufacturing-preparation/manufacturing-preparation-contract";
import { releaseAssessments, releaseDetail, releaseHeader, type ReleaseApi, type ReleaseAssessment, type ReleaseDetail, type ReleaseHeader, type ReleaseScope } from "./releases";

export type ProjectReleaseScope = ReleaseScope;
export type ProjectReleaseApi = ReleaseApi;
export type ProjectReleaseHeader = ReleaseHeader & { isSeriesCurrent: boolean };
export type ProjectReleaseList = { items: ProjectReleaseHeader[]; nextCursor: string | null };
export type ProjectReleasePackage = { detail: ReleaseDetail; isSeriesCurrent: boolean; assessments: ReleaseAssessment[] };

const text = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const instant = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
function invalid(): never { throw new Error("本项目固定发布包、所选版本或专业决定读取不完整，请刷新后重新选择；不能用当前版或旧资料补齐。"); }
function scopeRoot(scope: ProjectReleaseScope): string {
  if (!mpRecord(scope) || ![scope.categoryId, scope.productId, scope.projectId, scope.principalId].every(mpUuid)) invalid();
  return `v1/categories/${scope.categoryId}/products/${scope.productId}/release-packages`;
}
function header(value: unknown, scope: ProjectReleaseScope): value is ReleaseHeader {
  if (!releaseHeader(value, scope.projectId) || !text(value.purpose) || value.status !== "assembled") return false;
  const current = value.current;
  return current.epoch === current.version.revision && current.version.revision >= value.revision
    && (current.version.id === value.id) === (current.version.revision === value.revision);
}
function isSeriesCurrent(value: ReleaseHeader): boolean {
  return value.current.version.id === value.id && value.current.version.revision === value.revision;
}
function bothAssessments(value: unknown): ReleaseAssessment[] | null {
  const rows = releaseAssessments(value);
  return rows?.length === 2 && rows.some(row => row.discipline === "engineering") && rows.some(row => row.discipline === "manufacturing") ? rows : null;
}

/** Returned rows only; a series head may lie outside this historical page. */
export async function readProjectReleasePackages(api: ProjectReleaseApi, scope: ProjectReleaseScope, cursor?: string): Promise<ProjectReleaseList> {
  const root = scopeRoot(scope);
  if (cursor !== undefined && !mpUuid(cursor)) invalid();
  const query = new URLSearchParams({ project_id: scope.projectId });
  if (cursor !== undefined) query.set("history_cursor", cursor);
  const value = await api<unknown>(`${root}?${query}`);
  if (!mpRecord(value) || !Array.isArray(value.items) || !value.items.every(row => header(row, scope))
    || !(value.next_cursor === null || mpUuid(value.next_cursor)) || new Set(value.items.map(row => row.id)).size !== value.items.length) invalid();
  const rows = value.items as ReleaseHeader[], pointers = new Map<string, ReleaseHeader["current"]>();
  if (new Set(rows.map(row => JSON.stringify([row.current.id, row.revision]))).size !== rows.length) invalid();
  for (const row of rows) {
    const previous = pointers.get(row.current.id);
    if (previous && !mpSame(previous, row.current)) invalid();
    pointers.set(row.current.id, row.current);
  }
  if (value.next_cursor !== null && (value.next_cursor === cursor || rows.at(-1)?.id !== value.next_cursor)) invalid();
  return { items: rows.map(row => ({ ...row, isSeriesCurrent: isSeriesCurrent(row) })), nextCursor: value.next_cursor };
}

/** Explicit fixed identity, never a Current substitution or an authorization decision. */
export async function readProjectReleasePackage(api: ProjectReleaseApi, scope: ProjectReleaseScope, selected: { id: string; revision: number }): Promise<ProjectReleasePackage> {
  const root = scopeRoot(scope);
  if (!mpRecord(selected) || !mpUuid(selected.id) || !mpRevision(selected.revision)) invalid();
  const value = await api<unknown>(`${root}/${selected.id}`);
  if (!releaseDetail(value, scope) || !header(value, scope) || value.id !== selected.id || value.revision !== selected.revision
    || !mpRecord(value.package.scope) || !mpUuid(value.package.scope.tenant_id)
    || !mpRecord(value.package.declaration) || value.package.declaration.purpose !== value.purpose
    || !mpUuid(value.package.owner_id) || !mpRevision(value.package.product_revision)
    || value.package.status !== "unexecuted_candidate") invalid();
  const assessments = bothAssessments(value.assessments);
  if (!assessments || new Set(value.decisions.map(row => row.id)).size !== value.decisions.length
    || new Set(value.decisions.map(row => row.discipline)).size !== value.decisions.length) invalid();
  for (const row of value.decisions) {
    const body = row.decision;
    if (!mpRecord(body) || !mpRecord(row.authority) || !mpRecord(body.scope) || !mpSame(body.scope, value.package.scope)
      || body.category_id !== scope.categoryId || !mpSame(body.package, { id: selected.id, revision: selected.revision })
      || body.discipline !== row.discipline || body.operation !== `release.${row.discipline}.approve`
      || body.purpose !== value.purpose || !mpRecord(body.release_scope)
      || !mpRecord(value.package.declaration) || !mpSame(body.subject_config, value.package.declaration.subject_config)
      || !Array.isArray(body.signers) || !body.signers.length || !body.signers.every(mpUuid)
      || !(body.expiry === null || instant(body.expiry)) || !instant(body.prepared_at)
      || !Array.isArray(body.limits) || !body.limits.every(limit => mpRecord(limit) && text(limit.text) && Array.isArray(limit.sources) && limit.sources.length > 0)
      || !mpRecord(body.assessment) || body.assessment.discipline !== row.discipline || releaseAssessments([body.assessment]) === null) invalid();
  }
  // Preserve the complete original detail, including either assessment shape,
  // immutable decision bodies and each independent applicability result.
  return { detail: value, isSeriesCurrent: isSeriesCurrent(value), assessments };
}
