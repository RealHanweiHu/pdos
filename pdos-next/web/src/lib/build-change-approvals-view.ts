import type { CommandPlan } from "../components/change_control/contracts";
import { handoffTime } from "./build-handoff-view";
import { readOrderScope, type OrderApi, type OrderContext, type OrderReadSource, type OrderSource } from "./build-change-orders-view";
import { qualityReads, qualityRecord, qualityRevision, qualitySame, qualitySourceKey, qualityTime, sourceReads, validQualitySource } from "./build-quality-loop-view";
import { proofClockCurrent } from "./proof-clock";
import type { DefinitionSource } from "./product-view";
import type { SourceRead } from "./project-plan-view";

export const approvalDisciplines = ["engineering", "manufacturing", "customer", "regulatory"] as const;
export type ApprovalDiscipline = typeof approvalDisciplines[number];
export const approvalDisciplineNames: Record<ApprovalDiscipline, string> = { engineering: "工程", manufacturing: "制造", customer: "客户", regulatory: "法规" };
export type ApprovalDecision = { actor_id: string; at: string; text: string; sources: OrderReadSource[]; discipline: ApprovalDiscipline; decision_id: string; content_digest: string; expires_at: string | null };
export type ApprovalOrder = { id: string; assessment_id: string; assessment_digest: string; content_digest: string; plan: CommandPlan; policy: OrderReadSource; required_disciplines: ApprovalDiscipline[]; approvals: ApprovalDecision[]; implementations: unknown[]; effectivity: unknown[]; verifications: unknown[]; closure: unknown };
export type ApprovalScope = { context: OrderContext; orders: ApprovalOrder[]; sources: DefinitionSource[] };
export type ApprovalDraft = { discipline: "" | ApprovalDiscipline; text: string; expiresAt: string; sources: OrderSource[] };
export type ApprovalCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; operation: "change.order.approve"; payload: { change_id: string; expected_change_revision: number; visibility: string; discipline: ApprovalDiscipline; text: string; expires_at: string | null; sources: OrderSource[]; approval_token?: string | null }; source_read_set: SourceRead[]; category_id?: string | null };
export type ApprovalPending = { stage: "inputs" | "preview" | "execute"; orderId: string; command: ApprovalCommand };
export type ApprovalLocal = { selectedOrderId: string; drafts: Record<string, ApprovalDraft>; pending: ApprovalPending | null };
export type ApprovalPreview = { command: ApprovalCommand; expires_at: string | null; write_tier: "T2"; named_decision: true; review: Record<string, unknown> & { before: Record<string, unknown>; after: Record<string, unknown>; effect: string } };
export const blankApprovalLocal = (): ApprovalLocal => ({ selectedOrderId: "", drafts: {}, pending: null });
export const blankApprovalDraft = (): ApprovalDraft => ({ discipline: "", text: "", expiresAt: "", sources: [] });
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
const discipline = (value: unknown): value is ApprovalDiscipline => approvalDisciplines.includes(value as ApprovalDiscipline);
const provenance = (value: unknown): value is OrderReadSource => qualityRecord(value) && uuid(value.id) && qualityRevision(value.revision) && ["artifact", "domain", "command"].includes(String(value.kind)) && typeof value.position === "string" && !!value.position;
const nullableTime = (value: unknown) => value === null || !!qualityTime(value);
const exactKeys = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).every(key => keys.includes(key));
function validDecision(value: unknown): value is ApprovalDecision {
  return qualityRecord(value) && uuid(value.actor_id) && uuid(value.decision_id) && !!qualityTime(value.at) && typeof value.text === "string" && !!value.text.trim() && discipline(value.discipline) && typeof value.content_digest === "string" && !!value.content_digest && nullableTime(value.expires_at) && Array.isArray(value.sources) && !!value.sources.length && value.sources.every(provenance);
}
export function approvalOrders(context: OrderContext): ApprovalOrder[] {
  const values = context.change.request.orders;
  if (!Array.isArray(values) || values.some(value => !qualityRecord(value) || !uuid(value.id) || !uuid(value.assessment_id) || typeof value.assessment_digest !== "string" || typeof value.content_digest !== "string" || !value.content_digest || !qualityRecord(value.plan) || !uuid(value.plan.id) || !nullableTime(value.plan.expires_at) || !Array.isArray(value.plan.items) || !value.plan.items.length || !value.plan.items.every(qualityRecord) || !Array.isArray(value.plan.dispositions) || !value.plan.dispositions.every(qualityRecord) || !provenance(value.policy) || !Array.isArray(value.required_disciplines) || !value.required_disciplines.length || !value.required_disciplines.every(discipline) || new Set(value.required_disciplines).size !== value.required_disciplines.length || !Array.isArray(value.approvals) || !value.approvals.every(validDecision) || new Set(value.approvals.map(row => row.discipline)).size !== value.approvals.length || value.approvals.some(row => !(value.required_disciplines as unknown[]).includes(row.discipline) || row.content_digest !== value.content_digest) || !["implementations", "effectivity", "verifications"].every(key => Array.isArray(value[key])) || !("closure" in value))) throw new Error("变更令的完整计划、固定内容或具名决定尚未完整返回，请重新读取。");
  if (new Set(values.map(row => row.id)).size !== values.length) throw new Error("正式变更令身份重复，不能默认选择或批准。");
  return values as ApprovalOrder[];
}
export async function readApprovalScope(api: OrderApi, productId: string, changeId: string, projectId: string, current: () => boolean): Promise<ApprovalScope | null> {
  if (!uuid(productId) || !uuid(changeId) || (projectId && !uuid(projectId))) throw new Error("请选择明确的型号、项目及变更。");
  const value = await readOrderScope(api, productId, changeId, projectId, current);
  if (!value || !current()) return null;
  const context = value.context, indexed = value.changes.find(row => row.change_id === changeId);
  if (!context || !indexed || indexed.current !== true || indexed.id !== context.change.id || indexed.revision !== context.change.revision || indexed.project_id !== context.change.project_id || indexed.status !== context.change.status || context.change.current === false || (context.change.source_status !== undefined && context.change.source_status !== "current") || !qualityRecord(context.change.request.scope) || context.change.request.scope.product_id !== productId || context.change.request.scope.project_id !== context.change.project_id || context.change.request.id !== changeId || context.change.request.revision !== context.change.revision || context.change.request.status !== context.change.status) throw new Error("所选变更当前版本或项目范围已变化，请重新读取；不沿用历史批准入口。");
  return { context, orders: approvalOrders(context), sources: value.sources };
}
function canonical(value: unknown, field = ""): unknown {
  if (Array.isArray(value)) return value.map(row => canonical(row));
  if (qualityRecord(value)) return Object.fromEntries(Object.entries(value).filter(([key]) => key !== "approval_token").map(([key, row]) => [key, canonical(row, key)]));
  return ["expires_at", "valid_from", "valid_until"].includes(field) && value !== null ? handoffTime(value) : value;
}
function sameCommand(value: unknown, original: ApprovalCommand, reads: boolean): value is ApprovalCommand {
  if (!validApprovalCommand(value, original.product_id, original.payload.change_id) || !["command_id", "idempotency_key", "product_id", "expected_revision", "operation"].every(key => value[key as keyof ApprovalCommand] === original[key as keyof ApprovalCommand]) || (original.category_id != null && value.category_id !== original.category_id) || !qualitySame(canonical(value.payload), canonical(original.payload))) return false;
  return !reads || qualitySame(value.source_read_set, original.source_read_set);
}
export function approvalInputs(value: unknown, command: ApprovalCommand): ApprovalCommand | null {
  if (!qualityRecord(value) || typeof value.allowed !== "boolean" || !sameCommand(value.command, command, false)) throw new Error("服务器核对未保留同一具名请求及固定范围。");
  const returned = value.command;
  qualityReads(command.source_read_set, returned.source_read_set);
  if (command.source_read_set.some(read => !returned.source_read_set.some(row => row.artifact_id === read.artifact_id && row.expected_revision === read.expected_revision))) throw new Error("服务器核对丢失了本次明确选择的原文依据。");
  return value.allowed ? returned : null;
}
export function makeApprovalCommand(product: { id: string; revision: number }, scope: ApprovalScope, orderId: string, draft: ApprovalDraft, id: string, key: string, now = Date.now()): ApprovalCommand {
  const order = scope.orders.at(-1), change = scope.context.change;
  if (!order || order.id !== orderId || change.status !== "review" || !qualityRecord(change.request.scope) || change.request.scope.product_id !== product.id || !uuid(id) || !uuid(key) || !uuid(product.id) || !qualityRevision(product.revision) || !discipline(draft.discipline) || !order.required_disciplines.includes(draft.discipline) || order.approvals.some(row => row.discipline === draft.discipline)) throw new Error("请明确选择当前待批准变更令和尚待具名决定的本专业；历史计划不能在此批准。");
  const text = draft.text.trim(), expires = draft.expiresAt.trim();
  if (!text || text.length > 2000 || (expires && (!qualityTime(expires) || Date.parse(expires) <= now || (order.plan.expires_at !== null && Date.parse(expires) > Date.parse(order.plan.expires_at))))) throw new Error("请填写具名批准说明；有效期须含时区、晚于当前且不超过固定计划，留空不另设有效期。");
  if (new Set(draft.sources.map(qualitySourceKey)).size !== draft.sources.length || draft.sources.some(ref => !scope.sources.some(row => row.id === ref.id && row.revision === ref.revision && row.status === "active"))) throw new Error("所选依据必须是当前可读有效原文的精确版本，不能重复或沿用其他范围的材料。");
  return { command_id: id, idempotency_key: key, product_id: product.id, expected_revision: product.revision, operation: "change.order.approve", payload: { change_id: change.change_id, expected_change_revision: change.revision, visibility: change.visibility, discipline: draft.discipline, text, expires_at: expires || null, sources: draft.sources.map(row => ({ ...row })) }, source_read_set: sourceReads(draft.sources) };
}
export function validApprovalPreview(value: unknown, original: ApprovalCommand, scope: ApprovalScope, orderId: string, principalId: string, now = Date.now()): value is ApprovalPreview {
  if (!qualityRecord(value) || !sameCommand(value.command, original, true) || value.write_tier !== "T2" || value.named_decision !== true || !proofClockCurrent("T2", value.expires_at, now) || typeof value.command.payload.approval_token !== "string" || value.command.payload.approval_token.length < 16 || !qualityRecord(value.review) || value.review.operation !== original.operation || typeof value.review.effect !== "string" || !value.review.effect.trim() || !qualityRecord(value.review.before) || !qualityRecord(value.review.after)) return false;
  const before = value.review.before, after = value.review.after, expected = scope.orders.at(-1);
  if (!expected || expected.id !== orderId || before.id !== original.payload.change_id || before.revision !== original.payload.expected_change_revision || before.status !== "review" || !qualitySame(canonical(before), canonical(scope.context.change.request)) || after.id !== before.id || after.revision !== Number(before.revision) + 1 || !Array.isArray(after.orders) || after.orders.length !== scope.orders.length) return false;
  const unchanged = (request: Record<string, unknown>) => Object.fromEntries(Object.entries(request).filter(([key]) => !["revision", "status", "orders", "history"].includes(key)));
  if (!qualitySame(canonical(unchanged(before)), canonical(unchanged(after)))) return false;
  const order = after.orders.at(-1);
  if (!qualityRecord(order) || !Array.isArray(order.approvals) || order.approvals.length !== expected.approvals.length + 1 || !qualitySame(canonical(after.orders.slice(0, -1)), canonical(scope.orders.slice(0, -1))) || !qualitySame(canonical({ ...order, approvals: expected.approvals }), canonical(expected)) || !qualitySame(canonical(order.approvals.slice(0, -1)), canonical(expected.approvals))) return false;
  const decision = order.approvals.at(-1), payload = original.payload;
  if (!qualityRecord(decision) || decision.actor_id !== principalId || decision.discipline !== payload.discipline || decision.text !== payload.text || decision.content_digest !== expected.content_digest || decision.at !== "server_on_save" || decision.decision_id !== "actual_consumed_named_proof_on_save" || !qualitySame(canonical({ expires_at: decision.expires_at }), canonical({ expires_at: payload.expires_at })) || !Array.isArray(decision.sources) || !decision.sources.length || !decision.sources.every(provenance)) return false;
  if (!Array.isArray(before.sources) || !before.sources.length || !before.sources.every(provenance)) return false;
  const decisionSources = [...new Map([...before.sources, expected.policy].map(ref => [JSON.stringify([ref.kind, ref.id, ref.revision, ref.position]), ref])).values()];
  if (!qualitySame(decision.sources, decisionSources)) return false;
  const completed = new Set([...expected.approvals.map(row => row.discipline), payload.discipline]);
  return after.status === (expected.required_disciplines.every(row => completed.has(row)) ? "approved" : "review");
}
export function validApprovalReceipt(value: unknown, command: ApprovalCommand, principalId: string): value is { id: string; subject_id: string } {
  return qualityRecord(value) && uuid(value.id) && uuid(value.subject_id) && value.product_id === command.product_id && value.operation === command.operation && value.subject_type === "change_request" && value.subject_revision === command.payload.expected_change_revision + 1 && value.writer_id === principalId && value.requester_id === principalId && value.agent_run_id === null;
}
function validApprovalCommand(value: unknown, productId: string, changeId: string): value is ApprovalCommand {
  if (!qualityRecord(value) || !uuid(value.command_id) || !uuid(value.idempotency_key) || value.product_id !== productId || !qualityRevision(value.expected_revision) || value.operation !== "change.order.approve" || !qualityRecord(value.payload) || value.payload.change_id !== changeId || !qualityRevision(value.payload.expected_change_revision) || !["private", "category", "audience"].includes(String(value.payload.visibility)) || !discipline(value.payload.discipline) || typeof value.payload.text !== "string" || !value.payload.text.trim() || value.payload.text.length > 2000 || !nullableTime(value.payload.expires_at) || !Array.isArray(value.payload.sources) || !value.payload.sources.length || !value.payload.sources.every(validQualitySource) || !Array.isArray(value.source_read_set) || !exactKeys(value.payload, ["change_id", "expected_change_revision", "visibility", "discipline", "text", "expires_at", "sources", "approval_token"])) return false;
  try { qualityReads(value.source_read_set as SourceRead[]); } catch { return false; }
  return true;
}
export function restoreApprovals(value: unknown, productId: string, principalId: string, projectId: string, changeId: string): ApprovalLocal | null {
  if (!qualityRecord(value) || value.schema_version !== 1 || value.product_id !== productId || value.principal_id !== principalId || value.project_id !== projectId || value.change_id !== changeId || typeof value.selectedOrderId !== "string" || (value.selectedOrderId && !uuid(value.selectedOrderId)) || !qualityRecord(value.drafts)) return null;
  if (Object.entries(value.drafts).some(([id, row]) => !uuid(id) || !qualityRecord(row) || !(row.discipline === "" || discipline(row.discipline)) || typeof row.text !== "string" || typeof row.expiresAt !== "string" || !Array.isArray(row.sources) || !row.sources.every(validQualitySource))) return null;
  if (value.pending !== null && (!qualityRecord(value.pending) || !["inputs", "preview", "execute"].includes(String(value.pending.stage)) || !uuid(value.pending.orderId) || value.pending.orderId !== value.selectedOrderId || !validApprovalCommand(value.pending.command, productId, changeId) || (value.pending.stage === "execute" && (typeof value.pending.command.payload.approval_token !== "string" || value.pending.command.payload.approval_token.length < 16)))) return null;
  return { selectedOrderId: value.selectedOrderId, drafts: value.drafts as Record<string, ApprovalDraft>, pending: value.pending as ApprovalPending | null };
}
