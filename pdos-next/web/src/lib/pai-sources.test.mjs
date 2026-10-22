import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const ts = createRequire(import.meta.url)("typescript"), compiled = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./pai-sources.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { module: compiled, exports: compiled.exports, URLSearchParams });
const { readInputSources, readRunSourceBindings, inputSourceReference, validateInputSourceSelection, sourceSelectionMatchesBindings } = compiled.exports;
const id = n => `00000000-0000-0000-0000-${n.toString(16).padStart(12, "0")}`;
const scope = { principalId: id(1), categoryId: id(2), productId: id(3), proposalId: id(4) };
const date = "2026-10-17T12:34:56.123456+00:00";
const clone = value => JSON.parse(JSON.stringify(value));
const actualScope = () => ({ category_id: scope.categoryId, product_id: scope.productId, proposal_id: scope.proposalId });
function source(n = 20) {
  return { artifact_id: id(n), artifact_revision: 3, title: "实际登记附件", product_id: scope.productId, status: "active",
    original: { id: id(n + 100), revision: 7, filename: "真实原件.pdf", parse_status: "parsed", parse_code: null, scan_status: "clean" },
    availability: { available: true, code: null } };
}
function catalog() { return { version: "agent-input-sources/v1", principal_id: scope.principalId, scope: actualScope(), as_of: date, items: [source()], next_cursor: null }; }
function bindings() { return { version: "agent-run-source-bindings/v1", principal_id: scope.principalId, scope: actualScope(), as_of: date, run_id: id(8), session_id: id(9), items: [{ artifact_id: id(20), expected_revision: 3, product_id: scope.productId, current: source() }] }; }
function apiFor(value) {
  const calls = [];
  const api = async (...args) => { calls.push(args); assert.equal(args.length, 1, "GET only; no body"); return clone(value); };
  return { api, calls };
}

test("catalog GET binds full category/filter scope and retains distinct Artifact/original versions", async () => {
  const raw = catalog(), transport = apiFor(raw), value = await readInputSources(transport.api, scope);
  assert.equal(transport.calls[0][0], `v1/categories/${scope.categoryId}/agent-input-sources?page_size=20&product_id=${scope.productId}&proposal_id=${scope.proposalId}`);
  assert.deepEqual(clone(value), raw); assert.equal(value.as_of, date);
  assert.deepEqual(clone(inputSourceReference(value.items[0])), { artifact_id: id(20), expected_revision: 3 });
  assert.equal(value.items[0].original.revision, 7, "Original revision is never borrowed as Artifact revision");
});

test("category roots and registered text require no Product or original upload", async () => {
  const raw = catalog(); raw.scope.product_id = null; raw.scope.proposal_id = null;
  raw.items[0].product_id = null; raw.items[0].original = null;
  const transport = apiFor(raw), value = await readInputSources(transport.api, { ...scope, productId: null, proposalId: null });
  assert.equal(transport.calls[0][0], `v1/categories/${scope.categoryId}/agent-input-sources?page_size=20`);
  assert.equal(value.items[0].original, null); assert.equal(inputSourceReference(value.items[0]).expected_revision, 3);
});

test("selected Product catalog may include root sources and explicit unavailable heads", async () => {
  const raw = catalog(), unavailable = source(21); unavailable.product_id = null; unavailable.status = "withdrawn";
  unavailable.availability = { available: false, code: "SOURCE_UNAVAILABLE" }; raw.items.push(unavailable);
  const value = await readInputSources(apiFor(raw).api, scope);
  assert.equal(value.items.length, 2); assert.throws(() => inputSourceReference(value.items[1]));
});

test("page anchors are fixed Artifact IDs, never inferred from titles or row position", async () => {
  const raw = catalog(); raw.next_cursor = id(20);
  const transport = apiFor(raw); assert.equal((await readInputSources(transport.api, scope, { pageSize: 1, cursor: id(19) })).next_cursor, id(20));
  assert.match(transport.calls[0][0], new RegExp(`cursor=${id(19)}`));
});

