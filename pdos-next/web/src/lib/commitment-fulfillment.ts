import { workCommandsRoot, workRecord, workRoot, workSame, workUuid, type ProjectWorkApi, type WorkCheck, type WorkRead, type WorkRef, type WorkResult, type WorkScope, type WorkSource } from "./project-work";

export const fulfillmentOperation = "work.commitment.review" as const;
export type FulfillmentReview = WorkRef & { decision: "accepted" | "returned"; state: "open" | "fulfilled"; checks: WorkCheck[]; actor_id: string; recorded_at: string; receipt_id: string };
export type FulfillmentCommitment = WorkRef & {
  series_id: string; task_id: string; promisor_id: string; recipient_id: string; outcome_keys: string[];
  promised_at: string | null; original_timezone: string; calendar_id: string | null; status: "current" | "superseded";
  task: { id: string; version_id: string; revision: number; title: string; state: "proposed" | "assigned" | "accepted" | "in_progress" | "submitted" | "completed" };
  submission: null | (WorkRef & { actor_id: string; results: WorkResult[]; time: { actual_at: string; original_timezone: string; calendar_id: string | null; actor_id: string; recorded_at: string } });
  fulfillment: { state: "open" | "fulfilled"; revision: number; review: FulfillmentReview | null; history: FulfillmentReview[] };
  can_review: boolean; sources: WorkSource[];
};
export type FulfillmentView = { project: { id: string; revision: number; name: string; owner_id: string; visibility: string }; product_revision: number; as_of: string; commitments: FulfillmentCommitment[] };
export type FulfillmentPayload = { project_id: string; commitment: WorkRef; task: WorkRef; submission: WorkRef; expected_review_revision: number; decision: "accepted" | "returned"; checks: WorkCheck[]; sources: WorkSource[]; reason: string; confirmation_token?: string | null };
export type FulfillmentCommand = { command_id: string; idempotency_key: string; operation: typeof fulfillmentOperation; category_id: string; product_id: string; expected_revision: number; source_read_set: WorkRead[]; payload: FulfillmentPayload };
export type FulfillmentInputs = { payload: FulfillmentPayload; required_source_read_set: WorkRead[]; review: Record<string, unknown> };
export type FulfillmentPending = { stage: "inputs" | "preview" | "execute"; command: FulfillmentCommand; inputs?: FulfillmentInputs };
export type FulfillmentPrepared = { command: FulfillmentCommand; review: Record<string, unknown>; expires_at: string };
export type FulfillmentReceipt = { id: string; operation: typeof fulfillmentOperation; subject_id: string; subject_revision: number; subject_type: string };
export type FulfillmentLocal = { schema_version: 1; scope: WorkScope; draft: FulfillmentPayload | null; pending: FulfillmentPending | null; receipt: FulfillmentReceipt | null; completed: FulfillmentCommand | null };
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
const rev = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const zeroRev = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) >= 0;
const ref = (v: unknown): v is WorkRef & Record<string, unknown> => workRecord(v) && workUuid(v.id) && rev(v.revision);
const instant = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const nullableId = (v: unknown) => v === null || workUuid(v);
const zone = (v: unknown): v is string => { if (!text(v)) return false; try { new Intl.DateTimeFormat("en", { timeZone: v }); return true; } catch { return false; } };
const unique = (v: string[]) => new Set(v).size === v.length;
const source = (v: unknown): v is WorkSource => ref(v) && workRecord(v) && v.kind === "artifact" && text(v.position);
const sources = (v: unknown, required = true): v is WorkSource[] => Array.isArray(v) && (!required || v.length > 0) && v.every(source);
const checks = (v: unknown): v is WorkCheck[] => Array.isArray(v) && v.length > 0 && v.every(row => workRecord(row) && text(row.key) && ["accepted", "rejected", "unknown"].includes(String(row.decision)) && typeof row.reason === "string") && unique(v.map(row => row.key));
const reads = (v: unknown): v is WorkRead[] => Array.isArray(v) && v.length > 0 && v.every(row => workRecord(row) && workUuid(row.artifact_id) && rev(row.expected_revision)) && unique(v.map(row => row.artifact_id));
const results = (v: unknown): v is WorkResult[] => Array.isArray(v) && v.length > 0 && v.every(row => workRecord(row) && text(row.key) && text(row.text) && ["present", "partial", "missing"].includes(String(row.status)) && sources(row.sources, row.status === "present")) && unique(v.map(row => row.key));
function review(v: unknown): v is FulfillmentReview { return ref(v) && workRecord(v) && ["accepted", "returned"].includes(String(v.decision)) && ["open", "fulfilled"].includes(String(v.state)) && checks(v.checks) && v.checks.every(row => text(row.reason)) && workUuid(v.actor_id) && instant(v.recorded_at) && workUuid(v.receipt_id); }
function commitment(v: unknown): v is FulfillmentCommitment {
  if (!ref(v) || !workRecord(v) || !workUuid(v.series_id) || !workUuid(v.task_id) || !workUuid(v.promisor_id) || !workUuid(v.recipient_id) || !Array.isArray(v.outcome_keys) || !v.outcome_keys.length || !v.outcome_keys.every(text) || !unique(v.outcome_keys) || !(v.promised_at === null || instant(v.promised_at)) || !zone(v.original_timezone) || !nullableId(v.calendar_id) || !["current", "superseded"].includes(String(v.status)) || typeof v.can_review !== "boolean" || !sources(v.sources)) return false;
  const task = v.task, sub = v.submission, state = v.fulfillment;
  if (!ref(task) || !workRecord(task) || task.id !== v.task_id || !workUuid(task.version_id) || !text(task.title) || !["proposed", "assigned", "accepted", "in_progress", "submitted", "completed"].includes(String(task.state))) return false;
  if (sub !== null && (!ref(sub) || !workRecord(sub) || !workUuid(sub.actor_id) || !results(sub.results) || !workRecord(sub.time) || !instant(sub.time.actual_at) || !zone(sub.time.original_timezone) || !nullableId(sub.time.calendar_id) || !workUuid(sub.time.actor_id) || !instant(sub.time.recorded_at))) return false;
  return workRecord(state) && ["open", "fulfilled"].includes(String(state.state)) && zeroRev(state.revision) && (state.review === null || review(state.review)) && Array.isArray(state.history) && state.history.every(review) && unique(state.history.map(row => row.id)) && (state.revision === 0 ? state.review === null && state.history.length === 0 && state.state === "open" : review(state.review) && state.review.revision === state.revision && state.review.state === state.state && state.history.some(row => workSame(row, state.review)));
}
export function parseFulfillmentView(v: unknown, scope: WorkScope): FulfillmentView {
  if (!workRecord(v) || !ref(v.project) || !workRecord(v.project) || v.project.id !== scope.projectId || !text(v.project.name) || !workUuid(v.project.owner_id) || !text(v.project.visibility) || !rev(v.product_revision) || !instant(v.as_of) || !Array.isArray(v.commitments) || !v.commitments.every(commitment) || !unique(v.commitments.map(row => row.id))) throw new Error("承诺履行资料未完整取得，不能当作空列表。");
  return v as FulfillmentView;
}
export const fulfillmentRoot = (scope: WorkScope) => `${workRoot(scope)}/project-work/fulfillment`;
export async function readFulfillment(api: ProjectWorkApi, scope: WorkScope) { return parseFulfillmentView(await api<unknown>(`${fulfillmentRoot(scope)}?project_id=${encodeURIComponent(scope.projectId)}`), scope); }
export function fulfillmentSemantic(payload: FulfillmentPayload) { const result = structuredClone(payload); delete result.confirmation_token; return result; }
export function parseFulfillmentPayload(v: unknown, scope: WorkScope, complete = true): FulfillmentPayload {
  const allowed = ["project_id", "commitment", "task", "submission", "expected_review_revision", "decision", "checks", "sources", "reason", "confirmation_token"];
  if (!workRecord(v) || Object.keys(v).some(key => !allowed.includes(key)) || v.project_id !== scope.projectId || !ref(v.commitment) || !ref(v.task) || !ref(v.submission) || !zeroRev(v.expected_review_revision) || !["accepted", "returned"].includes(String(v.decision)) || !checks(v.checks) || !sources(v.sources) || typeof v.reason !== "string" || (complete && (!text(v.reason) || !v.checks.every(row => text(row.reason)))) || !(v.confirmation_token == null || typeof v.confirmation_token === "string" && v.confirmation_token.length >= 20)) throw new Error("须核对本项目固定承诺、原提交版本及每项成果，并填写来源与理由。");
  if (complete && (v.decision === "accepted" ? v.checks.some(row => row.decision !== "accepted") : v.checks.every(row => row.decision === "accepted"))) throw new Error("履行接收须逐项满足；退回须明确至少一项未接收成果。");
  return structuredClone(v) as FulfillmentPayload;
}
export function canReviewFulfillment(row: FulfillmentCommitment, scope: WorkScope) { return row.can_review && row.status === "current" && row.recipient_id === scope.principalId && row.fulfillment.state === "open" && row.submission !== null; }
export function fulfillmentDraft(row: FulfillmentCommitment, scope: WorkScope): FulfillmentPayload {
  if (!canReviewFulfillment(row, scope) || !row.submission) throw new Error("仅本条承诺的接收人可核对当前原提交。");
  return { project_id: scope.projectId, commitment: { id: row.id, revision: row.revision }, task: { id: row.task.id, revision: row.task.revision }, submission: { id: row.submission.id, revision: row.submission.revision }, expected_review_revision: row.fulfillment.revision, decision: "returned", checks: row.outcome_keys.map(key => ({ key, decision: "unknown", reason: "" })), sources: structuredClone(row.sources), reason: "" };
}
export function fulfillmentDraftCurrent(payload: FulfillmentPayload, row: FulfillmentCommitment, scope: WorkScope) {
  return canReviewFulfillment(row, scope) && workSame(payload.commitment, { id: row.id, revision: row.revision }) && workSame(payload.task, { id: row.task.id, revision: row.task.revision }) && workSame(payload.submission, row.submission && { id: row.submission.id, revision: row.submission.revision }) && payload.expected_review_revision === row.fulfillment.revision && workSame(payload.checks.map(v => v.key).sort(), [...row.outcome_keys].sort());
}
export function newFulfillmentCommand(scope: WorkScope, productRevision: number, payload: FulfillmentPayload, row: FulfillmentCommitment): FulfillmentCommand {
  const parsed = parseFulfillmentPayload(payload, scope);
  if (!rev(productRevision) || parsed.confirmation_token != null || !fulfillmentDraftCurrent(parsed, row, scope)) throw new Error("固定承诺或原提交已变化，请重新选择当前材料。");
  if (parsed.decision === "accepted" && row.outcome_keys.some(key => row.submission?.results.find(result => result.key === key)?.status !== "present")) throw new Error("全部承诺成果（含可选成果）实际提供后才可接收履行。");
  const found = new Map<string, number>(); for (const s of parsed.sources) { if (found.has(s.id) && found.get(s.id) !== s.revision) throw new Error("同一来源不能引用两个版本。"); found.set(s.id, s.revision); }
  return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: fulfillmentOperation, category_id: scope.categoryId, product_id: scope.productId, expected_revision: productRevision, source_read_set: [...found].sort(([a], [b]) => a.localeCompare(b)).map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision })), payload: parsed };
}
export function validFulfillmentCommand(v: unknown, scope: WorkScope): v is FulfillmentCommand {
  if (!workRecord(v) || !workUuid(v.command_id) || !workUuid(v.idempotency_key) || v.operation !== fulfillmentOperation || v.category_id !== scope.categoryId || v.product_id !== scope.productId || !rev(v.expected_revision) || !reads(v.source_read_set)) return false;
  try { const payload = parseFulfillmentPayload(v.payload, scope), actualReads = v.source_read_set; return payload.sources.every(s => actualReads.some(r => r.artifact_id === s.id && r.expected_revision === s.revision)); } catch { return false; }
}
function input(v: unknown, c: FulfillmentCommand, scope: WorkScope): FulfillmentInputs | null {
  if (!workRecord(v) || !reads(v.required_source_read_set) || !workRecord(v.review)) return null;
  try { const payload = parseFulfillmentPayload(v.payload, scope); if (payload.confirmation_token != null || !workSame(fulfillmentSemantic(payload), fulfillmentSemantic(c.payload)) || !c.source_read_set.every(r => (v.required_source_read_set as WorkRead[]).some(actual => workSame(actual, r)))) return null; return { payload, required_source_read_set: v.required_source_read_set, review: v.review }; } catch { return null; }
}
export function fulfillmentPrepared(v: unknown, c: FulfillmentCommand, scope: WorkScope, now = Date.now()): FulfillmentPrepared | null {
  if (!workRecord(v) || !validFulfillmentCommand(v.command, scope) || !workRecord(v.review) || !instant(v.expires_at) || Date.parse(v.expires_at) <= now || typeof v.command.payload.confirmation_token !== "string" || (v.confirmation_token != null && v.confirmation_token !== v.command.payload.confirmation_token)) return null;
  const a = { ...c, payload: fulfillmentSemantic(c.payload) }, b = { ...v.command, payload: fulfillmentSemantic(v.command.payload) };
  return workSame(a, b) ? { command: v.command, review: v.review, expires_at: v.expires_at } : null;
}
export function fulfillmentPreviewCurrent(value: FulfillmentPrepared, now = Date.now()) { return Date.parse(value.expires_at) > now; }
function receipt(v: unknown, c: FulfillmentCommand): v is FulfillmentReceipt { return workRecord(v) && workUuid(v.id) && v.operation === fulfillmentOperation && workUuid(v.subject_id) && rev(v.subject_revision) && text(v.subject_type) && c.operation === v.operation; }
export async function runFulfillmentRequest(api: ProjectWorkApi, pending: FulfillmentPending, scope: WorkScope, onStage: (v: FulfillmentPending) => void, active: () => boolean) {
  if (!validFulfillmentCommand(pending.command, scope) || !["inputs", "preview", "execute"].includes(pending.stage) || (pending.stage !== "execute" && pending.command.payload.confirmation_token != null) || (pending.stage === "execute" && typeof pending.command.payload.confirmation_token !== "string")) throw new Error("原履行核对请求与当前范围或确认阶段不一致。");
  let step = pending; if (!active()) return null;
  if (step.stage === "inputs") { const raw = await api<unknown>(`${fulfillmentRoot(scope)}/inputs`, step.command); if (!active()) return null; const value = input(raw, step.command, scope); if (!value) throw new Error("服务器未返回与原请求一致的履行材料。"); step = { stage: "preview", command: { ...step.command, payload: value.payload, source_read_set: structuredClone(value.required_source_read_set) }, inputs: value }; onStage(step); }
  if (step.stage === "preview") { const raw = await api<unknown>(`${workCommandsRoot(scope)}/preview`, step.command); if (!active()) return null; const prepared = fulfillmentPrepared(raw, step.command, scope); if (!prepared) throw new Error("尚未取得固定载荷和版本一致的共同确认。"); return { stage: "preview" as const, prepared }; }
  const value = await api<unknown>(workCommandsRoot(scope), step.command); if (!active()) return null; if (!receipt(value, step.command)) throw new Error("保存回执尚未核实，请保留原请求。"); return { stage: "saved" as const, receipt: value, command: step.command };
}
export const fulfillmentStorageKey = (scope: WorkScope) => `pdos.commitment-fulfillment.v1:${scope.principalId}:${scope.categoryId}:${scope.productId}:${scope.projectId}`;
export const blankFulfillmentLocal = (scope: WorkScope): FulfillmentLocal => ({ schema_version: 1, scope: structuredClone(scope), draft: null, pending: null, receipt: null, completed: null });
export function restoreFulfillmentLocal(v: unknown, scope: WorkScope): FulfillmentLocal | null {
  if (!workRecord(v) || v.schema_version !== 1 || !workSame(v.scope, scope)) return null;
  try { if (v.draft !== null) parseFulfillmentPayload(v.draft, scope, false); } catch { return null; }
  if (v.pending !== null && (!workRecord(v.pending) || !validFulfillmentCommand(v.pending.command, scope) || !["inputs", "preview", "execute"].includes(String(v.pending.stage)) || v.receipt !== null || v.completed !== null || (v.pending.stage === "execute" ? typeof v.pending.command.payload.confirmation_token !== "string" : v.pending.command.payload.confirmation_token != null))) return null;
  if (v.receipt !== null && (!validFulfillmentCommand(v.completed, scope) || !receipt(v.receipt, v.completed) || v.pending !== null)) return null;
  if (v.completed !== null && v.receipt === null) return null;
  return structuredClone(v) as FulfillmentLocal;
}
