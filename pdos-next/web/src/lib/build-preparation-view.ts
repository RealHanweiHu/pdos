import type { DefinitionReference, DefinitionSource } from "@/lib/product-view";
import type { Project, SourceRead } from "@/lib/project-plan-view";

export type PreparationApi = <T>(path: string, body?: unknown) => Promise<T>;
export type Visibility = "private" | "category" | "audience";
export type ConfigurationBase = {
  id: string; revision: number; name: string; status: "draft"; visibility: Visibility;
  owner_id: string; required_source_read_set: SourceRead[]; source_status?: string;
  sources?: DefinitionReference[]; created_at?: string; series_id?: string; previous_id?: string | null;
};
export type ExternalReference = { system: string; external_id: string; revision: string | null; as_of: string | null; content_sha256: string | null; basis: DefinitionReference | null };
export type PartInput = { name: string; internal_number: string | null; erp_number: string | null; customer_number: string | null; mapping_version: string | null; external_design_refs: ExternalReference[] };
export type BomLineInput = { key: string; part_id: string | null; expected_part_revision: number | null; part: PartInput | null; quantity: string | null; unit: string | null; loss_rate: string | null; critical: boolean; notes: string | null };
export type BomLine = Omit<BomLineInput, "part"> & { part: PartInput & ConfigurationBase };
export type BomConfiguration = ConfigurationBase & { lines: BomLine[] } & Record<string, unknown>;
export type EngineeringConfiguration = ConfigurationBase & { definition_id: string; bom_id: string; bom: BomConfiguration; design_versions: { mechanical: ExternalReference | null; electronic: ExternalReference | null; firmware: ExternalReference | null } } & Record<string, unknown>;
export type ManufacturingConfiguration = ConfigurationBase & { engineering_configuration_id: string; site: string | null; line: string | null; operations: OperationInput[] } & Record<string, unknown>;
export type ConfigurationList = {
  boms: BomConfiguration[]; engineering: EngineeringConfiguration[]; processes: ManufacturingConfiguration[];
  unavailable_count: number; has_more: boolean;
};
export type RevisionPayload = { name: string; visibility: Visibility; previous_id: string | null; expected_previous_revision: number | null; reason: string; sources: DefinitionReference[]; confirmation_token?: string | null };
export type BomPayload = RevisionPayload & { lines: BomLineInput[] };
export type EngineeringPayload = RevisionPayload & { definition_id: string; expected_definition_revision: number; bom_id: string; expected_bom_revision: number; mechanical: ExternalReference | null; electronic: ExternalReference | null; firmware: ExternalReference | null };
export type ResourceInput = { kind: "person" | "equipment" | "tooling" | "station" | "other"; name: string; external_id: string | null; qualification: string | null };
export type OperationInput = { key: string; name: string; kind: "assembly" | "inspection" | "test" | "packaging" | "other"; depends_on: string[]; bom_line_keys: string[]; sop: ExternalReference | null; resource_requirements: ResourceInput[]; cycle_time_minutes: string | null; acceptance_criterion: string | null; notes: string | null };
export type ProcessPayload = RevisionPayload & { engineering_configuration_id: string; expected_engineering_revision: number; site: string | null; line: string | null; operations: OperationInput[] };
export type BuildType = "prototype" | "tool_trial" | "pilot";
export type BuildPayload = {
  project_id: string; expected_project_revision: number; engineering_configuration_id: string;
  manufacturing_configuration_id: string; name: string; type: BuildType; purpose: string;
  planned_quantity: string; unit: string; planned_start: string | null; planned_end: string | null;
  verification_objectives: string; disposition_plan: string; previous_build_id: string | null;
  confirmation_token?: string | null;
};
export type ReadinessPayload = { build_id: string; expected_build_revision: number };
export type ReadinessResult = {
  schema_version: string; algorithm: string; as_of: string; build_id: string; build_revision: number;
  status: "unknown" | "blocked"; ready: null; hard_blocking: boolean;
  checks: { key: string; label: string; status: "known" | "unknown" | "blocked"; blocking: boolean; reason_code: string; message: string; source_refs: { kind: string; id: string; revision: number }[]; recovery_action: string }[];
  demands: { item_id: string; material_id: string; unit: string | null; critical: boolean; quantity_per_product: string | null; required_quantity: string | null; issues: { code: string; path: string; message: string; kind: string }[] }[];
  coverage: Record<string, unknown> | null;
};
export type Build = Omit<BuildPayload, "expected_project_revision" | "engineering_configuration_id" | "manufacturing_configuration_id" | "confirmation_token"> & {
  id: string; revision: number; status: "planned"; owner_id: string; visibility: Visibility; project_name: string;
  engineering_configuration: ConfigurationBase & Record<string, unknown>;
  manufacturing_configuration: ConfigurationBase & Record<string, unknown>;
  required_source_read_set: SourceRead[]; source_status?: string;
  readiness: null | { id: string; revision: number; status: "blocked"; is_current: boolean; result: ReadinessResult };
  created_at: string;
};
export type BuildList = { items: Build[]; unavailable_count: number; has_more: boolean };
export type PreparationOperation = "engineering.bom.revise" | "engineering.configuration.create" | "npi.process.revise" | "build.create" | "build.readiness.compute";
export type PreparationCommand = {
  command_id: string; idempotency_key: string; operation: PreparationOperation; product_id: string;
  expected_revision: number; source_read_set: SourceRead[]; payload: Record<string, unknown> | BuildPayload | ReadinessPayload;
};
export type PreparationPreview = {
  command: PreparationCommand; confirmation_token: string; expires_at: string;
  review: Record<string, unknown> & { effect: string; operation?: PreparationOperation };
};
export type WaitingPreparation = { stage: "preview" | "execute"; command: PreparationCommand };
export type BuildDraft = {
  projectId: string; engineeringId: string; manufacturingId: string; name: string; type: BuildType;
  purpose: string; quantity: string; unit: string; startUtc: string; endUtc: string;
  objectives: string; disposition: string; previousId: string;
};
export type PreparationDraft = {
  build: BuildDraft;
  bom: BomDraft;
  engineering: EngineeringDraft;
  process: ProcessDraft;
  references: DefinitionReference[];
};
export type ExternalDraft = { system: string; externalId: string; revision: string; asOfUtc: string; asOfOriginal?: string; hash: string; referenceKey: string };
export type BomLineDraft = { key: string; partId: string; partRevision: number | null; name: string; internal: string; erp: string; customer: string; mappingVersion: string; quantity: string; unit: string; loss: string; critical: boolean; notes: string; designRefs: ExternalDraft[] };
export type RevisionDraft = { name: string; previousId: string; visibility: Visibility; reason: string };
export type BomDraft = RevisionDraft & { lines: BomLineDraft[] };
export type EngineeringDraft = RevisionDraft & { definitionId: string; bomId: string; designs: { mechanical: ExternalDraft; electronic: ExternalDraft; firmware: ExternalDraft } };
export type OperationDraft = { key: string; name: string; kind: OperationInput["kind"]; dependencies: string; bomLineKeys: string[]; cycle: string; acceptance: string; notes: string; sop: ExternalDraft; resources: { kind: ResourceInput["kind"]; name: string; externalId: string; qualification: string }[] };
export type ProcessDraft = RevisionDraft & { engineeringId: string; site: string; line: string; operations: OperationDraft[] };

