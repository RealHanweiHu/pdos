import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const require = createRequire(import.meta.url), ts = require("typescript");
const compile = name => ts.transpileModule(readFileSync(new URL(name, import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const contract = { exports: {} }, parser = { exports: {} };
runInNewContext(compile("../components/manufacturing-preparation/manufacturing-preparation-contract.ts"), { module: contract, exports: contract.exports });
runInNewContext(compile("./project-build-readiness.ts"), { module: parser, exports: parser.exports,
  require: name => { assert.equal(name, "../components/manufacturing-preparation/manufacturing-preparation-contract"); return contract.exports; },
});
const { parseProjectBuildReadiness } = parser.exports;
const id = number => `00000000-0000-4000-8000-${number.toString(16).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3) };
const at = "2026-10-17T18:55:53.897642Z";
const clone = value => JSON.parse(JSON.stringify(value));
const issue = () => ({ code: "incomplete_supply_scope", kind: "missing", path: "supply_snapshot", message: "Relevant pools may be missing" });
const fixedSource = (kind, identity) => ({ kind, id: id(identity), revision: 1 });
const supplyRef = (kind, identity) => ({ source_id: `${kind}:${id(identity)}`, version: "1", sha256: "b".repeat(64), captured_at: at, valid_until: null, state: "current" });
function savedBuild() {
  const build = { id: id(4), revision: 1, project_id: scope.projectId, project_revision: 3, name: "Synthetic fixed Build",
    project_name: "Current project name", status: "planned", source_status: "current", planned_quantity: "10.00000000", unit: "ea",
    engineering_configuration: { id: id(5), product_id: scope.productId, revision: 1, name: "Fixed engineering", status: "draft" },
    manufacturing_configuration: { id: id(6), product_id: scope.productId, revision: 1, name: "Fixed process", status: "draft" } };
  const snapshot = identity => ({ id: id(identity), revision: 1, created_at: at, source_state: "current", valid_until: null, metadata: {} });
  const demand = { item_id: "motor", material_id: id(8), unit: "ea", critical: true, ancestry: [],
    quantity_per_product: "2.2", required_quantity: "22.000000000", issues: [] };
  const basis = { schema_version: "supply-cost-input.v1",
    build: { build_id: build.id, ref: supplyRef("build", 4), quantity: build.planned_quantity, product_unit: "ea" },
    bom: { ref: supplyRef("bom", 7), engineering_configuration: supplyRef("configuration", 5), items: [
      { item_id: "motor", parent_item_id: null, material_id: id(8), quantity_per_parent: "2", unit: "ea", loss_rate: "0.1", supply_required: true, critical: true },
    ] } };
  build.readiness = { id: id(9), revision: 1, status: "blocked", is_current: true,
    result: { schema_version: "build-readiness-result.v1", algorithm: "fixed-build-readiness.v1", as_of: at,
      input_sha256: "a".repeat(64), build_id: build.id, build_revision: build.revision,
      status: "unknown", ready: null, hard_blocking: true,
      input_snapshot: { schema_version: "build-readiness-input.v1", as_of: at,
        build: { ...snapshot(4), quantity: build.planned_quantity, unit: "ea", metadata: { project_id: build.project_id, project_revision: 3, name: "Saved project context", historical_unknown: null } },
        engineering_configuration: { ...snapshot(5), definition_id: id(10), bom: { ...snapshot(7), lines: [
          { key: "motor", part_id: id(8), quantity: "2", unit: "ea", loss_rate: "0.1", critical: true, metadata: { notes: null } },
        ] } },
        manufacturing_configuration: { ...snapshot(6), operations: [{ key: "assembly", acceptance_criterion: null }] } },
      checks: [{ key: "material_demand", label: "物料需求量", status: "known", blocking: false,
        reason_code: "DEMAND_COMPUTED", message: "需求不证明库存或到货", recovery_action: "核对固定范围", issues: [],
        source_refs: [fixedSource("build", 4), fixedSource("engineering_configuration", 5), fixedSource("bom", 7)] }],
      demands: [demand],
      coverage: { schema_version: "supply-coverage-result.v1", algorithm: "fixed-bom-shared-pool.v1",
        input_sha256: "c".repeat(64), input_snapshot: { as_of: at, basis, pools: [], reservations: [], alternates: [],
          supply_scope_complete: false, supply_snapshot: { ...supplyRef("unconnected", 11), source_id: "unconnected-supply", version: "unconnected.v1", state: "unknown" } },
        secured_ready: null, potential_ready: null, critical_secured_ready: null,
        candidate_policy: "critical-then-item-primary-then-alternate.v1", potential_is_feasibility_proof: false,
        lines: [{ demand: clone(demand), known_secured_quantity: "0", known_potential_quantity: "0", secured_gap: null, potential_gap: null,
          secured_ready: null, potential_ready: null, uses: [], issues: [] }], pools: [], issues: [issue()], notice: "Snapshot calculation only" },
      notice: "准备检查不占用库存、不批准开工、不代替专业放行。", saved_extra: { original: "原metadata", missing: null } } };
  return build;
}
const read = build => parseProjectBuildReadiness(build, scope);
function freeze(value) {
  if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); }
  return value;
}

test("pure parsing returns the entire saved wrapper by identity without modifying hidden metadata or original Decimal/null values", () => {
  const build = freeze(savedBuild()), before = clone(build), result = read(build);
  assert.equal(result, build.readiness); assert.deepEqual(build, before);
  assert.equal(result.status, "blocked"); assert.equal(result.result.status, "unknown");
  assert.equal(result.result.as_of, at); assert.equal(result.result.input_snapshot.build.metadata.project_revision, 3);
  assert.equal(result.result.demands[0].required_quantity, "22.000000000");
  assert.equal(result.result.coverage.lines[0].known_secured_quantity, "0");
  assert.equal(result.result.coverage.lines[0].secured_gap, null);
  assert.deepEqual(result.result.saved_extra, { original: "原metadata", missing: null });
});

test("a genuinely absent saved check is null, not a fabricated result or an empty status", () => {
  const build = savedBuild(); build.readiness = null; assert.equal(read(build), null);
});

test("saved historical source state and is_current false remain readable without a clock or current-state eligibility rule", () => {
  const build = savedBuild(); build.readiness.is_current = false; build.source_status = "needs_recheck";
  build.readiness.result.input_snapshot.build.source_state = "withdrawn";
  build.readiness.result.input_snapshot.build.metadata.name = "Name at calculation time";
  assert.equal(read(build), build.readiness); assert.equal(read(build).is_current, false);
});

test("nullable material mapping, unknown demand, and coverage=null are preserved", () => {
  const build = savedBuild(), demand = build.readiness.result.demands[0];
  Object.assign(demand, { material_id: null, unit: null, required_quantity: null, quantity_per_product: null, ancestry: ["parent"] });
  demand.issues.push({ code: "material_mapping_unknown", path: "motor", kind: "missing", message: "No known mapping" });
  build.readiness.result.coverage = null;
  assert.equal(read(build).result.demands[0], demand); assert.equal(read(build).result.coverage, null);
});

test("zero, scientific notation and high precision derived decimals retain their exact saved strings", () => {
  const build = savedBuild(), result = build.readiness.result;
  result.demands[0].quantity_per_product = "+2.2E+0"; result.demands[0].required_quantity = "9007199254740993.1234567890123456789";
  Object.assign(result.coverage.lines[0], { known_secured_quantity: "0E-12", known_potential_quantity: "2.2000000000001e+1", secured_gap: "0", potential_gap: null });
  assert.equal(read(build).result, result);
});

test("check count is not fixed to seven and server flags/statuses are retained without client evaluation", () => {
  const build = savedBuild(), result = build.readiness.result;
  result.checks.push({ ...clone(result.checks[0]), key: "additional_server_check", status: "unknown", blocking: true, source_refs: [] });
  result.status = "blocked";
  const saved = read(build); assert.equal(saved.result.checks.length, 2); assert.equal(saved.result.status, "blocked");
  assert.equal(saved.result.checks[0].blocking, false); assert.equal(saved.result.ready, null);
});

test("unshown metadata and source-reference additions remain original rather than being projected or defaulted", () => {
  const build = savedBuild(), result = build.readiness.result;
  result.checks[0].source_refs[0].saved_note = "Original reference metadata";
  result.coverage.input_snapshot.original_extra = null;
  result.coverage.lines[0].original_extra = "原值";
  assert.equal(read(build), build.readiness);
  assert.equal(read(build).result.checks[0].source_refs[0].saved_note, "Original reference metadata");
  assert.equal(read(build).result.coverage.lines[0].original_extra, "原值");
});

for (const [name, mutate] of [
  ["malformed category scope", (_b, s) => { s.categoryId = "bad"; }],
  ["malformed product scope", (_b, s) => { s.productId = null; }],
  ["wrong project scope", (_b, s) => { s.projectId = id(70); }],
  ["mixed product configuration", b => { b.engineering_configuration.product_id = id(70); }],
  ["missing wrapper", b => { delete b.readiness; }],
  ["bad wrapper identity", b => { b.readiness.id = "wrong"; }],
  ["bad wrapper revision", b => { b.readiness.revision = 0; }],
  ["unknown wrapper status", b => { b.readiness.status = "ready"; }],
  ["untyped current marker", b => { b.readiness.is_current = "true"; }],
  ["different saved Build", b => { b.readiness.result.build_id = id(70); }],
  ["different saved Build revision", b => { b.readiness.result.build_revision = 2; }],
  ["different input Build revision", b => { b.readiness.result.input_snapshot.build.revision = 2; }],
  ["different snapshot project", b => { b.readiness.result.input_snapshot.build.metadata.project_id = id(70); }],
  ["different frozen project revision", b => { b.readiness.result.input_snapshot.build.metadata.project_revision = 4; }],
  ["different fixed engineering version", b => { b.readiness.result.input_snapshot.engineering_configuration.revision = 2; }],
  ["different fixed manufacturing version", b => { b.readiness.result.input_snapshot.manufacturing_configuration.id = id(70); }],
  ["missing input snapshot", b => { delete b.readiness.result.input_snapshot; }],
  ["unknown result schema", b => { b.readiness.result.schema_version = "build-readiness-result.v2"; }],
  ["unknown algorithm", b => { b.readiness.result.algorithm = "client-guess"; }],
  ["unknown input schema", b => { b.readiness.result.input_snapshot.schema_version = "wrong"; }],
  ["naive as_of", b => { b.readiness.result.as_of = "2026-10-18T12:00:00"; }],
  ["snapshot/result time mismatch", b => { b.readiness.result.input_snapshot.as_of = "2026-10-17T18:55:53Z"; }],
  ["missing saved hash", b => { delete b.readiness.result.input_sha256; }],
  ["non-v1 ready flag", b => { b.readiness.result.ready = true; }],
  ["untyped hard-blocking flag", b => { b.readiness.result.hard_blocking = "true"; }],
  ["duplicate check key", b => { b.readiness.result.checks.push(clone(b.readiness.result.checks[0])); }],
  ["empty saved checks", b => { b.readiness.result.checks = []; }],
  ["unrecognized check status", b => { b.readiness.result.checks[0].status = "pass"; }],
  ["untyped check blocking", b => { b.readiness.result.checks[0].blocking = "false"; }],
  ["missing recovery action", b => { delete b.readiness.result.checks[0].recovery_action; }],
  ["wrong fixed check reference", b => { b.readiness.result.checks[0].source_refs[0].revision = 2; }],
  ["invalid check reference revision", b => { b.readiness.result.checks[0].source_refs[0].revision = 1.1; }],
  ["numeric demand loses Decimal representation", b => { b.readiness.result.demands[0].required_quantity = 22; }],
  ["non-finite demand string", b => { b.readiness.result.demands[0].quantity_per_product = "NaN"; }],
  ["missing nullable mapping instead of explicit unknown", b => { delete b.readiness.result.demands[0].material_id; }],
  ["missing ancestry", b => { delete b.readiness.result.demands[0].ancestry; }],
  ["malformed issue", b => { b.readiness.result.demands[0].issues = [{ code: "x" }]; }],
  ["unknown coverage schema", b => { b.readiness.result.coverage.schema_version = "coverage-guess"; }],
  ["missing coverage input", b => { delete b.readiness.result.coverage.input_snapshot; }],
  ["untyped coverage ready", b => { b.readiness.result.coverage.secured_ready = "unknown"; }],
  ["non-v1 feasibility claim", b => { b.readiness.result.coverage.potential_is_feasibility_proof = true; }],
  ["numeric pool quantity", b => { b.readiness.result.coverage.lines[0].known_secured_quantity = 0; }],
  ["missing gap instead of explicit unknown", b => { delete b.readiness.result.coverage.lines[0].secured_gap; }],
  ["missing pool collection", b => { delete b.readiness.result.coverage.pools; }],
]) {
  test(`rejects ${name} without returning a partial or empty result`, () => {
    const build = savedBuild(), currentScope = clone(scope); mutate(build, currentScope);
    assert.throws(() => parseProjectBuildReadiness(build, currentScope), /固定版本无法核对/);
  });
}

test("null still requires the explicit selected Build and project scope to be valid", () => {
  const build = savedBuild(); build.readiness = null;
  assert.throws(() => parseProjectBuildReadiness(build, { ...scope, projectId: id(70) }), /固定版本无法核对/);
});
