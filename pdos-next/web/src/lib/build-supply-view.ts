import type { Build } from "@/lib/build-preparation-view";
import { mergeReadSets, referencesReadSet, utcInput } from "@/lib/build-preparation-view";
import type { DefinitionReference } from "@/lib/product-view";
import type { SourceRead } from "@/lib/project-plan-view";
import type { CoverageView, ProjectionRecord, SupplySnapshotView } from "@/components/supply_cost/types";

export type SupplyApi = <T>(path: string, body?: unknown) => Promise<T>;
export type SupplyKind = "inventory" | "commitment" | "in_transit" | "receipt" | "restriction";
export type SupplyRecordInput = {
  record_kind: SupplyKind; record_id: string; material_id: string; quantity: string | null;
  unit: string | null; sources: DefinitionReference[]; source_system: string | null;
  pool_id: string | null; supplier_id: string | null; expected_at: string | null;
  received_at: string | null; commitment_id: string | null;
  quality: "unknown" | "frozen"; availability: "unknown" | "unavailable"; note: string;
};
export type CaptureInput = { capture_key: string; expected_product_revision: number; build_id: string; expected_build_revision: number; reason: string; records: SupplyRecordInput[] };
export type SnapshotRecordPayload = { build_id: string; expected_build_revision: number; capture_id: string; expected_capture_revision: number; expected_previous_snapshot_id: string | null; expected_previous_revision: number | null; reason: string; confirmation_token?: string | null };
export type KitComputePayload = { build_id: string; expected_build_revision: number; supply_snapshot_id: string; expected_supply_revision: number };
type SupplyScope = { build_id: string; project_id: string; owner_id: string; visibility: "private" | "category" | "audience"; required_source_read_set: SourceRead[] };
export type SupplyCapture = SupplyScope & { id: string; revision: number; build_revision: number; status: "unapplied"; source_status: "current" | "needs_recheck"; created_at: string; applied_snapshot_id: string | null; reason: string; input_snapshot: CaptureInput; snapshot_record_payload: SnapshotRecordPayload };
export type PreparedSupply = { capture: SupplyCapture; snapshot_record_payload: SnapshotRecordPayload; required_source_read_set: SourceRead[] };
export type SupplySnapshot = SupplySnapshotView & SupplyScope & { reason: string };
export type SupplyKit = ProjectionRecord<CoverageView> & SupplyScope & { supply_snapshot_id: string };
export type SupplyList = { captures: SupplyCapture[]; snapshots: SupplySnapshot[]; kits: SupplyKit[]; current_by_build: Record<string, { snapshot_id: string; revision: number }>; unavailable_count: number; has_more: boolean };
export type SupplyOperation = "supply.snapshot.record" | "supply.kit.compute";
export type SupplyCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: SupplyOperation; source_read_set: SourceRead[]; payload: SnapshotRecordPayload | KitComputePayload };
export type SupplyPreview = { command: SupplyCommand; confirmation_token: string; expires_at: string; review: Record<string, unknown> & { operation: "supply.snapshot.record"; effect: string; before: SupplySnapshotView | null; after: SupplySnapshot & { input_snapshot: CaptureInput; sources: DefinitionReference[]; capture_id: string; previous_snapshot_id: string | null; previous_revision: number | null } } };
export type SupplyWaiting = { stage: "capture"; request: CaptureInput } | { stage: "preview" | "execute"; command: SupplyCommand };
export type SupplyRowDraft = {
  kind: SupplyKind; recordId: string; materialId: string; quantity: string; unit: string;
  system: string; pool: string; supplier: string; expectedUtc: string; receivedUtc: string;
  commitment: string; quality: "unknown" | "frozen"; availability: "unknown" | "unavailable";
  note: string; sources: DefinitionReference[];
};
export type SupplyDraft = { reason: string; records: SupplyRowDraft[]; references: DefinitionReference[] };
export type SupplyLocal = { buildId: string; drafts: Record<string, SupplyDraft>; prepared: Record<string, PreparedSupply>; pending: SupplyWaiting | null };
export type MaterialOption = { id: string; name: string; unit: string | null; revision: number | null };
export const supplyNames = { "supply.snapshot.record": "供给来源快照", "supply.kit.compute": "固定快照齐套结果" };
export const supplySubjects = { "supply.snapshot.record": "supply_snapshot", "supply.kit.compute": "supply_coverage" };
export const supplyKindNames: Record<SupplyKind, string> = { inventory: "当前库存记录", commitment: "已有供方承诺", in_transit: "在途记录", receipt: "实际到货记录", restriction: "质量或可用限制" };
export const emptySupply: SupplyList = { captures: [], snapshots: [], kits: [], current_by_build: {}, unavailable_count: 0, has_more: false };
export function blankSupplyRow(): SupplyRowDraft { return { kind: "inventory", recordId: "", materialId: "", quantity: "", unit: "", system: "", pool: "", supplier: "", expectedUtc: "", receivedUtc: "", commitment: "", quality: "unknown", availability: "unknown", note: "", sources: [] }; }
export function blankSupplyDraft(): SupplyDraft { return { reason: "", records: [blankSupplyRow()], references: [] }; }
export function isObject(value: unknown): value is Record<string, unknown> { return value !== null && typeof value === "object" && !Array.isArray(value); }
function refsValid(value: unknown): value is DefinitionReference[] { return Array.isArray(value) && value.every(ref => isObject(ref) && typeof ref.artifact_id === "string" && Number.isInteger(ref.expected_revision) && Number(ref.expected_revision) > 0 && Number.isInteger(ref.line) && Number(ref.line) > 0 && typeof ref.quote === "string"); }
function readsValid(value: unknown): value is SourceRead[] { return Array.isArray(value) && value.every(read => isObject(read) && typeof read.artifact_id === "string" && Number.isInteger(read.expected_revision) && Number(read.expected_revision) > 0); }
function draftValid(value: unknown): value is SupplyDraft {
  return isObject(value) && typeof value.reason === "string" && refsValid(value.references) && Array.isArray(value.records) && value.records.length > 0 && value.records.length <= 500 && value.records.every(row => isObject(row) && Object.hasOwn(supplyKindNames, String(row.kind)) && ["recordId", "materialId", "quantity", "unit", "system", "pool", "supplier", "expectedUtc", "receivedUtc", "commitment", "note"].every(key => typeof row[key] === "string") && ["unknown", "frozen"].includes(String(row.quality)) && ["unknown", "unavailable"].includes(String(row.availability)) && refsValid(row.sources));
}
function captureInputValid(value: unknown): value is CaptureInput { return isObject(value) && typeof value.capture_key === "string" && value.capture_key.length >= 8 && typeof value.build_id === "string" && Number.isInteger(value.expected_product_revision) && Number(value.expected_product_revision) > 0 && Number.isInteger(value.expected_build_revision) && Number(value.expected_build_revision) > 0 && typeof value.reason === "string" && Array.isArray(value.records) && value.records.length > 0 && value.records.length <= 500 && value.records.every(row => isObject(row) && Object.hasOwn(supplyKindNames, String(row.record_kind)) && typeof row.record_id === "string" && typeof row.material_id === "string" && refsValid(row.sources)); }
function preparedValid(value: unknown, buildId?: string): value is PreparedSupply { return isObject(value) && isObject(value.capture) && typeof value.capture.id === "string" && Number.isInteger(value.capture.revision) && typeof value.capture.build_id === "string" && (!buildId || value.capture.build_id === buildId) && captureInputValid(value.capture.input_snapshot) && value.capture.input_snapshot.build_id === value.capture.build_id && isObject(value.snapshot_record_payload) && value.snapshot_record_payload.build_id === value.capture.build_id && value.snapshot_record_payload.capture_id === value.capture.id && value.snapshot_record_payload.expected_capture_revision === value.capture.revision && readsValid(value.required_source_read_set); }
export function restoreSupply(value: unknown, productId: string): SupplyLocal | null {
  if (!isObject(value) || typeof value.buildId !== "string" || !isObject(value.drafts) || !Object.values(value.drafts).every(draftValid) || !isObject(value.prepared) || !Object.entries(value.prepared).every(([id, prepared]) => preparedValid(prepared, id))) return null;
  if (value.pending != null) {
    const waiting = value.pending;
    if (!isObject(waiting)) return null;
    if (waiting.stage === "capture") { if (!captureInputValid(waiting.request) || waiting.request.build_id !== value.buildId) return null; }
    else if (["preview", "execute"].includes(String(waiting.stage)) && isObject(waiting.command)) {
      const command = waiting.command;
      if (command.product_id !== productId || !Object.hasOwn(supplyNames, String(command.operation)) || typeof command.command_id !== "string" || typeof command.idempotency_key !== "string" || !Number.isInteger(command.expected_revision) || Number(command.expected_revision) <= 0 || !readsValid(command.source_read_set) || !isObject(command.payload) || command.payload.build_id !== value.buildId || (waiting.stage === "preview" && command.operation !== "supply.snapshot.record")) return null;
    } else return null;
  }
  return value as unknown as SupplyLocal;
}
export function materialsFromBuild(build: Build | undefined): MaterialOption[] {
  const bom = build?.engineering_configuration.bom;
  if (!isObject(bom) || !Array.isArray(bom.lines)) return [];
  const options: MaterialOption[] = [];
  for (const line of bom.lines) if (isObject(line) && isObject(line.part) && typeof line.part.id === "string" && typeof line.part.name === "string") options.push({ id: line.part.id, name: line.part.name, unit: typeof line.unit === "string" ? line.unit : null, revision: typeof line.part.revision === "number" ? line.part.revision : null });
  return [...new Map(options.map(option => [option.id, option])).values()];
}
function text(value: string, label: string, max: number, min = 1): string { const cleaned = value.trim(); if (cleaned.length < min || cleaned.length > max) throw new Error(`${label}须为 ${min}–${max} 字的明确记录。`); return cleaned; }
function optional(value: string, label: string, max: number): string | null { return value.trim() ? text(value, label, max) : null; }
export function supplyQuantity(value: string): string | null {
  const cleaned = value.trim(); if (!cleaned) return null;
  const match = /^(\d+)(?:\.(\d+))?$/.exec(cleaned);
  if (!match || match[1].replace(/^0+/, "").length > 16 || (match[2]?.length ?? 0) > 8) throw new Error("来源数量须为非负十进制数，最多 16 位整数与 8 位小数；未知留空，明确为零才填 0。");
  return cleaned;
}
export function supplyUtc(value: string, label: string): string | null {
  if (!value.trim()) return null;
  // Preserved captures may carry microseconds. A source fact must not lose them on editing.
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})\.(\d{4,6})Z?$/.exec(value.trim());
  if (match) { utcInput(`${match[1]}.${match[2].slice(0, 3)}`, label); return `${match[1]}.${match[2]}Z`; }
  return utcInput(value.trim().replace(/Z$/, ""), label);
}
export function createCaptureInput(draft: SupplyDraft, build: Build, productRevision: number, captureKey: string): CaptureInput {
  if (!draft.records.length || draft.records.length > 500) throw new Error("每版快照须包含 1–500 条来源记录。");
  const materials = new Set(materialsFromBuild(build).map(option => option.id));
  const records = draft.records.map((row, index): SupplyRecordInput => {
    const label = `第 ${index + 1} 条来源`;
    if (!materials.has(row.materialId)) throw new Error(`${label}须选择固定 BOM 中的真实物料。`);
    if (!row.sources.length) throw new Error(`${label}须独立选择 1–20 条精确原文依据。`);
    const quantity = supplyQuantity(row.quantity), unit = optional(row.unit, `${label}单位`, 80);
    if (quantity !== null && unit === null) throw new Error(`${label}数量已知时须明确来源单位，不能隐式换算。`);
    const source_system = optional(row.system, "来源系统", 100), pool_id = optional(row.pool, "外部物理池标识", 200), supplier_id = optional(row.supplier, "供方标识", 200);
    if (row.kind !== "commitment" && (!source_system || !pool_id)) throw new Error(`${label}须明确来源系统与真实外部物理池标识。`);
    if (row.kind === "commitment" && !supplier_id) throw new Error(`${label}须明确已有承诺的外部供方标识。`);
    const received_at = row.kind === "receipt" ? supplyUtc(row.receivedUtc, "实际到货时间") : null;
    if (row.kind === "receipt" && !received_at) throw new Error(`${label}须填写真实到货发生时间，不能用快照捕获时间代填。`);
    return { record_kind: row.kind, record_id: text(row.recordId, `${label}稳定记录标识`, 160), material_id: row.materialId, quantity, unit, sources: row.sources.map(({ artifact_id, expected_revision, line, quote }) => ({ artifact_id, expected_revision, line, quote })), source_system, pool_id, supplier_id, expected_at: supplyUtc(row.expectedUtc, "来源预计到达时间"), received_at, commitment_id: optional(row.commitment, "承诺关联标识", 160), quality: row.quality, availability: row.availability, note: text(row.note, `${label}说明`, 2000) };
  });
  if (new Set(records.map(row => JSON.stringify([row.record_kind, row.record_id]))).size !== records.length) throw new Error("同一版不能重复录入同种来源的稳定记录标识。");
  mergeReadSets(build.required_source_read_set, referencesReadSet(records.flatMap(row => row.sources)));
  return { capture_key: text(captureKey, "原捕获请求标识", 160, 8), expected_product_revision: productRevision, build_id: build.id, expected_build_revision: build.revision, reason: text(draft.reason, "整版记录原因", 2000, 3), records };
}
export function draftFromCapture(input: CaptureInput): SupplyDraft {
  const records = input.records.map((row): SupplyRowDraft => ({ kind: row.record_kind, recordId: row.record_id, materialId: row.material_id, quantity: row.quantity ?? "", unit: row.unit ?? "", sources: row.sources.map(ref => ({ ...ref })), system: row.source_system ?? "", pool: row.pool_id ?? "", supplier: row.supplier_id ?? "", expectedUtc: row.expected_at?.replace(/Z$/, "").replace(/\+00:00$/, "") ?? "", receivedUtc: row.received_at?.replace(/Z$/, "").replace(/\+00:00$/, "") ?? "", commitment: row.commitment_id ?? "", quality: row.quality, availability: row.availability, note: row.note }));
  const refs = records.flatMap(row => row.sources), distinct = [...new Map(refs.map(ref => [JSON.stringify(ref), ref])).values()];
  return { reason: input.reason, records, references: distinct };
}
export function checkPrepared(prepared: PreparedSupply, input: CaptureInput): void {
  if (!preparedValid(prepared, input.build_id) || prepared.capture.input_snapshot.capture_key !== input.capture_key || prepared.capture.input_snapshot.expected_build_revision !== input.expected_build_revision || prepared.snapshot_record_payload.expected_build_revision !== input.expected_build_revision) throw new Error("来源捕获回执不对应原请求，请保留原标识重试。");
}
export function snapshotCanCompute(snapshot: SupplySnapshot | undefined, build: Build | undefined, principalId: string): boolean { return !!snapshot && !!build && snapshot.build_id === build.id && snapshot.owner_id === principalId && build.owner_id === principalId && snapshot.freshness === "current" && build.source_status === "current" && build.readiness?.is_current === true && snapshot.source_refs.length > 0 && snapshot.source_refs.every(ref => ref.state === "current"); }
export function kitPayload(build: Build, snapshot: SupplySnapshot, current: { snapshot_id: string; revision: number }): KitComputePayload {
  const revision = Number(snapshot.revision);
  if (snapshot.build_id !== build.id || snapshot.id !== current.snapshot_id || !Number.isInteger(revision) || revision < 1 || revision !== current.revision || snapshot.binding.basis.build.build_id !== build.id || snapshot.binding.basis.build.ref.version !== String(build.revision)) throw new Error("当前供给快照与固定 Build 版本不一致，请刷新服务器绑定。");
  return { build_id: build.id, expected_build_revision: build.revision, supply_snapshot_id: snapshot.id, expected_supply_revision: revision };
}

