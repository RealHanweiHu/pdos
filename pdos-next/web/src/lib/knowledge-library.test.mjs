import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(extension => filename + extension).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const runtime = new Module(filename); modules.set(filename, runtime);
  runtime.require = name => name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  runtime._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, filename);
  return runtime.exports;
}
const { readKnowledgeLibrary, readKnowledgeLibraryProducts } = load(path.join(directory, "knowledge-library.ts"));
const id = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`, clone = value => structuredClone(value);
const scope = { categoryId: id(1), principalId: id(4), productId: null }, modelScope = { ...scope, productId: id(2) };
const root = `v1/categories/${scope.categoryId}`, at = "2030-10-17T12:34:56.123456+08:00", before = "2030-10-16T12:34:56.654321+08:00";
const source = { kind: "artifact", id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` };
function candidate(n = 6, projectId = id(3)) {
  return { id: id(n), version_id: id(n + 100), revision: 2, project_id: projectId, owner_id: id(9), visibility: "category", title: "合成材料经验",
    lesson: "先核对原件", evidence_summary: "固定证据摘要", applicability_hypothesis: "尚待评估的适用性假设", sources: [clone(source)], result_receipts: [{ receipt_id: id(10) }],
    author_id: id(11), origin: "ai", created_at: at, can_revise: false,
    history: [{ id: id(n + 200), revision: 1, actor_id: id(9), created_at: before, receipt_id: id(n + 300) }, { id: id(n + 100), revision: 2, actor_id: id(11), created_at: at, receipt_id: id(n + 400) }] };
}
function rule() {
  return { id: id(20), version_id: id(21), revision: 1, project_id: id(3), owner_id: id(9), visibility: "category", title: "固定范围经验规则", rule_text: "按原配置和原件执行", nature: "synthetic",
    candidate: { id: id(6), revision: 1 }, candidate_version_id: id(206),
    applicability: { target: { kind: "engineering_configuration", id: id(8), revision: 1 }, purpose: "指定用途", differences: ["原材料差异"], adopted_rule: "原采用规则", conditions: ["原条件"],
      decision: "applicable", rationale: "保存时具名核对", valid_from: at, valid_until: null, candidate_version: { id: id(206), revision: 1 }, assessor_id: id(4), withdrawal_reason: null },
    usability: { state: "needs_recheck", reason_codes: ["source_changed"] }, sources: [clone(source)], author_id: id(4), created_at: at, can_revise: false,
    history: [{ id: id(21), revision: 1, actor_id: id(4), created_at: at, receipt_id: id(22) }] };
}
function categoryView() { return { product_revision: 7, projects: [], configurations: [], candidates: [candidate(6, null)], rules: [], as_of: at }; }
function modelView() {
  return { product_revision: 3, projects: [{ id: id(3), revision: 1, name: "原项目", owner_id: id(9), visibility: "category" }],
    configurations: [{ kind: "engineering_configuration", id: id(8), revision: 2, name: "当前配置名" }],
    candidates: [candidate(), candidate(60, null)], rules: [rule()], as_of: at };
}
function product(n = 2) { return { id: id(n), category_id: scope.categoryId, visibility: "category", name: "已登记型号", purpose: "已登记原用途", revision: 11, status: "draft" }; }
function world() {
  const state = { calls: [], category: categoryView(), model: modelView(), products: [product()], error: null };
  state.api = async (requested, ...body) => {
    assert.equal(body.length, 0, "GET only"); state.calls.push(requested); if (state.error) throw state.error;
    return clone(requested.endsWith("/products") ? state.products : requested === `${root}/experience` ? state.category : state.model);
  };
  return state;
}

