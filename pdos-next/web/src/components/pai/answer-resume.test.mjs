import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Execute both real parent components and their actual resume hook. Only React
// scheduling, clock, unrelated children and HTTP are controlled substitutes.
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../.."), dep = createRequire(path.join(web, "package.json"));
const ts = dep("typescript"), React = dep("react"), modules = new Map();
let hooks;
const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
const shim = { ...React,
  useState(initial) { const own = hooks, i = own.index++; if (!own.values[i]) { const cell = { value: typeof initial === "function" ? initial() : initial }; cell.set = value => { if (!own.disposed) { cell.value = typeof value === "function" ? value(cell.value) : value; own.dirty = true; } }; own.values[i] = cell; } const cell = own.values[i]; return [cell.value, cell.set]; },
  useRef(initial) { const i = hooks.index++; if (!hooks.values[i]) hooks.values[i] = { current: initial }; return hooks.values[i]; },
  useCallback(callback, deps) { const i = hooks.index++; if (!same(hooks.values[i]?.deps, deps)) hooks.values[i] = { deps, value: callback }; return hooks.values[i].value; },
  useMemo(callback, deps) { const i = hooks.index++; if (!same(hooks.values[i]?.deps, deps)) hooks.values[i] = { deps, value: callback() }; return hooks.values[i].value; },
  useEffect(effect, deps) { const own = hooks, i = own.index++; if (!same(own.values[i]?.deps, deps)) { const previous = own.values[i], cell = { deps, cleanup: previous?.cleanup }; own.values[i] = cell; own.effects.push(() => { cell.cleanup?.(); cell.cleanup = effect(); }); } },
};
const noop = () => {}, products = { items: [], busy: false, openProduct: null, load: async () => {}, clear: noop };
const children = new Map();
function child(name) { if (!children.has(name)) { const fn = props => React.createElement("div", null, props.children); Object.defineProperty(fn, "name", { value: name }); children.set(name, fn); } return children.get(name); }
const stubs = new Proxy({ useSessionDraft: () => shim.useState(""), clearPaiComposerDrafts: noop, useWorkProducts: () => products, usePaiScroll: noop,
  loadedSkillFacts: () => [], reconciliationNeeded: () => false, collapsedAnswerCitations: () => [], panelVisible: () => false,
  asCandidate: () => null, adoptedCategory: () => null, materialContextText: () => "", sourcePickerScope: v => JSON.stringify(v), defaultSearchPreferences: {},
}, { get: (object, key) => key in object ? object[key] : child(key) });
function load(filename) { if (modules.has(filename)) return modules.get(filename).exports; const m = new Module(filename); modules.set(filename, m); m.require = name => name === "react" ? shim : name.includes("use-answer-resume") ? load(path.join(web, "src/components/pai/use-answer-resume.ts")) : name.endsWith(".module.css") ? { __esModule: true, default: {} } : name === "@phosphor-icons/react" || name.startsWith("@/") || name.startsWith(".") ? stubs : dep(name); m._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename); return m.exports; }
const { Xiaopai } = load(path.join(web, "src/components/xiaopai.tsx"));
const { PersonalXiaopai } = load(path.join(web, "src/components/category-create/personal-xiaopai.tsx"));
const uuid = n => `00000000-1111-4111-8111-${String(n).padStart(12, "0")}`, runId = uuid(1), sessionId = uuid(2);
const base = { run_id: runId, session_id: sessionId, goal: "准备三件复验", status: "waiting_input", reverted: false, cancel_epoch: 0, product_id: uuid(3), proposal_id: null, result: {} };
const input = (sequence = 4) => ({ sequence, event: { type: "needs_input", questions: [{ id: "sample_count", question: `确认样本数量 ${sequence}`, why: "明确实际准备数量", allow_free_text: true, options: [] }] } });
const nodes = (tree, match) => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(t => nodes(t, match)) : [...(match(tree) ? [tree] : []), ...nodes(tree.props?.children, match)];
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t, personal) {
  const originalInterval = globalThis.setInterval, originalClear = globalThis.clearInterval, originalDocument = globalThis.document;
  const timers = new Map(); let nextTimer = 0;
  globalThis.setInterval = callback => { const id = ++nextTimer; timers.set(id, callback); return id; }; globalThis.clearInterval = id => timers.delete(id);
  globalThis.document = { visibilityState: "visible", addEventListener: noop, removeEventListener: noop };
  const state = { run: structuredClone(base), events: [input()], calls: [], failRead: null, failPost: false, acceptedReadFailure: false };
  const api = async (route, body) => { state.calls.push({ route, body: body === undefined ? undefined : structuredClone(body) }); if (body !== undefined) { if (state.failPost) { state.failPost = false; throw new Error("synthetic lost acknowledgement"); } if (state.acceptedReadFailure) { state.acceptedReadFailure = false; state.failRead = Object.assign(new Error("synthetic read unavailable"), { status: 503 }); } return { run_id: runId, answer_ref: uuid(20), status: "resume_requested" }; } if (route.includes("/events?")) return { items: structuredClone(state.events), next_cursor: state.events.at(-1)?.sequence ?? 0 }; if (state.failRead) { const error = state.failRead; state.failRead = null; throw error; } return structuredClone(state.run); };
  let props = { api, principalId: uuid(4), initialRunId: runId, onCreated: noop, categoryId: uuid(5), productId: uuid(3), sources: [], composeOpen: false, onComposeChange: noop }, tree;
  const levels = [], Component = personal ? PersonalXiaopai : Xiaopai;
  const dispose = (from = 0) => { for (const own of levels.slice(from)) if (!own.disposed) { own.disposed = true; own.values.forEach(cell => cell?.cleanup?.()); } levels.splice(from); };
  const render = () => { let call = Component, args = props, depth = 0; for (;;) { const key = args.__key ?? "root"; if (levels[depth]?.key !== key) { dispose(depth); levels[depth] = { key, values: [], index: 0, effects: [], dirty: false }; } const own = levels[depth]; own.index = 0; own.effects = []; own.dirty = false; hooks = own; let result; try { result = call(args); } finally { hooks = null; } if (!result || typeof result.type !== "function" || !/ScopedXiaopai|PersonalIdentity|ScopedPersonalXiaopai/.test(result.type.name)) { tree = result; break; } call = result.type; args = { ...result.props, __key: result.key }; depth++; } levels.forEach(own => own.effects.forEach(effect => effect())); };
  const flush = async () => { for (let i = 0; i < 12; i++) { await tick(); if (levels.some(v => v.dirty)) render(); } };
  const question = () => personal ? nodes(tree, node => node.type?.name === "ClarificationForm")[0] : nodes(tree, node => node.type === "form" && nodes(node, n => n.type === "input" && n.props.id === "pai-sample_count").length)[0];
  const submit = async () => { const q = question(); assert.ok(q, "actual clarification form"); q.props.onSubmit(personal ? undefined : { preventDefault: noop }); await flush(); };
  const value = () => { const q = question(); return personal ? q?.props.answers.sample_count : nodes(q, n => n.type === "input")[0]?.props.value; };
  const disabled = () => { const q = question(); return personal ? q?.props.disabled : nodes(q, n => n.type === "fieldset")[0]?.props.disabled; };
  render(); t.after(() => { dispose(); globalThis.setInterval = originalInterval; globalThis.clearInterval = originalClear; globalThis.document = originalDocument; });
  return { state, flush, submit, value, disabled, question, timers, tree: () => tree, async fill(value) { const q = question(); assert.ok(q); if (personal) q.props.onAnswer("sample_count", value); else nodes(q, n => n.type === "input")[0].props.onChange({ target: { value } }); await flush(); }, async poll() { assert.ok(timers.size, "resume poll remains scheduled"); for (const callback of [...timers.values()]) callback(); await flush(); }, writes: () => state.calls.filter(c => c.body !== undefined), async retry() { const button = nodes(tree, n => n.props?.onClick && ["重试原请求", "重试同一请求"].includes(n.props.children))[0]; assert.ok(button, "same original request recovery"); button.props.onClick(); await flush(); }, async open(id) { const history = nodes(tree, n => n.type?.name === "SessionHistory")[0]; history.props.onSelectRun(id, sessionId); await flush(); }, async changeProps(next) { props = { ...props, ...next }; render(); await flush(); } };
}

