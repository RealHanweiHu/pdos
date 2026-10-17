import type { DefinitionReference, DefinitionSource } from "@/lib/product-view";
import type { SourceRead } from "@/lib/project-plan-view";
import type { PreparationItem, PreparationDocument, PreparationGap, VerificationPreparation } from "@/lib/build-verification-view";

export type ProfessionalApi = <T>(path: string, body?: unknown) => Promise<T>;
export type ProfessionalPreparation = VerificationPreparation & { sha256: string; authority?: ProfessionalAuthorities; capabilities: Record<string, boolean> };
export type MethodStatus = "applicable" | "not_applicable" | "unknown";
export type MethodAssessment = { item_id: string; status: MethodStatus; conditions: string[]; reason: string; sources: DefinitionReference[] };
export type ResourceIntent = { kind: "equipment" | "fixture" | "person" | "line" | "tooling"; label: string; resource_id?: string | null; expected_revision?: number | null; units: string | null };
export type CreateProfessionalPayload = { request_id: string; preparation_id: string; expected_preparation_revision: number; preparation_sha256: string; reason: string };
export type MethodProfessionalPayload = { request_id: string; expected_request_revision: number; assessments: MethodAssessment[]; reason: string; confirmation_token?: string | null };
export type ScheduleProfessionalPayload = { request_id: string; expected_request_revision: number; start: string; finish: string; original_timezone: string; resource_intents: ResourceIntent[]; duration_basis: DefinitionReference | null; calendar_source: DefinitionReference | null; sources: DefinitionReference[]; reason: string };
export const professionalOperations = ["verification.request.create", "verification.method.prepare", "verification.schedule.propose"] as const;
export type ProfessionalOperation = typeof professionalOperations[number];
export type ProfessionalPayload = CreateProfessionalPayload | MethodProfessionalPayload | ScheduleProfessionalPayload;
export type ProfessionalCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: ProfessionalOperation; source_read_set: SourceRead[]; payload: ProfessionalPayload };
export type PendingProfessional = { stage: "preview" | "execute"; command: ProfessionalCommand };
export const methodStatusNames: Record<MethodStatus, string> = { applicable: "方法适用（具名核对）", not_applicable: "方法不适用", unknown: "适用性未知 · 待核对" };
export const professionalRequestStateNames = { draft: "正式请求草稿", offered: "已提出交样", accepted: "已部分或全部接收", scheduled: "已具名承诺，尚未实际开测", executing: "已记录实际开测，测试结果尚未登记", reported: "已登记最终结果，专业处置另行核对", disposed: "已登记具名处置" } as const;
export type ProfessionalRequestStatus = keyof typeof professionalRequestStateNames;
export const professionalOperationNames: Record<ProfessionalOperation, string> = { "verification.request.create": "建立正式验证草稿请求", "verification.method.prepare": "逐项方法适用核对", "verification.schedule.propose": "保存资源意向窗口" };
export const resourceKindNames: Record<ResourceIntent["kind"], string> = { equipment: "设备", fixture: "夹具", person: "人员", line: "产线", tooling: "工装" };
export const professionalRecord = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
export function professionalStable(value: unknown): unknown { return Array.isArray(value) ? value.map(professionalStable) : professionalRecord(value) ? Object.fromEntries(Object.keys(value).sort().map(key => [key, professionalStable(value[key])])) : value; }
export const professionalSame = (left: unknown, right: unknown): boolean => JSON.stringify(professionalStable(left)) === JSON.stringify(professionalStable(right));
export function professionalTime(value: unknown): string | null {
  if (typeof value !== "string") return null;
  const match = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?(Z|[+-]\d{2}:\d{2})$/.exec(value);
  if (!match || !Number.isFinite(Date.parse(value))) return null;
  const date = new Date(0); date.setUTCFullYear(Number(match[1]), Number(match[2]), 0);
  if (Number(match[2]) < 1 || Number(match[2]) > 12 || Number(match[3]) < 1 || Number(match[3]) > date.getUTCDate() || Number(match[4]) > 23 || Number(match[5]) > 59 || Number(match[6] ?? 0) > 59) return null;
  const fraction = (match[7] ?? "").padEnd(6, "0").replace(/0+$/, "");
  return new Date(Date.parse(value.replace(/\.\d+(?=Z|[+-]\d{2}:\d{2}$)/i, ""))).toISOString().replace(/\.000Z$/, `${fraction ? `.${fraction}` : ""}Z`);
}
export function professionalZone(value: string): string { const zone = value.trim(); if (!zone || zone.length > 120) throw new Error("请保留有效 IANA 原时区，例如 America/Los_Angeles。"); try { new Intl.DateTimeFormat("zh-CN", { timeZone: zone }); } catch { throw new Error("请填写有效的 IANA 原时区。"); } return zone; }
export function professionalReason(value: string): string { const result = value.trim(); if (!result || result.length > 2000) throw new Error("请填写 1–2000 字的具名核对原因。"); return result; }
export function professionalReferenceKey(ref: DefinitionReference): string { return JSON.stringify([ref.artifact_id, ref.expected_revision, ref.line, ref.quote]); }
export function preciseProfessionalReference(source: DefinitionSource, line: number, quote: string): DefinitionReference {
  const cleaned = quote.trim(); if (source.status !== "active" || !Number.isSafeInteger(line) || line < 1 || !cleaned || cleaned.length > 4000 || !source.content.split(/\r?\n/)[line - 1]?.includes(cleaned)) throw new Error("请选择当前有效资料，并在所选原文行保留可精确核对的摘录。");
  return { artifact_id: source.id, expected_revision: source.revision, line, quote: cleaned };
}
export function professionalReads(...sets: SourceRead[][]): SourceRead[] {
  const reads = new Map<string, number>(); for (const read of sets.flat()) { if (!read.artifact_id || !Number.isSafeInteger(read.expected_revision) || read.expected_revision < 1) throw new Error("来源读集尚不完整，请刷新固定请求与职责事实。"); if (reads.has(read.artifact_id) && reads.get(read.artifact_id) !== read.expected_revision) throw new Error("同一资料的固定版本不一致，请先重新核对。"); reads.set(read.artifact_id, read.expected_revision); }
  return [...reads].sort(([a], [b]) => a.localeCompare(b)).map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision }));
}
export const professionalReferenceReads = (refs: DefinitionReference[]): SourceRead[] => professionalReads(refs.map(ref => ({ artifact_id: ref.artifact_id, expected_revision: ref.expected_revision })));
export function professionalUnits(value: string): string | null { const cleaned = value.trim(); if (!cleaned) return null; const match = /^(\d+)(?:\.(\d+))?$/.exec(cleaned); if (!match || !/[1-9]/.test(cleaned) || (match[1].replace(/^0+/, "").length || 1) + (match[2]?.length ?? 0) > 24 || (match[2]?.length ?? 0) > 12) throw new Error("资源意向数量须大于零，最多 12 位小数；未知留空，不补零。"); return cleaned; }
export type MethodDraft = { itemId: string; status: MethodStatus; conditions: string; reason: string; references: DefinitionReference[] };
export type ResourceDraft = { kind: ResourceIntent["kind"]; label: string; units: string };
export type ScheduleDraft = { start: string; finish: string; timezone: string; resources: ResourceDraft[]; durationRef: DefinitionReference | null; calendarRef: DefinitionReference | null; references: DefinitionReference[]; reason: string };
export const blankProfessionalSchedule = (): ScheduleDraft => ({ start: "", finish: "", timezone: "", resources: [], durationRef: null, calendarRef: null, references: [], reason: "" });
export const blankProfessionalMethods = (items: PreparationItem[]): MethodDraft[] => items.map(item => ({ itemId: item.id, status: "unknown", conditions: "", reason: "", references: [] }));
export type ProfessionalDrafts = { preparationId: string; createId: string; createReason: string; requestId: string; versionId: string; methodVersion: string; methods: MethodDraft[]; methodReason: string; scheduleVersion: string; schedule: ScheduleDraft; references: DefinitionReference[] };
const validRef = (value: unknown): value is DefinitionReference => professionalRecord(value) && typeof value.artifact_id === "string" && !!value.artifact_id && Number.isSafeInteger(value.expected_revision) && Number(value.expected_revision) > 0 && Number.isSafeInteger(value.line) && Number(value.line) > 0 && typeof value.quote === "string" && !!value.quote && value.quote.length <= 4000;
const validRefs = (value: unknown): value is DefinitionReference[] => Array.isArray(value) && value.every(validRef);
export function restoreProfessional(value: unknown, productId: string, principalId: string): { draft: ProfessionalDrafts; pending: PendingProfessional | null } | null {
  if (!professionalRecord(value) || value.schema_version !== 1 || value.product_id !== productId || value.principal_id !== principalId || !professionalRecord(value.draft)) return null;
  const draft = value.draft, fields = ["preparationId", "createId", "createReason", "requestId", "versionId", "methodVersion", "methodReason", "scheduleVersion"];
  if (!fields.every(key => typeof draft[key] === "string") || !validRefs(draft.references) || !Array.isArray(draft.methods) || draft.methods.length > 100
    || !draft.methods.every(row => professionalRecord(row) && typeof row.itemId === "string" && Object.hasOwn(methodStatusNames, String(row.status)) && typeof row.conditions === "string" && typeof row.reason === "string" && validRefs(row.references)) || !professionalRecord(draft.schedule)) return null;
  const schedule = draft.schedule;
  if (!["start", "finish", "timezone", "reason"].every(key => typeof schedule[key] === "string") || !Array.isArray(schedule.resources) || !schedule.resources.every(row => professionalRecord(row) && Object.hasOwn(resourceKindNames, String(row.kind)) && typeof row.label === "string" && typeof row.units === "string")
    || !validRefs(schedule.references) || !(schedule.durationRef === null || validRef(schedule.durationRef)) || !(schedule.calendarRef === null || validRef(schedule.calendarRef))) return null;
  if (value.pending !== null) {
    const pending = value.pending; if (!professionalRecord(pending) || !["preview", "execute"].includes(String(pending.stage)) || !professionalRecord(pending.command)) return null;
    const command = pending.command;
    if (command.product_id !== productId || typeof command.command_id !== "string" || !command.command_id || typeof command.idempotency_key !== "string" || !command.idempotency_key || !professionalOperations.includes(command.operation as ProfessionalOperation) || !Number.isSafeInteger(command.expected_revision) || Number(command.expected_revision) < 1 || !Array.isArray(command.source_read_set) || !command.source_read_set.every(ref => professionalRecord(ref) && typeof ref.artifact_id === "string" && Number.isSafeInteger(ref.expected_revision) && Number(ref.expected_revision) > 0) || !professionalRecord(command.payload)) return null;
    const payload = command.payload;
    if (typeof payload.request_id !== "string" || typeof payload.reason !== "string") return null;
    if (command.operation === "verification.request.create") { if (pending.stage !== "execute" || typeof payload.preparation_id !== "string" || !Number.isSafeInteger(payload.expected_preparation_revision) || Number(payload.expected_preparation_revision) < 1 || typeof payload.preparation_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(payload.preparation_sha256)) return null; }
    else {
      if (!Number.isSafeInteger(payload.expected_request_revision) || Number(payload.expected_request_revision) < 1) return null;
      if (command.operation === "verification.method.prepare") {
        if (!Array.isArray(payload.assessments) || !payload.assessments.length || !payload.assessments.every(row => professionalRecord(row) && typeof row.item_id === "string" && Object.hasOwn(methodStatusNames, String(row.status)) && typeof row.reason === "string" && Array.isArray(row.conditions) && row.conditions.every(condition => typeof condition === "string") && validRefs(row.sources)) || pending.stage === "execute" && (typeof payload.confirmation_token !== "string" || payload.confirmation_token.length < 20)) return null;
      } else if (pending.stage !== "execute" || !professionalTime(payload.start) || !professionalTime(payload.finish) || typeof payload.original_timezone !== "string" || !Array.isArray(payload.resource_intents) || !validRefs(payload.sources) || !(payload.duration_basis === null || validRef(payload.duration_basis)) || !(payload.calendar_source === null || validRef(payload.calendar_source))) return null;
    }
  }
  return { draft: draft as unknown as ProfessionalDrafts, pending: value.pending as PendingProfessional | null };
}

