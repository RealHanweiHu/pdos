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
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Existing isolated state driver; no browser or actual HTTP behavior is implied. */
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
const { ProjectBuildEngineering } = load(path.join(directory, "project-build-engineering.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(60) };
const at = "2026-10-18T01:02:03.888505+08:00";
const source = () => ({ artifact_id: id(50), expected_revision: 2, line: 3, quote: "合成固定工程依据原句" });
// Synthetic data goes through the actual list and fixed-engineering readers.
function base(n, productId) { return { id: id(n), product_id: productId, revision: 1, name: `合成登记${n}`, status: "draft", visibility: "private", owner_id: id(60), created_at: at, sources: [source()], required_source_read_set: [{ artifact_id: id(50), expected_revision: 2 }], source_status: "current" }; }
const series = (n, productId) => ({ ...base(n, productId), series_id: id(n), previous_id: null, expected_previous_revision: null, reason: "合成保存原因原值" });
const external = (basis = null) => ({ system: "合成PLM", external_id: "CAD-fixed", revision: basis ? null : "R2", as_of: basis ? null : at, content_sha256: basis ? null : "a".repeat(64), basis });
function build(n = 4, input = scope) {
  const part = { ...base(n + 30, input.productId), internal_number: "RD-fixed", erp_number: null, customer_number: null, mapping_version: null, external_design_refs: [external(source())], external_verification: "not_checked", mapping_status: "unknown" };
  const bom = { ...series(n + 20, input.productId), name: `固定BOM${n}`, lines: [
    { key: "known", part_id: part.id, expected_part_revision: 1, part, quantity: "9007199254740993.123456789012", unit: "ea", loss_rate: "0.100000000001", critical: true, notes: null },
    { key: "unknown", part_id: part.id, expected_part_revision: 1, part: structuredClone(part), quantity: null, unit: null, loss_rate: null, critical: false, notes: "原值未知，不补默认单位" },
  ] };
  const config = { ...series(n + 10, input.productId), name: `固定工程配置${n}`, definition_id: id(n + 40), definition_revision: 3, definition: { id: id(n + 40), revision: 3, title: `固定定义${n}`, status: "published", visibility: "private", source_status: "current" }, bom_id: bom.id, bom_revision: 1, bom, design_versions: { mechanical: external(), electronic: external(source()), firmware: null }, external_verification: "not_checked" };
  return { id: id(n), revision: 1, name: `合成Build${n}`, purpose: `原始目的${n}`, type: "tool_trial", status: "planned", source_status: "current", owner_id: id(60), visibility: "private", project_id: input.projectId, project_name: "合成本项目", project_revision: 2, planned_quantity: "10", unit: "ea", planned_start: at, planned_end: null, created_at: at, verification_objectives: "合成固定目标", disposition_plan: "合成处置计划", previous_build_id: null, engineering_configuration: config, manufacturing_configuration: { id: id(n + 70), revision: 1, name: "固定制造配置", status: "draft" }, required_source_read_set: [{ artifact_id: id(50), expected_revision: 2 }], readiness: null };
}
const page = (input = scope) => ({ items: [build(4, input), build(5, input)], unavailable_count: 0, has_more: false });
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const calls = [], makeApi = () => (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false }));
  let props = { ...scope, readVersion: 0, api: makeApi() }, instance, tree;
  const dispose = () => { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } };
  function render(commit = true) {
    const wrapper = ProjectBuildEngineering(props);
    if (!instance || instance.key !== wrapper.key) { dispose(); instance = { key: wrapper.key, slots: [], index: 0, effects: [], layouts: [], dirty: true, disposed: false }; }
    instance.index = 0; instance.effects = []; instance.layouts = []; instance.dirty = false; hooks = instance;
    try { tree = wrapper.type(wrapper.props); } finally { hooks = null; }
    instance.layouts.forEach(effect => effect()); if (commit) instance.effects.forEach(effect => effect());
  }
  render(); t.after(dispose);
  return { calls, render, tree: () => tree, html: () => renderToStaticMarkup(tree), props: () => props,
    setProps(next, commit = true) { props = { ...props, ...next }; render(commit); }, replaceApi(commit = true) { props = { ...props, api: makeApi() }; render(commit); },
    unmountLayout() { instance.slots.filter(slot => slot?.phase === "layout").forEach(slot => slot.cleanup?.()); }, pending() { return calls.findLast(call => !call.done); },
    respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, value) { assert.ok(call); call.done = true; call.reject(value); },
    async flush() { for (let i = 0; i < 5; i++) { await tick(); if (instance.dirty) render(); } } };
}
async function click(env, label, commit = true) { const button = elements(env.tree(), node => (node.props?.children === label || node.props?.["aria-label"] === label) && typeof node.props.onClick === "function")[0]; assert.ok(button, label); button.props.onClick(); env.render(commit); await env.flush(); }
async function respond(env, value = page(env.props())) { env.respond(env.pending(), value); await env.flush(); }
async function chosen(env, n = 4, value = page(env.props())) { await click(env, `核对 合成Build${n} 工程配置`); await respond(env, value); }
const hasDetail = env => /aria-label="固定 BOM 每份原值"/.test(env.html());

