import { readProjectBuilds, type ProjectBuildApi, type ProjectBuildRecord, type ProjectBuildScope, type ProjectBuildSourceStatus } from "./project-build-summary";

export type ProjectBuildOutputRef = { id: string; revision: number };
export type ProjectBuildOutputConfigurationRef = ProjectBuildOutputRef & { name: string };
export type ProjectBuildOutputRow = ProjectBuildOutputRef & { createdAt: string; sourceStatus: ProjectBuildSourceStatus };
export type ProjectBuildActualConfiguration = ProjectBuildOutputRow & {
  observedAt: string;
  plannedEngineering: ProjectBuildOutputConfigurationRef;
  plannedManufacturing: ProjectBuildOutputConfigurationRef;
  actualEngineering: ProjectBuildOutputConfigurationRef;
  actualManufacturing: ProjectBuildOutputConfigurationRef;
};
export type ProjectBuildOutputLot = ProjectBuildOutputRow & {
  lotLabel: string; actualConfiguration: ProjectBuildOutputRef;
  observedUnitCount: number; identifiedCount: number; remainingUnitCount: number;
  buildObservedUnitCount: number; unit: string;
  observation: { system: string; externalId: string; nature: "real" | "synthetic"; occurredAt: string; receivedAt: string };
};
export type ProjectBuildSampleAllocation = ProjectBuildOutputRow & {
  lotId: string; actualConfigurationId: string; unitCount: number; sampleIds: string[];
};
export type ProjectBuildOutputSample = ProjectBuildOutputRow & {
  label: string; lotId: string; allocationId: string; actualConfiguration: ProjectBuildOutputRef;
  operationKey: string | null; cavity: string | null; custodianId: string | null;
  custodianLabel: string | null; location: string | null; destination: string | null;
  recordedAvailability: "unknown" | "hold"; observationNature: "real" | "synthetic";
};
export type ProjectBuildOutput = {
  build: ProjectBuildRecord;
  actualConfigurations: ProjectBuildActualConfiguration[];
  lots: ProjectBuildOutputLot[];
  allocations: ProjectBuildSampleAllocation[];
  samples: ProjectBuildOutputSample[];
  /** These describe the product-wide response, never the selected Build's total. */
  productUnavailableCount: number;
  productHasMore: boolean;
};

type RawRow = Record<string, unknown> & {
  id: string; revision: number; product_id: string; project_id: string; build_id: string;
  build_revision: number; created_at: string; source_status: ProjectBuildSourceStatus;
};
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const count = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) >= 0;
const text = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const nullableText = (value: unknown): value is string | null => value === null || typeof value === "string";
const nullableId = (value: unknown): value is string | null => value === null || uuid(value);
const instant = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const sourceStatus = (value: unknown): value is ProjectBuildSourceStatus => value === "current" || value === "needs_recheck";
const nature = (value: unknown): value is "real" | "synthetic" => value === "real" || value === "synthetic";

function invalid(): never {
  throw new Error("所选轮次的实物登记范围或固定链无法核对，请刷新；不能用其他项目、轮次或计划资料补齐。");
}
function ref(value: unknown): value is ProjectBuildOutputRef & Record<string, unknown> {
  return record(value) && uuid(value.id) && positive(value.revision);
}
function sameRef(a: ProjectBuildOutputRef, b: ProjectBuildOutputRef): boolean { return a.id === b.id && a.revision === b.revision; }
function configuration(value: unknown): ProjectBuildOutputConfigurationRef {
  if (!ref(value) || !record(value) || !text(value.name)) invalid();
  return { id: value.id, revision: value.revision, name: value.name };
}
function base(row: RawRow): ProjectBuildOutputRow {
  return { id: row.id, revision: row.revision, createdAt: row.created_at, sourceStatus: row.source_status };
}
function rows(value: unknown, scope: ProjectBuildScope, status: string): RawRow[] {
  if (!Array.isArray(value)) invalid();
  const result: RawRow[] = [];
  for (const row of value) {
    if (!record(row) || !uuid(row.id) || !positive(row.revision) || row.product_id !== scope.productId
      || !uuid(row.project_id) || !uuid(row.build_id) || !positive(row.build_revision)
      || row.status !== status || !instant(row.created_at) || !sourceStatus(row.source_status)) invalid();
    result.push(row as RawRow);
  }
  if (new Set(result.map(row => row.id)).size !== result.length) invalid();
  return result;
}
function selected(rows: RawRow[], scope: ProjectBuildScope, build: ProjectBuildRecord): RawRow[] {
  return rows.filter(row => {
    if (row.build_id !== build.id) return false;
    if (row.project_id !== scope.projectId || row.build_revision !== build.revision) invalid();
    return true;
  });
}

