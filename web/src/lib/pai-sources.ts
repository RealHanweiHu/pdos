export type PaiSourcesApi = <T>(path: string, body?: unknown) => Promise<T>;
export type PaiSourcesScope = { principalId: string; categoryId: string; productId: string | null; proposalId: string | null };
export type PaiSourceReference = { artifact_id: string; expected_revision: number };
export type PaiInputSource = {
  artifact_id: string; artifact_revision: number; title: string; product_id: string | null; status: "active" | "withdrawn";
  original: null | { id: string; revision: number; filename: string; parse_status: string; parse_code: string | null; scan_status: string };
  availability: { available: boolean; code: string | null };
};
export type SourceHead = PaiInputSource;
type SourceScope = { category_id: string; product_id: string | null; proposal_id: string | null };
export type PaiInputSources = { version: "agent-input-sources/v1"; principal_id: string; scope: SourceScope; as_of: string; items: PaiInputSource[]; next_cursor: string | null };
export type PaiRunSourceBindings = {
  version: "agent-run-source-bindings/v1"; principal_id: string; scope: SourceScope; as_of: string; run_id: string; session_id: string;
  items: { artifact_id: string; expected_revision: number; product_id: string | null; current: PaiInputSource | null }[];
};
export type PaiSourcePage = { cursor?: string | null; pageSize?: number };

const object = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
const nullableUuid = (value: unknown) => value === null || uuid(value);
const revision = (value: unknown): value is number => typeof value === "number" && Number.isSafeInteger(value) && value > 0;
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const nullableText = (value: unknown) => value === null || typeof value === "string";
const sameId = (a: unknown, b: unknown) => typeof a === "string" && typeof b === "string" ? a.toLowerCase() === b.toLowerCase() : a === b;
const keys = (value: Record<string, unknown>, expected: string[]) => Object.keys(value).length === expected.length && expected.every(key => Object.hasOwn(value, key));
const timestamp = (value: unknown): value is string => typeof value === "string" && /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:Z|[+-]\d{2}:\d{2})$/.test(value) && Number.isFinite(Date.parse(value));
function invalid(): never { throw new Error("来源、固定版本或当前身份范围无法核对，请重新读取并选择。"); }

function expectedScope(scope: PaiSourcesScope): SourceScope {
  if (!object(scope) || !uuid(scope.principalId) || !uuid(scope.categoryId) || !nullableUuid(scope.productId) || !nullableUuid(scope.proposalId)) invalid();
  return { category_id: scope.categoryId, product_id: scope.productId, proposal_id: scope.proposalId };
}
function source(value: unknown): value is PaiInputSource {
  if (!object(value) || !keys(value, ["artifact_id", "artifact_revision", "title", "product_id", "status", "original", "availability"])
    || !uuid(value.artifact_id) || !revision(value.artifact_revision) || !text(value.title) || !nullableUuid(value.product_id)
    || !["active", "withdrawn"].includes(String(value.status)) || !object(value.availability) || !keys(value.availability, ["available", "code"])
    || typeof value.availability.available !== "boolean") return false;
  if (value.availability.available ? value.availability.code !== null || value.status !== "active" : !text(value.availability.code)) return false;
  const original = value.original;
  return original === null || object(original) && keys(original, ["id", "revision", "filename", "parse_status", "parse_code", "scan_status"])
    && uuid(original.id) && revision(original.revision) && text(original.filename) && text(original.parse_status)
    && nullableText(original.parse_code) && text(original.scan_status);
}
function envelope(value: unknown, scope: PaiSourcesScope, expected: SourceScope, version: string, extra: string[]): Record<string, unknown> {
  if (!object(value) || !keys(value, ["version", "principal_id", "scope", "as_of", "items", ...extra]) || value.version !== version
    || !sameId(value.principal_id, scope.principalId) || !object(value.scope) || !keys(value.scope, ["category_id", "product_id", "proposal_id"])
    || !sameId(value.scope.category_id, expected.category_id) || !sameId(value.scope.product_id, expected.product_id)
    || !sameId(value.scope.proposal_id, expected.proposal_id) || !timestamp(value.as_of) || !Array.isArray(value.items)) invalid();
  return value;
}
function pageInput(options: PaiSourcePage) {
  if (!object(options) || Object.keys(options).some(key => !["cursor", "pageSize"].includes(key))) invalid();
  const pageSize = options.pageSize === undefined ? 20 : options.pageSize, cursor = options.cursor ?? null;
  if (!revision(pageSize) || pageSize > 50 || !nullableUuid(cursor)) invalid();
  return { pageSize, cursor };
}
function reference(value: unknown): value is PaiSourceReference {
  return object(value) && keys(value, ["artifact_id", "expected_revision"]) && uuid(value.artifact_id) && revision(value.expected_revision);
}
function references(value: unknown): value is PaiSourceReference[] {
  return Array.isArray(value) && value.every(reference) && new Set(value.map(item => item.artifact_id.toLowerCase())).size === value.length;
}