test("category is a real nil-product GET and preserves its own positive revision with only category candidates", async () => {
  const state = world(), raw = clone(state.category), value = await readKnowledgeLibrary(state.api, scope);
  assert.deepEqual(state.calls, [`${root}/experience`]); assert.deepEqual(value, raw); assert.equal(value.product_revision, 7);
  assert.equal(value.candidates[0].project_id, null); assert.deepEqual(value.rules, []); assert.deepEqual(state.category, raw);
});
test("products are the unmodified actual seven-field category rows, with no default or automatic experience GET", async () => {
  const state = world(), value = await readKnowledgeLibraryProducts(state.api, scope);
  assert.deepEqual(state.calls, [`${root}/products`]); assert.deepEqual(value, state.products);
  assert.equal(value[0].purpose, "已登记原用途"); assert.equal(value[0].revision, 11); assert.equal(value[0].status, "draft");
});
test("explicit model uses one exact GET without project filtering and keeps category candidates alongside model facts", async () => {
  const state = world(), value = await readKnowledgeLibrary(state.api, modelScope);
  assert.deepEqual(state.calls, [`${root}/products/${modelScope.productId}/experience`]); assert.deepEqual(value, state.model);
  assert.equal(value.candidates.some(row => row.project_id === null), true);
});
test("a rule's old fixed candidate version and old target revision never follow current lists", async () => {
  const state = world(), value = await readKnowledgeLibrary(state.api, modelScope);
  assert.equal(value.candidates[0].revision, 2); assert.equal(value.rules[0].candidate.revision, 1);
  assert.equal(value.rules[0].candidate_version_id, id(206)); assert.equal(value.configurations[0].revision, 2); assert.equal(value.rules[0].applicability.target.revision, 1);
});
test("bounded project/configuration lists may omit a rule's fixed references without invalidating saved facts", async () => {
  const state = world(); state.model.projects = []; state.model.configurations = []; state.model.candidates = [];
  const value = await readKnowledgeLibrary(state.api, modelScope); assert.equal(value.rules.length, 1); assert.equal(value.rules[0].project_id, id(3));
});
for (const usability of ["current", "not_yet_effective", "expired", "needs_recheck"]) test(`server usability ${usability} survives with exact as_of and no local clock recomputation`, async () => {
  const state = world(); state.model.rules[0].usability.state = usability;
  const value = await readKnowledgeLibrary(state.api, modelScope); assert.deepEqual(value.rules[0].usability, state.model.rules[0].usability); assert.equal(value.as_of, at);
});
test("real/synthetic nature, explicit assessment, author/origin and fixed history stay original", async () => {
  const state = world(); state.model.rules[0].nature = "real"; state.model.rules[0].applicability.decision = "not_applicable";
  const value = await readKnowledgeLibrary(state.api, modelScope);
  assert.equal(value.rules[0].nature, "real"); assert.equal(value.rules[0].applicability.decision, "not_applicable");
  assert.equal(value.candidates[0].origin, "ai"); assert.deepEqual(value.candidates[0].history, state.model.candidates[0].history);
  assert.equal(value.rules[0].applicability.valid_until, null); assert.equal(value.rules[0].applicability.assessor_id, id(4));
});
test("empty readable products and knowledge are explicit server values", async () => {
  const state = world(); state.products = []; state.category.candidates = [];
  assert.deepEqual(await readKnowledgeLibraryProducts(state.api, scope), []); assert.deepEqual((await readKnowledgeLibrary(state.api, scope)).candidates, []);
});
test("product list has no invented 100-row cap or revision equality with a later knowledge read", async () => {
  const state = world(); state.products = Array.from({ length: 101 }, (_, i) => product(1000 + i));
  assert.equal((await readKnowledgeLibraryProducts(state.api, scope)).length, 101);
  const view = await readKnowledgeLibrary(state.api, modelScope); assert.equal(view.product_revision, 3);
});
test("each configuration kind may independently return 100 rows without being collapsed", async () => {
  const state = world(); state.model.configurations = ["engineering_configuration", "process_revision"].flatMap((kind, k) => Array.from({ length: 100 }, (_, i) => ({ kind, id: id(1000 + k * 100 + i), revision: 1, name: "原配置名" })));
  assert.equal((await readKnowledgeLibrary(state.api, modelScope)).configurations.length, 200);
});
for (const [name, bad] of [
  ["bad category", { ...scope, categoryId: "bad" }], ["bad principal", { ...scope, principalId: "bad" }],
  ["missing product scope", { categoryId: scope.categoryId, principalId: scope.principalId }], ["empty product", { ...scope, productId: "" }],
  ["bad product", { ...scope, productId: "bad" }], ["unexpected project filter", { ...scope, projectId: id(3) }],
]) test(`${name} is rejected before any request`, async () => {
  const state = world(); await assert.rejects(readKnowledgeLibrary(state.api, bad)); await assert.rejects(readKnowledgeLibraryProducts(state.api, bad)); assert.equal(state.calls.length, 0);
});
for (const [name, mutate] of [
  ["wrong category", state => { state.products[0].category_id = id(90); }],
  ["duplicate product", state => { state.products.push(clone(state.products[0])); }],
  ["missing purpose", state => { delete state.products[0].purpose; }],
  ["bad revision", state => { state.products[0].revision = 0; }],
  ["missing status", state => { delete state.products[0].status; }],
]) test(`product response rejects ${name} rather than inventing an option`, async () => { const state = world(); mutate(state); await assert.rejects(readKnowledgeLibraryProducts(state.api, scope)); });
for (const [name, mutate] of [
  ["project candidate", state => { state.category.candidates[0].project_id = id(3); }],
  ["model projects", state => { state.category.projects = state.model.projects; }],
  ["model configurations", state => { state.category.configurations = state.model.configurations; }],
  ["model rule", state => { state.category.rules = state.model.rules; }],
  ["zero category revision", state => { state.category.product_revision = 0; }],
]) test(`category scope rejects unexpected ${name} without filtering it into an empty result`, async () => { const state = world(); mutate(state); await assert.rejects(readKnowledgeLibrary(state.api, scope)); });
for (const [name, mutate] of [
  ["missing history", state => { state.model.candidates[0].history = []; }],
  ["duplicate candidate", state => { state.model.candidates.push(clone(state.model.candidates[0])); }],
  ["fixed candidate version mismatch", state => { state.model.rules[0].applicability.candidate_version.id = id(90); }],
  ["duplicated history revision", state => { state.model.candidates[0].history[0].revision = 2; }],
  ["history from wrong author", state => { state.model.candidates[0].history[1].actor_id = id(90); }],
  ["history from wrong saved clock", state => { state.model.candidates[0].history[1].created_at = before; }],
  ["history unordered", state => { state.model.candidates[0].history.reverse(); }],
  ["history shared by unrelated candidate", state => { state.model.candidates[1].history[0] = clone(state.model.candidates[0].history[0]); }],
  ["duplicate configuration identity", state => { state.model.configurations.push({ ...state.model.configurations[0], revision: 3 }); }],
  ["missing as_of", state => { delete state.model.as_of; }],
  ["over-returned candidates", state => { state.model.candidates = Array.from({ length: 101 }, (_, i) => candidate(1000 + i * 1000)); }],
]) test(`knowledge read rejects ${name} instead of returning partial facts`, async () => { const state = world(); mutate(state); await assert.rejects(readKnowledgeLibrary(state.api, modelScope)); });
for (const status of [401, 403, 409, 503]) test(`original ${status} failures remain errors for both independent reads`, async () => {
  const state = world(); state.error = Object.assign(new Error("Original API failure"), { status, code: "SOURCE_UNAVAILABLE" });
  await assert.rejects(readKnowledgeLibrary(state.api, scope), error => error === state.error);
  await assert.rejects(readKnowledgeLibraryProducts(state.api, scope), error => error === state.error);
});
