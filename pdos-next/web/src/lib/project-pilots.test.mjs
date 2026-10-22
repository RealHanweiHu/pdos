import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../..");
const require = createRequire(path.join(web, "package.json")), ts = require("typescript"), modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(extension => filename + extension).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const runtime = new Module(filename); modules.set(filename, runtime);
  runtime.require = name => name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : require(name);
  runtime._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, filename);
  return runtime.exports;
}
const { readProjectPilots } = load(path.join(directory, "project-pilots.ts"));
const id = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const clone = value => JSON.parse(JSON.stringify(value));
const scope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) };
const at = "2026-10-18T12:34:56.123456+08:00", start = "2026-10-18T12:00:00.654321+08:00", finish = "2026-10-18T13:00:00+08:00";
const source = { kind: "artifact", id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const ref = (kind, n) => ({ kind, id: id(n), revision: 1 });
const basis = { build: ref("build", 6), lot: ref("build_lot", 7), actual_configuration: ref("actual_configuration", 8), engineering_configuration: ref("engineering_configuration", 9), process_revision: ref("process_revision", 10), unit: "ea" };
const boundScope = { tenant_id: id(11), product_id: scope.productId, project_id: scope.projectId };
const conservative = { qualification: "unknown", start_authorized: false, manufacturing_release: null, external_delivery: false };
function metadata(n, revision) {
  return { id: id(n), revision, created_at: at, owner_id: id(12), writer_id: id(12), visibility: "private", receipt_id: id(100 + n),
    source_status: "needs_recheck", sources: [clone(source)], required_source_read_set: [{ artifact_id: source.id, expected_revision: 1 }],
    material: { pilot: { scope: clone(boundScope), category_id: scope.categoryId, basis: clone(basis) }, statistics: null, fixed_scope: null },
    gaps: [{ code: "ORIGINAL_SAVED_GAP", detail: "Saved at creation; not current readiness", state: "unknown" }], ...conservative };
}
function counts(complete = false) {
  return { input_count: 4, output_count: 4, first_pass: 2, first_failed: 2, first_unknown: 0, final_good: complete ? 4 : 2,
    reworked_good: complete ? 2 : 0, scrap: 0, rework_pending: complete ? 0 : 2, undecided: 0, unprocessed: 0, rework_cycles: complete ? 2 : 0 };
}
function rate(complete) { return { numerator: complete ? 4 : 2, denominator: 4, value: complete ? "1" : null, recorded_fraction: complete ? "1" : "0.5", partition_complete: complete, state: complete ? "known" : "partial" }; }
function observation(n, revision, previous = null, complete = false) {
  const yieldScope = { basis: clone(basis), manufacturing_baseline: ref("manufacturing_baseline", 13), line: ref("line", 14), cohort_key: "fixed-cohort",
    window_start: start, window_end: finish, criterion: ref("criterion", 15), nature: "synthetic", minimum_sample: 1 };
  const fixed = { schema_version: "pdos-pilot-result-scope-v1", scope: clone(boundScope), pilot_id: id(20), pilot_revision: revision - 1,
    purpose: "Fixed synthetic statistics", site: "Synthetic lab", original_timezone: "Asia/Shanghai", yield_scope: clone(yieldScope),
    cohort: { population_count: 4, fixed_input_count: 4, mode: "entire_lot", denominator_policy: "all_fixed_input_units", statistics_basis_key: "original-statistics", unit_refs: null, source: clone(source) } };
  return { ...metadata(n, revision), pilot_id: id(20), pilot_revision_before: revision - 1, previous_observation_id: previous,
    record: { observation_id: id(n), expected_pilot_revision: revision - 1, previous_observation_id: previous, correction_reason: previous ? "Original correction reason" : null,
      scope: yieldScope, counts: counts(complete), units: [], exceptions: [], observed: { occurred_at: at, original_timezone: "Asia/Shanghai", effective_at: null, source: clone(source) }, source: clone(source) },
    fixed_scope: fixed, projection: { schema_version: "pdos-pilot-result-projection-v1", fixed: clone(fixed), observation_id: id(n), received_at: null,
      counts: counts(complete), metrics: { first_pass_yield: { numerator: 2, denominator: 4, value: "0.5", recorded_fraction: "0.5", partition_complete: true, state: "known" },
        final_good_yield: rate(complete), warnings: complete ? [] : ["FINAL_GOOD_PARTITION_NOT_FINAL"], process_capability: "NOT_ASSESSED", factory_qualification: "NOT_ASSESSED",
        start_authorized: false, manufacturing_release: null, external_delivery_authorized: false } } };
}
function item(withObservations = true) {
  const observations = withObservations ? [observation(21, 2), observation(22, 3, id(21), true)] : [];
  return { schema_version: "pdos-native-pilot-v1", project_id: scope.projectId,
    pilot: { ...metadata(20, 1), details: { pilot_id: id(20), basis: clone(basis), purpose: "Fixed synthetic Pilot", source: clone(source), manufacturing_baseline: null, line: null }, statistics_basis: null },
    current: { revision: observations.length + 1, epoch: observations.length + 1, latest_observation_id: observations.at(-1)?.id ?? null }, observations, ...conservative };
}
function world() {
  const state = { calls: [], error: null, page: { schema_version: "pdos-native-pilot-v1", project_id: scope.projectId,
    items: [item()], next_cursor: null, qualification: "unknown", manufacturing_release: null } };
  state.api = async (requested, ...body) => {
    state.calls.push(requested); assert.equal(body.length, 0); assert.ok(requested.startsWith(`v1/categories/${scope.categoryId}/products/${scope.productId}/pilots?project_id=${scope.projectId}`));
    if (state.error) throw state.error; return clone(state.page);
  };
  return state;
}
const read = state => readProjectPilots(state.api, scope);

test("one project GET returns full unmodified roots, Current and partial/final correction history without percentage derivation", async () => {
  const state = world(), before = clone(state.page), result = await read(state);
  assert.equal(state.calls.length, 1); assert.equal(state.calls[0], `v1/categories/${scope.categoryId}/products/${scope.productId}/pilots?project_id=${scope.projectId}`);
  assert.deepEqual(result.items, state.page.items); assert.deepEqual(state.page, before); assert.equal(result.nextCursor, null);
  const pilot = result.items[0]; assert.equal(pilot.pilot.revision, 1); assert.equal(pilot.current.revision, 3);
  assert.equal(pilot.observations[0].projection.metrics.final_good_yield.value, null);
  assert.equal(pilot.observations[0].projection.metrics.final_good_yield.recorded_fraction, "0.5");
  assert.equal(pilot.observations[1].projection.metrics.final_good_yield.value, "1");
  assert.equal(pilot.observations[1].record.previous_observation_id, pilot.observations[0].id);
  assert.equal(pilot.observations[0].record.observed.occurred_at, at); assert.equal(pilot.observations[0].fixed_scope.yield_scope.window_start, start);
  assert.equal(pilot.observations[0].projection.received_at, null); assert.equal(pilot.pilot.created_at, at);
  assert.equal("totalYield" in result, false); assert.equal("percentage" in result, false); assert.equal("ready" in result, false);
});
test("a root without observations is a complete readable record without inventing statistics", async () => {
  const state = world(); state.page.items = [item(false)]; const result = await read(state);
  assert.equal(result.items[0].current.revision, 1); assert.equal(result.items[0].current.latest_observation_id, null);
  assert.equal(result.items[0].pilot.statistics_basis, null); assert.deepEqual(result.items[0].observations, []);
});
test("retained fixed scope with no projection and wholly unknown scope/projection are both legal", async () => {
  const state = world(); state.page.items[0].observations[0].projection = null;
  state.page.items[0].observations[1].fixed_scope = null; state.page.items[0].observations[1].projection = null;
  const result = await read(state); assert.ok(result.items[0].observations[0].fixed_scope);
  assert.equal(result.items[0].observations[0].projection, null); assert.equal(result.items[0].observations[1].fixed_scope, null);
});
test("original unknown integer counts and scientific decimal rate strings are retained without repairing them", async () => {
  const state = world(), row = state.page.items[0].observations[0];
  row.record.counts.input_count = null; row.projection.counts.input_count = null;
  row.projection.metrics.first_pass_yield.value = "5.000000000000000000000000E-1";
  const result = await read(state); assert.equal(result.items[0].observations[0].record.counts.input_count, null);
  assert.equal(result.items[0].observations[0].projection.metrics.first_pass_yield.value, "5.000000000000000000000000E-1");
});
test("explicit cursor is forwarded once, retained unchanged, and never triggers per-Pilot detail reads", async () => {
  const state = world(); state.page.next_cursor = state.page.items[0].pilot.id;
  const result = await readProjectPilots(state.api, scope, id(99));
  assert.equal(result.nextCursor, id(20)); assert.equal(state.calls.length, 1);
  assert.equal(state.calls[0], `v1/categories/${scope.categoryId}/products/${scope.productId}/pilots?project_id=${scope.projectId}&history_cursor=${id(99)}`);
});
test("actual empty page remains empty without a fabricated total or current-maturity result", async () => {
  const state = world(); state.page.items = []; assert.deepEqual(await read(state), { items: [], nextCursor: null });
});
for (const key of ["categoryId", "productId", "projectId", "principalId"]) test(`invalid ${key} fails before transport`, async () => {
  const state = world(); await assert.rejects(readProjectPilots(state.api, { ...scope, [key]: "bad" })); assert.equal(state.calls.length, 0);
});
test("invalid cursors fail before transport", async () => {
  const state = world(); for (const cursor of [null, "", "bad", 3]) await assert.rejects(readProjectPilots(state.api, scope, cursor));
  assert.equal(state.calls.length, 0);
});
for (const [name, mutate] of [
  ["top schema", state => { state.page.schema_version = "other"; }],
  ["top project", state => { state.page.project_id = id(99); }],
  ["item project", state => { state.page.items[0].project_id = id(99); }],
  ["material product", state => { state.page.items[0].pilot.material.pilot.scope.product_id = id(99); }],
  ["material category", state => { state.page.items[0].pilot.material.pilot.category_id = id(99); }],
  ["duplicate Pilot identity", state => { state.page.items.push(clone(state.page.items[0])); }],
  ["Current epoch", state => { state.page.items[0].current.epoch = 4; }],
  ["Current latest observation", state => { state.page.items[0].current.latest_observation_id = id(99); }],
  ["observation parent", state => { state.page.items[0].observations[1].pilot_id = id(99); }],
  ["observation duplicate identity", state => { state.page.items[0].observations[1].id = id(21); }],
  ["wrong previous observation", state => { state.page.items[0].observations[1].previous_observation_id = id(99); }],
  ["record previous mismatch", state => { state.page.items[0].observations[1].record.previous_observation_id = null; }],
  ["missing correction reason", state => { state.page.items[0].observations[1].record.correction_reason = null; }],
  ["record basis from other Build", state => { state.page.items[0].observations[0].record.scope.basis.build.id = id(99); }],
  ["missing fixed scope field", state => { delete state.page.items[0].observations[0].fixed_scope; }],
  ["projection without fixed scope", state => { state.page.items[0].observations[0].fixed_scope = null; }],
  ["projection observation identity", state => { state.page.items[0].observations[0].projection.observation_id = id(99); }],
  ["fixed scope project", state => { state.page.items[0].observations[0].fixed_scope.scope.project_id = id(99); }],
  ["projection fixed scope contradiction", state => { state.page.items[0].observations[0].projection.fixed.pilot_revision = 2; }],
  ["missing original count", state => { delete state.page.items[0].observations[0].projection.counts.first_unknown; }],
  ["negative projection count", state => { state.page.items[0].observations[0].projection.counts.first_pass = -1; }],
  ["binary numeric ratio", state => { state.page.items[0].observations[0].projection.metrics.first_pass_yield.value = 0.5; }],
  ["unknown ratio state", state => { state.page.items[0].observations[0].projection.metrics.final_good_yield.state = "final"; }],
  ["missing partition flag", state => { delete state.page.items[0].observations[0].projection.metrics.final_good_yield.partition_complete; }],
  ["invented pure receive clock", state => { state.page.items[0].observations[0].projection.received_at = at; }],
  ["future qualification claim", state => { state.page.qualification = "qualified"; }],
  ["invented start authorization", state => { state.page.items[0].start_authorized = true; }],
  ["invented publication", state => { state.page.manufacturing_release = { id: id(99) }; }],
  ["missing observation timezone", state => { state.page.items[0].observations[0].record.observed.occurred_at = "2026-10-18T12:34:56"; }],
  ["non-final cursor", state => { state.page.next_cursor = id(99); }],
]) test(`rejects ${name} without partial/defaulted output`, async () => {
  const state = world(); mutate(state); await assert.rejects(read(state));
});
test("a repeated page cursor is rejected rather than silently looping", async () => {
  const state = world(); state.page.next_cursor = id(20); await assert.rejects(readProjectPilots(state.api, scope, id(20)));
});
for (const status of [401, 403, 409, 503]) test(`HTTP ${status} is propagated unchanged instead of becoming empty`, async () => {
  const state = world(), error = Object.assign(new Error("Actual scoped read failed"), { status, code: "SOURCE_UNAVAILABLE" }); state.error = error;
  await assert.rejects(read(state), actual => actual === error); assert.equal(state.calls.length, 1);
});
