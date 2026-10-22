import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Local hook driver executes real scope keys, GET effects and retries. */
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
const { ProposalVoices } = load(path.join(directory, "proposal-voices.tsx"));
const { isProposalVoicesResponse, proposalVoiceQuotes, proposalVoicesPath, readProposalVoices } = load(path.join(webRoot, "src/lib/proposal-voices.ts"));
const document = { proposal_id: "proposal", revision: 3, document_digest: "fixed-digest", submission_id: "fixed-submission", document_mode: "frozen" };
const source = { type: "snapshot", id: "fixed-source", version: 1, line: 8, quote: "ACTUAL_QUOTE <img src=x onerror=alert(1)>", url: "javascript:alert(1)" };
const entry = { knowledge_id: "voice-one", lineage_id: "voice-lineage", version: 1, label: "SUMMARY_LABEL", source_platform: "合成平台", origin: "ai_draft", status: "active", current_version: 2, sample_size: 7, source_refs: [source], representative_refs: [source], related_items: [{ item_id: "real-item", version: 4, kind: "spec", label: "已关联的真实规格" }], used_in_context: true, source_changes: [{ type: "knowledge", id: "voice-one", version: 1, current_version: 2, status: "active" }] };
function response(identity = document) { return structuredClone({ version: "proposal-voices/v1", category_id: "category", document: identity, as_of: "2026-10-17T20:00:00Z", entries: [entry], unavailable: [], counts: { entries: 1, unavailable_entries: 0 } }); }
const tick = () => new Promise(resolve => setImmediate(resolve));
const html = tree => renderToStaticMarkup(tree);
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
function environment(t, overrides = {}) {
  const calls = [];
  const reader = (url, signal) => new Promise((resolve, reject) => calls.push({ url, signal, resolve, reject }));
  let props = { categoryId: "category", proposalId: "proposal", document, readVersion: 1, reader, ...overrides }, instance, key, tree;
  function unmount() { if (instance) { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; } }
  function render() { const wrapper = ProposalVoices(props); if (!instance || wrapper.key !== key) { unmount(); key = wrapper.key; instance = { slots: [], index: 0, effects: [], dirty: true, disposed: false }; } instance.index = 0; instance.effects = []; instance.dirty = false; hooks = instance; try { tree = wrapper.type(wrapper.props); } finally { hooks = null; } instance.effects.forEach(effect => effect()); }
  render(); t.after(unmount);
  return { calls, tree: () => tree, html: () => html(tree), setProps(next) { props = { ...props, ...next }; render(); }, async flush() { for (let i = 0; i < 5; i++) { await tick(); if (instance.dirty) render(); } return tree; }, async refresh() { elements(tree, item => item.props?.["aria-label"] === "刷新本案声音")[0].props.onClick(); return this.flush(); } };
}

test("transport matches category and all five document identity fields before displaying a voice", () => {
  assert.ok(isProposalVoicesResponse(response(), "category", document));
  assert.equal(isProposalVoicesResponse(response(), "other", document), false);
  for (const [key, value] of Object.entries({ proposal_id: "other", revision: 4, document_digest: "other", submission_id: null, document_mode: "current" })) assert.equal(isProposalVoicesResponse(response(), "category", { ...document, [key]: value }), false, key);
  for (const mutate of [value => { value.version = "unknown"; }, value => { value.entries[0].sample_size = "7"; }, value => { value.counts.entries = 3; }, value => { value.entries[0].source_refs[0].status = "unavailable"; }, value => { value.entries[0].source_changes[0].status = "withdrawn"; }]) { const malformed = response(); mutate(malformed); assert.equal(isProposalVoicesResponse(malformed, "category", document), false); }
});

test("actual quote fields preserve exact text and deduplicate references without turning labels or statements into quotations", () => {
  assert.equal(proposalVoiceQuotes(entry).length, 1);
  assert.equal(proposalVoiceQuotes(entry)[0].quote, source.quote);
  assert.deepEqual(proposalVoiceQuotes({ ...entry, representative_refs: [{ type: "human", id: "person", version: 1, statement: "NAMED_STATEMENT" }], source_refs: [{ type: "snapshot", id: "blocked", version: 1, quote: "OLD_QUOTE", status: "unavailable" }] }), []);
});

test("default reader uses the exact scoped GET with cache bypass and the caller's abort signal", async t => {
  const saved = globalThis.fetch, calls = [], controller = new AbortController();
  globalThis.fetch = async (url, options) => { calls.push({ url, options }); return { ok: true, json: async () => response() }; };
  t.after(() => { globalThis.fetch = saved; });
  const path = proposalVoicesPath("cat/a", "proposal/a"); assert.equal(path, "/api/v1/categories/cat%2Fa/proposals/proposal%2Fa/voices");
  await readProposalVoices(path, controller.signal); assert.equal(calls.length, 1); assert.deepEqual(calls[0], { url: path, options: { method: "GET", cache: "no-store", signal: controller.signal } });
  globalThis.fetch = async () => ({ ok: false, json: async () => ({ message: "受众已变化" }) });
  await assert.rejects(() => readProposalVoices(path, controller.signal), /受众已变化/);
});

