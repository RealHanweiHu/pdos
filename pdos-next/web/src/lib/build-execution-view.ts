import type { DefinitionReference } from "@/lib/product-view";
import type { SourceRead } from "@/lib/project-plan-view";
import type { Build, EngineeringConfiguration, ManufacturingConfiguration } from "@/lib/build-preparation-view";
import { mergeReadSets, referencesReadSet, utcInput } from "@/lib/build-preparation-view";

export type ExecutionApi = <T>(path: string, body?: unknown) => Promise<T>;
export type ExecutionOperation = "build.configuration.actual.record" | "build.output.record" | "build.sample.allocate";
export type ExecutionBase = { id: string; revision: number; owner_id: string; visibility: "private" | "category" | "audience"; build_id: string; project_id: string; sources: DefinitionReference[]; required_source_read_set: SourceRead[]; source_status: "current" | "needs_recheck"; reason: string; created_at?: string };
export type FixedConfigurations = { engineering_configuration: EngineeringConfiguration; manufacturing_configuration: ManufacturingConfiguration };
export type ConfigurationDifference = { path: string; label?: string; before: unknown; after: unknown };
export type ExplainedDifference = ConfigurationDifference & { reason: string; sources: DefinitionReference[] };
export type ActualConfiguration = ExecutionBase & {
  planned: FixedConfigurations; actual: FixedConfigurations;
  planned_engineering_configuration_id: string; planned_manufacturing_configuration_id: string;
  actual_engineering_configuration_id: string; actual_manufacturing_configuration_id: string;
  observed_at: string; differences: ExplainedDifference[];
};
export type Observation = { system: string; external_id: string; nature: "real" | "synthetic"; occurred_at: string };
export type BuildLot = ExecutionBase & { actual_configuration_id: string; actual_configuration_revision: number; lot_label: string; observed_unit_count: number; build_observed_unit_count: number; unit: string; identified_count: number; remaining_unit_count: number; over_planned_quantity: boolean; observation: Observation & { received_at: string }; status: "observed" };
export type SampleFields = { label: string; operation_key: string | null; cavity: string | null; custodian_id: string | null; custodian_label: string | null; location: string | null; destination: string | null; availability: "unknown" | "hold" };
export type SampleUnit = ExecutionBase & SampleFields & { lot_id: string; actual_configuration_id: string; allocation_id: string; observation_nature: "real" | "synthetic"; reservation: null; consumption: null };
export type SampleAllocation = ExecutionBase & { lot_id: string; actual_configuration_id: string; unit_count: number; sample_ids: string[] };
export type ExecutionList = { actual_configurations: ActualConfiguration[]; lots: BuildLot[]; allocations: SampleAllocation[]; samples: SampleUnit[]; unavailable_count: number; has_more: boolean };
export type ActualComparison = {
  build: { id: string; revision: number; name: string; project_id: string; unit: string; planned_quantity: string; status: string };
  planned: FixedConfigurations; actual: FixedConfigurations; differences: ConfigurationDifference[];
  required_source_read_set: SourceRead[]; source_status: "current" | "needs_recheck"; visibility: "private" | "category" | "audience";
};
export type DifferencePayload = { path: string; reason: string; sources: DefinitionReference[] };
export type ActualConfigurationPayload = {
  build_id: string; expected_build_revision: number; actual_engineering_configuration_id: string;
  expected_actual_engineering_revision: number; actual_manufacturing_configuration_id: string;
  expected_actual_manufacturing_revision: number; observed_at: string; differences: DifferencePayload[];
  reason: string; sources: DefinitionReference[]; confirmation_token?: string | null;
};
export type OutputPayload = {
  build_id: string; expected_build_revision: number; actual_configuration_id: string;
  expected_actual_configuration_revision: number; lot_label: string; observed_unit_count: number;
  unit: string; observation: Observation; reason: string; sources: DefinitionReference[]; confirmation_token?: string | null;
};
export type SampleAllocatePayload = { lot_id: string; expected_lot_revision: number; samples: SampleFields[]; reason: string; sources: DefinitionReference[]; confirmation_token?: string | null };
export type ExecutionCommand = { command_id: string; idempotency_key: string; operation: ExecutionOperation; product_id: string; expected_revision: number; source_read_set: SourceRead[]; payload: ActualConfigurationPayload | OutputPayload | SampleAllocatePayload };
export type ExecutionPreview = { command: ExecutionCommand; confirmation_token: string; expires_at: string; review: { operation: ExecutionOperation; name: string; effect: string; before: unknown; after: Record<string, unknown>; reason: string } };
export type WaitingExecution = { stage: "preview" | "execute"; command: ExecutionCommand };
export type SampleDraft = { label: string; operationKey: string; cavity: string; custodian: "unknown" | "self" | "label"; custodianLabel: string; location: string; destination: string; availability: "unknown" | "hold" };
export type ExecutionDraft = {
  engineeringId: string; manufacturingId: string; actualObservedUtc: string; actualReason: string;
  differences: Record<string, { reason: string; references: DefinitionReference[] }>;
  actualId: string; lotLabel: string; count: string; observationSystem: string; observationId: string;
  observationNature: "real" | "synthetic"; occurredUtc: string; outputReason: string;
  lotId: string; samples: SampleDraft[]; allocationReason: string; references: DefinitionReference[];
};
export type LocalExecution = { selectedBuildId: string; drafts: Record<string, ExecutionDraft>; pending: WaitingExecution | null };
export const executionNames: Record<ExecutionOperation, string> = {
  "build.configuration.actual.record": "实际配置记录", "build.output.record": "已发生产出批次", "build.sample.allocate": "批次样件身份分配",
};
export const executionReceiptTypes: Record<ExecutionOperation, string> = {
  "build.configuration.actual.record": "actual_configuration", "build.output.record": "build_lot", "build.sample.allocate": "sample_allocation",
};
export const supportedDiscreteUnits = new Set(["台", "件", "个", "只", "套", "ea", "piece", "unit"]);
export const availabilityNames = { unknown: "可用性未知，待核对", hold: "保留待处置，不能投入测试" };
export function blankSample(): SampleDraft { return { label: "", operationKey: "", cavity: "", custodian: "unknown", custodianLabel: "", location: "", destination: "", availability: "unknown" }; }
export function blankExecution(): ExecutionDraft { return { engineeringId: "", manufacturingId: "", actualObservedUtc: "", actualReason: "", differences: {}, actualId: "", lotLabel: "", count: "", observationSystem: "", observationId: "", observationNature: "real", occurredUtc: "", outputReason: "", lotId: "", samples: [blankSample()], allocationReason: "", references: [] }; }
function record(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function validReferences(value: unknown): value is DefinitionReference[] { return Array.isArray(value) && value.every(ref => record(ref) && typeof ref.artifact_id === "string" && Number.isInteger(ref.expected_revision) && Number(ref.expected_revision) > 0 && Number.isInteger(ref.line) && Number(ref.line) > 0 && typeof ref.quote === "string"); }
function validDraft(value: unknown): value is ExecutionDraft {
  if (!record(value) || !["engineeringId", "manufacturingId", "actualObservedUtc", "actualReason", "actualId", "lotLabel", "count", "observationSystem", "observationId", "occurredUtc", "outputReason", "lotId", "allocationReason"].every(key => typeof value[key] === "string") || !["real", "synthetic"].includes(String(value.observationNature)) || !validReferences(value.references) || !record(value.differences)) return false;
  if (!Object.values(value.differences).every(difference => record(difference) && typeof difference.reason === "string" && validReferences(difference.references))) return false;
  return Array.isArray(value.samples) && value.samples.length > 0 && value.samples.length <= 500 && value.samples.every(sample => record(sample) && ["label", "operationKey", "cavity", "custodianLabel", "location", "destination"].every(key => typeof sample[key] === "string") && ["unknown", "self", "label"].includes(String(sample.custodian)) && ["unknown", "hold"].includes(String(sample.availability)));
}
export function restoreExecution(value: unknown, productId: string): LocalExecution | null {
  if (!record(value) || typeof value.selectedBuildId !== "string" || !record(value.drafts) || !Object.values(value.drafts).every(validDraft)) return null;
  if (value.pending != null) {
    const pending = value.pending;
    if (!record(pending) || !["preview", "execute"].includes(String(pending.stage)) || !record(pending.command)) return null;
    const command = pending.command;
    if (command.product_id !== productId || typeof command.command_id !== "string" || typeof command.idempotency_key !== "string" || !Object.hasOwn(executionNames, String(command.operation)) || !Number.isInteger(command.expected_revision) || Number(command.expected_revision) < 1 || !record(command.payload)) return null;
    if (!Array.isArray(command.source_read_set) || !command.source_read_set.every(read => record(read) && typeof read.artifact_id === "string" && Number.isInteger(read.expected_revision) && Number(read.expected_revision) > 0)) return null;
  }
  return value as unknown as LocalExecution;
}
function evidence(refs: DefinitionReference[]): DefinitionReference[] {
  if (!refs.length) throw new Error("请加入 至少一条能精确定位的原文依据。");
  return refs.map(({ artifact_id, expected_revision, line, quote }) => ({ artifact_id, expected_revision, line, quote }));
}
function reason(value: string): string { if (value.trim().length < 3 || value.length > 2000) throw new Error("请填写 3–2000 字的记录原因。"); return value.trim(); }
function boundedText(value: string, title: string, max: number): string { const text = value.trim(); if (!text || text.length > max) throw new Error(`${title}须为 1–${max} 字的明确记录。`); return text; }
function optionalText(value: string, title: string, max: number): string | null { return value.trim() ? boundedText(value, title, max) : null; }
function eventTime(value: string, title: string): string { const result = utcInput(value, title); if (!result) throw new Error(`${title}须为已发生的明确 UTC 时间，不能用当前时间代填。`); return result; }
export function unitCount(value: string): number { const text = value.trim(); if (!/^\d+$/.test(text) || !Number.isSafeInteger(Number(text)) || Number(text) < 1) throw new Error("产出件数须为大于零的可精确表示整数，不作重量或单位换算。"); return Number(text); }
export function actualPayload(draft: ExecutionDraft, build: Build, comparison: ActualComparison): ActualConfigurationPayload {
  if (comparison.source_status !== "current") throw new Error("固定计划或实际来源需重核，当前不能继续登记。");
  if (comparison.build.id !== build.id || comparison.build.revision !== build.revision || comparison.actual.engineering_configuration.id !== draft.engineeringId || comparison.actual.manufacturing_configuration.id !== draft.manufacturingId) throw new Error("差异不是当前选择，请重新读取计划与实际的差异。");
  const differences = comparison.differences.map(difference => {
    const explanation = draft.differences[difference.path];
    if (!explanation) throw new Error("每一处实际差异都需要解释与独立选择的精确原文依据。");
    return { path: difference.path, reason: reason(explanation.reason), sources: evidence(explanation.references) };
  });
  return { build_id: build.id, expected_build_revision: build.revision, actual_engineering_configuration_id: comparison.actual.engineering_configuration.id, expected_actual_engineering_revision: comparison.actual.engineering_configuration.revision, actual_manufacturing_configuration_id: comparison.actual.manufacturing_configuration.id, expected_actual_manufacturing_revision: comparison.actual.manufacturing_configuration.revision, observed_at: eventTime(draft.actualObservedUtc, "实际配置观察时间"), differences, reason: reason(draft.actualReason), sources: evidence(draft.references) };
}
export function outputPayload(draft: ExecutionDraft, build: Build, actual: ActualConfiguration): OutputPayload {
  if (actual.source_status !== "current") throw new Error("实际配置来源需重核，当前不能继续登记产出。");
  if (actual.build_id !== build.id || actual.id !== draft.actualId) throw new Error("请选择本轮已登记的实际配置。");
  if (!supportedDiscreteUnits.has(build.unit)) throw new Error("本轮计划单位不属于离散件数单位，请另行核对计量合同；这里不换算。");
  return { build_id: build.id, expected_build_revision: build.revision, actual_configuration_id: actual.id, expected_actual_configuration_revision: actual.revision, lot_label: boundedText(draft.lotLabel, "批次标识", 100), observed_unit_count: unitCount(draft.count), unit: build.unit, observation: { system: boundedText(draft.observationSystem, "外部观察系统或来源名称", 100), external_id: boundedText(draft.observationId, "外部事件编号", 200), nature: draft.observationNature, occurred_at: eventTime(draft.occurredUtc, "外部产出事件时间") }, reason: reason(draft.outputReason), sources: evidence(draft.references) };
}
export function samplePayload(draft: ExecutionDraft, lot: BuildLot, actual: ActualConfiguration, principalId: string): SampleAllocatePayload {
  if (lot.source_status !== "current" || actual.source_status !== "current") throw new Error("批次或实际配置来源需重核，当前不能继续分配样件。");
  if (lot.id !== draft.lotId || lot.actual_configuration_id !== actual.id) throw new Error("样件须来自所选批次固定的实际配置。");
  if (!draft.samples.length || draft.samples.length > lot.remaining_unit_count) throw new Error("样件数须在本批次剩余可分配件数内。");
  const samples = draft.samples.map(sample => {
    if (sample.operationKey && !actual.actual.manufacturing_configuration.operations.some(operation => operation.key === sample.operationKey)) throw new Error("样件来源工序不属于固定实际制造配置。");
    if (sample.custodian === "label" && !sample.custodianLabel.trim()) throw new Error("保管人选为外部姓名时，请填写明确姓名；未知请选择待核对。");
    return { label: boundedText(sample.label, "样件标识", 100), operation_key: optionalText(sample.operationKey, "来源工序", 80), cavity: optionalText(sample.cavity, "模穴标记", 100), custodian_id: sample.custodian === "self" ? principalId : null, custodian_label: sample.custodian === "label" ? boundedText(sample.custodianLabel, "外部保管人姓名", 200) : null, location: optionalText(sample.location, "保管位置", 500), destination: optionalText(sample.destination, "已知去向", 500), availability: sample.availability };
  });
  if (new Set(samples.map(sample => sample.label)).size !== samples.length) throw new Error("本次样件标识不能重复。");
  return { lot_id: lot.id, expected_lot_revision: lot.revision, samples, reason: reason(draft.allocationReason), sources: evidence(draft.references) };
}
export function executionReads(inherited: SourceRead[], refs: DefinitionReference[], differences: { sources: DefinitionReference[] }[] = []): SourceRead[] { return mergeReadSets(inherited, referencesReadSet([...refs, ...differences.flatMap(difference => difference.sources)])); }
export function differenceLabel(path: string): string {
  const names: Record<string, string> = { engineering_configuration: "工程配置", manufacturing_configuration: "制造配置", definition: "型号定义", definition_id: "固定型号定义", bom: "BOM", bom_id: "固定 BOM", mechanical: "机械设计版本", electronic: "电子设计版本", firmware: "固件制品版本", design_versions: "设计版本", operations: "工序", site: "制造场地", line: "制造产线", unit: "单位", quantity: "每件用量", loss_rate: "损耗率", part_id: "固定物料", part: "物料", lines: "BOM 物料行", name: "名称", revision: "版本", sop: "作业文件", resources: "资源要求", resource_requirements: "资源要求", cycle_time_minutes: "节拍", acceptance_criterion: "验收判据", bom_line_keys: "关联物料行", notes: "说明", key: "标识", critical: "关键件", depends_on: "前置工序", internal_number: "研发编号", erp_number: "ERP 料号", customer_number: "客户料号" };
  return path.split(/[./]/).filter(Boolean).map(part => names[part] ?? part).join(" · ");
}