test("Run binding GET is exact, query-free and preserves its actual Session", async () => {
  const raw = bindings(), transport = apiFor(raw), value = await readRunSourceBindings(transport.api, scope, id(8), id(9));
  assert.equal(transport.calls[0][0], `v1/categories/${scope.categoryId}/agent-runs/${id(8)}/source-bindings`);
  assert.deepEqual(clone(value), raw); assert.equal(value.items[0].expected_revision, 3);
});

test("Run fixed versions survive Current drift without silently upgrading selected references", async () => {
  const raw = bindings(); raw.items[0].current.artifact_revision = 4;
  raw.items[0].current.availability = { available: false, code: "SOURCE_STALE" };
  const value = await readRunSourceBindings(apiFor(raw).api, scope, id(8));
  assert.equal(value.items[0].expected_revision, 3); assert.equal(value.items[0].current.artifact_revision, 4);
  assert.equal(sourceSelectionMatchesBindings([{ artifact_id: id(20), expected_revision: 3 }], value), true);
  assert.equal(sourceSelectionMatchesBindings([{ artifact_id: id(20), expected_revision: 4 }], value), false);
});

test("currently unreadable bindings retain only the fixed identity without a fallback title", async () => {
  const raw = bindings(); raw.items[0].current = null;
  const value = await readRunSourceBindings(apiFor(raw).api, scope, id(8));
  assert.equal(value.items[0].current, null);
  assert.equal(sourceSelectionMatchesBindings([{ artifact_id: id(20), expected_revision: 3 }], value), true);
});

test("root Run bindings can retain real Product sources without inventing their role", async () => {
  const raw = bindings(); raw.scope.product_id = null;
  const value = await readRunSourceBindings(apiFor(raw).api, { ...scope, productId: null }, id(8));
  assert.equal(value.items[0].product_id, scope.productId);
  assert.equal("role" in value.items[0], false); assert.equal("context_snapshot" in value, false);
});

test("fixed selection is copied, deduplicated by identity and rechecked against refreshed availability", () => {
  const ref = inputSourceReference(source()), raw = catalog();
  const valid = validateInputSourceSelection([ref], raw);
  assert.deepEqual(clone(valid), [{ artifact_id: id(20), expected_revision: 3 }]); assert.notEqual(valid[0], ref);
  const drift = catalog(); drift.items[0].artifact_revision = 4;
  const withdrawn = catalog(); withdrawn.items[0].availability = { available: false, code: "SOURCE_UNAVAILABLE" };
  const gone = catalog(); gone.items = [];
  for (const value of [drift, withdrawn, gone]) assert.throws(() => validateInputSourceSelection([ref], value));
  assert.throws(() => validateInputSourceSelection([ref, ref], raw));
  assert.throws(() => validateInputSourceSelection([{ ...ref, title: "not POST data" }], raw));
  assert.equal(ref.expected_revision, 3);
});

test("actual binding comparison checks only an exact selected subset, not invented source roles", () => {
  const raw = bindings(); raw.items.push({ artifact_id: id(21), expected_revision: 1, product_id: null, current: null });
  assert.equal(sourceSelectionMatchesBindings([{ artifact_id: id(20), expected_revision: 3 }], raw), true);
  assert.equal(sourceSelectionMatchesBindings([{ artifact_id: id(22), expected_revision: 3 }], raw), false);
  assert.equal(sourceSelectionMatchesBindings([{ artifact_id: id(20), expected_revision: 3 }, { artifact_id: id(20), expected_revision: 3 }], raw), false);
});

test("invalid scope, selection and query are rejected before any GET", async () => {
  const transport = apiFor(catalog());
  for (const bad of [{ ...scope, principalId: "wrong" }, { ...scope, categoryId: "" }, { ...scope, productId: undefined }, { ...scope, proposalId: "bad" }]) await assert.rejects(readInputSources(transport.api, bad));
  for (const options of [{ cursor: "bad" }, { pageSize: 0 }, { pageSize: 51 }, { pageSize: 1.5 }, { pageSize: null }, { q: "unsupported" }]) await assert.rejects(readInputSources(transport.api, scope, options));
  await assert.rejects(readRunSourceBindings(transport.api, scope, "bad"));
  await assert.rejects(readRunSourceBindings(transport.api, scope, id(8), "bad"));
  assert.equal(transport.calls.length, 0);
});

