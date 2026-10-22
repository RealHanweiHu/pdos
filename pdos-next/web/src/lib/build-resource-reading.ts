import type { Build } from "@/lib/build-preparation-view";
import type { DefinitionReference } from "@/lib/product-view";
import type { SourceRead } from "@/lib/project-plan-view";
import { sameStart, startDecimal, startRecord, startText, startTime, startZone, type ScopeDraft } from "@/lib/build-start-view";

type Version = { id: string; revision: number } & Record<string, unknown>;
type Resource = Version & { kind: "equipment" | "fixture" | "person" | "line" | "tooling" };
export type ResourceInspectBody = {
  project_id: string; expected_build_revision: number; process: Version;
  execution: { purpose: string; quantity: string; unit: string; site: string; window: { start: string; finish: string; original_timezone: string } };
  operation_key: string;
};
export type ResourceReading = {
  state: "known" | "historical" | "unknown"; current: boolean; nature: "real" | "synthetic" | "unknown";
  fact: Version | null; fact_sha256: string | null; facts_revision: string;
  valid_until: string | null; fact_valid_until: string | null;
  resources: { resource: Resource; lifecycle: "active" | "withdrawn" | "unknown"; current: boolean; originals: DefinitionReference[]; acceptance: "unknown"; calibration: "unknown"; qualification: "unknown" }[];
  relations: { build: Version; process: Version; operation_key: string; resource: Resource; units: string; relation: "operation_uses_resource"; relation_source: Version & { kind: string; position: string }; relation_originals: DefinitionReference[] }[];
  required_source_read_set: SourceRead[]; gaps: string[];
  negative_enumeration_complete: false; execution_authorized: false;
};

export function resourceOperations(build: Build): { key: string; name: string }[] {
  const operations = build.manufacturing_configuration.operations;
  if (!Array.isArray(operations) || operations.some(row => !startRecord(row) || typeof row.key !== "string" || typeof row.name !== "string")) return [];
  return operations.map(row => ({ key: row.key as string, name: row.name as string }));
}

export function resourceInspectBody(build: Build, draft: ScopeDraft, operation: string): ResourceInspectBody {
  if (!resourceOperations(build).some(row => row.key === operation)) throw new Error("请选择此固定制造版的工序。");
  const start = startTime(draft.start), finish = startTime(draft.finish);
  if (!start || !finish || Date.parse(finish) <= Date.parse(start)) throw new Error("请先填写带时区的完整执行窗口。");
  const quantity = startDecimal(draft.quantity), unit = startText(draft.unit, "单位", 160);
  if (quantity !== startDecimal(build.planned_quantity) || unit !== build.unit) throw new Error("读取数量与单位须精确等于本轮固定计划。");
  return {
    project_id: build.project_id, expected_build_revision: build.revision,
    process: { id: build.manufacturing_configuration.id, revision: build.manufacturing_configuration.revision },
    execution: { purpose: startText(draft.purpose, "用途", 160), quantity, unit, site: startText(draft.site, "场地", 160), window: { start, finish, original_timezone: startZone(draft.timezone) } },
    operation_key: operation,
  };
}

const version = (value: unknown): value is Version => startRecord(value) && typeof value.id === "string" && !!value.id && Number.isSafeInteger(value.revision) && Number(value.revision) > 0;
const resource = (value: unknown): value is Resource => version(value) && startRecord(value) && ["equipment", "fixture", "person", "line", "tooling"].includes(String(value.kind));
const hash = (value: unknown) => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const timestamp = (value: unknown) => value === null || typeof value === "string" && !!startTime(value);
function sameExecution(value: unknown, expected: ResourceInspectBody["execution"]): boolean {
  if (!startRecord(value) || !startRecord(value.window)) return false;
  return ["purpose", "quantity", "unit", "site"].every(key => value[key] === expected[key as keyof typeof expected])
    && startTime(value.window.start) === expected.window.start && startTime(value.window.finish) === expected.window.finish
    && value.window.original_timezone === expected.window.original_timezone;
}

/** Checks the returned fixed reading; no field can enable a manufacturing action. */
export function resourceReading(value: unknown, productId: string, build: Build, expected: ResourceInspectBody): ResourceReading {
  const failure = () => { throw new Error("资源读回缺少完整固定范围或出处，请重新读取。"); };
  if (!startRecord(value) || !startRecord(value.request) || !startRecord(value.request.scope)) return failure();
  const request = value.request;
  if (!sameStart(request.build, { id: build.id, revision: build.revision }) || !sameStart(request.process, expected.process)
    || value.request.scope.product_id !== productId || value.request.scope.project_id !== build.project_id
    || request.operation_key !== expected.operation_key || request.resource != null || request.fact != null || !sameExecution(request.execution, expected.execution)
    || value.execution_authorized !== false || value.negative_enumeration_complete !== false
    || !["known", "historical", "unknown"].includes(String(value.state)) || typeof value.current !== "boolean"
    || !["real", "synthetic", "unknown"].includes(String(value.nature)) || !hash(value.facts_revision)
    || !timestamp(value.valid_until) || !timestamp(value.fact_valid_until)
    || !(value.fact === null || version(value.fact)) || !(value.fact_sha256 === null || hash(value.fact_sha256))
    || !Array.isArray(value.resources) || value.resources.length > 100 || !Array.isArray(value.relations) || value.relations.length > 100
    || !Array.isArray(value.required_source_read_set)
    || !Array.isArray(value.gaps) || value.gaps.some(gap => typeof gap !== "string")) return failure();
  const reads = new Map<string, number>();
  for (const read of value.required_source_read_set) {
    if (!startRecord(read) || typeof read.artifact_id !== "string" || !Number.isSafeInteger(read.expected_revision) || Number(read.expected_revision) < 1 || reads.has(read.artifact_id)) return failure();
    reads.set(read.artifact_id, Number(read.expected_revision));
  }
  const originals = (refs: unknown): boolean => Array.isArray(refs) && refs.length > 0 && refs.every(ref => startRecord(ref)
    && typeof ref.artifact_id === "string" && reads.get(ref.artifact_id) === ref.expected_revision
    && Number.isSafeInteger(ref.line) && Number(ref.line) > 0 && typeof ref.quote === "string" && !!ref.quote);
  const identities = new Set<string>();
  for (const row of value.resources) {
    if (!startRecord(row) || !resource(row.resource) || identities.has(row.resource.id) || typeof row.current !== "boolean"
      || !["active", "withdrawn", "unknown"].includes(String(row.lifecycle)) || !originals(row.originals)
      || row.acceptance !== "unknown" || row.calibration !== "unknown" || row.qualification !== "unknown") return failure();
    identities.add(row.resource.id);
  }
  for (const relation of value.relations) {
    if (!startRecord(relation) || !resource(relation.resource) || !value.resources.some(row => startRecord(row) && sameStart(row.resource, relation.resource))
      || !sameStart(relation.build, request.build) || !sameStart(relation.process, expected.process) || relation.operation_key !== expected.operation_key
      || relation.relation !== "operation_uses_resource" || typeof relation.units !== "string" || !relation.units
      || !version(relation.relation_source) || !startRecord(relation.relation_source) || relation.relation_source.kind !== "domain"
      || !version(value.fact) || relation.relation_source.id !== value.fact.id || relation.relation_source.revision !== value.fact.revision
      || typeof relation.relation_source.position !== "string" || !relation.relation_source.position || !originals(relation.relation_originals)) return failure();
  }
  if (value.current !== (value.relations.length > 0) || (value.state === "known") !== (value.relations.length > 0)) return failure();
  return value as unknown as ResourceReading;
}
