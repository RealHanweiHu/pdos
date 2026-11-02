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
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Existing isolated state driver; not browser or actual HTTP evidence. */
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
const { ProjectReleasePackages } = load(path.join(directory, "project-release-packages.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) };
const ref = (n, revision = 1) => ({ id: id(n), revision });
const at = "2026-10-18T01:02:03.888505+08:00", expiry = "2099-01-01T00:00:00.123456Z";
const source = () => ({ kind: "artifact", ...ref(5), position: `line:3;quote_sha256:${"a".repeat(64)}` });
const configuration = () => ({ definition: ref(6, 3), engineering_configuration: ref(7, 2), manufacturing_configuration: ref(8, 4) });
const range = () => ({ quantity: "9007199254740993.123456789012", unit: "ea", lots: null, site: null, lines: [], regions: ["CN"] });
function assessment(discipline, state = "READY") { return { discipline, state, checks: [{ key: `${discipline}-fixed-check`, discipline, state: "unknown", detail: `${discipline}原始核对说明`, applicable: true, required: true, non_waivable: false, sources: [source()] }], blocked: state === "BLOCKED" ? ["原始硬阻塞"] : [], unknown: state === "UNKNOWN" || state === "BLOCKED" ? ["原始未知仍保留"] : [], conditions: state === "READY_WITH_CONDITIONS" ? [ref(25, 2)] : [] }; }
function header(n = 10, revision = 1, input = scope) { return { ...ref(n, revision), project_id: input.projectId, purpose: `合成固定用途${n}`, status: "assembled", receipt_id: id(70 + n), current: n === 10 || n === 12 ? { id: id(10), version: ref(12, 2), epoch: 2 } : { id: id(n), version: ref(n, revision), epoch: revision }, applicability: "not_checked" }; }
const page = (input = scope) => ({ items: [header(10, 1, input), header(12, 2, input)], next_cursor: id(12) });
// Explicitly synthetic read responses; the real strict project readers are used.
function detail(n = 10, revision = 1, input = scope) {
  const selected = ref(n, revision), boundScope = { tenant_id: id(30), product_id: input.productId, project_id: input.projectId }, purpose = `合成固定用途${n}`;
  const decisions = ["engineering", "manufacturing"].map((discipline, index) => ({ id: id(40 + index), revision: 1, discipline, package: { ...selected }, receipt_id: id(45 + index), applicability: index ? "needs_recheck" : "current", authority: { subject_id: id(50 + index), scope: boundScope, opaque_internal: "must-not-render-authority", write_tier: "T2" }, decision: { structural_only: true, status: "unexecuted_candidate", operation: `release.${discipline}.approve`, discipline, package: { ...selected }, package_sha256: "c".repeat(64), scope: boundScope, category_id: input.categoryId, subject_config: configuration(), release_scope: range(), purpose, policy_version: "fixed-policy-v1", signers: [id(50 + index)], expiry: index ? expiry : null, prepared_at: at, limits: [{ text: `${discipline}独立固定限制`, sources: [source()] }], input_snapshot: { reason: "合成具名说明", opaque_internal: "must-not-render-input-snapshot" }, evidence_digest: "d".repeat(64), assessment: assessment(discipline, index ? "READY" : "READY_WITH_CONDITIONS"), customer_acceptance: null, external_received: false, external_effective: false } }));
  return { ...header(n, revision, input), applicability: "needs_recheck", package: { structural_only: true, status: "unexecuted_candidate", scope: boundScope, category_id: input.categoryId, product_revision: 7, owner_id: id(60), declaration: { project_id: input.projectId, subject_config: configuration(), release_scope: range(), purpose, reason: "包原始保存说明", sources: [source()], previous: null, documents: [], limits: [{ text: "固定包原限制", sources: [source()] }] }, objects: [{ ref: { kind: "definition", ...ref(6, 3) }, product_id: input.productId, project_id: null, sha256: "b".repeat(64) }], policy: null, checks: [], exceptions: [], sources: [source()], required_source_read_set: [{ artifact_id: id(5), expected_revision: 1 }], evidence_digest: "a".repeat(64), body_sha256: "b".repeat(64) }, assessments: { engineering: assessment("engineering", "BLOCKED"), manufacturing: assessment("manufacturing", "UNKNOWN") }, decisions };
}
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const calls = [], makeApi = () => (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false }));
  let props = { ...scope, readVersion: 0, api: makeApi() }, instance, tree;
  const dispose = () => { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } };
  function render(commit = true) {
    const wrapper = ProjectReleasePackages(props);
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
function button(env, label) { return elements(env.tree(), node => (node.props?.children === label || node.props?.["aria-label"] === label) && typeof node.props.onClick === "function")[0]; }
async function click(env, label, commit = true) { const target = button(env, label); assert.ok(target, label); assert.ok(!target.props.disabled, `${label} is enabled`); target.props.onClick(); env.render(commit); await env.flush(); }
async function respond(env, value = page(env.props())) { env.respond(env.pending(), value); await env.flush(); }
async function choose(env, n = 10, revision = 1, value = detail(n, revision, env.props())) { await click(env, `读取发布包 ${id(n)} v${revision}`); await respond(env, value); }
const fixed = env => /包内固定对象与内容指纹/.test(env.html());

test("page headers never auto-select; only an explicit choice makes one fixed package GET", async t => {
  const env = environment(t); await respond(env); assert.equal(env.calls.length, 1); assert.match(env.html(), /尚未选择固定包/); assert.equal(fixed(env), false); assert.match(env.html(), /本系列当前头/); assert.match(env.html(), /历史固定版本/); assert.match(env.html(), /适用性未核对/);
  const original = detail(); const before = structuredClone(original); await choose(env, 10, 1, original); assert.equal(env.calls.length, 2); assert.equal(env.calls[0].route, `v1/categories/${scope.categoryId}/products/${scope.productId}/release-packages?project_id=${scope.projectId}`); assert.equal(env.calls[1].route, `v1/categories/${scope.categoryId}/products/${scope.productId}/release-packages/${id(10)}`); assert.equal(fixed(env), true); assert.deepEqual(original, before); assert.ok(env.calls.every(call => call.body === undefined));
});

test("fixed package scope preserves decimal, null, empty-set, object versions and evidence fingerprints", async t => {
  const env = environment(t); await respond(env); await choose(env); const html = env.html();
  for (const raw of ["9007199254740993.123456789012", "未知 / 未覆盖", "明确为空，不代表全部", "固定包原限制", "包原始保存说明", id(6), id(7), id(8), "a".repeat(64), "b".repeat(64), id(80)]) assert.ok(html.includes(raw), raw);
  assert.match(html, /产品定义/); assert.match(html, /固定工程配置/); assert.match(html, /固定制造配置/); assert.doesNotMatch(html, /9007199254740994|不限量|全部批次|全部产线/);
});

test("blocked and unknown package checks coexist independently of each stored decision assessment and conditions", async t => {
  const env = environment(t); await respond(env); await choose(env); const html = env.html();
  for (const raw of ["工程包范围检查", "制造包范围检查", "原始硬阻塞", "原始未知仍保留", "工程决定内固定检查", "制造决定内固定检查", "附条件满足本范围检查", id(25), "engineering原始核对说明", "manufacturing原始核对说明"]) assert.ok(html.includes(raw), raw);
  assert.match(html, /阻塞（原列表）/); assert.match(html, /未知（原列表）/); assert.match(html, /不可豁免：否/); assert.match(html, /固定条件决定/);
});

test("check-specific and fixed exception scopes retain their own original ranges, nulls, policy and limits", async t => {
  const env = environment(t), value = detail(), engineering = value.assessments.engineering.checks[0], manufacturing = value.assessments.manufacturing.checks[0];
  engineering.release_scope = { quantity: "1.000000000001", unit: "件", lots: [ref(91, 4)], site: "规则固定场地", lines: null, regions: [] }; engineering.exception = ref(25, 2);
  manufacturing.release_scope = null; manufacturing.exception = null;
  value.package.exceptions = [{ decision: ref(25, 2), scope: { tenant_id: id(30), product_id: scope.productId, project_id: scope.projectId }, subject_config: configuration(), release_scope: { quantity: null, unit: null, lots: [], site: null, lines: null, regions: ["固定例外地区"] }, purpose: "固定例外用途", policy_version: "fixed-exception-policy-v2", discipline: "engineering", check_keys: ["check-only-A"], state: "current", expiry: null, limits: [{ text: "固定例外独立限制", sources: [source()] }], sources: [source()] }];
  const before = structuredClone(value); await respond(env); await choose(env, 10, 1, value); const html = env.html();
  const start = html.indexOf('aria-label="检查范围 engineering-fixed-check"'), checkHtml = html.slice(start, html.indexOf("</details>", start));
  assert.ok(start >= 0); assert.match(checkHtml, /1\.000000000001|规则固定场地/); assert.ok(checkHtml.includes(id(91))); assert.ok(checkHtml.includes(id(25))); assert.doesNotMatch(checkHtml, /9007199254740993/);
  assert.match(html, /未单列本检查范围（原值为空），不以包全局范围补齐/); assert.match(html, /未提供固定例外引用（原值为空）/);
  for (const raw of ["包内固定例外依据（1 条）", "保存时状态原值", "current", "fixed-exception-policy-v2", "check-only-A", "固定例外地区", "固定例外独立限制", "未另设期限（原值为空）", "原状态与期限不作为本页重新判定的当前有效性"]) assert.ok(html.includes(raw), raw);
  assert.deepEqual(value, before); assert.equal(env.calls.length, 2); assert.ok(env.calls.every(call => call.body === undefined));
});

test("actual Decision rows remain visible despite candidate body status; signer, expiry, prepare time and receipt stay separate", async t => {
  const env = environment(t); await respond(env); await choose(env); const html = env.html(); assert.equal((html.match(/aria-label="专业决定 /g) ?? []).length, 2);
  for (const raw of [id(40), id(41), id(50), id(51), id(45), id(46), at, expiry, "engineering独立固定限制", "manufacturing独立固定限制", "准备时点不作为签署时点", "未另设期限（原值为空）"]) assert.ok(html.includes(raw), raw);
  assert.match(html, /当前适用依据可核/); assert.match(html, /适用依据需重核，历史保留/); assert.doesNotMatch(html, /尚未签署|签署时间：|张工程师|李制造|已失效|已撤回/);
  assert.doesNotMatch(html, /must-not-render|\bT[012]\b|token|approval_token|unexecuted_candidate|<pre/);
});

test("current-series pointer without returned decisions never fabricates professional approval or a complete absence", async t => {
  const env = environment(t), value = detail(12, 2); value.decisions = []; await respond(env); await choose(env, 12, 2, value); assert.match(env.html(), /本系列当前头/); assert.match(env.html(), /本次可读固定包未返回工程决定记录/); assert.match(env.html(), /本次可读固定包未返回制造决定记录/); assert.doesNotMatch(env.html(), /已登记决定 · v|工程已批准|制造已放行|整个项目没有决定/);
});

test("server next-page and home requests replace the page and selection without accumulating totals", async t => {
  const env = environment(t); await respond(env); await choose(env); await click(env, "下一页发布包"); assert.equal(fixed(env), false); assert.doesNotMatch(env.html(), /合成固定用途10|engineering独立固定限制/); assert.equal(env.pending().route, `v1/categories/${scope.categoryId}/products/${scope.productId}/release-packages?project_id=${scope.projectId}&history_cursor=${id(12)}`);
  await respond(env, { items: [header(9)], next_cursor: null }); assert.match(env.html(), /本页返回 1 条可读包版本，非项目总数/); assert.doesNotMatch(env.html(), /合成固定用途10|本页返回 3/); assert.equal(button(env, "下一页发布包").props.disabled, true); await click(env, "回首页"); await respond(env); assert.match(env.html(), /本页返回 2 条可读包版本，非项目总数/); assert.equal(button(env, "回首页").props.disabled, true); assert.match(env.html(), /尚未选择固定包/);
});

test("an empty historical page remains distinct from failed or whole-project empty data", async t => {
  const env = environment(t); await respond(env); await click(env, "下一页发布包"); await respond(env, { items: [], next_cursor: null }); assert.match(env.html(), /本页没有可展示的固定包版本，不据此推断整个项目或系列没有发布包/); assert.equal(button(env, "回首页").props.disabled, false); assert.equal(fixed(env), false);
});

test("failed historical cursor can explicitly return home instead of retrying the same unavailable page forever", async t => {
  const env = environment(t); await respond(env); await click(env, "下一页发布包"); env.reject(env.pending(), Object.assign(Error("历史页当前不可读"), { status: 403 })); await env.flush(); assert.match(env.html(), /历史页当前不可读/); assert.doesNotMatch(env.html(), /合成固定用途10/); await click(env, "回首页"); assert.equal(env.pending().route, `v1/categories/${scope.categoryId}/products/${scope.productId}/release-packages?project_id=${scope.projectId}`); await respond(env); assert.match(env.html(), /尚未选择固定包/); assert.equal(fixed(env), false);
});

test("refresh clears page details immediately; a detail 503 is retryable while 403 or protocol failure hides old headers", async t => {
  const env = environment(t); await respond(env); await choose(env); await click(env, "刷新已选固定包"); assert.equal(fixed(env), false); env.reject(env.pending(), Object.assign(Error("原固定包临时503"), { status: 503 })); await env.flush(); assert.match(env.html(), /原固定包临时503/); assert.doesNotMatch(env.html(), /engineering独立固定限制/);
  await click(env, "重新读取已选固定包"); await respond(env, detail()); await click(env, "刷新已选固定包"); env.reject(env.pending(), Object.assign(Error("实际读权限收窄"), { status: 403 })); await env.flush(); assert.match(env.html(), /已隐藏旧资料/); assert.doesNotMatch(env.html(), /合成固定用途10|本页没有可展示/);
  await click(env, "重新读取本页发布包"); await respond(env); await click(env, `读取发布包 ${id(10)} v1`); const wrong = detail(); wrong.revision = 2; await respond(env, wrong); assert.equal(fixed(env), false); assert.match(env.html(), /读取不完整/); assert.doesNotMatch(env.html(), /合成固定用途12|engineering独立固定限制/);
});

test("principal, category, product, project, API and readVersion changes hide previous data synchronously", async t => {
  const env = environment(t); await respond(env); await choose(env);
  for (const next of [{ principalId: id(61) }, { categoryId: id(62) }, { productId: id(63) }, { projectId: id(64) }, { readVersion: 1 }]) { env.setProps(next); assert.equal(fixed(env), false); assert.doesNotMatch(env.html(), /合成固定用途10|engineering独立固定限制/); await respond(env); assert.match(env.html(), /尚未选择固定包/); await choose(env); }
  env.replaceApi(); assert.equal(fixed(env), false); assert.doesNotMatch(env.html(), /合成固定用途10/); await respond(env); assert.match(env.html(), /尚未选择固定包/);
});

test("late pagination/list responses cannot overwrite the new home page or refreshed generation", async t => {
  const env = environment(t); await respond(env); await click(env, "下一页发布包"); const oldPage = env.pending(); await click(env, "刷新本页发布包"); await respond(env, { items: [header(9)], next_cursor: null }); env.respond(oldPage, page()); await env.flush(); assert.match(env.html(), /合成固定用途9/); assert.doesNotMatch(env.html(), /合成固定用途10/);
  await click(env, "回首页"); const stale = env.pending(); env.replaceApi(false); env.reject(stale, Error("旧API列表迟到错误")); await env.flush(); assert.doesNotMatch(env.html(), /旧API列表迟到错误|合成固定用途9/);
});

test("changing explicit selection blocks late success and pre-cleanup error from the old fixed package", async t => {
  const env = environment(t); await respond(env); await click(env, `读取发布包 ${id(10)} v1`); const old = env.pending(); await click(env, `读取发布包 ${id(12)} v2`); await respond(env, detail(12, 2)); env.respond(old, detail()); await env.flush(); assert.match(env.html(), /合成固定用途12 · 固定包 v2/); assert.doesNotMatch(env.html(), /合成固定用途10 · 固定包 v1/);
  await click(env, "刷新已选固定包"); const oldError = env.pending(); await click(env, `读取发布包 ${id(10)} v1`, false); env.reject(oldError, Object.assign(Error("旧包迟到403"), { status: 403 })); await env.flush(); assert.doesNotMatch(env.html(), /旧包迟到403/); await click(env, "刷新已选固定包"); await respond(env, detail()); assert.equal(fixed(env), true);
});

test("list errors are not successful zero pages, and layout teardown discards a pending detail", async t => {
  const env = environment(t); env.reject(env.pending(), Object.assign(Error("列表暂不可读"), { status: 503 })); await env.flush(); assert.match(env.html(), /列表暂不可读/); assert.doesNotMatch(env.html(), /本页返回 0|本页没有可展示/); await click(env, "重新读取本页发布包"); await respond(env); await click(env, `读取发布包 ${id(10)} v1`); const pending = env.pending(); env.unmountLayout(); env.respond(pending, detail()); await env.flush(); assert.equal(fixed(env), false);
});

test("all actions only read and wide identities or fingerprints stay inside keyboard-scrollable tables", async t => {
  const env = environment(t); await respond(env); await choose(env); const html = env.html(); assert.ok(env.calls.every(call => call.body === undefined)); assert.match(html, /role="region" aria-label="包内固定对象与内容指纹" tabindex="0"/); assert.doesNotMatch(html, /<form|<input|<select|<textarea|提交批准|确认放行|保存决定/);
});
