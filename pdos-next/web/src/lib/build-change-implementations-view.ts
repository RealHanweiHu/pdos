import type { Ref } from "../components/change_control/contracts";
import { readApprovalScope, type ApprovalScope } from "./build-change-approvals-view";
import type { OrderItem, OrderReadSource, OrderSource } from "./build-change-orders-view";
import { handoffTime } from "./build-handoff-view";
import { qualityReads, qualityRecord, qualityRevision, qualitySame, qualityTime, qualityZone, qualityStable, validQualitySource } from "./build-quality-loop-view";
import { orderSelectionUsable, type OrderSelection } from "./build-change-orders-view";
import type { MaterialRequest } from "./change-source-material";
import type { DefinitionSource } from "./product-view";
import type { SourceRead } from "./project-plan-view";

export const readImplementationScope = readApprovalScope;
export type ImplementationScope = ApprovalScope;
export type ImplementationFact = { id: string; reconciles_id: string | null; item_id: string; intent_id: string; executor_id: string; outcome: "succeeded" | "failed" | "unknown"; occurred_at: string; received_at: string; sources: OrderReadSource[]; outputs: Ref[]; note: string; nature: "real" | "synthetic" };
export type ImplementationCaptureRequest = { capture_key: string; change_id: string; expected_change_revision: number; visibility: string; order_id: string; item_id: string; source: OrderSource };
export type ImplementationCapture = { id: string; revision: number; change_id: string; change_revision: number; order_id: string; item_id: string; fact_id: string; fact: ImplementationFact; required_source_read_set: SourceRead[]; created_at: string; expires_at: string | null };
export type ImplementationCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: "change.implementation.record"; payload: { change_id: string; expected_change_revision: number; visibility: string; item_id: string; fact_id: string; confirmation_token?: string | null }; source_read_set: SourceRead[]; category_id?: string | null };
export type ImplementationDraft = { orderId: string; itemId: string; source: OrderSource | null; request: ImplementationCaptureRequest | null; capture: ImplementationCapture | null };
export type ImplementationPending = { stage: "capture"; request: ImplementationCaptureRequest } | { stage: "inputs" | "preview" | "execute"; orderId: string; itemId: string; command: ImplementationCommand };
export type ImplementationLocal = { selectedOrderId: string; selectedItemId: string; drafts: Record<string, ImplementationDraft>; pending: ImplementationPending | null };
export type ImplementationPreview = { command: ImplementationCommand; expires_at: string; review: Record<string, unknown> & { before: Record<string, unknown>; after: Record<string, unknown>; effect: string } };
export type FieldOccurrenceDraft = { implementationId: string; reconcilesId: string; outcome: "succeeded" | "failed" | "unknown"; occurredAt: string; timezone: string; source: OrderSource | null; outputKeys: string[]; note: string };
export type FieldOutputOption = { ref: Ref; name: string; previous_id: string; expected_previous_revision: number; owner_id: string; visibility: string; created_at: string; required_source_read_set: SourceRead[] };
export const blankFieldOccurrenceDraft = (implementationId: string): FieldOccurrenceDraft => ({ implementationId, reconcilesId: "", outcome: "unknown", occurredAt: "", timezone: "", source: null, outputKeys: [], note: "" });
export const implementationKey = (orderId: string, itemId: string) => JSON.stringify([orderId, itemId]);
export const blankImplementationLocal = (): ImplementationLocal => ({ selectedOrderId: "", selectedItemId: "", drafts: {}, pending: null });
export const blankImplementationDraft = (orderId: string, itemId: string): ImplementationDraft => ({ orderId, itemId, source: null, request: null, capture: null });
export const implementationOutcomeNames = { succeeded: "原件记载成功", failed: "原件记载失败", unknown: "原件记载结果未知" };
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
const nullableTime = (value: unknown) => value === null || !!qualityTime(value);
const provenance = (value: unknown): value is OrderReadSource => qualityRecord(value) && uuid(value.id) && qualityRevision(value.revision) && ["artifact", "domain", "command"].includes(String(value.kind)) && typeof value.position === "string" && !!value.position;
const validRef = (value: unknown): value is Ref => qualityRecord(value) && uuid(value.id) && qualityRevision(value.revision) && typeof value.kind === "string" && (value.key == null || typeof value.key === "string");
const refKey = (ref: Ref) => JSON.stringify([ref.kind, ref.id, ref.revision, ref.key ?? null]);
export function nativeImplementationSources(sources: DefinitionSource[]): DefinitionSource[] { return sources.filter(row => qualityRecord(row) && "original_id" in row && row.original_id === null); }
export function implementationPlanReady(scope: ImplementationScope, orderId: string, now = Date.now()): boolean {
  const order = scope.orders.at(-1);
  return !!order && order.id === orderId && ["approved", "implementing"].includes(scope.context.change.status) && ["engineering", "manufacturing"].every(role => order.required_disciplines.includes(role as "engineering" | "manufacturing")) && order.required_disciplines.every(role => order.approvals.some(decision => decision.discipline === role && decision.content_digest === order.content_digest && (decision.expires_at === null || Date.parse(decision.expires_at) > now))) && (order.plan.expires_at === null || Date.parse(order.plan.expires_at) > now);
}
export function implementationItem(scope: ImplementationScope, orderId: string, itemId: string): OrderItem | null { return scope.orders.find(order => order.id === orderId)?.plan.items.find(item => item.id === itemId) ?? null; }
export const supportedImplementationItem = (item: OrderItem | null | undefined): boolean => !!item && ["new_engineering_configuration", "new_manufacturing_configuration"].includes(item.intent.kind);
export function fieldImplementationSelection(scope: ImplementationScope, itemId: string): OrderSelection | null { return scope.context.selections.find(row => row.basis_kind === "field_intent" && row.item.id === itemId) ?? null; }
export async function readFieldImplementationOutputs(api: import("./workspace-api").WorkspaceTransport, productId: string, scope: ImplementationScope, orderId: string, itemId: string, principalId: string): Promise<FieldOutputOption[]> {
  const item = implementationItem(scope, orderId, itemId), order = scope.orders.find(row => row.id === orderId);
  if (!item || !order || !supportedImplementationItem(item)) throw new Error("请选择实际已批准配置计划项。");
  const value = await api<unknown>(`v1/products/${productId}/configurations`);
  if (!qualityRecord(value) || !Array.isArray(value.engineering) || !Array.isArray(value.processes)) throw new Error("实际新配置列表尚未完整取得，不能当作空结果。");
  const kind = item.intent.kind === "new_engineering_configuration" ? "engineering_configuration" : "manufacturing_configuration", rows = kind === "engineering_configuration" ? value.engineering : value.processes, approvedAt = Math.max(...order.approvals.map(row => Date.parse(row.at)));
  const options: FieldOutputOption[] = [];
  for (const row of rows) {
    if (!qualityRecord(row) || !uuid(row.id) || !qualityRevision(row.revision) || typeof row.name !== "string" || !row.name.trim() || typeof row.owner_id !== "string" || typeof row.visibility !== "string" || !qualityTime(row.created_at) || !Array.isArray(row.required_source_read_set)) throw new Error("实际配置身份、版本、署名或创建时间不完整。");
    if (row.owner_id !== principalId || row.source_status !== "current" || !uuid(row.previous_id) || !qualityRevision(row.expected_previous_revision) || !item.intent.basis.some(previous => previous.kind === kind && previous.id === row.previous_id && previous.revision === row.expected_previous_revision) || !Number.isFinite(approvedAt) || Date.parse(String(row.created_at)) < approvedAt) continue;
    options.push({ ref: { kind, id: row.id, revision: row.revision, key: null }, name: row.name, previous_id: row.previous_id, expected_previous_revision: row.expected_previous_revision, owner_id: row.owner_id, visibility: row.visibility, created_at: String(row.created_at), required_source_read_set: row.required_source_read_set as SourceRead[] });
  }
  return options;
}
export function fieldOccurrenceRequest(scope: ImplementationScope, orderId: string, itemId: string, principalId: string, draft: FieldOccurrenceDraft, options: FieldOutputOption[], now = Date.now()): Extract<MaterialRequest, { path: null }> {
  const item = implementationItem(scope, orderId, itemId), selected = fieldImplementationSelection(scope, itemId), order = scope.orders.find(row => row.id === orderId), actualScope = scope.context.change.request.scope;
  if (!item || !selected || !order || !implementationPlanReady(scope, orderId, now) || !orderSelectionUsable(selected, now) || selected.executor_id !== principalId || selected.intent_id !== item.intent.id || !qualitySame(selected.item, item) || !selected.feedback || !uuid(selected.feedback.id) || !qualityRevision(selected.feedback.revision) || !uuid(selected.feedback_version_id) || typeof selected.feedback_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(selected.feedback_sha256) || typeof selected.material_sha256 !== "string" || !/^[0-9a-f]{64}$/.test(selected.material_sha256) || !qualityRecord(actualScope) || !["tenant_id", "product_id", "project_id"].every(key => uuid(actualScope[key]))) throw new Error("本项实际反馈、具名适用性与批准范围尚未取得，须由计划执行人本人办理。");
  if (!uuid(draft.implementationId) || !qualityTime(draft.occurredAt) || Date.parse(draft.occurredAt) > now || !draft.note.trim() || draft.note.trim().length > 4000 || !validQualitySource(draft.source) || !nativeImplementationSources(scope.sources).some(row => row.id === draft.source?.id && row.revision === draft.source.revision && row.status === "active") || !["succeeded", "failed", "unknown"].includes(draft.outcome)) throw new Error("请填写已发生结果、带时区的实际时间、原时区、说明和新证据原文，不能用计划代替事实。");
  const outputs = draft.outputKeys.map(key => options.find(option => refKey(option.ref) === key));
  if (new Set(draft.outputKeys).size !== draft.outputKeys.length || outputs.some(option => !option || Date.parse(option.created_at) > Date.parse(draft.occurredAt)) || draft.outcome === "succeeded" && outputs.length === 0) throw new Error("成功实施须明确选择本人在批准后建立且早于实际发生时间的新配置；失败或未知可保留没有输出。");
  if (scope.context.change.visibility === "category" && (scope.sources.find(row => row.id === draft.source?.id && row.revision === draft.source.revision)?.visibility === "private" || outputs.some(option => option!.visibility === "private"))) throw new Error("当前变更受众不可采用该私有原文/输出，请选择当前可共享来源。");
  if (draft.reconcilesId && !order.implementations.some(value => validImplementationFact(value) && value.id === draft.reconcilesId && value.item_id === itemId && value.outcome === "unknown")) throw new Error("对账只能选择本项已保存的未知实施事实。");
  const assessments = scope.context.change.request.assessments, assessment = Array.isArray(assessments) ? assessments.find(row => qualityRecord(row) && row.id === order.assessment_id) : null, graph = qualityRecord(assessment) && qualityRecord(assessment.graph) ? assessment.graph : null;
  if (!graph || !["real", "synthetic"].includes(String(graph.nature))) throw new Error("固定评估的事实性质尚未取得。");
  const body = { schema_version: "pdos-field-change-implementation-occurrence-v1", scope: actualScope, purpose: scope.context.change.purpose, feedback: selected.feedback, feedback_version_id: selected.feedback_version_id, feedback_sha256: selected.feedback_sha256, selection_id: selected.id, selection_revision: selected.revision, selection_sha256: selected.material_sha256, change_id: scope.context.change.change_id, order_id: orderId, implementation_id: draft.implementationId, reconciles_id: draft.reconcilesId || null, item_id: item.id, intent_id: item.intent.id, executor_id: principalId, operation: "change.implementation.record", outcome: draft.outcome, occurred_at: draft.occurredAt, original_timezone: qualityZone(draft.timezone), sources: [{ ...draft.source }], outputs: outputs.map(option => ({ ...option!.ref })), note: draft.note.trim(), nature: graph.nature };
  if (typeof body.purpose !== "string" || !body.purpose.trim()) throw new Error("所选变更的实际用途尚未取得。");
  const reads = new Map<string, SourceRead>(); for (const read of [{ artifact_id: draft.source.id, expected_revision: draft.source.revision }, ...outputs.flatMap(option => option!.required_source_read_set)]) { const prior = reads.get(read.artifact_id); if (prior && prior.expected_revision !== read.expected_revision) throw new Error("同一实际原件不能采用两个版本。"); reads.set(read.artifact_id, { ...read }); }
  return { path: null, body, artifact_payload: { title: `实际实施：${String(scope.context.change.request.title ?? "现场反馈变更").slice(0, 60)}`, content: JSON.stringify(qualityStable(body)), source_label: "本人明确记录的已发生结果，待核对与一次确认", visibility: scope.context.change.visibility }, required_source_read_set: [...reads.values()].sort((a, b) => a.artifact_id.localeCompare(b.artifact_id)) };
}
export function makeImplementationCapture(scope: ImplementationScope, orderId: string, itemId: string, source: OrderSource | null, key: string, now = Date.now()): ImplementationCaptureRequest {
  if (!implementationPlanReady(scope, orderId, now) || !supportedImplementationItem(implementationItem(scope, orderId, itemId)) || !uuid(key) || !validQualitySource(source) || !nativeImplementationSources(scope.sources).some(row => row.id === source.id && row.revision === source.revision && row.status === "active")) throw new Error("请选择当前已获两专业批准的配置计划项，以及当前可读的系统内登记原文完整行；其他输出所有者尚未接入。");
  return { capture_key: key, change_id: scope.context.change.change_id, expected_change_revision: scope.context.change.revision, visibility: scope.context.change.visibility, order_id: orderId, item_id: itemId, source: { ...source } };
}
export function validImplementationFact(value: unknown): value is ImplementationFact {
  return qualityRecord(value) && ["id", "item_id", "intent_id", "executor_id"].every(key => uuid(value[key])) && (value.reconciles_id === null || uuid(value.reconciles_id)) && ["succeeded", "failed", "unknown"].includes(String(value.outcome)) && !!qualityTime(value.occurred_at) && !!qualityTime(value.received_at) && Date.parse(String(value.occurred_at)) <= Date.parse(String(value.received_at)) && Array.isArray(value.sources) && !!value.sources.length && value.sources.every(provenance) && Array.isArray(value.outputs) && value.outputs.every(validRef) && new Set(value.outputs.map(refKey)).size === value.outputs.length && typeof value.note === "string" && !!value.note.trim() && ["real", "synthetic"].includes(String(value.nature));
}
function canonical(value: unknown, field = ""): unknown {
  if (Array.isArray(value)) return value.map(row => canonical(row));
  if (qualityRecord(value)) return Object.fromEntries(Object.entries(value).filter(([key]) => key !== "confirmation_token").map(([key, row]) => [key, canonical(row, key)]));
  return ["occurred_at", "received_at", "created_at", "expires_at", "valid_until", "valid_from"].includes(field) && value !== null ? handoffTime(value) : value;
}
function basicCapture(value: unknown): value is ImplementationCapture {
  if (!qualityRecord(value) || !["id", "change_id", "order_id", "item_id", "fact_id"].every(key => uuid(value[key])) || value.revision !== 1 || !qualityRevision(value.change_revision) || !validImplementationFact(value.fact) || value.fact.id !== value.fact_id || value.fact.item_id !== value.item_id || !qualityTime(value.created_at) || !qualitySame(canonical({ received_at: value.fact.received_at }), canonical({ received_at: value.created_at })) || !nullableTime(value.expires_at) || !Array.isArray(value.required_source_read_set) || !value.required_source_read_set.length) return false;
  try { qualityReads(value.required_source_read_set as SourceRead[]); } catch { return false; }
  return true;
}
export function normalizeImplementationCapture(value: unknown, request: ImplementationCaptureRequest, scope: ImplementationScope, principalId: string): ImplementationCapture {
  const item = implementationItem(scope, request.order_id, request.item_id), order = scope.orders.find(row => row.id === request.order_id), assessments = scope.context.change.request.assessments;
  const assessment = Array.isArray(assessments) ? assessments.find(row => qualityRecord(row) && row.id === order?.assessment_id) : null;
  if (!basicCapture(value) || value.change_id !== request.change_id || value.change_revision !== request.expected_change_revision || value.order_id !== request.order_id || value.item_id !== request.item_id || !item || value.fact.intent_id !== item.intent.id || value.fact.executor_id !== principalId || !qualityRecord(assessment) || !qualityRecord(assessment.graph) || value.fact.nature !== assessment.graph.nature || !value.required_source_read_set.some(row => row.artifact_id === request.source.id && row.expected_revision === request.source.revision)) throw new Error("捕获尚未返回与原请求、本计划项、本人和实际原件一致的完整事实；保留同一捕获请求核对。");
  const expected = item.intent.kind === "new_engineering_configuration" ? "engineering_configuration" : item.intent.kind === "new_manufacturing_configuration" ? "manufacturing_configuration" : null;
  if (value.fact.outputs.some(ref => ref.kind !== expected || ref.key != null || item.intent.basis.some(previous => previous.id === ref.id)) || (value.fact.outcome === "succeeded" && !value.fact.outputs.length)) throw new Error("捕获缺少与批准意图匹配的真实新配置输出，不能用原配置或计划身份补足。");
  return value;
}
export function makeImplementationCommand(product: { id: string; revision: number }, scope: ImplementationScope, draft: ImplementationDraft, principalId: string, id: string, key: string, now = Date.now()): ImplementationCommand {
  if (!uuid(product.id) || !qualityRevision(product.revision) || !uuid(id) || !uuid(key) || !qualityRecord(scope.context.change.request.scope) || scope.context.change.request.scope.product_id !== product.id || !implementationPlanReady(scope, draft.orderId, now) || !draft.request || !draft.capture || draft.request.change_id !== scope.context.change.change_id || draft.request.expected_change_revision !== scope.context.change.revision || draft.request.order_id !== draft.orderId || draft.request.item_id !== draft.itemId || !qualitySame(draft.source, draft.request.source)) throw new Error("当前批准、变更版本或捕获事实已变化，请先核对真实原件捕获；不能沿用其他计划项。");
  if (!qualitySame(draft.request, makeImplementationCapture(scope, draft.orderId, draft.itemId, draft.source, draft.request.capture_key, now))) throw new Error("捕获原件、受众或固定范围已变化，请重新核对，不改写原捕获请求。");
  const capture = normalizeImplementationCapture(draft.capture, draft.request, scope, principalId);
  if ((capture.expires_at !== null && Date.parse(capture.expires_at) <= now) || scope.orders.at(-1)!.implementations.some(fact => qualityRecord(fact) && fact.id === capture.fact_id)) throw new Error("本捕获已过期或实际实施事实已保存；请刷新核对，不另建提交替代原请求恢复。");
  return { command_id: id, idempotency_key: key, product_id: product.id, expected_revision: product.revision, operation: "change.implementation.record", payload: { change_id: capture.change_id, expected_change_revision: capture.change_revision, visibility: scope.context.change.visibility, item_id: capture.item_id, fact_id: capture.fact_id }, source_read_set: qualityReads(capture.required_source_read_set) };
}
function validCaptureRequest(value: unknown, changeId: string): value is ImplementationCaptureRequest { return qualityRecord(value) && uuid(value.capture_key) && value.change_id === changeId && qualityRevision(value.expected_change_revision) && ["private", "category", "audience"].includes(String(value.visibility)) && uuid(value.order_id) && uuid(value.item_id) && validQualitySource(value.source); }
function validCommand(value: unknown, productId: string, changeId: string): value is ImplementationCommand {
  if (!qualityRecord(value) || !uuid(value.command_id) || !uuid(value.idempotency_key) || value.product_id !== productId || !qualityRevision(value.expected_revision) || value.operation !== "change.implementation.record" || !qualityRecord(value.payload) || value.payload.change_id !== changeId || !qualityRevision(value.payload.expected_change_revision) || !["private", "category", "audience"].includes(String(value.payload.visibility)) || !uuid(value.payload.item_id) || !uuid(value.payload.fact_id) || Object.keys(value.payload).some(key => !["change_id", "expected_change_revision", "visibility", "item_id", "fact_id", "confirmation_token"].includes(key)) || !Array.isArray(value.source_read_set) || !value.source_read_set.length) return false;
  try { qualityReads(value.source_read_set as SourceRead[]); } catch { return false; }
  return true;
}
function sameCommand(value: unknown, original: ImplementationCommand, reads: boolean): value is ImplementationCommand { return validCommand(value, original.product_id, original.payload.change_id) && ["command_id", "idempotency_key", "product_id", "expected_revision", "operation"].every(key => value[key as keyof ImplementationCommand] === original[key as keyof ImplementationCommand]) && (original.category_id == null || value.category_id === original.category_id) && qualitySame(canonical(value.payload), canonical(original.payload)) && (!reads || qualitySame(value.source_read_set, original.source_read_set)); }
export function implementationInputs(value: unknown, original: ImplementationCommand): ImplementationCommand | null {
  if (!qualityRecord(value) || typeof value.allowed !== "boolean" || !sameCommand(value.command, original, false)) throw new Error("服务器尚未返回与原实施请求一致的完整条件核对。");
  const command = value.command;
  qualityReads(original.source_read_set, command.source_read_set);
  if (original.source_read_set.some(read => !command.source_read_set.some(row => row.artifact_id === read.artifact_id && row.expected_revision === read.expected_revision))) throw new Error("本次核对丢失了原捕获固定来源，不能继续保存实施。");
  return value.allowed ? command : null;
}
export function validImplementationPreview(value: unknown, command: ImplementationCommand, scope: ImplementationScope, draft: ImplementationDraft, now = Date.now()): value is ImplementationPreview {
  if (!qualityRecord(value) || !sameCommand(value.command, command, true) || !qualityTime(value.expires_at) || Date.parse(String(value.expires_at)) <= now || typeof value.command.payload.confirmation_token !== "string" || value.command.payload.confirmation_token.length < 16 || !qualityRecord(value.review) || value.review.operation !== command.operation || typeof value.review.effect !== "string" || !value.review.effect.trim() || !qualityRecord(value.review.before) || !qualityRecord(value.review.after) || !draft.capture || draft.capture.fact_id !== command.payload.fact_id || draft.itemId !== command.payload.item_id) return false;
  const before = value.review.before, after = value.review.after, order = scope.orders.at(-1);
  if (!order || order.id !== draft.orderId || !qualitySame(canonical(before), canonical(scope.context.change.request)) || before.id !== command.payload.change_id || before.revision !== command.payload.expected_change_revision || !["approved", "implementing"].includes(String(before.status)) || after.id !== before.id || after.revision !== Number(before.revision) + 1 || after.status !== "implementing" || !Array.isArray(after.orders) || after.orders.length !== scope.orders.length) return false;
  const unchanged = (row: Record<string, unknown>) => Object.fromEntries(Object.entries(row).filter(([key]) => !["revision", "status", "orders", "history"].includes(key)));
  if (!qualitySame(canonical(unchanged(before)), canonical(unchanged(after))) || !qualitySame(canonical(after.orders.slice(0, -1)), canonical(scope.orders.slice(0, -1)))) return false;
  const proposed = after.orders.at(-1);
  return qualityRecord(proposed) && Array.isArray(proposed.implementations) && proposed.implementations.length === order.implementations.length + 1 && qualitySame(canonical(proposed.implementations.slice(0, -1)), canonical(order.implementations)) && qualitySame(canonical(proposed.implementations.at(-1)), canonical(draft.capture.fact)) && qualitySame(canonical({ ...proposed, implementations: order.implementations }), canonical(order));
}
export function validImplementationReceipt(value: unknown, command: ImplementationCommand, principalId: string): value is { id: string; subject_id: string } { return qualityRecord(value) && uuid(value.id) && uuid(value.subject_id) && value.product_id === command.product_id && value.operation === command.operation && value.subject_type === "change_request" && value.subject_revision === command.payload.expected_change_revision + 1 && value.writer_id === principalId && value.requester_id === principalId && value.agent_run_id === null; }
export function restoreImplementations(value: unknown, productId: string, principalId: string, projectId: string, changeId: string): ImplementationLocal | null {
  if (!qualityRecord(value) || value.schema_version !== 1 || value.product_id !== productId || value.principal_id !== principalId || value.project_id !== projectId || value.change_id !== changeId || typeof value.selectedOrderId !== "string" || (value.selectedOrderId && !uuid(value.selectedOrderId)) || typeof value.selectedItemId !== "string" || (value.selectedItemId && (!uuid(value.selectedItemId) || !value.selectedOrderId)) || !qualityRecord(value.drafts)) return null;
  for (const [key, draft] of Object.entries(value.drafts)) {
    if (!qualityRecord(draft) || !uuid(draft.orderId) || !uuid(draft.itemId) || key !== implementationKey(draft.orderId, draft.itemId) || !(draft.source === null || validQualitySource(draft.source)) || !(draft.request === null || validCaptureRequest(draft.request, changeId) && draft.request.order_id === draft.orderId && draft.request.item_id === draft.itemId && qualitySame(draft.request.source, draft.source))) return null;
    if (draft.capture !== null && (!basicCapture(draft.capture) || !qualityRecord(draft.request) || draft.capture.change_id !== changeId || draft.capture.change_revision !== draft.request.expected_change_revision || draft.capture.order_id !== draft.orderId || draft.capture.item_id !== draft.itemId || draft.capture.fact.executor_id !== principalId)) return null;
  }
  const pending = value.pending;
  if (pending !== null) {
    if (!qualityRecord(pending)) return null;
    const draft = value.drafts[implementationKey(value.selectedOrderId, value.selectedItemId)];
    if (!qualityRecord(draft)) return null;
    if (pending.stage === "capture") { if (!validCaptureRequest(pending.request, changeId) || pending.request.order_id !== value.selectedOrderId || pending.request.item_id !== value.selectedItemId || !qualitySame(pending.request, draft.request)) return null; }
    else if (!["inputs", "preview", "execute"].includes(String(pending.stage)) || pending.orderId !== value.selectedOrderId || pending.itemId !== value.selectedItemId || !validCommand(pending.command, productId, changeId) || pending.command.payload.item_id !== value.selectedItemId || !basicCapture(draft.capture) || pending.command.payload.fact_id !== draft.capture.fact_id || pending.command.payload.expected_change_revision !== draft.capture.change_revision || (pending.stage === "execute" && (typeof pending.command.payload.confirmation_token !== "string" || pending.command.payload.confirmation_token.length < 16))) return null;
  }
  return { selectedOrderId: value.selectedOrderId, selectedItemId: value.selectedItemId, drafts: value.drafts as Record<string, ImplementationDraft>, pending: pending as ImplementationPending | null };
}
