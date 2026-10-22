import { readProjectBuilds, type ProjectBuildApi, type ProjectBuildRecord, type ProjectBuildScope, type ProjectBuildSourceStatus } from "./project-build-summary";

export type ProjectBuildEngineeringSource = { artifact_id: string; expected_revision: number; line: number; quote: string };
export type ProjectBuildEngineeringRead = { artifact_id: string; expected_revision: number };
export type ProjectBuildEngineeringExternalReference = {
  system: string; external_id: string; revision: string | null; as_of: string | null;
  content_sha256: string | null; basis: ProjectBuildEngineeringSource | null;
};
export type ProjectBuildEngineeringSnapshot = {
  id: string; product_id: string; revision: number; name: string; status: "draft";
  visibility: "private" | "category" | "audience"; owner_id: string; created_at: string;
  sources: ProjectBuildEngineeringSource[]; required_source_read_set: ProjectBuildEngineeringRead[];
  source_status: ProjectBuildSourceStatus;
};
type Series = { series_id: string; previous_id: string | null; expected_previous_revision: number | null; reason: string };
export type ProjectBuildEngineeringPart = ProjectBuildEngineeringSnapshot & {
  internal_number: string | null; erp_number: string | null; customer_number: string | null; mapping_version: string | null;
  external_design_refs: ProjectBuildEngineeringExternalReference[]; external_verification: "not_checked"; mapping_status: "declared" | "unknown";
};
export type ProjectBuildEngineeringBomLine = {
  key: string; part_id: string; expected_part_revision: number; part: ProjectBuildEngineeringPart;
  quantity: string | null; unit: string | null; loss_rate: string | null; critical: boolean; notes: string | null;
};
export type ProjectBuildEngineeringBom = ProjectBuildEngineeringSnapshot & Series & { lines: ProjectBuildEngineeringBomLine[] };
export type ProjectBuildEngineeringDefinition = {
  id: string; revision: number; title: string; status: "draft" | "published";
  visibility: "private" | "category" | "audience"; source_status: ProjectBuildSourceStatus;
};
export type ProjectBuildEngineeringConfiguration = ProjectBuildEngineeringSnapshot & Series & {
  definition_id: string; definition_revision: number; definition: ProjectBuildEngineeringDefinition;
  bom_id: string; bom_revision: number; bom: ProjectBuildEngineeringBom;
  design_versions: { mechanical: ProjectBuildEngineeringExternalReference | null; electronic: ProjectBuildEngineeringExternalReference | null; firmware: ProjectBuildEngineeringExternalReference | null };
  external_verification: "not_checked";
};
export type ProjectBuildEngineering = {
  build: ProjectBuildRecord; configuration: ProjectBuildEngineeringConfiguration;
  /** Coverage of the fresh project Build response, not a configuration or BOM total. */
  unavailableCount: number; hasMore: boolean;
};

