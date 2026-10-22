import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Isolated state driver; the read library has its own actual DTO/transport tests. */
const react = { ...React, useState(initial) {
  if (!hooks) return React.useState(initial);
  const own = hooks, index = own.index++;
  if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial;
  return [own.slots[index], next => { if (!own.disposed) { own.slots[index] = typeof next === "function" ? next(own.slots[index]) : next; own.dirty = true; } }];
}, useCallback(callback, deps) {
  if (!hooks) return React.useCallback(callback, deps);
  const index = hooks.index++; if (!same(hooks.slots[index]?.deps, deps)) hooks.slots[index] = { deps, callback }; return hooks.slots[index].callback;
}, useEffect(effect, deps) {
  if (!hooks) return React.useEffect(effect, deps);
  const own = hooks, index = own.index++;
  if (!same(own.slots[index]?.deps, deps)) { const prior = own.slots[index], next = { deps, cleanup: prior?.cleanup }; own.slots[index] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); }
} };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { ProjectCommitments, currentProjectCommitments, pairProjectCommitments } = load(path.join(directory, "project-commitments.tsx"));
const publicFixture = JSON.parse(readFileSync(path.resolve(webRoot, "../../docs/reports/evidence/pdos-next-s5-20261018/project-work/browser-final-api.json"), "utf8"));
const scope = { categoryId: "4005cc53-21fc-4e3b-bb4a-4f9b7179a121", productId: "5c5b1613-08a1-4ca4-8d47-548f29ea13b1", projectId: publicFixture.project.id, principalId: publicFixture.project.owner_id };
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
// Each mutation below is an explicitly synthetic state case; the source evidence remains unchanged.
const sample = () => structuredClone(publicFixture);
function elements(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate)); return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function fulfillmentSample(view = sample()) {
  return { project: structuredClone(view.project), product_revision: view.product_revision, as_of: "2026-10-18T03:00:00.999999+00:00",
    commitments: view.commitments.map((commitment, index) => {
      const task = view.tasks.find(row => row.id === commitment.task_id) ?? publicFixture.tasks[0];
      return { ...structuredClone(commitment), series_id: id(100 + index), sources: structuredClone(task.sources),
        task: Object.fromEntries(["id", "version_id", "revision", "title", "state"].map(key => [key, task[key]])), submission: null,
        fulfillment: { state: "open", revision: 0, review: null, history: [] }, can_review: false };
    }) };
}
function review(row, revision = 1, decision = "accepted") {
  return { id: id(300 + revision), revision, decision, state: decision === "accepted" ? "fulfilled" : "open", checks: row.outcome_keys.map((key, index) => ({ key, decision: decision === "accepted" || index ? "accepted" : "rejected", reason: `实际核对理由 ${revision} ${key}` })), actor_id: row.recipient_id, recorded_at: `2026-10-18T03:00:0${revision}.123456+00:00`, receipt_id: id(400 + revision) };
}
function setReviews(row, history) { const current = history.at(-1); row.fulfillment = { state: current.state, revision: current.revision, review: current, history }; }
const isFulfillment = route => route.includes("/project-work/fulfillment?");
function environment(t) {
  const calls = [], makeApi = () => (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false }));
  let props = { ...scope, readVersion: 0, api: makeApi() }, instance, tree;
  const dispose = value => { if (value) { value.slots.forEach(slot => slot?.cleanup?.()); value.disposed = true; } };
  function render() {
    const wrapper = ProjectCommitments(props);
    if (!instance || instance.key !== wrapper.key) { dispose(instance); instance = { key: wrapper.key, slots: [], index: 0, effects: [], dirty: true, disposed: false }; }
    instance.index = 0; instance.effects = []; instance.dirty = false; hooks = instance;
    try { tree = wrapper.type(wrapper.props); } finally { hooks = null; }
    instance.effects.forEach(effect => effect());
  }
  render(); t.after(() => dispose(instance));
  return { calls, render, tree: () => tree, html: () => renderToStaticMarkup(tree), props: () => props, setProps(next) { props = { ...props, ...next }; render(); }, replaceApi() { props = { ...props, api: makeApi() }; render(); },
    pending(kind = "work") { return calls.findLast(call => !call.done && isFulfillment(call.route) === (kind === "fulfillment")); },
    respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, value) { assert.ok(call); call.done = true; call.reject(value); },
    async flush() { for (let i = 0; i < 5; i++) { await tick(); if (instance.dirty) render(); } } };
}
function button(env, label) { return elements(env.tree(), node => node.props?.children === label && typeof node.props.onClick === "function")[0]; }
async function click(env, label) { const found = button(env, label); assert.ok(found, label); found.props.onClick(); env.render(); await env.flush(); }
async function ready(env, value = sample(), fulfillment) { value.project.id = env.props().projectId; env.respond(env.pending(), value); env.respond(env.pending("fulfillment"), fulfillment ?? fulfillmentSample(value)); await env.flush(); }
const rowCount = env => (env.html().match(/aria-label="承诺记录 /g) ?? []).length;

test("two actual readers publish only a matched pair; legacy Work DTO still preserves fixed v3, current v8 and original dates", async t => {
  const env = environment(t); assert.match(env.html(), /正在读取本项目承诺记录/); assert.equal(env.calls.length, 2);
  assert.equal(env.calls[0].route, `v1/categories/${scope.categoryId}/products/${scope.productId}/project-work?project_id=${scope.projectId}`);
  assert.equal(env.calls[1].route, `v1/categories/${scope.categoryId}/products/${scope.productId}/project-work/fulfillment?project_id=${scope.projectId}`);
  const value = sample(); env.respond(env.pending(), value); await env.flush(); assert.equal(rowCount(env), 0); assert.match(env.html(), /正在读取本项目承诺记录/);
  env.respond(env.pending("fulfillment"), fulfillmentSample(value)); await env.flush(); assert.equal(currentProjectCommitments(publicFixture).length, 4); assert.equal(rowCount(env), 3);
  await click(env, "展开其余 1 条当前记录"); assert.equal(rowCount(env), 4); const html = env.html();
  assert.match(html, /固定任务 v3 · 当前任务 v8/); assert.match(html, /v8 · 已完成/); assert.match(html, /尚未具名核对/);
  assert.match(html, /已读取当前版本人工任务承诺 4 条/); assert.doesNotMatch(html, /已具名核对履行|未结承诺|已逾期|承诺已完成/);
  for (const row of publicFixture.commitments) { assert.ok(html.includes(row.id)); assert.ok(html.includes(row.recorded_at)); assert.ok(html.includes(row.created_at)); assert.ok(html.includes(row.original_timezone)); }
  assert.match(html, /2026-10-19T00:42:47.888505Z/); assert.match(html, /日期未知/); assert.match(html, /以下仅为当前任务上下文，不是承诺时的固定成果正文/);
  assert.ok(env.calls.every(call => call.body === undefined));
});

test("superseded versions stay excluded and completed tasks retain separate current promises to each recipient", async t => {
  const env = environment(t), value = sample(), historical = { ...publicFixture.commitments[0], id: id(50), status: "superseded" };
  value.commitments.push(historical); value.commitments[0].replaces = { id: historical.id, revision: 1 };
  await ready(env, value); await click(env, "展开其余 1 条当前记录"); assert.equal(rowCount(env), 4);
  assert.ok(!env.html().includes(`aria-label="承诺记录 ${historical.id}"`)); assert.ok(env.html().includes(`${historical.id} · v1`));
  assert.notEqual(value.commitments[0].recipient_id, value.commitments[1].recipient_id);
  for (const row of value.commitments.slice(0, 2)) assert.ok(env.html().includes(`aria-label="承诺记录 ${row.id}"`));
});

test("read-only or missing member names do not filter the promise or fabricate review actors", async t => {
  const env = environment(t), value = sample(); value.members.forEach(member => { member.can_write = false; }); const projection = fulfillmentSample(value); setReviews(projection.commitments[0], [review(projection.commitments[0])]);
  await ready(env, value, projection); for (const member of value.members) assert.ok(env.html().includes(member.name)); assert.match(env.html(), /已具名核对履行/);
  await click(env, "刷新承诺"); value.members = []; await ready(env, value, projection);
  assert.match(env.html(), /姓名暂不可读/); assert.ok(env.html().includes(value.commitments[0].promisor_id)); assert.ok(env.html().includes(value.commitments[0].recipient_id)); assert.equal(rowCount(env), 3);
});

test("missing fixed task revision or recorded_at on either reader is incomplete instead of using current task or created_at", async t => {
  for (const side of ["work", "projection"]) for (const field of ["task_revision", "recorded_at"]) {
    const env = environment(t), value = sample(), projection = fulfillmentSample(value); delete (side === "work" ? value.commitments : projection.commitments)[0][field]; await ready(env, value, projection);
    assert.match(env.html(), /未完整取得/); assert.equal(rowCount(env), 0); assert.doesNotMatch(env.html(), /尚无当前版本人工任务承诺|已读取当前版本人工任务承诺 0 条/);
  }
});

test("genuine paired empty state differs from failed or missing projection, and unknown date does not imply overdue", async t => {
  const env = environment(t), empty = sample(); empty.commitments.forEach(item => { item.status = "superseded"; }); await ready(env, empty);
  assert.match(env.html(), /尚无当前版本人工任务承诺/); assert.match(env.html(), /已读取当前版本人工任务承诺 0 条/);
  await click(env, "刷新承诺"); const unknown = sample(); unknown.commitments = [unknown.commitments[0]]; await ready(env, unknown);
  assert.match(env.html(), /日期未知/); assert.equal(rowCount(env), 1); assert.doesNotMatch(env.html(), /逾期|截止已过|未履行/);
  await click(env, "刷新承诺"); const missing = fulfillmentSample(unknown); missing.commitments = []; await ready(env, unknown, missing);
  assert.equal(rowCount(env), 0); assert.match(env.html(), /请重新读取/); assert.doesNotMatch(env.html(), /尚无当前版本人工任务承诺|尚未具名核对/);
});

test("403 or 503 from either read hides previous private details and never replaces the failure with open or zero", async t => {
  const env = environment(t); await ready(env);
  for (const [kind, status] of [["fulfillment", 403], ["work", 503]]) {
    await click(env, "刷新承诺"); assert.equal(rowCount(env), 0);
    const rejected = env.pending(kind), other = env.pending(kind === "work" ? "fulfillment" : "work");
    env.reject(rejected, Object.assign(Error(`本次${status}读取失败`), { status })); await env.flush();
    env.respond(other, kind === "work" ? fulfillmentSample() : sample()); await env.flush();
    assert.match(env.html(), new RegExp(`本次${status}读取失败`)); assert.equal(rowCount(env), 0); assert.doesNotMatch(env.html(), /尚无当前版本人工任务承诺|尚未具名核对/);
    await click(env, "重新读取承诺"); await ready(env); assert.equal(rowCount(env), 3);
  }
});

test("identity/category/product/project/readVersion changes hide both previous readers synchronously", async t => {
  const env = environment(t); await ready(env);
  for (const update of [{ principalId: id(60) }, { categoryId: id(61) }, { productId: id(62) }, { projectId: id(63) }, { readVersion: 1 }]) {
    env.setProps(update); assert.equal(rowCount(env), 0); assert.match(env.html(), /正在读取本项目承诺记录/); await ready(env); assert.equal(rowCount(env), 3);
  }
});

test("API replacement blocks old paired successes and old failures after a new pair is current", async t => {
  const env = environment(t), oldWork = env.pending(), oldProjection = env.pending("fulfillment");
  env.replaceApi(); assert.equal(rowCount(env), 0); await ready(env); assert.equal(rowCount(env), 3);
  const old = sample(); old.tasks[0].title = "迟到旧身份的私有任务"; env.respond(oldWork, old); env.respond(oldProjection, fulfillmentSample(old)); await env.flush(); assert.doesNotMatch(env.html(), /迟到旧身份/);
  env.replaceApi(); assert.equal(rowCount(env), 0); await ready(env);
  await click(env, "刷新承诺"); const staleWork = env.pending(), staleProjection = env.pending("fulfillment"); env.replaceApi(); await ready(env);
  env.reject(staleProjection, Object.assign(Error("旧读取的迟到403"), { status: 403 })); env.respond(staleWork, sample()); await env.flush(); assert.equal(rowCount(env), 3); assert.doesNotMatch(env.html(), /旧读取的迟到403/);
});

test("refresh generations never cross-pair an old fulfillment response with a new Work view", async t => {
  const env = environment(t), oldWork = env.pending(), oldProjection = env.pending("fulfillment"); await click(env, "刷新承诺");
  env.respond(env.pending(), sample()); env.respond(oldProjection, fulfillmentSample()); await env.flush(); assert.equal(rowCount(env), 0);
  env.respond(env.pending("fulfillment"), fulfillmentSample()); await env.flush(); assert.equal(rowCount(env), 3);
  env.reject(oldWork, Error("旧任务读取迟到失败")); await env.flush(); assert.equal(rowCount(env), 3); assert.doesNotMatch(env.html(), /旧任务读取迟到失败/);
});

test("fulfilled, returned-open and unreviewed-open remain distinct explicit states", async t => {
  const env = environment(t), value = sample(); value.commitments = value.commitments.slice(0, 3); const projection = fulfillmentSample(value);
  setReviews(projection.commitments[0], [review(projection.commitments[0])]); setReviews(projection.commitments[1], [review(projection.commitments[1], 1, "returned")]);
  await ready(env, value, projection); const html = env.html(); assert.equal(rowCount(env), 3);
  assert.match(html, /已具名核对履行/); assert.match(html, /已退回 · 履行保持开放/); assert.match(html, /尚未具名核对/); assert.match(html, /当前没有具名履行结论，不代表承诺事实未完成/);
  assert.ok(html.includes(projection.commitments[0].fulfillment.review.recorded_at)); assert.ok(html.includes(projection.commitments[1].fulfillment.review.receipt_id));
});

test("contradictory decision and state in a current or historical review cannot publish fulfillment", async t => {
  for (const [decision, state, historical] of [["returned", "fulfilled", false], ["accepted", "open", false], ["returned", "fulfilled", true]]) {
    const env = environment(t), value = sample(), projection = fulfillmentSample(value), row = projection.commitments[0];
    const inconsistent = { ...review(row, 1, decision), state };
    setReviews(row, historical ? [inconsistent, review(row, 2)] : [inconsistent]);
    await ready(env, value, projection);
    assert.equal(rowCount(env), 0); assert.match(env.html(), /请重新读取/); assert.doesNotMatch(env.html(), /已具名核对履行|已退回 · 履行保持开放|尚未具名核对/);
  }
});

test("fulfilled superseded promise never gives fulfillment to a new open version of the same task and series", async t => {
  const env = environment(t), value = sample(); value.commitments = [value.commitments[0]];
  const old = { ...structuredClone(value.commitments[0]), status: "superseded" }, current = { ...structuredClone(old), id: id(80), revision: 2, status: "current", replaces: { id: old.id, revision: old.revision } }; value.commitments = [old, current];
  const projection = fulfillmentSample(value); projection.commitments[1].series_id = projection.commitments[0].series_id; setReviews(projection.commitments[0], [review(projection.commitments[0])]);
  await ready(env, value, projection); assert.equal(rowCount(env), 1); assert.match(env.html(), /尚未具名核对/); assert.doesNotMatch(env.html(), /已具名核对履行|履行核对记录/); assert.ok(env.html().includes(`aria-label="承诺记录 ${current.id}"`));
});

test("project/product revisions, immutable commitment scope and one-to-one current set must all match", async t => {
  const changes = [p => p.project.revision++, p => p.product_revision++, p => p.commitments[0].revision++, p => p.commitments[0].id = id(91), p => p.commitments[0].task_id = id(92), p => p.commitments[0].promisor_id = id(93), p => p.commitments[0].recipient_id = id(94), p => p.commitments[0].outcome_keys = ["other"], p => p.commitments[0].promised_at = "2026-10-25T01:02:03.123456+08:00", p => p.commitments[0].original_timezone = "UTC", p => p.commitments[0].calendar_id = id(95), p => p.commitments[0].task_revision++, p => p.commitments[0].recorded_at = "2026-10-19T00:00:00Z", p => p.commitments[0].created_at = "2026-10-19T00:00:00Z", p => p.commitments[0].status = "superseded"];
  for (const change of changes) { const env = environment(t), value = sample(), projection = fulfillmentSample(value); change(projection); await ready(env, value, projection); assert.equal(rowCount(env), 0); assert.match(env.html(), /未能配对|未完整取得/); assert.doesNotMatch(env.html(), /尚未具名核对|已具名核对履行/); }
});

test("current task identity/version/revision/state mismatches or missing current task reject the paired projection", async t => {
  for (const change of [p => p.commitments[0].task.id = id(96), p => p.commitments[0].task.version_id = id(97), p => p.commitments[0].task.revision++, p => p.commitments[0].task.state = "submitted", p => p.commitments[0].task.title = "Changed current title"]) {
    const env = environment(t), value = sample(), projection = fulfillmentSample(value); change(projection); await ready(env, value, projection); assert.equal(rowCount(env), 0); assert.match(env.html(), /未能配对|未完整取得/);
  }
  const env = environment(t), value = sample(), projection = fulfillmentSample(value); value.tasks = []; await ready(env, value, projection); assert.equal(rowCount(env), 0); assert.match(env.html(), /未能配对/);
});

test("review history retains only actual reviewer/time/receipt/checks and never borrows current material as historical fixed references", async t => {
  const env = environment(t), value = sample(); value.commitments = [value.commitments[0]]; const projection = fulfillmentSample(value), row = projection.commitments[0];
  const returned = review(row, 1, "returned"), accepted = review(row, 2, "accepted"); setReviews(row, [returned, accepted]);
  row.submission = { id: id(98), revision: 7, actor_id: row.promisor_id, results: [{ key: "drawing", text: "CURRENT_SUBMISSION_NOT_A_HISTORICAL_FACT", status: "missing", sources: [] }], time: { actual_at: "2026-10-18T01:00:00.999999Z", original_timezone: "Asia/Shanghai", calendar_id: null, actor_id: row.promisor_id, recorded_at: "2026-10-18T01:00:00.999999Z" } };
  await ready(env, value, projection); const html = env.html(); assert.match(html, /核对 v1 · 退回 · 历史核对/); assert.match(html, /核对 v2 · 接收履行 · 当前核对/);
  for (const record of [returned, accepted]) { assert.ok(html.includes(record.id)); assert.ok(html.includes(record.recorded_at)); assert.ok(html.includes(record.receipt_id)); for (const check of record.checks) assert.ok(html.includes(check.reason)); }
  assert.match(html, /未提供每次核对固定的任务、提交和承诺引用/); assert.doesNotMatch(html, /CURRENT_SUBMISSION_NOT_A_HISTORICAL_FACT|实际完成时间/);
});

test("a named fulfillment decision never supplies an unknown promise date or rewrites the raw promise clocks", async t => {
  const env = environment(t), value = sample(); value.commitments = value.commitments.slice(0, 2); const projection = fulfillmentSample(value);
  setReviews(projection.commitments[0], [review(projection.commitments[0])]); const original = structuredClone(value.commitments); await ready(env, value, projection);
  assert.match(env.html(), /日期未知/); assert.match(env.html(), /2026-10-19T00:42:47.888505Z/); assert.deepEqual(value.commitments, original);
  assert.equal(pairProjectCommitments(value, projection)[0].commitment.promised_at, null); assert.equal(pairProjectCommitments(value, projection)[1].commitment.promised_at, original[1].promised_at);
});

test("can_review is never a read filter or a write action, and missing actor names keep the exact actor identity", async t => {
  const env = environment(t), value = sample(); value.members = []; const projection = fulfillmentSample(value); projection.commitments.forEach(row => { row.can_review = false; }); setReviews(projection.commitments[0], [review(projection.commitments[0])]);
  await ready(env, value, projection); assert.equal(rowCount(env), 3); assert.match(env.html(), /核对人：姓名暂不可读/); assert.ok(env.html().includes(projection.commitments[0].fulfillment.review.actor_id));
  assert.ok(env.calls.every(call => call.body === undefined)); assert.doesNotMatch(env.html(), /本人确认|保存并|具名接收按钮/);
});
