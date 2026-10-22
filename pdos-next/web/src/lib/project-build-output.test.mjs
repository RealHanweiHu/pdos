import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const require = createRequire(import.meta.url), ts = require("typescript");
const compile = name => ts.transpileModule(readFileSync(new URL(name, import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const summary = { exports: {} }, output = { exports: {} };
runInNewContext(compile("./project-build-summary.ts"), { module: summary, exports: summary.exports, URLSearchParams });
runInNewContext(compile("./project-build-output.ts"), {
  module: output, exports: output.exports,
  require: name => { assert.equal(name, "./project-build-summary"); return summary.exports; },
});
const { readProjectBuildOutput } = output.exports;
const id = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3) };
const at = "2026-10-18T12:34:56.123456+00:00", received = "2026-10-18T12:35:56.654321+00:00";
const clone = value => JSON.parse(JSON.stringify(value));
const buildPath = `v1/categories/${scope.categoryId}/products/${scope.productId}/builds?project_id=${scope.projectId}`;
const outputPath = `v1/categories/${scope.categoryId}/products/${scope.productId}/build-execution`;

function build() {
  return { id: id(4), revision: 1, name: "Selected Build", purpose: "Fixed purpose", type: "tool_trial", status: "planned", source_status: "needs_recheck",
    owner_id: id(50), visibility: "category", project_id: scope.projectId, project_name: "Current project", project_revision: 2,
    planned_quantity: "9007199254740993.123456789", unit: "件", planned_start: at, planned_end: null, created_at: at,
    verification_objectives: "Fixed objectives", disposition_plan: "Fixed plan", previous_build_id: null,
    engineering_configuration: { id: id(5), revision: 3, status: "draft", name: "Planned engineering", definition: { id: id(7), revision: 1 }, bom: { id: id(8), revision: 1 }, design_versions: {}, sources: [] },
    manufacturing_configuration: { id: id(6), revision: 4, status: "draft", name: "Planned manufacturing", site: null, line: null, operations: [], sources: [] },
    required_source_read_set: [], readiness: null };
}
function base(identity, status) {
  return { id: id(identity), revision: 1, product_id: scope.productId, project_id: scope.projectId, build_id: id(4), build_revision: 1,
    status, created_at: received, source_status: "needs_recheck", sources: [{ quote: "synthetic source body omitted from summary" }], required_source_read_set: [] };
}
function raw() {
  return {
    actual_configurations: [{ ...base(10, "recorded"), observed_at: at,
      planned_engineering_configuration_id: id(5), planned_manufacturing_configuration_id: id(6),
      actual_engineering_configuration_id: id(15), actual_engineering_revision: 2, actual_manufacturing_configuration_id: id(16), actual_manufacturing_revision: 2,
      planned: { engineering_configuration: { id: id(5), revision: 3, name: "Planned engineering" }, manufacturing_configuration: { id: id(6), revision: 4, name: "Planned manufacturing" } },
      actual: { engineering_configuration: { id: id(15), revision: 2, name: "Actual engineering" }, manufacturing_configuration: { id: id(16), revision: 2, name: "Actual manufacturing", engineering_configuration_id: id(15) } } }],
    lots: [{ ...base(20, "observed"), actual_configuration_id: id(10), actual_configuration_revision: 1, lot_label: "Registered lot",
      observed_unit_count: 10, identified_count: 4, remaining_unit_count: 6, build_observed_unit_count: 10, unit: "件",
      observation: { system: "registered synthetic observation", external_id: "synthetic-lot-01", nature: "synthetic", occurred_at: at, received_at: received } }],
    allocations: [{ ...base(30, "identified"), lot_id: id(20), actual_configuration_id: id(10), unit_count: 4, sample_ids: [id(40), id(41)] }],
    samples: [{ ...base(40, "identified"), label: "Registered sample", lot_id: id(20), allocation_id: id(30), actual_configuration_id: id(10), actual_configuration_revision: 1,
      operation_key: "inspection", cavity: "B", custodian_id: null, custodian_label: null, location: "  original location  ", destination: "登记去向，非实到",
      availability: "unknown", observation_nature: "synthetic", reservation: null, consumption: null }],
    unavailable_count: 5, has_more: true,
  };
}
function world() {
  const state = { calls: [], build: build(), outputs: raw(), fail: null };
  state.builds = { items: [state.build], unavailable_count: 0, has_more: false };
  state.api = async (path, ...body) => {
    state.calls.push([path, body]);
    assert.equal(body.length, 0, "Every output request must be GET-only");
    if (state.fail && path === state.fail.path) throw state.fail.error;
    assert.ok(path === buildPath || path === outputPath, "Only the two existing scoped endpoints are read");
    return clone(path === buildPath ? state.builds : state.outputs);
  };
  return state;
}
const read = state => readProjectBuildOutput(state.api, scope, clone(state.build));

test("fresh Build then product output GET preserve exact registered metadata without source bodies or invented physical state", async () => {
  const state = world(), before = clone(state.outputs), result = clone(await read(state));
  assert.deepEqual(state.calls.map(([path]) => path), [buildPath, outputPath]);
  assert.equal(result.build.planned_quantity, "9007199254740993.123456789");
  assert.equal(result.build.project_revision, 2, "Frozen project version is not compared to an invented current parent version");
  assert.deepEqual(result.actualConfigurations[0].actualManufacturing, { id: id(16), revision: 2, name: "Actual manufacturing" });
  assert.equal(result.actualConfigurations[0].observedAt, at);
  assert.equal(result.lots[0].observation.receivedAt, received);
  assert.equal(result.lots[0].observation.nature, "synthetic");
  assert.equal(result.samples[0].location, "  original location  ");
  assert.equal(result.samples[0].custodianLabel, null);
  assert.equal(result.samples[0].recordedAvailability, "unknown");
  assert.equal(result.samples[0].sourceStatus, "needs_recheck");
  assert.equal(result.productUnavailableCount, 5); assert.equal(result.productHasMore, true);
  assert.deepEqual(state.outputs, before);
  assert.equal("reservation" in result.samples[0], false); assert.equal("consumption" in result.samples[0], false);
  assert.doesNotMatch(JSON.stringify(result.actualConfigurations), /source body|quote|authority/);
});

test("server identification/allocation counts and unresolved sample references remain distinct from readable sample rows", async () => {
  const result = await read(world());
  assert.equal(result.samples.length, 1);
  assert.equal(result.lots[0].identifiedCount, 4); assert.equal(result.lots[0].remainingUnitCount, 6);
  assert.equal(result.allocations[0].unitCount, 4); assert.equal(result.allocations[0].sampleIds.length, 2);
  assert.equal(result.allocations[0].sampleIds[1], id(41));
  assert.equal(result.samples.some(row => row.id === id(41)), false);
});

test("legitimate other project/Build metadata in a product-wide response is ignored", async () => {
  const state = world();
  for (const [key, number] of [["actual_configurations", 110], ["lots", 120], ["allocations", 130], ["samples", 140]]) {
    state.outputs[key].push({ ...clone(state.outputs[key][0]), id: id(number), project_id: id(90), build_id: id(91), build_revision: 5 });
  }
  const result = await read(state);
  for (const key of ["actualConfigurations", "lots", "allocations", "samples"]) assert.equal(result[key].length, 1);
});

test("an empty currently readable set retains product-wide incompleteness without inventing a complete Build total", async () => {
  const state = world(); for (const key of ["actual_configurations", "lots", "allocations", "samples"]) state.outputs[key] = [];
  const value = await read(state);
  assert.equal(value.samples.length, 0); assert.equal(value.productUnavailableCount, 5); assert.equal(value.productHasMore, true);
  assert.equal("totalSamples" in value, false); assert.equal("availableSamples" in value, false);
});

test("reservation/consumption-like raw fields never become SampleUnit facts", async () => {
  const state = world(); state.outputs.samples[0].reservation = { state: "reserved" }; state.outputs.samples[0].consumption = { state: "consumed" };
  const value = await read(state); assert.equal(value.samples[0].recordedAvailability, "unknown");
  assert.equal("reservation" in value.samples[0], false); assert.equal("consumption" in value.samples[0], false);
});

for (const [name, mutate] of [
  ["foreign product row", state => { state.outputs.samples[0].product_id = id(90); }],
  ["selected Build cross-project row", state => { state.outputs.lots[0].project_id = id(90); }],
  ["selected Build revision mismatch", state => { state.outputs.allocations[0].build_revision = 2; }],
  ["unknown source status", state => { state.outputs.samples[0].source_status = "withdrawn"; }],
  ["missing product coverage", state => { delete state.outputs.unavailable_count; }],
  ["unknown metadata status", state => { state.outputs.lots[0].status = "available"; }],
  ["negative count", state => { state.outputs.lots[0].identified_count = -1; }],
  ["inconsistent registration remainder", state => { state.outputs.lots[0].remaining_unit_count = 7; }],
  ["noninteger allocation count", state => { state.outputs.allocations[0].unit_count = 1.5; }],
  ["unit mismatch", state => { state.outputs.lots[0].unit = "台"; }],
  ["clock without timezone", state => { state.outputs.lots[0].observation.received_at = "2026-10-18T12:35:56"; }],
  ["unknown observation nature", state => { state.outputs.samples[0].observation_nature = "assumed"; }],
  ["invented ready availability", state => { state.outputs.samples[0].availability = "ready"; }],
  ["planned configuration revision drift", state => { state.outputs.actual_configurations[0].planned.engineering_configuration.revision = 4; }],
  ["actual configuration revision contradiction", state => { state.outputs.actual_configurations[0].actual_engineering_revision = 3; }],
  ["manufacturing bound to other engineering", state => { state.outputs.actual_configurations[0].actual.manufacturing_configuration.engineering_configuration_id = id(99); }],
  ["lot missing actual parent", state => { state.outputs.actual_configurations = []; }],
  ["lot actual version mismatch", state => { state.outputs.lots[0].actual_configuration_revision = 2; }],
  ["allocation missing lot parent", state => { state.outputs.lots = []; }],
  ["allocation points to other actual", state => { state.outputs.allocations[0].actual_configuration_id = id(99); }],
  ["sample missing allocation parent", state => { state.outputs.allocations = []; }],
  ["sample fixed actual mismatch", state => { state.outputs.samples[0].actual_configuration_revision = 2; }],
  ["sample not in allocation references", state => { state.outputs.allocations[0].sample_ids = [id(41)]; }],
  ["duplicate allocation references", state => { state.outputs.allocations[0].sample_ids.push(id(40)); }],
  ["sample has mismatched observation origin", state => { state.outputs.samples[0].observation_nature = "real"; }],
  ["selected allocation references another Build's visible sample", state => {
    state.outputs.samples.push({ ...clone(state.outputs.samples[0]), id: id(41), build_id: id(92), project_id: id(93) });
  }],
]) test(`rejects ${name} without returning a partial summary`, async () => {
  const state = world(); mutate(state); await assert.rejects(read(state), /固定链/);
});

for (const key of ["actual_configurations", "lots", "allocations", "samples"]) test(`rejects duplicate ${key} identities`, async () => {
  const state = world(); state.outputs[key].push(clone(state.outputs[key][0])); await assert.rejects(read(state), /固定链/);
});

for (const [name, mutate] of [
  ["selection removed", state => { state.builds.items = []; }],
  ["Build revision changed", state => { state.builds.items = [{ ...clone(state.build), revision: 2 }]; }],
  ["fixed configuration identity changed", state => {
    state.builds.items = [{ ...clone(state.build), engineering_configuration: { ...state.build.engineering_configuration, id: id(98) } }];
  }],
]) test(`fresh Build guard: ${name} prevents the output GET`, async () => {
  const state = world(); mutate(state); await assert.rejects(read(state)); assert.deepEqual(state.calls.map(([path]) => path), [buildPath]);
});

test("invalid explicit selection never reads any endpoint", async () => {
  const state = world(); await assert.rejects(readProjectBuildOutput(state.api, scope, { ...state.build, id: "" })); assert.equal(state.calls.length, 0);
});
for (const path of [buildPath, outputPath]) test(`API failure keeps its original status at ${path.endsWith("build-execution") ? "output" : "Build"}`, async () => {
  const state = world(), error = Object.assign(new Error("Current permission unavailable"), { status: 403, code: "FORBIDDEN_SCOPE" });
  state.fail = { path, error }; await assert.rejects(read(state), actual => actual === error);
});
