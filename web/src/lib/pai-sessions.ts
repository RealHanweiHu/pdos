export type PaiSessionApi = <T>(path: string, body?: unknown) => Promise<T>;
export type PaiSessionScope = { principalId: string; categoryId: string | null; proposalId?: string | null; projectId?: string | null };
export type PaiRunStatus = "queued" | "running" | "waiting_input" | "completed" | "partial" | "failed" | "cancelled" | "hidden";
type ReadableHead = { run_id: string; goal: string; status: Exclude<PaiRunStatus, "hidden">; error_code: string | null; created_at: string; continued_from_id: string | null; reverted: boolean; history_hidden?: false };
export type PaiHiddenHead = { run_id: string; goal: string; status: "hidden"; error_code: null; created_at: null; recorded_at: string; continued_from_id: null; reverted: null; history_hidden: true; hidden_message: string };
export type PaiRunHead = ReadableHead | PaiHiddenHead;
export type PaiHiddenRun = Omit<PaiHiddenHead, "continued_from_id"> & {
  session_id: string; hidden_reason: "source_unavailable"; result: null; versions: Record<string, never>;
  product_id: string | null; project_id: string | null; proposal_id: null; session_proposal_id: string | null;
  conversation: { previous_run_id: null; next_run_id: null; links_unavailable: true };
  reconciliation: null; process: null; reverted_at: null; reverted_by: null; revert_receipt_id: null; cancel_epoch: null;
};
export type PaiSessionMeta = {
  session_id: string; revision: number; created_at: string;
  scope: { category_id: string | null; product_id: string | null; proposal_id: string | null; project_id?: string | null };
  run_count: number;
};
export type PaiSessionItem = PaiSessionMeta & { latest_run: PaiRunHead; matched_run: (PaiRunHead & { match_kind: "goal" | "run_id" | "session_id" }) | null };
export type PaiSessionRun = PaiRunHead & { conversation: { previous_run_id: string | null; next_run_id: string | null; links_unavailable?: true } };
type PageScope = { category_id: string | null; proposal_id: string | null; project_id?: string | null };
export type PaiSessionList = { version: "agent-session-list/v1"; principal_id: string; scope: PageScope; as_of: string; items: PaiSessionItem[]; next_cursor: string | null };
export type PaiSessionRuns = { version: "agent-session-runs/v1"; principal_id: string; scope: PageScope; as_of: string; session: PaiSessionMeta; items: PaiSessionRun[]; next_cursor: string | null };
export type PaiSessionListOptions = { q?: string; cursor?: string | null; pageSize?: number };
export type PaiSessionRunsOptions = Omit<PaiSessionListOptions, "q">;

const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const nullableUuid = (value: unknown) => value === null || uuid(value);
const integer = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const nullableString = (value: unknown) => value === null || typeof value === "string";
const sameId = (a: unknown, b: unknown) => typeof a === "string" && typeof b === "string" ? a.toLowerCase() === b.toLowerCase() : a === b;
const keys = (value: Record<string, unknown>, expected: string[]) => Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key));
function invalid(): never { throw new Error("会话列表、身份或固定范围无法核对，请在当前范围重新读取。"); }

