import type { PaiSessionApi, PaiSessionScope, PaiSessionItem, PaiRunHead } from "./pai-sessions";
export type PaiPresentation = { id: string | null; revision: number; title: string | null; pinned: boolean; archived: boolean; created_at: string | null };
export type PaiConversation = Omit<PaiSessionItem, "scope"> & { scope: { category_id: string | null; product_id: string | null; proposal_id: string | null; project_id: string | null }; presentation: PaiPresentation };
export type PaiConversationList = { version: "agent-conversation-list/v1"; principal_id: string; scope: PageScope; as_of: string; items: PaiConversation[]; next_cursor: string | null };
export type PresentationAction = "rename" | "pin" | "unpin" | "archive" | "restore";
export type PresentationBody = { expected_revision: number; request_key: string; action: PresentationAction; title?: string | null };
export type PresentationRequest = { sessionId: string; body: PresentationBody };
export type PresentationReceipt = { version: "agent-session-presentation/v1"; principal_id: string; scope: PageScope; session: { session_id: string; category_id: string | null; product_id: string | null; proposal_id: string | null; project_id: string | null }; presentation: PaiPresentation & { action: PresentationAction; request_key: string } };
type PageScope = { category_id: string | null; proposal_id: string | null; project_id?: string | null };
type PaiSessionListOptions = { q?: string; cursor?: string | null; pageSize?: number };
type PaiSessionMeta = Omit<PaiConversation, "latest_run" | "matched_run" | "presentation">;
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
function descending(rows: { created_at: string }[], ids: string[]): void {
  for (let index = 1; index < rows.length; index++) {
    const order = compareTime(rows[index - 1].created_at, rows[index].created_at);
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
const headKeys = ["run_id", "goal", "status", "error_code", "created_at", "continued_from_id", "reverted"];
const hiddenHeadKeys = [...headKeys, "recorded_at", "history_hidden", "hidden_message"];
function timeOf(row: PaiRunHead): string { return row.status === "hidden" ? row.recorded_at : row.created_at; }
function head(value: unknown, extra: string[] = []): value is PaiRunHead & Record<string, unknown> {
  if (object(value) && value.status === "hidden") return keys(value, [...hiddenHeadKeys, ...extra]) && uuid(value.run_id) && typeof value.goal === "string" && value.goal.length > 0
    && value.error_code === null && value.created_at === null && timestamp(value.recorded_at) && value.continued_from_id === null
    && value.reverted === null && value.history_hidden === true && typeof value.hidden_message === "string" && value.hidden_message.length > 0;
  return object(value) && keys(value, [...headKeys, ...extra]) && uuid(value.run_id) && typeof value.goal === "string" && value.goal.length > 0
    && typeof value.status === "string" && ["queued", "running", "waiting_input", "completed", "partial", "failed", "cancelled"].includes(value.status)
    && nullableString(value.error_code) && timestamp(value.created_at) && nullableUuid(value.continued_from_id)
    && !sameId(value.run_id, value.continued_from_id) && typeof value.reverted === "boolean";
}
function sessionMeta(value: unknown, expected: PageScope, extra: string[] = []): value is PaiSessionMeta & Record<string, unknown> {
  return object(value) && keys(value, ["session_id", "revision", "created_at", "scope", "run_count", ...extra])
    && uuid(value.session_id) && integer(value.revision) && timestamp(value.created_at) && integer(value.run_count)
    && object(value.scope) && keys(value.scope, ["category_id", "product_id", "proposal_id", "project_id"])
    && nullableUuid(value.scope.project_id) && sameId(value.scope.category_id, expected.category_id) && nullableUuid(value.scope.product_id) && nullableUuid(value.scope.proposal_id)
    && (expected.proposal_id === null || sameId(value.scope.proposal_id, expected.proposal_id))
    && (!expected.project_id || sameId(value.scope.project_id, expected.project_id))
    && (expected.category_id !== null || value.scope.product_id === null && value.scope.proposal_id === null && value.scope.project_id === null);
}
function pageEnd(value: Record<string, unknown>, page: ReturnType<typeof pageInput>, ids: string[]): void {
  if (ids.length > page.pageSize || new Set(ids.map(id => id.toLowerCase())).size !== ids.length || ids.some(id => sameId(id, page.cursor))) invalid();
  if (value.next_cursor !== null && (ids.length !== page.pageSize || !sameId(value.next_cursor, ids.at(-1)))) invalid();
}


function presentation(value: unknown, receipt = false): value is PaiPresentation & Record<string, unknown> {
  if (!object(value) || !keys(value, ["id", "revision", "title", "pinned", "archived", "created_at", ...(receipt ? ["action", "request_key"] : [])])
    || !Number.isSafeInteger(value.revision) || (value.revision as number) < 0 || typeof value.pinned !== "boolean" || typeof value.archived !== "boolean"
    || !(value.title === null || typeof value.title === "string" && value.title === value.title.trim() && [...value.title].length > 0 && [...value.title].length <= 160)) return false;
  return value.revision === 0 ? !receipt && value.id === null && value.title === null && value.pinned === false && value.archived === false && value.created_at === null
    : uuid(value.id) && timestamp(value.created_at);
}
const root = (scope: PageScope) => scope.category_id === null ? "v1/personal" : `v1/categories/${scope.category_id}`;
function boundScope(value: unknown, expected: PageScope, projectFiltered = true): boolean {
  return object(value) && keys(value, ["category_id", "proposal_id", ...(projectFiltered && expected.project_id ? ["project_id"] : [])])
    && sameId(value.category_id, expected.category_id) && sameId(value.proposal_id, expected.proposal_id)
    && (!projectFiltered || !expected.project_id || sameId(value.project_id, expected.project_id));
}
function withProposal(scope: PageScope, path: string): string {
  return `${root(scope)}/${path}${scope.proposal_id ? `?${new URLSearchParams({ proposal_id: scope.proposal_id })}` : ""}`;
}
export function validatePresentationBody(body: unknown): asserts body is PresentationBody {
  if (!object(body) || !["rename", "pin", "unpin", "archive", "restore"].includes(String(body.action))
    || !keys(body, ["expected_revision", "request_key", "action", ...(body.action === "rename" ? ["title"] : [])])
    || !Number.isSafeInteger(body.expected_revision) || (body.expected_revision as number) < 0 || !uuid(body.request_key)
    || body.action === "rename" && !(body.title === null || typeof body.title === "string" && body.title === body.title.trim() && [...body.title].length > 0 && [...body.title].length <= 160)) invalid();
}
/** Server owns title search, pin ordering and archive filtering before pagination. */
export async function readConversations(api: PaiSessionApi, scope: PaiSessionScope, options: PaiSessionListOptions & { view?: "active" | "archived" } = {}): Promise<PaiConversationList> {
  const expected = scopeInput(scope), { view = "active", ...paging } = options;
  if (view !== "active" && view !== "archived") invalid();
  const page = pageInput(paging, true), query = new URLSearchParams({ view, page_size: String(page.pageSize) });
  if (page.q) query.set("q", page.q); if (page.cursor) query.set("cursor", page.cursor); if (expected.proposal_id) query.set("proposal_id", expected.proposal_id);
  if (expected.project_id) query.set("project_id", expected.project_id);
  const value = await api<unknown>(`${root(expected)}/agent-conversations?${query}`);
  if (!object(value) || !keys(value, ["version", "principal_id", "scope", "as_of", "items", "next_cursor"]) || value.version !== "agent-conversation-list/v1"
    || !sameId(value.principal_id, scope.principalId) || !boundScope(value.scope, expected) || !timestamp(value.as_of) || !Array.isArray(value.items) || !nullableUuid(value.next_cursor)) invalid();
  const rows = value.items as unknown[], seenRuns = new Map<string, string>();
  for (const item of rows) {
    if (!sessionMeta(item, expected, ["latest_run", "matched_run", "presentation"]) || !head(item.latest_run) || !presentation(item.presentation) || item.presentation.archived !== (view === "archived")) invalid();
    const latest = item.latest_run, matched = item.matched_run;
    if (!page.q && matched !== null || page.q && matched === null && !(typeof item.presentation.title === "string")) invalid();
    if (matched !== null) {
      if (!head(matched, ["match_kind"]) || !["goal", "run_id", "session_id"].includes(String(matched.match_kind)) || compareTime(timeOf(latest), timeOf(matched)) < 0
        || sameId(latest.run_id, matched.run_id) && (latest.status === "hidden" ? hiddenHeadKeys : headKeys).some(key => latest[key] !== matched[key]) || item.run_count === 1 && !sameId(latest.run_id, matched.run_id)) invalid();
    }
    for (const run of [latest, ...(matched === null ? [] : [matched as typeof latest])]) {
      const previous = seenRuns.get(run.run_id.toLowerCase()); if (previous && !sameId(previous, item.session_id)) invalid(); seenRuns.set(run.run_id.toLowerCase(), item.session_id);
    }
  }
  const items = rows as PaiConversation[], ids = items.map(item => item.session_id); pageEnd(value, page, ids);
  for (let index = 1; index < items.length; index++) {
    const a = items[index - 1], b = items[index]; if (!a.presentation.pinned && b.presentation.pinned) invalid();
    if (a.presentation.pinned === b.presentation.pinned) descending([a, b], [a.session_id, b.session_id]);
  }
  return value as unknown as PaiConversationList;
}
function receipt(value: unknown, scope: PaiSessionScope, expected: PageScope, request: PresentationRequest): PresentationReceipt {
  if (!object(value) || !keys(value, ["version", "principal_id", "scope", "session", "presentation"]) || value.version !== "agent-session-presentation/v1"
    || !sameId(value.principal_id, scope.principalId) || !boundScope(value.scope, expected, false) || !object(value.session)
    || !keys(value.session, ["session_id", "category_id", "product_id", "proposal_id", "project_id"]) || !sameId(value.session.session_id, request.sessionId)
    || !sameId(value.session.category_id, expected.category_id) || !nullableUuid(value.session.product_id) || !nullableUuid(value.session.proposal_id) || !nullableUuid(value.session.project_id)
    || expected.proposal_id !== null && !sameId(value.session.proposal_id, expected.proposal_id)
    || expected.project_id && !sameId(value.session.project_id, expected.project_id)
    || expected.category_id === null && [value.session.product_id, value.session.proposal_id, value.session.project_id].some(id => id !== null)
    || !presentation(value.presentation, true) || value.presentation.revision !== request.body.expected_revision + 1
    || value.presentation.action !== request.body.action || !sameId(value.presentation.request_key, request.body.request_key)) invalid();
  const p = value.presentation, action = request.body.action;
  if (action === "rename" && p.title !== request.body.title || action === "pin" && p.pinned !== true || action === "unpin" && p.pinned !== false || action === "archive" && p.archived !== true || action === "restore" && p.archived !== false) invalid();
  return value as unknown as PresentationReceipt;
}
/** A response is the immutable receipt for this exact body, never a replacement Current. */
export async function writePresentation(api: PaiSessionApi, scope: PaiSessionScope, request: PresentationRequest): Promise<PresentationReceipt> {
  const expected = scopeInput(scope); if (!uuid(request.sessionId)) invalid(); validatePresentationBody(request.body);
  const value = await api<unknown>(withProposal(expected, `agent-sessions/${request.sessionId}/presentation`), request.body);
  try { return receipt(value, scope, expected, request); } catch { throw Object.assign(new Error("修改回执无法核对，请保留原请求并查询回执。"), { status: 503 }); }
}
export async function recoverPresentation(api: PaiSessionApi, scope: PaiSessionScope, request: PresentationRequest): Promise<PresentationReceipt> {
  const expected = scopeInput(scope); if (!uuid(request.sessionId)) invalid(); validatePresentationBody(request.body);
  return receipt(await api<unknown>(withProposal(expected, `agent-sessions/${request.sessionId}/presentation/requests/${request.body.request_key}`)), scope, expected, request);
}
