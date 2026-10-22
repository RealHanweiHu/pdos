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
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Test-only dispatcher runs the actual scoped reader and editor handlers. */
const react = { ...React, useState(initial) {
  if (!hooks) return React.useState(initial);
  const own = hooks, index = own.index++;
  if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial;
  return [own.slots[index], next => { if (!own.disposed) { own.slots[index] = typeof next === "function" ? next(own.slots[index]) : next; own.dirty = true; } }];
}, useRef(initial) { if (!hooks) return React.useRef(initial); const index = hooks.index++; return hooks.slots[index] ??= { current: initial }; }, useEffect(effect, deps) {
  if (!hooks) return React.useEffect(effect, deps);
  const own = hooks, index = own.index++;
  if (!same(own.slots[index]?.deps, deps)) { const prior = own.slots[index], next = { deps, cleanup: prior?.cleanup }; own.slots[index] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); }
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
const { CompetitorSegments } = load(path.join(directory, "competitor-segments.tsx"));
const lib = load(path.join(webRoot, "src/lib/competitor-segments.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const cat = id(1), actor = id(2), entry = id(3), lineage = id(4), source = { type: "snapshot", id: id(5), version: 1, quote: "SYNTHETIC_SOURCE_QUOTE" };
const segment = (version = 1) => ({ entry_id: id(10 + version), version, lineage_id: id(10), label: `合成细分 v${version}`, source_refs: [source] });
function assignment(overrides = {}) {
  return { version: "competitor-segment-assignment/v1", category_id: cat, principal_id: actor, as_of: "2026-10-17T20:00:00+00:00", competitor: { id: entry, lineage_id: lineage, version: 3, origin: "ai_draft", writer_id: id(6), run_id: id(7), confirmed_by: actor, content: { brand: "合成品牌", model: "SYNTHETIC_MODEL", prices: [{ amount: "199.1234567890123456789", currency: "CNY", observed_on: "2026-10-17", price_type: "retail", includes_tax: false, includes_shipping: null, channel: "合成渠道", region: "CN", source_ref: source }], metrics: [{ parameter_id: id(8), parameter_version: 2, value: "0", nature: "claimed", unit: "psi", condition_note: "合成工况", source_ref: source }], features: [], segment_refs: [{ entry_id: segment().entry_id, version: 1 }] }, regions: ["CN"], source_refs: [source] }, can_edit: true, blockers: [], selected_segments: [{ ...segment(), status: "available" }], segments: [segment(2)], unavailable_segment_count: 0, ...overrides };
}
function preview(command) { return { command: { ...command, payload: { ...command.payload, confirmation_token: "synthetic-confirmation-token-fixed" } }, confirmation_token: "synthetic-confirmation-token-fixed", expires_at: "2026-10-17T20:10:00Z", review: { operation: command.operation, effect: "追加共享品类资料；保留既有版本。", payload: { ...command.payload, prepared_by_run_id: null, candidate_digest: null } } }; }
function receipt(command) { return { id: id(50), category_id: cat, product_id: null, operation: "category.knowledge.add", subject_type: "category_knowledge", subject_id: lineage, subject_revision: command.expected_revision + 1, result: { id: lineage, revision: command.expected_revision + 1, status: "active", lineage_id: lineage, version: command.expected_revision + 1, entry_id: id(51) } }; }
function memory() { const map = new Map(); return { map, getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value), removeItem: key => map.delete(key) }; }
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t, storage = memory()) {
  const previous = globalThis.window; globalThis.window = { sessionStorage: storage };
  const calls = [], changes = [], closes = [], api = (route, body) => new Promise((resolve, reject) => calls.push({ route, body: body === undefined ? undefined : structuredClone(body), resolve, reject, done: false, journalAtCall: [...storage.map.values()] }));
  let props = { categoryId: cat, entryId: entry, api, onSaved: () => changes.push("refresh"), onClose: () => closes.push("close") }, reader, editor, tree;
  function dispose(instance) { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } }
  const fresh = key => ({ key, slots: [], index: 0, effects: [], dirty: true, disposed: false });
  function execute(instance, element) { instance.index = 0; instance.effects = []; instance.dirty = false; hooks = instance; try { return element.type(element.props); } finally { hooks = null; } }
  function replace(node, target, replacement) { if (node === target) return replacement; if (Array.isArray(node)) return node.map((child, index) => { const next = replace(child, target, replacement); return React.isValidElement(next) ? React.cloneElement(next, { key: next.key ?? index }) : next; }); if (!React.isValidElement(node) || node.props.children === undefined) return node; return React.cloneElement(node, { children: replace(node.props.children, target, replacement) }); }
  function render() {
    const wrapper = CompetitorSegments(props);
    if (!reader || reader.key !== wrapper.key) { dispose(reader); dispose(editor); editor = null; reader = fresh(wrapper.key); }
    const outer = execute(reader, wrapper), inner = elements(outer, node => node.type?.name === "SegmentEditor")[0];
    if (inner) { if (!editor || editor.key !== inner.key) { dispose(editor); editor = fresh(inner.key); } tree = replace(outer, inner, execute(editor, inner)); }
    else { dispose(editor); editor = null; tree = outer; }
    reader.effects.forEach(effect => effect()); editor?.effects.forEach(effect => effect());
  }
  render();
  const unmount = () => { dispose(reader); dispose(editor); reader = null; editor = null; };
  t.after(() => { unmount(); globalThis.window = previous; });
  return { calls, changes, closes, storage, tree: () => tree, html: () => renderToStaticMarkup(tree), unmount, remount(next = {}) { unmount(); props = { ...props, ...next }; render(); }, setProps(next) { props = { ...props, ...next }; render(); }, pending(route) { return calls.find(c => !c.done && c.route === route); }, respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, error) { assert.ok(call); call.done = true; call.reject(error); }, async flush() { for (let i = 0; i < 8; i++) { await tick(); if (reader?.dirty || editor?.dirty) render(); } } };
}
const readPath = (entryId = entry) => lib.competitorAssignmentPath(cat, entryId);
const button = (env, label) => elements(env.tree(), e => e.props?.children === label && typeof e.props?.onClick === "function")[0];
async function click(env, label) { const found = button(env, label); assert.ok(found, `Missing ${label}`); assert.ok(!found.props.disabled, `${label} disabled`); found.props.onClick(); await env.flush(); }
async function ready(env, data = assignment()) { env.respond(env.pending(readPath(data.competitor.id)), data); await env.flush(); }
async function toggle(env, index, checked) { elements(env.tree(), e => e.type === "input" && e.props.type === "checkbox")[index].props.onChange({ target: { checked } }); await env.flush(); }
async function prepared(env) { await toggle(env, 0, false); await toggle(env, 1, true); await click(env, "预览细分续版"); const call = env.pending(`v1/categories/${cat}/commands/preview`); env.respond(call, preview(call.body)); await env.flush(); return call.body; }

