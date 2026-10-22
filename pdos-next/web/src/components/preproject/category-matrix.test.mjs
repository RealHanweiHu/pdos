import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Local hook driver exercises actual read effects and event handlers. */
const react = { ...React, useState(initial) {
  if (!hooks) return React.useState(initial);
  const own = hooks, index = own.index++;
  if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial;
  return [own.slots[index], next => { if (!own.disposed) { own.slots[index] = typeof next === "function" ? next(own.slots[index]) : next; own.dirty = true; } }];
}, useRef(initial) { if (!hooks) return React.useRef(initial); const index = hooks.index++; return hooks.slots[index] ??= { current: initial }; }, useEffect(effect, deps) {
  if (!hooks) return React.useEffect(effect, deps);
  const own = hooks, index = own.index++;
  if (!same(own.slots[index]?.deps, deps)) { const previous = own.slots[index]; const entry = { deps, cleanup: previous?.cleanup }; own.slots[index] = entry; own.effects.push(() => { entry.cleanup?.(); entry.cleanup = effect(); }); }
} };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { CategoryMatrix } = load(path.join(directory, "category-matrix.tsx"));
const { matrixBreaks, categoryMatrixPath, isCategoryMatrixResponse } = load(path.join(webRoot, "src/lib/category-matrix.ts"));
const tick = () => new Promise(resolve => setImmediate(resolve));
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
const html = tree => renderToStaticMarkup(tree);
const source = { type: "snapshot", id: "exact-source", version: 4, locator: { line: 8 }, quote: "INERT_SOURCE_TEXT", url: "javascript:alert(1)" };
const segment = { lineage_id: "segment", version: 2, entry_id: "segment-version-two", label: "合成细分", status: "active", source_refs: [{ type: "knowledge", id: "segment-source", version: 2 }], reasons: [] };
const makePlacement = (type, id, amount = "199.12345678901234567890") => ({ subject: { type, id, label: `合成${id}`, revision: 3 }, price: { amount, currency: "CNY", basis: "retail", as_of: "2026-10-17", includes_tax: false, includes_shipping: null, region: "CN", channel: "线上", source_refs: [source], g0_source: { proposal_id: "fixed-proposal", submission_id: "fixed-submission", document_digest: "fixed-digest" } }, source_refs: [source] });
function response(categoryId = "category", breaks = ["150", "300"]) {
  const bands = [...breaks, null].map((upper, index) => ({ id: `band:${index}`, lower: index === 0 ? null : breaks[index - 1], upper, lower_inclusive: index !== 0, upper_inclusive: false }));
  const own = makePlacement("product", "我方"), competitor = makePlacement("competitor", "竞品", "0");
  const cells = bands.map((band, index) => ({ band_id: band.id, status: index < 2 ? "observed" : "no_readable_observations", products: index === 1 ? [own] : [], competitors: index === 0 ? [competitor] : [], counts: { products: index === 1 ? 1 : 0, competitors: index === 0 ? 1 : 0 } }));
  return { version: "category-matrix/v1", category_id: categoryId, as_of: "2026-10-17T17:00:00Z", display: { breaks, bands, semantics: "read_only_distribution" }, groups: [{ id: "CNY", basis: { currency: "CNY", as_of: "2026-10-17", basis: "retail", includes_tax: false, includes_shipping: null, region: "CN", channel: "线上" }, rows: [{ segment, cells }] }], unplaced: [{ ...makePlacement("product", "未知"), fixed_segment: null, reasons: ["segment_missing", "g0_price_source_unavailable"] }], coverage: { visible_products: 2, visible_competitors: 1, placed_subjects: 2, unplaced_subjects: 1, partially_placed_subjects: 0, placements: 2, price_observations: 3, reason_counts: { segment_missing: 1 } }, limitations: ["empty_cells_are_not_market_gaps", "target_price_requires_readable_matching_g0_source"] };
}
function environment(t) {
  const calls = [], opened = [];
  const api = (url, body) => new Promise((resolve, reject) => calls.push({ url, body, resolve, reject }));
  let props = { categoryId: "category", api, onOpenProduct: id => opened.push(id) }, instance, key, tree;
  function unmount() { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } }
  function render() {
    const wrapper = CategoryMatrix(props);
    if (!instance || wrapper.key !== key) { unmount(); key = wrapper.key; instance = { slots: [], index: 0, effects: [], dirty: true, disposed: false }; }
    instance.index = 0; instance.effects = []; instance.dirty = false; hooks = instance;
    try { tree = wrapper.type(wrapper.props); } finally { hooks = null; }
    instance.effects.forEach(effect => effect());
  }
  render(); t.after(unmount);
  return { calls, opened, tree: () => tree, html: () => html(tree), setCategory(categoryId) { props = { ...props, categoryId }; render(); }, async flush() { for (let i = 0; i < 5; i++) { await tick(); if (instance.dirty) render(); } return tree; }, async submit(value) { elements(tree, item => item.type === "input")[0].props.onChange({ target: { value } }); await this.flush(); elements(tree, item => item.type === "form")[0].props.onSubmit({ preventDefault() {} }); return this.flush(); } };
}

