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
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Isolated component state driver; the strict reader has separate DTO and transport checks. */
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
  if (!same(own.slots[index]?.deps, deps)) { const prior = own.slots[index], next = { deps, cleanup: prior?.cleanup }; own.slots[index] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); }
}, useLayoutEffect(effect, deps) {
  if (!hooks) return React.useLayoutEffect(effect, deps);
  const own = hooks, index = own.index++;
  if (!same(own.slots[index]?.deps, deps)) { const prior = own.slots[index], next = { deps, cleanup: prior?.cleanup, phase: "layout" }; own.slots[index] = next; own.layouts.push(() => { next.cleanup?.(); next.cleanup = effect(); }); }
} };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
// This boundary supplies already validated reader values to exercise component state only.
const boundary = { readProjectBuildOutput(api, scope, build) { return api(`component-output-read/${scope.categoryId}/${scope.productId}/${scope.projectId}/${build.id}`); } };
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react : name === "@/lib/project-build-output" ? boundary : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { ProjectBuildOutput } = load(path.join(directory, "project-build-output.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3) };
const fixed = (n, name) => ({ id: id(n), revision: n, name });
const base = n => ({ id: id(n), revision: 1, createdAt: "2026-10-18T01:02:03.123456+00:00", sourceStatus: "current" });
function build(n = 4) { return { id: id(n), revision: 3, name: `合成Build ${n}`, project_id: scope.projectId, engineering_configuration: fixed(6, "计划工程"), manufacturing_configuration: fixed(7, "计划制造") }; }
function reading(selectedBuild = build()) {
  return { build: selectedBuild, productUnavailableCount: 0, productHasMore: false,
    actualConfigurations: [{ ...base(10), observedAt: "2026-10-18T01:00:00.888505+08:00", plannedEngineering: fixed(6, "计划工程"), plannedManufacturing: fixed(7, "计划制造"), actualEngineering: fixed(8, "实际工程甲"), actualManufacturing: fixed(9, "实际制造乙") }],
    lots: [{ ...base(11), lotLabel: "合成批次L1", actualConfiguration: { id: id(10), revision: 1 }, observedUnitCount: 4, identifiedCount: 3, remainingUnitCount: 1, buildObservedUnitCount: 4, unit: "件", observation: { system: "合成观测系统", externalId: "OBS-SYNTHETIC", nature: "synthetic", occurredAt: "2026-10-18T01:02:03.888505+08:00", receivedAt: "2026-10-18T01:02:04.999999+00:00" } }],
    allocations: [{ ...base(12), lotId: id(11), actualConfigurationId: id(10), unitCount: 3, sampleIds: [id(13), id(14), id(15)] }],
    samples: [{ ...base(13), label: "合成样件S1", lotId: id(11), allocationId: id(12), actualConfiguration: { id: id(10), revision: 1 }, operationKey: "OP-登记", cavity: "C2", custodianId: id(16), custodianLabel: "合成保管人", location: "登记位置A", destination: "登记去向B", recordedAvailability: "hold", observationNature: "synthetic" }] };
}
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const calls = [], rejected = [], api = (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false }));
  let props = { api, scope, build: build(), onAccessRejected: message => rejected.push(message) }, instance, tree;
  const dispose = () => { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } };
  function render(commit = true) {
    const wrapper = ProjectBuildOutput(props);
    if (!instance || instance.key !== wrapper.key) { dispose(); instance = { key: wrapper.key, slots: [], index: 0, effects: [], layouts: [], dirty: true, disposed: false }; }
    instance.index = 0; instance.effects = []; instance.layouts = []; instance.dirty = false; hooks = instance;
    try { tree = wrapper.type(wrapper.props); } finally { hooks = null; }
    instance.layouts.forEach(effect => effect());
    if (commit) instance.effects.forEach(effect => effect());
  }
  render(); t.after(dispose);
  return { calls, rejected, render, props: () => props, tree: () => tree, html: () => renderToStaticMarkup(tree), unmountLayout() { instance.slots.filter(slot => slot?.phase === "layout").forEach(slot => slot.cleanup?.()); },
    setProps(next, commit = true) { props = { ...props, ...next }; render(commit); }, replaceApi() { props = { ...props, api: (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false })) }; render(); },
    pending() { return calls.findLast(call => !call.done); }, respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, value) { assert.ok(call); call.done = true; call.reject(value); },
    async flush() { for (let i = 0; i < 5; i++) { await tick(); if (instance.dirty) render(); } } };
}
function button(env, label) { return elements(env.tree(), node => node.props?.children === label && typeof node.props.onClick === "function")[0]; }
async function click(env, label) { const target = button(env, label); assert.ok(target, label); target.props.onClick(); env.render(); await env.flush(); }
async function ready(env, value = reading(env.props().build)) { env.respond(env.pending(), value); await env.flush(); }