for (const personal of [false, true]) {
  const label = personal ? "Personal" : "Xiaopai";
  test(`${label}: 202 plus unchanged waiting_input preserves answer, polls, blocks repeat and reaches completion`, async t => { const e = environment(t, personal); await e.flush(); await e.fill("3"); await e.submit(); assert.equal(e.value(), "3"); assert.equal(e.disabled(), true); assert.equal(e.writes().length, 1); await e.submit(); assert.equal(e.writes().length, 1); await e.poll(); assert.equal(e.disabled(), true); e.state.run.status = "completed"; await e.poll(); assert.equal(e.question(), undefined); assert.equal(e.timers.size, 0); assert.equal(e.writes().length, 1); });
  test(`${label}: new needs_input sequence with the same question ID unlocks a fresh empty answer`, async t => { const e = environment(t, personal); await e.flush(); await e.fill("3"); await e.submit(); e.state.events = [input(), input(7)]; await e.poll(); assert.equal(e.disabled(), false); assert.equal(e.value() ?? "", ""); assert.equal(e.timers.size, 0); assert.equal(e.writes().length, 1); });
  test(`${label}: unknown POST response retains the exact original answer and key for explicit retry`, async t => { const e = environment(t, personal); await e.flush(); await e.fill("3"); e.state.failPost = true; await e.submit(); const first = e.writes()[0]; assert.equal(e.disabled(), true); await e.retry(); assert.deepEqual(e.writes()[1], first); assert.equal(e.disabled(), true); await e.submit(); assert.equal(e.writes().length, 2); });
  test(`${label}: accepted answer survives an immediate GET 503 and resumes GET polling without reposting`, async t => { const e = environment(t, personal); await e.flush(); await e.fill("3"); e.state.acceptedReadFailure = true; await e.submit(); assert.equal(e.question(), undefined); assert.equal(e.writes().length, 1); await e.poll(); assert.equal(e.disabled(), true); e.state.run.status = "completed"; await e.poll(); assert.equal(e.timers.size, 0); assert.equal(e.writes().length, 1); });
  test(`${label}: a later 403 clears the old form and stops the accepted-resume poll`, async t => { const e = environment(t, personal); await e.flush(); await e.fill("3"); await e.submit(); e.state.failRead = Object.assign(new Error("scope revoked"), { status: 403 }); await e.poll(); assert.equal(e.question(), undefined); assert.equal(e.timers.size, 0); assert.equal(e.writes().length, 1); });
  test(`${label}: navigating away and back cannot re-enable the already submitted old interrupt`, async t => { const e = environment(t, personal); await e.flush(); await e.fill("3"); await e.submit(); e.state.run.run_id = uuid(8); await e.open(uuid(8)); assert.equal(e.disabled(), false); e.state.run.run_id = runId; await e.open(runId); assert.equal(e.disabled(), true); await e.submit(); assert.equal(e.writes().length, 1); });
}
