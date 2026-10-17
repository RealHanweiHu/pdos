import { mpDecimal, mpRecord, mpRevision, mpSame, mpUuid } from "@/components/manufacturing-preparation/manufacturing-preparation-contract";
import { qualitySource, validQualitySource, type QualitySource } from "@/lib/build-quality-loop-view";
import { sourceLines, type DefinitionSource } from "@/lib/product-view";
import type { SourceRead } from "@/lib/project-plan-view";
import type { ActualConfiguration, BuildLot } from "@/lib/build-execution-view";
import type { Build } from "@/lib/build-preparation-view";

export const nativeOperations = ["npi.pilot.create", "npi.pilot.result.record"] as const;
export type NativeOperation = typeof nativeOperations[number];
export type NativeScope = { categoryId: string; productId: string; projectId: string; principalId: string };
export type NativeRef = { kind: string; id: string; revision: number };
export type NativeSource = QualitySource;
export type NativeReferenceSource = { kind: "artifact" | "domain" | "command"; id: string; revision: number; position: string };
export type NativeDetails = Record<string, unknown> & { pilot_id: string; basis: Record<string, NativeRef | string>; purpose: string; source: NativeReferenceSource };
export type NativeRecord = Record<string, unknown> & { observation_id: string; expected_pilot_revision: number; previous_observation_id: string | null; correction_reason: string | null; scope: Record<string, unknown>; counts: Record<string, number | null> | null; units: Record<string, unknown>[]; exceptions: Record<string, unknown>[]; observed: Record<string, unknown>; source: NativeSource };
export type NativeCreatePayload = { project_id: string; details: NativeDetails; statistics: Record<string, unknown> | null; visibility: "private" | "category" | "audience"; confirmation_token?: string | null };
export type NativeResultPayload = { pilot_id: string; expected_pilot_revision: number; record: NativeRecord; confirmation_token?: string | null };
export type NativePayload = NativeCreatePayload | NativeResultPayload;
export type NativeCommand = { command_id: string; idempotency_key: string; category_id: string; product_id: string; expected_revision: number; operation: NativeOperation; source_read_set: SourceRead[]; payload: NativePayload };
export type NativePending = { stage: "inputs" | "preview" | "execute"; command: NativeCommand };
export type NativeReceipt = { id: string; subject_id: string; subject_revision: number; subject_type: "pilot_run" | "pilot_observation"; operation: NativeOperation };
export type NativeReview = { operation: NativeOperation; before: unknown; after: Record<string, unknown>; authority: Record<string, unknown>; effect: string; required_source_read_set: SourceRead[] };
export type NativePrepared = { command: NativeCommand; confirmation_token: string; expires_at: string; review: NativeReview };
export type NativePilotItem = {
  schema_version: "pdos-native-pilot-v1"; project_id: string;
  pilot: { id: string; revision: 1; details: NativeDetails; statistics_basis: Record<string, unknown> | null; material: Record<string, unknown>; gaps: NativeGap[]; receipt_id: string; source_status: string };
  current: { revision: number; epoch: number; latest_observation_id: string | null };
  observations: { id: string; revision: number; record: NativeRecord; fixed_scope: Record<string, unknown> | null; projection: Record<string, unknown> | null; material: Record<string, unknown>; gaps: NativeGap[]; receipt_id: string; source_status: string }[];
  qualification: "unknown"; start_authorized: false; manufacturing_release: null;
};
export type NativeGap = { code: string; detail: string; state?: string };
export type NativeApi = <T>(path: string, body?: unknown) => Promise<T>;
export type NativeCreateDraft = { pilotId: string; lotId: string; publicationId: string; line: NativeRef | null; source: NativeSource | null; statistics: Record<string, unknown> | null; visibility: "private" | "category" | "audience" };
export type NativeLocal = { schema_version: 1; scope: NativeScope; create: NativeCreateDraft; selectedPilotId: string; results: Record<string, NativeRecord>; pending: NativePending | null; receipt: NativeReceipt | null };
export const nativeCountFields = ["input_count", "output_count", "first_pass", "first_failed", "first_unknown", "final_good", "reworked_good", "scrap", "rework_pending", "undecided", "unprocessed", "rework_cycles"] as const;
export const nativeCountNames: Record<typeof nativeCountFields[number], string> = { input_count: "固定投入", output_count: "已加工产出", first_pass: "首遍合格", first_failed: "首遍失败", first_unknown: "首遍未知", final_good: "最终合格", reworked_good: "返工后合格", scrap: "报废", rework_pending: "返工待定", undecided: "最终未决", unprocessed: "未加工", rework_cycles: "返工次数（不计新增投入）" };
const clone = <T,>(value: T): T => structuredClone(value);
const ref = (v: unknown, kind?: string): v is NativeRef => mpRecord(v) && mpUuid(v.id) && mpRevision(v.revision) && typeof v.kind === "string" && (!kind || v.kind === kind);
const nullableRef = (v: unknown, kind?: string) => v === null || ref(v, kind);
const readSource = (v: unknown): v is NativeReferenceSource => mpRecord(v) && mpUuid(v.id) && mpRevision(v.revision) && ["artifact", "domain", "command"].includes(String(v.kind)) && typeof v.position === "string" && !!v.position;
const token = (v: unknown) => typeof v === "string" && v.length >= 20 && v.length <= 128;
const reads = (v: unknown): v is SourceRead[] => Array.isArray(v) && v.length > 0 && v.every(r => mpRecord(r) && mpUuid(r.artifact_id) && mpRevision(r.expected_revision)) && new Set(v.map(r => r.artifact_id)).size === v.length;
const conservative = (v: unknown) => mpRecord(v) && v.qualification === "unknown" && v.start_authorized === false && v.manufacturing_release === null;
const gapRows = (v: unknown): v is NativeGap[] => Array.isArray(v) && v.every(g => mpRecord(g) && typeof g.code === "string" && typeof g.detail === "string");
function basis(v: unknown) { return mpRecord(v) && [["build", "build"], ["lot", "build_lot"], ["actual_configuration", "actual_configuration"], ["engineering_configuration", "engineering_configuration"], ["process_revision", "process_revision"]].every(([key, kind]) => ref(v[key], kind)) && typeof v.unit === "string"; }
function canonicalInstant(v: unknown, utc = false): unknown {
  if (typeof v !== "string" || !Number.isFinite(Date.parse(v))) return v;
  const match = /^(\d{4}-\d{2}-\d{2}T\d{2}:\d{2})(?::(\d{2}))?(?:\.(\d{1,6}))?(Z|[+-]\d{2}:\d{2})$/.exec(v);
  if (!match) return v;
  const fraction = (match[3] ?? "").padEnd(6, "0"), suffix = match[4] === "+00:00" ? "Z" : match[4];
  return `${utc ? new Date(v).toISOString().slice(0, 19) : `${match[1]}:${match[2] ?? "00"}`}${Number(fraction) ? `.${fraction}` : ""}${utc ? "Z" : suffix}`;
}
function detailsSemantic(v: Record<string, unknown>): Record<string, unknown> {
  return { manufacturing_baseline: null, line: null, people: [], material_lots: [], fixtures: [], equipment: [], instructions: [], control_plan: null, risk: null, reservation: null, first_article: null, parameters: [], ...clone(v) };
}
function statisticsSemantic(v: Record<string, unknown> | null) {
  if (v === null) return null;
  let operational = v.operational_scope ?? null;
  if (mpRecord(operational)) operational = { ...operational, quantity: mpDecimal(String(operational.quantity)), ...(mpRecord(operational.window) ? { window: { ...operational.window, start: canonicalInstant(operational.window.start, true), finish: canonicalInstant(operational.window.finish, true) } } : {}) };
  return { samples: [], criterion_revision: 1, ...clone(v), operational_scope: operational, window_start: canonicalInstant(v.window_start), window_end: canonicalInstant(v.window_end) };
}
function recordSemantic(v: Record<string, unknown>) {
  const result: Record<string, unknown> = { previous_observation_id: null, correction_reason: null, counts: null, units: [], exceptions: [], ...clone(v) };
  if (Array.isArray(result.exceptions)) result.exceptions = result.exceptions.map(e => mpRecord(e) ? { issue: null, disposition: null, ...e } : e);
  if (mpRecord(result.scope)) result.scope = { ...result.scope, window_start: canonicalInstant(result.scope.window_start), window_end: canonicalInstant(result.scope.window_end) };
  if (mpRecord(result.observed)) result.observed = { ...result.observed, occurred_at: canonicalInstant(result.observed.occurred_at, true), effective_at: result.observed.effective_at == null ? null : canonicalInstant(result.observed.effective_at, true) };
  return result;
}
export function nativeSemantic(payload: NativePayload): Record<string, unknown> {
  const result: Record<string, unknown> = clone(payload); delete result.confirmation_token;
  if ("details" in payload) { result.statistics ??= null; result.visibility ??= "private"; result.details = detailsSemantic(payload.details); result.statistics = statisticsSemantic(payload.statistics ?? null); }
  else result.record = recordSemantic(payload.record);
  return result;
}
function validDetails(v: unknown): v is NativeDetails {
  return mpRecord(v) && mpUuid(v.pilot_id) && basis(v.basis) && typeof v.purpose === "string" && !!v.purpose.trim() && readSource(v.source) && nullableRef(v.manufacturing_baseline ?? null, "manufacturing_baseline") && nullableRef(v.line ?? null, "line");
}
export function validNativeRecord(v: unknown): v is NativeRecord {
  if (!mpRecord(v) || !mpUuid(v.observation_id) || !mpRevision(v.expected_pilot_revision) || !mpRecord(v.scope) || !basis(v.scope.basis) || !mpRecord(v.observed) || !validQualitySource(v.source) || !validQualitySource(v.observed.source) || typeof v.observed.occurred_at !== "string" || !Number.isFinite(Date.parse(v.observed.occurred_at))) return false;
  const counts = v.counts ?? null, units = v.units ?? [];
  if ((counts === null) === (!Array.isArray(units) || !units.length)) return false;
  if (counts !== null && (!mpRecord(counts) || !nativeCountFields.every(key => counts[key] === null || (typeof counts[key] === "number" && Number.isSafeInteger(counts[key]) && Number(counts[key]) >= 0 && Number(counts[key]) <= 1e12)))) return false;
  if (!Array.isArray(units) || !units.every(u => mpRecord(u) && ref(u.sample, "sample") && validQualitySource(u.source))) return false;
  return (v.previous_observation_id == null || mpUuid(v.previous_observation_id)) && Array.isArray(v.exceptions ?? []) && (v.exceptions as unknown[] | undefined ?? []).every(e => mpRecord(e) && typeof e.key === "string" && typeof e.description === "string" && validQualitySource(e.source) && nullableRef(e.issue ?? null, "issue"));
}
export function validNativeCommand(v: unknown): v is NativeCommand {
  if (!mpRecord(v) || !mpUuid(v.category_id) || !mpUuid(v.product_id) || !mpUuid(v.command_id) || !mpUuid(v.idempotency_key) || !mpRevision(v.expected_revision) || !reads(v.source_read_set) || !mpRecord(v.payload) || !nativeOperations.includes(v.operation as NativeOperation)) return false;
  if (v.payload.confirmation_token != null && !token(v.payload.confirmation_token)) return false;
  return v.operation === nativeOperations[0] ? mpUuid(v.payload.project_id) && validDetails(v.payload.details) && ["private", "category", "audience"].includes(String(v.payload.visibility ?? "private")) && (v.payload.statistics == null || mpRecord(v.payload.statistics)) : mpUuid(v.payload.pilot_id) && mpRevision(v.payload.expected_pilot_revision) && validNativeRecord(v.payload.record) && v.payload.expected_pilot_revision === v.payload.record.expected_pilot_revision;
}
export function nativePayloadReads(payload: NativePayload): SourceRead[] {
  const values = new Map<string, number>();
  function visit(value: unknown) { if (Array.isArray(value)) value.forEach(visit); else if (mpRecord(value)) { if (value.kind === "artifact") { if (!validQualitySource(value)) throw new Error("原文须为实际完整行定位。"); const old = values.get(value.id); if (old && old !== value.revision) throw new Error("同一资料版本冲突。"); values.set(value.id, value.revision); } else Object.values(value).forEach(visit); } }
  visit(payload); return [...values].map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision }));
}
export function newNativeCommand(scope: NativeScope, revision: number, operation: NativeOperation, payload: NativePayload): NativeCommand {
  const value = { category_id: scope.categoryId, product_id: scope.productId, command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation, expected_revision: revision, payload: clone(payload), source_read_set: nativePayloadReads(payload) };
  if (!validNativeCommand(value) || value.payload.confirmation_token != null || ("project_id" in payload && payload.project_id !== scope.projectId)) throw new Error("请选择本项目实际批次与完整原文材料。");
  return value;
}
function sameCommand(a: NativeCommand, b: NativeCommand, includeReads = true) {
  return (["category_id", "product_id", "command_id", "idempotency_key", "operation", "expected_revision"] as const).every(key => a[key] === b[key]) && mpSame(nativeSemantic(a.payload), nativeSemantic(b.payload)) && (!includeReads || mpSame(a.source_read_set, b.source_read_set));
}
function validReview(value: unknown, command: NativeCommand, scope: NativeScope, purpose: string): value is NativeReview {
  if (command.category_id !== scope.categoryId || command.product_id !== scope.productId || ("project_id" in command.payload && command.payload.project_id !== scope.projectId) || !mpRecord(value) || value.operation !== command.operation || !conservative(value.after) || !mpRecord(value.after) || !gapRows(value.after.gaps) || !mpRecord(value.authority) || value.authority.subject_id !== scope.principalId || value.authority.operation !== command.operation || value.authority.purpose !== purpose || value.authority.authorized !== true || value.authority.qualified !== true || !Array.isArray(value.authority.roles) || !value.authority.roles.includes("manufacturing") || !mpRecord(value.authority.scope) || value.authority.scope.product_id !== scope.productId || value.authority.scope.project_id !== scope.projectId || !reads(value.required_source_read_set) || !mpSame(value.required_source_read_set, command.source_read_set) || typeof value.effect !== "string") return false;
  const p = nativeSemantic(command.payload), after = value.after;
  if (command.operation === nativeOperations[0]) return mpRecord(after.details) && mpSame(detailsSemantic(after.details), p.details) && mpSame(statisticsSemantic(mpRecord(after.statistics_basis) ? after.statistics_basis : null), p.statistics);
  return mpRecord(after.record) && mpSame(recordSemantic(after.record), p.record) && after.pilot_id === p.pilot_id && after.pilot_revision_before === p.expected_pilot_revision;
}
export function nativeInputs(value: unknown, original: NativeCommand, scope: NativeScope, purpose: string): NativeCommand | null {
  if (!mpRecord(value) || !validNativeCommand(value.command) || value.command.payload.confirmation_token != null || !sameCommand(value.command, original, false) || !validReview(value.review, value.command, scope, purpose)) return null;
  const command = value.command;
  return original.source_read_set.every(r => command.source_read_set.some(a => mpSame(a, r))) ? command : null;
}
export function nativePrepared(value: unknown, original: NativeCommand, scope: NativeScope, purpose: string, now = Date.now()): NativePrepared | null {
  if (!mpRecord(value) || value.write_tier === "T2" || value.named_decision === true || !validNativeCommand(value.command) || !token(value.confirmation_token) || value.command.payload.confirmation_token !== value.confirmation_token || !sameCommand(value.command, original) || !validReview(value.review, value.command, scope, purpose) || typeof value.expires_at !== "string" || !/(?:Z|[+-]\d{2}:\d{2})$/.test(value.expires_at) || !Number.isFinite(Date.parse(value.expires_at)) || Date.parse(value.expires_at) <= now) return null;
  return value as NativePrepared;
}
export function nativePreviewExpired(expiresAt: string, now = Date.now()) { return !Number.isFinite(Date.parse(expiresAt)) || Date.parse(expiresAt) <= now; }
export function nativeReceipt(v: unknown, command: NativeCommand): v is NativeReceipt {
  const create = "details" in command.payload;
  return mpRecord(v) && mpUuid(v.id) && v.operation === command.operation && v.subject_type === (create ? "pilot_run" : "pilot_observation") && v.subject_id === (create ? (command.payload as NativeCreatePayload).details.pilot_id : (command.payload as NativeResultPayload).record.observation_id) && v.subject_revision === (create ? 1 : (command.payload as NativeResultPayload).expected_pilot_revision + 1);
}
export async function runNativeRequest(api: NativeApi, pending: NativePending, scope: NativeScope, purpose: string, onStage: (value: NativePending) => void, active: () => boolean) {
  if (!validNativeCommand(pending.command) || !["inputs", "preview", "execute"].includes(pending.stage) || pending.command.category_id !== scope.categoryId || pending.command.product_id !== scope.productId || ("project_id" in pending.command.payload && pending.command.payload.project_id !== scope.projectId) || (pending.stage === "execute" ? !token(pending.command.payload.confirmation_token) : pending.command.payload.confirmation_token != null)) throw new Error("原试产请求范围或阶段不一致。");
  let step = pending; if (!active()) return null;
  if (step.stage === "inputs") { const raw = await api<unknown>(`v1/products/${scope.productId}/pilots/inputs`, step.command); if (!active()) return null; const command = nativeInputs(raw, step.command, scope, purpose); if (!command) throw new Error("服务器未返回与本次范围和本人一致的完整材料。"); step = { stage: "preview", command }; onStage(step); }
  if (step.stage === "preview") { const raw = await api<unknown>("v1/commands/preview", step.command); if (!active()) return null; const prepared = nativePrepared(raw, step.command, scope, purpose); if (!prepared) throw new Error("尚未取得本次完整一次确认预览。"); return { stage: "preview" as const, prepared }; }
  const raw = await api<unknown>("v1/commands", step.command); if (!active()) return null; if (!nativeReceipt(raw, step.command)) throw new Error("原提交结果尚未核实，请保留原请求。"); return { stage: "saved" as const, receipt: raw };
}
export function nativeItem(v: unknown, projectId: string): v is NativePilotItem {
  if (!mpRecord(v) || v.schema_version !== "pdos-native-pilot-v1" || v.project_id !== projectId || !conservative(v) || !mpRecord(v.pilot) || !mpUuid(v.pilot.id) || v.pilot.revision !== 1 || !validDetails(v.pilot.details) || v.pilot.id !== v.pilot.details.pilot_id || !gapRows(v.pilot.gaps) || !mpUuid(v.pilot.receipt_id) || !mpRecord(v.current) || !mpRevision(v.current.revision) || v.current.epoch !== v.current.revision || !Array.isArray(v.observations)) return false;
  if (!v.observations.every((row, index) => mpRecord(row) && mpUuid(row.id) && row.revision === index + 2 && validNativeRecord(row.record) && row.record.observation_id === row.id && row.record.expected_pilot_revision === index + 1 && gapRows(row.gaps) && mpUuid(row.receipt_id))) return false;
  return v.current.revision === v.observations.length + 1 && v.current.latest_observation_id === (v.observations.at(-1)?.id ?? null);
}
export function blankNativeLocal(scope: NativeScope): NativeLocal { return { schema_version: 1, scope: clone(scope), create: { pilotId: "", lotId: "", publicationId: "", line: null, source: null, statistics: null, visibility: "private" }, selectedPilotId: "", results: {}, pending: null, receipt: null }; }
export function restoreNativeLocal(value: unknown, scope: NativeScope): NativeLocal | null {
  if (!mpRecord(value) || value.schema_version !== 1 || !mpSame(value.scope, scope) || !mpRecord(value.create)) return null;
  const create = value.create;
  if (!["pilotId", "lotId", "publicationId"].every(key => typeof create[key] === "string") || !["private", "category", "audience"].includes(String(create.visibility)) || !nullableRef(create.line, "line") || !(create.source === null || validQualitySource(create.source)) || !(create.statistics === null || mpRecord(create.statistics)) || typeof value.selectedPilotId !== "string" || !mpRecord(value.results) || !Object.values(value.results).every(validNativeRecord)) return null;
  if (value.pending !== null) {
    const waiting = value.pending;
    if (!mpRecord(waiting) || !["inputs", "preview", "execute"].includes(String(waiting.stage)) || !validNativeCommand(waiting.command) || waiting.command.category_id !== scope.categoryId || waiting.command.product_id !== scope.productId || (waiting.stage === "execute" ? !token(waiting.command.payload.confirmation_token) : waiting.command.payload.confirmation_token != null) || value.receipt !== null) return null;
    const p = waiting.command.payload;
    if ("details" in p ? p.project_id !== scope.projectId || p.details.pilot_id !== create.pilotId || (p.details.basis.lot as NativeRef).id !== create.lotId || !mpSame(p.details.source, create.source) || (mpRecord(p.details.manufacturing_baseline) ? p.details.manufacturing_baseline.id : "") !== create.publicationId || !mpSame(p.details.line ?? null, create.line) || !mpSame(statisticsSemantic(p.statistics), statisticsSemantic(create.statistics as Record<string, unknown> | null)) || p.visibility !== create.visibility : p.pilot_id !== value.selectedPilotId || !mpSame(recordSemantic(p.record), recordSemantic(value.results[p.pilot_id] as NativeRecord))) return null;
  }
  return value as unknown as NativeLocal;
}
export function sourceFree(value: unknown): unknown {
  if (Array.isArray(value)) return value.map(sourceFree);
  if (!mpRecord(value)) return value;
  return Object.fromEntries(Object.entries(value).filter(([key, child]) => !validQualitySource(child) && !((key === "source" || key === "disposition") && child === null)).map(([key, child]) => [key, sourceFree(child)]));
}
export function nativeOriginalStatistics(pilotId: string, statistics: Record<string, unknown>) { return { schema_version: "pdos-pilot-statistics-declaration-v1", pilot_id: pilotId, statistics: sourceFree(statisticsSemantic(statistics)) }; }
export function nativeOriginalResult(pilotId: string, record: NativeRecord) { return { schema_version: "pdos-pilot-result-values-v1", pilot_id: pilotId, record: sourceFree(recordSemantic(record)) }; }
async function originalLine(source: DefinitionSource, line: number) { const ref = await qualitySource(source, line), quote = sourceLines(source.content)[line - 1]; let value: unknown; try { value = JSON.parse(quote); } catch { throw new Error("须选择已登记、完整且符合支持结构的JSON原文行。"); } return { ref, value }; }
export async function importNativeStatistics(source: DefinitionSource, line: number, pilotId: string): Promise<Record<string, unknown> & { source: NativeSource }> {
  const original = await originalLine(source, line);
  if (!mpRecord(original.value) || original.value.schema_version !== "pdos-pilot-statistics-declaration-v1" || original.value.pilot_id !== pilotId || !mpRecord(original.value.statistics)) throw new Error("原文须明确本次Pilot身份与完整统计声明。");
  const statistics = { ...original.value.statistics, source: original.ref };
  if (!mpSame(original.value, nativeOriginalStatistics(pilotId, statistics))) throw new Error("原文须包含typed默认字段，且不得改写统计声明。");
  return statistics;
}
export async function importNativeResult(source: DefinitionSource, line: number, pilot: NativePilotItem) {
  const original = await originalLine(source, line);
  if (!mpRecord(original.value) || original.value.schema_version !== "pdos-pilot-result-values-v1" || original.value.pilot_id !== pilot.pilot.id || !mpRecord(original.value.record) || !mpRecord(original.value.record.observed)) throw new Error("原文须绑定所选Pilot与完整原始观察值。");
  const raw = original.value.record;
  const record = { ...raw, source: original.ref, observed: { ...raw.observed as Record<string, unknown>, source: original.ref }, units: Array.isArray(raw.units) ? raw.units.map(v => mpRecord(v) ? { ...v, source: original.ref } : v) : [], exceptions: Array.isArray(raw.exceptions) ? raw.exceptions.map(v => mpRecord(v) ? { ...v, source: original.ref, disposition: null } : v) : [] };
  if (!validNativeRecord(record) || record.expected_pilot_revision !== pilot.current.revision || record.previous_observation_id !== pilot.current.latest_observation_id || !mpSame(record.scope.basis, pilot.pilot.details.basis) || !mpSame(original.value, nativeOriginalResult(pilot.pilot.id, record))) throw new Error("原观察须对应当前Pilot版本、精确批次/配置、前驱观察与完整原文值。");
  return record;
}
export async function requireNativeOriginal(record: NativeRecord, pilotId: string, sources: DefinitionSource[]) {
  const row = sources.find(s => s.id === record.source.id && s.revision === record.source.revision);
  if (!row) throw new Error("原观察资料当前不可读取，请刷新后重核。");
  const line = Number(record.source.position.split(";")[0].slice(5)), original = await originalLine(row, line);
  if (!mpSame(original.ref, record.source) || !mpSame(original.value, nativeOriginalResult(pilotId, record))) throw new Error("当前录入值与已登记原文不一致；请准备对应实际原件后重新选择。");
}
export function makeNativeDetails(id: string, purpose: string, build: Build, lot: BuildLot, actual: ActualConfiguration, source: NativeSource, publication: NativeRef | null, line: NativeRef | null): NativeDetails {
  if (lot.build_id !== build.id || lot.project_id !== build.project_id || lot.actual_configuration_id !== actual.id || actual.build_id !== build.id || actual.project_id !== build.project_id) throw new Error("批次与实际配置不属于本项目所选Build。");
  const named = (kind: string, value: { id: string; revision: number }) => ({ kind, id: value.id, revision: value.revision });
  return detailsSemantic({ pilot_id: id, purpose, basis: { build: named("build", build), lot: named("build_lot", lot), actual_configuration: named("actual_configuration", actual), engineering_configuration: named("engineering_configuration", actual.actual.engineering_configuration), process_revision: named("process_revision", actual.actual.manufacturing_configuration), unit: lot.unit }, manufacturing_baseline: publication, line, source }) as NativeDetails;
}
export function nativeRate(value: unknown): string { if (!mpRecord(value) || value.value == null || value.state !== "known" || value.partition_complete !== true || typeof value.denominator !== "number" || value.denominator <= 0) return "未知"; const n = Number(value.value); return Number.isFinite(n) ? `${(n * 100).toFixed(2)}%（${String(value.numerator)} / ${String(value.denominator)}）` : "未知"; }
