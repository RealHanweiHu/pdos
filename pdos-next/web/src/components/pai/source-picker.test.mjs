import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- In-memory event dispatcher; SSR forwards hooks unchanged. */
const same = (a, b) => a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const shim = { ...React,
  useState(initial) {
    if (!hooks) return React.useState(initial);
    const state = hooks, index = state.index++;
    if (!(index in state.values)) state.values[index] = typeof initial === "function" ? initial() : initial;
    return [state.values[index], value => { state.values[index] = typeof value === "function" ? value(state.values[index]) : value; }];
  },
  useRef(initial) {
    if (!hooks) return React.useRef(initial);
    const state = hooks, index = state.index++;
    if (!(index in state.values)) state.values[index] = { current: initial };
    return state.values[index];
  },
  useCallback(callback, dependencies) {
    if (!hooks) return React.useCallback(callback, dependencies);
    const state = hooks, index = state.index++, prior = state.values[index];
    if (!prior || !same(prior.dependencies, dependencies)) state.values[index] = { dependencies, callback };
    return state.values[index].callback;
  },
  useEffect(effect, dependencies) {
    if (!hooks) return React.useEffect(effect, dependencies);
    const state = hooks, index = state.index++, prior = state.values[index];
    if (!prior || !same(prior.dependencies, dependencies)) {
      state.values[index] = { dependencies, cleanup: prior?.cleanup };
      state.effects.push(() => { state.values[index].cleanup?.(); state.values[index].cleanup = effect(); });
    }
  },
};
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const cache = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? shim
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier.endsWith(".module.css") ? { __esModule: true, default: new Proxy({}, { get: (_target, key) => String(key) }) }
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { fileName: filename, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}
const { SourcePicker, RunSourceBindings, sourcePickerScope } = load(path.join(directory, "source-picker.tsx"));
const uuid = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const principal = uuid(100), category = uuid(101), product = uuid(102), runId = uuid(104), sessionId = uuid(105);
const scope = { principalId: principal, categoryId: category, productId: null, proposalId: null };
const source = (id = uuid(1), extra = {}) => ({ artifact_id: id, artifact_revision: 3, title: "真实已登记附件", product_id: null, status: "active",
  original: { id: uuid(201), revision: 8, filename: "真实规格.pdf", parse_status: "parsed", parse_code: null, scan_status: "clean" }, availability: { available: true, code: null }, ...extra });
const catalog = (items = [source()], next_cursor = null, currentScope = scope) => ({ version: "agent-input-sources/v1", principal_id: currentScope.principalId,
  scope: { category_id: currentScope.categoryId, product_id: currentScope.productId, proposal_id: currentScope.proposalId }, as_of: "2026-10-17T00:00:00Z", items, next_cursor });
const bindings = (items = [{ artifact_id: uuid(1), expected_revision: 3, product_id: null, current: source() }], currentScope = scope) => ({ version: "agent-run-source-bindings/v1", principal_id: currentScope.principalId,
  scope: { category_id: currentScope.categoryId, product_id: currentScope.productId, proposal_id: currentScope.proposalId }, as_of: "2026-10-17T00:00:00Z", run_id: runId, session_id: sessionId, items });