function timestamp(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const parts = /^(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})(?:\.\d+)?(?:Z|([+-])(\d{2}):(\d{2}))$/.exec(value);
  if (!parts) return false;
  const [, year, month, day, hour, minute, second, , offsetHour, offsetMinute] = parts;
  const y = Number(year), m = Number(month), d = Number(day);
  const days = [31, y % 4 === 0 && (y % 100 !== 0 || y % 400 === 0) ? 29 : 28, 31, 30, 31, 30, 31, 31, 30, 31, 30, 31];
  return y > 0 && m >= 1 && m <= 12 && d >= 1 && d <= days[m - 1] && Number(hour) < 24 && Number(minute) < 60 && Number(second) < 60
    && (!offsetHour || Number(offsetHour) < 24 && Number(offsetMinute) < 60) && Number.isFinite(Date.parse(value));
}
// Compare stored subsecond precision directly; Date alone would collapse microseconds.
function compareTime(a: string, b: string): number {
  const whole = Date.parse(a.replace(/\.\d+/, "")) - Date.parse(b.replace(/\.\d+/, ""));
  if (whole) return Math.sign(whole);
  const fraction = (value: string) => /\.(\d+)/.exec(value)?.[1] ?? "";
  const left = fraction(a), right = fraction(b), length = Math.max(left.length, right.length);
  const l = left.padEnd(length, "0"), r = right.padEnd(length, "0");
  return l === r ? 0 : l < r ? -1 : 1;
}
function timeOf(row: { created_at: string | null; recorded_at?: string }): string { return row.created_at ?? row.recorded_at ?? invalid(); }
function descending(rows: { created_at: string | null; recorded_at?: string }[], ids: string[]): void {
  for (let index = 1; index < rows.length; index++) {
    const order = compareTime(timeOf(rows[index - 1]), timeOf(rows[index]));
    if (order < 0 || order === 0 && ids[index - 1].toLowerCase() <= ids[index].toLowerCase()) invalid();
  }
}
function scopeInput(scope: PaiSessionScope): PageScope {
  if (!object(scope) || !uuid(scope.principalId) || !(scope.categoryId === null || scope.categoryId === "" || uuid(scope.categoryId))
    || !(scope.proposalId === undefined || scope.proposalId === null || uuid(scope.proposalId))
    || !(scope.projectId === undefined || scope.projectId === null || uuid(scope.projectId))) invalid();
  const category_id = scope.categoryId || null, proposal_id = scope.proposalId ?? null;
  if (category_id === null && (proposal_id !== null || scope.projectId != null)) invalid();
  return { category_id, proposal_id, ...(scope.projectId ? { project_id: scope.projectId } : {}) };
}
function pageInput(options: PaiSessionListOptions, searching: boolean) {
  if (!object(options) || Object.keys(options).some(key => !["cursor", "pageSize", ...(searching ? ["q"] : [])].includes(key))) invalid();
  const pageSize = options.pageSize === undefined ? 20 : options.pageSize, cursor = options.cursor ?? null;
  if (!integer(pageSize) || pageSize > 50 || !nullableUuid(cursor) || !(options.q === undefined || typeof options.q === "string" && [...options.q].length <= 160)) invalid();
  return { pageSize, cursor, q: options.q?.trim() ?? "" };
}
function path(scope: PageScope, suffix: string, page: ReturnType<typeof pageInput>): string {
  const root = scope.category_id === null ? "v1/personal/agent-sessions" : `v1/categories/${scope.category_id}/agent-sessions`;
  const query = new URLSearchParams({ page_size: String(page.pageSize) });
  if (page.cursor) query.set("cursor", page.cursor);
  if (page.q) query.set("q", page.q);
  if (scope.proposal_id) query.set("proposal_id", scope.proposal_id);
  if (scope.project_id) query.set("project_id", scope.project_id);
  return `${root}${suffix}?${query}`;
}
function envelope(value: unknown, scope: PaiSessionScope, expected: PageScope, version: string, detail: boolean): Record<string, unknown> {
  if (!object(value) || !keys(value, ["version", "principal_id", "scope", "as_of", "items", "next_cursor", ...(detail ? ["session"] : [])]) || value.version !== version
    || !sameId(value.principal_id, scope.principalId) || !object(value.scope) || !keys(value.scope, ["category_id", "proposal_id", ...(expected.project_id ? ["project_id"] : [])])
    || !sameId(value.scope.category_id, expected.category_id) || !sameId(value.scope.proposal_id, expected.proposal_id)
    || expected.project_id && !sameId(value.scope.project_id, expected.project_id)
    || !timestamp(value.as_of) || !Array.isArray(value.items) || !nullableUuid(value.next_cursor)) invalid();
  return value;
}
const headKeys = ["run_id", "goal", "status", "error_code", "created_at", "continued_from_id", "reverted"];
const hiddenHeadKeys = [...headKeys, "recorded_at", "history_hidden", "hidden_message"];
function head(value: unknown, extra: string[] = []): value is PaiRunHead & Record<string, unknown> {
  if (object(value) && value.status === "hidden") return keys(value, [...hiddenHeadKeys, ...extra]) && uuid(value.run_id) && typeof value.goal === "string" && value.goal.length > 0
    && value.error_code === null && value.created_at === null && timestamp(value.recorded_at) && value.continued_from_id === null
    && value.reverted === null && value.history_hidden === true && typeof value.hidden_message === "string" && value.hidden_message.length > 0;
  return object(value) && keys(value, [...headKeys, ...extra]) && uuid(value.run_id) && typeof value.goal === "string" && value.goal.length > 0
    && typeof value.status === "string" && ["queued", "running", "waiting_input", "completed", "partial", "failed", "cancelled"].includes(value.status)
    && nullableString(value.error_code) && timestamp(value.created_at) && nullableUuid(value.continued_from_id)
    && !sameId(value.run_id, value.continued_from_id) && typeof value.reverted === "boolean";
}
/** A goal-only HTTP placeholder grants no operational Run or lineage authority. */
export function assertHiddenRun(value: unknown): asserts value is PaiHiddenRun {
  const fields = [...hiddenHeadKeys.filter(key => key !== "continued_from_id"), "session_id", "hidden_reason", "result", "versions", "product_id", "project_id", "proposal_id", "session_proposal_id", "conversation", "reconciliation", "process", "reverted_at", "reverted_by", "revert_receipt_id", "cancel_epoch"];
  if (!object(value) || !keys(value, fields) || !uuid(value.run_id) || !uuid(value.session_id) || typeof value.goal !== "string" || !value.goal.length
    || value.status !== "hidden" || value.history_hidden !== true || value.hidden_reason !== "source_unavailable"
    || typeof value.hidden_message !== "string" || !value.hidden_message.length || value.result !== null || value.created_at !== null || !timestamp(value.recorded_at)
    || !object(value.versions) || Object.keys(value.versions).length || !nullableUuid(value.product_id) || !nullableUuid(value.project_id)
    || value.proposal_id !== null || !nullableUuid(value.session_proposal_id) || !object(value.conversation) || !keys(value.conversation, ["previous_run_id", "next_run_id", "links_unavailable"])
    || value.conversation.previous_run_id !== null || value.conversation.next_run_id !== null || value.conversation.links_unavailable !== true
    || ["error_code", "reconciliation", "process", "reverted", "reverted_at", "reverted_by", "revert_receipt_id", "cancel_epoch"].some(key => value[key] !== null)) invalid();
}
function sessionMeta(value: unknown, expected: PageScope, extra: string[] = []): value is PaiSessionMeta & Record<string, unknown> {
  return object(value) && keys(value, ["session_id", "revision", "created_at", "scope", "run_count", ...extra])
    && uuid(value.session_id) && integer(value.revision) && timestamp(value.created_at) && integer(value.run_count)
    && object(value.scope) && keys(value.scope, ["category_id", "product_id", "proposal_id", ...(expected.project_id ? ["project_id"] : [])])
    && sameId(value.scope.category_id, expected.category_id) && nullableUuid(value.scope.product_id) && nullableUuid(value.scope.proposal_id)
    && (expected.proposal_id === null || sameId(value.scope.proposal_id, expected.proposal_id))
    && (!expected.project_id || sameId(value.scope.project_id, expected.project_id))
    && (expected.category_id !== null || value.scope.product_id === null && value.scope.proposal_id === null);
}
function pageEnd(value: Record<string, unknown>, page: ReturnType<typeof pageInput>, ids: string[]): void {
  if (ids.length > page.pageSize || new Set(ids.map(id => id.toLowerCase())).size !== ids.length || ids.some(id => sameId(id, page.cursor))) invalid();
  if (value.next_cursor !== null && (ids.length !== page.pageSize || !sameId(value.next_cursor, ids.at(-1)))) invalid();
}