test("only registered facts are rendered with actual dual configuration, original clocks and explicit synthetic observation", async t => {
  const env = environment(t), value = reading(); assert.match(env.html(), /正在核对本轮实际配置/); await ready(env, value); const html = env.html();
  for (const raw of ["实际工程甲", "实际制造乙", "计划工程", "计划制造", "合成批次L1", "合成样件S1", "C2", "合成保管人", "登记位置A", "登记去向B", "合成观测记录", "暂缓使用", value.actualConfigurations[0].observedAt, value.lots[0].observation.occurredAt, value.lots[0].observation.receivedAt]) assert.ok(html.includes(raw), raw);
  assert.equal(env.calls.length, 1); assert.ok(env.calls.every(call => call.body === undefined)); assert.equal(env.rejected.length, 0);
  assert.doesNotMatch(html, /已到达|已消耗|预约成功|可用库存|试模合格通过|<pre/);
});

test("server identified counts and unreadable allocation sample identities are preserved without fabricating sample rows", async t => {
  const env = environment(t), value = reading(); await ready(env, value); const html = env.html();
  assert.match(html, /已登记单件标识数<\/dt><dd>3/); assert.match(html, /尚未登记单件标识数<\/dt><dd>1/);
  assert.equal((html.match(/aria-label="样件登记 /g) ?? []).length, 1); assert.ok(html.includes(id(14))); assert.ok(html.includes(id(15))); assert.match(html, /样件名称暂不可读/);
});

test("null and empty registration fields are not filled from IDs, allocation names or an inferred current location", async t => {
  const env = environment(t), value = reading(), sample = value.samples[0]; sample.cavity = null; sample.operationKey = ""; sample.custodianLabel = ""; sample.location = null; sample.destination = ""; sample.recordedAvailability = "unknown";
  await ready(env, value); const html = env.html(); assert.match(html, /模穴：未登记/); assert.match(html, /工序：未登记/); assert.match(html, /保管人：姓名未登记/); assert.match(html, /位置：未登记/); assert.match(html, /登记可用性：未知/); assert.ok(html.includes(sample.custodianId));
  assert.doesNotMatch(html, /合成保管人|登记位置A|登记去向B|暂缓使用/);
});

test("partial product coverage cannot be relabelled as an empty Build or a zero missing count", async t => {
  const env = environment(t), value = reading(); value.actualConfigurations = []; value.lots = []; value.allocations = []; value.samples = []; value.productUnavailableCount = 2; value.productHasMore = true;
  await ready(env, value); const html = env.html(); assert.match(html, /型号范围内 2 条记录暂不可读/); assert.match(html, /该数不是本轮缺失记录数/); assert.match(html, /读取范围尚未完整/); assert.doesNotMatch(html, /尚无本轮|全部已读取|样件 0|批次 0/);
  await click(env, "刷新产出与样件"); value.productUnavailableCount = 0; value.productHasMore = false; await ready(env, value); assert.match(env.html(), /尚无本轮产出批次登记/); assert.match(env.html(), /尚无本轮样件单件标识登记/);
});

test("source-needs-recheck retains registration facts and never upgrades them to current applicability", async t => {
  const env = environment(t), value = reading(); for (const rows of [value.actualConfigurations, value.lots, value.allocations, value.samples]) rows.forEach(row => { row.sourceStatus = "needs_recheck"; });
  await ready(env, value); assert.match(env.html(), /来源需重核/); assert.match(env.html(), /合成样件S1/); assert.doesNotMatch(env.html(), /来源当前可读|当前可执行|已经批准/);
});

test("503 hides old output independently and stays retryable while access or protocol failure rejects the parent Build", async t => {
  const env = environment(t); await ready(env); await click(env, "刷新产出与样件"); assert.doesNotMatch(env.html(), /合成样件S1|实际工程甲/);
  env.reject(env.pending(), Object.assign(Error("临时读失败"), { status: 503 })); await env.flush(); assert.match(env.html(), /临时读失败/); assert.doesNotMatch(env.html(), /尚无本轮/); assert.equal(env.rejected.length, 0);
  await click(env, "重新读取产出与样件"); await ready(env); await click(env, "刷新产出与样件"); env.reject(env.pending(), Object.assign(Error("读权限变化"), { status: 403 })); await env.flush(); assert.equal(env.rejected.length, 1); assert.match(env.rejected[0], /读权限变化/); assert.doesNotMatch(env.html(), /合成样件S1/);
  await click(env, "重新读取产出与样件"); env.reject(env.pending(), Error("固定链不匹配")); await env.flush(); assert.equal(env.rejected.length, 2); assert.doesNotMatch(env.html(), /尚无本轮/);
});

test("scope, API and refreshed Build objects hide old output synchronously and ignore old successes", async t => {
  const env = environment(t); await ready(env);
  for (const change of [{ scope: { ...scope, categoryId: id(31) } }, { scope: { ...scope, productId: id(32) } }, { scope: { ...scope, projectId: id(33) } }, { build: build(34) }, { build: { ...build(34), revision: 4 } }, { build: { ...build(34), revision: 4 } }]) {
    env.setProps(change); assert.doesNotMatch(env.html(), /合成样件S1|实际工程甲/); assert.match(env.html(), /正在核对本轮实际配置/); await ready(env);
  }
  await click(env, "刷新产出与样件"); const old = env.pending(); env.replaceApi(); assert.doesNotMatch(env.html(), /合成样件S1/); await ready(env); const stale = reading(); stale.samples[0].label = "迟到旧样件"; env.respond(old, stale); await env.flush(); assert.doesNotMatch(env.html(), /迟到旧样件/); assert.match(env.html(), /合成样件S1/);
});

test("late errors cannot invoke the old parent callback after scope, API, Build or refresh changes", async t => {
  const env = environment(t), original = env.pending(); env.setProps({ build: build(40) }); await ready(env); env.reject(original, Object.assign(Error("旧Build403"), { status: 403 })); await env.flush(); assert.equal(env.rejected.length, 0); assert.doesNotMatch(env.html(), /旧Build403/);
  await click(env, "刷新产出与样件"); const lateRefresh = env.pending(); await click(env, "刷新产出与样件"); await ready(env); env.reject(lateRefresh, Error("旧刷新协议失败")); await env.flush(); assert.equal(env.rejected.length, 0); assert.match(env.html(), /合成样件S1/);
  await click(env, "刷新产出与样件"); const beforeEffects = env.pending(); env.setProps({ build: { ...env.props().build } }, false); env.reject(beforeEffects, Object.assign(Error("提交新props后旧403"), { status: 403 })); await env.flush(); assert.equal(env.rejected.length, 0); assert.doesNotMatch(env.html(), /提交新props后旧403/);
});

test("callback replacement guards the old request before passive cleanup and uses only the current callback for a new failure", async t => {
  const env = environment(t), old = env.pending(), nextRejected = [];
  env.setProps({ onAccessRejected: message => nextRejected.push(message) }, false);
  env.reject(old, Object.assign(Error("旧回调403"), { status: 403 })); await env.flush(); assert.equal(env.rejected.length, 0); assert.equal(nextRejected.length, 0); assert.doesNotMatch(env.html(), /旧回调403/);
  await click(env, "刷新产出与样件"); env.reject(env.pending(), Object.assign(Error("当前回调403"), { status: 403 })); await env.flush(); assert.equal(env.rejected.length, 0); assert.equal(nextRejected.length, 1); assert.match(nextRejected[0], /当前回调403/);
});

test("a removed scope cannot call its parent while passive unmount cleanup is still pending", async t => {
  const env = environment(t), old = env.pending(); env.unmountLayout();
  env.reject(old, Object.assign(Error("卸载旧scope403"), { status: 403 })); await env.flush(); assert.equal(env.rejected.length, 0); assert.doesNotMatch(env.html(), /卸载旧scope403/);
});

test("read-only registration pane has no business mutation, storage or inferred write action", async t => {
  const env = environment(t); await ready(env); const controls = elements(env.tree(), node => typeof node.props?.onClick === "function"); assert.equal(controls.length, 1); assert.equal(controls[0].props.type, "button");
  assert.ok(env.calls.every(call => call.body === undefined)); const source = readFileSync(path.join(directory, "project-build-output.tsx"), "utf8"); assert.doesNotMatch(source, /localStorage|sessionStorage|commands|fetch\(/);
});
