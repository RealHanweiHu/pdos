import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const require = createRequire(import.meta.url), ts = require("typescript"), compiled = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./project-build-summary.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { module: compiled, exports: compiled.exports, URLSearchParams });
const { readProjectBuilds, readBuildTestSummary } = compiled.exports;
const id = n => `00000000-0000-0000-0000-${n.toString(16).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3) };
const date = "2026-10-17T12:34:56.123456+00:00", basis = "a".repeat(64);
const clone = value => JSON.parse(JSON.stringify(value));
const plain = clone;
const buildPath = `v1/categories/${scope.categoryId}/products/${scope.productId}/builds?project_id=${scope.projectId}`;
const resultsPath = `v1/categories/${scope.categoryId}/products/${scope.productId}/verification-results?build_id=${id(4)}`;

function build() {
  return { id: id(4), revision: 1, status: "planned", source_status: "needs_recheck", name: "Actual Build name", type: "tool_trial", purpose: "Actual purpose",
    owner_id: id(50), visibility: "category", project_id: scope.projectId, project_name: "Actual project", project_revision: 2,
    planned_quantity: "9007199254740993.12345678", unit: "件", planned_start: date, planned_end: null, created_at: date,
    verification_objectives: "Actual objectives", disposition_plan: "Actual disposition plan", previous_build_id: null,
    engineering_configuration: { id: id(5), revision: 3, status: "draft", name: "Fixed engineering", source_status: "needs_recheck",
      definition: { id: id(8), revision: 2 }, bom: { id: id(9), revision: 1 }, design_versions: { firmware: { external_id: "rev-04" } }, sources: [] },
    manufacturing_configuration: { id: id(6), revision: 4, status: "draft", name: "Fixed manufacturing", site: "Actual site", line: "Actual line", operations: [], sources: [] },
    required_source_read_set: [], readiness: null };
}
function binding() {
  return { id: id(4), revision: 1, product_id: scope.productId, project_id: scope.projectId,
    engineering_configuration: { id: id(5), revision: 3 }, manufacturing_configuration: { id: id(6), revision: 4 } };
}
function time() { return { occurred_at: date, received_at: date, original_timezone: "Asia/Shanghai", effective_at: null, source: { id: id(80), revision: 1, kind: "domain", position: "actual event" }, actor_id: id(50) }; }
function pair(n) { return { sample_id: id(n), item_id: "pressure" }; }
function measurement(n = 1) {
  return { id: id(60 + n), coverage: pair(40 + n), raw_value: " 9007199254740993.123456789 mm ", unit: "mm", observed_at: date, observed_timezone: "Asia/Shanghai", missing: [] };
}
function run(version = 3, status = "running") {
  const final = ["results_pending", "reviewed", "disposed"].includes(status);
  const snapshot = { id: id(20), revision: version, scope: { tenant_id: id(90), product_id: scope.productId, project_id: scope.projectId },
    request_id: id(30), request_revision: 3, build: binding(), status, result: "pending", coverage: [pair(41), pair(42)],
    measurements: status === "planned" ? [] : [measurement()],
    computed_results: status === "planned" ? [] : [
      { coverage: pair(41), result: "pass", measurement_id: id(61), reasons: [] },
      { coverage: pair(42), result: "indeterminate", measurement_id: null, reasons: ["尚未返回测量"] },
    ], partial_returns: status === "running" ? [{ returned_coverage: [pair(41)], pending_coverage: [pair(42)], at: time(), reason: "Actual partial return" }] : [],
    actual_start: status === "planned" ? null : time(), actual_end: final ? time() : null, final_result: final ? time() : null,
    professional_conclusion: ["reviewed", "disposed"].includes(status) ? { text: "Actual named review", at: time() } : null,
    disposition: status === "disposed" ? { text: "Actual named decision", at: time() } : null };
  return { id: id(20 + version), run_id: id(20), revision: version, request_id: id(30), request_revision: 3, build: binding(), status, result: "pending",
    source_status: "current", is_current: true, created_at: date, basis_sha256: basis, run_snapshot: snapshot,
    current_projection: status === "planned" ? null : { id: id(70), revision: 1, basis_sha256: basis, result: "indeterminate" } };
}
function request() {
  return { id: id(31), request_id: id(30), revision: 6, project_id: scope.projectId, title: "Actual current request", status: "executing", source_status: "current", is_current: true,
    build: binding(), request_snapshot: { id: id(30), revision: 6, status: "executing", scope: { tenant_id: id(90), product_id: scope.productId, project_id: scope.projectId }, build: binding() } };
}
function results() {
  return { requests: [request()], runs: [run()], current_by_request: { [id(30)]: { request_version_id: id(31), revision: 6 } },
    current_by_run: { [id(20)]: { run_version_id: id(23), revision: 3 } },
    projections: [{ id: id(70), revision: 1, run_id: id(20), run_version_id: id(23), run_revision: 3, basis_sha256: basis, result: "indeterminate", source_status: "current" }],
    unavailable_count: 2, has_more: false };
}
function world() {
  const state = { calls: [], builds: { items: [build()], unavailable_count: 1, has_more: false }, results: results(), fail: null };
  state.api = async function(path, ...args) {
    state.calls.push([path, args]);
    assert.equal(args.length, 0, "Every summary request is GET-only");
    if (state.fail && path.includes(state.fail.path)) throw state.fail.error;
    if (path === buildPath) return clone(state.builds);
    assert.equal(path, resultsPath);
    return clone(state.results);
  };
  return state;
}

test("project Build listing performs only its scoped GET, preserving exact quantity/date/configuration facts", async () => {
  const state = world(), before = clone(state.builds);
  const value = await readProjectBuilds(state.api, scope);
  assert.equal(state.calls.length, 1);
  assert.equal(state.calls[0][0], buildPath);
  assert.equal(value.items.length, 1);
  assert.equal(value.items[0].planned_quantity, "9007199254740993.12345678");
  assert.equal(value.items[0].planned_start, date);
  assert.equal(value.items[0].project_revision, 2, "A fixed project revision need not equal today's project version");
  assert.equal(value.items[0].status, "planned", "Plan metadata never becomes an execution status");
  assert.equal(value.items[0].source_status, "needs_recheck", "Configuration movement never becomes withdrawn");
  assert.deepEqual(plain(value.items[0].engineering_configuration), before.items[0].engineering_configuration);
  assert.deepEqual(plain(value.items[0].manufacturing_configuration), before.items[0].manufacturing_configuration);
  assert.equal(value.unavailableCount, 1);
  assert.equal(value.hasMore, false);
});

test("an explicit project-filtered response rejects mixed or wholly different projects", async () => {
  for (const allWrong of [false, true]) {
    const state = world(), other = { ...build(), id: id(999), project_id: id(999) };
    state.builds.items = allWrong ? [other] : [...state.builds.items, other];
    await assert.rejects(readProjectBuilds(state.api, scope));
    assert.equal(state.calls.length, 1);
  }
});

test("an explicit Build selection is revalidated before reading only that Build's current tests", async () => {
  const state = world(), original = clone(state.results);
  const value = await readBuildTestSummary(state.api, scope, build());
  assert.deepEqual(state.calls.map(call => call[0]), [buildPath, resultsPath]);
  assert.equal(value.runs.length, 1);
  assert.equal(value.runs[0].versionId, id(23));
  assert.equal(value.runs[0].revision, 3);
  assert.equal(value.runs[0].requestRevision, 3, "Run keeps its fixed request binding independently of the current request");
  assert.equal(value.runs[0].request.revision, 6, "Current request is separate from Run's originating request revision 3");
  assert.deepEqual(plain(value.runs[0].coverage), { sampleCount: 2, itemCount: 1, pairCount: 2, measuredPairCount: 1, missingPairCount: 1 });
  assert.equal(value.runs[0].runSnapshot.measurements[0].raw_value, measurement().raw_value);
  assert.equal(value.runs[0].runSnapshot.measurements[0].observed_at, date);
  assert.equal(value.runs[0].currentProjection.result, "indeterminate");
  assert.equal(value.unavailableCount, 2);
  assert.deepEqual(state.results, original);
});

test("no selection, invalid UUID or another project's selection never initiates a test read", async () => {
  for (const selected of [null, undefined, { ...build(), project_id: id(99) }]) {
    const state = world();
    await assert.rejects(readBuildTestSummary(state.api, scope, selected));
    assert.equal(state.calls.length, 0);
  }
  const state = world();
  await assert.rejects(readProjectBuilds(state.api, { ...scope, categoryId: "../wrong" }));
  assert.equal(state.calls.length, 0);
});

test("a removed or revised Build blocks test loading instead of choosing another Build", async () => {
  for (const mode of ["removed", "revision"]) {
    const state = world();
    if (mode === "removed") state.builds.items = [{ ...build(), id: id(400) }];
    else state.builds.items[0].revision = 2;
    await assert.rejects(readBuildTestSummary(state.api, scope, build()));
    assert.deepEqual(state.calls.map(call => call[0]), [buildPath]);
  }
});

test("Run current index is authoritative; a newer unindexed historical row never replaces it", async () => {
  const state = world(), historical = run(9);
  historical.is_current = false; historical.current_projection = null;
  state.results.runs.unshift(historical);
  const value = await readBuildTestSummary(state.api, scope, build());
  assert.equal(value.runs[0].revision, 3);
});

test("a projection may bind a real historical version of the same Run with the same basis", async () => {
  const state = world(), previous = run(3, "results_pending"), current = run(4, "reviewed");
  previous.is_current = false;
  state.results.runs = [current, previous];
  state.results.current_by_run[id(20)] = { run_version_id: current.id, revision: 4 };
  const value = await readBuildTestSummary(state.api, scope, build());
  assert.equal(value.runs[0].revision, 4);
  assert.equal(value.runs[0].currentProjection.runVersionId, previous.id);
  assert.equal(value.runs[0].currentProjection.runRevision, 3);
});

test("no current projection remains explicitly absent instead of promoting snapshot results to a saved decision", async () => {
  const state = world();
  state.results.runs[0].current_projection = null;
  const value = await readBuildTestSummary(state.api, scope, build());
  assert.equal(value.runs[0].currentProjection, null);
});

test("history without a current index is counted separately and never shown as the current Run", async () => {
  const state = world();
  state.results.current_by_run = {}; state.results.runs[0].is_current = false;
  const value = await readBuildTestSummary(state.api, scope, build());
  assert.equal(value.runs.length, 0);
  assert.equal(value.unindexedRunCount, 1);
  assert.equal(value.unavailableCount, 2, "No invented addition to the server unavailable count");
});

for (const [name, mutate] of [
  ["current Run index points to missing version", data => { data.current_by_run[id(20)].run_version_id = id(999); }],
  ["current Run index revision differs", data => { data.current_by_run[id(20)].revision = 4; }],
  ["current flag disagrees with index", data => { data.runs[0].is_current = false; }],
  ["current request index version differs", data => { data.current_by_request[id(30)].request_version_id = id(999); }],
  ["current request revision differs", data => { data.current_by_request[id(30)].revision = 7; }],
  ["Run body revision differs", data => { data.runs[0].run_snapshot.revision = 99; }],
  ["Run body logical identity differs", data => { data.runs[0].run_snapshot.id = id(999); }],
  ["Run fixed request revision differs from its body", data => { data.runs[0].run_snapshot.request_revision = 6; }],
  ["Run body product differs", data => { data.runs[0].run_snapshot.scope.product_id = id(999); }],
  ["Run body project differs", data => { data.runs[0].run_snapshot.scope.project_id = id(999); }],
  ["Run body tenant differs from request", data => { data.runs[0].run_snapshot.scope.tenant_id = id(999); }],
  ["Run top Build differs", data => { data.runs[0].build.id = id(999); }],
  ["Run snapshot Build version differs", data => { data.runs[0].run_snapshot.build.revision = 2; }],
  ["fixed engineering differs", data => { data.runs[0].run_snapshot.build.engineering_configuration.id = id(999); }],
  ["fixed manufacturing version differs", data => { data.runs[0].run_snapshot.build.manufacturing_configuration.revision = 99; }],
  ["request project differs", data => { data.requests[0].project_id = id(999); }],
  ["request snapshot Build differs", data => { data.requests[0].request_snapshot.build.id = id(999); }],
  ["request body revision differs", data => { data.requests[0].request_snapshot.revision = 99; }],
  ["projection pointer differs from current basis", data => { data.runs[0].current_projection.basis_sha256 = "b".repeat(64); }],
  ["projection row differs from pointer basis", data => { data.projections[0].basis_sha256 = "b".repeat(64); }],
  ["projection row revision differs", data => { data.projections[0].revision = 2; }],
  ["projection row result differs", data => { data.projections[0].result = "pass"; }],
  ["projection belongs to another Run", data => { data.projections[0].run_id = id(999); }],
  ["projection binds an unavailable version", data => { data.projections[0].run_version_id = id(999); }],
  ["projection bound version number differs", data => { data.projections[0].run_revision = 99; }],
  ["duplicate projection identity", data => { data.projections.push(clone(data.projections[0])); }],
  ["duplicate Run version identity", data => { data.runs.push(clone(data.runs[0])); }],
  ["empty fixed coverage", data => { data.runs[0].run_snapshot.coverage = []; }],
  ["duplicate fixed pair", data => { data.runs[0].run_snapshot.coverage.push(pair(41)); }],
  ["measurement outside fixed coverage", data => { data.runs[0].run_snapshot.measurements[0].coverage = pair(99); }],
  ["duplicate measurement pair", data => { data.runs[0].run_snapshot.measurements.push({ ...measurement(), id: id(99) }); }],
  ["numeric report value would lose original precision", data => { data.runs[0].run_snapshot.measurements[0].raw_value = 12.3; }],
  ["computed result outside fixed coverage", data => { data.runs[0].run_snapshot.computed_results[0].coverage = pair(99); }],
  ["partial return outside fixed coverage", data => { data.runs[0].run_snapshot.partial_returns[0].pending_coverage = [pair(99)]; }],
  ["partial return overlaps returned coverage", data => { data.runs[0].run_snapshot.partial_returns[0].pending_coverage = [pair(41)]; }],
  ["running without actual start", data => { data.runs[0].run_snapshot.actual_start = null; }],
]) test(`inconsistent ${name} fails closed`, async () => {
  const state = world(); mutate(state.results);
  await assert.rejects(readBuildTestSummary(state.api, scope, build()));
});

test("missing rows, malformed list metadata and numeric quantities are not silently rendered as empty", async () => {
  for (const mutate of [data => { data.items = [null]; }, data => { delete data.unavailable_count; }, data => { data.has_more = "false"; }, data => { data.items[0].planned_quantity = 100; }, data => { data.items[0].planned_start = "2026-10-17T12:34:56"; }]) {
    const state = world(); mutate(state.builds);
    await assert.rejects(readProjectBuilds(state.api, scope));
  }
});

test("quantity validation rejects nonpositive or invalid decimals without rounding valid strings", async () => {
  for (const quantity of ["0", "0.00000000", "-1", "-0.1", "NaN", "Infinity", "1.2.3", "", " 1", "1e3"]) {
    const state = world(); state.builds.items[0].planned_quantity = quantity;
    await assert.rejects(readProjectBuilds(state.api, scope));
  }
  const state = world(); state.builds.items[0].planned_quantity = "0.00000001";
  assert.equal((await readProjectBuilds(state.api, scope)).items[0].planned_quantity, "0.00000001");
});

test("a permission/source failure propagates and produces no stale or partial summary", async () => {
  const state = world(), failure = { status: 403, message: "Source no longer readable" };
  state.fail = { path: "verification-results", error: failure };
  await assert.rejects(readBuildTestSummary(state.api, scope, build()), error => error === failure);
  assert.deepEqual(state.calls.map(call => call[0]), [buildPath, resultsPath]);
});

test("empty complete test read and server partial coverage remain distinguishable", async () => {
  const state = world(); state.results = { requests: [], runs: [], projections: [], current_by_run: {}, current_by_request: {}, unavailable_count: 0, has_more: false };
  let value = await readBuildTestSummary(state.api, scope, build());
  assert.equal(value.runs.length, 0); assert.equal(value.unavailableCount, 0); assert.equal(value.unindexedRunCount, 0);
  state.results.unavailable_count = 4; state.results.has_more = true;
  value = await readBuildTestSummary(state.api, scope, build());
  assert.equal(value.unavailableCount, 4); assert.equal(value.hasMore, true);
});
