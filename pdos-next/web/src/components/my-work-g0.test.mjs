import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Local dispatcher runs the actual independent G0 queue hook. */
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
  loaded.require = name => name === "react" ? react : name === "next/link" ? props => React.createElement("a", { href: props.href }, props.children) : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { useMyWorkG0, MyWorkG0 } = load(path.join(directory, "my-work-g0.tsx"));
const { isPersonalG0Page, personalG0Href, mergePersonalG0 } = load(path.join(webRoot, "src/lib/personal-g0-reviews.ts"));
const tick = () => new Promise(resolve => setImmediate(resolve));
const html = tree => renderToStaticMarkup(tree);
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
function review(id, principalId = "me") { return { proposal_id: id, title: `合成提案 ${id}`, proposal_revision: 4, status: "in_review", category: { id: "category", name: "合成品类" }, owner: { id: "owner", name: "合成负责人" }, reviewer_id: principalId, submission: { id: `submission-${id}`, revision: 3, submitted_at: "2026-10-17T20:00:00Z", document_digest: `digest-${id}` } }; }
function page(items = [review("one")], total = items.length, cursor = null, principalId = "me") { return { version: "personal-g0-reviews/v1", principal_id: principalId, as_of: "2026-10-17T20:00:00Z", total_pending: total, items, next_cursor: cursor }; }
/* eslint-disable react-hooks/rules-of-hooks -- Test-only dispatcher executes the actual queue hook. */
function environment(t) {
  const calls = [], api = (url, body) => new Promise((resolve, reject) => calls.push({ url, body, resolve, reject }));
  let props = { api, principalId: "me", reload: 0 }, queue, tree;
  const state = { slots: [], index: 0, effects: [], dirty: true, disposed: false };
  function render() { state.index = 0; state.effects = []; state.dirty = false; hooks = state; try { queue = useMyWorkG0(props.api, props.principalId, props.reload); tree = MyWorkG0({ queue }); } finally { hooks = null; } state.effects.forEach(effect => effect()); }
  function unmount() { state.slots.forEach(slot => slot?.cleanup?.()); state.disposed = true; }
  render(); t.after(unmount);
  return { calls, queue: () => queue, tree: () => tree, html: () => html(tree), setProps(next) { props = { ...props, ...next }; render(); }, async flush() { for (let i = 0; i < 6; i++) { await tick(); if (state.dirty) render(); } return tree; }, async more() { void queue.loadMore(); return this.flush(); }, async refresh() { queue.refresh(); return this.flush(); } };
}
/* eslint-enable react-hooks/rules-of-hooks */

test("G0 metadata contract keeps exact reviewer identity, current state and fixed submission separate", () => {
  assert.ok(isPersonalG0Page(page(), "me")); assert.equal(isPersonalG0Page(page(), "other"), false);
  for (const mutate of [value => { value.items[0].reviewer_id = "other"; }, value => { value.items[0].status = "approved"; }, value => { value.items[0].submission = null; }, value => { value.items[0].submission.document_digest = ""; }, value => { value.total_pending = null; }]) { const value = page(); mutate(value); assert.equal(isPersonalG0Page(value, "me"), false); }
  assert.equal(personalG0Href({ ...review("proposal/one"), category: { id: "category/scope", name: "x" } }), "/categories/category%2Fscope/proposals/proposal%2Fone");
  assert.equal(mergePersonalG0([review("one")], [{ ...review("one"), title: "最新头标题" }])[0].title, "最新头标题");
});

test("first page uses server total_pending, labels loaded coverage and never invents a deadline, unread count or qualification", async t => {
  const env = environment(t); assert.match(env.html(), /正在读取/); assert.equal(env.queue().totalPending, null);
  env.calls[0].resolve(page(Array.from({ length: 50 }, (_, index) => review(`p-${index}`)), 120, "cursor-one")); await env.flush();
  const rendered = env.html(); assert.equal(env.queue().totalPending, 120); assert.equal(env.queue().items.length, 50);
  assert.match(rendered, /已加载 <b>50<\/b> \/ 全部 <b>120<\/b>/); assert.match(rendered, /加载更多 G0 评审/);
  for (const text of ["G0 立项评审待我决定", "合成负责人", "当前提案 v4", "固定提交 v3", "提交于"]) assert.ok(rendered.includes(text));
  assert.doesNotMatch(rendered, /逾期|到期|未读|资格|确认批准|<form/); assert.equal(env.calls.length, 1); assert.ok(env.calls.every(call => call.body === undefined));
});