/** Read one real Session page. Latest Run metadata grants no continuation authority. */
export async function readSessionList(api: PaiSessionApi, scope: PaiSessionScope, options: PaiSessionListOptions = {}): Promise<PaiSessionList> {
  const expected = scopeInput(scope), page = pageInput(options, true);
  const value = envelope(await api<unknown>(path(expected, "", page)), scope, expected, "agent-session-list/v1", false);
  const rows = value.items as unknown[], seenRuns = new Map<string, string>();
  for (const item of rows) {
    if (!sessionMeta(item, expected, ["latest_run", "matched_run"]) || !head(item.latest_run)) invalid();
    const latest = item.latest_run, matched = item.matched_run;
    if (!page.q && matched !== null || page.q && !head(matched, ["match_kind"])) invalid();
    if (matched !== null) {
      if (!head(matched, ["match_kind"]) || !["goal", "run_id", "session_id"].includes(String(matched.match_kind))) invalid();
      // SQL collation and accepted UUID search spellings belong to the server.
      if (compareTime(timeOf(latest), timeOf(matched)) < 0) invalid();
      if (sameId(latest.run_id, matched.run_id) && (latest.status === "hidden" ? hiddenHeadKeys : headKeys).some(key => latest[key] !== matched[key])) invalid();
      if (item.run_count === 1 && !sameId(latest.run_id, matched.run_id)) invalid();
    }
    for (const run of [latest, ...(matched === null ? [] : [matched as PaiRunHead])]) {
      const previous = seenRuns.get(run.run_id.toLowerCase());
      if (previous && !sameId(previous, item.session_id)) invalid();
      seenRuns.set(run.run_id.toLowerCase(), item.session_id);
    }
  }
  const items = rows as PaiSessionItem[], ids = items.map(item => item.session_id);
  pageEnd(value, page, ids); descending(items, ids);
  return value as unknown as PaiSessionList;
}

