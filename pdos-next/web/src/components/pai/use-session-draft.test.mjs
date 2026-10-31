import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

/* eslint-disable react-hooks/rules-of-hooks -- Direct dispatcher for the actual session-draft hook. */

const directory = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.join(directory, "../../package.json"));
const ts = dependency("typescript"), React = dependency("react");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const shim = { ...React,
  useState(initial) { const state = hooks, index = state.index++; if (!(index in state.values)) state.values[index] = typeof initial === "function" ? initial() : initial; return [state.values[index], value => { state.values[index] = typeof value === "function" ? value(state.values[index]) : value; }]; },
  useRef(initial) { const state = hooks, index = state.index++; if (!(index in state.values)) state.values[index] = { current: initial }; return state.values[index]; },
  useCallback(callback, dependencies) { const state = hooks, index = state.index++, prior = state.values[index]; if (!prior || !same(prior.dependencies, dependencies)) state.values[index] = { callback, dependencies }; return state.values[index].callback; },
  useEffect(effect, dependencies) { const state = hooks, index = state.index++, prior = state.values[index]; if (!prior || !same(prior.dependencies, dependencies)) { state.values[index] = { dependencies, cleanup: prior?.cleanup }; state.effects.push(() => { state.values[index].cleanup?.(); state.values[index].cleanup = effect(); }); } },
};
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? shim : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
  return loaded.exports;
}
const { useSessionDraft, clearPaiComposerDrafts, writePaiComposerDraft } = load(path.join(directory, "use-session-draft.ts"));
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const before = Object.getOwnPropertyDescriptor(globalThis, "sessionStorage"), values = new Map();
  Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: {
    get length() { return values.size; }, key: index => [...values.keys()][index] ?? null,
    getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value), removeItem: key => values.delete(key),
  } });
  const state = { values: [], index: 0, effects: [] };
  let props = { principalId: "person-a", scope: "scope-a", sessionId: null }, result;
  function renderDraft(next) {
    if (next) props = { ...props, ...next };
    state.index = 0; state.effects = []; hooks = state;
    try { result = useSessionDraft(props.principalId, props.scope, props.sessionId); } finally { hooks = null; }
    state.effects.forEach(effect => effect()); return result;
  }
  t.after(() => { state.values.forEach(value => value?.cleanup?.()); if (before) Object.defineProperty(globalThis, "sessionStorage", before); else delete globalThis.sessionStorage; });
  return { render: renderDraft, values, async flush(next) { renderDraft(next); await tick(); return renderDraft(); } };
}

test("composer drafts restore per session and never cross scope or principal", async t => {
  const env = environment(t);
  let draft = await env.flush(); assert.equal(draft[0], "");
  draft[1]("新会话草稿"); draft = await env.flush(); assert.equal(draft[0], "新会话草稿");
  draft = await env.flush({ sessionId: "session-a" }); assert.equal(draft[0], "");
  draft[1]("A 会话草稿"); draft = await env.flush({ sessionId: "session-b" }); assert.equal(draft[0], "");
  draft[1]("B 会话草稿"); draft = await env.flush({ sessionId: "session-a" }); assert.equal(draft[0], "A 会话草稿");
  draft = await env.flush({ scope: "scope-b" }); assert.equal(draft[0], "");
  draft = await env.flush({ scope: "scope-a", principalId: "person-b" }); assert.equal(draft[0], "");
  draft[1]("B 用户草稿");
  draft = await env.flush({ principalId: "person-a" }); assert.equal(draft[0], "A 会话草稿");
  draft = await env.flush({ sessionId: null }); assert.equal(draft[0], "新会话草稿");
  clearPaiComposerDrafts("person-a");
  assert.equal([...env.values.keys()].some(key => key.includes("person-a")), false);
  assert.equal([...env.values.keys()].some(key => key.includes("person-b")), true);
});

test("setter identity is stable and page actions target the new conversation", async t => {
  const env = environment(t); let draft = await env.flush({ sessionId: "session-a" });
  const setter = draft[1];
  draft = await env.flush({ sessionId: "session-b" }); assert.equal(draft[1], setter);
  writePaiComposerDraft("person-a", "scope-a", null, "页面准备的新对话");
  draft = await env.flush({ sessionId: null }); assert.equal(draft[0], "页面准备的新对话");
});

test("clear removes only the current draft and unavailable storage keeps memory", async t => {
  const env = environment(t); let draft = await env.flush({ sessionId: "session-a" });
  draft[1]("保留在当前会话"); draft = await env.flush(); draft[2](); draft = await env.flush(); assert.equal(draft[0], "");
  Object.defineProperty(globalThis, "sessionStorage", { configurable: true, value: { get length() { return 0; }, key: () => null, getItem: () => { throw Error("denied"); }, setItem: () => { throw Error("denied"); }, removeItem: () => { throw Error("denied"); } } });
  draft[1]("内存草稿"); draft = await env.flush(); assert.equal(draft[0], "内存草稿");
  assert.doesNotThrow(() => clearPaiComposerDrafts("person-a"));
});
