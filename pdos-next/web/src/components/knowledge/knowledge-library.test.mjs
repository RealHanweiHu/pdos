import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Isolated actual hook/event driver, not browser or HTTP evidence. */
const react = { ...React, useState(initial) { if (!hooks) return React.useState(initial); const own = hooks, index = own.index++; if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial; return [own.slots[index], next => { if (!own.disposed) { own.slots[index] = typeof next === "function" ? next(own.slots[index]) : next; own.dirty = true; } }]; }, useRef(initial) { if (!hooks) return React.useRef(initial); const index = hooks.index++; if (!(index in hooks.slots)) hooks.slots[index] = { current: initial }; return hooks.slots[index]; }, useEffect(effect, deps) { if (!hooks) return React.useEffect(effect, deps); const own = hooks, index = own.index++; if (!same(own.slots[index]?.deps, deps)) { const next = { deps, cleanup: own.slots[index]?.cleanup }; own.slots[index] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); } }, useLayoutEffect(effect, deps) { if (!hooks) return React.useLayoutEffect(effect, deps); const own = hooks, index = own.index++; if (!same(own.slots[index]?.deps, deps)) { const next = { deps, cleanup: own.slots[index]?.cleanup, phase: "layout" }; own.slots[index] = next; own.layouts.push(() => { next.cleanup?.(); next.cleanup = effect(); }); } } };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
// Existing workbench is substituted only to inspect explicit mounting and exact
// parent props; its command behavior remains covered by its own actual tests.
function ExistingWorkbench(props) { return React.createElement("section", { "aria-label": "既有知识工作台替身", "data-product": props.product.id, "data-revision": props.product.revision, "data-project": props.projectId === null ? "null" : props.projectId, "data-category": props.categoryId, "data-principal": props.principalId }, React.createElement("button", { onClick: props.onSaved }, "测试原工作台已保存")); }
const modules = new Map();
function load(filename) { if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) }; if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync); if (modules.has(filename)) return modules.get(filename).exports; const loaded = new Module(filename); modules.set(filename, loaded); loaded.require = name => name === "react" ? react : name === "./knowledge-experience" && path.dirname(filename) === directory ? { KnowledgeExperience: ExistingWorkbench } : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name); loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename); return loaded.exports; }
const { KnowledgeLibrary, KnowledgeCandidateReading, KnowledgeRuleReading } = load(path.join(directory, "knowledge-library.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, at = "2026-10-18T12:34:56.123456+08:00";
const scope = { categoryId: id(1), categoryName: "合成品类原名", principalId: id(2) };
const source = () => ({ kind: "artifact", id: id(90), revision: 2, position: `line:7;quote_sha256:${"a".repeat(64)}` });
const history = (versionId, revision, actorId = id(2)) => [{ id: versionId, revision, actor_id: actorId, created_at: at, receipt_id: id(91) }];
function candidate(n = 10, projectId = null) { return { id: id(n), revision: 2, version_id: id(n + 100), project_id: projectId, owner_id: id(2), visibility: "private", title: `候选原题${n}`, lesson: "原经验与教训\n保留原行", evidence_summary: "来源原文核对的证据摘要", applicability_hypothesis: "仅为假设，未知配置仍待核对", sources: [source()], result_receipts: [{ receipt_id: id(92) }], author_id: id(93), origin: "ai", created_at: at, can_revise: false, history: [{ id: id(n + 200), revision: 1, actor_id: id(93), created_at: at, receipt_id: id(94) }, ...history(id(n + 100), 2, id(93))] }; }
function rule(n = 40, state = "current", decision = "applicable") { return { id: id(n), revision: 1, version_id: id(n + 100), project_id: id(30), owner_id: id(2), visibility: "category", title: `固定规则原题${n}`, rule_text: "仅供固定配置及原用途的规则正文", nature: "synthetic", candidate: { id: id(10), revision: 1 }, candidate_version_id: id(210), applicability: { target: { kind: "engineering_configuration", id: id(31), revision: 1 }, purpose: "原固定用途", differences: ["材料差异原值"], adopted_rule: "本配置明确采用的原规则", conditions: ["原条件一", "原条件二"], decision, rationale: "原具名评估依据", valid_from: at, valid_until: null, candidate_version: { id: id(210), revision: 1 }, assessor_id: id(95), withdrawal_reason: null }, usability: { state, reason_codes: state === "current" ? [] : ["原服务器原因码"] }, sources: [source()], author_id: id(96), created_at: at, can_revise: false, history: history(id(n + 100), 1, id(96)) }; }
// Pure synthetic transport DTOs pass through the real frozen reader. No actual
// HTTP, DB, external qualification or browser validation is represented here.
const categoryView = () => ({ product_revision: 3, projects: [], configurations: [], candidates: [candidate()], rules: [], as_of: at });
const modelView = () => ({ product_revision: 5, projects: [{ id: id(30), revision: 3, name: "真实返回项目名", owner_id: id(2), visibility: "private" }], configurations: [{ kind: "engineering_configuration", id: id(31), revision: 2, name: "当前配置v2不能替代固定v1" }], candidates: [candidate(), candidate(11, id(30))], rules: [rule()], as_of: at });
const products = (input = scope) => [4, 5].map(n => ({ id: id(n), category_id: input.categoryId, visibility: "category", name: `可读型号${n}`, purpose: "真实返回型号用途", revision: n + 1, status: "draft" }));
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate)); if (typeof tree.type === "function") return elements(tree.type(tree.props), predicate); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
function collapsedText(tree) { if (typeof tree === "string" || typeof tree === "number") return String(tree); if (!tree || typeof tree !== "object") return ""; if (Array.isArray(tree)) return tree.map(collapsedText).join(""); if (typeof tree.type === "function") return collapsedText(tree.type(tree.props)); return tree.type === "details" ? "" : collapsedText(tree.props?.children); }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const calls = [], makeApi = () => (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false }));
  let props = { ...scope, api: makeApi(), readVersion: 0 }, instance, tree;
  const dispose = () => { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } };
  function render(commit = true) { const wrapper = KnowledgeLibrary(props); if (!instance || instance.key !== wrapper.key) { dispose(); instance = { key: wrapper.key, slots: [], index: 0, effects: [], layouts: [], dirty: true, disposed: false }; } instance.index = 0; instance.effects = []; instance.layouts = []; instance.dirty = false; hooks = instance; try { tree = wrapper.type(wrapper.props); } finally { hooks = null; } instance.layouts.forEach(effect => effect()); if (commit) instance.effects.forEach(effect => effect()); }
  render(); t.after(dispose);
  return { calls, tree: () => tree, html: () => renderToStaticMarkup(tree), render, props: () => props, setProps(next, commit = true) { props = { ...props, ...next }; render(commit); }, replaceApi(commit = true) { props = { ...props, api: makeApi() }; render(commit); }, unmountLayout() { instance.slots.filter(slot => slot?.phase === "layout").forEach(slot => slot.cleanup?.()); }, pending(fragment = "/experience") { return calls.findLast(call => !call.done && call.route.includes(fragment)); }, respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, failure) { assert.ok(call); call.done = true; call.reject(failure); }, async flush() { for (let i = 0; i < 6; i++) { await tick(); if (instance.dirty) render(); } } };
}
const button = (env, label) => elements(env.tree(), node => (node.props?.children === label || node.props?.["aria-label"] === label) && typeof node.props.onClick === "function")[0];
async function click(env, label, commit = true) { const node = button(env, label); assert.ok(node, label); assert.ok(!node.props.disabled, label); node.props.onClick(); env.render(commit); await env.flush(); }
async function change(env, label, value, commit = true) { const node = elements(env.tree(), node => node.props?.["aria-label"] === label && typeof node.props.onChange === "function")[0]; assert.ok(node, label); node.props.onChange({ target: { value } }); env.render(commit); await env.flush(); }
async function ready(env, value = categoryView(), returnedProducts = products(env.props())) { const options = env.calls.findLast(call => !call.done && call.route.endsWith("/products")); if (options) { env.respond(options, returnedProducts); await env.flush(); } env.respond(env.pending(), value); await env.flush(); }
async function chooseModel(env, n = 4, value = modelView()) { await change(env, "知识读取范围", id(n)); env.respond(env.pending(), value); await env.flush(); }
const hasBody = env => /aria-label="经验候选正文|aria-label="固定配置规则正文/.test(env.html());
const hasManager = env => /既有知识工作台替身/.test(env.html());

