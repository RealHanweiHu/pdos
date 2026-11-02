import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Actual component events and request recovery; HTTP/storage substitutes only.
const directory = path.dirname(fileURLToPath(import.meta.url)), root = path.resolve(directory, "../../.."), dependency = createRequire(path.join(root, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
let hooks;
const same = (a, b) => a?.length === b?.length && a.every((v, i) => Object.is(v, b[i]));
const react = { ...React, useState(initial) { const own = hooks, i = own.index++; if (!(i in own.slots)) own.slots[i] = initial; return [own.slots[i], value => { own.slots[i] = typeof value === "function" ? value(own.slots[i]) : value; own.dirty = true; }]; }, useRef(initial) { const i = hooks.index++; return hooks.slots[i] ??= { current: initial }; }, useEffect(effect, deps) { const own = hooks, i = own.index++; if (!same(own.slots[i]?.deps, deps)) { const before = own.slots[i]; own.slots[i] = { deps }; own.effects.push(() => { before?.cleanup?.(); own.slots[i].cleanup = effect(); }); } } };
const modules = new Map();
function load(filename) { if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync); if (modules.has(filename)) return modules.get(filename).exports; const loaded = new Module(filename); modules.set(filename, loaded); loaded.require = name => name === "react" ? react : name === "@/components/ui/button" ? { Button: props => React.createElement("button", props) } : name.startsWith("@/") ? load(path.join(root, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name); loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename); return loaded.exports; }
const { ContextRestart } = load(path.join(directory, "context-restart.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const words = tree => typeof tree === "string" ? tree : Array.isArray(tree) ? tree.map(words).join("") : tree && typeof tree === "object" ? words(tree.props?.children) : "";
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t) {
  const before = globalThis.localStorage, store = new Map(), calls = [], opened = [], state = { index: 0, slots: [], effects: [], dirty: false };
  globalThis.localStorage = { getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) };
  let tree, unavailable = 0;
  const props = { root: "v1/agent-runs", runId: id(1), sessionId: id(2), revision: 4, goal: "只看D16，继续核对。", principalId: id(3), requested: [], excluded: [], onOpen: async (...args) => opened.push(args), onUnavailable: () => unavailable++, api: (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject })) };
  function render() { state.index = 0; state.effects = []; state.dirty = false; hooks = state; try { tree = ContextRestart(props); } finally { hooks = null; } state.effects.forEach(effect => effect()); }
  render(); t.after(() => { state.slots.forEach(slot => slot?.cleanup?.()); globalThis.localStorage = before; });
  return { calls, opened, store, unavailable: () => unavailable, words: () => words(tree), props, async flush() { for (let i = 0; i < 5; i++) { await tick(); if (state.dirty) render(); } }, async click() { nodes(tree).find(node => typeof node.props?.onClick === "function").props.onClick(); await this.flush(); } };
}
test("opening does not send; explicit budget recovery accepts only a fresh server session", async t => {
  const env = environment(t); await env.flush(); assert.equal(env.calls.length, 0);
  await env.click(); const call = env.calls[0];
  assert.equal(call.body.restart_from_run_id, id(1)); assert.equal(call.body.context_revision, 4); assert.equal(call.body.work_state, undefined);
  call.resolve({ run_id: id(4), session_id: id(5), continued_from_id: null, restarted_from_id: id(1) }); await env.flush();
  assert.deepEqual(env.opened, [[id(4), id(5)]]); assert.equal(env.store.size, 0);
});
test("unknown response retains and replays original goal, state version and skill selections", async t => {
  const env = environment(t); await env.flush(); await env.click(); const original = structuredClone(env.calls[0].body);
  env.calls[0].reject(new Error("连接中断")); await env.flush();
  env.props.goal = "改变后的输入"; env.props.revision = 8;
  await env.click(); assert.deepEqual(env.calls[1].body, original); assert.match(env.words(), /原携带版本/);
});
test("a clearly rejected skill selection remains editable without clearing the conversation", async t => {
  const env = environment(t); await env.flush(); await env.click();
  env.calls[0].reject(Object.assign(new Error("请移除已停用技能"), { status: 403, detail: { reason: "requested_skill_unavailable" } })); await env.flush();
  assert.equal(env.unavailable(), 0); assert.equal(env.store.size, 0); assert.match(env.words(), /请移除/);
});
test("permission withdrawal clears the saved request and delegates private-context cleanup", async t => {
  const env = environment(t); await env.flush(); await env.click();
  env.calls[0].reject(Object.assign(new Error("当前不可读"), { status: 403 })); await env.flush();
  assert.equal(env.unavailable(), 1); assert.equal(env.store.size, 0);
});