test("readable voice cards distinguish summary, original quote, sample registration and explicit item references", async t => {
  const env = environment(t); assert.match(env.html(), /正在读取/); assert.doesNotMatch(env.html(), /0 条可读|本案没有明确/);
  assert.equal(env.calls.length, 1); assert.equal(env.calls[0].url, "/api/v1/categories/category/proposals/proposal/voices");
  env.calls[0].resolve(response()); await env.flush(); const markup = env.html();
  for (const text of ["SUMMARY_LABEL", "声音标签 / 摘要", "ACTUAL_QUOTE &lt;img", "登记样本 7", "AI 草稿", "合成平台", "固定 v1", "更新至 v2", "已作为本案上下文引用", "已关联的真实规格", "real-item", "fixed-source", "第 8 行"]) assert.ok(markup.includes(text), text);
  assert.equal((markup.match(/<blockquote/g) ?? []).length, 1);
  assert.doesNotMatch(markup, /<img|href="javascript:|%|综合评分/);
  const voice = elements(env.tree(), item => item.props?.entry?.knowledge_id === "voice-one")[0], card = voice.type(voice.props);
  assert.doesNotMatch(html(elements(card, item => item.props?.className === "associations")[0]), /real-item/);
  assert.match(html(elements(card, item => item.props?.className === "sources")[0]), /real-item/);
  assert.equal(env.calls.length, 1);
});

test("labels without quote fields remain summaries and null sample sizes never become zero", async t => {
  const env = environment(t), value = response(); value.entries[0].representative_refs = [{ type: "knowledge", id: "identity-only", version: 1 }]; value.entries[0].source_refs = []; value.entries[0].sample_size = null; value.entries[0].related_items = []; value.entries[0].used_in_context = false;
  env.calls[0].resolve(value); await env.flush(); const markup = env.html();
  assert.match(markup, /SUMMARY_LABEL/); assert.match(markup, /未提供可读原文片段/); assert.match(markup, /登记样本数未知/); assert.match(markup, /identity-only/);
  assert.doesNotMatch(markup, /<blockquote|登记样本 0|已关联的真实规格/);
});

test("unreadable voices show only returned reference identities and reasons, including when an old body is mistakenly present", async t => {
  const env = environment(t), value = response(); value.entries = []; value.counts = { entries: 0, unavailable_entries: 1 }; value.unavailable = [{ reference: { type: "knowledge", id: "unreadable-ref", version: 2, quote: "LEAK_REFERENCE_QUOTE", label: "LEAK_REFERENCE_LABEL" }, reasons: ["source_unavailable"], label: "LEAK_LABEL", sample_size: 999, quote: "LEAK_QUOTE", source_refs: [source] }];
  env.calls[0].resolve(value); await env.flush(); const markup = env.html();
  assert.match(markup, /unreadable-ref/); assert.match(markup, /底层来源不可读/); assert.match(markup, /部分知识引用当前无法核对/);
  assert.doesNotMatch(markup, /LEAK_|ACTUAL_QUOTE|999|本案没有明确的声音引用/);
});

test("malformed fixed references retain only their safe identity metadata and explicit reason", async t => {
  const env = environment(t), value = response(); value.entries = []; value.counts = { entries: 0, unavailable_entries: 2 };
  value.unavailable = [{ reference: { type: "knowledge", id: "malformed-identity", version: "bad-version" }, reasons: ["knowledge_reference_invalid"] }, { reference: { type: "knowledge" }, reasons: ["knowledge_reference_invalid"] }];
  env.calls[0].resolve(value); await env.flush(); const markup = env.html();
  assert.match(markup, /malformed-identity/); assert.match(markup, /bad-version/); assert.match(markup, /声音引用身份不完整/); assert.match(markup, /编号未提供/); assert.match(markup, /版本未提供/); assert.doesNotMatch(markup, /ACTUAL_QUOTE|资料不完整，请刷新后重试/);
});

test("same frozen identity with a new read version clears old text immediately and rejects late responses", async t => {
  const env = environment(t); env.calls[0].resolve(response()); await env.flush(); assert.match(env.html(), /ACTUAL_QUOTE/);
  await env.refresh(); const old = env.calls[1]; env.setProps({ readVersion: 2 });
  assert.equal(old.signal.aborted, true); assert.doesNotMatch(env.html(), /ACTUAL_QUOTE|SUMMARY_LABEL/);
  const fresh = response(); fresh.entries = []; fresh.counts.entries = 0; env.calls[2].resolve(fresh); await env.flush(); old.resolve(response()); await env.flush();
  assert.match(env.html(), /本案没有明确的声音引用/); assert.doesNotMatch(env.html(), /ACTUAL_QUOTE|SUMMARY_LABEL/); assert.equal(env.calls.length, 3);
});

test("scope and immutable identity changes abort reads before any old content can appear", async t => {
  const env = environment(t); env.calls[0].resolve(response()); await env.flush();
  const nextDocument = { ...document, proposal_id: "other-proposal", revision: 4, document_digest: "next-digest", submission_id: null, document_mode: "current" };
  env.setProps({ categoryId: "other-category", proposalId: "other-proposal", document: nextDocument });
  assert.equal(env.calls[0].signal.aborted, true); assert.match(env.html(), /正在读取/); assert.doesNotMatch(env.html(), /ACTUAL_QUOTE/);
  env.calls[1].resolve(response()); await env.flush(); assert.match(env.html(), /声音结果与当前提案文档不一致/); assert.doesNotMatch(env.html(), /ACTUAL_QUOTE/);
});

test("GET failures and retries hide stale success and reuse only the current scoped read", async t => {
  const env = environment(t); env.calls[0].resolve(response()); await env.flush(); await env.refresh();
  assert.doesNotMatch(env.html(), /ACTUAL_QUOTE/); env.calls[1].reject(new Error("合成读取失败")); await env.flush();
  assert.match(env.html(), /合成读取失败/); assert.doesNotMatch(env.html(), /本案没有明确的声音引用|0 条可读/);
  elements(env.tree(), item => item.props?.children === "重新读取本案声音")[0].props.onClick(); await env.flush();
  env.calls[2].resolve(response()); await env.flush(); assert.match(env.html(), /ACTUAL_QUOTE/); assert.equal(new Set(env.calls.map(call => call.url)).size, 1);
});
