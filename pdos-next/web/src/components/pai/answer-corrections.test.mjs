import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks;
const same = (a, b) => a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const shim = { ...React,
  useState(initial) { const h = hooks, i = h.index++; if (!(i in h.values)) h.values[i] = initial; return [h.values[i], value => { h.values[i] = typeof value === "function" ? value(h.values[i]) : value; }]; },
  useRef(initial) { const h = hooks, i = h.index++; if (!(i in h.values)) h.values[i] = { current: initial }; return h.values[i]; },
  useEffect(effect, deps) { const h = hooks, i = h.index++, old = h.values[i]; if (!old || !same(old.deps, deps)) { h.values[i] = { deps, cleanup: null }; h.effects.push(() => { old?.cleanup?.(); h.values[i].cleanup = effect(); }); } },
};
function load(filename, react = shim) {
  const compiled = new Module(filename);
  compiled.require = name => name === "react" ? react : name === "@/components/ui/button" ? { Button: "button" } : name === "@/lib/answer-corrections" ? load(path.join(directory, "../../lib/answer-corrections.ts")) : name === "./search-preferences" ? load(path.join(directory, "../../lib/search-preferences.ts")) : dependency(name);
  compiled._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return compiled.exports;
}
const { AnswerCorrections, CorrectableAnswerResult } = load(path.join(directory, "answer-corrections.tsx"));
const { AnswerCorrections: StaticAnswerCorrections } = load(path.join(directory, "answer-corrections.tsx"), React);
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const context = () => ({ root: "v1/agent-runs", run: { run_id: id(1), session_id: id(2), status: "completed", reverted: false, project_id: id(3) }, workState: { version: "agent-work-state/v1", session_id: id(2), revision: 4, focus_objects: [], citations: [{ citation_id: id(5), title: "历史进水案例", source_revision: 3 }], exclusions: [], search_preferences: { scope: "current", include_customer_private: false }, search_context: { kind: "project", scoped: true, label: "气密项目" } } });
const text = tree => typeof tree === "string" || typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(tree.props?.children) : "";
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const tick = () => new Promise(resolve => setImmediate(resolve));
function session(extra = {}) {
  const h = { values: [], index: 0, effects: [] }, starts = [], exclusions = [], collapsed = [], unavailable = [];
  const props = { context: context(), onContinue: async request => { starts.push(structuredClone(request)); }, onExclude: async request => { exclusions.push(structuredClone(request)); return { ...props.context.workState, revision: request.body.expected_revision + 1, exclusions: [{ id: request.body.item_id, reason: "用户标记不相关" }] }; }, onCollapsed: (...args) => collapsed.push(args), onUnavailable: () => unavailable.push(true), ...extra };
  function render() { h.index = 0; h.effects = []; hooks = h; const outer = AnswerCorrections(props); const tree = outer ? outer.type(outer.props) : null; hooks = null; h.effects.forEach(effect => effect()); return tree; }
  return { props, starts, exclusions, collapsed, unavailable, render, unmount() { h.values.forEach(value => value?.cleanup?.()); }, async settle() { for (let i = 0; i < 3; i++) { render(); await tick(); } return render(); }, async click(label) { const button = nodes(render()).find(node => node.type === "button" && text(node) === label); assert.ok(button, label); assert.ok(!button.props.disabled, label); button.props.onClick(); return this.settle(); }, async input(value) { const input = nodes(render()).find(node => node.type === "textarea"); assert.ok(input); input.props.onChange({ target: { value } }); return this.settle(); }, async submit() { nodes(render()).find(node => node.type === "form").props.onSubmit({ preventDefault() {} }); return this.settle(); } };
}

