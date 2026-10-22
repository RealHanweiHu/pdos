import { parseWorkSources, workCommandsRoot, workRecord, workRoot, workSame, workUuid, type ProjectWorkApi, type WorkRead, type WorkRef, type WorkScope, type WorkSource } from "./project-work";

export const riskFollowupOperation = "work.risk.followup.record" as const;
export type RiskRef = { id: string; decision_id: string };
export type RiskAction = "close" | "reopen";
export type RiskHistory = WorkRef & { action: RiskAction; state: "open" | "closed"; summary: string; actor_id: string; created_at: string; receipt_id: string };
export type ProjectRisk = RiskRef & {
  title: string; note: string; responsible_id: string; due_date: string;
  source: { kind: "question" | "spec"; id: string };
  state: "open" | "closed" | "unknown"; current: WorkRef | null; summary: string | null;
  can_record: boolean; blocked: { code: string; message: string } | null; history: RiskHistory[];
  task: (WorkRef & { state: "proposed" | "assigned" | "accepted" | "in_progress" | "submitted" | "completed" }) | null;
};
export type ProjectRiskView = {
  project: { id: string; revision: number; name: string; owner_id: string; visibility: string };
  product_revision: number; members: { id: string; name: string; can_write: boolean }[]; risks: ProjectRisk[]; as_of: string;
};
export type RiskPayload = { project_id: string; risk: RiskRef; current: WorkRef | null; action: RiskAction; summary: string; sources: WorkSource[]; reason: string; confirmation_token?: string | null };
export type RiskCommand = { command_id: string; idempotency_key: string; operation: typeof riskFollowupOperation; category_id: string; product_id: string; expected_revision: number; source_read_set: WorkRead[]; payload: RiskPayload };
export type RiskInputs = { payload: RiskPayload; required_source_read_set: WorkRead[]; review: Record<string, unknown> };
export type RiskPending = { stage: "inputs" | "preview" | "execute"; command: RiskCommand; inputs?: RiskInputs };
export type RiskPrepared = { command: RiskCommand; review: Record<string, unknown>; expires_at: string };
export type RiskReceipt = { id: string; operation: typeof riskFollowupOperation; subject_type: "risk_followup"; subject_id: string; subject_revision: number; result: { id: string; revision: number; status: "open" | "closed"; risk_id: string; project_id: string } };
export type RiskDraft = { risk: RiskRef; current: WorkRef | null; action: RiskAction; summary: string; reason: string; sources: string };
export type RiskLocal = { schema_version: 1; scope: WorkScope; draft: RiskDraft | null; pending: RiskPending | null; receipt: RiskReceipt | null; completed: RiskCommand | null };

