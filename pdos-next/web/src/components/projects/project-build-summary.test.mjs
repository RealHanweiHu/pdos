import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Isolated state driver; the read library has its own actual DTO/transport tests. */
const react = { ...React, useState(initial) {
  if (!hooks) return React.useState(initial);
  const own = hooks, index = own.index++;
  if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial;
  return [own.slots[index], next => { if (!own.disposed) { own.slots[index] = typeof next === "function" ? next(own.slots[index]) : next; own.dirty = true; } }];
}, useCallback(callback, deps) {
  if (!hooks) return React.useCallback(callback, deps);
  const index = hooks.index++; if (!same(hooks.slots[index]?.deps, deps)) hooks.slots[index] = { deps, callback }; return hooks.slots[index].callback;
}, useEffect(effect, deps) {
  if (!hooks) return React.useEffect(effect, deps);
  const own = hooks, index = own.index++;
  if (!same(own.slots[index]?.deps, deps)) { const prior = own.slots[index], next = { deps, cleanup: prior?.cleanup }; own.slots[index] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); }
} };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const boundary = {
  readProjectBuilds(api, scope) { return api(`v1/categories/${scope.categoryId}/products/${scope.productId}/builds?project_id=${scope.projectId}`); },
  readBuildTestSummary(api, scope, build) { return api(`v1/categories/${scope.categoryId}/products/${scope.productId}/verification-results?build_id=${build.id}`).then(result => ({ build, ...result })); },
};
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react : name === "@/lib/project-build-summary" ? boundary : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { ProjectBuildSummary } = load(path.join(directory, "project-build-summary.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3) };
function build(n = 5) { return { id: id(n), project_id: scope.projectId, project_revision: 2, revision: 3, name: `合成轮次 ${n}`, type: "prototype", status: "planned", source_status: "current", purpose: "合成轮次目的", planned_quantity: "24.0000000001", unit: "台", planned_start: "2026-10-20T01:00:00+00:00", planned_end: null, previous_build_id: id(90), readiness: null, verification_objectives: "保留原验证目标", disposition_plan: "保留原处置要求", engineering_configuration: { id: id(7), name: "固定工程配置", revision: 4, status: "draft", definition: { id: id(8), revision: 2 }, sources: [{ artifact_id: id(10), expected_revision: 2, line: 1, quote: "SYNTHETIC_SOURCE" }] }, manufacturing_configuration: { id: id(9), name: "固定制造配置", revision: 6, status: "draft" } }; }
const list = (items = [build()], unavailableCount = 0, hasMore = false) => ({ items, unavailableCount, hasMore });
function tests({ runs = true, unavailableCount = 0, hasMore = false, unindexedRunCount = 0 } = {}) { return { runs: runs ? [{ runId: id(20), versionId: id(21), revision: 4, requestRevision: 3, status: "results_pending", result: "fail", sourceStatus: "current", createdAt: "2026-10-17T00:00:00Z", request: { id: id(22), versionId: id(23), revision: 3, title: "合成固定测试请求", status: "in_test", sourceStatus: "current" }, coverage: { sampleCount: 2, itemCount: 3, pairCount: 5, measuredPairCount: 4, missingPairCount: 1 }, currentProjection: { id: id(24), revision: 1, basisSha256: "a".repeat(64), result: "fail", runVersionId: id(21), runRevision: 4, sourceStatus: "current" }, runSnapshot: { coverage: [{ sample_id: id(25), item_id: id(26) }], measurements: [{ id: id(27), coverage: { sample_id: id(25), item_id: id(26) }, raw_value: "11.000001", unit: "psi", observed_at: "2026-10-17T01:00:00.000001Z", observed_timezone: "Asia/Shanghai" }], actual_start: { occurred_at: "2026-10-17T00:00:00.000001Z", original_timezone: "Asia/Shanghai", received_at: "2026-10-17T00:01:00Z" }, actual_end: null, final_result: null, professional_conclusion: { text: "仅覆盖当前固定测试范围的具名结论", actor_id: id(30) }, disposition: null, internal_material_not_for_display: "INTERNAL_SNAPSHOT_SHOULD_NOT_RENDER" } }] : [], unavailableCount, hasMore, unindexedRunCount }; }
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const calls = [], api = (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false }));
  let props = { ...scope, principalId: id(4), readVersion: 0, api }, parent, child, tree;
  const fresh = key => ({ key, slots: [], index: 0, effects: [], dirty: true, disposed: false });
  function dispose(instance) { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } }
  function evaluate(instance, element) { instance.index = 0; instance.effects = []; instance.dirty = false; hooks = instance; try { return element.type(element.props); } finally { hooks = null; } }
  function replace(node, target, replacement) { if (node === target) return replacement; if (Array.isArray(node)) return node.map((item, index) => { const result = replace(item, target, replacement); return React.isValidElement(result) ? React.cloneElement(result, { key: result.key ?? index }) : result; }); if (!React.isValidElement(node) || node.props.children === undefined) return node; return React.cloneElement(node, { children: replace(node.props.children, target, replacement) }); }
  function render() {
    const wrapper = ProjectBuildSummary(props);
    if (!parent || parent.key !== wrapper.key) { dispose(parent); dispose(child); child = null; parent = fresh(wrapper.key); }
    const outer = evaluate(parent, wrapper), inner = elements(outer, node => node.type?.name === "SelectedBuild")[0];
    if (inner) { if (!child || child.key !== inner.key) { dispose(child); child = fresh(inner.key); } tree = replace(outer, inner, evaluate(child, inner)); } else { dispose(child); child = null; tree = outer; }
    parent.effects.forEach(effect => effect()); child?.effects.forEach(effect => effect());
  }
  render(); t.after(() => { dispose(parent); dispose(child); });
  return { calls, tree: () => tree, html: () => renderToStaticMarkup(tree), setProps(next) { props = { ...props, ...next }; render(); }, pending(fragment) { return calls.find(call => !call.done && call.route.includes(fragment)); }, respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, value) { assert.ok(call); call.done = true; call.reject(value); }, async flush() { for (let i = 0; i < 7; i++) { await tick(); if (parent.dirty || child?.dirty) render(); } } };
}
const button = (env, label) => elements(env.tree(), node => node.props?.children === label && typeof node.props.onClick === "function")[0];
async function click(env, label) { const found = button(env, label); assert.ok(found, label); found.props.onClick(); await env.flush(); }
async function ready(env, value = list()) { env.respond(env.pending("/builds?"), value); await env.flush(); }
async function select(env, name = "合成轮次 5") { const found = elements(env.tree(), node => node.props?.["aria-label"] === `查看 ${name} 轮次摘要`)[0]; assert.ok(found); found.props.onClick(); await env.flush(); }

