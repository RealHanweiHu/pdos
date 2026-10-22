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
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Local dispatcher executes actual promise-record reads and state handlers. */
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
const { useMyWorkPromises, MyWorkPromises } = load(path.join(directory, "my-work-promises.tsx"));
const { isPersonalTestStartPromisePage, originalTestStartTime, testStartWorkbenchHref } = load(path.join(webRoot, "src/lib/personal-test-start-promises.ts"));
const tick = () => new Promise(resolve => setImmediate(resolve));
const html = tree => renderToStaticMarkup(tree);
function record(id = "one", timing = "awaiting_start") {
  const promise = { occurred_at: "2026-10-17T01:25:03.160086+00:00", original_timezone: "Asia/Shanghai", effective_at: null };
  return { id, recorded_at: "2026-10-17T00:00:00Z", category: { id: "category", name: "合成品类" }, product: { id: "product", name: "合成型号" }, project: { id: "project", name: "合成项目" }, build: { id: `build-${id}`, name: `合成Build ${id}` }, request: { id: `request-${id}` }, run: { id: `run-${id}`, revision: 3, status: "planned" }, promise, actual_start: timing.startsWith("started_") ? { ...promise, occurred_at: "2026-10-17T01:30:03.000001Z", received_at: "2026-10-17T01:31:00Z" } : null, recipient: null, recipient_status: "not_recorded", timing, coverage: { sample_count: 2, item_count: 3, pair_count: 6 } };
}
function page(items = [record()], total = items.length, cursor = null, principalId = "me") { return { version: "personal-test-start-promises/v1", principal_id: principalId, as_of: "2026-10-17T20:00:00Z", total_records: total, items, next_cursor: cursor }; }
/* eslint-disable react-hooks/rules-of-hooks -- Test-only dispatcher executes the actual isolated hook. */
function environment(t) {
  const calls = [], api = (url, body) => new Promise((resolve, reject) => calls.push({ url, body, resolve, reject }));
  let props = { api, principalId: "me", reload: 0 }, queue, tree;
  const state = { slots: [], index: 0, effects: [], dirty: true, disposed: false };
  function render() { state.index = 0; state.effects = []; state.dirty = false; hooks = state; try { queue = useMyWorkPromises(props.api, props.principalId, props.reload); tree = MyWorkPromises({ queue }); } finally { hooks = null; } state.effects.forEach(effect => effect()); }
  function unmount() { state.slots.forEach(slot => slot?.cleanup?.()); state.disposed = true; }
  render(); t.after(unmount);
  return { calls, queue: () => queue, tree: () => tree, html: () => html(tree), setProps(next) { props = { ...props, ...next }; render(); }, async flush() { for (let i = 0; i < 6; i++) { await tick(); if (state.dirty) render(); } return tree; }, async more() { void queue.loadMore(); return this.flush(); }, async refresh() { queue.refresh(); return this.flush(); } };
}
/* eslint-enable react-hooks/rules-of-hooks */

test("contract requires actor scope, valid original timezone, fixed scope and explicit missing recipient", () => {
  assert.ok(isPersonalTestStartPromisePage(page(), "me")); assert.equal(isPersonalTestStartPromisePage(page(), "other"), false);
  for (const mutate of [value => { value.items[0].promise.original_timezone = "invented/zone"; }, value => { value.items[0].promise.occurred_at = "2026-10-17T09:00:00"; }, value => { value.items[0].recipient = { id: "request-owner" }; }, value => { value.items[0].recipient_status = "accepted"; }, value => { value.items[0].coverage.pair_count = null; }, value => { value.items[0].run.status = "cancelled"; }, value => { value.items[0].timing = "guessed_late"; }]) { const value = page(); mutate(value); assert.equal(isPersonalTestStartPromisePage(value, "me"), false); }
});

test("original timezone presentation retains six-digit fact precision and crossing a UTC day boundary", () => {
  assert.equal(originalTestStartTime(record().promise), "2026-10-17 09:25:03.160086 Asia/Shanghai");
  assert.equal(originalTestStartTime({ occurred_at: "2026-10-17T20:00:00.000001Z", original_timezone: "Asia/Shanghai", effective_at: null }), "2026-10-18 04:00:00.000001 Asia/Shanghai");
  assert.equal(originalTestStartTime({ occurred_at: "2026-10-17T09:25:03.160086+08:00", original_timezone: "UTC", effective_at: null }), "2026-10-17 01:25:03.160086 UTC");
});

test("workbench link preserves category/product/project while leaving Build/request/Run selection to the existing page", () => {
  const item = record(), link = testStartWorkbenchHref(item), query = new URL(link, "https://example.test").searchParams;
  assert.ok(link.startsWith("/?")); assert.equal(query.get("area"), "category"); assert.equal(query.get("bench"), "projects"); assert.equal(query.get("view"), "verification"); assert.equal(query.get("task"), "launch");
  for (const key of ["category", "product", "project"]) assert.equal(query.get(key), item[key].id);
  for (const key of ["build", "request", "run"]) assert.equal(query.has(key), false);
  const stack = [MyWorkPromises({ queue: { items: [item], totalRecords: 1, nextCursor: null, asOf: null, loadingMore: false, error: "" } })];
  let entry;
  while (stack.length) {
    const node = stack.pop();
    if (!React.isValidElement(node)) continue;
    if (node.props.href === link) entry = node;
    stack.push(...React.Children.toArray(node.props.children));
  }
  assert.equal(entry?.type, "a", "workbench entry must use native document navigation so AppShell reloads its location");
});

