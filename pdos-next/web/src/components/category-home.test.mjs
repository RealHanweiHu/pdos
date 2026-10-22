import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
/* eslint-disable react-hooks/rules-of-hooks -- Isolated component state driver; real SSR hooks delegate unchanged. */
const reactShim = { ...React, useState(initial) {
  if (!hooks) return React.useState(initial);
  const own = hooks, index = own.index++;
  if (!(index in own.values)) own.values[index] = typeof initial === "function" ? initial() : initial;
  return [own.values[index], next => { own.values[index] = typeof next === "function" ? next(own.values[index]) : next; }];
}, useEffect(callback) { if (!hooks) return React.useEffect(callback); hooks.effects.push(callback); }, useId() { return hooks ? "knowledge-panel" : React.useId(); }, useRef(value) { return hooks ? { current: value } : React.useRef(value); } };
/* eslint-enable react-hooks/rules-of-hooks */
const leaf = name => function PreservedLeaf() { return React.createElement("div", { "data-preserved": name }); };
const cache = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? reactShim
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier === "@/components/proposals/proposal-list" ? { ProposalList: leaf("ProposalList") }
    : specifier === "@/components/preproject/category-matrix" ? { CategoryMatrix: leaf("CategoryMatrix") }
    : specifier === "@/components/preproject/competitor-segments" ? { CompetitorSegments: leaf("CompetitorSegments") }
    : specifier === "@/components/preproject/standard-match" ? { StandardMatch: leaf("StandardMatch") }
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { CategoryHome } = load(path.join(directory, "category-home.tsx"));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
function driver(props) {
  const state = { index: 0, values: [], effects: [] };
  return { render() { hooks = state; state.index = 0; state.effects = []; try { return CategoryHome(props); } finally { hooks = null; } }, setProps(next) { props = { ...props, ...next }; }, mount() { return state.effects.map(effect => effect()); } };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const markup = tree => renderToStaticMarkup(tree);
const category = "22222222-2222-4222-8222-222222222222";
const parameters = [{ parameter_id: "pressure", version: 2, key: "pressure", name: "合成气压", unit: "psi", value_type: "number", standard_condition: "合成工况" }];
const knowledge = [{ id: "boundary", kind: "boundary", status: "active", origin: "human", content: { definition: "合成边界" } }, {
  id: "competitor", version: 3, kind: "competitor", status: "active", origin: "ai_draft", source_changes: [{ status: "stale" }], content: { brand: "合成品牌", model: "A-01", prices: [
    { amount: "0", currency: "USD", observed_on: "2026-10-15", price_type: "retail", includes_tax: false, includes_shipping: null },
    { amount: "199", currency: "CNY", observed_on: "2026-10-16", price_type: "promo", includes_tax: true, includes_shipping: false }], metrics: [
    { parameter_id: "pressure", parameter_version: 2, value: 0, unit: "psi", nature: "claimed", condition_note: "合成低温工况" },
    { parameter_id: "pressure", parameter_version: 1, value: false, nature: "inferred", condition_note: null }] }
}, { id: "voice", kind: "voice", origin: "human", status: "active", content: { label: "合成场景标签", source_platform: "合成来源平台", sample_size: 3 } },
{ id: "regulation", kind: "regulation", origin: "ai_draft", status: "active", content: { instrument: "合成法规", region: "合成地区", source_state: "confirmed", applicability_state: "unknown", compliance_state: "unknown", requirement_kind: "voluntary_reference" } }];
function api(calls, failure = () => false) { return async (route, body) => {
  calls.push({ route, body });
  if (failure(route)) throw new Error("合成读取失败");
  if (route.endsWith("/products")) return [{ id: "model-a", name: "合成型号", purpose: "合成用途" }];
  if (route.includes("/parameters?")) return { items: parameters, next_cursor: null };
  if (route.includes("cursor=next")) return { items: knowledge.slice(2), next_cursor: null };
  return { items: knowledge.slice(0, 2), next_cursor: "next" };
}; }
function switchView(tree, label) { const button = elements(tree, e => e.type === "button" && e.props.children === label)[0]; assert.ok(button); button.props.onClick(); }
function create(api, opened = []) { return driver({ categoryId: category, categoryName: "合成品类", api, onOpenPai() { opened.push("pai"); }, onOpenWorkbench(...args) { opened.push(args); } }); }

test("category reads every knowledge page once and keeps original price, condition and per-observation nature", async () => {
  const calls = [], component = create(api(calls)); component.render(); component.mount(); await tick();
  const html = markup(component.render());
  for (const value of ["合成边界", "合成品牌", "0 USD", "199 CNY", "2026-10-15", "合成低温工况", "宣传", "推断", "未映射参数", "v1", "来源需重核"]) assert.ok(html.includes(value), value);
  assert.match(html, /含税：否/); assert.match(html, /合成气压.*<b>0<\/b>/); assert.match(html, /<b>否<\/b>/);
  assert.equal(calls.filter(call => call.route.includes("/knowledge?")).length, 2);
  assert.ok(calls.every(call => call.body === undefined));
});
test("six knowledge views use the same reads and retain real proposal and standard matching components", async () => {
  const calls = [], opened = [], component = create(api(calls), opened); component.render(); component.mount(); await tick();
  let tree = component.render(), html = markup(tree);
  assert.match(html, /data-preserved="ProposalList"/); assert.match(html, /data-preserved="StandardMatch"/);
  switchView(tree, "用户声音"); tree = component.render(); html = markup(tree); assert.match(html, /合成场景标签/); assert.match(html, /合成来源平台/); assert.doesNotMatch(html, /32%|47 条|<blockquote/);
  switchView(tree, "法规认证"); tree = component.render(); html = markup(tree); assert.match(html, /符合性：未知/); assert.match(html, /自愿参考/); assert.doesNotMatch(html, /已符合/);
  switchView(tree, "规格字典"); tree = component.render(); assert.match(markup(tree), /合成工况/);
  switchView(tree, "型号"); tree = component.render(); const openModel = elements(tree, e => e.props?.children?.some?.(child => child === "打开型号"))[0]; openModel.props.onClick(); assert.deepEqual(opened, [["products", "model-a"]]);
  switchView(tree, "品类矩阵"); tree = component.render(); html = markup(tree); assert.match(html, /data-preserved="CategoryMatrix"/); assert.doesNotMatch(html, /<table|2 款竞品|目标格/);
  assert.equal(calls.length, 4);
});
test("read failure remains a retryable error and cannot become a zero count or empty knowledge claim", async () => {
  const calls = []; let failed = true;
  const component = create(api(calls, route => failed && route.includes("/knowledge?")));
  component.render(); component.mount(); await tick(); let tree = component.render(), html = markup(tree);
  assert.match(html, /竞品库暂不可读：合成读取失败/); assert.doesNotMatch(html, /0 条当前记录|尚无竞品库记录/);
  failed = false; elements(tree, e => e.props?.["aria-label"] === "刷新品类资料")[0].props.onClick(); component.render(); component.mount(); await tick();
  tree = component.render(); assert.match(markup(tree), /合成品牌/); assert.doesNotMatch(markup(tree), /合成读取失败/);
});
test("a repeated pagination cursor fails visibly instead of presenting a partial count", async () => {
  const calls = [], component = create(async route => { calls.push(route); if (route.endsWith("/products")) return []; if (route.includes("/parameters?")) return { items: [], next_cursor: null }; return { items: [], next_cursor: "stuck" }; });
  component.render(); component.mount(); await tick(); const html = markup(component.render()); assert.match(html, /资料分页位置未推进/); assert.doesNotMatch(html, /0 条当前记录/); assert.equal(calls.filter(route => route.includes("knowledge")).length, 2);
});
test("unmounted category reads cannot publish late records into another category", async () => {
  const pending = []; const component = create(route => new Promise(resolve => pending.push({ route, resolve })));
  component.render(); const cleanups = component.mount(); cleanups.forEach(cleanup => cleanup());
  for (const read of pending) read.resolve(read.route.endsWith("/products") ? [{ id: "late", name: "迟到型号", purpose: "迟到" }] : { items: knowledge, next_cursor: null });
  await tick(); const html = markup(component.render()); assert.doesNotMatch(html, /合成品牌|迟到型号/); assert.match(html, /正在读取竞品库/);
});
test("competitor segment maintenance loads only when opened and save invalidates category and matrix reads", async () => {
  const calls = [], component = create(api(calls)); component.render(); component.mount(); await tick();
  let tree = component.render(); assert.equal(elements(tree, e => e.props?.entryId === "competitor").length, 0);
  const button = elements(tree, e => e.props?.children === "维护细分")[0]; assert.ok(button); button.props.onClick(); tree = component.render();
  const editor = elements(tree, e => e.props?.entryId === "competitor")[0]; assert.equal(editor.props.categoryId, category); assert.equal(calls.length, 4);
  editor.props.onSaved(); tree = component.render(); assert.match(markup(tree), /正在读取竞品库/); component.mount(); await tick(); tree = component.render();
  assert.equal(calls.length, 8); switchView(tree, "品类矩阵"); tree = component.render();
  const matrix = elements(tree, e => e.props?.onOpenProduct && e.props?.categoryId === category)[0]; assert.equal(matrix.key, `${category}:1`);
});
test("category and API scope changes synchronously hide prior category content and its editor before effects", async () => {
  const calls = [], component = create(api(calls)); component.render(); component.mount(); await tick(); let tree = component.render();
  elements(tree, e => e.props?.children === "维护细分")[0].props.onClick(); component.render();
  component.setProps({ categoryId: "33333333-3333-4333-8333-333333333333", categoryName: "另一个品类" }); tree = component.render();
  assert.doesNotMatch(markup(tree), /合成品牌|合成边界|data-preserved="CompetitorSegments"/); assert.match(markup(tree), /正在读取竞品库/);
  component.setProps({ categoryId: category, api: api([]) }); tree = component.render(); assert.doesNotMatch(markup(tree), /合成品牌|合成边界|data-preserved="CompetitorSegments"/);
});
test("a refresh hides late records from its earlier read even before effect cleanup", async () => {
  const pending = [], component = create(route => new Promise(resolve => pending.push({ route, resolve }))); let tree = component.render(); component.mount();
  elements(tree, e => e.props?.["aria-label"] === "刷新品类资料")[0].props.onClick(); component.render();
  for (const read of pending) read.resolve(read.route.endsWith("/products") ? [] : { items: read.route.includes("/knowledge?") ? knowledge : [], next_cursor: null });
  await tick(); tree = component.render(); assert.doesNotMatch(markup(tree), /合成品牌|合成边界/); assert.match(markup(tree), /正在读取竞品库/);
});
