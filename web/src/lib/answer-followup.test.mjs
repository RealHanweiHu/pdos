import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(import.meta.url), ts = dependency("typescript");
function load(filename) { const compiled = new Module(filename); compiled.require = name => name.startsWith(".") ? load(path.resolve(path.dirname(filename), name + ".ts")) : dependency(name); compiled._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename); return compiled.exports; }
const { deeperLookupRequest, collapsedAnswerCitations, readExclusionSources } = load(path.join(directory, "answer-followup.ts"));
const { restoreContinuation } = load(path.join(directory, "run-continuation.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;

test("deep is an explicit same-parent continuation and holds detached fixed sources", () => {
  const selected = [{ artifact_id: id(4), expected_revision: 2 }];
  const body = deeperLookupRequest(id(1), "进一步核对工况", id(2), selected);
  assert.deepEqual(body, { goal: "进一步核对工况", idempotency_key: id(2), continue_from_run_id: id(1), lookup_depth: "deep", sources: selected });
  selected[0].expected_revision = 9; assert.equal(body.sources[0].expected_revision, 2);
  for (const key of ["session_id", "product_id", "project_id", "requested_skills", "verification_action", "audience"]) assert.equal(key in body, false);
});
test("native continuation journal retains full deep/search choices and rejects added scope", () => {
  const pending = { root: "v1/personal/agent-runs", owner_id: id(8), request: { ...deeperLookupRequest(id(1), "继续核对", id(2)), search_preferences: { scope: "same_category", include_customer_private: false } } };
  assert.deepEqual(restoreContinuation(JSON.parse(JSON.stringify(pending)), pending.root, id(8), id(1)), pending);
  for (const patch of [{ lookup_depth: "quick" }, { lookup_depth: "max" }, { product_id: id(4) }, { session_id: id(5) }, { source_proof: {} }, { search_preferences: { scope: "current", include_customer_private: false, approved: true } }]) assert.equal(restoreContinuation({ ...pending, request: { ...pending.request, ...patch } }, pending.root, id(8), id(1)), null);
  assert.equal(restoreContinuation(pending, pending.root, id(9), id(1)), null);
});
test("deep helper rejects malformed fixed sources before journal delegation", () => {
  assert.throws(() => deeperLookupRequest(id(1), "继续", id(2), [{ artifact_id: id(4), expected_revision: 0 }]));
  assert.throws(() => deeperLookupRequest(id(1), "继续", id(2), [{ artifact_id: id(4), expected_revision: 1, owner: id(3) }]));
  assert.throws(() => deeperLookupRequest(id(1), "x".repeat(8001), id(2)));
});
test("collapse maps root/reissued citations only through current saved exclusions and exact server source identity", () => {
  const answer = { sources: [{ citation_id: id(10), source_type: "issue", source_id: id(20), source_revision: 1, title: "同名案例" }, { citation_id: id(11), source_type: "issue", source_id: id(21), source_revision: 1, title: "同名案例" }] };
  const before = JSON.stringify(answer);
  const snapshot = { run_id: id(1), state: { exclusions: [{ id: id(9), kind: "citation" }] }, feedbacks: [{ selection_id: id(9), source_type: "issue", source_id: id(20) }] };
  assert.deepEqual(collapsedAnswerCitations(answer, snapshot, id(1)), [id(10)]);
  assert.deepEqual(collapsedAnswerCitations(answer, { ...snapshot, state: { exclusions: [] } }, id(1)), []);
  assert.deepEqual(collapsedAnswerCitations(answer, snapshot, id(2)), []);
  assert.deepEqual(collapsedAnswerCitations(answer, { ...snapshot, feedbacks: [] }, id(1)), []);
  assert.equal(JSON.stringify(answer), before);
});
test("artifact exclusions use typed stable artifact identity and direct citation IDs remain exact", () => {
  const answer = { sources: [{ citation_id: id(10), source_type: "artifact", source_id: id(20) }, { citation_id: id(11), source_type: "issue", source_id: id(20) }] };
  const snapshot = { run_id: id(1), state: { exclusions: [{ id: id(20), kind: "artifact" }] }, feedbacks: [] };
  assert.deepEqual(collapsedAnswerCitations(answer, snapshot, id(1)), [id(10)]);
  snapshot.state.exclusions = [{ id: id(11), kind: "citation" }];
  assert.deepEqual(collapsedAnswerCitations(answer, snapshot, id(1)), [id(11)]);
});
test("private feedback pagination yields identity only and never query/quote/rank text", async () => {
  const calls = [];
  const value = { type: "retrieval_feedback", version: "retrieval-feedback/v1", action: "not_relevant", selection: { id: id(5), kind: "citation" }, source: { source_type: "issue", source_id: id(6), title: "PRIVATE_TITLE" }, candidate: { ranking_version: "PRIVATE_RANK" }, quote: "PRIVATE_QUOTE" };
  const rows = [{ event: value }, ...Array.from({ length: 199 }, () => ({ event: { type: "tool_finished" } }))];
  const result = await readExclusionSources(async url => { calls.push(url); return calls.length === 1 ? { items: rows, next_cursor: 200 } : { items: [], next_cursor: 200 }; }, "v1/agent-runs", id(1));
  assert.equal(calls.length, 2); assert.match(calls[1], /after=200/);
  assert.deepEqual(result, [{ selection_id: id(5), source_type: "issue", source_id: id(6) }]);
  assert.doesNotMatch(JSON.stringify(result), /PRIVATE_/);
});