test("price break inputs remain exact decimals and reject ambiguous, duplicate or nonincreasing boundaries", () => {
  assert.deepEqual(matrixBreaks("00150.00，300.000"), ["150", "300"]);
  assert.deepEqual(matrixBreaks("0.00000000000000000001, 9007199254740993.00000000000000001"), ["0.00000000000000000001", "9007199254740993.00000000000000001"]);
  assert.deepEqual(matrixBreaks(".5,1."), ["0.5", "1"]);
  for (const value of ["", "0,300", "150,150.0", "300,150", "-1,300", "NaN", "Infinity", "100x", "1,2,3,4,5,6,7,8,9,10,11"]) assert.throws(() => matrixBreaks(value), Error, value);
  assert.equal(categoryMatrixPath("cat/scope", ["150.01", "300"]), "v1/categories/cat%2Fscope/category-matrix?price_breaks=150.01&price_breaks=300");
});

test("transport rejects another category, another partition and incomplete facts", () => {
  const data = response(); assert.ok(isCategoryMatrixResponse(data, "category", ["150.0", "300"]));
  assert.equal(isCategoryMatrixResponse(data, "other", ["150", "300"]), false);
  assert.equal(isCategoryMatrixResponse(data, "category", ["100", "300"]), false);
  for (const mutate of [value => { value.version = "other"; }, value => { delete value.coverage; }, value => { value.groups[0].basis.includes_tax = "false"; }, value => { value.groups[0].rows[0].cells.pop(); }, value => { value.groups[0].rows[0].cells[0].competitors[0].source_refs = null; }]) { const malformed = structuredClone(data); mutate(malformed); assert.equal(isCategoryMatrixResponse(malformed, "category", ["150", "300"]), false); }
});

test("default read renders loading without invented zero coverage, then preserves precise values and source identities", async t => {
  const env = environment(t); assert.match(env.html(), /正在读取/); assert.doesNotMatch(env.html(), /可见型号|暂无可读记录/);
  assert.equal(env.calls[0].url, "v1/categories/category/category-matrix?price_breaks=150&price_breaks=300");
  env.calls[0].resolve(response()); await env.flush(); const markup = env.html();
  for (const text of ["199.12345678901234567890", "fixed-submission", "exact-source", "segment-source", "INERT_SOURCE_TEXT", "≥300", "[150, 300)", "暂无可读记录", "含税", "否", "线上"]) assert.ok(markup.includes(text), text);
  assert.doesNotMatch(markup, /市场空档|>空档</); assert.equal(markup.includes('href="javascript:'), false);
  const matrix = elements(env.tree(), item => item.type === "table")[0]; assert.doesNotMatch(html(matrix), /合成未知/);
  assert.ok(env.calls.every(call => call.body === undefined));
});