const tick = () => new Promise(resolve => setImmediate(resolve));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
const text = tree => !tree || typeof tree === "boolean" ? "" : typeof tree !== "object" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : text(tree.props?.children);
function component(Component, initial) {
  let props = { ...initial }; const levels = [];
  function render(next) {
    if (next) props = { ...props, ...next };
    let call = Component, input = props, depth = 0;
    try { for (;;) {
      const key = input.__key ?? "root";
      if (!levels[depth] || levels[depth].key !== key) {
        levels.slice(depth).forEach(state => state?.values.forEach(value => value?.cleanup?.()));
        levels.length = depth; levels[depth] = { key, values: [], effects: [], index: 0 };
      }
      hooks = levels[depth]; hooks.index = 0; hooks.effects = [];
      const tree = call(input);
      if (!tree || typeof tree.type !== "function" || !/ScopedSourcePicker|ScopedRunBindings/.test(tree.type.name)) return tree;
      call = tree.type; input = { ...tree.props, __key: tree.key }; depth++;
    } } finally { hooks = null; }
  }
  function effects() { levels.forEach(state => { const scheduled = state.effects; state.effects = []; scheduled.forEach(effect => effect()); }); }
  return { render, update(next) { props = { ...props, ...next }; }, async flush() { render(); effects(); await tick(); const tree = render(); effects(); return tree; } };
}
const namedButton = (c, label) => elements(c.render(), e => e.props?.onClick && text(e) === label)[0];
async function click(c, label) { const target = namedButton(c, label); assert.ok(target, label); target.props.onClick(); return c.flush(); }
const checkboxes = c => elements(c.render(), e => e.type === "input" && e.props.type === "checkbox");
function picker(api, extra = {}) {
  let selected = null; const changes = [];
  const c = component(SourcePicker, { api, scope, value: null, onChange(value) { selected = value; changes.push(value); c.update({ value }); }, ...extra });
  return { c, changes, selected: () => selected };
}
const pickerButton = c => elements(c.render(), e => e.props?.onClick && e.props?.["aria-expanded"] !== undefined)[0];

test("picker opens with GET only, distinguishes Artifact/original versions and copies the selected fixed version", async () => {
  const calls = []; const { c, selected } = picker(async (path, body) => { calls.push({ path, body }); return catalog(); });
  assert.equal(calls.length, 0); c.render(); assert.equal(calls.length, 0);
  pickerButton(c).props.onClick(); await c.flush();
  assert.equal(calls.length, 1); assert.ok(calls[0].path.startsWith(`v1/categories/${category}/agent-input-sources?`));
  checkboxes(c)[0].props.onChange({ target: { checked: true } });
  assert.deepEqual(selected(), { scope: sourcePickerScope(scope), items: [{ artifact_id: uuid(1), expected_revision: 3, title: "真实已登记附件" }] });
  const details = elements(c.render(), e => e.type?.name === "SourceDetails")[0];
  const html = renderToStaticMarkup(React.createElement(details.type, details.props));
  assert.match(html, /原件：真实规格.pdf · 版本 8/); assert.match(html, /已登记解析结果/); assert.match(html, /已记录扫描通过/);
  assert.equal(calls[0].body, undefined); assert.match(text(c.render()), /所选资料会限定下次回答的检索范围/);
  pickerButton(c).props.onClick(); await c.flush(); assert.equal(calls.length, 1); assert.match(text(c.render()), /真实已登记附件 · v3/);
});

test("unavailable source explains the server reason and stays unselectable; text registration needs no upload", async () => {
  const unavailable = source(uuid(2), { title: "撤回登记", status: "withdrawn", availability: { available: false, code: "SOURCE_UNAVAILABLE" } });
  const { c, changes } = picker(async () => catalog([source(uuid(1), { title: "纯登记文本", original: null }), unavailable]));
  pickerButton(c).props.onClick(); await c.flush();
  assert.equal(checkboxes(c)[0].props.disabled, false); assert.equal(checkboxes(c)[1].props.disabled, true);
  assert.match(text(c.render()), /来源已撤回或不可继续使用/); assert.match(text(c.render()), /登记文本/);
  const before = changes.length; checkboxes(c)[1].props.onChange({ target: { checked: true } }); assert.equal(changes.length, before);
});

test("refresh or read failure clears selected versions and old names instead of silently following Current", async () => {
  let fail = false, revision = 3;
  const { c, selected } = picker(async () => { if (fail) throw Object.assign(Error("权限已收窄"), { status: 403 }); return catalog([source(uuid(1), { artifact_revision: revision })]); });
  pickerButton(c).props.onClick(); await c.flush(); checkboxes(c)[0].props.onChange({ target: { checked: true } });
  revision = 4; await click(c, "刷新来源"); assert.deepEqual(selected().items, []); assert.equal(checkboxes(c)[0].props.checked, false);
  checkboxes(c)[0].props.onChange({ target: { checked: true } }); assert.equal(selected().items[0].expected_revision, 4);
  fail = true; await click(c, "刷新来源"); assert.deepEqual(selected().items, []); assert.equal(checkboxes(c).length, 0); assert.ok(!text(c.render()).includes("真实已登记附件"));
});

