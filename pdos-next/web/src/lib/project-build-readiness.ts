import { mpRecord, mpRevision, mpUuid } from "../components/manufacturing-preparation/manufacturing-preparation-contract";
import type { ProjectBuildRecord, ProjectBuildScope } from "./project-build-summary";

type SavedReadiness = NonNullable<ProjectBuildRecord["readiness"]>;
type SavedResult = SavedReadiness["result"];
type Issue = SavedResult["demands"][number]["issues"][number];
export type ProjectBuildReadinessDemand = Omit<SavedResult["demands"][number], "material_id"> & {
  material_id: string | null; ancestry: string[];
};
export type ProjectBuildReadinessCoverageLine = {
  demand: ProjectBuildReadinessDemand; known_secured_quantity: string; known_potential_quantity: string;
  secured_gap: string | null; potential_gap: string | null; secured_ready: boolean | null; potential_ready: boolean | null;
  uses: Record<string, unknown>[]; issues: Issue[];
} & Record<string, unknown>;
export type ProjectBuildReadinessCoverage = {
  schema_version: "supply-coverage-result.v1"; algorithm: "fixed-bom-shared-pool.v1";
  input_sha256: string; input_snapshot: Record<string, unknown>;
  secured_ready: boolean | null; potential_ready: boolean | null; critical_secured_ready: boolean | null;
  candidate_policy: "critical-then-item-primary-then-alternate.v1"; potential_is_feasibility_proof: false;
  lines: ProjectBuildReadinessCoverageLine[]; pools: Record<string, unknown>[]; issues: Issue[]; notice: string;
} & Record<string, unknown>;
export type ProjectBuildReadinessResult = Omit<SavedResult, "demands" | "coverage"> & {
  schema_version: "build-readiness-result.v1"; algorithm: "fixed-build-readiness.v1";
  input_sha256: string; input_snapshot: Record<string, unknown>; notice: string;
  demands: ProjectBuildReadinessDemand[]; coverage: ProjectBuildReadinessCoverage | null;
};
export type ProjectBuildReadiness = Omit<SavedReadiness, "result"> & { result: ProjectBuildReadinessResult };

const text = (value: unknown): value is string => typeof value === "string" && !!value.trim();
const nullableText = (value: unknown) => value === null || text(value);
const hash = (value: unknown) => typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const instant = (value: unknown) => typeof value === "string"
  && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value)
  && Number.isFinite(Date.parse(value));
// Decimal JSON remains a string, including scientific notation and derived precision.
const decimal = (value: unknown) => typeof value === "string" && /^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$/.test(value);
const nullableDecimal = (value: unknown) => value === null || decimal(value);
const nullableBoolean = (value: unknown) => value === null || typeof value === "boolean";
const issues = (value: unknown): value is Issue[] => Array.isArray(value) && value.every(row => mpRecord(row)
  && text(row.code) && text(row.path) && text(row.message) && ["missing", "conflict", "restriction", "sensitivity"].includes(String(row.kind)));
function demand(value: unknown): value is ProjectBuildReadinessDemand {
  return mpRecord(value) && text(value.item_id) && nullableText(value.material_id) && nullableText(value.unit)
    && typeof value.critical === "boolean" && Array.isArray(value.ancestry) && value.ancestry.every(text)
    && nullableDecimal(value.quantity_per_product) && nullableDecimal(value.required_quantity) && issues(value.issues);
}
function coverage(value: unknown): value is ProjectBuildReadinessCoverage {
  return mpRecord(value) && value.schema_version === "supply-coverage-result.v1" && value.algorithm === "fixed-bom-shared-pool.v1"
    && hash(value.input_sha256) && mpRecord(value.input_snapshot) && text(value.notice)
    && [value.secured_ready, value.potential_ready, value.critical_secured_ready].every(nullableBoolean)
    && value.candidate_policy === "critical-then-item-primary-then-alternate.v1" && value.potential_is_feasibility_proof === false
    && Array.isArray(value.lines) && value.lines.every(line => mpRecord(line) && demand(line.demand)
      && decimal(line.known_secured_quantity) && decimal(line.known_potential_quantity)
      && nullableDecimal(line.secured_gap) && nullableDecimal(line.potential_gap)
      && nullableBoolean(line.secured_ready) && nullableBoolean(line.potential_ready)
      && Array.isArray(line.uses) && line.uses.every(mpRecord) && issues(line.issues))
    && Array.isArray(value.pools) && value.pools.every(mpRecord) && issues(value.issues);
}
function fixedRef(value: unknown): value is { id: string; revision: number } & Record<string, unknown> {
  return mpRecord(value) && mpUuid(value.id) && mpRevision(value.revision);
}
function sameRef(left: unknown, right: unknown): boolean {
  return fixedRef(left) && fixedRef(right) && left.id === right.id && left.revision === right.revision;
}
function invalid(): never {
  throw new Error("本轮保存的准备检查与所选 Build 固定版本无法核对。请刷新后重读；不能以当前配置补齐历史检查。");
}

