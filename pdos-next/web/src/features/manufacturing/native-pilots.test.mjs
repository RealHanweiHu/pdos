import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Actual React component/contract. Transport, browser storage and hooks are IO
// drivers; these checks never attest actual authority, source registration or PG.
const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Explicit isolated hook dispatcher. */
const react = { ...React,
  useState(initial) { if (!hooks) return React.useState(initial); const own = hooks, i = own.index++; if (!(i in own.slots)) own.slots[i] = typeof initial === "function" ? initial() : initial; return [own.slots[i], value => { if (!own.disposed) { own.slots[i] = typeof value === "function" ? value(own.slots[i]) : value; own.dirty = true; } }]; },
  useRef(initial) { if (!hooks) return React.useRef(initial); const i = hooks.index++; if (!(i in hooks.slots)) hooks.slots[i] = { current: initial }; return hooks.slots[i]; },
  useCallback(fn, deps) { if (!hooks) return React.useCallback(fn, deps); const i = hooks.index++; if (!same(hooks.slots[i]?.deps, deps)) hooks.slots[i] = { deps, value: fn }; return hooks.slots[i].value; },
  useMemo(fn, deps) { if (!hooks) return React.useMemo(fn, deps); const i = hooks.index++; if (!same(hooks.slots[i]?.deps, deps)) hooks.slots[i] = { deps, value: fn() }; return hooks.slots[i].value; },
  useEffect(fn, deps) { if (!hooks) return React.useEffect(fn, deps); const own = hooks, i = own.index++; if (!same(own.slots[i]?.deps, deps)) { const old = own.slots[i], next = { deps, cleanup: old?.cleanup }; own.slots[i] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = fn(); }); } },
};
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync);
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_object, key) => String(key) }) };
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { NativePilots, NativePilotReading } = load(path.join(directory, "native-pilots.tsx"));
const { nativeSemantic, nativeCountFields, nativeOriginalResult } = load(path.join(web, "src/lib/native-pilots.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const props = { categoryId: id(1), product: { id: id(2), revision: 3 }, projectId: id(3), principalId: id(4) };
const source = { id: id(5), revision: 1, title: "已登记合成原文", content: "真实准备原文行", status: "active", visibility: "private" };
const named = (kind, n) => ({ kind, id: id(n), revision: 1 });
function material(projectId = props.projectId) { const build = { id: id(11), revision: 1, name: "EVT实际轮次", type: "prototype", project_id: projectId }; const lot = { id: id(12), revision: 1, build_id: build.id, project_id: projectId, actual_configuration_id: id(13), unit: "ea", lot_label: "实际批次A", observed_unit_count: 10 }; const actual = { id: id(13), revision: 1, build_id: build.id, project_id: projectId, actual: { engineering_configuration: { id: id(14), revision: 1, name: "实际工程配置" }, manufacturing_configuration: { id: id(15), revision: 1, name: "实际制造工艺" } } }; return { build, lot, actual }; }
const scope = { categoryId: props.categoryId, productId: props.product.id, projectId: props.projectId, principalId: props.principalId };
function pilot() { return { schema_version: "pdos-native-pilot-v1", project_id: props.projectId, pilot: { id: id(10), revision: 1, details: { pilot_id: id(10), purpose: "固定项目用途", basis: { build: named("build", 11), lot: named("build_lot", 12), actual_configuration: named("actual_configuration", 13), engineering_configuration: named("engineering_configuration", 14), process_revision: named("process_revision", 15), unit: "ea" }, source: { kind: "artifact", id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` } }, statistics_basis: null, material: {}, gaps: [{ code: "RESOURCE_UNKNOWN", detail: "资源资格未知" }], receipt_id: id(19), source_status: "current" }, current: { revision: 1, epoch: 1, latest_observation_id: null }, observations: [], qualification: "unknown", start_authorized: false, manufacturing_release: null }; }
function record() { const fixed = pilot().pilot.details; return { observation_id: id(20), expected_pilot_revision: 1, previous_observation_id: null, correction_reason: null, scope: { basis: fixed.basis, manufacturing_baseline: null, line: null, cohort_key: "本批", window_start: "2026-10-17T09:00:00Z", window_end: "2026-10-17T10:00:00Z", criterion: named("criterion", 21), nature: "synthetic", minimum_sample: 2 }, counts: Object.fromEntries(nativeCountFields.map(key => [key, ["input_count", "output_count", "first_pass", "final_good"].includes(key) ? 10 : 0])), units: [], exceptions: [{ key: "unexpected", description: "实际异常待整改", issue: named("issue", 22), source: fixed.source, disposition: null }], observed: { occurred_at: "2026-10-17T10:00:00Z", original_timezone: "UTC", effective_at: null, source: fixed.source }, source: fixed.source }; }
function review(c) { const semantic = nativeSemantic(c.payload); return { operation: c.operation, before: null, after: { qualification: "unknown", start_authorized: false, manufacturing_release: null, external_delivery: false, material: {}, gaps: [{ code: "RESOURCE_UNKNOWN", detail: "准备缺项明确未知" }], ...(c.operation === "npi.pilot.create" ? { details: semantic.details, statistics_basis: semantic.statistics } : { record: semantic.record, pilot_id: c.payload.pilot_id, pilot_revision_before: c.payload.expected_pilot_revision, fixed_scope: null, projection: null }) }, authority: { subject_id: props.principalId, operation: c.operation, purpose: "固定项目用途", authorized: true, qualified: true, roles: ["manufacturing"], scope: { product_id: c.product_id, project_id: props.projectId } }, required_source_read_set: c.source_read_set, effect: "保存原始材料，启动和制造放行仍未授予" }; }
function prepared(c) { const confirmation_token = "explicit-test-common-confirmation"; return { command: { ...structuredClone(c), payload: { ...structuredClone(c.payload), confirmation_token } }, confirmation_token, expires_at: "2099-10-17T10:00:00Z", review: review(c) }; }
function elements(node, pred) { if (!node || typeof node !== "object") return []; if (Array.isArray(node)) return node.flatMap(v => elements(v, pred)); return [...(pred(node) ? [node] : []), ...elements(node.props?.children, pred)]; }
function text(node) { return Array.isArray(node) ? node.map(text).join("") : node && typeof node === "object" ? text(node.props?.children) : typeof node === "string" || typeof node === "number" ? String(node) : ""; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t, options = {}) {
  const values = new Map(), storage = { failSet: false, getItem: key => values.get(key) ?? null, setItem(key, value) { if (this.failSet) throw new Error("storage unavailable"); values.set(key, value); }, removeItem: key => values.delete(key) };
  const prior = Object.getOwnPropertyDescriptor(globalThis, "localStorage"); Object.defineProperty(globalThis, "localStorage", { configurable: true, value: storage });
  const calls = [], api = (route, body) => new Promise((resolve, reject) => calls.push({ route, body: body === undefined ? undefined : structuredClone(body), resolve, reject, done: false }));
  let state, tree, currentProps = { ...props, api, onSaved: () => {}, ...options }, dialog = { opens: 0, showModal() { this.opens++; }, close() {} };
  function dispose() { if (state) { state.slots.forEach(v => v?.cleanup?.()); state.disposed = true; } }
  function render() { const node = NativePilots(currentProps); if (!state || state.key !== node.key || state.disposed) { dispose(); state = { key: node.key, slots: [], index: 0, effects: [], dirty: true, disposed: false }; } state.index = 0; state.effects = []; state.dirty = false; hooks = state; try { tree = node.type(node.props); } finally { hooks = null; } const modal = elements(tree, n => n.type === "dialog")[0]; if (modal?.props.ref) modal.props.ref.current = dialog; state.effects.forEach(fn => fn()); }
  render(); t.after(() => { dispose(); if (prior) Object.defineProperty(globalThis, "localStorage", prior); else delete globalThis.localStorage; });
  const key = () => `pdos-native-pilot-v1:${currentProps.categoryId}:${currentProps.principalId}:${currentProps.product.id}:${currentProps.projectId}`;
  return { calls, storage, tree: () => tree, html: () => renderToStaticMarkup(tree), local: () => JSON.parse(storage.getItem(key()) ?? "null"), projectId: () => currentProps.projectId,
    pending: fragment => calls.find(c => !c.done && c.route.includes(fragment)), respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, e) { assert.ok(call); call.done = true; call.reject(e); },
    remount() { dispose(); render(); }, setProps(next) { currentProps = { ...currentProps, ...next }; render(); },
    async flush() { for (let i = 0; i < 8; i++) { await tick(); if (state.dirty && !state.disposed) render(); } },
  };
}
function button(env, label) { return elements(env.tree(), n => typeof n.props?.onClick === "function" && text(n.props.children) === label)[0]; }
async function click(env, label) { const b = button(env, label); assert.ok(b, label); assert.ok(!b.props.disabled, label); b.props.onClick(); await env.flush(); }
async function change(env, label, value) { const row = elements(env.tree(), n => n.type === "label" && text(n.props.children).startsWith(label))[0], input = row && elements(row, n => ["input", "select", "textarea"].includes(n.type))[0]; assert.ok(input, label); input.props.onChange({ target: { value } }); await env.flush(); }
async function ready(env, items = [], sources = [source]) { await env.flush(); const p = env.projectId(), m = material(p); env.respond(env.pending("/projects"), { items: [{ id: p, purpose: "固定项目用途" }] }); env.respond(env.pending("/builds?"), { items: [m.build] }); env.respond(env.pending("/build-execution"), { actual_configurations: [m.actual], lots: [m.lot], allocations: [], samples: [] }); env.respond(env.pending("/manufacturing-publications?"), { versions: [] }); env.respond(env.pending("/workspace"), { sources }); env.respond(env.pending("/pilots?"), { schema_version: "pdos-native-pilot-v1", items, next_cursor: null }); await env.flush(); }
const executions = env => env.calls.filter(c => c.route === "v1/commands");
async function startCreate(env) { await click(env, "新建试产准备"); await change(env, "真实已登记批次", id(12)); await change(env, "有效原文", id(5)); await click(env, "采用本行作为准备依据"); await click(env, "核对并预览本次保存"); }
async function finishPreview(env) { const inputs = env.pending("/pilots/inputs"); env.respond(inputs, { command: inputs.body, review: review(inputs.body) }); await env.flush(); const call = env.pending("v1/commands/preview"); env.respond(call, prepared(call.body)); await env.flush(); return call.body; }

test("failed project reading remains a visible failure and never becomes a successful empty Pilot list", async t => { const env = environment(t); await env.flush(); env.reject(env.pending("/projects"), new Error("实际读取失败")); await env.flush(); assert.match(env.html(), /本项目资料读取未完成/); assert.equal(executions(env).length, 0); assert.equal(button(env, "新建试产准备").props.disabled, true); });

test("actual lot selection keeps EVT Build and exact actual references; preview waits for explicit confirmation", async t => {
  const env = environment(t); await ready(env); await startCreate(env);
  const pending = env.pending("/pilots/inputs").body;
  assert.equal(pending.payload.details.basis.build.id, id(11)); assert.equal(pending.payload.details.basis.lot.id, id(12)); assert.equal(pending.payload.details.basis.actual_configuration.id, id(13));
  await finishPreview(env); assert.equal(executions(env).length, 0); assert.match(env.html(), /准备缺项明确未知/);
  await click(env, "本人确认保存"); assert.equal(executions(env).length, 1); assert.ok(executions(env)[0].body.payload.confirmation_token);
});

test("UNKNOWN survives remount and replays the identical original command/key/token without automatic POST", async t => {
  const env = environment(t); await ready(env); await startCreate(env); await finishPreview(env); await click(env, "本人确认保存");
  const first = executions(env)[0]; env.reject(first, new Error("response lost")); await env.flush(); const original = structuredClone(env.local());
  env.remount(); await ready(env); assert.deepEqual(env.local(), original); assert.equal(executions(env).length, 1);
  await click(env, "重放并核对同一原提交"); assert.deepEqual(executions(env)[1].body, first.body);
});

test("a known creation success adopts only the returned receipt, refreshes and permits fixed readonly reread", async t => {
  const env = environment(t); await ready(env); await startCreate(env); await finishPreview(env); await click(env, "本人确认保存");
  const written = executions(env)[0].body, item = pilot(); item.pilot.id = written.payload.details.pilot_id; item.pilot.details = structuredClone(written.payload.details);
  env.respond(executions(env)[0], { id: id(80), operation: written.operation, subject_type: "pilot_run", subject_id: item.pilot.id, subject_revision: 1 }); await env.flush(); await ready(env, [item]);
  assert.equal(env.local().pending, null); assert.equal(env.local().receipt.id, id(80)); assert.equal(env.local().selectedPilotId, item.pilot.id);
  await click(env, "回读所选试产"); const reread = env.pending(`/pilots/${item.pilot.id}`); assert.equal(reread.body, undefined); env.respond(reread, item); await env.flush();
  assert.match(env.html(), /已保存 v1|原准备 v1/); assert.equal(executions(env).length, 1);
  env.remount(); await ready(env, [item]); assert.equal(executions(env).length, 1); assert.equal(env.local().receipt.id, id(80));
});

test("changing projects disposes an in-flight inputs response and cannot preview or save in the next scope", async t => {
  const env = environment(t); await ready(env); await startCreate(env); const old = env.pending("/pilots/inputs"), original = structuredClone(env.local());
  env.setProps({ projectId: id(33) }); await ready(env); env.respond(old, { command: old.body, review: review(old.body) }); await env.flush();
  assert.equal(env.calls.filter(c => c.route === "v1/commands/preview").length, 0); assert.equal(executions(env).length, 0); assert.equal(env.local(), null);
  env.setProps({ projectId: props.projectId }); await ready(env); assert.deepEqual(env.local(), original);
});

test("actual original result imports counts and Issue backlink, then obtains a result preview without executing", async t => {
  const item = pilot(), bytes = { ...source, content: JSON.stringify(nativeOriginalResult(item.pilot.id, record())) }, env = environment(t); await ready(env, [item], [bytes]);
  await change(env, "已保存试产", item.pilot.id); await change(env, "有效原文", id(5)); await click(env, "采用本行原始结果");
  await click(env, "核对并预览本次保存"); const original = await finishPreview(env);
  assert.equal(original.operation, "npi.pilot.result.record"); assert.equal(original.payload.expected_pilot_revision, 1); assert.equal(original.payload.record.counts.input_count, 10);
  assert.match(env.html(), /首遍良率|关联问题|实际异常待整改/); assert.equal(executions(env).length, 0);
});

test("an actual correction retains the saved observation, exact current revision, predecessor and reason", async t => {
  const item = pilot(), original = record();
  item.observations = [{ id: original.observation_id, revision: 2, record: original, fixed_scope: null, projection: null, material: {}, gaps: [], receipt_id: id(24), source_status: "current" }];
  item.current = { revision: 2, epoch: 2, latest_observation_id: original.observation_id };
  const corrected = { ...record(), observation_id: id(25), expected_pilot_revision: 2, previous_observation_id: original.observation_id, correction_reason: "原始复核修正，旧观察保留" };
  const bytes = { ...source, content: JSON.stringify(nativeOriginalResult(item.pilot.id, corrected)) }, before = structuredClone(item), env = environment(t);
  await ready(env, [item], [bytes]); await change(env, "已保存试产", item.pilot.id); await change(env, "有效原文", id(5)); await click(env, "采用本行原始结果");
  await click(env, "核对并预览本次保存"); const proposed = await finishPreview(env);
  assert.equal(proposed.payload.expected_pilot_revision, 2); assert.equal(proposed.payload.record.previous_observation_id, original.observation_id); assert.equal(proposed.payload.record.correction_reason, corrected.correction_reason);
  assert.match(env.html(), /本次固定前驱观察|原始复核修正/); assert.equal(executions(env).length, 0); assert.deepEqual(item, before);
});

test("saved reading shows actual two rates and Issue linkage, while unknown projection never becomes a rate", () => {
  const item = pilot(), observation = { id: id(20), revision: 2, record: record(), fixed_scope: null, projection: { counts: record().counts, metrics: { first_pass_yield: { value: "0.8", numerator: 8, denominator: 10, state: "known", partition_complete: true }, final_good_yield: { value: "0.9", numerator: 9, denominator: 10, state: "known", partition_complete: true } } }, material: {}, gaps: [], receipt_id: id(24), source_status: "current" };
  item.observations.push(observation); item.current = { revision: 2, epoch: 2, latest_observation_id: observation.id };
  let html = renderToStaticMarkup(React.createElement(NativePilotReading, { item, scope }));
  assert.match(html, /80.00%|90.00%/); assert.match(html, /view=issues/); assert.match(html, /工厂资格：尚未评估/);
  observation.projection = null; html = renderToStaticMarkup(React.createElement(NativePilotReading, { item, scope }));
  assert.doesNotMatch(html, /80.00%|90.00%/); assert.match(html, /完整统计范围或核对尚缺/);
});

test("unavailable local persistence prevents a command before any inputs or execution", async t => {
  const env = environment(t); await ready(env); await click(env, "新建试产准备"); await change(env, "真实已登记批次", id(12)); await change(env, "有效原文", id(5)); await click(env, "采用本行作为准备依据");
  const original = structuredClone(env.local()); env.storage.failSet = true; await click(env, "核对并预览本次保存");
  assert.deepEqual(env.local(), original); assert.equal(env.calls.filter(c => c.body !== undefined).length, 0); assert.match(env.html(), /未能保留原请求/);
});

for (const status of [401, 403]) test(`actual ${status} response clears private material and blocks new actions`, async t => {
  const env = environment(t); await ready(env); await startCreate(env); await finishPreview(env); await click(env, "本人确认保存");
  env.reject(executions(env)[0], Object.assign(new Error("access rejected"), { status })); await env.flush();
  assert.equal(env.local(), null); assert.match(env.html(), /私有材料已清除/);
  assert.doesNotMatch(env.html(), /EVT实际轮次|实际批次A|待创建Pilot身份|本人确认保存/);
  assert.equal(button(env, "新建试产准备").props.disabled, true);
});
