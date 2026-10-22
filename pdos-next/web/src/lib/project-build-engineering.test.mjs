import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const require = createRequire(import.meta.url), ts = require("typescript");
const compile = name => ts.transpileModule(readFileSync(new URL(name, import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText;
const summary = { exports: {} }, engineering = { exports: {} };
runInNewContext(compile("./project-build-summary.ts"), { module: summary, exports: summary.exports, URLSearchParams });
runInNewContext(compile("./project-build-engineering.ts"), { module: engineering, exports: engineering.exports,
  require: name => { assert.equal(name, "./project-build-summary"); return summary.exports; } });
const { readProjectBuildEngineering } = engineering.exports;
const id = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const clone = value => JSON.parse(JSON.stringify(value));
const scope = { categoryId: id(1), productId: id(2), projectId: id(3) };
const at = "2026-10-18T12:34:56.123456+08:00";
const path = `v1/categories/${scope.categoryId}/products/${scope.productId}/builds?project_id=${scope.projectId}`;
const source = { artifact_id: id(50), expected_revision: 2, line: 3, quote: "Synthetic exact source line" };
function snapshot(n) {
  return { id: id(n), product_id: scope.productId, revision: 1, name: `Synthetic ${n}`, status: "draft", visibility: "private",
    owner_id: id(60), created_at: at, sources: [clone(source)], required_source_read_set: [{ artifact_id: source.artifact_id, expected_revision: 2 }], source_status: "current" };
}
function series(n) { return { ...snapshot(n), series_id: id(n), previous_id: null, expected_previous_revision: null, reason: "Synthetic saved reason" }; }
function external(basis = null) {
  return { system: "Synthetic PLM", external_id: "CAD-01", revision: basis ? null : "R2", as_of: basis ? null : at,
    content_sha256: basis ? null : "a".repeat(64), basis };
}
function build() {
  const part = { ...snapshot(9), internal_number: "RD-01", erp_number: null, customer_number: null, mapping_version: null,
    external_design_refs: [external(clone(source))], external_verification: "not_checked", mapping_status: "unknown" };
  const bom = { ...series(8), lines: [
    { key: "known", part_id: part.id, expected_part_revision: 1, part, quantity: "9007199254740993.123456789012", unit: "ea", loss_rate: "0.100000000001", critical: true, notes: null },
    { key: "unknown", part_id: part.id, expected_part_revision: 1, part: clone(part), quantity: null, unit: null, loss_rate: null, critical: false, notes: "Original unknown" },
  ] };
  const config = { ...series(7), definition_id: id(6), definition_revision: 3,
    definition: { id: id(6), revision: 3, title: "Fixed definition", status: "published", visibility: "private", source_status: "current" },
    bom_id: bom.id, bom_revision: 1, bom, design_versions: { mechanical: external(), electronic: external(clone(source)), firmware: null }, external_verification: "not_checked" };
  return { id: id(4), revision: 1, name: "Selected Build", purpose: "Fixed purpose", type: "prototype", status: "planned", source_status: "current",
    owner_id: id(60), visibility: "private", project_id: scope.projectId, project_name: "Current project", project_revision: 2,
    planned_quantity: "10", unit: "ea", planned_start: at, planned_end: null, created_at: at, verification_objectives: "Fixed objectives",
    disposition_plan: "Fixed disposition", previous_build_id: null, engineering_configuration: config,
    manufacturing_configuration: { id: id(10), revision: 1, name: "Fixed process", status: "draft" },
    required_source_read_set: [{ artifact_id: source.artifact_id, expected_revision: 2 }], readiness: null };
}
function world() {
  const state = { selected: build(), calls: [], error: null };
  state.page = { items: [clone(state.selected)], unavailable_count: 4, has_more: true };
  state.api = async (requested, ...body) => {
    state.calls.push(requested); assert.equal(body.length, 0); assert.equal(requested, path);
    if (state.error) throw state.error;
    return clone(state.page);
  };
  return state;
}
const read = state => readProjectBuildEngineering(state.api, scope, clone(state.selected));

test("one fresh project-only GET preserves complete fixed configuration, source references, nulls and exact decimal strings", async () => {
  const state = world(), before = clone(state.page), result = clone(await read(state));
  assert.deepEqual(state.calls, [path]); assert.deepEqual(result.build, state.page.items[0]);
  assert.deepEqual(result.configuration, state.page.items[0].engineering_configuration);
  assert.deepEqual(state.page, before);
  assert.equal(result.unavailableCount, 4); assert.equal(result.hasMore, true);
  assert.equal(result.configuration.bom.lines[0].quantity, "9007199254740993.123456789012");
  assert.equal(result.configuration.bom.lines[0].loss_rate, "0.100000000001");
  assert.equal(result.configuration.bom.lines[1].quantity, null);
  assert.equal(result.configuration.created_at, at);
  assert.equal(result.configuration.external_verification, "not_checked");
  for (const absent of ["latest", "drift", "flashed", "released", "qualified", "demand", "inventory", "interfaces"]) assert.equal(absent in result, false);
});

test("both external-reference alternatives and a partially supplied metadata set are legal without inventing missing versions", async () => {
  const state = world(), config = state.page.items[0].engineering_configuration;
  config.design_versions.firmware = { ...external(clone(source)), revision: "fw-0.7.3" };
  const result = await read(state);
  assert.equal(result.configuration.design_versions.mechanical.basis, null);
  assert.equal(result.configuration.design_versions.electronic.revision, null);
  assert.equal(result.configuration.design_versions.electronic.as_of, null);
  assert.equal(result.configuration.design_versions.electronic.content_sha256, null);
  assert.equal(result.configuration.design_versions.firmware.revision, "fw-0.7.3");
  assert.equal(result.configuration.design_versions.firmware.as_of, null);
});

test("all design slots may remain null and source recheck does not force latest or source-withdrawn conclusions", async () => {
  const state = world(), config = state.page.items[0].engineering_configuration;
  config.design_versions = { mechanical: null, electronic: null, firmware: null };
  config.source_status = "needs_recheck"; config.definition.source_status = "needs_recheck";
  const result = await read(state);
  assert.equal(result.configuration.source_status, "needs_recheck");
  assert.equal(result.configuration.design_versions.firmware, null);
});

test("same Part may occur on different BOM rows and known loss zero remains an original string", async () => {
  const state = world(); state.page.items[0].engineering_configuration.bom.lines[0].loss_rate = "0";
  const result = await read(state); assert.equal(result.configuration.bom.lines.length, 2);
  assert.equal(result.configuration.bom.lines[0].part_id, result.configuration.bom.lines[1].part_id);
  assert.equal(result.configuration.bom.lines[0].loss_rate, "0");
});

test("legal scientific Decimal strings preserve their signs, exponent and precision without binary conversion", async () => {
  const state = world(), line = state.page.items[0].engineering_configuration.bom.lines[0];
  line.quantity = "+9.007199254740993123456789012E+15"; line.loss_rate = "1.00000000001e-1";
  const result = await read(state);
  assert.equal(result.configuration.bom.lines[0].quantity, line.quantity);
  assert.equal(result.configuration.bom.lines[0].loss_rate, line.loss_rate);
});

test("legal old engineering/BOM series versions and frozen project revision do not require a latest-head lookup", async () => {
  const state = world();
  for (const row of [state.selected, state.page.items[0]]) {
    const config = row.engineering_configuration;
    Object.assign(config, { revision: 2, series_id: id(70), previous_id: id(70), expected_previous_revision: 1 });
    Object.assign(config.bom, { revision: 3, series_id: id(80), previous_id: id(81), expected_previous_revision: 2 });
    config.bom_revision = 3;
  }
  const result = await read(state);
  assert.equal(result.build.project_revision, 2); assert.equal(result.configuration.revision, 2);
  assert.equal(result.configuration.bom.revision, 3); assert.deepEqual(state.calls, [path]);
});

for (const [name, mutate] of [
  ["selection no longer readable", state => { state.page.items = []; }],
  ["Build version changed", state => { state.page.items[0].revision = 2; }],
  ["frozen project binding changed", state => { state.page.items[0].project_revision = 3; }],
  ["fixed engineering identity changed", state => { state.page.items[0].engineering_configuration.id = id(90); state.page.items[0].engineering_configuration.series_id = id(90); }],
  ["fixed manufacturing changed", state => { state.page.items[0].manufacturing_configuration.id = id(90); }],
  ["foreign project returned by scoped list", state => { state.page.items[0].project_id = id(90); }],
  ["engineering product mismatch", state => { state.page.items[0].engineering_configuration.product_id = id(90); }],
  ["definition fixed version contradiction", state => { state.page.items[0].engineering_configuration.definition.revision = 4; }],
  ["BOM fixed identity contradiction", state => { state.page.items[0].engineering_configuration.bom.id = id(90); }],
  ["BOM product mismatch", state => { state.page.items[0].engineering_configuration.bom.product_id = id(90); }],
  ["Part fixed revision contradiction", state => { state.page.items[0].engineering_configuration.bom.lines[0].part.revision = 2; }],
  ["Part product mismatch", state => { state.page.items[0].engineering_configuration.bom.lines[0].part.product_id = id(90); }],
  ["duplicate BOM line key", state => { state.page.items[0].engineering_configuration.bom.lines[1].key = "known"; }],
  ["numeric binary quantity", state => { state.page.items[0].engineering_configuration.bom.lines[0].quantity = 1.1; }],
  ["zero known quantity", state => { state.page.items[0].engineering_configuration.bom.lines[0].quantity = "0.000"; }],
  ["zero with a nonzero exponent", state => { state.page.items[0].engineering_configuration.bom.lines[0].quantity = "0e99"; }],
  ["negative loss rate", state => { state.page.items[0].engineering_configuration.bom.lines[0].loss_rate = "-0.1"; }],
  ["known quantity without unit", state => { state.page.items[0].engineering_configuration.bom.lines[0].unit = null; }],
  ["basis-free external metadata incomplete", state => { state.page.items[0].engineering_configuration.design_versions.mechanical.as_of = null; }],
  ["basis missing fixed source version", state => { delete state.page.items[0].engineering_configuration.design_versions.electronic.basis.expected_revision; }],
  ["external timestamp without zone", state => { state.page.items[0].engineering_configuration.design_versions.mechanical.as_of = "2026-10-18T12:34:56"; }],
  ["source missing required fixed read", state => { state.page.items[0].engineering_configuration.required_source_read_set = []; }],
  ["duplicate read-set identity", state => { state.page.items[0].engineering_configuration.required_source_read_set.push(clone(state.page.items[0].engineering_configuration.required_source_read_set[0])); }],
  ["missing design slot", state => { delete state.page.items[0].engineering_configuration.design_versions.firmware; }],
  ["unknown source status", state => { state.page.items[0].engineering_configuration.source_status = "withdrawn"; }],
  ["unproven external verification", state => { state.page.items[0].engineering_configuration.external_verification = "verified"; }],
  ["missing configuration snapshot fields", state => { delete state.page.items[0].engineering_configuration.bom.lines; }],
]) test(`rejects ${name} without returning stale or partial configuration`, async () => {
  const state = world(); mutate(state); await assert.rejects(read(state)); assert.deepEqual(state.calls, [path]);
});

test("a new definition/BOM cannot silently replace the selected configuration's fixed bindings", async () => {
  const state = world(), config = state.page.items[0].engineering_configuration;
  config.definition_id = config.definition.id = id(90);
  await assert.rejects(read(state), /固定工程配置/);
});

test("invalid explicit selection is rejected before any GET", async () => {
  const state = world(); state.selected.project_id = id(99);
  await assert.rejects(read(state)); assert.equal(state.calls.length, 0);
});

for (const status of [401, 403, 409, 503]) test(`original HTTP ${status} propagates unchanged without fallback`, async () => {
  const state = world(), error = Object.assign(new Error("Actual read unavailable"), { status, code: "SOURCE_UNAVAILABLE" });
  state.error = error; await assert.rejects(read(state), actual => actual === error); assert.deepEqual(state.calls, [path]);
});