/** Registered Artifact heads only; a saved upload without an Artifact is not an input. */
export async function readInputSources(api: PaiSourcesApi, scope: PaiSourcesScope, options: PaiSourcePage = {}): Promise<PaiInputSources> {
  const expected = expectedScope(scope), page = pageInput(options), query = new URLSearchParams({ page_size: String(page.pageSize) });
  if (expected.product_id) query.set("product_id", expected.product_id);
  if (expected.proposal_id) query.set("proposal_id", expected.proposal_id);
  if (page.cursor) query.set("cursor", page.cursor);
  const value = envelope(await api<unknown>(`v1/categories/${scope.categoryId}/agent-input-sources?${query}`), scope, expected, "agent-input-sources/v1", ["next_cursor"]);
  if (!nullableUuid(value.next_cursor)) invalid();
  const rows = value.items as unknown[];
  if (rows.length > page.pageSize || !rows.every(source)) invalid();
  const items = rows as PaiInputSource[], ids = items.map(item => item.artifact_id.toLowerCase());
  if (new Set(ids).size !== ids.length || items.some(item => sameId(item.artifact_id, page.cursor)
    || item.product_id !== null && !sameId(item.product_id, expected.product_id))) invalid();
  if (value.next_cursor !== null && (items.length !== page.pageSize || !sameId(value.next_cursor, items.at(-1)?.artifact_id))) invalid();
  return value as unknown as PaiInputSources;
}

/** Actual persisted read-set, including any server-bound sources; not an executed ContextSnapshot. */
export async function readRunSourceBindings(api: PaiSourcesApi, scope: PaiSourcesScope, runId: string, expectedSessionId?: string): Promise<PaiRunSourceBindings> {
  const expected = expectedScope(scope);
  if (!uuid(runId) || expectedSessionId !== undefined && !uuid(expectedSessionId)) invalid();
  const value = envelope(await api<unknown>(`v1/categories/${scope.categoryId}/agent-runs/${runId}/source-bindings`), scope, expected, "agent-run-source-bindings/v1", ["run_id", "session_id"]);
  if (!sameId(value.run_id, runId) || !uuid(value.session_id) || expectedSessionId !== undefined && !sameId(value.session_id, expectedSessionId)) invalid();
  const rows = value.items as unknown[];
  let previous: string | null = null;
  for (const item of rows) {
    if (!object(item) || !keys(item, ["artifact_id", "expected_revision", "product_id", "current"])
      || !uuid(item.artifact_id) || !revision(item.expected_revision) || !nullableUuid(item.product_id)) invalid();
    const identity = item.artifact_id.toLowerCase();
    if (previous !== null && previous >= identity) invalid();
    previous = identity;
    if (item.current !== null && (!source(item.current) || !sameId(item.current.artifact_id, item.artifact_id)
      || !sameId(item.current.product_id, item.product_id)
      || item.current.availability.available && item.current.artifact_revision !== item.expected_revision)) invalid();
  }
  return value as unknown as PaiRunSourceBindings;
}

/** Copy the selected Artifact version; UploadedOriginal.revision is a separate fact. */
export function inputSourceReference(value: PaiInputSource): PaiSourceReference {
  if (!source(value) || !value.availability.available) invalid();
  return { artifact_id: value.artifact_id, expected_revision: value.artifact_revision };
}

/** A refreshed catalog can invalidate a selection, never silently upgrade its version. */
export function validateInputSourceSelection(selected: readonly PaiSourceReference[], catalog: PaiInputSources): PaiSourceReference[] {
  if (!references(selected) || !Array.isArray(catalog.items) || !catalog.items.every(source)) invalid();
  return selected.map(ref => {
    const candidates = catalog.items.filter(item => sameId(item.artifact_id, ref.artifact_id));
    if (candidates.length !== 1 || !candidates[0].availability.available || candidates[0].artifact_revision !== ref.expected_revision) invalid();
    return { artifact_id: ref.artifact_id, expected_revision: ref.expected_revision };
  });
}

/** Exact selected subset only; extra persisted bindings have no inferred source role. */
export function sourceSelectionMatchesBindings(selected: readonly PaiSourceReference[], bindings: PaiRunSourceBindings): boolean {
  return references(selected) && Array.isArray(bindings.items) && selected.every(ref => bindings.items.filter(item =>
    sameId(item.artifact_id, ref.artifact_id) && item.expected_revision === ref.expected_revision).length === 1);
}