// These fixed preparation DTOs remain separate from professional authority and physical events.
export type ProfessionalRequest = {
  id: string; request_id: string; revision: number; previous_request_id: string | null; previous_revision: number | null;
  preparation_id: string; preparation_revision: number; preparation_sha256: string; project_id: string; owner_id: string; visibility: string;
  build: { id: string; revision: number; engineering_configuration: { id: string; revision: number }; manufacturing_configuration: { id: string; revision: number } };
  title: string; purpose: string; status: ProfessionalRequestStatus; items: PreparationItem[]; documents: PreparationDocument[]; request_snapshot: Record<string, unknown>;
  document_gaps: PreparationGap[]; coverage_gaps: PreparationGap[]; method_assessments: Record<string, unknown>[]; window_proposals: Record<string, unknown>[];
  first_requested_at: string | null; created_at: string | null; sources: DefinitionReference[]; required_source_read_set: SourceRead[];
  source_status: string; is_current: boolean; freshness: string; capabilities: Record<string, boolean>; zero_occupancy: boolean; authority?: ProfessionalAuthorities;
} & Record<string, unknown>;
export type ProfessionalAuthority = { authorized: boolean; roles: string[]; qualified: boolean | null; reason_codes: string[]; fact_refs: { id: string; revision: number; epoch: number; kind: string; role: string; nature: string; issuer_key: string; issuer_version: string }[]; facts_revision: string | null; valid_until: string | null; synthetic: boolean; required_source_read_set: SourceRead[]; operation: string; purpose: string; subject_id: string; scope: { project_id: string; product_id: string } };
export type ProfessionalAuthorities = Partial<Record<"request_create" | "method_prepare" | "schedule_propose", ProfessionalAuthority>>;
export type ProfessionalList = { requests: ProfessionalRequest[]; preparations: ProfessionalPreparation[]; current_by_request: Record<string, { request_version_id: string; revision: number }>; capabilities: Record<string, boolean>; blockers: unknown[]; authority_by_project: unknown[]; has_more: boolean; unavailable_count: number };
export type ProfessionalPreview = { command: ProfessionalCommand; expires_at: string; review: { operation: ProfessionalOperation; before: ProfessionalRequest | null; after: ProfessionalRequest; effect: string; reason: string; authority: ProfessionalAuthority; gap_changes?: unknown } };
export const emptyProfessional: ProfessionalList = { requests: [], preparations: [], current_by_request: {}, capabilities: {}, blockers: [], authority_by_project: [], has_more: false, unavailable_count: 0 };
export function professionalCapability(value: unknown, key: string): boolean { return professionalRecord(value) && value[key] === true; }
export function professionalAuthorityReads(authority: ProfessionalAuthority | undefined): SourceRead[] { return authority ? professionalReads(authority.required_source_read_set ?? []) : []; }
export function professionalCreate(preparation: ProfessionalPreparation, requestId: string, reason: string): CreateProfessionalPayload {
  if (!professionalCapability(preparation.capabilities, "request_create") || preparation.source_status !== "current") throw new Error("当前固定准备版没有服务器授予的建请求能力，请核对职责、资格与来源。");
  if (!/^[0-9a-f]{64}$/.test(preparation.sha256)) throw new Error("固定准备内容摘要尚未取得，请刷新核对。");
  return { request_id: requestId, preparation_id: preparation.id, expected_preparation_revision: preparation.revision, preparation_sha256: preparation.sha256, reason: professionalReason(reason) };
}
export function professionalMethods(request: ProfessionalRequest, draft: MethodDraft[], reason: string): MethodProfessionalPayload {
  if (["reported", "disposed"].includes(request.status) || !professionalCapability(request.capabilities, "method_prepare") || !request.is_current || request.source_status !== "current") throw new Error("当前请求版不允许专业方法核对，请刷新资格、来源与请求版本。");
  if (draft.length !== request.items.length || new Set(draft.map(row => row.itemId)).size !== draft.length || draft.some(row => !request.items.some(item => item.id === row.itemId))) throw new Error("必须逐项覆盖固定请求的全部测试项，不能替换或扩大测试范围。");
  return { request_id: request.request_id, expected_request_revision: request.revision, assessments: draft.map(row => {
    if (!Object.hasOwn(methodStatusNames, row.status)) throw new Error("请明确选择适用、不适用或未知。");
    if (row.status === "applicable" && !row.references.length) throw new Error("具名确认方法适用需要可精确核验的原文依据。");
    const conditions = row.conditions.split(/\r?\n/).map(value => value.trim()).filter(Boolean); if (conditions.some(value => value.length > 2000)) throw new Error("每条条件不超过 2000 字。");
    return { item_id: row.itemId, status: row.status, conditions, reason: professionalReason(row.reason), sources: row.references.map(ref => ({ ...ref })) };
  }), reason: professionalReason(reason) };
}
export function professionalSchedule(request: ProfessionalRequest, draft: ScheduleDraft, now = Date.now()): ScheduleProfessionalPayload {
  if (["reported", "disposed"].includes(request.status) || !professionalCapability(request.capabilities, "schedule_propose") || !request.is_current || request.source_status !== "current") throw new Error("当前请求版不允许资源意向窗口，请核对当前职责、资格和来源。");
  const start = professionalTime(draft.start.trim()), finish = professionalTime(draft.finish.trim());
  if (!start || !finish || Date.parse(start) < now || Date.parse(finish) <= Date.parse(start)) throw new Error("请填写带时区且尚未开始的明确窗口，结束须晚于开始；最终以服务器时钟核对。");
  return { request_id: request.request_id, expected_request_revision: request.revision, start, finish, original_timezone: professionalZone(draft.timezone), resource_intents: draft.resources.map(resource => {
    const label = resource.label.trim(); if (!label || label.length > 2000 || !Object.hasOwn(resourceKindNames, resource.kind)) throw new Error("每个资源意向须有真实名称和明确类型，缺资源身份仍保留未知。");
    return { kind: resource.kind, label, resource_id: null, expected_revision: null, units: professionalUnits(resource.units) };
  }), duration_basis: draft.durationRef, calendar_source: draft.calendarRef, sources: draft.references.map(ref => ({ ...ref })), reason: professionalReason(draft.reason) };
}
export function professionalCommand(product: { id: string; revision: number }, operation: ProfessionalOperation, payload: ProfessionalPayload, reads: SourceRead[], commandId: string, key: string): ProfessionalCommand { return { command_id: commandId, idempotency_key: key, product_id: product.id, expected_revision: product.revision, operation, payload, source_read_set: professionalReads(reads) }; }
export function validProfessionalPreview(value: unknown, original: ProfessionalCommand, request: ProfessionalRequest, now = Date.now()): value is ProfessionalPreview {
  if (!professionalRecord(value) || !professionalRecord(value.command) || !professionalRecord(value.command.payload) || !professionalRecord(value.review) || !professionalRecord(value.review.before) || !professionalRecord(value.review.after) || !professionalRecord(value.review.authority)
    || original.operation !== "verification.method.prepare" || typeof value.expires_at !== "string" || !professionalTime(value.expires_at) || Date.parse(value.expires_at) <= now) return false;
  const command = value.command, fields = command.payload; if (!professionalRecord(fields)) return false; const payload = { ...fields }; delete payload.confirmation_token;
  const before = value.review.before, after = value.review.after;
  return ["command_id", "idempotency_key", "product_id", "expected_revision", "operation"].every(key => command[key] === original[key as keyof ProfessionalCommand])
    && typeof fields.confirmation_token === "string" && !!fields.confirmation_token && professionalSame(payload, original.payload) && professionalSame(command.source_read_set, original.source_read_set)
    && value.review.operation === original.operation && typeof value.review.effect === "string" && !!value.review.effect && before.id === request.id && before.revision === request.revision
    && after.request_id === request.request_id && after.status === "draft" && after.zero_occupancy === true && professionalSame(after.items, request.items) && Array.isArray(after.method_assessments);
}
export function validProfessionalReceipt(value: unknown, command: ProfessionalCommand): value is { id: string; subject_id: string; subject_type: "verification_request"; result: Record<string, unknown> } { return professionalRecord(value) && typeof value.id === "string" && !!value.id && typeof value.subject_id === "string" && !!value.subject_id && value.subject_type === "verification_request" && value.operation === command.operation; }
export type ProfessionalOccupancyState = "zero" | "saved_start" | "unknown";
export const professionalOccupancyDescriptions: Record<ProfessionalOccupancyState, string> = {
  zero: "本版尚未产生正式测试资源占用或样件消费；承诺与实际开测分别记录。",
  saved_start: "本版保留已记录的实际开测及随该次开测保存的资源、样件使用；这是历史事实，不表示资源当前可用、占用已释放或样件可再用。明细在测试计划与实际开测入口读取。",
  unknown: "本版实际开测时钟缺失或不完整，保存的占用与样件使用事实尚待核对；不能据结果或处置状态推定零占用、已释放或可再用。",
};
export function professionalOccupancyState(request: ProfessionalRequest): ProfessionalOccupancyState {
  if (!["reported", "disposed"].includes(request.status)) return request.zero_occupancy ? "zero" : "saved_start";
  const snapshot = professionalRecord(request.request_snapshot) ? request.request_snapshot : {}, timeline = professionalRecord(snapshot.timeline) ? snapshot.timeline : {}, start = timeline.actual_start;
  if (!professionalRecord(start) || !professionalTime(start.occurred_at) || !professionalTime(start.received_at) || typeof start.actor_id !== "string" || !start.actor_id || typeof start.original_timezone !== "string" || !professionalRecord(start.source)) return "unknown";
  const source = start.source;
  if (typeof source.id !== "string" || !source.id || !Number.isSafeInteger(source.revision) || Number(source.revision) < 1 || !["artifact", "domain", "command"].includes(String(source.kind)) || typeof source.position !== "string" || !source.position) return "unknown";
  try { professionalZone(start.original_timezone); } catch { return "unknown"; }
  return "saved_start";
}
export function normalizeProfessional(value: unknown, projectId = ""): ProfessionalList {
  if (!professionalRecord(value) || !Array.isArray(value.requests) || !Array.isArray(value.preparations) || !professionalRecord(value.current_by_request)) throw new Error("专业验证读模型尚未完整取得，请刷新核对。");
  if (value.requests.some(row => !professionalRecord(row) || typeof row.id !== "string" || typeof row.request_id !== "string" || !Number.isSafeInteger(row.revision) || !Array.isArray(row.items) || !Array.isArray(row.documents) || !Object.hasOwn(professionalRequestStateNames, String(row.status)) || typeof row.zero_occupancy !== "boolean" || (!["reported", "disposed"].includes(String(row.status)) && row.zero_occupancy !== (row.status !== "executing"))) || value.preparations.some(row => !professionalRecord(row) || typeof row.id !== "string" || typeof row.sha256 !== "string" || !Array.isArray(row.items))) throw new Error("固定请求或准备版缺少关键范围信息，未启用写入。");
  return { requests: (value.requests as ProfessionalRequest[]).filter(row => !projectId || row.project_id === projectId), preparations: (value.preparations as ProfessionalPreparation[]).filter(row => !projectId || row.project_id === projectId), current_by_request: value.current_by_request as ProfessionalList["current_by_request"], capabilities: professionalRecord(value.capabilities) ? value.capabilities as Record<string, boolean> : {}, blockers: Array.isArray(value.blockers) ? value.blockers : [], authority_by_project: Array.isArray(value.authority_by_project) ? value.authority_by_project : [], has_more: value.has_more === true, unavailable_count: typeof value.unavailable_count === "number" ? value.unavailable_count : 0 };
}
export function professionalError(failure: unknown): { status?: number; message: string } { const value = professionalRecord(failure) ? failure : {}, status = typeof value.status === "number" ? value.status : undefined; return { status, message: status === 401 || status === 403 ? "当前请求或专业职责范围不可用，请重新核对授权与资格。" : [400, 404, 409, 410, 422].includes(status ?? 0) ? "当前请求、来源、资格或时间窗口不符合办理条件，请刷新后核对具体缺项。" : "尚未取得确定回执，请保留原请求与原标识核对，不另造一次操作。" }; }
