import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Actual React component; hooks, storage and transport are explicit IO drivers.
// These checks do not establish actual source, signing, qualification or PG facts.
const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Isolated component IO dispatcher. */
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
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename); return loaded.exports;
}
const { ReleaseExceptions, ReleaseExceptionReading } = load(path.join(directory, "release-exceptions.tsx"));
const { exceptionSemantic } = load(path.join(web, "src/lib/release-exceptions.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, ref = n => ({ id: id(n), revision: 1 });
const props = { categoryId: id(1), product: { id: id(2), revision: 3 }, projectId: id(3), principalId: id(4) };
const source = { kind: "artifact", id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` }, reads = [{ artifact_id: source.id, expected_revision: 1 }];
const range = { quantity: "10", unit: "ea", site: "固定场地", lots: null, lines: [], regions: ["CN"] }, config = { definition: ref(6), engineering_configuration: ref(7), manufacturing_configuration: ref(8) };
const decide = "release.exception.decide", withdraw = "release.exception.withdraw";
function payload() { return { basis_package: ref(10), discipline: "engineering", release_scope: range, purpose: "固定例外用途", check_keys: ["fixed-check"], limits: [{ text: "仅限本批次", sources: [source] }], risk_controls: [{ text: "逐件人工核对", sources: [source] }], expiry: null, sources: [source], reason: "本人实际限定范围" }; }
function inputs(command, state = "READY") {
  const p = payload(), action = command.operation === decide ? "approved" : "withdrawn";
  const candidate = { structural_only: true, status: "unexecuted_candidate", operation: command.operation, action, declaration: exceptionSemantic(command.operation, command.payload), scope: { tenant_id: id(30), product_id: props.product.id, project_id: props.projectId }, category_id: props.categoryId, owner_id: props.principalId, visibility: "private", discipline: p.discipline, basis_package: p.basis_package, policy_fact: ref(11), policy_version: "policy-fixed-v1", subject_config: config, release_scope: range, purpose: p.purpose, check_keys: p.check_keys, selected_checks: [{ key: "fixed-check", discipline: "engineering", applicable: true, required: true, state: "unknown", non_waivable: false, detail: "原测试依据缺失", sources: [source], release_scope: range, exception: null }], limits: p.limits, risk_controls: p.risk_controls, expiry: null, sources: [source], required_source_read_set: command.source_read_set, signers: [props.principalId], prepared_at: "2026-10-17T12:00:00Z", previous: action === "approved" ? null : ref(20), reason: command.payload.reason, state, unknown: state === "UNKNOWN" ? ["RELEASE_POLICY_NOT_CURRENT"] : [], blocked: state === "BLOCKED" ? ["fixed-check:NON_WAIVABLE"] : [] };
  return { operation: command.operation, payload: exceptionSemantic(command.operation, command.payload), candidate, required_source_read_set: command.source_read_set, authority: { subject_id: props.principalId, operation: command.operation, purpose: p.purpose, authorized: true, qualified: true, roles: ["quality"], scope: candidate.scope }, diagnostics: [] };
}
function preview(command) { const value = inputs(command); return { command: { ...structuredClone(command), payload: { ...structuredClone(command.payload), approval_token: "actual-common-token-substitute" } }, approval_token: "actual-common-token-substitute", write_tier: "T2", named_decision: true, expires_at: null, review: { operation: command.operation, after: value.candidate, authority: value.authority, required_source_read_set: command.source_read_set } }; }
function detail() { const p = payload(), command = { operation: decide, payload: p, source_read_set: reads }, current = { decision: ref(20), epoch: 1, action: "approved" }; return { id: id(20), revision: 1, project_id: props.projectId, purpose: p.purpose, discipline: p.discipline, action: "approved", basis_package: ref(10), series_id: id(20), visibility: "private", expiry: null, created_at: "2026-10-17T12:00:00Z", receipt_id: id(40), as_of: current, decision: inputs(command).candidate, authority: {}, applicability: "current", current }; }
function fixed() { return { id: id(10), revision: 1, project_id: props.projectId, purpose: payload().purpose, current: { id: id(10), version: ref(10), epoch: 1 }, applicability: "current", receipt_id: id(41), package: { structural_only: true, scope: { product_id: props.product.id, project_id: props.projectId }, category_id: props.categoryId, declaration: { project_id: props.projectId, subject_config: config, release_scope: range, purpose: payload().purpose }, objects: [], evidence_digest: "a".repeat(64), checks: inputs({ operation: decide, payload: payload(), source_read_set: reads }).candidate.selected_checks }, assessments: [], decisions: [] }; }
function header(value) { const { decision, authority, applicability, current, ...row } = value; assert.ok(decision && authority && applicability && current); return row; }
function elements(node, predicate) { if (!node || typeof node !== "object") return []; if (Array.isArray(node)) return node.flatMap(item => elements(item, predicate)); return [...(predicate(node) ? [node] : []), ...elements(node.props?.children, predicate)]; }
function text(node) { return Array.isArray(node) ? node.map(text).join("") : node && typeof node === "object" ? text(node.props?.children) : typeof node === "string" ? node : ""; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const prior = Object.getOwnPropertyDescriptor(globalThis, "localStorage"), storage = new Map(); Object.defineProperty(globalThis, "localStorage", { configurable: true, value: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) } });
  const calls = [], api = (route, body) => new Promise((resolve, reject) => calls.push({ route, body: body === undefined ? undefined : structuredClone(body), resolve, reject, done: false }));
  let state, tree, currentProps = { ...props, api, onSaved: () => {} };
  const dialog = { showModal() {}, close() {} };
  function dispose() { if (state) { state.slots.forEach(value => value?.cleanup?.()); state.disposed = true; } }
  function render() { const node = ReleaseExceptions(currentProps); if (!state || state.key !== node.key || state.disposed) { dispose(); state = { key: node.key, slots: [], index: 0, effects: [], dirty: true, disposed: false }; } state.index = 0; state.effects = []; state.dirty = false; hooks = state; try { tree = node.type(node.props); } finally { hooks = null; } const modal = elements(tree, node => node.type === "dialog")[0]; if (modal?.props.ref) modal.props.ref.current = dialog; state.effects.forEach(fn => fn()); }
  render(); t.after(() => { dispose(); if (prior) Object.defineProperty(globalThis, "localStorage", prior); else delete globalThis.localStorage; });
  const key = () => `pdos-release-exceptions-v1:${currentProps.categoryId}:${currentProps.principalId}:${currentProps.product.id}:${currentProps.projectId}`;
  return { calls, tree: () => tree, html: () => renderToStaticMarkup(tree), local: () => JSON.parse(storage.get(key()) ?? "null"), pending: route => calls.find(call => !call.done && call.route.includes(route)), respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, error) { assert.ok(call); call.done = true; call.reject(error); }, remount() { dispose(); render(); }, setProps(next) { currentProps = { ...currentProps, ...next }; render(); }, async flush() { for (let i = 0; i < 8; i++) { await tick(); if (state.dirty && !state.disposed) render(); } } };
}
function button(env, label) { return elements(env.tree(), node => typeof node.props?.onClick === "function" && text(node.props.children) === label)[0]; }
async function click(env, label) { const node = button(env, label); assert.ok(node, label); assert.equal(!!node.props.disabled, false, label); node.props.onClick(); await env.flush(); }
async function change(env, label, value) { const row = elements(env.tree(), node => node.type === "label" && text(node.props.children).startsWith(label))[0], input = row && elements(row, node => ["select", "textarea"].includes(node.type))[0]; assert.ok(input, label); input.props.onChange({ target: { value } }); await env.flush(); }
async function ready(env, exceptions = []) { await env.flush(); env.respond(env.pending("/release-exceptions?"), { items: exceptions.map(header), next_cursor: null }); env.respond(env.pending("/release-packages?"), { items: [fixed()], next_cursor: null }); await env.flush(); }
async function start(env) { await change(env, "实际已保存发布包", id(10)); env.respond(env.pending(`/release-packages/${id(10)}`), fixed()); await env.flush(); await change(env, "高级材料 JSON", JSON.stringify(payload())); await click(env, "读取并核对本次材料"); }
const executes = env => env.calls.filter(call => call.route === "v1/commands");

test("saved exception shows fixed policy/config, controls and unchanged unknown checks", () => {
  const html = renderToStaticMarkup(React.createElement(ReleaseExceptionReading, { detail: detail() })); assert.match(html, /原检查未知/); assert.match(html, /原测试依据缺失/); assert.match(html, /policy-fixed-v1/); assert.match(html, /逐件人工核对/); assert.match(html, /仅限本批次/); assert.match(html, /READY_WITH_CONDITIONS/); assert.match(html, /未另设期限/); assert.match(html, /明确为空，不代表全部/); assert.doesNotMatch(html, /原检查已满足/);
});
test("withdrawal and superseded approved rows retain history and distinct current row", () => {
  const value = detail(); value.current = { decision: ref(21), epoch: 2, action: "withdrawn" }; value.as_of = value.current; value.applicability = "needs_recheck";
  const html = renderToStaticMarkup(React.createElement(ReleaseExceptionReading, { detail: value })); assert.match(html, /这是历史记录，不能作为当前批准/); assert.match(html, /当前适用依据待复核/); assert.match(html, /已撤回/);
  value.id = id(21); value.action = "withdrawn"; value.decision = inputs({ operation: withdraw, payload: { exception: ref(20), sources: [source], reason: "本人实际撤回" }, source_read_set: reads }).candidate;
  const withdrawn = renderToStaticMarkup(React.createElement(ReleaseExceptionReading, { detail: value })); assert.match(withdrawn, /已保存具名撤回/); assert.match(withdrawn, /明确撤回的原决定/); assert.match(withdrawn, /历史批准保留/); assert.match(withdrawn, /原检查未知/);
});
test("refresh and remount only read; saved package selection is always explicit", async t => {
  const env = environment(t); await ready(env); assert.equal(env.calls.length, 2); assert.equal(env.local(), null); assert.equal(executes(env).length, 0); assert.equal(env.calls.some(call => call.route.includes(`/release-packages/${id(10)}`)), false);
  await click(env, "刷新例外"); await ready(env); assert.ok(env.calls.every(call => call.body === undefined)); env.remount(); await ready(env); assert.ok(env.calls.every(call => call.body === undefined));
});
test("ready decision opens one common preview and waits for explicit personal confirmation", async t => {
  const env = environment(t); await ready(env); await start(env); const original = env.pending("/release-exception/inputs"); env.respond(original, inputs(original.body)); await env.flush(); const common = env.pending("v1/commands/preview"); assert.ok(common); assert.equal(executes(env).length, 0); env.respond(common, preview(common.body)); await env.flush(); assert.equal(executes(env).length, 0);
  await click(env, "本人具名确认例外决定"); assert.equal(executes(env).length, 1); assert.ok(executes(env)[0].body.payload.approval_token); assert.equal(executes(env)[0].body.command_id, original.body.command_id);
});
test("unknown execution remount performs zero POST and explicit replay preserves the original request", async t => {
  const env = environment(t); await ready(env); await start(env); const input = env.pending("/release-exception/inputs"); env.respond(input, inputs(input.body)); await env.flush(); const common = env.pending("v1/commands/preview"); env.respond(common, preview(common.body)); await env.flush(); await click(env, "本人具名确认例外决定"); const first = executes(env)[0]; env.reject(first, new Error("response lost")); await env.flush(); const stored = structuredClone(env.local()), postCount = env.calls.filter(call => call.body !== undefined).length;
  env.remount(); await ready(env); env.respond(env.pending(`/release-packages/${id(10)}`), fixed()); await env.flush(); assert.equal(env.calls.filter(call => call.body !== undefined).length, postCount); assert.deepEqual(env.local(), stored); await click(env, "重放并核对同一原提交"); assert.deepEqual(executes(env)[1].body, first.body);
});
test("withdrawal has its own common T2 preview and cannot silently reuse the original approval", async t => {
  const env = environment(t), saved = detail(); await ready(env, [saved]); await change(env, "已保存例外决定", saved.id); env.respond(env.pending(`/release-exceptions/${saved.id}`), saved); await env.flush(); await change(env, "办理内容", withdraw); await change(env, "高级材料 JSON", JSON.stringify({ exception: ref(20), sources: [source], reason: "本人实际撤回" })); await click(env, "读取并核对本次材料"); const input = env.pending("/release-exception/inputs"); env.respond(input, inputs(input.body)); await env.flush(); const common = env.pending("v1/commands/preview"); assert.equal(common.body.operation, withdraw); env.respond(common, preview(common.body)); await env.flush(); assert.equal(executes(env).length, 0); await click(env, "本人具名确认撤回"); assert.equal(executes(env).length, 1); assert.equal(executes(env)[0].body.operation, withdraw); assert.equal(executes(env)[0].body.payload.project_id, undefined);
});
test("non-waivable or unknown inputs remain reviewable and cannot dispatch a command", async t => {
  const env = environment(t); await ready(env); await start(env); const input = env.pending("/release-exception/inputs"); env.respond(input, inputs(input.body, "BLOCKED")); await env.flush(); assert.equal(executes(env).length, 0); assert.equal(env.pending("v1/commands/preview"), undefined); assert.equal(button(env, "本人具名确认例外决定").props.disabled, true); assert.match(env.html(), /此检查不得例外放行/);
});
test("project disposal blocks late previews and access loss hides saved private material", async t => {
  const env = environment(t); await ready(env); await start(env); const old = env.pending("/release-exception/inputs"), saved = structuredClone(env.local()); env.setProps({ projectId: id(90) }); await ready(env); env.respond(old, inputs(old.body)); await env.flush(); assert.equal(env.pending("v1/commands/preview"), undefined); assert.equal(executes(env).length, 0);
  env.setProps({ projectId: props.projectId }); await env.flush(); env.reject(env.pending("/release-exceptions?"), { status: 403 }); env.respond(env.pending("/release-packages?"), { items: [], next_cursor: null }); await env.flush(); assert.deepEqual(env.local(), saved); assert.doesNotMatch(env.html(), /逐件人工核对|本人实际限定范围/); assert.equal(button(env, "继续核对原请求"), undefined);
});