test("complete price bases remain separate and product navigation uses only the returned product identity", async t => {
  const env = environment(t), data = response();
  data.groups.push({ ...structuredClone(data.groups[0]), id: "USD", basis: { ...data.groups[0].basis, currency: "USD", as_of: "2026-10-18", includes_tax: true, includes_shipping: false, region: "US", channel: "线下", basis: "wholesale" } });
  env.calls[0].resolve(data); await env.flush();
  assert.equal(elements(env.tree(), item => item.type === "table").length, 2);
  for (const text of ["CNY", "USD", "2026-10-17", "2026-10-18", "批发", "线下", "含运费"]) assert.ok(env.html().includes(text));
  const placement = elements(env.tree(), item => item.props?.item?.subject?.id === "我方")[0];
  const element = placement.type(placement.props);
  elements(element, item => item.type === "button")[0].props.onClick(); assert.deepEqual(env.opened, ["我方"]);
  assert.match(html(placement), /data-kind="product"/);
  assert.match(html(elements(env.tree(), item => item.props?.item?.subject?.id === "竞品")[0]), /data-kind="competitor"/);
  assert.equal(env.calls.length, 1);
});

test("invalid display inputs retain the last verified read and never issue a request", async t => {
  const env = environment(t); env.calls[0].resolve(response()); await env.flush(); await env.submit("300, 150");
  assert.match(env.html(), /价格分界须严格递增/); assert.match(env.html(), /合成我方/); assert.equal(env.calls.length, 1);
});

test("late results from superseded breaks and a previous category cannot replace current data", async t => {
  const env = environment(t); await env.submit("100, 250"); assert.equal(env.calls.length, 2);
  env.calls[1].resolve(response("category", ["100", "250"])); await env.flush();
  env.calls[0].resolve(response()); await env.flush(); assert.match(env.html(), /当前分界：100、250/); assert.doesNotMatch(env.html(), /当前分界：150、300/);
  env.setCategory("other"); assert.match(env.html(), /正在读取/); assert.doesNotMatch(env.html(), /合成我方/);
  env.calls[2].resolve(response("other")); await env.flush(); assert.match(env.html(), /当前分界：150、300/); assert.ok(env.calls.every(call => call.body === undefined));
});

test("read failure and mismatched envelopes hide old success, and retry rereads the same authorized path", async t => {
  const env = environment(t); env.calls[0].resolve(response()); await env.flush();
  elements(env.tree(), item => item.props?.children?.some?.(child => child === "刷新"))[0].props.onClick(); await env.flush();
  assert.doesNotMatch(env.html(), /合成我方/); env.calls[1].reject(new Error("合成暂不可读")); await env.flush();
  assert.match(env.html(), /合成暂不可读/); assert.doesNotMatch(env.html(), /可见型号/);
  elements(env.tree(), item => item.props?.children === "重新读取矩阵")[0].props.onClick(); await env.flush();
  env.calls[2].resolve(response("wrong-scope")); await env.flush(); assert.match(env.html(), /当前品类、价格分界不一致/);
  elements(env.tree(), item => item.props?.children === "重新读取矩阵")[0].props.onClick(); await env.flush();
  env.calls[3].resolve(response()); await env.flush(); assert.match(env.html(), /合成我方/); assert.equal(new Set(env.calls.map(call => call.url)).size, 1); assert.ok(env.calls.every(call => call.body === undefined));
});

test("empty readable sets and unknown observations stay distinct", async t => {
  const env = environment(t), data = response(); data.groups = []; data.limitations.push("competitor_segments_missing");
  env.calls[0].resolve(data); await env.flush(); assert.match(env.html(), /没有同时具备可读细分与价格依据/); assert.match(env.html(), /未登记明确的细分关联/); assert.match(env.html(), /未取得可读的固定立项价格来源/); assert.match(env.html(), /部分竞品尚未关联固定细分/);
  const empty = environment(t), blank = response(); blank.groups = []; blank.unplaced = []; Object.keys(blank.coverage).forEach(key => { if (key !== "reason_counts") blank.coverage[key] = 0; }); blank.coverage.reason_counts = {};
  empty.calls[0].resolve(blank); await empty.flush(); assert.match(empty.html(), /可见范围内尚无型号或竞品记录/); assert.doesNotMatch(empty.html(), /未落格记录/);
});