test("list loading, partial reads and a genuinely empty list stay distinct; no Build is selected automatically", async t => {
  const env = environment(t); assert.match(env.html(), /正在读取本项目轮次/); assert.equal(env.calls.length, 1); await ready(env, list([], 2, true));
  assert.match(env.html(), /2 条记录暂不可读/); assert.match(env.html(), /读取范围尚不完整/); assert.doesNotMatch(env.html(), /尚无本项目 Build/); assert.equal(env.calls.length, 1);
  await click(env, "刷新本项目轮次"); await ready(env, list([])); assert.match(env.html(), /尚无本项目 Build/); assert.ok(env.calls.every(call => call.body === undefined));
});
test("Builds retain precise planned quantities, fixed configurations and purpose; tests are read only after an explicit selection", async t => {
  const env = environment(t); await ready(env); assert.equal(env.calls.length, 1);
  for (const text of ["24.0000000001", "计划已登记", "合成轮次目的", "固定工程配置", "固定制造配置", "2026-10-20T01:00:00+00:00", "计划窗口不是承诺"]) assert.ok(env.html().includes(text), text);
  assert.doesNotMatch(env.html(), /未开工|已完成|下一 Build|通过率/); await select(env); assert.equal(env.calls.length, 2); assert.ok(env.calls[1].route.endsWith(`verification-results?build_id=${id(5)}`));
  env.respond(env.pending("verification-results"), tests()); await env.flush();
  for (const text of ["保留原验证目标", "保留原处置要求", "固定范围数值判定未通过", "样件 2", "配对 5", "已登记测量记录配对 4", "尚缺测量记录配对 1", "本轮按下列固定引用核对", "11.000001", "2026-10-17T01:00:00.000001Z", "仅覆盖当前固定测试范围的具名结论"]) assert.ok(env.html().includes(text), text);
  assert.doesNotMatch(env.html(), /阶段通过<|制造放行成功|100%|INTERNAL_SNAPSHOT_SHOULD_NOT_RENDER|<pre/);
});
test("native workbench anchors retain all exact scope and Build parameters without claiming automatic Run selection", async t => {
  const env = environment(t); await ready(env); await select(env); env.respond(env.pending("verification-results"), tests()); await env.flush();
  const links = elements(env.tree(), node => node.props?.href); assert.ok(links.length >= 4);
  for (const anchor of links) { assert.equal(anchor.type, "a"); const params = new URL(anchor.props.href, "https://example.test").searchParams; assert.equal(params.get("category"), scope.categoryId); assert.equal(params.get("product"), scope.productId); assert.equal(params.get("project"), scope.projectId); assert.equal(params.get("build"), id(5)); assert.ok(params.get("view")); assert.ok(params.get("task")); assert.equal(params.has("run"), false); }
  assert.match(env.html(), /测试 Run 仍需在原页面选择/);
});
test("selected test failures do not erase the project Build list, and retry retains the same explicit Build", async t => {
  const env = environment(t); await ready(env); await select(env); env.reject(env.pending("verification-results"), Object.assign(new Error("合成测试读取失败"), { status: 503 })); await env.flush();
  assert.match(env.html(), /合成测试读取失败/); assert.match(env.html(), /合成轮次 5/); assert.doesNotMatch(env.html(), /尚无本轮测试 Run/);
  await click(env, "重新读取已选轮次摘要"); env.respond(env.pending("verification-results"), tests({ runs: false, unavailableCount: 1 })); await env.flush(); assert.match(env.html(), /读取范围尚不完整/); assert.doesNotMatch(env.html(), /尚无本轮测试 Run/);
});
test("late results from another selected Build cannot replace current tests or fixed scope", async t => {
  const env = environment(t); await ready(env, list([build(), build(6)])); await select(env); const first = env.pending("verification-results"); await select(env, "合成轮次 6");
  const next = env.calls.filter(call => call.route.includes("verification-results"))[1]; env.respond(next, tests({ runs: false })); await env.flush(); const late = tests(); late.runs[0].request.title = "迟到旧轮测试"; env.respond(first, late); await env.flush();
  assert.doesNotMatch(env.html(), /迟到旧轮测试/); assert.match(env.html(), /尚无本轮测试 Run/);
});
test("principal/category/product/project/refresh identity changes hide old private data synchronously", async t => {
  const env = environment(t); await ready(env);
  for (const change of [{ principalId: id(40) }, { categoryId: id(41) }, { productId: id(42) }, { projectId: id(43) }, { readVersion: 1 }]) { env.setProps(change); assert.doesNotMatch(env.html(), /合成轮次 5|固定工程配置/); assert.match(env.html(), /正在读取本项目轮次/); await ready(env); }
  const changedReads = []; env.setProps({ api: route => new Promise(resolve => changedReads.push({ route, resolve })) }); assert.doesNotMatch(env.html(), /合成轮次 5/); assert.match(env.html(), /正在读取本项目轮次/); changedReads[0].resolve(list()); await env.flush(); assert.match(env.html(), /合成轮次 5/);
});
test("refresh hides old detail immediately and ignores a late test response, while list failures remain retryable unknown", async t => {
  const env = environment(t); await ready(env); await select(env); const late = env.pending("verification-results"); await click(env, "刷新本项目轮次"); assert.doesNotMatch(env.html(), /固定工程配置|已选轮次事实摘要/);
  env.respond(late, tests()); env.reject(env.pending("/builds?"), new Error("合成列表读取失败")); await env.flush(); assert.match(env.html(), /合成列表读取失败/); assert.doesNotMatch(env.html(), /尚无本项目 Build|合成固定测试请求/);
  await click(env, "重新读取项目轮次"); await ready(env); assert.match(env.html(), /合成轮次 5/); assert.equal(env.calls.filter(call => call.route.includes("verification-results")).length, 1);
});