test("list requires explicit selection, then a fresh exact project Build read exposes only the chosen fixed engineering", async t => {
  const env = environment(t); assert.match(env.html(), /正在读取本项目可读 Build/); await respond(env); assert.equal(env.calls.length, 1); assert.match(env.html(), /尚未选择 Build/); assert.equal(hasDetail(env), false);
  const fresh = page(); const before = structuredClone(fresh); await chosen(env, 5, fresh); assert.equal(hasDetail(env), true); assert.equal(env.calls.length, 2); assert.match(env.html(), /固定定义5/); assert.doesNotMatch(env.html(), /固定定义4|固定BOM4/); assert.deepEqual(fresh, before);
  assert.ok(env.calls.every(call => call.route === `v1/categories/${scope.categoryId}/products/${scope.productId}/builds?project_id=${scope.projectId}` && call.body === undefined));
});

test("fixed BOM quantities, loss and null values are never multiplied by plan or rounded", async t => {
  const env = environment(t); await respond(env); await chosen(env); const html = env.html(); assert.match(html, /9007199254740993\.123456789012/); assert.match(html, /0\.100000000001/); assert.match(html, /不乘 Build 计划数量/); assert.match(html, /原值未知，不补默认单位/);
  assert.match(html, /<td class="mono">未知<\/td><td>未知<\/td><td class="mono">未知/); assert.equal((html.match(/RD-fixed/g) ?? []).length, 2); assert.doesNotMatch(html, /90071992547409930|9007199254740994|物料已齐套|ERP 已确认/);
});

test("both external-ref forms, partial metadata and null slots keep exact clocks and source evidence", async t => {
  const env = environment(t), fresh = page(); fresh.items[0].engineering_configuration.design_versions.firmware = { ...external(source()), revision: "fw-fixed-0.7.3" };
  await respond(env); await chosen(env, 4, fresh); const html = env.html(); for (const raw of ["R2", "fw-fixed-0.7.3", at, "a".repeat(64), source().quote, source().artifact_id, "RD-fixed", "not_checked"]) assert.ok(html.includes(raw), raw);
  assert.match(html, /外部版本原值<\/dt><dd>未知/); assert.match(html, /资料截至时点<\/dt><dd>未知/); assert.match(html, /SHA-256：未知/); assert.doesNotMatch(html, /固件状态：已刷入|已经核实|最新设计|引用已漂移/);
});

test("source recheck and owner UUIDs do not become withdrawal, approval, named designers or freeze facts", async t => {
  const env = environment(t), fresh = page(), config = fresh.items[0].engineering_configuration; config.source_status = "needs_recheck"; config.bom.source_status = "needs_recheck"; config.definition.source_status = "needs_recheck"; config.bom.lines.forEach(line => { line.part.source_status = "needs_recheck"; });
  await respond(env); await chosen(env, 4, fresh); const html = env.html(); assert.match(html, /来源状态：需重核/); assert.ok(html.includes(config.owner_id)); assert.match(html, /记录属主/); assert.doesNotMatch(html, /来源已撤回|已批准|已冻结引用|设计负责人：|接口已确认/);
});

test("partial or unavailable Build coverage cannot be called a complete empty project", async t => {
  const env = environment(t), incomplete = page(); incomplete.items = []; incomplete.has_more = true; incomplete.unavailable_count = 2; await respond(env, incomplete); assert.match(env.html(), /2 条记录暂不可读/); assert.match(env.html(), /列表尚未完整/); assert.match(env.html(), /本次没有可展示的 Build，读取范围尚未完整/); assert.doesNotMatch(env.html(), /尚无本项目 Build 记录/); assert.equal(env.calls.length, 1);
});