/** Viewer copies only: never use these labels as command IDs or recalculate a source digest. */
function displayCopy(value: unknown, names: Map<string, string>, field?: string): unknown {
  if (typeof value === "string" && field === "record_id") {
    try {
      const identity: unknown = JSON.parse(value);
      if (Array.isArray(identity) && identity.length === 3 && identity.every(part => typeof part === "string") && names.has(identity[2])) return `${identity[0]} · ${identity[1]} · ${names.get(identity[2])}`;
    } catch { /* External record identifiers remain exactly as recorded. */ }
    return value;
  }
  if (typeof value === "string" && field && ["material_id", "build_id", "source_id"].includes(field)) {
    if (names.has(value)) return names.get(value);
    if (field === "source_id") {
      const [kind, ...tail] = value.split(":");
      if (["artifact", "build", "bom", "configuration", "process", "manufacturing_configuration", "supply"].includes(kind)) return names.get(tail.join(":")) ?? value;
    }
    return value;
  }
  if (Array.isArray(value)) return value.map(item => displayCopy(item, names, field));
  if (isObject(value)) return Object.fromEntries(Object.entries(value).map(([key, item]) => [key, displayCopy(item, names, key)]));
  return value;
}
export function snapshotDisplay(raw: SupplySnapshotView, names: Map<string, string>): SupplySnapshotView { return displayCopy(raw, names) as SupplySnapshotView; }
export function kitDisplay(raw: ProjectionRecord<CoverageView>, names: Map<string, string>): ProjectionRecord<CoverageView> { return displayCopy(raw, names) as ProjectionRecord<CoverageView>; }