test("category candidates are the default and product options never select the first model", async t => {
  const env = environment(t); assert.equal(env.calls.length, 2); assert.ok(env.calls.some(call => call.route === `v1/categories/${scope.categoryId}/products`)); assert.ok(env.calls.some(call => call.route === `v1/categories/${scope.categoryId}/experience`)); await ready(env); assert.equal(env.calls.length, 2); assert.match(env.html(), /品类候选（不选型号）/); assert.match(env.html(), /候选原题10/); assert.equal(hasBody(env), false); assert.equal(hasManager(env), false); assert.equal(button(env, "记录 / 发布办理"), undefined); assert.ok(env.calls.every(call => call.body === undefined));
});

test("only an explicit visible model reads model knowledge and the full selected record expands without another GET", async t => {
  const env = environment(t); await ready(env); await chooseModel(env); assert.equal(env.calls.length, 3); assert.equal(env.calls[2].route, `v1/categories/${scope.categoryId}/products/${id(4)}/experience`); assert.equal(hasBody(env), false); await click(env, `展开规则 ${id(40)} v1`); assert.equal(env.calls.length, 3); assert.equal(hasBody(env), true); assert.match(env.html(), /原固定用途|固定配置规则正文/); await click(env, "收起知识详情"); assert.equal(hasBody(env), false); await change(env, "知识读取范围", id(99)); assert.equal(env.calls.length, 3); assert.doesNotMatch(env.html(), /所选型号待核对/);
});