test("assignment transport preserves unavailable reference identities and rejects unsafe scope/content", () => {
  assert.ok(lib.isCompetitorAssignment(assignment(), cat, entry)); assert.equal(lib.isCompetitorAssignment(assignment(), id(99), entry), false);
  const unavailable = assignment({ selected_segments: [{ entry_id: id(90), version: 2, lineage_id: null, label: null, status: "unavailable", source_refs: [] }] }); assert.ok(lib.isCompetitorAssignment(unavailable, cat, entry));
  for (const mutate of [d => { d.principal_id = "unknown"; }, d => { d.competitor.content = null; }, d => { d.competitor.id = id(99); }, d => { d.selected_segments[0].label = "guessed"; }]) { const d = structuredClone(unavailable); mutate(d); assert.equal(lib.isCompetitorAssignment(d, cat, entry), false); }
  assert.ok(lib.isCompetitorAssignment(assignment({ can_edit: false, competitor: { ...assignment().competitor, content: null, source_refs: [] } }), cat, entry));
});
test("manual continuation keeps the complete original content, sources and regions while replacing only fixed segment refs", () => {
  const data = assignment(), original = structuredClone(data), command = lib.segmentCommand(data, [segment(2)]);
  assert.deepEqual(command.payload.content, { ...data.competitor.content, segment_refs: [{ entry_id: segment(2).entry_id, version: 2 }] });
  assert.deepEqual(command.payload.regions, data.competitor.regions); assert.deepEqual(command.payload.source_refs, data.competitor.source_refs); assert.deepEqual(command.payload.supersedes, { lineage_id: lineage, expected_version: 3 });
  assert.equal(command.expected_revision, 3); assert.equal(command.product_id, null); assert.deepEqual(command.source_read_set, []); assert.equal("prepared_by_run_id" in command.payload, false); assert.equal("candidate_digest" in command.payload, false);
  assert.deepEqual(lib.segmentCommand(data, []).payload.content.segment_refs, []); assert.deepEqual(data, original); assert.throws(() => lib.segmentCommand(data, [segment(9)]), /固定细分版本/);
});
test("preview and success receipt must retain exact original command and fixed lineage/version", () => {
  const command = lib.segmentCommand(assignment(), [segment(2)]), value = preview(command); assert.ok(lib.validSegmentPreview(value, command));
  for (const mutate of [p => { p.command.payload.content.model = "changed"; }, p => { p.command.command_id = id(99); }, p => { p.review.payload.source_refs = []; }, p => { p.review.payload.prepared_by_run_id = id(99); }, p => { p.confirmation_token = "other"; }]) { const p = structuredClone(value); mutate(p); assert.equal(lib.validSegmentPreview(p, command), false); }
  assert.ok(lib.validSegmentReceipt(receipt(command), command)); const moved = receipt(command); moved.result.version++; assert.equal(lib.validSegmentReceipt(moved, command), false);
});
test("request journal validates exact actor/category/lineage and refuses a new request over an unknown original", () => {
  const storage = memory(), command = preview(lib.segmentCommand(assignment(), [segment(2)])).command;
  lib.persistSegmentJournal(storage, command, actor); const key = lib.segmentJournalKey(actor, cat, lineage), raw = storage.getItem(key);
  assert.deepEqual(lib.readSegmentJournal(raw, actor, cat, lineage), command); assert.throws(() => lib.readSegmentJournal(raw, id(99), cat, lineage)); assert.throws(() => lib.readSegmentJournal(raw, actor, id(99), lineage)); assert.throws(() => lib.readSegmentJournal(raw, actor, cat, id(99)));
  const changed = structuredClone(command); changed.command_id = id(99); assert.throws(() => lib.persistSegmentJournal(storage, changed, actor), /原保存请求待核对/); assert.equal(storage.getItem(key), raw);
  for (const mutate of [v => { v.command.payload.prepared_by_run_id = id(99); }, v => { v.command.operation = "category.knowledge.withdraw"; }, v => { v.command.payload.supersedes.expected_version++; }, v => { v.command.product_id = id(99); }, v => { v.command.payload.content.segment_refs[0].lineage_id = lineage; }]) { const v = JSON.parse(raw); mutate(v); assert.throws(() => lib.readSegmentJournal(JSON.stringify(v), actor, cat, lineage)); }
  lib.clearSegmentJournal(storage, command, actor); assert.equal(storage.getItem(key), null);
});
test("opening reads once, preserves a historic selection and only previews explicit fixed choices", async t => {
  const env = environment(t); assert.equal(env.calls.length, 1); assert.match(env.html(), /正在读取竞品固定版本/); await ready(env);
  const inputs = elements(env.tree(), e => e.type === "input"); assert.equal(inputs[0].props.checked, true); assert.equal(inputs[1].props.checked, false); assert.ok(button(env, "预览细分续版").props.disabled);
  const command = await prepared(env); assert.deepEqual(command.payload.content.segment_refs, [{ entry_id: segment(2).entry_id, version: 2 }]);
  assert.ok(env.calls.every(call => call.route.startsWith(`v1/categories/${cat}/`)), "all editor reads and previews must use the existing category-scoped BFF entry");
  for (const text of ["SYNTHETIC_MODEL", "199.1234567890123456789", "合成工况", "SYNTHETIC_SOURCE_QUOTE", "人工续版预览", "基版 v3 → 人工新版本", "合成细分 v2", "原价格、规格和来源完整沿用", "不代表新实测"]) assert.ok(env.html().includes(text), text);
  assert.doesNotMatch(env.html(), /synthetic-confirmation-token-fixed|prepared_by_run_id|candidate_digest|confirmation_token/); assert.equal(env.calls.filter(c => c.route === `v1/categories/${cat}/commands`).length, 0);
});
test("unavailable selected versions show identity only and can be explicitly cleared; readonly base exposes blockers", async t => {
  const env = environment(t), data = assignment(); data.selected_segments = [{ entry_id: id(90), version: 5, lineage_id: null, label: null, status: "unavailable", source_refs: [] }]; data.competitor.content.segment_refs = [{ entry_id: id(90), version: 5 }];
  await ready(env, data); assert.match(env.html(), /固定细分不可读/); assert.ok(env.html().includes(id(90))); await toggle(env, 0, false); await click(env, "预览细分续版"); const cleared = env.pending(`v1/categories/${cat}/commands/preview`); assert.deepEqual(cleared.body.payload.content.segment_refs, []); env.respond(cleared, preview(cleared.body)); await env.flush(); assert.match(env.html(), /无细分关联（本次明确清空）/);
  env.remount(); await ready(env, assignment({ can_edit: false, competitor: { ...assignment().competitor, content: null, source_refs: [] }, blockers: [{ code: "competitor_source_unavailable", message: "合成来源不可读" }] })); assert.match(env.html(), /合成来源不可读/); assert.doesNotMatch(env.html(), /SYNTHETIC_MODEL|199.123/); assert.equal(button(env, "预览细分续版"), undefined);
});
test("confirmed save journals before POST, preserves a verified success when reread fails and immediately invalidates the parent", async t => {
  const env = environment(t); await ready(env); await prepared(env); await click(env, "本人确认保存细分");
  const call = env.pending(`v1/categories/${cat}/commands`); assert.equal(call.route, `v1/categories/${cat}/commands`); assert.equal(call.journalAtCall.length, 1); assert.equal(env.storage.map.size, 1); env.respond(call, receipt(call.body)); await env.flush(); assert.deepEqual(env.changes, ["refresh"]);
  assert.equal(env.storage.map.size, 0); const read = env.pending(readPath(id(51))); env.reject(read, new Error("合成重新读取失败")); await env.flush();
  assert.match(env.html(), /人工续版已保存 · v4/); assert.match(env.html(), /保存已成功；最新竞品资料读取失败/); assert.doesNotMatch(env.html(), /SYNTHETIC_MODEL/);
});
test("unknown save survives close/reopen at the new current entry without automatic POST and replays the identical request", async t => {
  const env = environment(t); await ready(env); await prepared(env); await click(env, "本人确认保存细分"); const first = env.pending(`v1/categories/${cat}/commands`), original = structuredClone(first.body);
  env.reject(first, Object.assign(new Error("合成保存响应丢失"), { status: 503 })); await env.flush(); assert.match(env.html(), /原保存结果待核对/);
  env.remount({ entryId: id(51) }); const latest = assignment(); latest.competitor.id = id(51); latest.competitor.version = 4; latest.selected_segments = [{ ...segment(2), status: "available" }]; await ready(env, latest);
  assert.equal(env.calls.filter(c => c.route === `v1/categories/${cat}/commands`).length, 1); assert.match(env.html(), /固定基版 v3/); assert.equal(button(env, "预览细分续版"), undefined);
  await click(env, "核对原保存请求"); const replay = env.pending(`v1/categories/${cat}/commands`); assert.deepEqual(replay.body, original); assert.equal(replay.body.command_id, original.command_id); assert.equal(replay.body.idempotency_key, original.idempotency_key);
  env.respond(replay, receipt(replay.body)); await env.flush(); assert.equal(env.storage.map.size, 0); assert.match(env.html(), /人工续版已保存/); env.respond(env.pending(readPath(id(51))), latest); await env.flush(); assert.deepEqual(env.changes, ["refresh"]);
});
test("unavailable session storage prevents execute POST and a corrupt journal blocks replacement", async t => {
  const env = environment(t); await ready(env); await prepared(env); env.storage.setItem = () => { throw new Error("合成存储不可用"); }; await click(env, "本人确认保存细分"); assert.equal(env.calls.filter(c => c.route === `v1/categories/${cat}/commands`).length, 0); assert.match(env.html(), /合成存储不可用/);
  env.storage.map.set(lib.segmentJournalKey(actor, cat, lineage), JSON.stringify({ version: 1 })); env.remount(); await ready(env); assert.equal(button(env, "预览细分续版"), undefined); assert.match(env.html(), /恢复记录不完整/); assert.equal(env.calls.filter(c => c.route === `v1/categories/${cat}/commands`).length, 0);
});
test("an original receipt can be checked after category write permission is revoked while new edits stay forbidden", async t => {
  const env = environment(t); await ready(env); await prepared(env); await click(env, "本人确认保存细分"); const first = env.pending(`v1/categories/${cat}/commands`), original = structuredClone(first.body);
  env.reject(first, Object.assign(new Error("合成保存响应丢失"), { status: 503 })); await env.flush(); env.remount({ entryId: id(51) });
  const readonly = assignment({ can_edit: false, blockers: [{ code: "category_write_required", message: "当前没有品类写入权限。" }] }); readonly.competitor.id = id(51); readonly.competitor.version = 4; await ready(env, readonly);
  assert.equal(button(env, "预览细分续版"), undefined); assert.match(env.html(), /当前没有品类写入权限/); await click(env, "核对原保存请求"); const replay = env.pending(`v1/categories/${cat}/commands`); assert.deepEqual(replay.body, original);
  env.respond(replay, receipt(original)); await env.flush(); assert.equal(env.storage.map.size, 0); assert.match(env.html(), /人工续版已保存/);
});
test("permission narrowing hides old body while retaining its unknown request and does not treat generic conflicts as safe rejection", async t => {
  const env = environment(t); await ready(env); await prepared(env); await click(env, "本人确认保存细分"); env.reject(env.pending(`v1/categories/${cat}/commands`), Object.assign(new Error("合成权限收窄"), { status: 403 })); await env.flush();
  assert.doesNotMatch(env.html(), /SYNTHETIC_MODEL|199.123|SYNTHETIC_SOURCE_QUOTE/); assert.equal(env.storage.map.size, 1); assert.ok(button(env, "核对原保存请求").props.disabled); assert.equal(button(env, "结束已拒绝请求并刷新列表"), undefined);
  await click(env, "重新读取当前竞品"); await ready(env); await click(env, "核对原保存请求"); env.reject(env.pending(`v1/categories/${cat}/commands`), Object.assign(new Error("合成其他冲突"), { status: 409, code: "VERSION_CONFLICT", detail: { reason: "unrelated_conflict" } })); await env.flush(); assert.equal(button(env, "结束已拒绝请求并刷新列表"), undefined); assert.equal(env.storage.map.size, 1);
  await click(env, "核对原保存请求"); env.reject(env.pending(`v1/categories/${cat}/commands`), Object.assign(new Error("合成基版移动"), { status: 409, code: "VERSION_CONFLICT", detail: { reason: "material_version_moved" } })); await env.flush();
  await click(env, "结束已拒绝请求并刷新列表"); assert.equal(env.storage.map.size, 0); assert.deepEqual(env.changes, ["refresh"]); assert.deepEqual(env.closes, ["close"]);
});
test("keyed category/entry readers discard late reads and a response from another principal cannot expose a stored request", async t => {
  const env = environment(t), first = env.calls[0]; env.setProps({ entryId: id(60) }); assert.match(env.html(), /正在读取/); env.respond(first, assignment()); await env.flush(); assert.doesNotMatch(env.html(), /SYNTHETIC_MODEL/);
  const next = assignment(); next.competitor.id = id(60); next.principal_id = id(61); await ready(env, next); assert.equal(env.calls.filter(c => c.body !== undefined).length, 0);
  const command = preview(lib.segmentCommand(assignment(), [segment(2)])).command; lib.persistSegmentJournal(env.storage, command, actor); env.remount({ entryId: entry }); const other = assignment({ principal_id: id(61) }); await ready(env, other); assert.equal(button(env, "核对原保存请求"), undefined);
  const changedApiReads = []; env.setProps({ api: route => new Promise(resolve => changedApiReads.push({ route, resolve })) }); assert.doesNotMatch(env.html(), /SYNTHETIC_MODEL|SYNTHETIC_SOURCE_QUOTE/); assert.match(env.html(), /正在读取/);
  changedApiReads[0].resolve(assignment()); await env.flush(); assert.ok(button(env, "核对原保存请求"));
});
test("closing an in-flight save keeps its sealed request and a late success cannot refresh another editor scope", async t => {
  const env = environment(t); await ready(env); await prepared(env); await click(env, "本人确认保存细分"); const saved = env.pending(`v1/categories/${cat}/commands`);
  env.setProps({ categoryId: id(70), entryId: id(71) }); env.respond(saved, receipt(saved.body)); await env.flush();
  assert.equal(env.storage.map.size, 1); assert.deepEqual(env.changes, []); assert.doesNotMatch(env.html(), /人工续版已保存|SYNTHETIC_MODEL/);
});