test("explicit pagination deduplicates proposal cards and retains only original proposal navigation", async t => {
  const env = environment(t); env.calls[0].resolve(page([review("one"), review("two")], 3, "cursor/one")); await env.flush();
  void env.queue().loadMore(); void env.queue().loadMore(); await env.flush(); assert.equal(env.calls.length, 2);
  assert.equal(env.calls[1].url, "v1/personal/g0-reviews?page_size=50&cursor=cursor%2Fone");
  env.calls[1].resolve(page([{ ...review("two"), title: "第二案当前新头" }, review("three")], 3)); await env.flush();
  assert.equal(env.queue().items.length, 3); assert.match(env.html(), /第二案当前新头/); assert.doesNotMatch(env.html(), /加载更多 G0 评审/);
  const links = elements(env.tree(), item => typeof item.props?.href === "string"); assert.equal(links.length, 3);
  assert.deepEqual(links.map(item => item.props.href), ["/categories/category/proposals/one", "/categories/category/proposals/two", "/categories/category/proposals/three"]);
  assert.ok(env.calls.every(call => call.body === undefined));
});

test("repeated cursors fail closed and a fresh retry resets the paging history", async t => {
  const env = environment(t); env.calls[0].resolve(page([review("one")], 2, "cursor-one")); await env.flush(); await env.more();
  env.calls[1].resolve(page([review("two")], 2, "cursor-one")); await env.flush();
  assert.match(env.html(), /G0 分页位置未推进/); assert.equal(env.queue().totalPending, null); assert.doesNotMatch(env.html(), /合成提案 one/);
  await env.refresh(); assert.equal(env.calls[2].url, "v1/personal/g0-reviews?page_size=50");
  env.calls[2].resolve(page([review("one")], 2, "cursor-one")); await env.flush(); await env.more();
  env.calls[3].resolve(page([review("two")], 2)); await env.flush(); assert.equal(env.queue().items.length, 2); assert.equal(env.queue().error, "");
});

test("cursor permission loss and changing totals remove stale G0 metadata and require a fresh read", async t => {
  const env = environment(t); env.calls[0].resolve(page([review("one")], 2, "cursor-one")); await env.flush(); await env.more();
  env.calls[1].reject(Object.assign(new Error("分页引用已不在本人待评审范围，请刷新"), { code: "FORBIDDEN_SCOPE", status: 403 })); await env.flush();
  assert.match(env.html(), /已不在本人待评审范围/); assert.equal(env.queue().totalPending, null); assert.equal(env.queue().items.length, 0);
  await env.refresh(); env.calls[2].resolve(page([review("one")], 2, "cursor-one")); await env.flush(); await env.more();
  env.calls[3].resolve(page([review("two")], 3, "cursor-two")); await env.flush(); assert.match(env.html(), /G0 队列已有变化/); assert.equal(env.queue().totalPending, null);
});

test("principal and parent reload changes hide cards immediately and isolate late pagination responses", async t => {
  const env = environment(t); env.calls[0].resolve(page([review("one")], 2, "cursor-one")); await env.flush(); await env.more();
  env.setProps({ reload: 1 }); assert.match(env.html(), /正在读取/); assert.doesNotMatch(env.html(), /合成提案 one/);
  env.calls[1].resolve(page([review("two")], 2)); await env.flush(); assert.doesNotMatch(env.html(), /合成提案 two/);
  env.calls[2].resolve(page([review("fresh")])); await env.flush(); assert.match(env.html(), /合成提案 fresh/);
  env.setProps({ principalId: "other" }); assert.match(env.html(), /正在读取/); assert.doesNotMatch(env.html(), /合成提案 fresh/);
  env.calls[3].resolve(page([review("other-proposal", "other")], 1, null, "other")); await env.flush(); assert.match(env.html(), /other-proposal/); assert.equal(env.queue().totalPending, 1);
});

test("wrong-principal pages and failed initial reads remain unknown rather than an empty decision queue", async t => {
  const env = environment(t); env.calls[0].resolve(page([review("foreign", "other")], 1, null, "other")); await env.flush();
  assert.match(env.html(), /与当前本人身份不一致/); assert.doesNotMatch(env.html(), /foreign|当前没有需要本人具名决定/); assert.equal(env.queue().totalPending, null);
  await env.refresh(); env.calls[1].reject(new Error("合成暂不可读")); await env.flush(); assert.match(env.html(), /合成暂不可读/); assert.equal(env.queue().totalPending, null);
  await env.refresh(); env.calls[2].resolve(page([], 0)); await env.flush(); assert.match(env.html(), /当前没有需要本人具名决定/); assert.equal(env.queue().totalPending, 0);
});
