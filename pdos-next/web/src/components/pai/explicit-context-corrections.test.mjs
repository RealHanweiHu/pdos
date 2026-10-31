import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../.."), dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks;
const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
const shim = { ...React,
  useState(initial) { const h = hooks, i = h.index++; if (!(i in h.values)) h.values[i] = typeof initial === "function" ? initial() : initial; return [h.values[i], value => { h.values[i] = typeof value === "function" ? value(h.values[i]) : value; h.dirty = true; }]; },
  useRef(initial) { const h = hooks, i = h.index++; if (!(i in h.values)) h.values[i] = { current: initial }; return h.values[i]; },
  useCallback(callback, deps) { const h = hooks, i = h.index++; if (!same(h.values[i]?.deps, deps)) h.values[i] = { deps, callback }; return h.values[i].callback; },
  useEffect(effect, deps) { const h = hooks, i = h.index++, old = h.values[i]; if (!old || !same(old.deps, deps)) { h.values[i] = { deps, cleanup: null }; h.effects.push(() => { old?.cleanup?.(); h.values[i].cleanup = effect(); }); } },
};
function load(filename, react = shim) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_t, key) => key }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  const compiled = new Module(filename);
  compiled.require = name => name === "react" ? react : name === "@/components/ui/button" ? { Button: "button" } : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => "i" }) : name.startsWith("@/") ? load(path.join(web, "src", name.slice(2)), react) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name), react) : dependency(name);
  compiled._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return compiled.exports;
}
const { ExplicitContextCorrections } = load(path.join(directory, "explicit-context-corrections.tsx"));
const { ExplicitContextCorrections: StaticCorrections } = load(path.join(directory, "explicit-context-corrections.tsx"), React);
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const context = () => ({ root: "v1/agent-runs", run: { run_id: id(1), session_id: id(2), status: "completed", reverted: false }, workState: { version: "agent-work-state/v1", session_id: id(2), revision: 4, focus_objects: [], exclusions: [] } });
const words = tree => typeof tree === "string" || typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(words).join("") : tree && typeof tree === "object" ? words(tree.props?.children) : "";
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const tick = () => new Promise(resolve => setImmediate(resolve));
function component(props) {
  const h = { values: [], index: 0, effects: [], dirty: false }; let tree;
  function render() { h.index = 0; h.effects = []; h.dirty = false; hooks = h; try { tree = ExplicitContextCorrections(props); } finally { hooks = null; } h.effects.forEach(effect => effect()); return tree; }
  return { render, tree: () => tree, async settle() { for (let i = 0; i < 6; i++) { if (!tree || h.dirty) render(); await tick(); } return tree; } };
}
const option = () => ({ source_type: "issue", source_id: id(8), object_id: id(7), source_revision: 2, title: "实际问题", is_current: true });
const saved = () => ({ ...context().workState, revision: 5, context_selection: { version: 1, status: "available", focus: null, version_mode: "any", versions: [], sources: [option()] } });
const button = (c, text) => nodes(c.tree()).find(node => node.type === "button" && words(node) === text);
async function read(c) { await c.settle(); nodes(c.tree()).find(node => node.type === "input" && !node.props.type).props.onChange({ target: { value: "气密问题" } }); await c.settle(); await nodes(c.tree()).find(node => node.type === "form").props.onSubmit({ preventDefault() {} }); await c.settle(); }

test("SSR is a small explicit chooser and never reads, corrects or starts automatically", () => {
  const html = renderToStaticMarkup(React.createElement(StaticCorrections, { api: () => { throw Error("No SSR IO"); }, context: context(), onContinue() {}, onState() {} }));
  assert.match(html, /换对象、版本或资料/); assert.match(html, /只用所选资料/); assert.match(html, /对应会话/); assert.doesNotMatch(html, /00000000|预览|批准|确认弹窗/);
});
test("a readable single choice is displayed, fixed, saved, reread and natively continued once", async () => {
  const calls = [], continued = [], states = [];
  const c = component({ context: context(), api: async (url, body) => { calls.push({ url, body }); return url.includes("context-options") ? { items: [option()], has_more: false } : saved(); }, onContinue: async body => continued.push(body), onState: state => states.push(state) });
  await read(c); assert.match(calls[0].url, /context-options\?query=/); assert.equal(calls[0].body, undefined);
  assert.match(words(c.tree()), /实际问题 · v2/); assert.equal(button(c, "只用所选资料").props.disabled, false);
  await button(c, "只用所选资料").props.onClick(); await c.settle();
  assert.equal(calls.length, 3); assert.equal(calls[1].body.action, "correct_context");
  assert.deepEqual(calls[1].body.context_change, { kind: "limit_sources", sources: [{ source_type: "issue", source_id: id(8), expected_revision: 2 }] });
  assert.equal(calls[2].body, undefined); assert.equal(continued.length, 1); assert.equal(continued[0].continue_from_run_id, id(1)); assert.equal(continued[0].context_revision, 5);
  for (const key of ["product_id", "session_id", "source_proof", "owner_id", "lookup_depth"]) assert.equal(key in continued[0], false);
  assert.equal(states.length, 1);
});
test("lost correction response retries the original Human key and does not start early", async () => {
  const calls = [], continued = []; let lost = true;
  const c = component({ context: context(), api: async (url, body) => { calls.push({ url, body }); if (url.includes("context-options")) return { items: [option()], has_more: false }; if (body && lost) { lost = false; throw Error("response lost"); } return saved(); }, onContinue: async body => continued.push(body), onState() {} });
  await read(c); await button(c, "只用所选资料").props.onClick(); await c.settle(); assert.equal(continued.length, 0);
  const first = calls[1].body; await button(c, "重试原纠正").props.onClick(); await c.settle();
  assert.deepEqual(calls[2].body, first); assert.equal(continued.length, 1);
});
test("a later Human clear wins over an older replay and no continuation is posted", async () => {
  const calls = [], continued = [], states = [];
  const c = component({ context: context(), api: async (url, body) => { calls.push({ url, body }); if (url.includes("context-options")) return { items: [option()], has_more: false }; return body ? saved() : { ...context().workState, revision: 6 }; }, onContinue: async body => continued.push(body), onState: state => states.push(state) });
  await read(c); await button(c, "只用所选资料").props.onClick(); await c.settle();
  assert.equal(continued.length, 0); assert.equal(states.at(-1).context_selection, undefined); assert.match(words(c.tree()), /条件已变化/); assert.equal(button(c, "重试原纠正"), undefined);
});