test("query and type filters apply only to returned rows, clear details and never issue global search", async t => {
  const env = environment(t); await ready(env); await chooseModel(env); await click(env, `展开候选 ${id(10)} v2`); await change(env, "知识类型", "rule"); assert.equal(hasBody(env), false); assert.doesNotMatch(env.html(), /候选原题10/); assert.match(env.html(), /筛选显示 1 条/); await change(env, "查询本次知识", "不存在的本页内容"); assert.match(env.html(), /本次返回内容没有匹配项/); assert.doesNotMatch(env.html(), /全局没有|本品类没有规则/); assert.equal(env.calls.length, 3); await change(env, "查询本次知识", "原固定用途"); assert.match(env.html(), /固定规则原题40/);
});

test("server usability and all original applicability decisions remain independent, including current plus not_applicable", async t => {
  const env = environment(t); await ready(env); const view = modelView(); view.rules = [rule(40, "current", "not_applicable"), rule(41, "not_yet_effective", "unknown"), rule(42, "expired", "conflicted"), rule(43, "needs_recheck")]; view.rules[1].nature = "real"; await chooseModel(env, 4, view);
  for (const raw of ["当前可用", "不适用", "尚未生效", "未知", "已过有效期", "存在冲突", "需要重核", "合成资料（synthetic）", "真实资料（real）"]) assert.ok(env.html().includes(raw), raw);
  await click(env, `展开规则 ${id(40)} v1`); assert.match(env.html(), /服务器可用状态：当前可用（current）/); assert.match(env.html(), /固定适用判断：不适用（not_applicable）/); assert.doesNotMatch(env.html(), /所有配置均适用|当前配置v2不能替代固定v1|规则已撤回/);
});

