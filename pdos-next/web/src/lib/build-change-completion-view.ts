import type { Ref } from "../components/change_control/contracts";
import type { OrderApi, OrderItem, OrderMissing, OrderReadSource } from "./build-change-orders-view";
import type { SourceRead } from "./project-plan-view";
import { qualityReads, qualityRecord, qualityRevision, qualitySame, qualityStable, qualityTime } from "./build-quality-loop-view";
import { proofClockCurrent } from "./proof-clock";

export const completionOperations = ["change.effectivity.record", "change.verification.record", "change.close"] as const;
export type CompletionOperation = typeof completionOperations[number];
export const completionNames: Record<CompletionOperation, string> = { "change.effectivity.record": "记录开发 Build 实际采用", "change.verification.record": "具名独立验证本变更", "change.close": "分别具名关闭本变更" };
export const completionTier = (operation: CompletionOperation): "T1" | "T2" => operation === "change.effectivity.record" ? "T1" : "T2";
export type FixedNativeRef = { id: string; revision: number };
export type RunScopeMapping = { item_id: string; run: Ref; sample_id: string; test_item_id: string; method: OrderReadSource; requirement_sha256: string; rationale: string };
type Target = { change_id: string; expected_change_revision: number; visibility: "private" | "category" | "audience" };
export type EffectivityPayload = Target & { item_id: string; lot: FixedNativeRef; sample_refs: Ref[]; confirmation_token?: string | null };
export type VerificationPayload = Target & { mappings: RunScopeMapping[]; text: string; approval_token?: string | null };
export type ClosePayload = Target & { text: string; approval_token?: string | null };
export type CompletionMaterial = { operation: "change.effectivity.record"; payload: EffectivityPayload } | { operation: "change.verification.record"; payload: VerificationPayload } | { operation: "change.close"; payload: ClosePayload };
export type CompletionCommand = CompletionMaterial & { command_id: string; idempotency_key: string; product_id: string; expected_revision: number; source_read_set: SourceRead[]; category_id?: string | null };
export type CompletionPreview = { command: CompletionCommand; expires_at: string | null; write_tier?: string; named_decision?: boolean; review: Record<string, unknown> & { before: Record<string, unknown>; after: Record<string, unknown>; effect: string } };
export type CompletionItem = { item: OrderItem; requirement_sha256: string; implemented_outputs: Ref[]; effectivity_recorded: boolean };
export type AdoptionOption = { lot: FixedNativeRef; build: FixedNativeRef; build_name: string; occurred_at: string; samples: { ref: Ref; label: string }[] };
export type RunMappingOption = { sample_id: string; test_item_id: string; test_item_label: string; method: OrderReadSource };
export type CompletionRun = { run: Ref; label: string; build: FixedNativeRef; mappings: RunMappingOption[] };
export type CompletionContext = { change_id: string; change_revision: number; product_revision: number; project_id: string; visibility: Target["visibility"]; order_id: string | null; content_digest: string | null; status: string; items: CompletionItem[]; adoptions: AdoptionOption[]; runs: CompletionRun[]; capabilities: Record<CompletionOperation, { allowed: boolean; blockers: OrderMissing[] }>; closure: unknown; required_source_read_set: SourceRead[] };
export type MappingDraft = { itemId: string; runKey: string; pairKey: string; rationale: string };
export type CompletionDraft = { itemId: string; adoptionKey: string; sampleKeys: string[]; mappings: MappingDraft[]; verificationText: string; closeText: string };
export type CompletionPending = { stage: "material"; request: CompletionMaterial } | { stage: "preview" | "execute"; command: CompletionCommand };
export type CompletionLocal = { draft: CompletionDraft; pending: CompletionPending | null };
export const blankCompletionDraft = (): CompletionDraft => ({ itemId: "", adoptionKey: "", sampleKeys: [], mappings: [], verificationText: "", closeText: "" });
export const blankCompletionLocal = (): CompletionLocal => ({ draft: blankCompletionDraft(), pending: null });
export const completionRefKey = (value: Ref | FixedNativeRef): string => JSON.stringify(["kind" in value ? value.kind : "", value.id, value.revision, "key" in value ? value.key ?? null : null]);
export const completionPairKey = (value: Pick<RunMappingOption, "sample_id" | "test_item_id">): string => JSON.stringify([value.sample_id, value.test_item_id]);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-(?:[0-9a-f]{4}-){3}[0-9a-f]{12}$/i.test(value);
const text = (value: unknown): value is string => typeof value === "string" && !!value.trim() && value.length <= 2000;
const hash = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{64}$/.test(value);
const exact = (value: Record<string, unknown>, keys: string[]) => Object.keys(value).every(key => keys.includes(key));
const fixed = (value: unknown): value is FixedNativeRef & Record<string, unknown> => qualityRecord(value) && uuid(value.id) && qualityRevision(value.revision);
const reference = (value: unknown, kind?: string): value is Ref => fixed(value) && qualityRecord(value) && typeof value.kind === "string" && !!value.kind && (!kind || value.kind === kind) && value.key == null;
const source = (value: unknown): value is OrderReadSource => fixed(value) && qualityRecord(value) && ["artifact", "domain", "command"].includes(String(value.kind)) && typeof value.position === "string" && !!value.position;
const gaps = (value: unknown): value is OrderMissing[] => Array.isArray(value) && value.every(row => qualityRecord(row) && typeof row.code === "string" && typeof row.detail === "string");
const unique = <T>(values: T[], key: (row: T) => string): boolean => new Set(values.map(key)).size === values.length;
export function normalizeCompletionContext(value: unknown, changeId: string, projectId = ""): CompletionContext {
  if (!qualityRecord(value) || value.change_id !== changeId || !uuid(changeId) || !qualityRevision(value.change_revision) || !qualityRevision(value.product_revision) || !uuid(value.project_id) || projectId && value.project_id !== projectId || !["private", "category", "audience"].includes(String(value.visibility)) || !(value.order_id === null || uuid(value.order_id)) || !(value.content_digest === null || text(value.content_digest)) || typeof value.status !== "string" || !Array.isArray(value.items) || !Array.isArray(value.adoptions) || !Array.isArray(value.runs) || !qualityRecord(value.capabilities) || !("closure" in value) || !Array.isArray(value.required_source_read_set)) throw new Error("本变更的当前版本、项目或办理范围尚未完整取得，请重新读取。");
  const capabilities = value.capabilities;
  if (completionOperations.some(operation => !qualityRecord(capabilities[operation]) || typeof capabilities[operation].allowed !== "boolean" || !gaps(capabilities[operation].blockers))) throw new Error("实际采用、独立验证或关闭的逐操作条件尚未完整返回。");
  if (value.items.some(row => !qualityRecord(row) || !qualityRecord(row.item) || !uuid(row.item.id) || !qualityRecord(row.item.selection) || !Array.isArray(row.item.selection.objects) || !row.item.selection.objects.every(fixed) || !qualityRecord(row.item.intent) || !uuid(row.item.intent.id) || !text(row.item.intent.description) || !text(row.item.verification_requirement) || !hash(row.requirement_sha256) || typeof row.effectivity_recorded !== "boolean" || !Array.isArray(row.implemented_outputs) || !row.implemented_outputs.every(ref => reference(ref))) || !unique(value.items, row => String(row.item.id))) throw new Error("固定计划项、核验要求或实际实施输出尚未完整返回。");
  if (value.adoptions.some(row => !qualityRecord(row) || !fixed(row.lot) || !fixed(row.build) || !text(row.build_name) || !qualityTime(row.occurred_at) || !Array.isArray(row.samples) || row.samples.some(sample => !qualityRecord(sample) || !reference(sample.ref, "sample") || !text(sample.label)) || !unique(row.samples, sample => completionRefKey(sample.ref))) || !unique(value.adoptions, row => completionRefKey(row.lot))) throw new Error("实际开发 Build、批次或样件候选缺少准确版本。");
  if (value.runs.some(row => !qualityRecord(row) || !reference(row.run, "test_run") || !text(row.label) || !fixed(row.build) || !Array.isArray(row.mappings) || row.mappings.some(pair => !qualityRecord(pair) || !uuid(pair.sample_id) || typeof pair.test_item_id !== "string" || !pair.test_item_id || pair.test_item_id.length > 120 || !text(pair.test_item_label) || !source(pair.method)) || !unique(row.mappings, completionPairKey)) || !unique(value.runs, row => completionRefKey(row.run))) throw new Error("真实测试运行及样件、测试项、固定方法候选尚未完整返回。");
  qualityReads(value.required_source_read_set as SourceRead[]);
  return value as unknown as CompletionContext;
}
export async function readCompletionContext(api: OrderApi, productId: string, changeId: string, projectId: string, current: () => boolean): Promise<CompletionContext | null> {
  if (!uuid(productId) || !uuid(changeId) || projectId && !uuid(projectId)) throw new Error("请选择明确的产品、项目与变更。");
  if (!current()) return null;
  const value = await api<unknown>(`v1/products/${productId}/change-execution/completion-context?change_id=${encodeURIComponent(changeId)}`);
  return current() ? normalizeCompletionContext(value, changeId, projectId) : null;
}
export function completionMaterial(context: CompletionContext, operation: CompletionOperation, draft: CompletionDraft): CompletionMaterial {
  if (!context.order_id || !context.content_digest || !context.capabilities[operation].allowed) throw new Error("当前操作尚有范围、真实事实或具名职责缺项，请重新核对。");
  const target: Target = { change_id: context.change_id, expected_change_revision: context.change_revision, visibility: context.visibility };
  if (operation === "change.effectivity.record") {
    const item = context.items.find(row => row.item.id === draft.itemId), adoption = context.adoptions.find(row => completionRefKey(row.lot) === draft.adoptionKey), samples = draft.sampleKeys.map(key => adoption?.samples.find(row => completionRefKey(row.ref) === key));
    if (!item || item.effectivity_recorded || !item.implemented_outputs.length || !adoption || !samples.length || samples.some(row => !row) || new Set(draft.sampleKeys).size !== draft.sampleKeys.length) throw new Error("请明确选择本项已实施计划、真实开发 Build 批次及其实际样件。");
    return { operation, payload: { ...target, item_id: item.item.id, lot: { ...adoption.lot }, sample_refs: samples.map(row => ({ ...row!.ref })) } };
  }
  if (operation === "change.close") { if (!text(draft.closeText.trim())) throw new Error("请填写本次独立的具名关闭说明。"); return { operation, payload: { ...target, text: draft.closeText.trim() } }; }
  if (!text(draft.verificationText.trim()) || !draft.mappings.length) throw new Error("请填写具名验证说明，逐项选择真实 Run 与样件、测试项的对应依据。");
  const mappings = draft.mappings.map(row => {
    const item = context.items.find(item => item.item.id === row.itemId), run = context.runs.find(run => completionRefKey(run.run) === row.runKey), pair = run?.mappings.find(pair => completionPairKey(pair) === row.pairKey);
    if (!item || !run || !pair || !text(row.rationale.trim())) throw new Error("每条对应均须明确计划项、固定 Run、实际样件和测试项，以及覆盖该核验要求的理由。");
    return { item_id: item.item.id, run: { ...run.run }, sample_id: pair.sample_id, test_item_id: pair.test_item_id, method: { ...pair.method }, requirement_sha256: item.requirement_sha256, rationale: row.rationale.trim() };
  });
  if (!unique(mappings, row => JSON.stringify([row.item_id, completionRefKey(row.run), row.sample_id, row.test_item_id])) || context.items.some(row => !mappings.some(mapping => mapping.item_id === row.item.id))) throw new Error("请逐一覆盖全部批准计划项，不重复采用同一条对应。");
  return { operation, payload: { ...target, mappings, text: draft.verificationText.trim() } };
}
function validMaterial(value: unknown, changeId: string, tokens = false): value is CompletionMaterial & Record<string, unknown> {
  if (!qualityRecord(value) || !completionOperations.includes(value.operation as CompletionOperation) || !qualityRecord(value.payload)) return false;
  const payload = value.payload, common = ["change_id", "expected_change_revision", "visibility"];
  if (payload.change_id !== changeId || !uuid(changeId) || !qualityRevision(payload.expected_change_revision) || !["private", "category", "audience"].includes(String(payload.visibility))) return false;
  const token = completionTier(value.operation as CompletionOperation) === "T1" ? "confirmation_token" : "approval_token";
  if (payload[token] != null && (!tokens || typeof payload[token] !== "string" || payload[token].length < 16 || payload[token].length > 512)) return false;
  if (value.operation === "change.effectivity.record") return exact(payload, [...common, "item_id", "lot", "sample_refs", ...(tokens ? [token] : [])]) && uuid(payload.item_id) && fixed(payload.lot) && exact(payload.lot as Record<string, unknown>, ["id", "revision"]) && Array.isArray(payload.sample_refs) && !!payload.sample_refs.length && payload.sample_refs.every(ref => reference(ref, "sample")) && unique(payload.sample_refs, completionRefKey);
  if (!text(payload.text) || !exact(payload, [...common, "text", ...(value.operation === "change.verification.record" ? ["mappings"] : []), ...(tokens ? [token] : [])])) return false;
  return value.operation === "change.close" || Array.isArray(payload.mappings) && !!payload.mappings.length && payload.mappings.every(row => qualityRecord(row) && exact(row, ["item_id", "run", "sample_id", "test_item_id", "method", "requirement_sha256", "rationale"]) && uuid(row.item_id) && reference(row.run, "test_run") && uuid(row.sample_id) && typeof row.test_item_id === "string" && !!row.test_item_id && row.test_item_id.length <= 120 && source(row.method) && hash(row.requirement_sha256) && text(row.rationale));
}
export function validCompletionCommand(value: unknown, productId: string, changeId: string): value is CompletionCommand {
  if (!validMaterial(value, changeId, true) || !qualityRecord(value) || value.product_id !== productId || !uuid(productId) || !uuid(value.command_id) || (typeof value.idempotency_key !== "string" || value.idempotency_key.length < 8 || value.idempotency_key.length > 160) || !qualityRevision(value.expected_revision) || !Array.isArray(value.source_read_set)) return false;
  try { qualityReads(value.source_read_set as SourceRead[]); } catch { return false; }
  return true;
}
function intent(value: CompletionMaterial): CompletionMaterial { const { confirmation_token: _confirm, approval_token: _approve, ...payload } = value.payload as EffectivityPayload & VerificationPayload; void _confirm; void _approve; return { operation: value.operation, payload } as CompletionMaterial; }
export function preparedCompletion(value: unknown, request: CompletionMaterial, productId: string, productRevision: number): CompletionCommand | null {
  if (!qualityRecord(value) || typeof value.allowed !== "boolean" || !qualityRecord(value.review)) throw new Error("尚未取得同一操作的服务器实际核对，本次未提交。");
  if (!value.allowed) return null;
  if (!validCompletionCommand(value.command, productId, request.payload.change_id) || value.command.expected_revision !== productRevision || !qualitySame(intent(value.command), intent(request)) || (value.command.payload as EffectivityPayload).confirmation_token != null || (value.command.payload as ClosePayload).approval_token != null) throw new Error("服务器材料未保留本次准确输入、固定版本和操作，请保留原请求核对。");
  return value.command;
}
export function validCompletionPreview(value: unknown, original: CompletionCommand, context: CompletionContext, principalId: string, now = Date.now()): value is CompletionPreview {
  if (!qualityRecord(value) || !validCompletionCommand(value.command, original.product_id, original.payload.change_id)) return false;
  const command = value.command;
  if (!["command_id", "idempotency_key", "product_id", "expected_revision", "operation", "category_id"].every(key => command[key as keyof CompletionCommand] === original[key as keyof CompletionCommand]) || !qualitySame(intent(value.command), intent(original)) || !qualitySame(value.command.source_read_set, original.source_read_set) || !proofClockCurrent(completionTier(original.operation), value.expires_at, now) || !qualityRecord(value.review) || value.review.operation !== original.operation || value.review.proof_tier !== completionTier(original.operation) || !text(value.review.effect) || !qualityRecord(value.review.before) || !qualityRecord(value.review.after)) return false;
  const token = completionTier(original.operation) === "T1" ? "confirmation_token" : "approval_token", payload = value.command.payload as unknown as Record<string, unknown>;
  if (typeof payload[token] !== "string" || payload[token].length < 16 || completionTier(original.operation) === "T2" && (value.write_tier !== "T2" || value.named_decision !== true)) return false;
  const before = value.review.before, after = value.review.after;
  if (before.id !== context.change_id || before.revision !== original.payload.expected_change_revision || before.revision !== context.change_revision || before.status !== context.status || after.id !== before.id || after.revision !== Number(before.revision) + 1 || !qualityRecord(before.scope) || before.scope.product_id !== original.product_id || before.scope.project_id !== context.project_id || !Array.isArray(before.orders) || !Array.isArray(after.orders) || before.orders.length !== after.orders.length || !before.orders.length) return false;
  const old = before.orders.at(-1), next = after.orders.at(-1);
  if (!qualityRecord(old) || !qualityRecord(next) || old.id !== context.order_id || old.content_digest !== context.content_digest || !qualityRecord(old.plan) || !qualitySame(old.plan.items, context.items.map(row => row.item)) || !qualitySame(before.orders.slice(0, -1), after.orders.slice(0, -1))) return false;
  const unchanged = (request: Record<string, unknown>) => Object.fromEntries(Object.entries(request).filter(([key]) => !["revision", "status", "orders", "history"].includes(key)));
  if (!qualitySame(unchanged(before), unchanged(after))) return false;
  const field = original.operation === "change.effectivity.record" ? "effectivity" : original.operation === "change.verification.record" ? "verifications" : "closure";
  if (!qualitySame({ ...next, [field]: old[field] }, old)) return false;
  if (field === "closure") { const latest = Array.isArray(old.verifications) ? old.verifications.at(-1) : null; return old.closure === null && qualityRecord(latest) && qualityRecord(latest.fact) && latest.fact.result === "pass" && qualityRecord(next.closure) && next.closure.actor_id === principalId && next.closure.text === (original.payload as ClosePayload).text && after.status === "closed"; }
  if (!Array.isArray(old[field]) || !Array.isArray(next[field]) || next[field].length !== old[field].length + 1 || !qualitySame(next[field].slice(0, -1), old[field])) return false;
  const added = next[field].at(-1);
  if (!qualityRecord(added)) return false;
  if (field === "effectivity") { const payload = original.payload as EffectivityPayload, item = context.items.find(row => row.item.id === payload.item_id); return !!item && added.item_id === payload.item_id && added.intent_id === item.item.intent.id && uuid(added.id) && ["sent", "accepted", "effective"].includes(String(added.stage)) && ["succeeded", "failed", "unknown"].includes(String(added.outcome)) && qualitySame(added.output_refs, item.implemented_outputs) && ["implementing", "verifying"].includes(String(after.status)); }
  const fact = added.fact, involved = new Set([before.requester_id, ...(Array.isArray(old.approvals) ? old.approvals.filter(qualityRecord).map(row => row.actor_id) : []), ...(Array.isArray(old.implementations) ? old.implementations.filter(qualityRecord).map(row => row.executor_id) : [])]);
  const outputRefs = qualityRecord(fact) && Array.isArray(fact.output_refs) ? fact.output_refs : [];
  return added.actor_id === principalId && added.text === (original.payload as VerificationPayload).text && qualityRecord(fact) && uuid(fact.id) && fact.verifier_id === principalId && fact.content_digest === context.content_digest && Array.isArray(fact.item_ids) && qualitySame([...fact.item_ids].sort(), context.items.map(row => row.item.id).sort()) && Array.isArray(fact.executor_ids) && !fact.executor_ids.includes(principalId) && !involved.has(principalId) && Array.isArray(fact.output_refs) && fact.output_refs.every(ref => reference(ref)) && context.items.flatMap(row => row.implemented_outputs).every(ref => outputRefs.some((actual: Ref) => completionRefKey(actual) === completionRefKey(ref))) && Array.isArray(fact.sources) && !!fact.sources.length && fact.sources.every(source) && !!qualityTime(fact.observed_from) && !!qualityTime(fact.observed_until) && Date.parse(String(fact.observed_from)) <= Date.parse(String(fact.observed_until)) && Date.parse(String(fact.observed_until)) <= now && ["pass", "fail"].includes(String(fact.result)) && fact.current === true && fact.applicable === true && after.status === "verifying";
}
export function validCompletionReceipt(value: unknown, command: CompletionCommand, principalId: string): value is { id: string; subject_id: string } {
  return qualityRecord(value) && uuid(value.id) && uuid(value.subject_id) && value.product_id === command.product_id && value.operation === command.operation && value.subject_type === "change_request" && value.subject_revision === command.payload.expected_change_revision + 1 && value.writer_id === principalId && value.requester_id === principalId && value.agent_run_id === null;
}
export function restoreCompletion(value: unknown, productId: string, principalId: string, projectId: string, changeId: string): CompletionLocal | null {
  if (!qualityRecord(value) || value.schema_version !== 1 || value.product_id !== productId || value.principal_id !== principalId || value.project_id !== projectId || value.change_id !== changeId || !qualityRecord(value.draft)) return null;
  const draft = value.draft;
  if (!["itemId", "adoptionKey", "verificationText", "closeText"].every(key => typeof draft[key] === "string") || !Array.isArray(draft.sampleKeys) || !draft.sampleKeys.every(row => typeof row === "string") || !Array.isArray(draft.mappings) || draft.mappings.some(row => !qualityRecord(row) || !["itemId", "runKey", "pairKey", "rationale"].every(key => typeof row[key] === "string"))) return null;
  if (value.pending !== null) {
    const pending = value.pending;
    if (!qualityRecord(pending)) return null;
    if (pending.stage === "material") { if (!validMaterial(pending.request, changeId)) return null; }
    else if (pending.stage === "preview" || pending.stage === "execute") {
      if (!validCompletionCommand(pending.command, productId, changeId)) return null;
      if (pending.stage === "execute") { const token = completionTier(pending.command.operation) === "T1" ? "confirmation_token" : "approval_token", payload = pending.command.payload as unknown as Record<string, unknown>; if (typeof payload[token] !== "string" || payload[token].length < 16) return null; }
    } else return null;
  }
  return { draft: draft as CompletionDraft, pending: value.pending as CompletionPending | null };
}
export const completionContextKey = (context: CompletionContext | null): string => JSON.stringify(qualityStable(context));
export function completionObservations(review: unknown): { run_id: string; revision: number; observations: Record<string, unknown>[] }[] {
  if (!qualityRecord(review) || !qualityRecord(review.source_basis) || !qualityRecord(review.source_basis.completion)) return [];
  const readings = new Map<string, { run_id: string; revision: number; observations: Record<string, unknown>[] }>();
  for (const owner of Object.values(review.source_basis.completion)) {
    if (!qualityRecord(owner) || owner.schema_version !== "pdos-native-change-run-verification-v1" || !qualityRecord(owner.runs)) continue;
    for (const [identity, run] of Object.entries(owner.runs)) {
      const parts = identity.split(":");
      if (parts.length !== 4 || parts[0] !== "test_run" || !uuid(parts[1]) || !qualityRecord(run) || !qualityRevision(run.run_revision) || String(run.run_revision) !== parts[2] || !Array.isArray(run.observations) || !run.observations.every(qualityRecord)) continue;
      readings.set(identity, { run_id: parts[1], revision: run.run_revision, observations: run.observations });
    }
  }
  return [...readings.values()];
}
