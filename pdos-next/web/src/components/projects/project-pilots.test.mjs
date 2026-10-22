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
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Existing isolated state driver, not actual HTTP or browser verification. */
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
const { ProjectPilots } = load(path.join(directory, "project-pilots.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const clone = value => structuredClone(value);
const scope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) };
const at = "2026-10-18T12:34:56.123456+08:00", saved = "2026-10-18T08:40:00.654321Z", start = "2026-10-18T12:00:00.888505+08:00", finish = "2026-10-18T13:00:00+08:00";
const source = () => ({ kind: "artifact", id: id(5), revision: 1, position: `line:3;quote_sha256:${"a".repeat(64)}` });
const ref = (kind, n) => ({ kind, id: id(n), revision: 1 });
const basis = () => ({ build: ref("build", 6), lot: ref("build_lot", 7), actual_configuration: ref("actual_configuration", 8), engineering_configuration: ref("engineering_configuration", 9), process_revision: ref("process_revision", 10), unit: "件" });
const conservative = { qualification: "unknown", start_authorized: false, manufacturing_release: null, external_delivery: false };
const boundScope = input => ({ tenant_id: id(11), product_id: input.productId, project_id: input.projectId });
// All fixtures below are synthetic and use the real guarded project reader.
function metadata(n, revision, input) { return { id: id(n), revision, created_at: saved, owner_id: id(12), writer_id: id(12), visibility: "private", receipt_id: id(n + 100), source_status: "needs_recheck", sources: [source()], required_source_read_set: [{ artifact_id: id(5), expected_revision: 1 }], material: { pilot: { scope: boundScope(input), category_id: input.categoryId, basis: basis(), engineering_configuration: { definition: { id: id(44), revision: 5 } }, opaque_internal: "must-not-dump-material" }, statistics: null, fixed_scope: null }, gaps: [{ code: "SAVED_GAP", detail: "保存时资源未知，不代表实时准备度", state: "unknown" }], ...conservative }; }
const counts = complete => ({ input_count: 4, output_count: 4, first_pass: 2, first_failed: 2, first_unknown: 0, final_good: complete ? 4 : 2, reworked_good: complete ? 2 : 0, scrap: 0, rework_pending: complete ? 0 : 2, undecided: 0, unprocessed: 0, rework_cycles: complete ? 2 : 0 });
const rate = complete => ({ numerator: complete ? 4 : 2, denominator: 4, value: complete ? "1.000000000000000000000000000" : null, recorded_fraction: complete ? "1.000000000000000000000000000" : "0.5000000000000000000000000000", partition_complete: complete, state: complete ? "known" : "partial" });
function observation(pilotId, n, revision, previous, complete, input) {
  const yieldScope = { basis: basis(), manufacturing_baseline: ref("manufacturing_baseline", 13), line: ref("line", 14), cohort_key: "fixed-cohort", window_start: start, window_end: finish, criterion: ref("criterion", 15), nature: "synthetic", minimum_sample: 1 };
  const fixed = { schema_version: "pdos-pilot-result-scope-v1", scope: boundScope(input), pilot_id: pilotId, pilot_revision: revision - 1, purpose: "固定统计用途原文", site: "合成固定地点", original_timezone: "Asia/Shanghai", yield_scope: clone(yieldScope), cohort: { population_count: 4, fixed_input_count: 4, mode: "entire_lot", denominator_policy: "all_fixed_input_units", statistics_basis_key: "original-statistics", unit_refs: null, source: source() } };
  return { ...metadata(n, revision, input), pilot_id: pilotId, pilot_revision_before: revision - 1, previous_observation_id: previous, record: { observation_id: id(n), expected_pilot_revision: revision - 1, previous_observation_id: previous, correction_reason: previous ? "固定更正原因，沿用原投入" : null, scope: yieldScope, counts: counts(complete), units: [], exceptions: [{ key: "exception-1", description: "原始异常说明", issue: ref("issue", 80), disposition: null, source: source() }], observed: { occurred_at: at, original_timezone: "Asia/Shanghai", effective_at: null, source: source() }, source: source() }, fixed_scope: fixed, projection: { schema_version: "pdos-pilot-result-projection-v1", fixed: clone(fixed), observation_id: id(n), received_at: null, counts: counts(complete), metrics: { first_pass_yield: { numerator: 2, denominator: 4, value: "5.000000000000000000000000E-1", recorded_fraction: "0.5", partition_complete: true, state: "known" }, final_good_yield: rate(complete), warnings: complete ? [] : ["FINAL_GOOD_PARTITION_NOT_FINAL"], process_capability: "NOT_ASSESSED", factory_qualification: "NOT_ASSESSED", start_authorized: false, manufacturing_release: null, external_delivery_authorized: false } } };
}
function item(n = 20, input = scope, withObservations = true) { const observations = withObservations ? [observation(id(n), n + 1, 2, null, false, input), observation(id(n), n + 2, 3, id(n + 1), true, input)] : []; return { schema_version: "pdos-native-pilot-v1", project_id: input.projectId, pilot: { ...metadata(n, 1, input), details: { pilot_id: id(n), basis: basis(), purpose: `合成固定试产${n}`, source: source(), manufacturing_baseline: ref("manufacturing_baseline", 13), line: null }, statistics_basis: { statistics_basis_key: "原声明口径", site: "原声明地点", window_start: start, window_end: finish, original_timezone: "Asia/Shanghai", cohort_mode: "entire_lot", samples: [], criterion_id: id(15), criterion_revision: 1, criterion_text: "固定判据原文", minimum_sample: 1, operation_key: "assembly", operational_scope: null, source: source() } }, current: { revision: observations.length + 1, epoch: observations.length + 1, latest_observation_id: observations.at(-1)?.id ?? null }, observations, ...conservative }; }
const page = (input = scope) => ({ schema_version: "pdos-native-pilot-v1", project_id: input.projectId, items: [item(20, input), item(30, input)], next_cursor: id(30), qualification: "unknown", manufacturing_release: null });
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const calls = [], makeApi = () => (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false }));
  let props = { ...scope, readVersion: 0, api: makeApi() }, instance, tree;
  const dispose = () => { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } };
  function render(commit = true) { const wrapper = ProjectPilots(props); if (!instance || instance.key !== wrapper.key) { dispose(); instance = { key: wrapper.key, slots: [], index: 0, effects: [], layouts: [], dirty: true, disposed: false }; } instance.index = 0; instance.effects = []; instance.layouts = []; instance.dirty = false; hooks = instance; try { tree = wrapper.type(wrapper.props); } finally { hooks = null; } instance.layouts.forEach(effect => effect()); if (commit) instance.effects.forEach(effect => effect()); }
  render(); t.after(dispose);
  return { calls, render, tree: () => tree, html: () => renderToStaticMarkup(tree), props: () => props, setProps(next, commit = true) { props = { ...props, ...next }; render(commit); }, replaceApi(commit = true) { props = { ...props, api: makeApi() }; render(commit); }, unmountLayout() { instance.slots.filter(slot => slot?.phase === "layout").forEach(slot => slot.cleanup?.()); }, pending() { return calls.findLast(call => !call.done); }, respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, value) { assert.ok(call); call.done = true; call.reject(value); }, async flush() { for (let i = 0; i < 5; i++) { await tick(); if (instance.dirty) render(); } } };
}
function button(env, label) { return elements(env.tree(), node => (node.props?.children === label || node.props?.["aria-label"] === label) && typeof node.props.onClick === "function")[0]; }
async function click(env, label, commit = true) { const target = button(env, label); assert.ok(target, label); assert.ok(!target.props.disabled, `${label} is enabled`); target.props.onClick(); env.render(commit); await env.flush(); }
async function respond(env, value = page(env.props())) { env.respond(env.pending(), value); await env.flush(); }
const choose = (env, n = 20) => click(env, `展开试产记录 ${id(n)}`);
const hasSelection = env => /aria-label="已选试产 /.test(env.html());
const visibleText = env => env.html().replace(/<[^>]*>/g, "");