test("pure candidate and rule SSR preserve exact old references, source locations, actors, times and history metadata", () => {
  const c = candidate(), r = rule(), before = structuredClone([c, r]);
  const html = renderToStaticMarkup(React.createElement(KnowledgeCandidateReading, { value: c })) + renderToStaticMarkup(React.createElement(KnowledgeRuleReading, { value: r, configurations: modelView().configurations, projects: modelView().projects }));
  for (const raw of ["原经验与教训", "来源原文核对的证据摘要", "仅为假设，未知配置仍待核对", "AI 来源", "材料差异原值", "本配置明确采用的原规则", "原条件一", "原条件二", "原具名评估依据", "原固定用途", id(31), id(210), id(95), id(93), id(92), source().position, at, "未设截至时点（原值为空）", "未读取历史正文", "固定候选版本标识"]) assert.ok(html.includes(raw), raw);
  assert.doesNotMatch(html, /当前配置v2不能替代固定v1|<pre|<form|<textarea|已授予发布资格/); assert.deepEqual([c, r], before);
  const collapsed = collapsedText(React.createElement(KnowledgeRuleReading, { value: r })); assert.ok(!collapsed.includes(id(31))); assert.ok(!collapsed.includes(id(95)));
});

test("workbench mounts only after explicit action with exact current product metadata and closes on return", async t => {
  const env = environment(t); await ready(env); assert.equal(hasManager(env), false); await chooseModel(env); assert.equal(hasManager(env), false); await click(env, "记录 / 发布办理"); assert.equal(hasManager(env), true); const node = elements(env.tree(), node => node.props?.["aria-label"] === "既有知识工作台替身")[0]; assert.equal(node.props["data-product"], id(4)); assert.equal(node.props["data-revision"], 5); assert.equal(node.props["data-project"], "null"); assert.equal(node.props["data-principal"], scope.principalId); assert.equal(env.calls.length, 3); await click(env, "返回知识目录"); assert.equal(hasManager(env), false); assert.match(env.html(), /固定规则原题40/);
});

test("model changes remove the manager and selecting the same old model again cannot reopen it", async t => {
  const env = environment(t); await ready(env); await chooseModel(env); await click(env, "记录 / 发布办理"); await change(env, "知识读取范围", id(5)); assert.equal(hasManager(env), false); assert.equal(hasBody(env), false); env.respond(env.pending(), modelView()); await env.flush(); await change(env, "知识读取范围", id(4)); assert.equal(hasManager(env), false); env.respond(env.pending(), modelView()); await env.flush(); assert.equal(hasManager(env), false); await click(env, "记录 / 发布办理"); assert.equal(hasManager(env), true); await click(env, "测试原工作台已保存"); assert.equal(hasManager(env), false); assert.doesNotMatch(env.html(), /固定规则原题40/); await ready(env, modelView()); assert.equal(hasManager(env), false); assert.match(env.html(), /固定规则原题40/);
});

test("refresh revalidates the chosen model before reading, and absent or inaccessible options never fall back to the first product", async t => {
  const env = environment(t); await ready(env); await chooseModel(env); await click(env, `展开规则 ${id(40)} v1`); await click(env, "刷新知识资料"); assert.equal(hasBody(env), false); const reads = env.calls.length; env.respond(env.pending("/products"), [products()[1]]); await env.flush(); assert.equal(env.calls.length, reads); assert.match(env.html(), /所选型号已不在本次可读列表中/); assert.doesNotMatch(env.html(), /固定规则原题40|候选原题10/); assert.equal(button(env, "记录 / 发布办理"), undefined); await click(env, "返回品类候选"); env.respond(env.pending(), categoryView()); await env.flush(); assert.match(env.html(), /候选原题10/); assert.ok(env.calls.at(-1).route.endsWith(`${scope.categoryId}/experience`));
});

test("403, 503 and malformed knowledge reads clear old private bodies and never look like successful empty sets", async t => {
  const env = environment(t); await ready(env); await chooseModel(env); await click(env, `展开规则 ${id(40)} v1`);
  for (const status of [403, 503]) { await click(env, "刷新知识资料"); env.respond(env.pending("/products"), products()); await env.flush(); env.reject(env.pending(), Object.assign(Error(`知识真实${status}失败`), { status })); await env.flush(); assert.equal(hasBody(env), false); assert.doesNotMatch(env.html(), /固定规则原题40|本次读集没有返回/); assert.match(env.html(), new RegExp(`知识真实${status}失败`)); await click(env, "重新读取知识资料"); await ready(env, modelView()); await click(env, `展开规则 ${id(40)} v1`); }
  await click(env, "刷新知识资料"); const invalid = modelView(); invalid.rules[0].history = []; await ready(env, invalid); assert.equal(hasBody(env), false); assert.match(env.html(), /未完整取得/); assert.doesNotMatch(env.html(), /本次读集没有返回/);
});