test("scope and API switches hide old source names immediately and a late page cannot restore them", async () => {
  let resolveOld;
  const { c } = picker(async () => new Promise(resolve => { resolveOld = resolve; }));
  pickerButton(c).props.onClick(); await c.flush(); c.render({ scope: { ...scope, productId: product } });
  resolveOld(catalog()); await tick(); assert.equal(checkboxes(c).length, 0); assert.ok(!text(c.render()).includes("真实已登记附件"));
  assert.equal(c.render({ api: async () => catalog() }), null); await c.flush(); assert.equal(checkboxes(c).length, 0);
});

test("catalog paging remains explicit, deduplicates repeated heads and hides the catalog on cursor failure", async () => {
  const rows = Array.from({ length: 20 }, (_, index) => source(uuid(index + 1), { title: `来源${index + 1}` })); let fail = false;
  const { c, selected } = picker(async path => { if (path.includes("cursor=")) { if (fail) throw Object.assign(Error("游标已失效"), { status: 403 }); return catalog([rows[0], source(uuid(21))]); } return catalog(rows, uuid(20)); });
  pickerButton(c).props.onClick(); await c.flush(); checkboxes(c)[0].props.onChange({ target: { checked: true } });
  await click(c, "加载更多来源"); assert.equal(checkboxes(c).length, 21); assert.equal(selected().items.length, 1);
  await click(c, "刷新来源"); fail = true; await click(c, "加载更多来源"); assert.equal(checkboxes(c).length, 0); assert.deepEqual(selected().items, []); assert.match(text(c.render()), /游标已失效/);
});

test("Run bindings read actual scope and fixed refs, current null never falls back to selected title", async () => {
  const calls = [];
  const c = component(RunSourceBindings, { api: async (path, body) => { calls.push({ path, body }); return bindings([{ artifact_id: uuid(1), expected_revision: 3, product_id: null, current: null }]); }, scope, runId, sessionId });
  assert.equal(calls.length, 0); await c.flush();
  assert.equal(calls[0].path, `v1/categories/${category}/agent-runs/${runId}/source-bindings`); assert.equal(calls[0].body, undefined);
  assert.match(text(c.render()), /固定来源引用 · 绑定 v3/); assert.match(text(c.render()), /名称与正文未展示/); assert.ok(!text(c.render()).includes("真实已登记附件"));
  assert.match(text(c.render()), /不代表已完成解析或模型执行/);
});

test("Run binding refresh failure hides prior source names and only non503 notifies parent scope failure", async () => {
  let fail = 0, unavailable = 0;
  const c = component(RunSourceBindings, { api: async () => { if (fail) throw Object.assign(Error("读取失败"), { status: fail }); return bindings(); }, scope, runId, sessionId, onUnavailable() { unavailable++; } });
  await c.flush(); assert.match(text(c.render()), /真实已登记附件/);
  fail = 503; await click(c, "重新核对来源"); assert.ok(!text(c.render()).includes("真实已登记附件")); assert.equal(unavailable, 0);
  fail = 403; await click(c, "重新核对来源"); assert.equal(unavailable, 1);
});

test("Run binding identity/protocol mismatch is rejected, with no stale fixed source details", async () => {
  let unavailable = 0;
  const c = component(RunSourceBindings, { api: async () => ({ ...bindings(), session_id: uuid(999) }), scope, runId, sessionId, onUnavailable() { unavailable++; } });
  await c.flush(); assert.ok(!text(c.render()).includes("真实已登记附件")); assert.equal(unavailable, 1); assert.match(text(c.render()), /身份范围无法核对/);
});
