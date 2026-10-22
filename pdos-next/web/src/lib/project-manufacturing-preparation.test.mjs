import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const require = createRequire(import.meta.url), ts = require("typescript");
const compile = path => ts.transpileModule(readFileSync(new URL(path, import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const contract = { exports: {} }, compiled = { exports: {} };
runInNewContext(compile("../components/manufacturing-preparation/manufacturing-preparation-contract.ts"), { module: contract, exports: contract.exports });
runInNewContext(compile("./project-manufacturing-preparation.ts"), {
  module: compiled, exports: compiled.exports, URLSearchParams,
  require: name => { assert.equal(name, "../components/manufacturing-preparation/manufacturing-preparation-contract"); return contract.exports; },
});
const { readProjectManufacturingPreparation, readProjectManufacturingPreparationDocument } = compiled.exports;
const id = number => `00000000-0000-4000-8000-${number.toString(16).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3) };
const path = `v1/categories/${scope.categoryId}/products/${scope.productId}/manufacturing-preparations?project_id=${scope.projectId}`;
const schema = "pdos-manufacturing-preparation-v1", at = "2026-10-18T12:34:56.123456+00:00";
const copy = value => JSON.parse(JSON.stringify(value));
const source = () => ({ artifact_id: id(4), expected_revision: 1, line: 1, quote: "合成固定来源原文" });

function version(identity = 10, kind = "work_instruction") {
  const input = {
    project_id: scope.projectId, process: { id: id(5), revision: 2 }, title: `Actual ${kind} title`,
    previous_id: null, expected_previous_revision: null, visibility: "private", reason: "Original recorded reason", sources: [source()],
  };
  if (kind === "work_instruction") Object.assign(input, { operation_key: "assembly", conditions: null,
    steps: [{ key: "step-1", text: "原始作业说明", safety_notes: null, sources: [source()], parameters: [
      { key: "pressure", nominal: "9007199254740993.123456789", lower: null, upper: null, unit: "Pa", sources: [source()] },
      { key: "torque", nominal: null, lower: null, upper: null, unit: null, sources: [] },
    ] }] });
  else if (kind === "control_plan") Object.assign(input, { operation_key: "inspection", checks: [
    { key: "pressure-check", feature: "Original feature", method: null, criterion: null, frequency: null, sampling_method: null, reaction_plan: null, responsible_role: null, sources: [source()] },
  ] });
  else Object.assign(input, { operations: [{ operation_key: "assembly", work_instruction: null, control_plan: null },
    { operation_key: "inspection", work_instruction: null, control_plan: null }], risk_notes: null, packaging_label_basis: null });
  return {
    schema_version: schema, id: id(identity), kind, revision: 1, series_id: id(identity), project_id: scope.projectId,
    owner_id: id(6), visibility: "private", title: input.title, status: "draft", purpose: "Actual project purpose",
    process: copy(input.process), operation_key: input.operation_key ?? null, previous_id: null, previous_revision: null,
    created_at: at, is_current: true, source_status: "needs_recheck", required_source_read_set: [{ artifact_id: id(4), expected_revision: 1 }],
    body: { schema_version: schema, kind, status: "draft", input,
      scope: { project_id: scope.projectId, purpose: "Actual project purpose" },
      process_snapshot: { id: id(5), revision: 2, name: "Fixed manufacturing process", operations: [{ key: "assembly", name: "Original assembly" }, { key: "inspection", name: "Original inspection" }] },
      document_bindings: [], gaps: [{ code: "SAVED_UNKNOWN", detail: "保存时未知，未实时重算", operation_key: "assembly", fields: ["torque"] }],
      qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false },
    sources: [source()], receipt_id: id(identity + 100), qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false,
  };
}
function world() {
  const state = { calls: [], response: { schema_version: schema, versions: [version(), version(20, "control_plan"), version(30, "manufacturing_baseline")],
    history_page: { next_cursor: null }, has_more: false, unavailable_count: 0, qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false } };
  state.api = async (actual, ...body) => { state.calls.push([actual, body]); assert.equal(actual, path); assert.equal(body.length, 0); return copy(state.response); };
  return state;
}
const read = state => readProjectManufacturingPreparation(state.api, scope);

test("one exact project GET preserves guarded draft bodies, precision, nulls and saved gap context", async () => {
  const state = world(), before = copy(state.response), value = copy(await read(state));
  assert.deepEqual(state.calls, [[path, []]]);
  assert.deepEqual(value.currentVersions, before.versions); assert.deepEqual(value.returnedHistory, []);
  assert.equal(value.currentVersions[0].body.input.steps[0].parameters[0].nominal, "9007199254740993.123456789");
  assert.equal(value.currentVersions[0].body.input.steps[0].parameters[1].nominal, null);
  assert.equal(value.currentVersions[0].created_at, at); assert.equal(value.currentVersions[0].source_status, "needs_recheck");
  assert.equal(value.qualification, "unknown"); assert.equal(value.manufacturingRelease, null); assert.equal(value.negativeEnumerationComplete, false);
  assert.deepEqual(state.response, before);
});

test("same kind/process/operation may have multiple current series without being collapsed", async () => {
  const state = world(); state.response.versions.push(version(11));
  const value = await read(state); assert.equal(value.currentVersions.length, 4);
  assert.deepEqual(copy(value.currentVersions.filter(row => row.kind === "work_instruction").map(row => row.id)), [id(10), id(11)]);
});

test("returned history stays distinct and an unread previous version is not required or substituted", async () => {
  const state = world(), old = version(11), current = state.response.versions[0];
  old.series_id = current.series_id; old.is_current = false;
  current.revision = 2; current.previous_id = old.id; current.previous_revision = 1;
  current.body.input.previous_id = old.id; current.body.input.expected_previous_revision = 1;
  state.response.versions.push(old);
  state.response.has_more = true; state.response.history_page.next_cursor = "opaque-unfollowed-history-cursor";
  const value = await read(state); assert.equal(value.currentVersions.length, 3); assert.equal(value.returnedHistory.length, 1);
  assert.equal(value.returnedHistory[0].id, old.id); assert.equal(value.hasMore, true); assert.equal(state.calls.length, 1);
  state.response.versions.pop();
  const partial = await read(state); assert.equal(partial.returnedHistory.length, 0); assert.equal(partial.currentVersions[0].previous_id, old.id);
});

test("fixed baseline document binding retains the old exact reference without following Current", async () => {
  const state = world(), baseline = state.response.versions[2], fixed = { kind: "work_instruction", id: id(88), revision: 3 };
  baseline.body.input.operations[0].work_instruction = fixed;
  baseline.body.document_bindings = [{ operation_key: "assembly", ...fixed, body_sha256: "a".repeat(64) }];
  const result = await read(state);
  assert.deepEqual(copy(result.currentVersions[2].body.document_bindings), baseline.body.document_bindings);
  assert.equal(state.calls.length, 1, "The reader does not resolve or replace historical child references");
});

test("empty visible data keeps historical/availability limitations and no ready or release conclusion", async () => {
  const state = world(); state.response.versions = []; state.response.has_more = true;
  state.response.history_page.next_cursor = "opaque-cursor"; state.response.unavailable_count = 7;
  const value = await read(state); assert.equal(value.currentVersions.length, 0); assert.equal(value.hasMore, true); assert.equal(value.unavailableCount, 7);
  assert.equal("ready" in value, false); assert.equal("published" in value, false);
});

for (const [name, mutate] of [
  ["wrong project", state => { state.response.versions[0].project_id = id(90); }],
  ["fixed process snapshot mismatch", state => { state.response.versions[0].body.process_snapshot.revision = 3; }],
  ["source/body mismatch", state => { state.response.versions[0].body.input.sources[0].quote = "different source"; }],
  ["fabricated published draft", state => { state.response.versions[0].status = "published"; }],
  ["fabricated qualification", state => { state.response.qualification = "qualified"; }],
  ["fabricated release", state => { state.response.versions[0].manufacturing_release = { status: "approved" }; }],
  ["fabricated complete negative enumeration", state => { state.response.negative_enumeration_complete = true; }],
  ["unknown missing fields", state => { delete state.response.versions[0].body.gaps; }],
  ["missing coverage count", state => { delete state.response.unavailable_count; }],
  ["missing page metadata", state => { delete state.response.history_page; }],
  ["has-more without actual cursor", state => { state.response.has_more = true; }],
  ["cursor contradicts complete history", state => { state.response.history_page.next_cursor = "opaque"; }],
  ["duplicate record identity", state => { state.response.versions.push(copy(state.response.versions[0])); }],
  ["two current heads in one series", state => { const row = version(11); row.series_id = state.response.versions[0].series_id; row.revision = 2; state.response.versions.push(row); }],
  ["duplicate series/revision under another identity", state => { const row = version(11); row.series_id = state.response.versions[0].series_id; row.is_current = false; state.response.versions.push(row); }],
  ["visible previous belongs to another series", state => { const row = state.response.versions[0], previous = state.response.versions[1]; row.previous_id = previous.id; row.previous_revision = previous.revision; row.body.input.previous_id = previous.id; row.body.input.expected_previous_revision = previous.revision; }],
  ["registration time has no timezone", state => { state.response.versions[0].created_at = "2026-10-18T12:34:56"; }],
]) test(`rejects ${name} instead of returning partial or invented facts`, async () => {
  const state = world(); mutate(state); await assert.rejects(read(state), /未能核对/);
});

for (const field of ["categoryId", "productId", "projectId"]) test(`invalid ${field} never calls an endpoint`, async () => {
  const state = world(); await assert.rejects(readProjectManufacturingPreparation(state.api, { ...scope, [field]: "bad" })); assert.equal(state.calls.length, 0);
});
for (const status of [401, 403, 409, 503]) test(`API ${status} remains a failure, never an empty draft collection`, async () => {
  const failure = Object.assign(new Error("Actual API failure"), { status });
  await assert.rejects(readProjectManufacturingPreparation(async () => { throw failure; }, scope), error => error === failure);
});

test("default list keeps its original path and adds the original next cursor without following it", async () => {
  const state = world(), result = await read(state);
  assert.equal(result.nextCursor, null); assert.equal(state.calls.length, 1);
  state.response.history_page.next_cursor = "raw-next-cursor"; state.response.has_more = true;
  assert.equal((await read(state)).nextCursor, "raw-next-cursor"); assert.equal(state.calls.length, 2);
});

test("history cursor remains opaque and is encoded as one exact query value", async () => {
  const state = world(), cursor = "opaque:+/=&?not-a-uuid", calls = [];
  state.response.history_page.next_cursor = "different-opaque-next"; state.response.has_more = true;
  const result = await readProjectManufacturingPreparation(async (request, ...body) => {
    calls.push(request); assert.equal(body.length, 0); return copy(state.response);
  }, scope, { historyCursor: cursor });
  assert.equal(calls.length, 1);
  const query = new URLSearchParams({ project_id: scope.projectId, history_cursor: cursor });
  assert.equal(calls[0], `${path.split("?")[0]}?${query}`); assert.equal(result.nextCursor, "different-opaque-next");
});

test("each history page is a new current-plus-history snapshot with its own unavailable count", async () => {
  const state = world(), first = copy(state.response), oldHistory = version(41, "control_plan"); oldHistory.is_current = false;
  first.versions.push(oldHistory); first.history_page.next_cursor = "first-page-end"; first.has_more = true; first.unavailable_count = 7;
  const second = copy(state.response), oldWi = second.versions.shift(), newWi = copy(oldWi);
  oldWi.is_current = false; newWi.id = id(11); newWi.revision = 2; newWi.previous_id = oldWi.id; newWi.previous_revision = 1;
  newWi.body.input.previous_id = oldWi.id; newWi.body.input.expected_previous_revision = 1;
  second.versions.unshift(newWi); second.versions.push(oldWi); second.unavailable_count = 2;
  const responses = [first, second], requests = [];
  const api = async (request, ...body) => { requests.push(request); assert.equal(body.length, 0); return responses.shift(); };
  const page1 = await readProjectManufacturingPreparation(api, scope);
  const page2 = await readProjectManufacturingPreparation(api, scope, { historyCursor: page1.nextCursor });
  assert.equal(page1.currentVersions[0].id, id(10)); assert.equal(page2.currentVersions[0].id, id(11));
  assert.deepEqual(copy(page2.returnedHistory.map(row => row.id)), [id(10)]);
  assert.equal(page2.returnedHistory.some(row => row.id === id(41)), false);
  assert.equal(page1.unavailableCount, 7); assert.equal(page2.unavailableCount, 2); assert.equal(page2.nextCursor, null); assert.equal(requests.length, 2);
});

test("an unavailable history page may return no history while retaining a next cursor", async () => {
  const state = world(); state.response.versions = []; state.response.unavailable_count = 50;
  state.response.history_page.next_cursor = "next-after-unreadable-candidates"; state.response.has_more = true;
  const value = await readProjectManufacturingPreparation(async () => copy(state.response), scope, { historyCursor: "older-page-position" });
  assert.equal(value.returnedHistory.length, 0); assert.equal(value.nextCursor, "next-after-unreadable-candidates"); assert.equal(value.unavailableCount, 50);
});

for (const options of [{ historyCursor: "" }, { historyCursor: "   " }, { historyCursor: "x".repeat(2001) }, { historyCursor: 7 }, { historyCursor: "\ud800" }, { cursor: "wrong-option" }, null]) {
  test(`invalid cursor options ${JSON.stringify(options)} fail before a request`, async () => {
    const state = world(); await assert.rejects(readProjectManufacturingPreparation(state.api, scope, options)); assert.equal(state.calls.length, 0);
  });
}
test("a response cannot repeat the requested cursor and pretend history advanced", async () => {
  const state = world(); state.response.history_page.next_cursor = "same-position"; state.response.has_more = true;
  await assert.rejects(readProjectManufacturingPreparation(async () => copy(state.response), scope, { historyCursor: "same-position" }));
});

function fixedWorld(kind = "work_instruction") {
  const baseline = version(30, "manufacturing_baseline"), document = version(kind === "work_instruction" ? 10 : 20, kind);
  const operation = baseline.body.input.operations.find(row => row.operation_key === document.operation_key);
  const binding = { operation_key: document.operation_key, kind, id: document.id, revision: document.revision, body_sha256: "a".repeat(64) };
  operation[kind] = { kind, id: document.id, revision: document.revision }; baseline.body.document_bindings.push(copy(binding));
  const state = { calls: [], baseline, binding, document, failure: null };
  state.api = async (request, ...body) => { assert.equal(body.length, 0); state.calls.push(request); if (state.failure) throw state.failure; return copy(state.document); };
  return state;
}
const readDocument = state => readProjectManufacturingPreparationDocument(state.api, scope, state.baseline, state.binding);

for (const kind of ["work_instruction", "control_plan"]) test(`fixed ${kind} GET uses saved binding and preserves original body, sources, gaps and hash caveat`, async () => {
  const state = fixedWorld(kind), baselineBefore = copy(state.baseline), original = copy(state.document);
  state.document.is_current = false; original.is_current = false;
  const result = copy(await readDocument(state));
  assert.deepEqual(state.calls, [`${path.split("?")[0]}/${kind}/${state.binding.id}?revision=${state.binding.revision}`]);
  assert.deepEqual(result.document, original); assert.deepEqual(result.binding, state.binding); assert.deepEqual(state.baseline, baselineBefore);
  assert.deepEqual(result.baseline, { kind: "manufacturing_baseline", id: state.baseline.id, revision: state.baseline.revision });
  assert.equal(result.bodyHashVerification, "not_returned_by_endpoint"); assert.equal(result.binding.body_sha256, "a".repeat(64));
  assert.equal(result.document.is_current, false); assert.equal(result.document.source_status, "needs_recheck");
  assert.equal("body_sha256" in result.document, false); assert.equal("bodyHashVerified" in result, false);
});

for (const [name, mutate] of [
  ["baseline from another project", state => { state.baseline.project_id = id(91); }],
  ["baseline kind is not baseline", state => { state.baseline = version(); }],
  ["unknown binding identity", state => { state.binding.id = id(91); }],
  ["changed bound revision", state => { state.binding.revision++; }],
  ["changed operation", state => { state.binding.operation_key = "inspection"; }],
  ["changed saved hash", state => { state.binding.body_sha256 = "b".repeat(64); }],
  ["baseline used as a child", state => { state.binding.kind = "manufacturing_baseline"; }],
  ["malformed baseline body", state => { state.baseline.body.process_snapshot.revision++; }],
]) test(`fixed read rejects ${name} before GET`, async () => {
  const state = fixedWorld(); mutate(state); await assert.rejects(readDocument(state)); assert.equal(state.calls.length, 0);
});

for (const [name, mutate] of [
  ["wrong fixed ID", state => { state.document.id = id(91); }],
  ["current child replacing fixed version", state => { state.document.revision = 2; }],
  ["wrong kind", state => { state.document = version(20, "control_plan"); }],
  ["wrong project", state => { state.document.project_id = id(91); }],
  ["different process", state => { state.document.process.id = id(91); state.document.body.input.process.id = id(91); state.document.body.process_snapshot.id = id(91); }],
  ["different process revision", state => { state.document.process.revision = 3; state.document.body.input.process.revision = 3; state.document.body.process_snapshot.revision = 3; }],
  ["different operation", state => { state.document.operation_key = "inspection"; state.document.body.input.operation_key = "inspection"; }],
  ["clock without timezone", state => { state.document.created_at = "2026-10-18T12:00:00"; }],
  ["missing body", state => { delete state.document.body; }],
]) test(`fixed response rejects ${name} rather than substituting Current or partial text`, async () => {
  const state = fixedWorld(); mutate(state); await assert.rejects(readDocument(state)); assert.equal(state.calls.length, 1);
});

for (const status of [401, 403, 409, 503]) test(`fixed endpoint ${status} propagates unchanged without text fallback`, async () => {
  const state = fixedWorld(); state.failure = Object.assign(new Error("Original fixed GET failure"), { status });
  await assert.rejects(readDocument(state), error => error === state.failure); assert.equal(state.calls.length, 1);
});