test("SSR is read-only, concise and offers only current server-supported actions", () => {
  let calls = 0;
  const markup = renderToStaticMarkup(React.createElement(StaticAnswerCorrections, { context: context(), onContinue: () => { calls++; }, onExclude: () => { calls++; }, onCollapsed: () => { calls++; } }));
  assert.equal(calls, 0); assert.match(markup, /同品类补查/); assert.match(markup, /历史进水案例 · v3/); assert.doesNotMatch(markup.replace(/<[^>]+>/g, ""), /指定版本|只看当前|限定来源|换对象|00000000-0000/);
});
test("supplement sends the exact condition once on submit without a second approval", async () => {
  const c = session(); await c.settle(); assert.equal(c.starts.length, 0);
  await c.click("补充条件"); await c.input("补充测试温度，样本数仍未知"); await c.submit();
  assert.equal(c.starts.length, 1); assert.equal(c.starts[0].body.goal, "补充测试温度，样本数仍未知"); assert.equal(c.starts[0].body.continue_from_run_id, id(1)); assert.equal("product_id" in c.starts[0].body, false);
});
test("same-category click delegates the actual search preference immediately", async () => {
  const c = session(); await c.click("同品类补查");
  assert.equal(c.starts.length, 1); assert.deepEqual(c.starts[0].body.search_preferences, { scope: "same_category", include_customer_private: false });
});
test("exclusion collapse waits for the real response and next exclusion uses its new revision", async () => {
  let finish;
  const c = session({ onExclude: request => { c.exclusions.push(structuredClone(request)); return new Promise(resolve => { finish = resolve; }); } });
  c.props.context.workState.citations.push({ citation_id: id(6), title: "另一资料", source_revision: 1 });
  await c.click("收起并排除"); assert.equal(c.collapsed.length, 0); assert.equal(c.exclusions.length, 1);
  finish({ ...c.props.context.workState, revision: 5, exclusions: [{ id: id(5), reason: "不相关" }] }); await c.settle();
  assert.equal(c.collapsed.length, 1); assert.equal(c.collapsed[0][0], id(5));
  await c.click("收起并排除"); assert.equal(c.exclusions[1].body.expected_revision, 5); assert.equal(c.exclusions[1].body.item_id, id(6));
  finish({ ...c.props.context.workState, revision: 6, exclusions: [{ id: id(5) }, { id: id(6) }] }); await c.settle();
});
test("lost exclusion reply replays the exact original body and never collapses optimistically", async () => {
  let attempts = 0;
  const c = session({ onExclude: async request => { c.exclusions.push(structuredClone(request)); if (++attempts === 1) throw Error("response lost"); return { ...c.props.context.workState, revision: 5, exclusions: [{ id: id(5), reason: "不相关" }] }; } });
  await c.click("收起并排除"); assert.equal(c.collapsed.length, 0); await c.click("重试原操作");
  assert.equal(c.exclusions.length, 2); assert.deepEqual(c.exclusions[0], c.exclusions[1]); assert.equal(c.collapsed.length, 1);
});
test("lost continuation reply retains exact search choice, condition and idempotency key", async () => {
  let attempts = 0;
  const c = session({ onContinue: async request => { c.starts.push(structuredClone(request)); if (++attempts === 1) throw Error("reply lost"); } });
  await c.click("补充条件"); await c.input("关注密封圈材料"); await c.click("同品类补查"); await c.click("重试原操作");
  assert.equal(c.starts.length, 2); assert.deepEqual(c.starts[0], c.starts[1]); assert.equal(c.starts[0].body.goal, "关注密封圈材料");
});
test("permission loss clears controls and cannot collapse a source", async () => {
  const c = session({ onExclude: async () => { throw Object.assign(Error("denied"), { status: 403 }); } });
  await c.click("收起并排除"); assert.equal(c.unavailable.length, 1); assert.equal(c.collapsed.length, 0); assert.doesNotMatch(text(c.render()), /历史进水案例|重试原操作/);
});
test("an unmounted answer ignores a delayed exclusion response", async () => {
  let finish;
  const c = session({ onExclude: () => new Promise(resolve => { finish = resolve; }) });
  await c.click("收起并排除"); c.unmount(); finish({ ...c.props.context.workState, revision: 5, exclusions: [{ id: id(5), reason: "不相关" }] }); await tick(); assert.equal(c.collapsed.length, 0);
});
test("collapsed result uses native disclosure and preserves escaped original text", () => {
  const markup = renderToStaticMarkup(React.createElement(CorrectableAnswerResult, { collapsed: true }, React.createElement("p", null, "<script>wrong source</script>")));
  assert.match(markup, /<details/); assert.doesNotMatch(markup, /<details open|<script>/); assert.match(markup, /&lt;script&gt;wrong source&lt;\/script&gt;/);
});
