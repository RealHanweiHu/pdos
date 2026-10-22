import { mpRecord, mpRevision, mpSame, mpUuid } from "../components/manufacturing-preparation/manufacturing-preparation-contract";
import { nativeCountFields, nativeItem, type NativeApi, type NativePilotItem, type NativeScope } from "./native-pilots";

export type ProjectPilotScope = NativeScope;
export type ProjectPilotApi = NativeApi;
export type ProjectPilotPage = { items: NativePilotItem[]; nextCursor: string | null };

const text = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0 && Number(value) <= 1e12;
const instant = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const sourceStatus = (value: unknown) => value === "current" || value === "needs_recheck";
const strings = (value: unknown) => Array.isArray(value) && value.every(text);
const decimal = (value: unknown) => value === null || typeof value === "string" && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value);
function invalid(): never { throw new Error("本项目试产记录的范围、当前指针、观察链或原统计读取不完整，请刷新；不能用其他项目、旧观察或默认数值补齐。"); }
function counts(value: unknown): boolean {
  return mpRecord(value) && nativeCountFields.every(field => value[field] === null || count(value[field]));
}
function metadata(value: unknown, scope: ProjectPilotScope): value is Record<string, unknown> {
  if (!mpRecord(value) || !mpUuid(value.id) || !mpRevision(value.revision) || !instant(value.created_at)
    || !mpUuid(value.owner_id) || !mpUuid(value.writer_id) || !mpUuid(value.receipt_id) || !sourceStatus(value.source_status)
    || !Array.isArray(value.sources) || !Array.isArray(value.required_source_read_set) || !mpRecord(value.material)
    || value.qualification !== "unknown" || value.start_authorized !== false || value.manufacturing_release !== null || value.external_delivery !== false
    || !mpRecord(value.material.pilot) || !mpRecord(value.material.pilot.scope)) return false;
  const material = value.material.pilot;
  return mpRecord(material.scope) && mpUuid(material.scope.tenant_id) && material.scope.product_id === scope.productId
    && material.scope.project_id === scope.projectId && material.category_id === scope.categoryId;
}
function rate(value: unknown): boolean {
  return mpRecord(value) && (value.numerator === null || count(value.numerator)) && (value.denominator === null || count(value.denominator))
    && decimal(value.value) && decimal(value.recorded_fraction) && typeof value.partition_complete === "boolean"
    && ["known", "partial", "unknown", "undefined_zero_denominator"].includes(String(value.state));
}
function projection(value: unknown, fixed: unknown, observationId: string): boolean {
  if (!mpRecord(value) || value.schema_version !== "pdos-pilot-result-projection-v1" || value.observation_id !== observationId
    || !mpSame(value.fixed, fixed) || !counts(value.counts) || value.received_at !== null || !mpRecord(value.metrics)) return false;
  const metrics = value.metrics;
  return rate(metrics.first_pass_yield) && rate(metrics.final_good_yield) && strings(metrics.warnings)
    && metrics.process_capability === "NOT_ASSESSED" && metrics.factory_qualification === "NOT_ASSESSED"
    && metrics.start_authorized === false && metrics.manufacturing_release === null && metrics.external_delivery_authorized === false;
}
function fixedScope(value: unknown, scope: ProjectPilotScope, pilotId: string, revision: number, recordScope: unknown): boolean {
  return mpRecord(value) && value.schema_version === "pdos-pilot-result-scope-v1" && mpRecord(value.scope)
    && mpUuid(value.scope.tenant_id) && value.scope.product_id === scope.productId && value.scope.project_id === scope.projectId
    && value.pilot_id === pilotId && value.pilot_revision === revision && text(value.purpose) && text(value.site)
    && text(value.original_timezone) && mpSame(value.yield_scope, recordScope) && mpRecord(value.cohort)
    && (value.cohort.population_count === null || count(value.cohort.population_count))
    && (value.cohort.fixed_input_count === null || count(value.cohort.fixed_input_count))
    && ["entire_lot", "fixed_sampled_subset"].includes(String(value.cohort.mode))
    && value.cohort.denominator_policy === "all_fixed_input_units" && text(value.cohort.statistics_basis_key)
    && (value.cohort.unit_refs === null || Array.isArray(value.cohort.unit_refs));
}
function completeItem(value: unknown, scope: ProjectPilotScope): value is NativePilotItem {
  if (!mpRecord(value) || value.external_delivery !== false || !nativeItem(value, scope.projectId) || !metadata(value.pilot, scope) || !mpRecord(value.pilot.material)
    || !mpRecord(value.pilot.material.pilot) || !mpSame(value.pilot.material.pilot.basis, value.pilot.details.basis)
    || !(value.pilot.statistics_basis === null || mpRecord(value.pilot.statistics_basis))) return false;
  const ids = new Set([value.pilot.id]);
  let previous: string | null = null;
  for (const row of value.observations) {
    const original: unknown = row;
    if (!metadata(original, scope)) return false;
    if (ids.has(row.id) || original.pilot_id !== value.pilot.id || original.pilot_revision_before !== row.revision - 1
      || original.previous_observation_id !== previous || row.record.previous_observation_id !== previous
      || row.record.expected_pilot_revision !== original.pilot_revision_before
      || (previous === null ? row.record.correction_reason !== null : !text(row.record.correction_reason))
      || !mpRecord(row.record.scope) || !mpSame(row.record.scope.basis, value.pilot.details.basis)
      || !instant(row.record.scope.window_start) || !instant(row.record.scope.window_end)
      || !mpRecord(row.record.observed) || !instant(row.record.observed.occurred_at) || !text(row.record.observed.original_timezone)
      || !(row.record.observed.effective_at === null || instant(row.record.observed.effective_at))
      || !(row.record.counts === null || counts(row.record.counts)) || !Array.isArray(row.record.units) || !Array.isArray(row.record.exceptions)) return false;
    if (!row.record.units.every(unit => ["pass", "fail", "unknown", "unprocessed"].includes(String(unit.first_result))
      && ["good", "scrap", "rework_pending", "undecided", "unprocessed"].includes(String(unit.final_state)) && count(unit.rework_cycles))) return false;
    if (row.fixed_scope !== null && !fixedScope(row.fixed_scope, scope, value.pilot.id, row.record.expected_pilot_revision, row.record.scope)) return false;
    // A retained fixed scope can legally have no projection while its window or resources remain unknown.
    if (row.projection !== null && (row.fixed_scope === null || !projection(row.projection, row.fixed_scope, row.id))) return false;
    ids.add(row.id); previous = row.id;
  }
  return value.current.latest_observation_id === previous;
}

