import { parseWorkSources, workCommandsRoot, workRecord, workRoot, workSame, workUuid, type ProjectWorkApi, type WorkRead, type WorkRef, type WorkScope, type WorkSource } from "./project-work";

export const externalWaitOperation = "work.external_wait.record" as const;
export const externalWaitActions = ["create", "details", "initiate", "delivery", "commitment", "reply", "close", "reopen", "transfer_request", "transfer_accept", "transfer_cancel"] as const;
export type ExternalWaitAction = typeof externalWaitActions[number];
export type ExternalCalendarRef = WorkRef & { kind: "project_plan" | "build_resource"; calendar_key: string; calendar_version: string; resource_id?: string | null };
type Schedule = { original_timezone: string; next_check_at: string | null; calendar?: ExternalCalendarRef | null };
export type ExternalWaitRecord =
  | (Schedule & { action: "create"; title: string; target: string; request_content: string; closure_condition: string; blocking: boolean; milestone?: WorkRef | null; build?: WorkRef | null; replaces?: WorkRef | null })
  | (Schedule & { action: "details"; title: string; closure_condition: string; blocking: boolean })
  | { action: "initiate"; at: string | null; text: string; original_timezone: string }
  | { action: "delivery"; at: string | null; text: string; original_timezone: string; status: "effective" | "unverified" | "conflict" }
  | { action: "commitment"; promised_at: string | null; text: string; original_timezone: string }
  | { action: "reply"; at: string | null; text: string; original_timezone: string; status: "partial" | "received" | "conflict" | "unknown" }
  | { action: "close"; result: string }
  | { action: "reopen" }
  | { action: "transfer_request"; to_id: string }
  | { action: "transfer_accept" | "transfer_cancel"; request_id: string };