/** Parse this already-read Build only; preserve its saved result rather than recomputing readiness or hashes. */
export function parseProjectBuildReadiness(build: ProjectBuildRecord, scope: ProjectBuildScope): ProjectBuildReadiness | null {
  if (!mpRecord(scope) || !mpUuid(scope.categoryId) || !mpUuid(scope.productId) || !mpUuid(scope.projectId)
    || !fixedRef(build) || build.project_id !== scope.projectId || !mpRevision(build.project_revision)
    || !fixedRef(build.engineering_configuration) || !fixedRef(build.manufacturing_configuration)) invalid();
  for (const configuration of [build.engineering_configuration, build.manufacturing_configuration]) {
    if (configuration.product_id !== undefined && configuration.product_id !== scope.productId) invalid();
  }
  const saved: unknown = build.readiness;
  if (saved === null) return null;
  if (!fixedRef(saved) || saved.status !== "blocked" || typeof saved.is_current !== "boolean" || !mpRecord(saved.result)) invalid();
  const result = saved.result, input = result.input_snapshot;
  if (result.schema_version !== "build-readiness-result.v1" || result.algorithm !== "fixed-build-readiness.v1"
    || !instant(result.as_of) || !hash(result.input_sha256) || result.build_id !== build.id || result.build_revision !== build.revision
    || !["unknown", "blocked"].includes(String(result.status)) || result.ready !== null || typeof result.hard_blocking !== "boolean"
    || !text(result.notice) || !mpRecord(input) || input.schema_version !== "build-readiness-input.v1" || input.as_of !== result.as_of
    || !sameRef(input.build, build) || !mpRecord(input.build) || !mpRecord(input.build.metadata)
    || input.build.metadata.project_id !== build.project_id || input.build.metadata.project_revision !== build.project_revision
    || !sameRef(input.engineering_configuration, build.engineering_configuration)
    || !sameRef(input.manufacturing_configuration, build.manufacturing_configuration)) invalid();
  const fixed: Record<string, unknown> = {
    build: input.build, engineering_configuration: input.engineering_configuration,
    manufacturing_configuration: input.manufacturing_configuration,
  };
  if (mpRecord(input.engineering_configuration) && input.engineering_configuration.bom !== null) {
    if (!fixedRef(input.engineering_configuration.bom)) invalid();
    fixed.bom = input.engineering_configuration.bom;
  }
  if (!Array.isArray(result.checks) || result.checks.length === 0 || !result.checks.every(check => mpRecord(check)
    && text(check.key) && text(check.label) && ["known", "unknown", "blocked"].includes(String(check.status))
    && typeof check.blocking === "boolean" && text(check.reason_code) && text(check.message) && text(check.recovery_action)
    && Array.isArray(check.source_refs) && check.source_refs.every(ref => mpRecord(ref) && text(ref.kind) && mpUuid(ref.id) && mpRevision(ref.revision)
      && (!(ref.kind in fixed) || sameRef(ref, fixed[ref.kind])))
    && (check.issues === undefined || issues(check.issues)))
    || new Set(result.checks.map(check => check.key)).size !== result.checks.length
    || !Array.isArray(result.demands) || !result.demands.every(demand)
    || !(result.coverage === null || coverage(result.coverage))) invalid();
  return saved as ProjectBuildReadiness;
}