test("missing current projection is not replaced by a raw Run result, and missing current indexes cannot become an empty claim", async t => {
  const env = environment(t); await ready(env); await select(env); const value = tests(); value.runs[0].currentProjection = null; value.runs[0].result = "pass"; value.runs[0].requestRevision = 2; env.respond(env.pending("verification-results"), value); await env.flush();
  assert.match(env.html(), /尚无与当前固定依据一致的已保存判定/); assert.doesNotMatch(env.html(), /固定范围数值判定通过/); assert.match(env.html(), /Run 固定请求 v2 · 请求当前 v3/);
  await click(env, "刷新已选轮次摘要"); env.respond(env.pending("verification-results"), tests({ runs: false, unindexedRunCount: 2 })); await env.flush(); assert.match(env.html(), /2 个历史运行尚未提供可核对的当前索引/); assert.doesNotMatch(env.html(), /尚无本轮测试 Run/);
});

test("access or source rejection hides the old Build list until an explicit reread, while a transport 503 retains it", async t => {
  const env = environment(t); await ready(env); await select(env); env.reject(env.pending("verification-results"), Object.assign(new Error("合成权限变化"), { status: 403 })); await env.flush();
  assert.match(env.html(), /已隐藏旧轮次资料/); assert.doesNotMatch(env.html(), /合成轮次 5|固定工程配置|合成固定测试请求/);
  await click(env, "重新读取项目轮次"); await ready(env); await select(env); env.reject(env.pending("verification-results"), Object.assign(new Error("合成来源过期"), { status: 409, code: "SOURCE_STALE" })); await env.flush(); assert.doesNotMatch(env.html(), /合成轮次 5|固定工程配置/);
  await click(env, "重新读取项目轮次"); await ready(env); await select(env); env.reject(env.pending("verification-results"), Object.assign(new Error("合成临时传输失败"), { status: 503, code: "SOURCE_UNAVAILABLE" })); await env.flush(); assert.match(env.html(), /合成轮次 5/); assert.match(env.html(), /合成临时传输失败/);
});

