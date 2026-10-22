import type { CommandPlan, EffectivityPlan, Ref, Source } from "../components/change_control/contracts";
import type { DefinitionSource } from "./product-view";
import type { SourceRead } from "./project-plan-view";
import { handoffTime } from "./build-handoff-view";
import { proofClockCurrent } from "./proof-clock";
import type { MaterialRequest } from "./change-source-material";
import { qualityReads, qualityRecord, qualityRevision, qualitySame, qualitySource, qualitySourceKey, qualityTime, validQualitySource, type QualitySource } from "./build-quality-loop-view";

export type OrderApi = <T>(path: string, body?: unknown) => Promise<T>;
export type OrderOperation = "change.selection.decide" | "change.order.prepare";
export const orderNames: Record<OrderOperation, string> = { "change.selection.decide": "具名决定逐项适用性", "change.order.prepare": "准备变更令与明确生效计划" };
export const orderRecord = qualityRecord, orderSame = qualitySame, orderSource = qualitySource, orderSourceKey = qualitySourceKey;
export type OrderSource = QualitySource;
export type OrderItem = CommandPlan["items"][number];
export type OrderChange = { id: string; change_id: string; revision: number; project_id: string; visibility: "private" | "category" | "audience"; status: string; request: Record<string, unknown>; purpose?: string; current?: boolean; source_status?: string };
export type OrderMissing = { code: string; detail: string };
export type OrderSelection = { id: string; revision: number; item: OrderItem; status: "applicable" | "not_applicable" | "unknown"; valid_until: string | null; source: OrderSource; receipt_id: string | null; current: boolean; source_status: string; missing: OrderMissing[]; basis_kind?: string; material_sha256?: string; feedback?: { id: string; revision: number }; feedback_version_id?: string; feedback_sha256?: string; intent_id?: string; executor_id?: string };
export type OrderReadSource = { id: string; revision: number; kind: string; position: string };
export type OrderObject = { ref: Ref; label: string; source: OrderReadSource };
export type FieldIntentTarget = { kind: "field_intent"; feedback: { id: string; revision: number }; executor_id: string };
export type FieldBasisOption = { feedback: { id: string; revision: number }; version_id: string; sha256: string; title: string };
export type OrderContext = { change: OrderChange; policy: { current: true; required_disciplines: string[]; valid_from: string; valid_until: string; nature: string; source: OrderSource } | null; actions: Record<string, unknown>[]; selections: OrderSelection[]; object_options: OrderObject[]; missing: OrderMissing[]; field_basis_options?: FieldBasisOption[]; executor_options?: { id: string; name: string }[]; adoption_condition?: string; old_builds?: { ref: Ref; label: string }[] };
export type OrderCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: OrderOperation; payload: Record<string, unknown>; source_read_set: SourceRead[]; category_id?: string | null };
export type OrderCandidate = { command: OrderCommand; material: Record<string, unknown>; required_source_read_set: SourceRead[] };
export type OrderPending = { stage: "inputs" | "preview" | "execute"; command: OrderCommand };
export type OrderPreview = { command: OrderCommand; expires_at: string | null; write_tier?: string; named_decision?: boolean; review: Record<string, unknown> & { before: Record<string, unknown>; after: Record<string, unknown>; effect: string } };
export type OrderDispositionDraft = { handling: "covered_by_plan" | "reviewed_no_change" | "unknown"; itemIds: string[]; rationale: string; source: OrderSource | null };
export type OrderDraft = { planId: string; selectedSelectionIds: string[]; dispositions: Record<string, OrderDispositionDraft>; expiresAt: string; reason: string; selectionSource: OrderSource | null; candidate: OrderCandidate | null };
export type OrderLocal = { selectedChangeId: string; drafts: Record<string, OrderDraft>; pending: OrderPending | null };
export type FieldPlanDraft = { itemId: string; intentId: string; feedbackKey: string; executorId: string; kind: "new_engineering_configuration" | "new_manufacturing_configuration"; objectKey: string; adoptionMode: boolean; oldBuildKey: string; conditions: string; description: string; verification: string; status: "applicable" | "not_applicable" | "unknown"; validUntil: string; reason: string };
export const blankFieldPlanDraft = (itemId: string, intentId: string): FieldPlanDraft => ({ itemId, intentId, feedbackKey: "", executorId: "", kind: "new_engineering_configuration", objectKey: "", adoptionMode: false, oldBuildKey: "", conditions: "", description: "", verification: "", status: "unknown", validUntil: "", reason: "" });
export const blankOrderLocal = (): OrderLocal => ({ selectedChangeId: "", drafts: {}, pending: null });
export const blankOrderDraft = (planId: string): OrderDraft => ({ planId, selectedSelectionIds: [], dispositions: {}, expiresAt: "", reason: "", selectionSource: null, candidate: null });
export const blankOrderDisposition = (): OrderDispositionDraft => ({ handling: "unknown", itemIds: [], rationale: "", source: null });
export const orderRefKey = (ref: Ref): string => JSON.stringify([ref.kind, ref.id, ref.revision, ref.key ?? null]);
export const fieldBasisKey = (basis: FieldBasisOption) => `${basis.feedback.id}:${basis.feedback.revision}`;
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
const exactKeys = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).every(key => keys.includes(key));
const feedbackRef = (v: unknown): v is { id: string; revision: number } => qualityRecord(v) && exactKeys(v, ["id", "revision"]) && uuid(v.id) && qualityRevision(v.revision);
const fieldIntent = (v: unknown): v is FieldIntentTarget => qualityRecord(v) && exactKeys(v, ["kind", "feedback", "executor_id"]) && v.kind === "field_intent" && feedbackRef(v.feedback) && uuid(v.executor_id);
const validRef = (value: unknown): value is Ref => qualityRecord(value) && uuid(value.id) && qualityRevision(value.revision) && typeof value.kind === "string" && !!value.kind && (value.key == null || typeof value.key === "string");
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(row => typeof row === "string");
const refs = (value: unknown): value is Ref[] => Array.isArray(value) && !!value.length && value.every(validRef);
const readSource = (value: unknown): value is OrderReadSource => qualityRecord(value) && uuid(value.id) && qualityRevision(value.revision) && ["artifact", "domain", "command"].includes(String(value.kind)) && typeof value.position === "string" && !!value.position;
const sources = (value: unknown): value is OrderReadSource[] => Array.isArray(value) && !!value.length && value.every(readSource);
const missing = (value: unknown): value is OrderMissing[] => Array.isArray(value) && value.every(row => qualityRecord(row) && typeof row.code === "string" && typeof row.detail === "string");
function validItem(value: unknown): value is OrderItem {
  if (!qualityRecord(value) || !uuid(value.id) || !["engineering", "manufacturing", "customer", "regulatory"].includes(String(value.discipline)) || !qualityRecord(value.selection) || !qualityRecord(value.intent) || typeof value.verification_requirement !== "string" || !value.verification_requirement.trim()) return false;
  const selection = value.selection, intent = value.intent;
  return refs(selection.objects) && strings(selection.units) && !!selection.units.length && selection.units.every(unit => /^(object|batch|serial):.+/.test(unit)) && strings(selection.conditions) && !!selection.conditions.length && sources(selection.sources) && uuid(intent.id) && ["new_engineering_configuration", "new_manufacturing_configuration", "new_build", "new_test_run", "erp_mes_effectivity"].includes(String(intent.kind)) && refs(intent.basis) && typeof intent.description === "string" && !!intent.description.trim();
}
function validChange(value: unknown): value is OrderChange { return qualityRecord(value) && uuid(value.id) && uuid(value.change_id) && qualityRevision(value.revision) && uuid(value.project_id) && ["private", "category", "audience"].includes(String(value.visibility)) && typeof value.status === "string" && qualityRecord(value.request); }
export function normalizeOrderChanges(value: unknown, projectId = ""): OrderChange[] {
  if (!qualityRecord(value) || !Array.isArray(value.changes) || !value.changes.every(validChange)) throw new Error("变更索引缺少固定版本或项目范围，请刷新核对。");
  if (projectId && value.changes.some(row => row.project_id !== projectId)) throw new Error("变更索引包含其他项目，当前未开放办理。");
  return value.changes.filter(row => row.current === true);
}
export function normalizeOrderContext(value: unknown, changeId: string, projectId = ""): OrderContext {
  if (!qualityRecord(value) || !validChange(value.change) || value.change.change_id !== changeId || (projectId && value.change.project_id !== projectId) || !Array.isArray(value.actions) || !value.actions.every(qualityRecord) || !Array.isArray(value.selections) || !Array.isArray(value.object_options) || !missing(value.missing)) throw new Error("尚未取得所选项目与变更的完整正式办理范围。");
  const policy = value.policy;
  if (policy !== null && (!qualityRecord(policy) || policy.current !== true || !strings(policy.required_disciplines) || !qualityTime(policy.valid_from) || !qualityTime(policy.valid_until) || typeof policy.nature !== "string" || !validQualitySource(policy.source))) throw new Error("政策原文、有效期或专业范围不完整，不能沿用旧政策。");
  if (value.selections.some(row => !qualityRecord(row) || !uuid(row.id) || !qualityRevision(row.revision) || !validItem(row.item) || !["applicable", "not_applicable", "unknown"].includes(String(row.status)) || !(row.valid_until === null || qualityTime(row.valid_until)) || !validQualitySource(row.source) || typeof row.current !== "boolean" || typeof row.source_status !== "string" || !missing(row.missing) || !(uuid(row.receipt_id) || (row.receipt_id === null && row.source_status !== "current" && row.missing.length > 0))) || value.object_options.some(row => !qualityRecord(row) || !validRef(row.ref) || typeof row.label !== "string" || !readSource(row.source))) throw new Error("适用性事实或已知对象缺少真实版本、回执或精确来源。");
  if (new Set(value.object_options.map(row => orderRefKey(row.ref))).size !== value.object_options.length) throw new Error("已知对象重复，须重新读取完整处置范围。");
  if (value.field_basis_options !== undefined && (!Array.isArray(value.field_basis_options) || value.field_basis_options.some(row => !qualityRecord(row) || !feedbackRef(row.feedback) || !uuid(row.version_id) || typeof row.sha256 !== "string" || !/^[0-9a-f]{64}$/.test(row.sha256) || typeof row.title !== "string" || !row.title.trim()))) throw new Error("现场反馈的固定来源依据尚未完整返回。");
  if (value.executor_options !== undefined && (!Array.isArray(value.executor_options) || value.executor_options.some(row => !qualityRecord(row) || !uuid(row.id) || typeof row.name !== "string" || !row.name.trim()))) throw new Error("实际执行者选项尚未完整返回。");
  if (value.adoption_condition !== undefined && (typeof value.adoption_condition !== "string" || !value.adoption_condition.trim() || value.adoption_condition.length > 2000)) throw new Error("开发 Build 采用条件尚未完整返回。");
  if (value.old_builds !== undefined && (!Array.isArray(value.old_builds) || value.old_builds.some(row => !qualityRecord(row) || !validRef(row.ref) || row.ref.kind !== "build" || row.ref.key != null || typeof row.label !== "string" || !row.label.trim()) || new Set(value.old_builds.map(row => orderRefKey(row.ref))).size !== value.old_builds.length)) throw new Error("明确前轮的真实 Build 选项尚未完整返回。");
  return value as unknown as OrderContext;
}
export function orderSelectionUsable(row: OrderSelection, now = Date.now()): boolean { return row.current && row.status === "applicable" && row.source_status === "current" && uuid(row.receipt_id) && !row.missing.length && (row.valid_until === null || Date.parse(row.valid_until) > now); }
export function fieldPlanRequest(context: OrderContext, draft: FieldPlanDraft, productId: string, now = Date.now()): MaterialRequest {
  const feedback = context.field_basis_options?.find(row => fieldBasisKey(row) === draft.feedbackKey), executor = context.executor_options?.find(row => row.id === draft.executorId), object = context.object_options.find(row => orderRefKey(row.ref) === draft.objectKey), expectedKind = draft.kind === "new_engineering_configuration" ? "engineering_configuration" : "manufacturing_configuration";
  const oldBuild = draft.adoptionMode ? context.old_builds?.find(row => orderRefKey(row.ref) === draft.oldBuildKey) : null;
  if (draft.adoptionMode && (!oldBuild || !context.adoption_condition)) throw new Error("请明确选择服务器列出的真实前轮 Build，并采用固定的继任开发 Build 条件。");
  const conditions = draft.adoptionMode ? [context.adoption_condition!] : draft.conditions.split(/\r?\n/).map(row => row.trim()).filter(Boolean), description = draft.description.trim(), verification = draft.verification.trim(), reason = draft.reason.trim(), deadline = draft.validUntil.trim();
  if (!feedback || !executor || !object || object.ref.kind !== expectedKind || !uuid(draft.itemId) || !uuid(draft.intentId) || !conditions.length || !description || !verification || !reason || [description, verification, reason, ...conditions].some(value => value.length > 2000) || !["applicable", "not_applicable", "unknown"].includes(draft.status) || deadline && (!qualityTime(deadline) || Date.parse(deadline) <= now)) throw new Error("请明确选择实际反馈、配置和执行人，填写未来实施意图、条件、复验要求与具名适用性判断；不采用已发生处置冒充未来计划。");
  const fixed = { ...object.ref, key: object.ref.key ?? null }, identity = `${fixed.kind}:${fixed.id}:${fixed.revision}:${fixed.key ?? ""}`;
  const item: OrderItem = { id: draft.itemId, discipline: expectedKind === "engineering_configuration" ? "engineering" : "manufacturing", selection: { objects: [fixed], units: [`object:${identity}`], conditions, sources: [{ ...object.source }] }, intent: { id: draft.intentId, kind: draft.kind, basis: [{ ...fixed }, ...(oldBuild ? [{ ...oldBuild.ref, key: null }] : [])], description }, verification_requirement: verification };
  return { path: `v1/products/${productId}/change-execution/selection-material`, body: { change_id: context.change.change_id, expected_change_revision: context.change.revision, field_intent: { kind: "field_intent", feedback: { ...feedback.feedback }, executor_id: executor.id }, item, status: draft.status, valid_until: deadline || null, reason } };
}
function normalizePayload(value: unknown, field = ""): unknown {
  if (Array.isArray(value)) return value.map(row => normalizePayload(row));
  if (!qualityRecord(value)) return ["valid_until", "expires_at", "valid_from"].includes(field) && value !== null ? handoffTime(value) : value;
  return Object.fromEntries(Object.entries(value).filter(([key]) => !["approval_token", "confirmation_token"].includes(key)).map(([key, row]) => [key, normalizePayload(row, key)]));
}
function sameCommand(returned: unknown, original: OrderCommand, includeReads: boolean): returned is OrderCommand {
  if (!qualityRecord(returned) || !qualityRecord(returned.payload) || !["command_id", "idempotency_key", "product_id", "expected_revision", "operation"].every(key => returned[key] === original[key as keyof OrderCommand]) || (original.category_id != null && returned.category_id !== original.category_id) || !qualitySame(normalizePayload(returned.payload), normalizePayload(original.payload))) return false;
  try { qualityReads(returned.source_read_set as SourceRead[]); } catch { return false; }
  return !includeReads || qualitySame(returned.source_read_set, original.source_read_set);
}
export function normalizeOrderCandidate(value: unknown, productId: string, context: OrderContext, source: OrderSource, principalId?: string): OrderCandidate {
  if (!qualityRecord(value) || !validOrderCommand(value.command, productId) || value.command.operation !== "change.selection.decide" || value.command.payload.change_id !== context.change.change_id || value.command.payload.expected_change_revision !== context.change.revision || !qualitySame(value.command.payload.source, source) || !qualityRecord(value.material) || !Array.isArray(value.required_source_read_set) || value.material.change_id !== context.change.change_id || !qualitySame(value.material.item, value.command.payload.item) || value.material.status !== value.command.payload.status) throw new Error("未取得与原文、变更版本及真实计划项一致的适用性候选。");
  const payload = value.command.payload, action = payload.action as Record<string, unknown>, material = value.material;
  const nativeBasis = fieldIntent(action) ? material.schema_version === "pdos-field-change-selection-v1" && qualitySame(material.feedback, action.feedback) && material.executor_id === action.executor_id && context.field_basis_options?.some(row => qualitySame(row.feedback, action.feedback) && material.feedback_version_id === row.version_id && material.feedback_sha256 === row.sha256) && context.executor_options?.some(row => row.id === action.executor_id) : context.actions.some(row => row.issue_id === action.issue_id && row.issue_revision === action.expected_issue_revision && row.capa_id === action.capa_id && row.action_id === action.action_id && row.executor_id === material.executor_id) && ["issue_id", "capa_id", "action_id"].every(key => material[key] === action[key]);
  if (!nativeBasis || !qualityRecord(material.scope) || material.scope.product_id !== productId || material.scope.project_id !== context.change.project_id || material.reason !== payload.reason || !qualitySame(normalizePayload({ valid_until: material.valid_until }), normalizePayload({ valid_until: payload.valid_until })) || (principalId && material.decider_id !== principalId)) throw new Error("原文计划项、原生依据、执行者或具名决定人未与当前真实范围一致。");
  qualityReads(value.required_source_read_set as SourceRead[], value.command.source_read_set);
  return value as unknown as OrderCandidate;
}
export function orderInputs(value: unknown, command: OrderCommand): OrderCommand | null {
  if (!qualityRecord(value) || typeof value.allowed !== "boolean" || !sameCommand(value.command, command, false)) throw new Error("尚未取得与原请求范围一致的完整核对，请保留原请求并重新核对。");
  const returned = value.command;
  qualityReads(command.source_read_set, returned.source_read_set);
  if (command.source_read_set.some(read => !returned.source_read_set.some(row => row.artifact_id === read.artifact_id && row.expected_revision === read.expected_revision))) throw new Error("本次核对丢失原请求的固定来源，请保留原请求重新核对。");
  return value.allowed ? returned : null;
}
export function validOrderPreview(value: unknown, command: OrderCommand, now = Date.now()): value is OrderPreview {
  if (!qualityRecord(value) || !sameCommand(value.command, command, true) || !proofClockCurrent(command.operation === "change.selection.decide" ? "T2" : "T1", value.expires_at, now) || !qualityRecord(value.review) || value.review.operation !== command.operation || !qualityRecord(value.review.before) || !qualityRecord(value.review.after) || typeof value.review.effect !== "string" || !value.review.effect) return false;
  const token = command.operation === "change.selection.decide" ? "approval_token" : "confirmation_token", payload = value.command.payload;
  if (typeof payload[token] !== "string" || payload[token].length < 16) return false;
  const before = value.review.before, after = value.review.after;
  if (command.operation === "change.selection.decide") {
    const action = command.payload.action, material = after.material;
    const nativeBasis = fieldIntent(action) ? qualityRecord(material) && material.schema_version === "pdos-field-change-selection-v1" && qualitySame(material.feedback, action.feedback) && material.executor_id === action.executor_id : qualityRecord(action) && qualityRecord(material) && material.issue_id === action.issue_id && material.capa_id === action.capa_id && material.action_id === action.action_id;
    return value.write_tier === "T2" && value.named_decision === true && before.change_id === command.payload.change_id && before.change_revision === command.payload.expected_change_revision && qualityRevision(after.selection_revision) && qualityRecord(material) && nativeBasis && material.change_id === command.payload.change_id && qualitySame(material.item, command.payload.item) && material.status === command.payload.status && material.reason === command.payload.reason && qualitySame(normalizePayload({ valid_until: material.valid_until }), normalizePayload({ valid_until: command.payload.valid_until }));
  }
  const orders = after.orders;
  if (before.id !== command.payload.change_id || before.revision !== command.payload.expected_change_revision || after.id !== command.payload.change_id || after.revision !== Number(command.payload.expected_change_revision) + 1 || after.status !== "review" || !Array.isArray(orders) || !orders.length) return false;
  const prepared = orders.at(-1);
  return qualityRecord(prepared) && prepared.assessment_id === command.payload.assessment_id && Array.isArray(prepared.approvals) && prepared.approvals.length === 0 && qualitySame(normalizePayload(prepared.plan), normalizePayload(command.payload.plan));
}
export function validOrderReceipt(value: unknown, command: OrderCommand): value is { id: string; subject_id: string } { return qualityRecord(value) && uuid(value.id) && uuid(value.subject_id) && value.operation === command.operation && value.subject_type === (command.operation === "change.selection.decide" ? "change_selection_fact" : "change_request"); }
export function orderPreparePayload(context: OrderContext, draft: OrderDraft, now = Date.now()): Record<string, unknown> {
  if (!context.policy || !["analysis", "review"].includes(context.change.status)) throw new Error("先取得本项目当前正式政策与固定影响评估。");
  const assessments = context.change.request.assessments, assessment = Array.isArray(assessments) ? assessments.at(-1) : null;
  if (!qualityRecord(assessment) || !uuid(assessment.id) || !uuid(draft.planId) || !draft.reason.trim() || draft.reason.trim().length > 2000) throw new Error("请核对最新影响评估、稳定计划标识与具名准备原因。");
  const chosen = draft.selectedSelectionIds.map(id => context.selections.find(row => row.id === id));
  if (!chosen.length || new Set(draft.selectedSelectionIds).size !== chosen.length || chosen.some(row => !row || !orderSelectionUsable(row, now))) throw new Error("只能明确选择服务器核对的当前、适用且未过期的具名计划项。");
  const items = chosen.map(row => row!.item);
  if (new Set(items.map(row => row.id)).size !== items.length) throw new Error("同一计划项不能重复采用两个适用性版本。");
  const selectedIds = new Set(items.map(row => row.id));
  if (!context.object_options.length) throw new Error("尚未读取全部已知影响对象，不能补造空处置。");
  const dispositions = context.object_options.map(option => {
    const row = draft.dispositions[orderRefKey(option.ref)];
    if (!row || !["covered_by_plan", "reviewed_no_change", "unknown"].includes(row.handling) || !row.rationale.trim() || row.rationale.trim().length > 2000 || !validQualitySource(row.source)) throw new Error("逐一填写已知对象的明确处置、具名原因和精确原文；未知不能补为无需更改。");
    if (row.handling === "covered_by_plan" ? !row.itemIds.length || new Set(row.itemIds).size !== row.itemIds.length || row.itemIds.some(id => !selectedIds.has(id)) : row.itemIds.length > 0) throw new Error("实施处置须关联本次真实计划项，其他处置不携带实施项。");
    return { object: { ...option.ref }, handling: row.handling, item_ids: [...row.itemIds], rationale: row.rationale.trim(), sources: [{ ...row.source }] };
  });
  const expires = draft.expiresAt.trim();
  if (expires && (!qualityTime(expires) || Date.parse(expires) <= now)) throw new Error("计划到期时间须含时区且晚于当前时点；留空表示不另设计划到期，不延长上游事实期限。");
  return { change_id: context.change.change_id, expected_change_revision: context.change.revision, visibility: context.change.visibility, assessment_id: assessment.id, plan: { id: draft.planId, items: structuredClone(items), expires_at: expires || null, dispositions }, reason: draft.reason.trim() };
}
export function makeOrderPrepare(product: { id: string; revision: number }, payload: Record<string, unknown>, id: string, key: string): OrderCommand { return { command_id: id, idempotency_key: key, product_id: product.id, expected_revision: product.revision, operation: "change.order.prepare", payload, source_read_set: [] }; }
function validOrderCommand(value: unknown, productId: string): value is OrderCommand {
  if (!qualityRecord(value) || !uuid(value.command_id) || typeof value.idempotency_key !== "string" || !value.idempotency_key || value.product_id !== productId || !qualityRevision(value.expected_revision) || !["change.selection.decide", "change.order.prepare"].includes(String(value.operation)) || !qualityRecord(value.payload) || !uuid(value.payload.change_id) || !qualityRevision(value.payload.expected_change_revision) || !Array.isArray(value.source_read_set)) return false;
  try { qualityReads(value.source_read_set as SourceRead[]); } catch { return false; }
  const payload = value.payload;
  if (value.operation === "change.selection.decide") return validItem(payload.item) && qualityRecord(payload.action) && (fieldIntent(payload.action) || payload.action.kind === undefined && ["issue_id", "capa_id", "action_id"].every(key => uuid((payload.action as Record<string, unknown>)[key])) && qualityRevision(payload.action.expected_issue_revision)) && ["applicable", "not_applicable", "unknown"].includes(String(payload.status)) && validQualitySource(payload.source) && typeof payload.reason === "string";
  const plan = payload.plan;
  return uuid(payload.assessment_id) && qualityRecord(plan) && uuid(plan.id) && Array.isArray(plan.items) && !!plan.items.length && plan.items.every(validItem) && Array.isArray(plan.dispositions) && !!plan.dispositions.length && (plan.expires_at === null || !!qualityTime(plan.expires_at)) && typeof payload.reason === "string";
}
export function restoreOrders(value: unknown, productId: string, principalId: string, projectId = "", fixedChangeId = ""): OrderLocal | null {
  if (!qualityRecord(value) || value.schema_version !== 1 || value.product_id !== productId || value.principal_id !== principalId || value.project_id !== projectId || typeof value.selectedChangeId !== "string" || (value.selectedChangeId && !uuid(value.selectedChangeId)) || !qualityRecord(value.drafts)) return null;
  if (fixedChangeId && value.selectedChangeId !== fixedChangeId) return null;
  for (const [id, row] of Object.entries(value.drafts)) {
    if (!uuid(id) || !qualityRecord(row) || !uuid(row.planId) || !strings(row.selectedSelectionIds) || !row.selectedSelectionIds.every(uuid) || !qualityRecord(row.dispositions) || typeof row.expiresAt !== "string" || typeof row.reason !== "string" || !(row.selectionSource === null || validQualitySource(row.selectionSource))) return null;
    for (const disposition of Object.values(row.dispositions)) if (!qualityRecord(disposition) || !["covered_by_plan", "reviewed_no_change", "unknown"].includes(String(disposition.handling)) || !strings(disposition.itemIds) || !disposition.itemIds.every(uuid) || typeof disposition.rationale !== "string" || !(disposition.source === null || validQualitySource(disposition.source))) return null;
    if (row.candidate !== null && (!qualityRecord(row.candidate) || !validOrderCommand(row.candidate.command, productId) || row.candidate.command.operation !== "change.selection.decide" || row.candidate.command.payload.change_id !== id || !qualityRecord(row.candidate.material) || !Array.isArray(row.candidate.required_source_read_set))) return null;
  }
  if (value.pending !== null) {
    if (!qualityRecord(value.pending) || !["inputs", "preview", "execute"].includes(String(value.pending.stage)) || !validOrderCommand(value.pending.command, productId) || value.pending.command.payload.change_id !== value.selectedChangeId) return null;
    const token = value.pending.command.operation === "change.selection.decide" ? "approval_token" : "confirmation_token";
    if (value.pending.stage === "execute" && (typeof value.pending.command.payload[token] !== "string" || String(value.pending.command.payload[token]).length < 16)) return null;
  }
  return { selectedChangeId: value.selectedChangeId, drafts: value.drafts as Record<string, OrderDraft>, pending: value.pending as OrderPending | null };
}
export function orderPlanReading(plan: CommandPlan, audience: string[]): EffectivityPlan {
  const source = (ref: CommandPlan["items"][number]["selection"]["sources"][number]): Source => ({ ...ref, status: "unknown" });
  return { id: plan.id, revision: 1, kind: "生效计划候选", dispositions: plan.dispositions, scopes: plan.items.map(item => ({ id: item.id, objects: item.selection.objects, units: item.selection.units, description: item.verification_requirement, audience, lots: [], serialRange: null, conditions: item.selection.conditions, sources: item.selection.sources.map(source) })), intents: plan.items.map(item => ({ id: item.intent.id, kind: ({ new_engineering_configuration: "new_configuration", new_manufacturing_configuration: "new_configuration", new_build: "new_build", new_test_run: "new_run", erp_mes_effectivity: "erp_mes_effectivity" } as const)[item.intent.kind], description: item.intent.description, fixedRefs: item.intent.basis, scopeIds: [item.id], actualRef: null })), inventoryDisposition: null, trainingRequirement: null };
}
export function orderError(value: unknown, reading = false): { status?: number; message: string } {
  const status = qualityRecord(value) && typeof value.status === "number" ? value.status : undefined;
  return { status, message: reading ? "当前项目变更、政策或真实适用性材料读取失败，请刷新核对；本次读取未保存或批准。" : status === 401 || status === 403 ? "当前项目、原文或具名专业权限不可用。原请求已保留，请刷新当前权限与范围，再核对回执。" : "尚未取得确定回执；原请求继续保留，请核对回执，不重复办理。" };
}
export async function readOrderScope(api: OrderApi, productId: string, changeId: string, projectId: string, current: () => boolean, fixedChangeId = ""): Promise<{ changes: OrderChange[]; sources: DefinitionSource[]; context: OrderContext | null } | null> {
  if (fixedChangeId && (fixedChangeId !== changeId || !uuid(fixedChangeId))) throw new Error("本次正式办理须保留原已选变更。");
  const parameters = new URLSearchParams(); if (projectId) parameters.set("project_id", projectId); if (fixedChangeId) parameters.set("change_id", fixedChangeId); const query = parameters.size ? `?${parameters}` : "";
  const values = await Promise.all([api<unknown>(`v1/products/${productId}/change-execution${query}`), api<{ sources: DefinitionSource[] }>(`v1/products/${productId}/workspace`)]);
  if (!current()) return null;
  const changes = normalizeOrderChanges(values[0], projectId);
  if (!Array.isArray(values[1].sources)) throw new Error("当前可读原文不完整。");
  let context: OrderContext | null = null;
  if (changeId && changes.some(row => row.change_id === changeId)) context = normalizeOrderContext(await api<unknown>(`v1/products/${productId}/change-execution/order-context?change_id=${encodeURIComponent(changeId)}`), changeId, projectId);
  return current() ? { changes, sources: values[1].sources, context } : null;
}