type Row = Record<string, unknown>;
const record = (value: unknown): value is Row => value !== null && typeof value === "object" && !Array.isArray(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}$/i.test(value);
const positive = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const text = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const nullableText = (value: unknown): value is string | null => value === null || text(value);
const instant = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
const visibility = (value: unknown) => value === "private" || value === "category" || value === "audience";
const sourceStatus = (value: unknown) => value === "current" || value === "needs_recheck";
function decimal(value: unknown, allowZero = true): value is string {
  if (typeof value !== "string" || value.length > 128) return false;
  const match = /^\+?(\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.exec(value);
  // Test the mantissa without binary conversion; an exponent cannot make zero positive.
  return !!match && (allowZero || /[1-9]/.test(match[1]));
}
const sameRef = (a: { id: string; revision: number }, b: { id: string; revision: number }) => a.id === b.id && a.revision === b.revision;
function invalid(): never { throw new Error("所选 Build 的固定工程配置、定义、BOM 或物料版本无法核对，请刷新后重新选择。不能用其他轮次或最新版本补齐。"); }
function source(value: unknown): value is ProjectBuildEngineeringSource {
  return record(value) && uuid(value.artifact_id) && positive(value.expected_revision) && positive(value.line) && text(value.quote);
}
function external(value: unknown): value is ProjectBuildEngineeringExternalReference {
  return record(value) && text(value.system) && text(value.external_id) && nullableText(value.revision)
    && (value.as_of === null || instant(value.as_of))
    && (value.content_sha256 === null || typeof value.content_sha256 === "string" && /^[a-f0-9]{64}$/.test(value.content_sha256))
    && (value.basis === null || source(value.basis))
    && (value.basis !== null || value.revision !== null && value.as_of !== null && value.content_sha256 !== null);
}
function snapshot(value: unknown, productId: string): value is ProjectBuildEngineeringSnapshot & Row {
  if (!record(value) || !uuid(value.id) || value.product_id !== productId || !positive(value.revision) || !text(value.name)
    || value.status !== "draft" || !visibility(value.visibility) || !uuid(value.owner_id) || !instant(value.created_at) || !sourceStatus(value.source_status)
    || !Array.isArray(value.sources) || !value.sources.every(source) || !Array.isArray(value.required_source_read_set)
    || !value.required_source_read_set.every(ref => record(ref) && uuid(ref.artifact_id) && positive(ref.expected_revision))) return false;
  const reads = value.required_source_read_set as ProjectBuildEngineeringRead[];
  return new Set(reads.map(ref => ref.artifact_id)).size === reads.length
    && value.sources.every(ref => reads.some(read => read.artifact_id === ref.artifact_id && read.expected_revision === ref.expected_revision));
}
function series(value: ProjectBuildEngineeringSnapshot & Row): boolean {
  return uuid(value.series_id) && text(value.reason) && (value.previous_id === null
    ? value.expected_previous_revision === null && value.revision === 1 && value.series_id === value.id
    : uuid(value.previous_id) && value.previous_id !== value.id && positive(value.expected_previous_revision) && value.revision === value.expected_previous_revision + 1);
}
function part(value: unknown, productId: string): value is ProjectBuildEngineeringPart {
  return snapshot(value, productId) && [value.internal_number, value.erp_number, value.customer_number, value.mapping_version].every(nullableText)
    && Array.isArray(value.external_design_refs) && value.external_design_refs.every(external)
    && value.external_verification === "not_checked" && value.mapping_status === (value.mapping_version === null ? "unknown" : "declared");
}
function bom(value: unknown, productId: string): value is ProjectBuildEngineeringBom {
  if (!snapshot(value, productId) || !series(value) || !Array.isArray(value.lines) || value.lines.length === 0) return false;
  return value.lines.every(line => record(line) && text(line.key) && uuid(line.part_id) && positive(line.expected_part_revision)
    && part(line.part, productId) && line.part.id === line.part_id && line.part.revision === line.expected_part_revision
    && (line.quantity === null || decimal(line.quantity, false)) && nullableText(line.unit)
    && (line.quantity === null || text(line.unit)) && (line.loss_rate === null || decimal(line.loss_rate))
    && typeof line.critical === "boolean" && nullableText(line.notes)) && new Set(value.lines.map(line => line.key)).size === value.lines.length;
}
function configuration(value: unknown, productId: string): value is ProjectBuildEngineeringConfiguration {
  if (!snapshot(value, productId) || !series(value) || !uuid(value.definition_id) || !positive(value.definition_revision)
    || !record(value.definition) || value.definition.id !== value.definition_id || value.definition.revision !== value.definition_revision
    || !text(value.definition.title) || !["draft", "published"].includes(String(value.definition.status))
    || !visibility(value.definition.visibility) || !sourceStatus(value.definition.source_status)
    || !uuid(value.bom_id) || !positive(value.bom_revision) || !bom(value.bom, productId)
    || value.bom.id !== value.bom_id || value.bom.revision !== value.bom_revision
    || !record(value.design_versions) || value.external_verification !== "not_checked") return false;
  const designs = value.design_versions;
  return ["mechanical", "electronic", "firmware"].every(kind => designs[kind] === null || external(designs[kind]));
}

/** The only GET rechecks this exact project Build; no series-head or external-system lookup. */
export async function readProjectBuildEngineering(api: ProjectBuildApi, scope: ProjectBuildScope, selectedBuild: ProjectBuildRecord): Promise<ProjectBuildEngineering> {
  if (!record(scope) || !uuid(scope.categoryId) || !uuid(scope.productId) || !uuid(scope.projectId)
    || !record(selectedBuild) || !uuid(selectedBuild.id) || !positive(selectedBuild.revision) || selectedBuild.project_id !== scope.projectId
    || !configuration(selectedBuild.engineering_configuration, scope.productId) || !record(selectedBuild.manufacturing_configuration)
    || !uuid(selectedBuild.manufacturing_configuration.id) || !positive(selectedBuild.manufacturing_configuration.revision)) invalid();
  const page = await readProjectBuilds(api, scope), build = page.items.find(row => row.id === selectedBuild.id);
  if (!build || build.revision !== selectedBuild.revision || build.project_revision !== selectedBuild.project_revision
    || !configuration(build.engineering_configuration, scope.productId)
    || !sameRef(build.engineering_configuration, selectedBuild.engineering_configuration)
    || !sameRef(build.manufacturing_configuration, selectedBuild.manufacturing_configuration)
    || build.engineering_configuration.definition_id !== selectedBuild.engineering_configuration.definition_id
    || build.engineering_configuration.definition_revision !== selectedBuild.engineering_configuration.definition_revision
    || build.engineering_configuration.bom_id !== selectedBuild.engineering_configuration.bom_id
    || build.engineering_configuration.bom_revision !== selectedBuild.engineering_configuration.bom_revision) invalid();
  return { build, configuration: build.engineering_configuration, unavailableCount: page.unavailableCount, hasMore: page.hasMore };
}