test("one guarded list GET contains complete records; explicit selection is local and root v1 stays separate from Current", async t => {
  const env = environment(t), value = page(), before = clone(value); await respond(env, value); assert.equal(env.calls.length, 1); assert.equal(hasSelection(env), false); await choose(env); assert.equal(env.calls.length, 1); assert.equal(hasSelection(env), true); assert.match(visibleText(env), /固定原准备 v1 · 当前链 v3 · epoch 3/); assert.equal((env.html().match(/aria-label="试产观察 /g) ?? []).length, 2); assert.ok(env.html().includes(id(22))); assert.deepEqual(value, before);
  assert.equal(env.calls[0].route, `v1/categories/${scope.categoryId}/products/${scope.productId}/pilots?project_id=${scope.projectId}`); assert.ok(env.calls.every(call => call.body === undefined)); assert.doesNotMatch(env.html(), /尚未读取明细|正在回读所选试产/);
});

test("server partial and known rates keep raw decimal, value-null, recorded_fraction and partition flags without percentages", async t => {
  const env = environment(t); await respond(env); await choose(env); const html = env.html(), text = visibleText(env);
  for (const raw of ["5.000000000000000000000000E-1", "0.5000000000000000000000000000", "1.000000000000000000000000000", "未知（原值为空）", "部分（partial）", "已知（known）", "否（false）", "是（true）"]) assert.ok(html.includes(raw), raw);
  assert.doesNotMatch(text, /50\.00%|100\.00%|总体良率|平均良率/); assert.match(text, /未换算百分比/); assert.match(text, /更正不作为新增投入，不跨观察求和/); assert.match(html, /固定更正原因，沿用原投入/);
});

test("fixed root references, declared statistics, actual cohort and null membership stay distinct", async t => {
  const env = environment(t); await respond(env); await choose(env); const html = env.html(); for (const raw of [id(6), id(7), id(8), id(9), id(10), id(13), id(44), "固定产品定义", "原声明口径", "固定判据原文", "固定统计用途原文", "all_fixed_input_units", "original-statistics", "未提供成员枚举；不等于零成员", "原列表为空，不代表全部成员"]) assert.ok(html.includes(raw), raw);
  assert.match(html, /固定投入分母<\/dt><dd>4/); assert.match(html, /母批数量<\/dt><dd>4/); assert.doesNotMatch(html, /默认分母|按产出作分母/);
});

test("null original batch counts preserve actual per-unit observations and separate server projected counts", async t => {
  const env = environment(t), value = page(), observation = value.items[0].observations[0]; observation.record.counts = null;
  observation.record.units = Array.from({ length: 4 }, (_, index) => ({ sample: ref("sample", 200 + index), first_result: index < 2 ? "pass" : "fail", final_state: index < 2 ? "good" : "rework_pending", rework_cycles: 0, source: source() }));
  observation.fixed_scope.cohort.unit_refs = observation.record.units.map(unit => clone(unit.sample)); observation.projection.fixed = clone(observation.fixed_scope);
  await respond(env, value); await choose(env); assert.match(env.html(), /原批次计数为空，保留逐件原记录，不补零/); assert.match(env.html(), /aria-label="逐件原始观察"/); for (const n of [200, 201, 202, 203]) assert.ok(env.html().includes(id(n))); assert.match(env.html(), /服务器投影计数/); assert.match(env.html(), /返工待定/); assert.equal(env.calls.length, 1);
});

test("a retained fixed scope with null projection remains visible without borrowed or zero statistics", async t => {
  const env = environment(t), value = page(), pilot = value.items[0]; pilot.observations = [pilot.observations[0]]; pilot.current = { revision: 2, epoch: 2, latest_observation_id: pilot.observations[0].id }; pilot.observations[0].projection = null;
  await respond(env, value); await choose(env); assert.match(env.html(), /本观察投影为空，未提供良率结论/); assert.match(env.html(), /固定投入分母<\/dt><dd>4/); assert.doesNotMatch(env.html(), /aria-label="服务器比例原值"|5\.000000|1\.000000/); assert.match(env.html(), /保存时资源未知/);
});

test("unknown counts or denominator and zero numerator remain explicit values instead of defaulting null to zero", async t => {
  const env = environment(t), value = page(), observation = value.items[0].observations[0]; observation.record.counts.input_count = null; observation.projection.counts.input_count = null; observation.fixed_scope.cohort.fixed_input_count = null; observation.projection.fixed = clone(observation.fixed_scope); observation.projection.metrics.final_good_yield = { numerator: 0, denominator: null, value: null, recorded_fraction: null, partition_complete: false, state: "unknown" };
  await respond(env, value); await choose(env); assert.match(env.html(), /固定投入分母<\/dt><dd>未知（原值为空）/); assert.match(env.html(), /<td>最终合格率<\/td><td>0<\/td><td>未知（原值为空）/); assert.match(env.html(), /未知（unknown）/);
});

test("event, save time, projection null receive time, source state, exceptions and qualification facts stay separate", async t => {
  const env = environment(t); await respond(env); await choose(env); const html = env.html(); for (const raw of [at, saved, start, finish, "观察保存原时点", "原值为空，不作为收到时点", "原始异常说明", id(80), id(121), id(122), "来源需重核", "资格未知（unknown）", "启动授权为否（false）", "制造放行为空（null）"]) assert.ok(html.includes(raw), raw);
  assert.doesNotMatch(html, /来源已撤回|资源资格通过|已具名放行|must-not-dump-material|\bT[012]\b|confirmation_token|<pre/);
});

test("a readable preparation without observations does not fabricate statistics or a start event", async t => {
  const env = environment(t), value = page(); value.items = [item(20, scope, false)]; value.next_cursor = null; value.items[0].pilot.statistics_basis = null; await respond(env, value); await choose(env); assert.match(env.html(), /本条已返回记录未含原始观察；原准备不代表已开工/); assert.match(env.html(), /原准备未提供统计声明（原值为空）/); assert.equal((env.html().match(/aria-label="试产观察 /g) ?? []).length, 0); assert.doesNotMatch(env.html(), /aria-label="服务器比例原值"|观察发生原时点/);
});

test("local switching replaces only the selected record and never dispatches a detail read", async t => {
  const env = environment(t); await respond(env); await choose(env); await choose(env, 30); assert.ok(env.html().includes(`aria-label="已选试产 ${id(30)}"`)); assert.ok(!env.html().includes(`aria-label="已选试产 ${id(20)}"`)); assert.ok(!env.html().includes(`aria-label="试产观察 ${id(21)}"`)); assert.equal(env.calls.length, 1);
});

test("server next page and home replace content, clear selection and never accumulate a project total", async t => {
  const env = environment(t); await respond(env); await choose(env); await click(env, "下一页试产记录"); assert.equal(hasSelection(env), false); assert.doesNotMatch(env.html(), /合成固定试产20/); assert.equal(env.pending().route, `v1/categories/${scope.categoryId}/products/${scope.productId}/pilots?project_id=${scope.projectId}&history_cursor=${id(30)}`);
  const next = page(); next.items = [item(40)]; next.next_cursor = null; await respond(env, next); assert.match(visibleText(env), /本页返回 1 条可读试产记录，非项目总数/); assert.doesNotMatch(env.html(), /合成固定试产20/); await click(env, "回首页"); await respond(env); assert.equal(hasSelection(env), false); assert.match(visibleText(env), /本页返回 2 条可读试产记录/);
});

test("empty pages and failed cursors remain distinct, with explicit home recovery from an unreadable page", async t => {
  const env = environment(t); await respond(env); await click(env, "下一页试产记录"); env.reject(env.pending(), Object.assign(Error("历史页读权限变化"), { status: 403 })); await env.flush(); assert.match(env.html(), /历史页读权限变化/); assert.doesNotMatch(env.html(), /本页返回 0|本页没有可展示/); await click(env, "回首页"); await respond(env); await click(env, "下一页试产记录"); const empty = page(); empty.items = []; empty.next_cursor = null; await respond(env, empty); assert.match(env.html(), /本页没有可展示的试产记录，不据此判断整个项目/); assert.equal(hasSelection(env), false);
});

test("refresh and principal, category, product, project, API or readVersion changes immediately hide old selection and body", async t => {
  const env = environment(t); await respond(env); await choose(env); await click(env, "刷新本页试产记录"); assert.equal(hasSelection(env), false); assert.doesNotMatch(env.html(), /合成固定试产20|固定更正原因/); await respond(env); assert.equal(hasSelection(env), false); await choose(env);
  for (const next of [{ principalId: id(61) }, { categoryId: id(62) }, { productId: id(63) }, { projectId: id(64) }, { readVersion: 1 }]) { env.setProps(next); assert.equal(hasSelection(env), false); assert.doesNotMatch(env.html(), /合成固定试产20|固定更正原因/); await respond(env); await choose(env); }
  env.replaceApi(); assert.equal(hasSelection(env), false); assert.doesNotMatch(env.html(), /合成固定试产20/); await respond(env); assert.equal(hasSelection(env), false);
});

test("late page/API outcomes before passive cleanup and after layout teardown cannot reveal stale data", async t => {
  const env = environment(t), first = env.pending(); await click(env, "刷新本页试产记录"); await respond(env); env.respond(first, page()); await env.flush(); assert.equal(hasSelection(env), false); await choose(env); await click(env, "刷新本页试产记录"); const old = env.pending(); env.replaceApi(false); env.reject(old, Object.assign(Error("旧API迟到403"), { status: 403 })); await env.flush(); assert.doesNotMatch(env.html(), /旧API迟到403|合成固定试产20/);
  await click(env, "刷新本页试产记录"); const pending = env.pending(); env.unmountLayout(); env.respond(pending, page()); await env.flush(); assert.doesNotMatch(env.html(), /合成固定试产20/);
});

test("failed reads or broken Current bindings never become successful empty records", async t => {
  const env = environment(t); env.reject(env.pending(), Object.assign(Error("实际503读取失败"), { status: 503 })); await env.flush(); assert.match(env.html(), /实际503读取失败/); assert.doesNotMatch(env.html(), /本页返回 0|本页没有可展示/); await click(env, "重新读取本页试产记录"); const bad = page(); bad.items[0].current.epoch = 9; await respond(env, bad); assert.match(env.html(), /读取不完整/); assert.equal(hasSelection(env), false); assert.doesNotMatch(env.html(), /合成固定试产20/);
});

test("wide source identities, raw counts and metrics use local keyboard-scrollable regions and no write controls", async t => {
  const env = environment(t); await respond(env); await choose(env); const html = env.html(); assert.match(html, /role="region" aria-label="原批次计数" tabindex="0"/); assert.match(html, /role="region" aria-label="服务器比例原值" tabindex="0"/); assert.doesNotMatch(html, /<input|<select|<textarea|<form|保存观察|确认开工/); assert.ok(env.calls.every(call => call.body === undefined));
});
