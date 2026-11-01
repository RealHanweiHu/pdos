import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), root = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(root, "package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
const modules = new Map();
function load(filename) { if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) }; if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync); if (modules.has(filename)) return modules.get(filename).exports; const loaded = new Module(filename); modules.set(filename, loaded); loaded.require = name => name.startsWith("@/") ? load(path.join(root, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name); loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename); return loaded.exports; }
const { ProjectBuildReadiness } = load(path.join(directory, "project-build-readiness.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, at = "2026-10-18T12:34:56.123456+08:00";
const scope = { categoryId: id(1), productId: id(2), projectId: id(3) };
const ref = n => ({ id: id(n), revision: 1 });
const issue = () => ({ code: "ORIGINAL_UNKNOWN", kind: "missing", path: "original.path", message: "保存时原未知项" });
function fixture() {
  const build = { ...ref(4), project_id: scope.projectId, project_revision: 3, name: "合成固定Build", project_name: "当前项目名不能代保存版本", status: "planned", source_status: "needs_recheck", planned_quantity: "10.00000000", unit: "ea", engineering_configuration: { ...ref(5), product_id: scope.productId, name: "固定工程", status: "draft" }, manufacturing_configuration: { ...ref(6), product_id: scope.productId, name: "固定制造", status: "draft" } };
  const demand = { item_id: "original-motor", material_id: id(8), unit: "ea", critical: true, ancestry: ["parent-original"], quantity_per_product: "2.2", required_quantity: "22.000000000", issues: [issue()] };
  const checks = ["known", "unknown", "blocked"].map((status, index) => ({ key: `original-${index}`, label: `原检查标签${index}`, status, blocking: status !== "known", reason_code: `ORIGINAL_REASON_${index}`, message: `原保存说明${index}`, recovery_action: `原恢复建议${index}`, source_refs: [{ kind: "build", ...ref(4) }, { kind: "engineering_configuration", ...ref(5) }, { kind: "manufacturing_configuration", ...ref(6) }, { kind: "bom", ...ref(7) }], issues: [issue()] }));
  build.readiness = { ...ref(9), status: "blocked", is_current: true, result: { schema_version: "build-readiness-result.v1", algorithm: "fixed-build-readiness.v1", as_of: at, build_id: build.id, build_revision: 1, status: "unknown", ready: null, hard_blocking: true, checks, demands: [demand], input_sha256: "a".repeat(64), input_snapshot: { schema_version: "build-readiness-input.v1", as_of: at, build: { ...ref(4), metadata: { project_id: scope.projectId, project_revision: 3, private_snapshot: "MUST_NOT_RENDER_HIDDEN_METADATA" } }, engineering_configuration: { ...ref(5), bom: { ...ref(7), secret_lines: "DO_NOT_DUMP_SNAPSHOT" } }, manufacturing_configuration: { ...ref(6), operations: [{ private_authority: "NO_AUTHORITY_DUMP" }] } }, coverage: { schema_version: "supply-coverage-result.v1", algorithm: "fixed-bom-shared-pool.v1", input_sha256: "b".repeat(64), input_snapshot: { private: "COVERAGE_INPUT_MUST_NOT_RENDER" }, secured_ready: null, potential_ready: null, critical_secured_ready: null, candidate_policy: "critical-then-item-primary-then-alternate.v1", potential_is_feasibility_proof: false, lines: [{ demand: structuredClone(demand), known_secured_quantity: "0", known_potential_quantity: "0", secured_gap: null, potential_gap: null, secured_ready: null, potential_ready: null, uses: [], issues: [issue()] }], pools: [], issues: [issue()], notice: "原覆盖说明：保存计算不是供应事实。" }, notice: "原准备说明：不占用库存、不批准开工、不代替专业放行。" } };
  return build;
}
const render = (build = fixture(), selectedScope = scope) => renderToStaticMarkup(React.createElement(ProjectBuildReadiness, { build, scope: selectedScope }));
function collapsedText(tree) { if (typeof tree === "string" || typeof tree === "number") return String(tree); if (!tree || typeof tree !== "object") return ""; if (Array.isArray(tree)) return tree.map(collapsedText).join(""); if (typeof tree.type === "function") return collapsedText(tree.type(tree.props)); return tree.type === "details" ? "" : collapsedText(tree.props?.children); }
function freeze(value) { if (value && typeof value === "object") { Object.values(value).forEach(freeze); Object.freeze(value); } return value; }

test("outer blocked and saved result unknown/null are independent from source readability and current qualification", () => {
  const html = render(); for (const raw of ["保存时准备检查", "保存记录状态", "阻断（blocked）", "原检查结果状态", "未知（unknown）", "原就绪值", "未知（null）", "当前可读", at, "来源可读不代表当前资格、阶段通过或可开工", "原准备说明"]) assert.ok(html.includes(raw), raw);
  const build = fixture(); build.readiness.is_current = false; build.readiness.result.status = "blocked"; assert.match(render(build), /需重核/); assert.doesNotMatch(html, /已批准开工|已满足全部资格|阶段已通过|准备度.*100/);
});

test("every returned check retains its own status, reason, recovery, blocking flag and exact fixed source pointers", () => {
  const build = fixture(), html = render(build); assert.equal((html.match(/<strong>原检查标签/g) ?? []).length, 3);
  for (let index = 0; index < 3; index++) for (const raw of [`原检查标签${index}`, `ORIGINAL_REASON_${index}`, `原保存说明${index}`, `原恢复建议${index}`]) assert.ok(html.includes(raw), raw);
  for (const raw of ["已知（known）", "未知（unknown）", "阻断（blocked）", "原阻塞标记：否（false）", "原阻塞标记：是（true）", id(4), id(5), id(6), id(7), "ORIGINAL_UNKNOWN", "original.path"]) assert.ok(html.includes(raw), raw);
  assert.match(html, /role="region" aria-label="保存时逐项准备检查" tabindex="0"/);
});

test("saved demand decimals, scientific notation, null mapping/unit and ancestry are never rounded, multiplied or filled", () => {
  const build = fixture(), result = build.readiness.result; assert.ok(render(build).includes("22.000000000")); Object.assign(result.demands[0], { material_id: null, unit: null, quantity_per_product: "+2.2E+0", required_quantity: "9007199254740993.1234567890123456789" }); const html = render(build);
  for (const raw of ["+2.2E+0", "9007199254740993.1234567890123456789", "parent-original", "物料标识：未知（null）", "不乘算、不转换单位"]) assert.ok(html.includes(raw), raw);
  assert.doesNotMatch(html, /9007199254740994|默认单位|齐套率/);
});

test("known coverage zero remains distinct from unknown gaps and readiness; null coverage is a separate original fact", () => {
  const html = render(); assert.match(html, /<td>0<\/td><td>0<\/td><td>未知（null）<\/td><td>未知（null）<\/td>/); assert.match(html, /原已保障就绪值：未知（null）/); assert.match(html, /原潜在候选就绪值：未知（null）/); assert.match(html, /这不是全库库存，也不表示供应范围完整/);
  const build = fixture(); build.readiness.result.coverage = null; const absent = render(build); assert.match(absent, /原覆盖计算为空（null），未知不补零/); assert.doesNotMatch(absent, /保存来源池观测|覆盖算法与保存时指纹/);
});

test("null is an absent original wrapper while malformed or wrong-scope data is an isolated explicit panel error", () => {
  const build = fixture(); build.readiness = null; assert.match(render(build), /本次 Build 回读未返回已保存的准备检查/); assert.doesNotMatch(render(build), /role="alert"|已知准备项为零/);
  for (const mutate of [value => { delete value.readiness; }, value => { value.readiness.result.build_revision = 2; }, value => { value.readiness.result.input_snapshot.build.metadata.project_revision = 4; }, value => { value.readiness.result.checks[0].source_refs[0].revision = 2; }]) { const wrong = fixture(); mutate(wrong); const before = structuredClone(wrong), html = render(wrong); assert.match(html, /role="alert"/); assert.match(html, /其他 Build 资料保留原回读/); assert.doesNotMatch(html, /原检查标签|原恢复建议|未返回已保存的准备检查/); assert.deepEqual(wrong, before); }
  assert.match(render(fixture(), { ...scope, projectId: id(99) }), /role="alert"/);
});

test("saved IDs/hashes are collapsed and exact while complete snapshots, hidden metadata and unverified hash claims are absent", () => {
  const build = fixture(), html = render(build); for (const raw of ["a".repeat(64), "b".repeat(64), id(9), id(7), `${id(3)} · v3`, "未由本次展示重新计算或复验", "未展开完整输入快照"]) assert.ok(html.includes(raw), raw);
  assert.doesNotMatch(html, /MUST_NOT_RENDER|DO_NOT_DUMP|NO_AUTHORITY_DUMP|COVERAGE_INPUT_MUST_NOT_RENDER|<pre|<form|<input|<button|指纹已验证/);
  const visible = collapsedText(React.createElement(ProjectBuildReadiness, { build, scope })); assert.ok(!visible.includes(id(9))); assert.ok(!visible.includes(id(7))); assert.ok(!visible.includes("a".repeat(64)));
});

test("unvalidated pool/use bodies stay unexpanded while their actual returned counts remain explicit", () => {
  const build = fixture(), coverage = build.readiness.result.coverage, pool = { hidden_original: { source: "UNVALIDATED_POOL_MUST_NOT_RENDER" } }, use = { private_original: "UNVALIDATED_USE_MUST_NOT_RENDER" };
  coverage.secured_ready = true; coverage.potential_ready = false; coverage.lines[0].uses = [use]; coverage.pools = [pool]; const before = structuredClone(build), html = render(build);
  for (const raw of ["是（true）", "否（false）", "本行返回使用项 1 条", "本次返回来源池记录 1 条", "本面板未展开其明细", "这不是全库库存，也不表示供应范围完整", "潜在候选不构成可行性证明"]) assert.ok(html.includes(raw), raw);
  assert.doesNotMatch(html, /UNVALIDATED_POOL|UNVALIDATED_USE|原已占用量|来源池单位原量|保存来源引用|未提供/); assert.deepEqual(build, before);
});

test("pure parsed SSR performs no API/write/clock work, mutates nothing and replaces facts on every prop render", () => {
  const build = freeze(fixture()), before = structuredClone(build), previousFetch = globalThis.fetch, previousNow = Date.now;
  globalThis.fetch = () => { throw new Error("NO_API_ALLOWED"); }; Date.now = () => { throw new Error("NO_CURRENT_CLOCK_ALLOWED"); };
  try { const first = render(build); assert.match(first, /原检查标签0/); const next = fixture(); next.id = id(70); next.readiness.result.build_id = next.id; next.readiness.result.input_snapshot.build.id = next.id; next.readiness.result.checks.forEach(check => { check.source_refs[0].id = next.id; }); next.readiness.result.checks[0].label = "另一固定Build原检查"; const html = render(next); assert.match(html, /另一固定Build原检查/); assert.doesNotMatch(html, /原检查标签0/); assert.deepEqual(build, before); }
  finally { globalThis.fetch = previousFetch; Date.now = previousNow; }
});