function output(value: unknown, scope: ProjectBuildScope, build: ProjectBuildRecord): ProjectBuildOutput {
  if (!record(value) || !count(value.unavailable_count) || typeof value.has_more !== "boolean") invalid();
  const allActuals = rows(value.actual_configurations, scope, "recorded");
  const allLots = rows(value.lots, scope, "observed");
  const allAllocations = rows(value.allocations, scope, "identified");
  const allSamples = rows(value.samples, scope, "identified");
  const actuals = selected(allActuals, scope, build), lotRows = selected(allLots, scope, build);
  const allocationRows = selected(allAllocations, scope, build), sampleRows = selected(allSamples, scope, build);

  const actualConfigurations = actuals.map((row): ProjectBuildActualConfiguration => {
    if (!record(row.planned) || !record(row.actual) || !instant(row.observed_at)) invalid();
    const plannedEngineering = configuration(row.planned.engineering_configuration);
    const plannedManufacturing = configuration(row.planned.manufacturing_configuration);
    const actualEngineering = configuration(row.actual.engineering_configuration);
    const actualManufacturing = configuration(row.actual.manufacturing_configuration);
    if (!sameRef(plannedEngineering, build.engineering_configuration) || !sameRef(plannedManufacturing, build.manufacturing_configuration)
      || row.planned_engineering_configuration_id !== plannedEngineering.id || row.planned_manufacturing_configuration_id !== plannedManufacturing.id
      || row.actual_engineering_configuration_id !== actualEngineering.id || row.actual_engineering_revision !== actualEngineering.revision
      || row.actual_manufacturing_configuration_id !== actualManufacturing.id || row.actual_manufacturing_revision !== actualManufacturing.revision
      || !record(row.actual.manufacturing_configuration) || row.actual.manufacturing_configuration.engineering_configuration_id !== actualEngineering.id) invalid();
    return { ...base(row), observedAt: row.observed_at, plannedEngineering, plannedManufacturing, actualEngineering, actualManufacturing };
  });
  const actualById = new Map(actualConfigurations.map(row => [row.id, row]));
  const lots = lotRows.map((row): ProjectBuildOutputLot => {
    if (!uuid(row.actual_configuration_id) || !positive(row.actual_configuration_revision) || !text(row.lot_label)
      || !positive(row.observed_unit_count) || !count(row.identified_count) || !count(row.remaining_unit_count)
      || row.identified_count > row.observed_unit_count || row.remaining_unit_count !== row.observed_unit_count - row.identified_count
      || !positive(row.build_observed_unit_count) || row.build_observed_unit_count < row.observed_unit_count || row.unit !== build.unit
      || !record(row.observation) || !text(row.observation.system) || !text(row.observation.external_id)
      || !nature(row.observation.nature) || !instant(row.observation.occurred_at) || !instant(row.observation.received_at)) invalid();
    const actual = actualById.get(row.actual_configuration_id);
    if (!actual || actual.revision !== row.actual_configuration_revision) invalid();
    return { ...base(row), lotLabel: row.lot_label, actualConfiguration: { id: actual.id, revision: actual.revision },
      observedUnitCount: row.observed_unit_count, identifiedCount: row.identified_count, remainingUnitCount: row.remaining_unit_count,
      buildObservedUnitCount: row.build_observed_unit_count, unit: row.unit,
      observation: { system: row.observation.system, externalId: row.observation.external_id, nature: row.observation.nature,
        occurredAt: row.observation.occurred_at, receivedAt: row.observation.received_at } };
  });
  const lotById = new Map(lots.map(row => [row.id, row]));
  const allocations = allocationRows.map((row): ProjectBuildSampleAllocation => {
    if (!uuid(row.lot_id) || !uuid(row.actual_configuration_id) || !positive(row.unit_count)
      || !Array.isArray(row.sample_ids) || !row.sample_ids.every(uuid) || new Set(row.sample_ids).size !== row.sample_ids.length) invalid();
    const lot = lotById.get(row.lot_id);
    if (!lot || row.actual_configuration_id !== lot.actualConfiguration.id) invalid();
    // sample_ids and unit_count are server facts; RLS may hide individual rows.
    for (const id of row.sample_ids) {
      const sample = allSamples.find(value => value.id === id);
      if (sample && (sample.build_id !== build.id || sample.project_id !== scope.projectId
        || sample.build_revision !== build.revision || sample.allocation_id !== row.id || sample.lot_id !== lot.id)) invalid();
    }
    return { ...base(row), lotId: row.lot_id, actualConfigurationId: row.actual_configuration_id,
      unitCount: row.unit_count, sampleIds: [...row.sample_ids] };
  });
  const allocationById = new Map(allocations.map(row => [row.id, row]));
  const samples = sampleRows.map((row): ProjectBuildOutputSample => {
    if (!text(row.label) || !uuid(row.lot_id) || !uuid(row.allocation_id) || !uuid(row.actual_configuration_id)
      || !positive(row.actual_configuration_revision) || !nullableText(row.operation_key) || !nullableText(row.cavity)
      || !nullableId(row.custodian_id) || !nullableText(row.custodian_label) || !nullableText(row.location) || !nullableText(row.destination)
      || !(row.availability === "unknown" || row.availability === "hold") || !nature(row.observation_nature)) invalid();
    const lot = lotById.get(row.lot_id), allocation = allocationById.get(row.allocation_id);
    if (!lot || !allocation || allocation.lotId !== lot.id || !allocation.sampleIds.includes(row.id)
      || row.actual_configuration_id !== lot.actualConfiguration.id || row.actual_configuration_revision !== lot.actualConfiguration.revision
      || allocation.actualConfigurationId !== row.actual_configuration_id || row.observation_nature !== lot.observation.nature) invalid();
    return { ...base(row), label: row.label, lotId: row.lot_id, allocationId: row.allocation_id,
      actualConfiguration: { id: row.actual_configuration_id, revision: row.actual_configuration_revision },
      operationKey: row.operation_key, cavity: row.cavity, custodianId: row.custodian_id, custodianLabel: row.custodian_label,
      location: row.location, destination: row.destination, recordedAvailability: row.availability, observationNature: row.observation_nature };
  });
  return { build, actualConfigurations, lots, allocations, samples, productUnavailableCount: value.unavailable_count, productHasMore: value.has_more };
}

/** Explicit selection, a fresh project Build check, then the existing product-wide GET. */
export async function readProjectBuildOutput(api: ProjectBuildApi, scope: ProjectBuildScope, selectedBuild: ProjectBuildRecord): Promise<ProjectBuildOutput> {
  if (!uuid(scope.categoryId) || !uuid(scope.productId) || !uuid(scope.projectId)
    || !record(selectedBuild) || !uuid(selectedBuild.id) || !positive(selectedBuild.revision) || selectedBuild.project_id !== scope.projectId
    || !ref(selectedBuild.engineering_configuration) || !ref(selectedBuild.manufacturing_configuration)) invalid();
  const latest = await readProjectBuilds(api, scope), build = latest.items.find(row => row.id === selectedBuild.id);
  if (!build || build.revision !== selectedBuild.revision || build.project_revision !== selectedBuild.project_revision
    || !sameRef(build.engineering_configuration, selectedBuild.engineering_configuration)
    || !sameRef(build.manufacturing_configuration, selectedBuild.manufacturing_configuration)) invalid();
  const value = await api<unknown>(`v1/categories/${scope.categoryId}/products/${scope.productId}/build-execution`);
  return output(value, scope, build);
}