const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
const revision = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const ref = (v: unknown): v is WorkRef & Record<string, unknown> => workRecord(v) && workUuid(v.id) && revision(v.revision);
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).every(key => keys.includes(key));
const riskRef = (v: unknown): v is RiskRef => workRecord(v) && exact(v, ["id", "decision_id"]) && workUuid(v.id) && workUuid(v.decision_id);
const instant = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const date = (v: unknown): v is string => typeof v === "string" && /^\d{4}-\d{2}-\d{2}$/.test(v) && Number.isFinite(Date.parse(v)) && new Date(v).toISOString().slice(0, 10) === v;
const unique = (v: string[]) => new Set(v).size === v.length;
const reads = (v: unknown): v is WorkRead[] => Array.isArray(v) && v.length > 0 && v.every(row => workRecord(row) && workUuid(row.artifact_id) && revision(row.expected_revision)) && unique(v.map(row => row.artifact_id));
const actions = ["close", "reopen"] as const;
function history(v: unknown): v is RiskHistory { return ref(v) && workRecord(v) && actions.includes(v.action as RiskAction) && ["open", "closed"].includes(String(v.state)) && (v.action === "close" ? v.state === "closed" : v.state === "open") && text(v.summary) && workUuid(v.actor_id) && instant(v.created_at) && workUuid(v.receipt_id); }
function risk(v: unknown): v is ProjectRisk {
  if (!workRecord(v) || !workUuid(v.id) || !workUuid(v.decision_id) || !text(v.title) || typeof v.note !== "string" || !workUuid(v.responsible_id) || !date(v.due_date) || !workRecord(v.source) || !["question", "spec"].includes(String(v.source.kind)) || !workUuid(v.source.id) || !["open", "closed", "unknown"].includes(String(v.state)) || !(v.current === null || ref(v.current)) || !(v.summary === null || text(v.summary)) || typeof v.can_record !== "boolean" || !(v.blocked === null || workRecord(v.blocked) && text(v.blocked.code) && text(v.blocked.message)) || !Array.isArray(v.history) || !v.history.every(history) || !unique(v.history.map(row => row.id)) || !(v.task === null || ref(v.task) && workRecord(v.task) && ["proposed", "assigned", "accepted", "in_progress", "submitted", "completed"].includes(String(v.task.state)))) return false;
  if (v.state === "unknown") return true;
  return v.current === null ? v.state === "open" && v.summary === null && v.history.length === 0 : v.history.some(row => workSame({ id: row.id, revision: row.revision }, v.current) && row.state === v.state && row.summary === v.summary);
}
export function parseProjectRiskView(v: unknown, scope: WorkScope): ProjectRiskView {
  if (!workRecord(v) || !ref(v.project) || !workRecord(v.project) || v.project.id !== scope.projectId || !text(v.project.name) || !workUuid(v.project.owner_id) || !text(v.project.visibility) || !revision(v.product_revision) || !instant(v.as_of) || !Array.isArray(v.members) || !v.members.every(row => workRecord(row) && workUuid(row.id) && text(row.name) && typeof row.can_write === "boolean") || !Array.isArray(v.risks) || !v.risks.every(risk) || !unique(v.risks.map(row => row.id))) throw new Error("本项目风险跟进资料未完整取得，不能当作空列表。");
  return v as ProjectRiskView;
}
export const projectRiskRoot = (scope: WorkScope) => `${workRoot(scope)}/project-work/risks`;
export async function readProjectRisks(api: ProjectWorkApi, scope: WorkScope) { return parseProjectRiskView(await api<unknown>(`${projectRiskRoot(scope)}?project_id=${encodeURIComponent(scope.projectId)}`), scope); }

