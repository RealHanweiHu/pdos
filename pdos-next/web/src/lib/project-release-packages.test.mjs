import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Load actual production readers and their parsers. Only transport is replaced.
const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../..");
const require = createRequire(path.join(web, "package.json")), ts = require("typescript"), loaded = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(extension => filename + extension).find(existsSync);
  if (loaded.has(filename)) return loaded.get(filename).exports;
  const runtimeModule = new Module(filename); loaded.set(filename, runtimeModule);
  runtimeModule.require = name => name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : require(name);
  runtimeModule._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
  return runtimeModule.exports;
}
const { readProjectReleasePackages, readProjectReleasePackage } = load(path.join(directory, "project-release-packages.ts"));
const id = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const clone = value => JSON.parse(JSON.stringify(value));
const scope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) };
const root = `v1/categories/${scope.categoryId}/products/${scope.productId}/release-packages`;
const selected = { id: id(10), revision: 1 }, current = { id: id(10), version: { id: id(12), revision: 2 }, epoch: 2 };
const source = { kind: "artifact", id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const configuration = { definition: { id: id(6), revision: 3 }, engineering_configuration: { id: id(7), revision: 2 }, manufacturing_configuration: { id: id(8), revision: 4 } };
const range = { quantity: "9007199254740993.123456789012", unit: "ea", lots: null, site: null, lines: [], regions: ["CN"] };
const at = "2026-10-18T12:34:56.123456+08:00";
function assessment(discipline, state) {
  return { discipline, state, checks: [{ key: "synthetic-original-check", state: "unknown", detail: "Original saved assessment", sources: [clone(source)] }],
    blocked: state === "BLOCKED" ? ["Original blocker"] : [], unknown: state === "UNKNOWN" ? ["Original unknown"] : [], conditions: state === "READY_WITH_CONDITIONS" ? [{ id: id(20), revision: 1 }] : [] };
}
function header(ref = selected) {
  return { ...ref, project_id: scope.projectId, purpose: "Fixed synthetic purpose", status: "assembled", receipt_id: id(15), current: clone(current), applicability: "not_checked" };
}
function detail() {
  const boundScope = { tenant_id: id(30), product_id: scope.productId, project_id: scope.projectId };
  const assessments = { engineering: assessment("engineering", "READY_WITH_CONDITIONS"), manufacturing: assessment("manufacturing", "UNKNOWN") };
  const decisions = ["engineering", "manufacturing"].map((discipline, index) => ({
    id: id(40 + index), revision: 1, discipline, package: clone(selected), receipt_id: id(45 + index), applicability: index ? "needs_recheck" : "current",
    authority: { subject_id: id(50 + index), scope: clone(boundScope), roles: [discipline], authorized: false, qualified: false },
    decision: { structural_only: true, status: "unexecuted_candidate", operation: `release.${discipline}.approve`, discipline,
      package: clone(selected), package_sha256: "c".repeat(64), scope: clone(boundScope), category_id: scope.categoryId,
      subject_config: clone(configuration), release_scope: clone(range), purpose: "Fixed synthetic purpose", policy_version: "original-policy-v1",
      signers: [id(50 + index)], expiry: null, prepared_at: at, limits: [{ text: "Original retained limit", sources: [clone(source)] }],
      input_snapshot: { expiry: null, sources: [clone(source)], reason: "Original named intent" }, evidence_digest: "d".repeat(64),
      assessment: assessment(discipline, index ? "READY" : "READY_WITH_CONDITIONS"), customer_acceptance: null, external_received: false, external_effective: false },
  }));
  return { ...header(), applicability: "needs_recheck", package: { structural_only: true, status: "unexecuted_candidate", scope: boundScope,
    category_id: scope.categoryId, product_revision: 7, owner_id: id(60), declaration: { project_id: scope.projectId, subject_config: clone(configuration), release_scope: clone(range), purpose: "Fixed synthetic purpose",
      reason: "Original saved package", sources: [clone(source)], previous: null, documents: [], limits: [] },
    objects: [{ ref: { kind: "definition", ...configuration.definition }, product_id: scope.productId, project_id: null, sha256: "b".repeat(64) }],
    policy: null, checks: [], exceptions: [], sources: [clone(source)], required_source_read_set: [{ artifact_id: source.id, expected_revision: 1 }], evidence_digest: "a".repeat(64), body_sha256: "b".repeat(64) },
    assessments, decisions };
}
function world() {
  const state = { calls: [], list: { items: [header(), header(current.version)], next_cursor: current.version.id }, detail: detail(), error: null };
  state.api = async (requested, ...body) => {
    assert.equal(body.length, 0, "All requests must be GET-only"); state.calls.push(requested);
    if (state.error) throw state.error;
    if (requested.startsWith(`${root}?`)) return clone(state.list);
    assert.equal(requested, `${root}/${selected.id}`); return clone(state.detail);
  };
  return state;
}

test("project-only list retains original header states and marks current only among returned rows", async () => {
  const state = world(), original = clone(state.list), result = await readProjectReleasePackages(state.api, scope);
  assert.deepEqual(state.calls, [`${root}?project_id=${scope.projectId}`]);
  assert.deepEqual(result.items.map(row => row.isSeriesCurrent), [false, true]);
  assert.equal(result.items[0].applicability, "not_checked"); assert.equal(result.nextCursor, current.version.id);
  assert.deepEqual(state.list, original); assert.equal("total" in result, false); assert.equal("approved" in result, false);
});
test("a returned historical row can point to a current version outside the page without a follow-up GET", async () => {
  const state = world(); state.list = { items: [header()], next_cursor: selected.id };
  const result = await readProjectReleasePackages(state.api, scope, id(99));
  assert.equal(result.items[0].isSeriesCurrent, false); assert.equal(result.nextCursor, selected.id);
  assert.deepEqual(state.calls, [`${root}?project_id=${scope.projectId}&history_cursor=${id(99)}`]);
});
test("an actual empty last page is distinct from a failed read", async () => {
  const state = world(); state.list = { items: [], next_cursor: null };
  assert.deepEqual(await readProjectReleasePackages(state.api, scope), { items: [], nextCursor: null });
});
test("explicit historical package keeps the complete original detail and two independent assessment states", async () => {
  const state = world(), before = clone(state.detail), result = await readProjectReleasePackage(state.api, scope, selected);
  assert.deepEqual(state.calls, [`${root}/${selected.id}`]); assert.deepEqual(result.detail, before);
  assert.equal(result.isSeriesCurrent, false); assert.deepEqual(result.assessments.map(row => row.state), ["READY_WITH_CONDITIONS", "UNKNOWN"]);
  assert.equal(result.detail.applicability, "needs_recheck"); assert.equal(result.detail.decisions[0].applicability, "current");
  assert.equal(result.detail.decisions[1].applicability, "needs_recheck"); assert.equal(result.detail.decisions[0].decision.expiry, null);
  assert.equal(result.detail.decisions[0].decision.prepared_at, at); assert.equal(result.detail.package.declaration.release_scope.quantity, range.quantity);
  assert.equal(result.detail.package.declaration.release_scope.lots, null); assert.deepEqual(state.detail, before);
  assert.equal("canApprove" in result, false); assert.equal("signed_at" in result.detail.decisions[0], false);
});
test("array-shaped assessments preserve original order and raw detail while null expiry stays legal", async () => {
  const state = world(); state.detail.assessments = [state.detail.assessments.manufacturing, state.detail.assessments.engineering];
  state.detail.decisions[1].decision.expiry = "2099-01-01T00:00:00.123456Z";
  const result = await readProjectReleasePackage(state.api, scope, { ...header(), ...selected });
  assert.deepEqual(result.assessments.map(row => row.discipline), ["manufacturing", "engineering"]);
  assert.deepEqual(result.detail.assessments, state.detail.assessments);
  assert.equal(result.detail.decisions[0].decision.expiry, null); assert.equal(result.detail.decisions[1].decision.expiry, "2099-01-01T00:00:00.123456Z");
});
test("assembled package without any decision is readable and a current-series pointer grants no approval", async () => {
  const state = world(); state.detail.current = { id: selected.id, version: clone(selected), epoch: 1 }; state.detail.decisions = [];
  const result = await readProjectReleasePackage(state.api, scope, selected);
  assert.equal(result.isSeriesCurrent, true); assert.equal(result.detail.decisions.length, 0);
  assert.equal(result.detail.applicability, "needs_recheck");
});

for (const key of ["categoryId", "productId", "projectId", "principalId"]) test(`invalid ${key} rejects both reads before transport`, async () => {
  const state = world(), badScope = { ...scope, [key]: "bad" };
  await assert.rejects(readProjectReleasePackages(state.api, badScope));
  await assert.rejects(readProjectReleasePackage(state.api, badScope, selected)); assert.equal(state.calls.length, 0);
});
test("malformed cursors and explicit selected versions never reach transport", async () => {
  const state = world();
  for (const cursor of [null, "", "bad", 1]) await assert.rejects(readProjectReleasePackages(state.api, scope, cursor));
  for (const choice of [null, {}, { id: "bad", revision: 1 }, { id: selected.id, revision: 0 }]) await assert.rejects(readProjectReleasePackage(state.api, scope, choice));
  assert.equal(state.calls.length, 0);
});
for (const [name, mutate] of [
  ["foreign project", state => { state.list.items[0].project_id = id(99); }],
  ["missing purpose", state => { delete state.list.items[0].purpose; }],
  ["unknown package status", state => { state.list.items[0].status = "approved"; }],
  ["duplicate identities", state => { state.list.items.push(clone(state.list.items[0])); }],
  ["contradictory current pointer", state => { state.list.items[0].current.epoch = 3; }],
  ["same-revision different current identity", state => { state.list.items[1].current.version.id = id(99); }],
  ["next cursor not the final row", state => { state.list.next_cursor = selected.id; }],
  ["malformed cursor response", state => { state.list.next_cursor = "bad"; }],
  ["missing item collection", state => { delete state.list.items; }],
]) test(`list rejects ${name} without a partial or empty fallback`, async () => {
  const state = world(); mutate(state); await assert.rejects(readProjectReleasePackages(state.api, scope));
});
test("a repeated next cursor is rejected instead of looping", async () => {
  const state = world(); await assert.rejects(readProjectReleasePackages(state.api, scope, current.version.id));
});
for (const [name, mutate] of [
  ["wrong selected id", state => { state.detail.id = id(99); }],
  ["wrong selected revision", state => { state.detail.revision = 2; }],
  ["wrong project", state => { state.detail.project_id = id(99); }],
  ["wrong package product", state => { state.detail.package.scope.product_id = id(99); }],
  ["wrong package category", state => { state.detail.package.category_id = id(99); }],
  ["not yet checked detail", state => { state.detail.applicability = "not_checked"; }],
  ["only one professional assessment", state => { delete state.detail.assessments.manufacturing; }],
  ["duplicate professional assessments", state => { state.detail.assessments = [state.detail.assessments.engineering, clone(state.detail.assessments.engineering)]; }],
  ["missing preserved package purpose", state => { delete state.detail.package.declaration.purpose; }],
  ["decision bound to another package", state => { state.detail.decisions[0].decision.package.id = id(99); }],
  ["decision bound to another project", state => { state.detail.decisions[0].decision.scope.project_id = id(99); }],
  ["decision bound to another category", state => { state.detail.decisions[0].decision.category_id = id(99); }],
  ["decision duplicate discipline", state => { state.detail.decisions.push(clone(state.detail.decisions[0])); }],
  ["decision missing signers", state => { state.detail.decisions[0].decision.signers = []; }],
  ["decision expiry without timezone", state => { state.detail.decisions[0].decision.expiry = "2099-01-01T00:00:00"; }],
  ["decision missing explicit expiry", state => { delete state.detail.decisions[0].decision.expiry; }],
  ["decision missing preparation instant", state => { delete state.detail.decisions[0].decision.prepared_at; }],
]) test(`fixed detail rejects ${name}`, async () => {
  const state = world(); mutate(state); await assert.rejects(readProjectReleasePackage(state.api, scope, selected));
});
for (const status of [401, 403, 409, 503]) test(`HTTP ${status} propagates unchanged through both reads`, async () => {
  const state = world(), error = Object.assign(new Error("Recorded read failure"), { status, code: "FORBIDDEN_SCOPE" }); state.error = error;
  await assert.rejects(readProjectReleasePackages(state.api, scope), actual => actual === error);
  await assert.rejects(readProjectReleasePackage(state.api, scope, selected), actual => actual === error);
});