test("switching Build hides fixed content immediately and blocks the previous late success", async t => {
  const env = environment(t); await respond(env); await chosen(env); await click(env, "刷新已选工程配置"); const stale = env.pending(); await click(env, "核对 合成Build5 工程配置"); assert.equal(hasDetail(env), false); await respond(env); env.respond(stale, page()); await env.flush(); assert.match(env.html(), /固定定义5/); assert.doesNotMatch(env.html(), /固定定义4/);
});

test("global refresh removes selection and detail, while selected refresh requires a fresh binding read", async t => {
  const env = environment(t); await respond(env); await chosen(env); await click(env, "刷新已选工程配置"); assert.equal(hasDetail(env), false); await respond(env); assert.equal(hasDetail(env), true);
  await click(env, "刷新工程 Build 列表"); assert.equal(hasDetail(env), false); assert.doesNotMatch(env.html(), /合成Build4|固定定义4/); await respond(env); assert.equal(hasDetail(env), false); assert.match(env.html(), /尚未选择 Build/);
});

test("transient detail failure is retryable without old body; access or binding failure clears the old Build list", async t => {
  const env = environment(t); await respond(env); await chosen(env); await click(env, "刷新已选工程配置"); env.reject(env.pending(), Object.assign(Error("临时503"), { status: 503 })); await env.flush(); assert.equal(hasDetail(env), false); assert.match(env.html(), /临时503/); assert.doesNotMatch(env.html(), /固定定义4/);
  await click(env, "重新读取已选工程配置"); await respond(env); await click(env, "刷新已选工程配置"); env.reject(env.pending(), Object.assign(Error("真实权限收窄"), { status: 403 })); await env.flush(); assert.match(env.html(), /已隐藏旧资料/); assert.doesNotMatch(env.html(), /合成Build4|固定定义4|尚无本项目 Build/);
  await click(env, "重新读取工程 Build 列表"); await respond(env); await click(env, "核对 合成Build4 工程配置"); const invalid = page(); invalid.items[0].engineering_configuration.bom.lines[0].part.revision = 2; await respond(env, invalid); assert.match(env.html(), /固定工程配置、定义、BOM 或物料版本无法核对/); assert.equal(hasDetail(env), false); assert.doesNotMatch(env.html(), /合成Build5|固定定义4/);
});

test("scope, identity, API and readVersion changes synchronously hide old list, selection and fixed body", async t => {
  const env = environment(t); await respond(env); await chosen(env);
  for (const next of [{ principalId: id(61) }, { categoryId: id(62) }, { productId: id(63) }, { projectId: id(64) }, { readVersion: 1 }]) { env.setProps(next); assert.equal(hasDetail(env), false); assert.doesNotMatch(env.html(), /合成Build4|固定定义4/); await respond(env); assert.match(env.html(), /尚未选择 Build/); await chosen(env); }
  env.replaceApi(); assert.equal(hasDetail(env), false); assert.doesNotMatch(env.html(), /合成Build4/); await respond(env); assert.match(env.html(), /尚未选择 Build/);
});

test("late detail errors before passive cleanup cannot clear the next choice or identity", async t => {
  const env = environment(t); await respond(env); await click(env, "核对 合成Build4 工程配置"); const old = env.pending(); await click(env, "核对 合成Build5 工程配置", false); env.reject(old, Object.assign(Error("旧Build迟到403"), { status: 403 })); await env.flush(); assert.doesNotMatch(env.html(), /旧Build迟到403/); assert.match(env.html(), /合成Build5/);
  await click(env, "刷新已选工程配置"); await respond(env); await click(env, "刷新已选工程配置"); const priorIdentity = env.pending(); env.setProps({ principalId: id(71) }, false); env.reject(priorIdentity, Error("旧身份迟到协议失败")); await env.flush(); assert.doesNotMatch(env.html(), /旧身份迟到协议失败|固定定义5/);
});

test("layout teardown rejects a pending completion, and component actions remain GET-only with local table scrolling", async t => {
  const env = environment(t); await respond(env); await chosen(env); const html = env.html(); assert.match(html, /role="region" aria-label="固定 BOM 每份原值" tabindex="0"/); assert.doesNotMatch(html, /<form|<input|<select|<textarea|<pre/); assert.ok(env.calls.every(call => call.body === undefined));
  await click(env, "刷新已选工程配置"); const pending = env.pending(); env.unmountLayout(); env.respond(pending, page()); await env.flush(); assert.equal(hasDetail(env), false);
});