function dtoValue(v: unknown, key = ""): unknown {
  if (Array.isArray(v)) return v.map(value => dtoValue(value));
  if (workRecord(v)) return Object.fromEntries(Object.entries(v).map(([field, value]) => [field, dtoValue(value, field)]));
  if (typeof v !== "string") return v;
  const trimmed = v.trim(); return ["id", "decision_id", "project_id"].includes(key) && workUuid(trimmed) ? trimmed.toLowerCase() : trimmed;
}
export function parseRiskPayload(v: unknown, scope: WorkScope): RiskPayload {
  v = dtoValue(v);
  if (!workRecord(v) || !exact(v, ["project_id", "risk", "current", "action", "summary", "sources", "reason", "confirmation_token"]) || v.project_id !== scope.projectId || !riskRef(v.risk) || !(v.current == null || ref(v.current) && exact(v.current, ["id", "revision"])) || !actions.includes(v.action as RiskAction) || !text(v.summary) || !text(v.reason) || !(v.confirmation_token == null || typeof v.confirmation_token === "string" && v.confirmation_token.length >= 20)) throw new Error("须固定本项目原 G0 风险及当前跟进版本，并填写跟进结果、来源和理由。");
  parseWorkSources(JSON.stringify(v.sources));
  return { ...structuredClone(v), current: v.current ?? null } as RiskPayload;
}
export function riskSemantic(payload: RiskPayload) { const result = dtoValue(payload) as RiskPayload; result.current ??= null; delete result.confirmation_token; return result; }
export function canRecordRisk(row: ProjectRisk, scope: WorkScope) { return row.can_record && row.responsible_id === scope.principalId && row.blocked === null && row.state !== "unknown"; }
export function riskDraft(row: ProjectRisk, scope: WorkScope): RiskDraft {
  if (!canRecordRisk(row, scope)) throw new Error("仅原 G0 具名跟进人可登记当前内部风险跟进结果。");
  return { risk: { id: row.id, decision_id: row.decision_id }, current: row.current && { ...row.current }, action: row.state === "closed" ? "reopen" : "close", summary: "", reason: "", sources: "[]" };
}
export function riskDraftCurrent(value: Pick<RiskPayload, "risk" | "current" | "action">, row: ProjectRisk, scope: WorkScope) { return canRecordRisk(row, scope) && workSame(value.risk, { id: row.id, decision_id: row.decision_id }) && workSame(value.current, row.current) && (value.action === "close" ? row.state === "open" : row.state === "closed"); }
function sourceReads(payload: RiskPayload) {
  const found = new Map<string, number>(); for (const source of payload.sources) { if (found.has(source.id) && found.get(source.id) !== source.revision) throw new Error("同一原件不能引用两个版本。"); found.set(source.id, source.revision); }
  return [...found].sort(([a], [b]) => a.localeCompare(b)).map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision }));
}
export function newRiskCommand(scope: WorkScope, productRevision: number, draft: RiskDraft, row: ProjectRisk): RiskCommand {
  const payload = parseRiskPayload({ ...draft, project_id: scope.projectId, sources: parseWorkSources(draft.sources) }, scope);
  if (!revision(productRevision) || !riskDraftCurrent(payload, row, scope)) throw new Error("风险跟进状态或固定材料已变化，请重新选择当前风险。");
  return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: riskFollowupOperation, category_id: scope.categoryId, product_id: scope.productId, expected_revision: productRevision, source_read_set: sourceReads(payload), payload };
}
export function validRiskCommand(v: unknown, scope: WorkScope): v is RiskCommand {
  if (!workRecord(v) || !workUuid(v.command_id) || !workUuid(v.idempotency_key) || v.operation !== riskFollowupOperation || v.category_id !== scope.categoryId || v.product_id !== scope.productId || !revision(v.expected_revision) || !reads(v.source_read_set)) return false;
  try { return sourceReads(parseRiskPayload(v.payload, scope)).every(read => (v.source_read_set as WorkRead[]).some(actual => workSame(actual, read))); } catch { return false; }
}
function inputs(v: unknown, c: RiskCommand, scope: WorkScope): RiskInputs | null {
  if (!workRecord(v) || !reads(v.required_source_read_set) || !workRecord(v.review)) return null;
  try { const payload = parseRiskPayload(v.payload, scope); if (payload.confirmation_token != null || !workSame(riskSemantic(payload), riskSemantic(c.payload)) || !c.source_read_set.every(read => (v.required_source_read_set as WorkRead[]).some(actual => workSame(actual, read)))) return null; return { payload, required_source_read_set: v.required_source_read_set, review: v.review }; } catch { return null; }
}
export function riskPrepared(v: unknown, c: RiskCommand, scope: WorkScope, now = Date.now()): RiskPrepared | null {
  if (!workRecord(v) || !validRiskCommand(v.command, scope) || !workRecord(v.review) || !instant(v.expires_at) || Date.parse(v.expires_at) <= now || typeof v.command.payload.confirmation_token !== "string" || (v.confirmation_token != null && v.confirmation_token !== v.command.payload.confirmation_token)) return null;
  const before = { ...c, payload: riskSemantic(c.payload) }, after = { ...v.command, payload: riskSemantic(v.command.payload) };
  return workSame(before, after) ? { command: v.command, review: v.review, expires_at: v.expires_at } : null;
}
export const riskPreviewCurrent = (value: RiskPrepared, now = Date.now()) => Date.parse(value.expires_at) > now;
function receipt(v: unknown, c: RiskCommand): v is RiskReceipt { return workRecord(v) && workUuid(v.id) && v.operation === riskFollowupOperation && v.subject_type === "risk_followup" && workUuid(v.subject_id) && revision(v.subject_revision) && workRecord(v.result) && v.result.id === v.subject_id && v.result.revision === v.subject_revision && v.result.risk_id === c.payload.risk.id && v.result.project_id === c.payload.project_id && v.result.status === (c.payload.action === "close" ? "closed" : "open"); }
export async function runRiskRequest(api: ProjectWorkApi, pending: RiskPending, scope: WorkScope, onStage: (v: RiskPending) => void, active: () => boolean) {
  if (!validRiskCommand(pending.command, scope) || !["inputs", "preview", "execute"].includes(pending.stage) || (pending.stage === "execute" ? typeof pending.command.payload.confirmation_token !== "string" : pending.command.payload.confirmation_token != null)) throw new Error("原风险跟进请求与当前范围或确认阶段不一致。");
  let step = pending; if (!active()) return null;
  if (step.stage === "inputs") { const raw = await api<unknown>(`${projectRiskRoot(scope)}/inputs`, step.command); if (!active()) return null; const value = inputs(raw, step.command, scope); if (!value) throw new Error("服务器未返回与原风险及跟进内容一致的实际材料。"); step = { stage: "preview", command: { ...step.command, payload: value.payload, source_read_set: structuredClone(value.required_source_read_set) }, inputs: value }; onStage(step); }
  if (step.stage === "preview") { const raw = await api<unknown>(`${workCommandsRoot(scope)}/preview`, step.command); if (!active()) return null; const prepared = riskPrepared(raw, step.command, scope); if (!prepared) throw new Error("尚未取得固定风险、内容及版本一致的共同确认。"); return { stage: "preview" as const, prepared }; }
  const value = await api<unknown>(workCommandsRoot(scope), step.command); if (!active()) return null; if (!receipt(value, step.command)) throw new Error("风险跟进回执尚未核实，请保留原请求。"); return { stage: "saved" as const, receipt: value, command: step.command };
}
export const riskStorageKey = (scope: WorkScope) => `pdos.project-risks.v1:${scope.principalId}:${scope.categoryId}:${scope.productId}:${scope.projectId}`;
export const blankRiskLocal = (scope: WorkScope): RiskLocal => ({ schema_version: 1, scope: structuredClone(scope), draft: null, pending: null, receipt: null, completed: null });
export function restoreRiskLocal(v: unknown, scope: WorkScope): RiskLocal | null {
  if (!workRecord(v) || v.schema_version !== 1 || !workSame(v.scope, scope)) return null;
  if (v.draft !== null && (!workRecord(v.draft) || !riskRef(v.draft.risk) || !(v.draft.current === null || ref(v.draft.current)) || !actions.includes(v.draft.action as RiskAction) || typeof v.draft.summary !== "string" || typeof v.draft.reason !== "string" || typeof v.draft.sources !== "string")) return null;
  if (v.pending !== null && (!workRecord(v.pending) || !validRiskCommand(v.pending.command, scope) || !["inputs", "preview", "execute"].includes(String(v.pending.stage)) || v.receipt !== null || v.completed !== null || (v.pending.stage === "execute" ? typeof v.pending.command.payload.confirmation_token !== "string" : v.pending.command.payload.confirmation_token != null))) return null;
  if (v.receipt !== null && (!validRiskCommand(v.completed, scope) || !receipt(v.receipt, v.completed) || v.pending !== null)) return null;
  if (v.completed !== null && v.receipt === null) return null;
  return structuredClone(v) as RiskLocal;
}
