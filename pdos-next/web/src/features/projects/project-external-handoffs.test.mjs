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
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Existing isolated state driver; no browser or actual HTTP verification. */
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
const { ProjectExternalHandoffs, ProjectExternalHandoffDetail, ProjectExternalHandoffReceipt } = load(path.join(directory, "project-external-handoffs.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, ref = n => ({ id: id(n), revision: 1 });
const clone = value => structuredClone(value);
const scope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) };
const at = "2026-10-18T12:34:56.123456+08:00", received = "2026-10-18T12:34:57.654321+08:00";
const source = () => ({ kind: "artifact", id: id(5), revision: 2, position: `line:3;quote_sha256:${"a".repeat(64)}` });
const range = () => ({ quantity: "1.234567890123456789E+3", unit: "件", site: "保存时固定场地", lots: null, lines: [], regions: ["CN"] });
// These are synthetic DTOs through the real reader, not actual external receipts.
function detail(n = 100, count = 25, input = scope) {
  const declaration = { project_id: input.projectId, package: ref(10), engineering_decision: ref(11), manufacturing_decision: ref(12), subject_config: { definition: ref(6), engineering_configuration: ref(7), manufacturing_configuration: ref(8) }, release_scope: range(), purpose: `合成外部交接${n}`, visibility: "category", destination: { system: "合成ERP", recipient_id: "固定收件方标识" }, external_id: "固定外部编号", mappings: [{ ref: { kind: "engineering_configuration", ...ref(7) }, external_number: "EC-fixed", external_version: "R2", sources: [source()] }], manifest: [{ artifact: ref(9), logical_name: "固定文件原名.txt", content_sha256: "b".repeat(64), external_number: "DOC-fixed", external_version: "A", sources: [source()] }], sources: [source()], reason: "原授权核对原因", approval_token: null };
  const authorization = { structural_only: true, status: "unexecuted_candidate", operation: "integration.handoff.authorize", scope: { tenant_id: id(15), product_id: input.productId, project_id: input.projectId }, category_id: input.categoryId, declaration, package_sha256: "c".repeat(64), manifest_sha256: "d".repeat(64), mappings_sha256: "e".repeat(64), content_sha256: "f".repeat(64), limits: [{ text: "原授权固定限制", sources: [source()] }], signers: [id(25)], state: "READY", unknown: [], blocked: [], sources: [source()], required_source_read_set: [{ artifact_id: id(5), expected_revision: 2 }], prepared_at: at, network_send: false, external_received: false, external_effective: false };
  const packet = { handoff: ref(n), ...Object.fromEntries(["package", "engineering_decision", "manufacturing_decision", "subject_config", "release_scope", "purpose", "destination", "external_id", "manifest", "mappings"].map(key => [key, clone(declaration[key])])), manifest_sha256: authorization.manifest_sha256, mappings_sha256: authorization.mappings_sha256, content_sha256: authorization.content_sha256, network_send: false };
  return { ...ref(n), project_id: input.projectId, purpose: declaration.purpose, package: ref(10), visibility: "category", created_at: received, receipt_id: id(500 + n), as_of: { id: id(1000 + n), handoff: ref(n), intent: ref(2000 + n), receipt_count: count, latest_receipt: count ? ref(3000 + count) : null, epoch: count + 1, projection_sha256: "a".repeat(64) }, reading: { status: "authorized", sent: { stage: "sent", state: "partial", active: [ref(3001)], covered_scopes: [{ ...range(), quantity: "4" }], mismatches: ["MANIFEST_MISMATCH"] }, accepted: { stage: "accepted", state: "rejected", active: [ref(3002)], covered_scopes: [], mismatches: ["DESTINATION_MISMATCH"] }, effective: { stage: "effective", state: "not_recorded", active: [], covered_scopes: [], mismatches: [] }, delivery_unknown: true, rejected: true, failed: true, conflict: true, network_send: false }, network_send: false, authorization, authority: { subject_id: id(25), operation: "integration.handoff.authorize", purpose: declaration.purpose, scope: clone(authorization.scope), authorized: true, qualified: true, roles: ["manufacturing"], reason_codes: [], valid_until: null, synthetic: true, facts_revision: "9".repeat(64), fact_refs: [{ ...ref(26), epoch: 4, kind: "qualification", role: "manufacturing", nature: "synthetic", state: "valid", issuer_key: "保存时专业事实发行键", issuer_version: "saved-v1", issuer_epoch: 2, valid_from: at, valid_until: received, operations: ["integration.handoff.authorize"], purposes: [declaration.purpose], fact_sha256: "8".repeat(64) }], opaque_internal: "must-not-render-authority", write_tier: "T2" }, intent: { ...ref(2000 + n), packet }, applicability: "needs_recheck" };
}
function header(value) { const { authorization, authority, intent, applicability, ...rest } = value; void authorization; void authority; void intent; void applicability; return rest; }
const page = (input = scope) => ({ items: [header(detail(100, 25, input)), header(detail(99, 0, input))], next_cursor: null });
function receipt(value, sequence) { return { ...ref(3000 + sequence), sequence, original: { schema_version: "pdos-external-receipt-v1", handoff: ref(Number(value.id.slice(-12))), intent: { id: value.intent.id, revision: 1 }, destination: clone(value.intent.packet.destination), external_id: value.intent.packet.external_id, manifest_sha256: value.intent.packet.manifest_sha256, release_scope: { ...range(), quantity: "2" }, stage: sequence % 3 === 0 ? "effective" : sequence % 3 === 1 ? "sent" : "accepted", outcome: sequence === 25 ? "unknown" : sequence === 24 ? "rejected" : sequence === 23 ? "failed" : "succeeded", external_receipt_id: `合成原回执-${sequence}`, occurred_at: at, reconciles: sequence === 22 ? ref(3023) : null }, source: source(), issuer: { key: "固定发行登记键", version: "issuer-v1", epoch: 3, system: "合成ERP", subject_id: "实际发行主体标识", proof_sha256: "b".repeat(64) }, mismatches: sequence === 21 ? ["EXTERNAL_ID_MISMATCH"] : [], receipt_id: id(4000 + sequence), received_at: received }; }
const historyPage = (value = detail(), before) => { const last = before === undefined ? value.as_of.receipt_count : Math.min(before - 1, value.as_of.receipt_count), length = Math.min(20, last); return { as_of: clone(value.as_of), items: Array.from({ length }, (_, index) => receipt(value, last - index)), before_sequence: last > 20 ? last - 19 : null }; };
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const calls = [], makeApi = () => (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false }));
  let props = { ...scope, readVersion: 0, api: makeApi() }, instance, tree;
  const dispose = () => { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } };
  function render(commit = true) { const wrapper = ProjectExternalHandoffs(props); if (!instance || instance.key !== wrapper.key) { dispose(); instance = { key: wrapper.key, slots: [], index: 0, effects: [], layouts: [], dirty: true, disposed: false }; } instance.index = 0; instance.effects = []; instance.layouts = []; instance.dirty = false; hooks = instance; try { tree = wrapper.type(wrapper.props); } finally { hooks = null; } instance.layouts.forEach(effect => effect()); if (commit) instance.effects.forEach(effect => effect()); }
  render(); t.after(dispose);
  return { calls, render, tree: () => tree, html: () => renderToStaticMarkup(tree), props: () => props, setProps(next, commit = true) { props = { ...props, ...next }; render(commit); }, replaceApi(commit = true) { props = { ...props, api: makeApi() }; render(commit); }, unmountLayout() { instance.slots.filter(slot => slot?.phase === "layout").forEach(slot => slot.cleanup?.()); }, pending() { return calls.findLast(call => !call.done); }, respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, value) { assert.ok(call); call.done = true; call.reject(value); }, async flush() { for (let i = 0; i < 5; i++) { await tick(); if (instance.dirty) render(); } } };
}
function button(env, label) { return elements(env.tree(), node => (node.props?.children === label || node.props?.["aria-label"] === label) && typeof node.props.onClick === "function")[0]; }
async function click(env, label, commit = true) { const target = button(env, label); assert.ok(target, label); assert.ok(!target.props.disabled, `${label} enabled`); target.props.onClick(); env.render(commit); await env.flush(); }
async function respond(env, value) { env.respond(env.pending(), value); await env.flush(); }
async function choose(env, n = 100, value = detail(n, n === 100 ? 25 : 0, env.props())) { await click(env, `读取外部交接 ${id(n)}`); await respond(env, value); }
async function ready(env, value = detail(100, 25, env.props())) { await respond(env, page(env.props())); await choose(env, 100, value); }
const hasDetail = env => /固定文件原名\.txt/.test(env.html());
const historyCount = env => (env.html().match(/aria-label="原回执 /g) ?? []).length;

test("only explicit selection reads detail; history is a separately requested matching snapshot", async t => {
  const env = environment(t); await respond(env, page()); assert.equal(env.calls.length, 1); assert.equal(hasDetail(env), false); await choose(env); assert.equal(env.calls.length, 2); assert.equal(hasDetail(env), true); assert.equal(historyCount(env), 0); assert.equal(env.calls[0].route, `v1/categories/${scope.categoryId}/products/${scope.productId}/external-handoffs?project_id=${scope.projectId}`); assert.equal(env.calls[1].route, `v1/categories/${scope.categoryId}/products/${scope.productId}/external-handoffs/${id(100)}`);
  await click(env, "展开原回执历史"); assert.equal(env.calls.length, 3); assert.equal(env.pending().route, `v1/categories/${scope.categoryId}/products/${scope.productId}/external-handoffs/${id(100)}/receipts`); await respond(env, historyPage()); assert.equal(historyCount(env), 20); assert.ok(env.calls.every(call => call.body === undefined));
});

test("pure detail and receipt SSR preserve fixed references, raw scope, manifest, mappings, issuer and independent times", () => {
  const fixed = detail(), original = clone(fixed), row = receipt(fixed, 22); row.original.external_id = "原件与授权编号不一致"; row.mismatches = ["EXTERNAL_ID_MISMATCH"];
  const html = renderToStaticMarkup(React.createElement(ProjectExternalHandoffDetail, { detail: fixed })) + renderToStaticMarkup(React.createElement(ProjectExternalHandoffReceipt, { value: row }));
  for (const raw of ["固定文件原名.txt", "EC-fixed", "DOC-fixed", "R2", "固定收件方标识", "1.234567890123456789E+3", "明确为空，不代表全部", "未知 / 未覆盖", "原授权固定限制", id(10), id(11), id(12), id(25), "f".repeat(64), "原件与授权编号不一致", "固定发行登记键", "issuer-v1", "实际发行主体标识", at, received, "EXTERNAL_ID_MISMATCH", "显式对账原事实"]) assert.ok(html.includes(raw), raw);
  assert.deepEqual(fixed, original); assert.doesNotMatch(html, /must-not-render|\bT[012]\b|approval_token|unexecuted_candidate|<pre/);
});

test("saved authority snapshot, original material diagnostics and source kinds remain historical semantic fields", () => {
  const fixed = detail(), baseline = clone(fixed);
  const saved = renderToStaticMarkup(React.createElement(ProjectExternalHandoffDetail, { detail: fixed }));
  for (const raw of ["保存时授权依据与材料状态", "不代表当前资格或当前成熟度", "未重新判定有效期", "READY", "原列表为空", id(15), id(25), id(26), "integration.handoff.authorize", "manufacturing", "是（true）", "保存时专业事实发行键", "saved-v1", "qualification", "synthetic", "9".repeat(64), "8".repeat(64), "来源种类：artifact"]) assert.ok(saved.includes(raw), raw);
  assert.deepEqual(fixed, baseline);
  fixed.authority.authorized = false; fixed.authority.qualified = null; fixed.authority.synthetic = false; fixed.authority.roles = []; fixed.authority.reason_codes = ["原资格原因码"];
  fixed.authorization.state = "UNKNOWN"; fixed.authorization.unknown = ["保存时原未知事项"]; fixed.authorization.blocked = ["保存时原阻断事项"];
  fixed.authorization.sources = [{ ...source(), kind: "domain" }, { ...source(), kind: "command" }];
  const changed = renderToStaticMarkup(React.createElement(ProjectExternalHandoffDetail, { detail: fixed }));
  for (const raw of ["UNKNOWN", "保存时原未知事项", "保存时原阻断事项", "否（false）", "未知（原值为空）", "原资格原因码", "来源种类：domain", "来源种类：command"]) assert.ok(changed.includes(raw), raw);
  assert.doesNotMatch(changed, /must-not-render|\bT[012]\b|<pre|当前资格已通过|当前成熟度已具备/);
});

test("sent, accepted and effective server states and covered ranges never derive from authorization or raw receipt outcomes", async t => {
  const env = environment(t), value = detail(); await ready(env, value); const before = clone(value.reading); assert.match(env.html(), /发送服务器阶段/); assert.match(env.html(), /接收服务器阶段/); assert.match(env.html(), /实际生效服务器阶段/); assert.match(env.html(), /部分范围/); assert.match(env.html(), /已拒绝/); assert.match(env.html(), /未记录/); assert.match(env.html(), /发送结果未知/); assert.match(env.html(), /阶段事实冲突/);
  await click(env, "展开原回执历史"); await respond(env, historyPage(value)); assert.deepEqual(value.reading, before); assert.match(env.html(), /回执收件方与授权不一致|回执文件指纹与授权不一致/); assert.doesNotMatch(env.html(), /已完成全部交付|资格已批准|全部已生效/);
});

test("receipt pagination forwards sequence and appends all same-watermark history without recomputing stage status", async t => {
  const env = environment(t), fixed = detail(); await ready(env, fixed); await click(env, "展开原回执历史"); await respond(env, historyPage(fixed)); await click(env, "读取更早原回执"); assert.equal(historyCount(env), 0); assert.equal(env.pending().route, `v1/categories/${scope.categoryId}/products/${scope.productId}/external-handoffs/${fixed.id}/receipts?before_sequence=6`); await respond(env, historyPage(fixed, 6)); assert.equal(historyCount(env), 25); assert.equal(new Set(Array.from(env.html().matchAll(/aria-label="原回执 ([^"]+)"/g), match => match[1])).size, 25); assert.match(env.html(), /本页未提供更早原回执位置/); assert.match(env.html(), /已读取 25 条原回执/);
});

test("new receipt watermark during more clears old detail and history instead of mixing pages", async t => {
  const env = environment(t), fixed = detail(); await ready(env, fixed); await click(env, "展开原回执历史"); await respond(env, historyPage(fixed)); await click(env, "读取更早原回执"); const changed = historyPage(fixed, 6); changed.as_of.epoch++; await respond(env, changed); assert.equal(historyCount(env), 0); assert.equal(hasDetail(env), false); assert.match(env.html(), /水位变化，已隐藏旧资料/); assert.doesNotMatch(env.html(), /合成外部交接100|固定文件原名/);
});

test("receipt 503 hides previous history but supports exact-page retry; 403 clears private details", async t => {
  const env = environment(t), fixed = detail(); await ready(env, fixed); await click(env, "展开原回执历史"); await respond(env, historyPage(fixed)); await click(env, "读取更早原回执"); env.reject(env.pending(), Object.assign(Error("原回执临时503"), { status: 503 })); await env.flush(); assert.equal(historyCount(env), 0); assert.match(env.html(), /原回执临时503/); await click(env, "重新读取本次原回执页"); await respond(env, historyPage(fixed, 6)); assert.equal(historyCount(env), 25);
  await click(env, "从最新原回执重新读取"); env.reject(env.pending(), Object.assign(Error("回执读权限收窄"), { status: 403 })); await env.flush(); assert.equal(historyCount(env), 0); assert.equal(hasDetail(env), false); assert.match(env.html(), /回执读权限收窄/);
});

test("collapse, selected refresh and new choice immediately clear history and reject late receipt success", async t => {
  const env = environment(t); await ready(env); await click(env, "展开原回执历史"); const old = env.pending(); await click(env, "收起原回执历史"); env.respond(old, historyPage()); await env.flush(); assert.equal(historyCount(env), 0); assert.ok(button(env, "展开原回执历史")); await click(env, "展开原回执历史"); await respond(env, historyPage()); await click(env, "刷新已选外部交接"); assert.equal(hasDetail(env), false); assert.equal(historyCount(env), 0); await respond(env, detail()); assert.ok(button(env, "展开原回执历史")); await choose(env, 99); assert.equal(historyCount(env), 0); assert.ok(env.html().includes("合成外部交接99 ·"));
});

test("detail 503 is retried separately; protocol or access failure cannot fall back to another handoff", async t => {
  const env = environment(t); await respond(env, page()); await click(env, `读取外部交接 ${id(100)}`); env.reject(env.pending(), Object.assign(Error("详情临时503"), { status: 503 })); await env.flush(); assert.equal(hasDetail(env), false); assert.match(env.html(), /详情临时503/); await click(env, "重新读取已选外部交接"); await respond(env, detail()); await click(env, "刷新已选外部交接"); const wrong = detail(); wrong.project_id = id(90); await respond(env, wrong); assert.equal(hasDetail(env), false); assert.match(env.html(), /已隐藏旧资料/); assert.doesNotMatch(env.html(), /合成外部交接99/);
});

test("list next-page and home replace page and selection without inventing a project total", async t => {
  const env = environment(t), first = { items: Array.from({ length: 20 }, (_, index) => header(detail(100 - index))), next_cursor: id(81) }; await respond(env, first); await choose(env); await click(env, "下一页外部交接"); assert.equal(hasDetail(env), false); assert.equal(env.pending().route, `v1/categories/${scope.categoryId}/products/${scope.productId}/external-handoffs?project_id=${scope.projectId}&history_cursor=${id(81)}`); await respond(env, { items: [header(detail(80))], next_cursor: null }); assert.match(env.html(), /本页 1 条可读交接，非项目总数/); assert.doesNotMatch(env.html(), /合成外部交接100/); await click(env, "回首页"); await respond(env, page()); assert.match(env.html(), /本页 2 条可读交接/); assert.equal(hasDetail(env), false);
});

test("failed historical list has home recovery and an actual empty page is not a whole-project absence", async t => {
  const env = environment(t); await respond(env, { items: Array.from({ length: 20 }, (_, index) => header(detail(100 - index))), next_cursor: id(81) }); await click(env, "下一页外部交接"); env.reject(env.pending(), Object.assign(Error("历史列表不可读"), { status: 403 })); await env.flush(); assert.doesNotMatch(env.html(), /本页 0|本页没有可展示/); await click(env, "回首页"); await respond(env, { items: [], next_cursor: null }); assert.match(env.html(), /本页没有可展示的外部交接，不据此判断整个项目/);
});

test("principal, category, product, project, API and readVersion changes synchronously clear old receipt and detail", async t => {
  const env = environment(t); await ready(env); await click(env, "展开原回执历史"); await respond(env, historyPage());
  for (const next of [{ principalId: id(61) }, { categoryId: id(62) }, { productId: id(63) }, { projectId: id(64) }, { readVersion: 1 }]) { env.setProps(next); assert.equal(hasDetail(env), false); assert.equal(historyCount(env), 0); assert.doesNotMatch(env.html(), /合成外部交接100/); await ready(env); }
  env.replaceApi(); assert.equal(hasDetail(env), false); assert.doesNotMatch(env.html(), /合成外部交接100/); await respond(env, page(env.props()));
});

test("new selection before passive cleanup blocks the old detail error and late receipts cannot cross a new API", async t => {
  const env = environment(t); await respond(env, page()); await click(env, `读取外部交接 ${id(100)}`); const old = env.pending(); await click(env, `读取外部交接 ${id(99)}`, false); env.reject(old, Object.assign(Error("旧交接迟到403"), { status: 403 })); await env.flush(); assert.doesNotMatch(env.html(), /旧交接迟到403/); await click(env, "刷新已选外部交接"); await respond(env, detail(99, 0)); await click(env, "展开原回执历史"); const stale = env.pending(); env.replaceApi(false); env.respond(stale, historyPage(detail(99, 0))); await env.flush(); assert.equal(historyCount(env), 0); assert.equal(hasDetail(env), false);
});

test("layout unmount ignores pending receipt completion and all controls stay GET-only", async t => {
  const env = environment(t); await ready(env); await click(env, "展开原回执历史"); const pending = env.pending(); env.unmountLayout(); env.respond(pending, historyPage()); await env.flush(); assert.equal(historyCount(env), 0); assert.ok(env.calls.every(call => call.body === undefined)); assert.match(env.html(), /role="region" aria-label="固定文件 manifest" tabindex="0"/); assert.doesNotMatch(env.html(), /<input|<select|<textarea|<form|<pre|保存授权|登记原回执按钮/);
});