/** The project list already contains full readable roots and observation chains. */
export async function readProjectPilots(api: ProjectPilotApi, scope: ProjectPilotScope, cursor?: string): Promise<ProjectPilotPage> {
  if (!mpRecord(scope) || ![scope.categoryId, scope.productId, scope.projectId, scope.principalId].every(mpUuid)
    || cursor !== undefined && !mpUuid(cursor)) invalid();
  const query = new URLSearchParams({ project_id: scope.projectId });
  if (cursor !== undefined) query.set("history_cursor", cursor);
  const value = await api<unknown>(`v1/categories/${scope.categoryId}/products/${scope.productId}/pilots?${query}`);
  if (!mpRecord(value) || value.schema_version !== "pdos-native-pilot-v1" || value.project_id !== scope.projectId
    || value.qualification !== "unknown" || value.manufacturing_release !== null || !Array.isArray(value.items)
    || !value.items.every(item => completeItem(item, scope)) || !(value.next_cursor === null || mpUuid(value.next_cursor))) invalid();
  const items = value.items as NativePilotItem[];
  if (new Set(items.map(item => item.pilot.id)).size !== items.length
    || value.next_cursor !== null && (value.next_cursor === cursor || items.at(-1)?.pilot.id !== value.next_cursor)) invalid();
  return { items, nextCursor: value.next_cursor };
}
