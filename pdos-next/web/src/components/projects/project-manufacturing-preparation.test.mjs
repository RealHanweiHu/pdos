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
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Existing isolated component state driver, not a browser or HTTP harness. */
const react = { ...React, useState(initial) {
  if (!hooks) return React.useState(initial);
  const own = hooks, index = own.index++;
  if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial;
  return [own.slots[index], next => { if (!own.disposed) { own.slots[index] = typeof next === "function" ? next(own.slots[index]) : next; own.dirty = true; } }];
}, useRef(initial) {
  if (!hooks) return React.useRef(initial);
  const index = hooks.index++; if (!(index in hooks.slots)) hooks.slots[index] = { current: initial }; return hooks.slots[index];
}, useEffect(effect, deps) {
  if (!hooks) return React.useEffect(effect, deps);
  const own = hooks, index = own.index++;
  if (!same(own.slots[index]?.deps, deps)) { const next = { deps, cleanup: own.slots[index]?.cleanup }; own.slots[index] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); }
}, useLayoutEffect(effect, deps) {
  if (!hooks) return React.useLayoutEffect(effect, deps);
  const own = hooks, index = own.index++;
  if (!same(own.slots[index]?.deps, deps)) { const next = { deps, cleanup: own.slots[index]?.cleanup, phase: "layout" }; own.slots[index] = next; own.layouts.push(() => { next.cleanup?.(); next.cleanup = effect(); }); }
} };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { ProjectManufacturingPreparation, PreparationVersion } = load(path.join(directory, "project-manufacturing-preparation.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(6) };
const schema = "pdos-manufacturing-preparation-v1", at = "2026-10-18T01:02:03.888505+08:00";
const source = () => ({ artifact_id: id(4), expected_revision: 3, line: 2, quote: "合成保存依据原句" });
// Synthetic DTOs are parsed by the real project reader; no actual PG/browser evidence is implied.
function version(identity = 10, kind = "work_instruction", projectId = scope.projectId) {
  const input = { project_id: projectId, process: { id: id(5), revision: 2 }, title: `合成${kind}资料`, previous_id: null, expected_previous_revision: null, visibility: "private", reason: "原始保存原因", sources: [source()] };
  if (kind === "work_instruction") Object.assign(input, { operation_key: "assembly", conditions: null, steps: [{ key: "step-1", text: "按本版装配说明\n保持原行", safety_notes: null, sources: [source()], parameters: [
    { key: "pressure", nominal: "9007199254740993.123456789", lower: "-0.000000000001", upper: null, unit: "Pa", sources: [source()] },
    { key: "torque", nominal: null, lower: null, upper: null, unit: null, sources: [] },
  ] }] });
  else if (kind === "control_plan") Object.assign(input, { operation_key: "inspection", checks: [{ key: "check-1", feature: "合成密封检查", method: null, criterion: null, frequency: null, sampling_method: null, reaction_plan: null, responsible_role: null, sources: [source()] }] });
  else Object.assign(input, { operations: [{ operation_key: "assembly", work_instruction: { kind: "work_instruction", id: id(88), revision: 3 }, control_plan: null }, { operation_key: "inspection", work_instruction: null, control_plan: null }], risk_notes: null, packaging_label_basis: "保持固定包装依据" });
  return { schema_version: schema, id: id(identity), kind, revision: 1, series_id: id(identity), project_id: projectId, owner_id: scope.principalId, visibility: "private", title: input.title, status: "draft", purpose: "合成本项目用途", process: { ...input.process }, operation_key: input.operation_key ?? null, previous_id: null, previous_revision: null, created_at: at, is_current: true, source_status: "current", required_source_read_set: [{ artifact_id: id(4), expected_revision: 3 }],
    body: { schema_version: schema, kind, status: "draft", input, scope: { project_id: projectId, purpose: "合成本项目用途" }, process_snapshot: { id: id(5), revision: 2, name: "固定制造配置原名", operations: [{ key: "assembly", name: "固定装配工序" }, { key: "inspection", name: "固定检验工序" }] }, document_bindings: kind === "manufacturing_baseline" ? [{ operation_key: "assembly", kind: "work_instruction", id: id(88), revision: 3, body_sha256: "a".repeat(64) }] : [], gaps: [{ code: "SAVED_UNKNOWN", detail: "保存时扭矩未知，尚未实时重算", operation_key: "assembly", key: "torque", fields: ["nominal", "unit"] }], qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false },
    sources: [source()], receipt_id: id(identity + 100), qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false };
}
function reading(projectId = scope.projectId) { return { schema_version: schema, versions: [version(10, "work_instruction", projectId), version(20, "control_plan", projectId), version(30, "manufacturing_baseline", projectId)], history_page: { next_cursor: null }, has_more: false, unavailable_count: 0, qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false }; }
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate)); if (typeof tree.type === "function") return elements(tree.type(tree.props), predicate); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const calls = [], makeApi = () => (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false }));
  let props = { ...scope, readVersion: 0, api: makeApi() }, instance, tree;
  const dispose = () => { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } };
  function render(commit = true) {
    const wrapper = ProjectManufacturingPreparation(props);
    if (!instance || instance.key !== wrapper.key) { dispose(); instance = { key: wrapper.key, slots: [], index: 0, effects: [], layouts: [], dirty: true, disposed: false }; }
    instance.index = 0; instance.effects = []; instance.layouts = []; instance.dirty = false; hooks = instance;
    try { tree = wrapper.type(wrapper.props); } finally { hooks = null; }
    instance.layouts.forEach(effect => effect()); if (commit) instance.effects.forEach(effect => effect());
  }
  render(); t.after(dispose);
  return { calls, render, tree: () => tree, html: () => renderToStaticMarkup(tree), props: () => props,
    setProps(next, commit = true) { props = { ...props, ...next }; render(commit); }, replaceApi(commit = true) { props = { ...props, api: makeApi() }; render(commit); },
    unmountLayout() { instance.slots.filter(slot => slot?.phase === "layout").forEach(slot => slot.cleanup?.()); },
    pending() { return calls.findLast(call => !call.done); }, respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, value) { assert.ok(call); call.done = true; call.reject(value); },
    async flush() { for (let i = 0; i < 5; i++) { await tick(); if (instance.dirty) render(); } } };
}
async function click(env, label, commit = true) { const button = elements(env.tree(), node => (node.props?.children === label || node.props?.["aria-label"] === label) && typeof node.props.onClick === "function")[0]; assert.ok(button, label); assert.ok(!button.props.disabled, `${label} enabled`); button.props.onClick(); env.render(commit); await env.flush(); }
async function refresh(env, label = "刷新制造资料") { await click(env, label); }
async function ready(env, value = reading(env.props().projectId)) { env.respond(env.pending(), value); await env.flush(); }
const count = env => (env.html().match(/aria-label="制造准备资料 /g) ?? []).length;
function recordHtml(env, identity) { const html = env.html(), start = html.indexOf(`aria-label="制造准备资料 ${identity}"`); assert.ok(start >= 0); return html.slice(start, html.indexOf("</article>", start)); }
const readLabel = (baseline, binding = baseline.body.document_bindings[0]) => `读取基线 ${baseline.id} 工序 ${binding.operation_key} 固定 ${binding.kind} ${binding.id} v${binding.revision}`;
function child(baseline, binding = baseline.body.document_bindings[0]) {
  const fixed = version(Number(binding.id.slice(-12)), binding.kind, baseline.project_id);
  fixed.revision = binding.revision; fixed.operation_key = binding.operation_key; fixed.body.input.operation_key = binding.operation_key;
  fixed.is_current = false; fixed.source_status = "needs_recheck"; fixed.title = "基线固定旧版原标题"; fixed.body.input.title = fixed.title;
  if (binding.kind === "work_instruction") fixed.body.input.steps[0].text = "仅固定旧版保存的作业正文";
  else fixed.body.input.checks[0].feature = "仅固定旧版保存的控制特性";
  return fixed;
}

test("exact project GET renders semantic WI, control checks and baseline refs with raw fixed scope, clocks and receipts", async t => {
  const env = environment(t), value = reading(), original = structuredClone(value); assert.match(env.html(), /正在读取本项目制造准备草稿/); await ready(env, value);
  assert.equal(count(env), 3); assert.equal(env.calls.length, 1); assert.equal(env.calls[0].route, `v1/categories/${scope.categoryId}/products/${scope.productId}/manufacturing-preparations?project_id=${scope.projectId}`);
  const html = env.html(); for (const raw of ["作业指导书草稿", "控制计划草稿", "制造基线草稿", "固定制造配置原名", "固定装配工序", "固定检验工序", "按本版装配说明", "合成密封检查", "保持固定包装依据", at, id(5), ...value.versions.map(row => row.receipt_id)]) assert.ok(html.includes(raw), raw);
  assert.ok(env.calls.every(call => call.body === undefined)); assert.deepEqual(value, original); assert.doesNotMatch(html, /<pre|<form|<input|<select|<textarea|schema_version|已正式发布|全部已就绪/);
});

test("decimal strings, null parameters, unknown criteria and saved gap fields keep their original meanings", async t => {
  const env = environment(t); await ready(env); const html = env.html(); assert.match(html, /9007199254740993\.123456789/); assert.match(html, /-0\.000000000001/); assert.match(html, /判据未知|适用条件：未知/);
  assert.match(html, /torque<\/td><td>未知<\/td><td>未知<\/td><td>未知<\/td><td>未知/); assert.match(html, /保存时扭矩未知，尚未实时重算/); assert.match(html, /SAVED_UNKNOWN · 工序 assembly · 条目 torque · 字段 nominal、unit/);
  assert.doesNotMatch(html, /9007199254740994|默认单位|扭矩就绪/);
});

test("independent series of the same kind, process and title are not merged, and history keeps its own body", async t => {
  const env = environment(t), value = reading(), current = value.versions[0], parallel = version(11), old = version(12);
  current.revision = 2; current.previous_id = old.id; current.previous_revision = 1; current.body.input.previous_id = old.id; current.body.input.expected_previous_revision = 1;
  old.series_id = current.series_id; old.is_current = false; old.body.input.steps[0].text = "历史原步骤不可替换"; old.body.process_snapshot.name = "历史固定制造名";
  value.versions.push(parallel, old); await ready(env, value); assert.equal(count(env), 5); assert.match(env.html(), /本次返回的历史版本（1 条）/);
  assert.ok(recordHtml(env, parallel.id).includes("本系列当前版本")); assert.ok(recordHtml(env, current.id).includes("本系列当前版本")); assert.ok(recordHtml(env, old.id).includes("固定历史版本")); assert.ok(recordHtml(env, old.id).includes("历史原步骤不可替换")); assert.ok(recordHtml(env, old.id).includes("历史固定制造名")); assert.ok(!recordHtml(env, current.id).includes("历史原步骤不可替换"));
});

test("baseline fixed old document identity and hash never borrow a newer current document title or body", async t => {
  const env = environment(t), value = reading(), baseline = value.versions[2], newer = value.versions[0];
  newer.title = "当前新版不可当旧正文"; newer.body.input.title = newer.title; newer.body.input.steps[0].text = "当前新正文不可回填";
  await ready(env, value); const html = recordHtml(env, baseline.id); assert.ok(html.includes(id(88))); assert.ok(html.includes("a".repeat(64))); assert.match(html, /固定 v3/); assert.match(html, /未知 \/ 未提供固定引用/);
  assert.doesNotMatch(html, /当前新版不可当旧正文|当前新正文不可回填/); assert.match(html, /明确选择后才读取固定正文，不从当前文档补齐/); assert.equal(env.calls.length, 1);
});

test("source needs_recheck preserves draft facts without calling it withdrawn, approved or ready", async t => {
  const env = environment(t), value = reading(); value.versions.forEach(row => { row.source_status = "needs_recheck"; }); await ready(env, value);
  assert.equal(count(env), 3); assert.match(env.html(), /来源状态：需重核/); assert.doesNotMatch(env.html(), /来源状态：当前|来源已撤回|已批准|当前可执行/); assert.match(env.html(), /正式发布、人员、工装、物料与库存资格不在本次读集内/);
});

test("has_more concerns history only; unreadable rows and an empty current set are never whole-project zero claims", async t => {
  const env = environment(t), value = reading(); value.has_more = true; value.history_page.next_cursor = "opaque-history"; value.unavailable_count = 2; await ready(env, value);
  assert.equal(count(env), 3); assert.match(env.html(), /尚有历史未读取/); assert.match(env.html(), /2 条资料暂不可读/); assert.doesNotMatch(env.html(), /当前版本未完整|当前缺失 2|全部制造资料已读取/); assert.equal(env.calls.length, 1);
  await refresh(env); value.versions = []; await ready(env, value); assert.equal(count(env), 0); assert.match(env.html(), /本次没有可展示的当前版本资料。仍有历史未读取/); assert.doesNotMatch(env.html(), /本项目没有资料|没有制造准备资料/);
});

test("403, 503 and invalid DTOs hide prior details and remain explicit read failures instead of empty states", async t => {
  const env = environment(t); await ready(env);
  for (const status of [403, 503]) { await refresh(env); assert.equal(count(env), 0); env.reject(env.pending(), Object.assign(Error(`真实${status}读失败`), { status })); await env.flush(); assert.match(env.html(), new RegExp(`真实${status}读失败`)); assert.equal(count(env), 0); assert.doesNotMatch(env.html(), /本次没有可展示|固定制造配置原名/); await refresh(env, "重新读取制造资料"); await ready(env); }
  await refresh(env); const invalid = reading(); invalid.versions[0].project_id = id(99); await ready(env, invalid); assert.equal(count(env), 0); assert.match(env.html(), /未能核对/); assert.doesNotMatch(env.html(), /本次没有可展示/);
});

test("principal, category, product, project and readVersion transitions hide old data synchronously", async t => {
  const env = environment(t); await ready(env);
  for (const next of [{ principalId: id(31) }, { categoryId: id(32) }, { productId: id(33) }, { projectId: id(34) }, { readVersion: 1 }]) { env.setProps(next); assert.equal(count(env), 0); assert.match(env.html(), /正在读取本项目制造准备草稿/); await ready(env); assert.equal(count(env), 3); }
  assert.ok(env.calls.every(call => call.body === undefined));
});

test("API replacement blocks old success or failure before passive cleanup and only publishes the current read", async t => {
  const env = environment(t), old = env.pending(); env.replaceApi(false); const stale = reading(); stale.versions[0].title = "迟到私有旧标题"; stale.versions[0].body.input.title = stale.versions[0].title; env.respond(old, stale); await env.flush(); assert.equal(count(env), 0); assert.doesNotMatch(env.html(), /迟到私有旧标题/);
  await refresh(env); await ready(env); await refresh(env); const oldError = env.pending(); env.replaceApi(); await ready(env); env.reject(oldError, Object.assign(Error("旧身份迟到403"), { status: 403 })); await env.flush(); assert.equal(count(env), 3); assert.doesNotMatch(env.html(), /旧身份迟到403/);
});

test("refresh generations, scope remounts and layout teardown ignore stale pending outcomes", async t => {
  const env = environment(t), first = env.pending(); await refresh(env); const second = env.pending(); await ready(env); env.reject(first, Error("首次读取迟到失败")); await env.flush(); assert.equal(count(env), 3); assert.doesNotMatch(env.html(), /首次读取迟到失败/);
  assert.equal(second.done, true); await refresh(env); const oldScope = env.pending(); env.setProps({ principalId: id(70) }, false); env.reject(oldScope, Error("旧scope迟到失败")); await env.flush(); assert.equal(count(env), 0); assert.doesNotMatch(env.html(), /旧scope迟到失败/);
  await refresh(env); const unmounted = env.pending(); env.unmountLayout(); env.respond(unmounted, reading()); await env.flush(); assert.equal(count(env), 0);
});

test("all actions only read pages or explicit fixed documents and tables have their own scroll region", async t => {
  const env = environment(t); await ready(env); const html = env.html(); assert.match(html, /合成保存依据原句/); assert.ok(html.includes(id(4))); assert.match(html, /行 2/); assert.match(html, /role="region" aria-label="固定参数原值" tabindex="0"/); assert.match(html, /role="region" aria-label="基线固定文档引用" tabindex="0"/);
  const actions = elements(env.tree(), node => typeof node.props?.onClick === "function"); assert.deepEqual(actions.map(action => action.props.children), ["刷新制造资料", "展开固定正文", "回历史首页", "下一页历史"]); assert.ok(env.calls.every(call => call.body === undefined));
});

test("historical pages replace current snapshots and history without accumulating unavailable counts", async t => {
  const env = environment(t), first = reading(), old = version(40); old.is_current = false; old.title = "历史第一页专属正文"; old.body.input.title = old.title; first.versions.push(old); first.has_more = true; first.history_page.next_cursor = "opaque+history/&=1"; first.unavailable_count = 2; await ready(env, first);
  await click(env, "下一页历史"); assert.equal(count(env), 0); assert.match(env.html(), /正在读取所选历史页/); assert.equal(env.pending().route, `v1/categories/${scope.categoryId}/products/${scope.productId}/manufacturing-preparations?project_id=${scope.projectId}&history_cursor=opaque%2Bhistory%2F%26%3D1`);
  const second = reading(), older = version(41); older.is_current = false; older.title = "历史第二页专属正文"; older.body.input.title = older.title; second.versions.push(older); second.versions[0].title = "第二页重新取得当前头"; second.versions[0].body.input.title = second.versions[0].title; second.unavailable_count = 1; await ready(env, second);
  assert.equal(count(env), 4); assert.match(env.html(), /历史分页：本页重新取得当前版本及单页历史/); assert.match(env.html(), /第二页重新取得当前头|历史第二页专属正文/); assert.match(env.html(), /1 条资料暂不可读/); assert.doesNotMatch(env.html(), /历史第一页专属正文|2 条资料暂不可读|3 条资料暂不可读/);
  await refresh(env); assert.equal(count(env), 0); assert.match(env.pending().route, /history_cursor=opaque%2Bhistory/); await ready(env, second); await click(env, "回历史首页"); assert.equal(count(env), 0); assert.equal(env.pending().route, env.calls[0].route); await ready(env); assert.match(env.html(), /历史首页/); assert.doesNotMatch(env.html(), /历史第二页专属正文/);
});

test("an inaccessible historical page hides old facts and still offers server first-page recovery", async t => {
  const env = environment(t), first = reading(); first.has_more = true; first.history_page.next_cursor = "next-page"; await ready(env, first); await click(env, "下一页历史"); env.reject(env.pending(), Object.assign(Error("历史游标已不可用"), { status: 403 })); await env.flush(); assert.equal(count(env), 0); assert.match(env.html(), /历史游标已不可用/); assert.doesNotMatch(env.html(), /本次没有可展示|合成work_instruction资料/); await click(env, "回历史首页"); await ready(env); assert.equal(count(env), 3);
});

test("explicit fixed WI and CP GETs preserve old versions, body, gaps, sources and unverified saved hashes", async t => {
  const env = environment(t), value = reading(), baseline = value.versions[2];
  const wi = baseline.body.document_bindings[0]; wi.revision = 1; baseline.body.input.operations[0].work_instruction.revision = 1;
  const cp = { operation_key: "inspection", kind: "control_plan", id: id(89), revision: 1, body_sha256: "b".repeat(64) }; baseline.body.input.operations[1].control_plan = { kind: cp.kind, id: cp.id, revision: cp.revision }; baseline.body.document_bindings.push(cp);
  const newer = value.versions[0]; newer.revision = 2; newer.series_id = wi.id; newer.previous_id = wi.id; newer.previous_revision = 1; newer.body.input.previous_id = wi.id; newer.body.input.expected_previous_revision = 1; newer.title = "当前新WI不替代基线"; newer.body.input.title = newer.title; newer.body.input.steps[0].text = "当前版新作业内容";
  await ready(env, value); assert.equal(env.calls.length, 1); assert.doesNotMatch(env.html(), /基线固定旧版原标题|仅固定旧版保存的作业正文/);
  await click(env, readLabel(baseline)); assert.equal(env.pending().route, `v1/categories/${scope.categoryId}/products/${scope.productId}/manufacturing-preparations/work_instruction/${id(88)}?revision=1`); assert.match(env.html(), /尚未取得标题、正文与原缺项/); assert.doesNotMatch(env.html(), /基线固定旧版原标题/);
  await ready(env, child(baseline)); const fixedHtml = recordHtml(env, baseline.id); for (const raw of ["基线固定旧版原标题", "仅固定旧版保存的作业正文", "固定历史版本", "来源状态：需重核", "9007199254740993.123456789", "保存时扭矩未知", "合成保存依据原句", "正文读取接口未返回可复验的正文指纹", "a".repeat(64)]) assert.ok(fixedHtml.includes(raw), raw); assert.doesNotMatch(fixedHtml, /当前版新作业内容|当前新WI不替代基线|指纹已验证|来源已撤回/);
  await click(env, readLabel(baseline, cp)); assert.doesNotMatch(recordHtml(env, baseline.id), /仅固定旧版保存的作业正文/); assert.match(env.pending().route, /control_plan\/.*revision=1$/); await ready(env, child(baseline, cp)); assert.match(recordHtml(env, baseline.id), /仅固定旧版保存的控制特性/); assert.doesNotMatch(recordHtml(env, baseline.id), /仅固定旧版保存的作业正文/); assert.ok(env.calls.every(call => call.body === undefined));
});

test("same document in separate baselines requires a new read and cannot publish the other binding's late result", async t => {
  const env = environment(t), value = reading(), baseline = value.versions[2], second = version(31, "manufacturing_baseline"); second.body.document_bindings[0].body_sha256 = "c".repeat(64); value.versions.push(second); await ready(env, value);
  await click(env, readLabel(baseline)); const stale = env.pending(); await click(env, readLabel(second), false); env.respond(stale, child(baseline)); await env.flush(); assert.doesNotMatch(env.html(), /基线固定旧版原标题|仅固定旧版保存的作业正文/);
  await click(env, readLabel(second)); await ready(env, child(second)); assert.match(recordHtml(env, second.id), /仅固定旧版保存的作业正文/); assert.doesNotMatch(recordHtml(env, baseline.id), /基线固定旧版原标题/); assert.ok(recordHtml(env, second.id).includes("c".repeat(64))); assert.equal(env.calls.filter(call => call.route.includes("/work_instruction/")).length, 2);
});

test("fixed read retry clears prior body and a permission or fixed-scope failure hides all private old details", async t => {
  const env = environment(t), value = reading(), baseline = value.versions[2]; await ready(env, value); await click(env, readLabel(baseline)); await ready(env, child(baseline)); await click(env, readLabel(baseline)); assert.doesNotMatch(env.html(), /基线固定旧版原标题/); env.reject(env.pending(), Object.assign(Error("固定正文临时失败"), { status: 503 })); await env.flush(); assert.match(env.html(), /固定正文临时失败/); assert.doesNotMatch(env.html(), /仅固定旧版保存的作业正文/); await click(env, "重新读取固定正文"); await ready(env, child(baseline));
  await click(env, readLabel(baseline)); env.reject(env.pending(), Object.assign(Error("原文权限已收窄"), { status: 403 })); await env.flush(); assert.equal(count(env), 0); assert.doesNotMatch(env.html(), /基线固定旧版原标题|仅固定旧版保存的作业正文|合成manufacturing_baseline资料/); assert.match(env.html(), /已隐藏本页旧资料：原文权限已收窄/);
  await refresh(env, "重新读取制造资料"); await ready(env, value); await click(env, readLabel(baseline)); const mismatch = child(baseline); mismatch.operation_key = "inspection"; mismatch.body.input.operation_key = "inspection"; await ready(env, mismatch); assert.equal(count(env), 0); assert.match(env.html(), /未能核对/);
});

test("collapse, page, refresh, API, scope and layout teardown suppress stale fixed bodies", async t => {
  const env = environment(t), value = reading(), baseline = value.versions[2]; value.has_more = true; value.history_page.next_cursor = "page-2"; await ready(env, value);
  await click(env, readLabel(baseline)); const collapse = env.pending(); await click(env, "收起固定正文"); env.respond(collapse, child(baseline)); await env.flush(); assert.doesNotMatch(env.html(), /基线固定旧版原标题|已选基线固定正文/);
  await click(env, readLabel(baseline)); const oldPage = env.pending(); await click(env, "下一页历史"); env.respond(oldPage, child(baseline)); await env.flush(); assert.equal(count(env), 0); await ready(env);
  const current = reading().versions[2]; await click(env, readLabel(current)); const oldRefresh = env.pending(); await refresh(env); env.respond(oldRefresh, child(current)); await env.flush(); assert.equal(count(env), 0); await ready(env);
  await click(env, readLabel(current)); const oldApi = env.pending(); env.replaceApi(false); env.respond(oldApi, child(current)); await env.flush(); assert.equal(count(env), 0); await refresh(env); await ready(env);
  await click(env, readLabel(current)); const oldScope = env.pending(); env.setProps({ readVersion: 1 }, false); env.reject(oldScope, Object.assign(Error("旧固定正文迟到403"), { status: 403 })); await env.flush(); assert.equal(count(env), 0); assert.doesNotMatch(env.html(), /旧固定正文迟到403/); await refresh(env); await ready(env);
  await click(env, readLabel(current)); const unmount = env.pending(); env.unmountLayout(); env.respond(unmount, child(current)); await env.flush(); assert.doesNotMatch(env.html(), /基线固定旧版原标题|仅固定旧版保存的作业正文/);
});

test("pure version SSR renders fixed old facts without recursively reading baseline children", () => {
  const baseline = version(30, "manufacturing_baseline"), old = child(baseline), before = structuredClone(old);
  const html = renderToStaticMarkup(React.createElement(PreparationVersion, { value: old })); assert.match(html, /基线固定旧版原标题|仅固定旧版保存的作业正文/); assert.match(html, /固定历史版本/); assert.deepEqual(old, before); assert.doesNotMatch(html, /展开固定正文|<button|<form|<pre/);
  const refs = renderToStaticMarkup(React.createElement(PreparationVersion, { value: baseline })); assert.ok(refs.includes(id(88))); assert.ok(refs.includes("a".repeat(64))); assert.doesNotMatch(refs, /仅固定旧版保存的作业正文|<button/);
});