test("physical output is scoped to the verified selected Build and is removed while the parent rereads", async t => {
  const env = environment(t);
  await ready(env);
  assert.equal(elements(env.tree(), node => node.type?.name === "ProjectBuildOutput").length, 0);
  await select(env);
  env.respond(env.pending("verification-results"), tests());
  await env.flush();
  const [output] = elements(env.tree(), node => node.type?.name === "ProjectBuildOutput");
  assert.ok(output);
  assert.deepEqual(output.props.scope, scope);
  assert.equal(output.props.build.id, id(5));
  assert.equal(output.props.build.revision, 3);
  assert.equal(typeof output.props.onAccessRejected, "function");
  await click(env, "刷新已选轮次摘要");
  assert.equal(elements(env.tree(), node => node.type?.name === "ProjectBuildOutput").length, 0);
  env.respond(env.pending("verification-results"), tests());
  await env.flush();
  elements(env.tree(), node => node.type?.name === "ProjectBuildOutput")[0].props.onAccessRejected("样件固定链已变化");
  await env.flush();
  assert.match(env.html(), /样件固定链已变化/);
  assert.equal(elements(env.tree(), node => node.type?.name === "ProjectBuildOutput").length, 0);
});


test("saved preparation receives only the explicitly selected, rechecked Build without additional reads", async t => {
  const env = environment(t), preparations = () => elements(env.tree(), node => node.type?.name === "ProjectBuildReadiness");
  await ready(env, list([build(), build(6)])); assert.equal(preparations().length, 0);
  await select(env); assert.equal(preparations().length, 0);
  env.respond(env.pending("verification-results"), tests()); await env.flush();
  const [panel] = preparations(); assert.ok(panel); assert.equal(panel.props.build.id, id(5));
  assert.equal(panel.props.build.revision, 3); assert.equal(panel.props.build.readiness, null);
  assert.deepEqual(panel.props.scope, scope); assert.equal("api" in panel.props, false);
  assert.equal(env.calls.length, 2); assert.match(env.html(), /保存时准备检查/);
  await click(env, "刷新已选轮次摘要"); assert.equal(preparations().length, 0);
  assert.equal(env.calls.length, 3); env.respond(env.pending("verification-results"), tests()); await env.flush();
  assert.equal(preparations().length, 1); assert.equal(env.calls.length, 3);
  await select(env, "合成轮次 6"); assert.equal(preparations().length, 0);
  env.respond(env.pending("verification-results"), tests()); await env.flush();
  assert.equal(preparations()[0].props.build.id, id(6)); assert.equal(env.calls.length, 4);
  assert.ok(env.calls.every(call => call.body === undefined));
});