test("late model read outcomes cannot cross a newer explicit model or API before passive cleanup", async t => {
  const env = environment(t); await ready(env); await change(env, "知识读取范围", id(4)); const old = env.pending(); await change(env, "知识读取范围", id(5), false); env.reject(old, Object.assign(Error("旧型号迟到403"), { status: 403 })); await env.flush(); assert.doesNotMatch(env.html(), /旧型号迟到403|固定规则原题40/); await click(env, "刷新知识资料"); await ready(env, modelView()); await click(env, `展开规则 ${id(40)} v1`); await click(env, "记录 / 发布办理"); env.replaceApi(false); assert.equal(hasBody(env), false); assert.equal(hasManager(env), false); assert.doesNotMatch(env.html(), /固定规则原题40/);
});

test("returning to the same model creates a fresh selection and rejects earlier same-model results", async t => {
  const env = environment(t); await ready(env); await chooseModel(env); await click(env, `展开规则 ${id(40)} v1`); await change(env, "知识读取范围", id(5)); await change(env, "知识读取范围", id(4)); assert.equal(hasBody(env), false); assert.doesNotMatch(env.html(), /固定规则原题40|候选原题10/); env.respond(env.pending(), modelView()); await env.flush(); assert.match(env.html(), /固定规则原题40/);
  await change(env, "知识读取范围", id(4)); const staleSameModel = env.pending(); await change(env, "知识读取范围", id(5), false); await change(env, "知识读取范围", id(4), false); env.respond(staleSameModel, modelView()); await env.flush(); assert.doesNotMatch(env.html(), /固定规则原题40|候选原题10/); assert.equal(hasManager(env), false);
});

test("identity, category, readVersion and refresh transitions hide selected details and manager synchronously", async t => {
  const env = environment(t); await ready(env);
  for (const next of [{ principalId: id(71) }, { categoryId: id(72), categoryName: "另一实际品类名" }, { readVersion: 1 }]) { await chooseModel(env); await click(env, "记录 / 发布办理"); env.setProps(next); assert.equal(hasManager(env), false); assert.equal(hasBody(env), false); assert.doesNotMatch(env.html(), /固定规则原题40/); await ready(env); assert.equal(button(env, "记录 / 发布办理"), undefined); }
  await chooseModel(env); await click(env, `展开候选 ${id(10)} v2`); await click(env, "刷新知识资料"); assert.equal(hasBody(env), false); assert.equal(hasManager(env), false);
});

test("layout disposal prevents late options and knowledge outcomes from reviving old content", async t => {
  const env = environment(t), options = env.pending("/products"), read = env.pending(); env.unmountLayout(); env.respond(options, products()); env.respond(read, categoryView()); await env.flush(); assert.doesNotMatch(env.html(), /候选原题10|可读型号4/); assert.equal(hasBody(env), false); assert.equal(hasManager(env), false);
});

test("read-only catalog has no write form or storage side effects, and empty evidence remains bounded", async t => {
  const env = environment(t); await ready(env, { ...categoryView(), candidates: [] }); assert.match(env.html(), /本次读集没有返回候选或规则/); assert.doesNotMatch(env.html(), /<form|<textarea|<pre|token|\bT[012]\b|本人确认正式发布/); assert.ok(env.calls.every(call => call.body === undefined)); await click(env, "刷新知识资料"); env.reject(env.pending("/products"), Object.assign(Error("型号列表权限拒绝"), { status: 403 })); env.respond(env.pending(), categoryView()); await env.flush(); assert.match(env.html(), /可读型号暂不可读：型号列表权限拒绝/); assert.equal(button(env, "记录 / 发布办理"), undefined); assert.equal(hasManager(env), false);
});