for (const [name, mutate] of [
  ["wrong version", value => { value.version = "unknown"; }],
  ["wrong owner", value => { value.principal_id = id(999); }],
  ["wrong category", value => { value.scope.category_id = id(999); }],
  ["wrong Product filter", value => { value.scope.product_id = null; }],
  ["wrong proposal", value => { value.scope.proposal_id = id(999); }],
  ["missing exact scope", value => { delete value.scope.proposal_id; }],
  ["foreign Product head", value => { value.items[0].product_id = id(999); }],
  ["missing Artifact version", value => { delete value.items[0].artifact_revision; }],
  ["invalid Artifact identity", value => { value.items[0].artifact_id = "bad"; }],
  ["zero Artifact version", value => { value.items[0].artifact_revision = 0; }],
  ["duplicate Artifact", value => { value.items.push(clone(value.items[0])); }],
  ["unknown lifecycle", value => { value.items[0].status = "ready"; }],
  ["missing availability", value => { delete value.items[0].availability; }],
  ["available withdrawn source", value => { value.items[0].status = "withdrawn"; }],
  ["available source carries failure", value => { value.items[0].availability.code = "SOURCE_STALE"; }],
  ["unavailable source lacks reason", value => { value.items[0].availability.available = false; }],
  ["missing original version", value => { delete value.items[0].original.revision; }],
  ["missing parse state", value => { delete value.items[0].original.parse_status; }],
  ["raw content in a head", value => { value.items[0].content = "private full text"; }],
  ["storage key in original", value => { value.items[0].original.storage_key = "private object"; }],
  ["missing next cursor", value => { delete value.next_cursor; }],
  ["next cursor not page end", value => { value.next_cursor = id(999); }],
]) test(`catalog fails closed on ${name}`, async () => { const raw = catalog(); mutate(raw); await assert.rejects(readInputSources(apiFor(raw).api, scope)); });

for (const [name, mutate] of [
  ["wrong Run", value => { value.run_id = id(999); }],
  ["wrong Session", value => { value.session_id = id(999); }],
  ["wrong Run Product scope", value => { value.scope.product_id = null; }],
  ["wrong current Artifact", value => { value.items[0].current.artifact_id = id(999); }],
  ["wrong current Product", value => { value.items[0].current.product_id = null; }],
  ["available wrong version", value => { value.items[0].current.artifact_revision = 4; }],
  ["duplicate fixed identity", value => { value.items.push(clone(value.items[0])); }],
  ["missing current marker", value => { delete value.items[0].current; }],
  ["zero fixed version", value => { value.items[0].expected_revision = 0; }],
  ["unreadable title fallback", value => { value.items[0].current = null; value.items[0].title = "private old title"; }],
  ["body in binding", value => { value.raw_content = "private"; }],
]) test(`binding fails closed on ${name}`, async () => { const raw = bindings(); mutate(raw); await assert.rejects(readRunSourceBindings(apiFor(raw).api, scope, id(8), id(9))); });

test("catalog pages never repeat the input anchor or exceed the requested size", async () => {
  await assert.rejects(readInputSources(apiFor(catalog()).api, scope, { cursor: id(20) }));
  const raw = catalog(); raw.items.push(source(21));
  await assert.rejects(readInputSources(apiFor(raw).api, scope, { pageSize: 1 }));
  raw.scope.product_id = null; raw.items = [source()];
  await assert.rejects(readInputSources(apiFor(raw).api, { ...scope, productId: null }));
});

test("empty catalog/bindings are real empty responses; failures propagate without retries or old data", async () => {
  const empty = catalog(); empty.items = []; assert.equal((await readInputSources(apiFor(empty).api, scope)).items.length, 0);
  const noBinding = bindings(); noBinding.items = []; assert.equal((await readRunSourceBindings(apiFor(noBinding).api, scope, id(8))).items.length, 0);
  const failure = Object.assign(new Error("已撤权"), { status: 403 }), calls = [];
  const api = async path => { calls.push(path); throw failure; };
  await assert.rejects(readInputSources(api, scope), error => error === failure);
  await assert.rejects(readRunSourceBindings(api, scope, id(8)), error => error === failure);
  assert.equal(calls.length, 2);
});