export const buildTypeNames: Record<BuildType, string> = { prototype: "原型验证", tool_trial: "试模 / 工装试验", pilot: "试产验证" };
export const preparationNames: Record<PreparationOperation, string> = {
  "engineering.bom.revise": "BOM 草稿版本", "engineering.configuration.create": "工程配置草稿",
  "npi.process.revise": "制造配置草稿版本", "build.create": "Build 计划", "build.readiness.compute": "Build 准备缺项计算",
};
export const preparationReceiptTypes: Record<PreparationOperation, string> = {
  "engineering.bom.revise": "bom_revision", "engineering.configuration.create": "engineering_configuration",
  "npi.process.revise": "process_revision", "build.create": "build", "build.readiness.compute": "build_readiness",
};
export function blankPreparation(purpose: string): PreparationDraft {
  return {
    build: { projectId: "", engineeringId: "", manufacturingId: "", name: "", type: "prototype", purpose, quantity: "", unit: "件", startUtc: "", endUtc: "", objectives: "", disposition: "", previousId: "" },
    bom: { name: "", previousId: "", visibility: "private", reason: "", lines: [blankBomLine(1)] },
    engineering: { name: "", previousId: "", visibility: "private", reason: "", definitionId: "", bomId: "", designs: { mechanical: blankExternal(), electronic: blankExternal(), firmware: blankExternal() } },
    process: { name: "", previousId: "", visibility: "private", reason: "", engineeringId: "", site: "", line: "", operations: [blankOperation(1)] }, references: [],
  };
}
export function blankExternal(): ExternalDraft { return { system: "", externalId: "", revision: "", asOfUtc: "", hash: "", referenceKey: "" }; }
export function blankBomLine(index: number): BomLineDraft { return { key: `line-${index}`, partId: "", partRevision: null, name: "", internal: "", erp: "", customer: "", mappingVersion: "", quantity: "", unit: "", loss: "", critical: false, notes: "", designRefs: [] }; }
export function blankOperation(index: number): OperationDraft { return { key: `operation-${index}`, name: "", kind: "assembly", dependencies: "", bomLineKeys: [], cycle: "", acceptance: "", notes: "", sop: blankExternal(), resources: [] }; }
export function externalDraft(value: ExternalReference | null): ExternalDraft { return value ? { system: value.system, externalId: value.external_id, revision: value.revision ?? "", asOfUtc: value.as_of ? new Date(value.as_of).toISOString().slice(0, -1) : "", asOfOriginal: value.as_of ?? "", hash: value.content_sha256 ?? "", referenceKey: value.basis ? JSON.stringify([value.basis.artifact_id, value.basis.expected_revision, value.basis.line, value.basis.quote]) : "" } : blankExternal(); }
function isRecord(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
export function restorePreparation(value: unknown, productId: string): { draft: PreparationDraft; pending: WaitingPreparation | null } | null {
  if (!isRecord(value) || !isRecord(value.draft) || !isRecord(value.draft.build)) return null;
  const draft = value.draft, build = draft.build as Record<string, unknown>;
  if (!["projectId", "engineeringId", "manufacturingId", "name", "purpose", "quantity", "unit", "startUtc", "endUtc", "objectives", "disposition", "previousId"].every(key => typeof build[key] === "string") || !["prototype", "tool_trial", "pilot"].includes(String(build.type))) return null;
  if (![draft.bom, draft.engineering, draft.process].every(isRecord) || !Array.isArray(draft.references) || !draft.references.every(ref => isRecord(ref) && typeof ref.artifact_id === "string" && Number.isInteger(ref.expected_revision) && Number(ref.expected_revision) > 0 && Number.isInteger(ref.line) && Number(ref.line) > 0 && typeof ref.quote === "string")) return null;
  const revisions = [draft.bom, draft.engineering, draft.process] as Record<string, unknown>[];
  if (!revisions.every(revision => ["name", "previousId", "reason"].every(key => typeof revision[key] === "string") && ["private", "category", "audience"].includes(String(revision.visibility)))) return null;
  const bom = draft.bom as Record<string, unknown>, process = draft.process as Record<string, unknown>, engineering = draft.engineering as Record<string, unknown>;
  if (typeof engineering.definitionId !== "string" || typeof engineering.bomId !== "string" || !isRecord(engineering.designs) || !["mechanical", "electronic", "firmware"].every(key => validExternal((engineering.designs as Record<string, unknown>)[key])) || !["engineeringId", "site", "line"].every(key => typeof process[key] === "string")) return null;
  if (!Array.isArray(bom.lines) || !bom.lines.length || bom.lines.length > 200 || !bom.lines.every(line => isRecord(line) && ["key", "partId", "name", "internal", "erp", "customer", "mappingVersion", "quantity", "unit", "loss", "notes"].every(key => typeof line[key] === "string") && typeof line.critical === "boolean" && Array.isArray(line.designRefs) && line.designRefs.every(validExternal))) return null;
  if (!Array.isArray(process.operations) || !process.operations.length || process.operations.length > 200 || !process.operations.every(operation => isRecord(operation) && ["key", "name", "dependencies", "cycle", "acceptance", "notes"].every(key => typeof operation[key] === "string") && Array.isArray(operation.bomLineKeys) && operation.bomLineKeys.every(key => typeof key === "string") && ["assembly", "inspection", "test", "packaging", "other"].includes(String(operation.kind)) && validExternal(operation.sop) && Array.isArray(operation.resources) && operation.resources.every(resource => isRecord(resource) && ["person", "equipment", "tooling", "station", "other"].includes(String(resource.kind)) && ["name", "externalId", "qualification"].every(key => typeof resource[key] === "string")))) return null;
  if (value.pending != null) {
    const pending = value.pending;
    if (!isRecord(pending) || !["preview", "execute"].includes(String(pending.stage)) || !isRecord(pending.command)) return null;
    const command = pending.command;
    if (command.product_id !== productId || typeof command.command_id !== "string" || typeof command.idempotency_key !== "string" || !Object.hasOwn(preparationNames, String(command.operation)) || !Number.isInteger(command.expected_revision) || Number(command.expected_revision) < 1 || !isRecord(command.payload)) return null;
    if (pending.stage === "preview" && command.operation === "build.readiness.compute") return null;
    if (!Array.isArray(command.source_read_set) || !command.source_read_set.every(read => isRecord(read) && typeof read.artifact_id === "string" && Number.isInteger(read.expected_revision) && Number(read.expected_revision) > 0)) return null;
  }
  return { draft: draft as unknown as PreparationDraft, pending: (value.pending ?? null) as WaitingPreparation | null };
}
function validExternal(value: unknown): boolean { return isRecord(value) && ["system", "externalId", "revision", "asOfUtc", "hash", "referenceKey"].every(key => typeof value[key] === "string") && (value.asOfOriginal === undefined || typeof value.asOfOriginal === "string"); }
export function externalPayload(draft: ExternalDraft, refs: DefinitionReference[]): ExternalReference | null {
  if (![draft.system, draft.externalId, draft.revision, draft.asOfUtc, draft.hash, draft.referenceKey].some(value => value.trim())) return null;
  if (!draft.system.trim() || !draft.externalId.trim()) throw new Error("外部引用需要系统名称与外部编号。");
  if (draft.hash && !/^[a-fA-F0-9]{64}$/.test(draft.hash.trim())) throw new Error("内容摘要须为 64 位十六进制值；未核验时留空并选择原文依据。");
  const basis = refs.find(ref => JSON.stringify([ref.artifact_id, ref.expected_revision, ref.line, ref.quote]) === draft.referenceKey) ?? null;
  let as_of = utcInput(draft.asOfUtc, "外部引用截至时间");
  if (draft.asOfOriginal && Number.isFinite(new Date(draft.asOfOriginal).getTime()) && draft.asOfUtc === new Date(draft.asOfOriginal).toISOString().slice(0, -1)) as_of = draft.asOfOriginal;
  if ((!draft.revision.trim() || !as_of || !draft.hash.trim()) && !basis) throw new Error("外部引用的版本、截至时间或摘要未齐全，请选择精确原文依据。");
  return { system: draft.system.trim(), external_id: draft.externalId.trim(), revision: draft.revision.trim() || null, as_of, content_sha256: draft.hash.trim().toLowerCase() || null, basis };
}
export function revisionPayload(draft: RevisionDraft, previous: ConfigurationBase | undefined, refs: DefinitionReference[]): RevisionPayload {
  if (draft.name.trim().length < 2 || draft.reason.trim().length < 3 || !refs.length) throw new Error("请填写名称、至少 3 字的保存原因，并选择精确原文依据。");

  if (draft.previousId && (!previous || previous.id !== draft.previousId)) throw new Error("所选前版已不可读，请重新选择。");
  return { name: draft.name.trim(), visibility: draft.visibility, previous_id: previous?.id ?? null, expected_previous_revision: previous?.revision ?? null, reason: draft.reason.trim(), sources: refs.map(ref => ({ ...ref })) };
}
export function bomLinesPayload(lines: BomLineDraft[], refs: DefinitionReference[]): BomLineInput[] {
  if (!lines.length || lines.length > 200 || new Set(lines.map(line => line.key)).size !== lines.length) throw new Error("BOM 须有 1–200 个标识不重复的物料行。");
  return lines.map(line => {
    if (!/^[a-zA-Z0-9_-]{1,80}$/.test(line.key) || !line.name.trim()) throw new Error("每个物料行都需要有效标识和物料名称。");
    let loss_rate: string | null = null;
    if (line.loss.trim()) {
      if (!/^(?:0(?:\.\d{1,8})?|1(?:\.0{1,8})?)$/.test(line.loss.trim())) throw new Error("损耗率按 0–1 小数填写，最多 8 位小数，例如 0.05 表示 5%；未知时留空。");
      loss_rate = line.loss.trim();
    }
    const quantity = line.quantity.trim() ? preciseQuantity(line.quantity, `${line.name}每件用量`) : null;
    if (quantity && !line.unit.trim()) throw new Error(`${line.name}已填写用量，请补充单位。`);
    return { key: line.key, part_id: line.partId || null, expected_part_revision: line.partId ? line.partRevision : null,
      part: line.partId ? null : { name: line.name.trim(), internal_number: line.internal.trim() || null, erp_number: line.erp.trim() || null, customer_number: line.customer.trim() || null, mapping_version: line.mappingVersion.trim() || null, external_design_refs: line.designRefs.map(ref => externalPayload(ref, refs)).filter((ref): ref is ExternalReference => ref !== null) },
      quantity, unit: line.unit.trim() || null, loss_rate, critical: line.critical, notes: line.notes.trim() || null };
  });
}
export function operationsPayload(operations: OperationDraft[], refs: DefinitionReference[]): OperationInput[] {
  if (!operations.length || operations.length > 200 || new Set(operations.map(operation => operation.key)).size !== operations.length) throw new Error("制造配置须有 1–200 个标识不重复的工序。");
  const result = operations.map(operation => {
    if (!/^[a-zA-Z0-9_-]{1,80}$/.test(operation.key) || !operation.name.trim()) throw new Error("每个工序都需要有效标识和名称。");
    return { key: operation.key, name: operation.name.trim(), kind: operation.kind, depends_on: operation.dependencies.split(/[\s,，;；、]+/).filter(Boolean), bom_line_keys: [...operation.bomLineKeys],
      sop: externalPayload(operation.sop, refs), resource_requirements: operation.resources.map(resource => {
        if (!resource.name.trim()) throw new Error(`${operation.name}的资源要求需要名称。`);
        return { kind: resource.kind, name: resource.name.trim(), external_id: resource.externalId.trim() || null, qualification: resource.qualification.trim() || null };
      }), cycle_time_minutes: operation.cycle.trim() ? preciseQuantity(operation.cycle, `${operation.name}节拍`) : null,
      acceptance_criterion: operation.acceptance.trim() || null, notes: operation.notes.trim() || null };
  });
  const keys = new Set(result.map(operation => operation.key));
  if (result.some(operation => operation.depends_on.some(key => !keys.has(key)) || new Set(operation.depends_on).size !== operation.depends_on.length)) throw new Error("前置工序必须存在且不能重复。");
  const unresolved = new Set(keys);
  while (unresolved.size) {
    const next = result.filter(operation => unresolved.has(operation.key) && operation.depends_on.every(key => !unresolved.has(key)));
    if (!next.length) throw new Error("工序依赖存在循环，请核对前置工序。");
    next.forEach(operation => unresolved.delete(operation.key));
  }
  return result;
}
export function mergeReadSets(...sets: SourceRead[][]): SourceRead[] {
  const reads = new Map<string, number>();
  for (const read of sets.flat()) {
    if (reads.has(read.artifact_id) && reads.get(read.artifact_id) !== read.expected_revision) throw new Error("所选对象的同一来源版本不一致，请先重核配置。");
    reads.set(read.artifact_id, read.expected_revision);
  }
  if (reads.size > 20) throw new Error("本轮固定来源超过 20 份，请缩小配置范围并重新核对。");
  return [...reads].sort(([left], [right]) => left.localeCompare(right)).map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision }));
}
export function referencesReadSet(refs: DefinitionReference[]): SourceRead[] {
  return mergeReadSets(refs.map(ref => ({ artifact_id: ref.artifact_id, expected_revision: ref.expected_revision })));
}
export function preciseQuantity(value: string, title = "计划数量"): string {
  const cleaned = value.trim();
  const matched = /^(\d+)(?:\.(\d+))?$/.exec(cleaned);
  if (!matched || !/[1-9]/.test(cleaned) || matched[1].replace(/^0+/, "").length > 16 || (matched[2]?.length ?? 0) > 8) throw new Error(`${title}须为大于 0 的十进制数，最多 16 位整数、8 位小数；未知时请先补充依据。`);
  return cleaned;
}
export function utcInput(value: string, title: string): string | null {
  if (!value.trim()) return null;
  const matched = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::(\d{2})(?:\.(\d{1,3}))?)?$/.exec(value);
  if (!matched) throw new Error(`${title}请填写完整 UTC 日期与时刻，未知时留空。`);
  const result = `${matched[1]}:${matched[2] ?? "00"}.${(matched[3] ?? "").padEnd(3, "0")}Z`, instant = new Date(result);
  if (!Number.isFinite(instant.getTime()) || instant.toISOString() !== result) throw new Error(`${title}不是有效日期或时刻。`);
  return result;
}
export function createBuildPayload(draft: BuildDraft, project: Project, engineering: EngineeringConfiguration, manufacturing: ManufacturingConfiguration): BuildPayload {
  if (project.id !== draft.projectId || project.definition.id !== engineering.definition_id || manufacturing.engineering_configuration_id !== engineering.id) throw new Error("项目固定定义、工程配置和制造配置必须逐级一致。");
  if (draft.name.trim().length < 2 || draft.purpose.trim().length < 3 || draft.objectives.trim().length < 3 || draft.disposition.trim().length < 3 || !draft.unit.trim()) throw new Error("请填写轮次名称、用途、单位、验证目标与实物处置要求。");
  const planned_start = utcInput(draft.startUtc, "计划开始"), planned_end = utcInput(draft.endUtc, "计划结束");
  if (planned_start && planned_end && new Date(planned_end) < new Date(planned_start)) throw new Error("计划结束不能早于计划开始。");
  return {
    project_id: project.id, expected_project_revision: project.revision,
    engineering_configuration_id: engineering.id, manufacturing_configuration_id: manufacturing.id,
    name: draft.name.trim(), type: draft.type, purpose: draft.purpose.trim(), planned_quantity: preciseQuantity(draft.quantity), unit: draft.unit.trim(), planned_start, planned_end,
    verification_objectives: draft.objectives.trim(), disposition_plan: draft.disposition.trim(), previous_build_id: draft.previousId || null,
  };
}
export function readableSources(sources: DefinitionSource[]): DefinitionSource[] { return sources.filter(source => source.status === "active"); }