/** Read only the selected Session's Run heads; never load results or start inference. */
export async function readSessionRuns(api: PaiSessionApi, scope: PaiSessionScope, sessionId: string, options: PaiSessionRunsOptions = {}): Promise<PaiSessionRuns> {
  const expected = scopeInput(scope), page = pageInput(options, false);
  if (!uuid(sessionId)) invalid();
  const value = envelope(await api<unknown>(path(expected, `/${sessionId}/runs`, page)), scope, expected, "agent-session-runs/v1", true);
  if (!sessionMeta(value.session, expected) || !sameId(value.session.session_id, sessionId)) invalid();
  const rows = value.items as unknown[];
  for (const item of rows) {
    if (!head(item, ["conversation"]) || !object(item.conversation) || !keys(item.conversation, ["previous_run_id", "next_run_id", ...(item.status === "hidden" ? ["links_unavailable"] : [])])
      || item.status === "hidden" && (item.conversation.links_unavailable !== true || item.conversation.previous_run_id !== null || item.conversation.next_run_id !== null)
      || !nullableUuid(item.conversation.previous_run_id) || !nullableUuid(item.conversation.next_run_id)
      || !sameId(item.conversation.previous_run_id, item.continued_from_id)
      || sameId(item.conversation.next_run_id, item.run_id)
      || item.conversation.next_run_id !== null && sameId(item.conversation.next_run_id, item.continued_from_id)) invalid();
  }
  const items = rows as PaiSessionRun[], ids = items.map(item => item.run_id);
  if (value.session.run_count < items.length || items.length === 0 && page.cursor === null
    || value.next_cursor !== null && value.session.run_count <= items.length) invalid();
  pageEnd(value, page, ids); descending(items, ids);
  const byId = new Map(items.map(item => [item.run_id.toLowerCase(), item]));
  for (const item of items) {
    const previous = item.conversation.previous_run_id && byId.get(item.conversation.previous_run_id.toLowerCase());
    const next = item.conversation.next_run_id && byId.get(item.conversation.next_run_id.toLowerCase());
    if (previous && !previous.conversation.links_unavailable && !sameId(previous.conversation.next_run_id, item.run_id) || next && !next.conversation.links_unavailable && !sameId(next.continued_from_id, item.run_id)) invalid();
  }
  return value as unknown as PaiSessionRuns;
}