test("cards display server timing without guessing from the browser clock or substituting a request owner as recipient", async t => {
  const env = environment(t), awaiting = record("waiting"), expired = record("past", "past_due_no_start_record");
  awaiting.promise.occurred_at = "2000-01-01T00:00:00Z"; awaiting.request.owner_name = "错误接收人"; expired.promise.occurred_at = "2050-01-01T00:00:00Z";
  env.calls[0].resolve(page([awaiting, expired, record("on-time", "started_on_or_before"), record("late", "started_late")])); await env.flush(); const rendered = env.html();
  for (const text of ["我作出的开测承诺记录（已接测试）", "尚未登记实际开测", "承诺时点已过，未登记开测", "实际开测未晚于承诺", "实际开测晚于承诺", "接收方尚未记录", "Asia/Shanghai", "样件 2", "测试项 3", "配对 6", "进入后仍需选择上述 Build、请求与 Run"]) assert.ok(rendered.includes(text), text);
  assert.doesNotMatch(rendered, /错误接收人|未读|自动定位|剩余|逾期天数|接收成功|<form/); assert.ok(env.calls.every(call => call.body === undefined));
});

test("server totals and explicit pagination remain separate from loaded record count, with duplicate record IDs merged", async t => {
  const env = environment(t); assert.equal(env.queue().totalRecords, null); assert.doesNotMatch(env.html(), /全部 <b>0/);
  env.calls[0].resolve(page([record("one")], 2, "cursor/one")); await env.flush(); assert.match(env.html(), /已加载 <b>1<\/b> \/ 全部 <b>2<\/b>/);
  void env.queue().loadMore(); void env.queue().loadMore(); await env.flush(); assert.equal(env.calls.length, 2); assert.equal(env.calls[1].url, "v1/personal/test-start-promises?page_size=20&cursor=cursor%2Fone");
  env.calls[1].resolve(page([{ ...record("one"), timing: "past_due_no_start_record" }, record("two")], 2)); await env.flush(); assert.equal(env.queue().items.length, 2); assert.equal(env.queue().items[0].timing, "past_due_no_start_record"); assert.doesNotMatch(env.html(), /加载更多开测承诺记录/);
  assert.ok(env.calls.every(call => call.body === undefined));
});

test("repeated cursors and changing totals hide stale record coverage and recover through a fresh first page", async t => {
  const env = environment(t); env.calls[0].resolve(page([record("one")], 2, "cursor-one")); await env.flush(); await env.more();
  env.calls[1].resolve(page([record("two")], 2, "cursor-one")); await env.flush(); assert.match(env.html(), /分页位置未推进/); assert.equal(env.queue().totalRecords, null); assert.doesNotMatch(env.html(), /合成Build one/);
  await env.refresh(); assert.equal(env.calls[2].url, "v1/personal/test-start-promises?page_size=20"); env.calls[2].resolve(page([record("one")], 2, "cursor-one")); await env.flush(); await env.more();
  env.calls[3].resolve(page([record("two")], 3, "cursor-two")); await env.flush(); assert.match(env.html(), /开测承诺记录已有变化/); assert.equal(env.queue().totalRecords, null);
  await env.refresh(); env.calls[4].resolve(page([record("fresh")])); await env.flush(); assert.match(env.html(), /合成Build fresh/);
});

test("principal and parent refresh changes immediately hide old scope and ignore late page results", async t => {
  const env = environment(t); env.calls[0].resolve(page([record("one")], 2, "cursor-one")); await env.flush(); await env.more();
  env.setProps({ reload: 1 }); assert.match(env.html(), /正在读取/); assert.doesNotMatch(env.html(), /合成Build one/);
  env.calls[1].resolve(page([record("two")], 2)); await env.flush(); assert.doesNotMatch(env.html(), /合成Build two/);
  env.calls[2].resolve(page([record("fresh")])); await env.flush(); assert.match(env.html(), /合成Build fresh/);
  env.setProps({ principalId: "other" }); assert.match(env.html(), /正在读取/); assert.doesNotMatch(env.html(), /合成Build fresh/);
  env.calls[3].resolve(page([record("other-principal")], 1, null, "other")); await env.flush(); assert.match(env.html(), /other-principal/);
});

test("failed or wrong-principal reads remain unknown and an actual empty result states only the current record scope", async t => {
  const env = environment(t); env.calls[0].reject(new Error("合成记录暂不可读")); await env.flush(); assert.match(env.html(), /合成记录暂不可读/); assert.equal(env.queue().totalRecords, null); assert.doesNotMatch(env.html(), /没有本人作出/);
  await env.refresh(); env.calls[1].resolve(page([record("foreign")], 1, null, "other")); await env.flush(); assert.match(env.html(), /当前本人身份不一致/); assert.doesNotMatch(env.html(), /合成Build foreign/);
  await env.refresh(); env.calls[2].resolve(page([], 0)); await env.flush(); assert.match(env.html(), /当前可读范围内没有本人作出的测试开测承诺记录/); assert.equal(env.queue().totalRecords, 0); assert.match(env.html(), /外部等待与其他通用承诺仍未接入/);
});