export type ExternalWaitPayload = { project_id: string; wait?: WorkRef | null; sources: WorkSource[]; reason: string; record: ExternalWaitRecord };
export type ExternalWaitCommand = { command_id: string; idempotency_key: string; operation: typeof externalWaitOperation; category_id: string; product_id: string; expected_revision: number; source_read_set: WorkRead[]; payload: ExternalWaitPayload };
export type ExternalWaitInputs = { payload: ExternalWaitPayload; required_source_read_set: WorkRead[]; review: Record<string, unknown> };
export type ExternalWaitPending = { stage: "inputs" | "execute"; command: ExternalWaitCommand; inputs?: ExternalWaitInputs };
export type ExternalWaitReceipt = { id: string; operation: typeof externalWaitOperation; subject_id: string; subject_revision: number; subject_type: "external_wait"; result: { wait_id: string } };
export type ExternalWaitEvent = { at: string | null; text: string; time_basis: "human_recorded" | "source_claim"; actor_id: string; requester_id: string; recorded_at: string; sources: WorkSource[]; original_timezone: string };
export type ExternalWaitSnapshot = WorkRef & Schedule & {
  wait_id: string; version_id: string; state: "open" | "closed"; responsible_id: string;
  title: string; target: string; request_content: string; closure_condition: string; blocking: boolean;
  milestone: WorkRef | null; build: WorkRef | null; replaces: WorkRef | null; created_at: string;
  initiation: ExternalWaitEvent | null;
  delivery: (ExternalWaitEvent & { status: "effective" | "unverified" | "conflict" }) | null;
  counterparty_commitment: { promised_at: string | null; text: string; actor_id: string; requester_id: string; recorded_at: string; sources: WorkSource[]; original_timezone: string } | null;
  reply: (ExternalWaitEvent & { status: "partial" | "received" | "conflict" | "unknown" }) | null;
  last_closure: { result: string; actor_id: string; requester_id: string; recorded_at: string; sources: WorkSource[] } | null;
  transfer: { request_id: string; from_id: string; to_id: string; actor_id: string; requested_at: string; sources: WorkSource[] } | null;
  history: { id: string; revision: number; action: ExternalWaitAction; state: "open" | "closed"; actor_id: string; created_at: string; receipt_id: string }[];
  clock: { status: "closed" | "delivery_unknown" | "delivery_conflict" | "calendar_unknown" | "calendar_unavailable" | "running"; response_started_at: string | null; working_minutes: number | null; calendar_label: string | null; check_due: boolean | null; claimed_commitment_due: boolean | null; escalation: "closed" | "claimed_commitment_due" | "check_due" | "none" | "unknown"; reasons: string[] };
};
export type ExternalWaitView = { project: { id: string; revision: number; name: string; owner_id: string; visibility: string }; product_revision: number; members: { id: string; name: string; can_write: boolean }[]; waits: ExternalWaitSnapshot[]; available_calendars: { ref: ExternalCalendarRef; label: string; calendar: Record<string, unknown> }[]; as_of: string };
export type ExternalWaitLocal = { schema_version: 1; scope: WorkScope; action: ExternalWaitAction; selectedId: string; draft: Record<string, string>; pending: ExternalWaitPending | null; receipt: ExternalWaitReceipt | null; completed: ExternalWaitCommand | null };
const text = (v: unknown): v is string => typeof v === "string" && !!v.trim();
const rev = (v: unknown): v is number => Number.isSafeInteger(v) && Number(v) > 0;
const ref = (v: unknown): v is WorkRef & Record<string, unknown> => workRecord(v) && workUuid(v.id) && rev(v.revision);
const nullableRef = (v: unknown) => v == null || ref(v);
const instant = (v: unknown): v is string => typeof v === "string" && /(?:Z|[+-]\d{2}:\d{2})$/.test(v) && Number.isFinite(Date.parse(v));
const nullableInstant = (v: unknown) => v === null || instant(v);
const zone = (v: unknown): v is string => { if (!text(v)) return false; try { new Intl.DateTimeFormat("en", { timeZone: v }); return true; } catch { return false; } };
const unique = (values: string[]) => new Set(values).size === values.length;
const exact = (v: Record<string, unknown>, keys: string[]) => Object.keys(v).every(key => keys.includes(key));
function sources(v: unknown): v is WorkSource[] { try { return parseWorkSources(JSON.stringify(v)).length > 0; } catch { return false; } }
function reads(v: unknown): v is WorkRead[] { return Array.isArray(v) && v.length > 0 && v.every(row => workRecord(row) && workUuid(row.artifact_id) && rev(row.expected_revision)) && unique(v.map(row => row.artifact_id)); }
export function isExternalCalendarRef(v: unknown): v is ExternalCalendarRef { return ref(v) && workRecord(v) && exact(v, ["kind", "id", "revision", "calendar_key", "calendar_version", "resource_id"]) && ["project_plan", "build_resource"].includes(String(v.kind)) && text(v.calendar_key) && text(v.calendar_version) && (v.resource_id == null || typeof v.resource_id === "string"); }
function record(v: unknown): v is ExternalWaitRecord {
  if (!workRecord(v) || !externalWaitActions.includes(v.action as ExternalWaitAction)) return false;
  const action = v.action;
  if (["create", "details"].includes(String(action))) {
    if (!zone(v.original_timezone) || !nullableInstant(v.next_check_at) || !(v.calendar == null || isExternalCalendarRef(v.calendar)) || !text(v.title) || v.title.length > 200 || !text(v.closure_condition) || typeof v.blocking !== "boolean") return false;
    return action === "create" ? exact(v, ["action", "title", "target", "request_content", "closure_condition", "blocking", "milestone", "build", "replaces", "next_check_at", "calendar", "original_timezone"]) && text(v.target) && text(v.request_content) && nullableRef(v.milestone) && nullableRef(v.build) && nullableRef(v.replaces) : exact(v, ["action", "title", "closure_condition", "blocking", "next_check_at", "calendar", "original_timezone"]);
  }
  if (["initiate", "delivery", "reply"].includes(String(action))) {
    if (!exact(v, ["action", "at", "text", "original_timezone", ...(action === "initiate" ? [] : ["status"])]) || !zone(v.original_timezone) || !nullableInstant(v.at) || !text(v.text)) return false;
    return action === "initiate" || (action === "delivery" ? ["effective", "unverified", "conflict"].includes(String(v.status)) && (v.status !== "effective" || instant(v.at)) : ["partial", "received", "conflict", "unknown"].includes(String(v.status)));
  }
  if (action === "commitment") return exact(v, ["action", "promised_at", "text", "original_timezone"]) && nullableInstant(v.promised_at) && text(v.text) && zone(v.original_timezone);
  if (action === "close") return exact(v, ["action", "result"]) && text(v.result);
  if (action === "reopen") return exact(v, ["action"]);
  if (action === "transfer_request") return exact(v, ["action", "to_id"]) && workUuid(v.to_id);
  return exact(v, ["action", "request_id"]) && workUuid(v.request_id);
}
function dtoValue(value: unknown, field = ""): unknown {
  if (Array.isArray(value)) return value.map(entry => dtoValue(entry));
  if (workRecord(value)) return Object.fromEntries(Object.entries(value).map(([key, entry]) => [key, dtoValue(entry, key)]));
  if (typeof value !== "string") return value;
  const trimmed = value.trim();
  return ["id", "project_id", "to_id", "request_id"].includes(field) && workUuid(trimmed) ? trimmed.toLowerCase() : trimmed;
}
export function parseExternalWaitPayload(v: unknown, scope: WorkScope): ExternalWaitPayload {
  v = dtoValue(v);
  if (!workRecord(v) || !exact(v, ["project_id", "wait", "sources", "reason", "record"]) || v.project_id !== scope.projectId || !record(v.record) || !sources(v.sources) || !text(v.reason) || (v.record.action === "create" ? v.wait != null : !ref(v.wait))) throw new Error("请核对当前项目、等待版本、原件来源及本次登记材料。");
  return structuredClone(v) as ExternalWaitPayload;
}
function normalizeInstant(v: string) { const fraction = (/\.(\d{1,6})(?:Z|[+-]\d{2}:\d{2})$/.exec(v)?.[1] ?? "").padEnd(6, "0"); return new Date(v).toISOString().slice(0, 19) + (Number(fraction) ? `.${fraction}` : "") + "Z"; }
export function externalWaitSemantic(payload: ExternalWaitPayload) {
  const result = dtoValue(payload) as ExternalWaitPayload; result.wait ??= null;
  const r = result.record as ExternalWaitRecord & Record<string, unknown>;
  if (r.action === "create") { r.milestone ??= null; r.build ??= null; r.replaces ??= null; }
  if (r.action === "create" || r.action === "details") { r.calendar ??= null; if (r.calendar) r.calendar.resource_id ??= null; }
  for (const key of ["at", "promised_at", "next_check_at"]) if (instant(r[key])) r[key] = normalizeInstant(r[key]);
  return result;
}
function sourceReads(payload: ExternalWaitPayload) { const found = new Map<string, number>(); for (const source of payload.sources) { if (found.has(source.id) && found.get(source.id) !== source.revision) throw new Error("同一原件不能使用两个版本。"); found.set(source.id, source.revision); } return [...found].sort(([a], [b]) => a.localeCompare(b)).map(([artifact_id, expected_revision]) => ({ artifact_id, expected_revision })); }
export function newExternalWaitCommand(scope: WorkScope, productRevision: number, payload: ExternalWaitPayload): ExternalWaitCommand { const parsed = parseExternalWaitPayload(payload, scope); if (!rev(productRevision)) throw new Error("尚未取得实际型号版本。"); return { command_id: crypto.randomUUID(), idempotency_key: crypto.randomUUID(), operation: externalWaitOperation, category_id: scope.categoryId, product_id: scope.productId, expected_revision: productRevision, source_read_set: sourceReads(parsed), payload: parsed }; }
export function validExternalWaitCommand(v: unknown, scope: WorkScope): v is ExternalWaitCommand {
  if (!workRecord(v) || !workUuid(v.command_id) || !workUuid(v.idempotency_key) || v.operation !== externalWaitOperation || v.category_id !== scope.categoryId || v.product_id !== scope.productId || !rev(v.expected_revision) || !reads(v.source_read_set)) return false;
  try { const payload = parseExternalWaitPayload(v.payload, scope), required = sourceReads(payload); return required.every(read => (v.source_read_set as WorkRead[]).some(actual => workSame(actual, read))); } catch { return false; }
}
function input(v: unknown, command: ExternalWaitCommand, scope: WorkScope): ExternalWaitInputs | null {
  if (!workRecord(v) || !reads(v.required_source_read_set) || !workRecord(v.review)) return null;
  try { const payload = parseExternalWaitPayload(v.payload, scope); if (!workSame(externalWaitSemantic(payload), externalWaitSemantic(command.payload)) || !command.source_read_set.every(read => (v.required_source_read_set as WorkRead[]).some(actual => workSame(actual, read)))) return null; return { payload, required_source_read_set: v.required_source_read_set, review: v.review }; } catch { return null; }
}
function receipt(v: unknown, command: ExternalWaitCommand): v is ExternalWaitReceipt { return workRecord(v) && workUuid(v.id) && v.operation === externalWaitOperation && v.subject_type === "external_wait" && workUuid(v.subject_id) && rev(v.subject_revision) && workRecord(v.result) && workUuid(v.result.wait_id) && (command.payload.wait == null || v.result.wait_id === command.payload.wait.id); }
export const externalWaitRoot = (scope: WorkScope) => `${workRoot(scope)}/project-work/external-waits`;
export async function runExternalWaitRequest(api: ProjectWorkApi, pending: ExternalWaitPending, scope: WorkScope, onStage: (v: ExternalWaitPending) => void, active: () => boolean) {
  if (!validExternalWaitCommand(pending.command, scope) || !["inputs", "execute"].includes(pending.stage)) throw new Error("原等待登记请求与当前项目或保存阶段不一致。");
  let step = pending; if (!active()) return null;
  if (step.stage === "inputs") {
    const raw = await api<unknown>(`${externalWaitRoot(scope)}/inputs`, step.command); if (!active()) return null;
    const value = input(raw, step.command, scope); if (!value) throw new Error("服务器未返回与原等待登记请求一致的实际材料。");
    step = { stage: "execute", command: { ...step.command, payload: value.payload, source_read_set: structuredClone(value.required_source_read_set) }, inputs: value }; onStage(step);
  }
  const value = await api<unknown>(workCommandsRoot(scope), step.command); if (!active()) return null;
  if (!receipt(value, step.command)) throw new Error("等待登记回执尚未核实，请保留原请求。");
  return { stage: "saved" as const, receipt: value, command: step.command };
}
function event(v: unknown): v is ExternalWaitEvent { return workRecord(v) && nullableInstant(v.at) && text(v.text) && ["human_recorded", "source_claim"].includes(String(v.time_basis)) && zone(v.original_timezone) && workUuid(v.actor_id) && workUuid(v.requester_id) && instant(v.recorded_at) && sources(v.sources); }
function snapshot(v: unknown): v is ExternalWaitSnapshot {
  if (!ref(v) || !workRecord(v) || v.id !== v.wait_id || !workUuid(v.version_id) || !["open", "closed"].includes(String(v.state)) || !workUuid(v.responsible_id) || !text(v.title) || !text(v.target) || !text(v.request_content) || !text(v.closure_condition) || typeof v.blocking !== "boolean" || !nullableRef(v.milestone) || !nullableRef(v.build) || !nullableRef(v.replaces) || !instant(v.created_at) || !nullableInstant(v.next_check_at) || !zone(v.original_timezone) || !(v.calendar == null || isExternalCalendarRef(v.calendar))) return false;
  if (!(v.initiation === null || event(v.initiation)) || !(v.delivery === null || (event(v.delivery) && ["effective", "unverified", "conflict"].includes(String((v.delivery as Record<string, unknown>).status)) && ((v.delivery as Record<string, unknown>).status !== "effective" || instant(v.delivery.at)))) || !(v.reply === null || (event(v.reply) && ["partial", "received", "conflict", "unknown"].includes(String((v.reply as Record<string, unknown>).status))))) return false;
  const claim = v.counterparty_commitment, closed = v.last_closure, transfer = v.transfer, clock = v.clock;
  if (claim !== null && (!workRecord(claim) || !nullableInstant(claim.promised_at) || !text(claim.text) || !zone(claim.original_timezone) || !workUuid(claim.actor_id) || !workUuid(claim.requester_id) || !instant(claim.recorded_at) || !sources(claim.sources))) return false;
  if (closed !== null && (!workRecord(closed) || !text(closed.result) || !workUuid(closed.actor_id) || !workUuid(closed.requester_id) || !instant(closed.recorded_at) || !sources(closed.sources))) return false;
  if (transfer !== null && (!workRecord(transfer) || !workUuid(transfer.request_id) || !workUuid(transfer.from_id) || !workUuid(transfer.to_id) || !workUuid(transfer.actor_id) || !instant(transfer.requested_at) || !sources(transfer.sources) || transfer.from_id !== v.responsible_id)) return false;
  if (!workRecord(clock) || !["closed", "delivery_unknown", "delivery_conflict", "calendar_unknown", "calendar_unavailable", "running"].includes(String(clock.status)) || !nullableInstant(clock.response_started_at) || !(clock.working_minutes === null || typeof clock.working_minutes === "number" && Number.isFinite(clock.working_minutes) && clock.working_minutes >= 0) || !(clock.calendar_label === null || text(clock.calendar_label)) || !(clock.check_due === null || typeof clock.check_due === "boolean") || !(clock.claimed_commitment_due === null || typeof clock.claimed_commitment_due === "boolean") || !["closed", "claimed_commitment_due", "check_due", "none", "unknown"].includes(String(clock.escalation)) || !Array.isArray(clock.reasons) || !clock.reasons.every(text)) return false;
  return Array.isArray(v.history) && v.history.every(row => ref(row) && workRecord(row) && externalWaitActions.includes(row.action as ExternalWaitAction) && ["open", "closed"].includes(String(row.state)) && workUuid(row.actor_id) && instant(row.created_at) && workUuid(row.receipt_id)) && unique(v.history.map(row => row.id));
}
export function parseExternalWaitView(v: unknown, scope: WorkScope): ExternalWaitView {
  if (!workRecord(v) || !ref(v.project) || !workRecord(v.project) || v.project.id !== scope.projectId || !text(v.project.name) || !workUuid(v.project.owner_id) || !text(v.project.visibility) || !rev(v.product_revision) || !instant(v.as_of) || !Array.isArray(v.members) || !v.members.every(row => workRecord(row) && workUuid(row.id) && text(row.name) && typeof row.can_write === "boolean") || !Array.isArray(v.waits) || !v.waits.every(snapshot) || !unique(v.waits.map(row => row.id)) || !Array.isArray(v.available_calendars) || !v.available_calendars.every(row => workRecord(row) && isExternalCalendarRef(row.ref) && text(row.label) && workRecord(row.calendar) && text(row.calendar.calendar_id) && text(row.calendar.version) && zone(row.calendar.timezone))) throw new Error("本项目外部等待资料未完整取得，不能显示为空列表。");
  return v as ExternalWaitView;
}
export async function readExternalWaits(api: ProjectWorkApi, scope: WorkScope) { return parseExternalWaitView(await api<unknown>(`${externalWaitRoot(scope)}?project_id=${encodeURIComponent(scope.projectId)}`), scope); }
export function availableExternalWaitActions(wait: ExternalWaitSnapshot, principalId: string, projectOwnerId: string): ExternalWaitAction[] {
  const controls = [wait.responsible_id, projectOwnerId].includes(principalId), result: ExternalWaitAction[] = [];
  if (wait.state === "closed") return controls ? ["reopen"] : [];
  if (controls) result.push("details", "initiate", "delivery", "commitment", "reply", "close", wait.transfer ? "transfer_cancel" : "transfer_request");
  if (wait.transfer?.to_id === principalId) result.push("transfer_accept");
  return result;
}
export const externalWaitStorageKey = (scope: WorkScope) => `pdos.external-waits.v1:${scope.principalId}:${scope.categoryId}:${scope.productId}:${scope.projectId}`;
export const blankExternalWaitLocal = (scope: WorkScope): ExternalWaitLocal => ({ schema_version: 1, scope: structuredClone(scope), action: "create", selectedId: "", draft: {}, pending: null, receipt: null, completed: null });
export function restoreExternalWaitLocal(v: unknown, scope: WorkScope): ExternalWaitLocal | null {
  if (!workRecord(v) || v.schema_version !== 1 || !workSame(v.scope, scope) || !externalWaitActions.includes(v.action as ExternalWaitAction) || typeof v.selectedId !== "string" || !workRecord(v.draft) || !Object.values(v.draft).every(value => typeof value === "string")) return null;
  if (v.pending !== null && (!workRecord(v.pending) || !validExternalWaitCommand(v.pending.command, scope) || !["inputs", "execute"].includes(String(v.pending.stage)) || v.receipt !== null || v.completed !== null)) return null;
  if (v.receipt !== null && (!validExternalWaitCommand(v.completed, scope) || !receipt(v.receipt, v.completed) || v.pending !== null)) return null;
  if (v.completed !== null && v.receipt === null) return null;
  return structuredClone(v) as ExternalWaitLocal;
}
