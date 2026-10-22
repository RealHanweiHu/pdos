import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Isolated component state harness. */
const reactShim = { ...React, useState(initial) {
  if (!hooks) return React.useState(initial);
  const own = hooks, index = own.index++;
  if (!(index in own.values)) own.values[index] = typeof initial === "function" ? initial() : initial;
  return [own.values[index], next => { own.values[index] = typeof next === "function" ? next(own.values[index]) : next; }];
}, useRef(initial) { if (!hooks) return React.useRef(initial); const index = hooks.index++; return hooks.values[index] ??= { current: initial }; }, useCallback(callback, dependencies) {
  if (!hooks) return React.useCallback(callback, dependencies);
  const index = hooks.index++;
  if (!same(hooks.values[index]?.dependencies, dependencies)) hooks.values[index] = { callback, dependencies };
  return hooks.values[index].callback;
}, useEffect(callback, dependencies) {
  if (!hooks) return React.useEffect(callback, dependencies);
  const own = hooks, index = own.index++;
  if (!same(own.values[index]?.dependencies, dependencies)) { const previous = own.values[index]; const entry = { dependencies, cleanup: previous?.cleanup }; own.values[index] = entry; own.effects.push(() => { entry.cleanup?.(); entry.cleanup = callback(); }); }
} };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const cache = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? reactShim
    : specifier === "next/link" ? props => React.createElement("a", { href: props.href }, props.children)
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { MyWork, taskPeriod } = load(path.join(directory, "my-work.tsx"));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
const markup = tree => renderToStaticMarkup(tree);
const tick = () => new Promise(resolve => setImmediate(resolve));
function driver(props) {
  const state = { index: 0, values: [], effects: [] };
  return { render() { hooks = state; state.index = 0; state.effects = []; try { return MyWork(props); } finally { hooks = null; } }, mount() { state.effects.forEach(effect => effect()); }, setProps(next) { props = { ...props, ...next }; } };
}
const today = new Date(), localDay = date => `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(date.getDate()).padStart(2, "0")}`;
const day = offset => { const date = new Date(today); date.setDate(date.getDate() + offset); return localDay(date); };
const task = (id, due_date, owner_id = "me", status = "open") => ({ id, kind: "task", title: `任务${id}`, owner_id, due_date, status });
const entry = { category: { id: "cat", name: "合成品类" }, product: { id: "product", name: "合成型号" }, project: { id: "project", name: "合成项目" }, openItems: [task("今日", day(0)), task("逾期", day(-1)), task("稍后", day(9)), task("未定", null), task("他人", day(0), "other"), task("已完", day(0), "me", "done"), { ...task("风险", day(2)), kind: "risk", title: "合成风险" }], openItemsError: "" };
const waiting = { run_id: "waiting", goal: "需要答复的合成工作", status: "waiting_input", categoryId: "cat", categoryName: "合成品类", scope: "category", product_id: null, created_at: "2026-10-17T08:00:00Z" };
const completed = { ...waiting, run_id: "complete", goal: "已完成的合成工作", status: "completed" };
const g0Item = { proposal_id: "proposal", title: "合成G0提案", proposal_revision: 3, status: "in_review", category: { id: "cat", name: "合成品类" }, owner: { id: "owner", name: "合成负责人" }, reviewer_id: "me", submission: { id: "submission", revision: 2, submitted_at: "2026-10-17T09:00:00Z", document_digest: "fixed-digest" } };
const promiseItem = { id: "promise-record", recorded_at: "2026-10-17T09:00:00Z", category: { id: "cat", name: "合成品类" }, product: { id: "product", name: "合成型号" }, project: { id: "project", name: "合成项目" }, build: { id: "build", name: "合成承诺Build" }, request: { id: "request" }, run: { id: "test-run", revision: 2, status: "planned" }, promise: { occurred_at: "2026-10-17T00:00:00.160086Z", original_timezone: "Asia/Shanghai", effective_at: null }, actual_start: null, recipient: null, recipient_status: "not_recorded", timing: "awaiting_start", coverage: { sample_count: 2, item_count: 3, pair_count: 6 } };
function apiFixture({ fail = () => false, unavailable = 0, g0Fail = () => false, g0Items = [], promisesFail = () => false, promiseItems = [] } = {}) {
  const calls = [];
  return { calls, api: async (url, body) => { calls.push({ url, body }); if (fail()) throw new Error("合成读取失败"); if (url.startsWith("v1/personal/g0-reviews")) { if (g0Fail()) throw new Error("合成G0读取失败"); return { version: "personal-g0-reviews/v1", principal_id: "me", as_of: "2026-10-17T09:00:00Z", total_pending: g0Items.length, items: g0Items, next_cursor: null }; } if (url.startsWith("v1/personal/test-start-promises")) { if (promisesFail()) throw new Error("合成开测承诺读取失败"); return { version: "personal-test-start-promises/v1", principal_id: "me", as_of: "2026-10-17T09:00:00Z", total_records: promiseItems.length, items: promiseItems, next_cursor: null }; } return url.startsWith("v1/personal/projects") ? { items: [entry], next_cursor: null, unavailable_count: unavailable, as_of: "2026-10-17T09:00:00Z" } : { items: url.includes("waiting=true") ? [waiting] : [waiting, completed], next_cursor: null }; } };
}
const defaultProps = api => ({ api, session: { name: "合成人员", principal_id: "me" }, onOpenRun() {}, onOpenProject() {}, onOpenPai() {} });
const section = (tree, label) => elements(tree, element => element.props?.["aria-label"] === label)[0];

test("task periods keep overdue visible, use calendar weeks, and never invent a due date", () => {
  for (const date of ["2026-10-16", "2026-10-17"]) assert.equal(taskPeriod(date, "2026-10-17"), "today");
  assert.equal(taskPeriod("2026-10-18", "2026-10-17"), "week");
  assert.equal(taskPeriod("2026-10-19", "2026-10-17"), "later");
  assert.equal(taskPeriod("2026-10-19", "2026-10-18"), "later");
  assert.equal(taskPeriod("2026-10-25", "2026-10-19"), "week");
  assert.equal(taskPeriod(null, "2026-10-17"), "later");
});

test("paused runs retain their own navigation and task clicks retain exact scope", async () => {
  const fixture = apiFixture(), opened = [];
  const component = driver({ ...defaultProps(fixture.api), onOpenProject: (...args) => opened.push(args) });
  component.render(); component.mount(); await tick(); const tree = component.render(), html = markup(tree);
  assert.match(html, /合成风险/); assert.match(html, /任务今日/); assert.doesNotMatch(html, /任务他人|任务已完/);
  assert.match(markup(section(tree, "运行与项目风险")), /需要答复的合成工作/);
  assert.doesNotMatch(markup(section(tree, "通知与运行动态")), /需要答复的合成工作/);
  assert.doesNotMatch(markup(section(tree, "办理类型")), /要我决定|要我接收/);
  assert.equal(elements(tree, element => element.type === "input" && element.props.type === "checkbox").length, 0);
  elements(tree, element => element.type === "button" && element.props.children === "任务今日")[0].props.onClick();
  assert.deepEqual(opened, [["cat", "project"]]);
  assert.equal(fixture.calls.length, 6); assert.ok(fixture.calls.every(call => call.body === undefined));
});

test("period filtering and collapsing only change the local view of authorized tasks", async () => {
  const fixture = apiFixture(), component = driver(defaultProps(fixture.api));
  component.render(); component.mount(); await tick(); let tree = component.render();
  elements(section(tree, "任务期限筛选"), element => element.type === "button" && element.props.children === "稍后")[0].props.onClick();
  tree = component.render(); const tasks = section(tree, "我的任务");
  assert.match(markup(tasks), /任务稍后/); assert.match(markup(tasks), /任务未定/); assert.doesNotMatch(markup(tasks), /任务今日|任务逾期/);
  const group = elements(tasks, element => element.props?.["aria-controls"] === "my-work-tasks-later")[0];
  group.props.onClick(); tree = component.render();
  assert.equal(elements(tree, element => element.props?.id === "my-work-tasks-later")[0].props.hidden, true);
  assert.equal(fixture.calls.length, 6); assert.ok(fixture.calls.every(call => call.body === undefined));
});

test("answer and risk filters preserve run and project navigation without classifying runs as decisions", async () => {
  const fixture = apiFixture(), opened = [], component = driver({ ...defaultProps(fixture.api), onOpenRun: (...args) => opened.push(args) });
  component.render(); component.mount(); await tick(); let tree = component.render();
  elements(section(tree, "办理类型"), element => element.type === "button" && markup(element).includes("暂停的运行"))[0].props.onClick();
  tree = component.render(); const triage = section(tree, "运行与项目风险");
  assert.doesNotMatch(markup(triage), /合成风险/);
  elements(triage, element => element.props?.children?.some?.(child => child === "查看运行"))[0].props.onClick();
  assert.deepEqual(opened, [["waiting", "cat"]]); assert.ok(fixture.calls.every(call => call.body === undefined));
});

test("recent project history is per person and filtered against the current authorized read set", async () => {
  const previous = globalThis.localStorage, values = new Map([["pdos-next:my-work:recent-projects:me", JSON.stringify(["revoked", "project"])], ["pdos-next:my-work:recent-projects:other", JSON.stringify(["other-project"])]]);
  globalThis.localStorage = { getItem: key => values.get(key) ?? null, setItem: (key, value) => values.set(key, value) };
  try {
    const fixture = apiFixture(), opened = [], component = driver({ ...defaultProps(fixture.api), onOpenProject: (...args) => opened.push(args) });
    component.render(); component.mount(); await tick(); const tree = component.render(), recents = section(tree, "最近访问的项目");
    assert.match(markup(recents), /合成项目/); assert.doesNotMatch(markup(recents), /revoked|other-project/);
    elements(recents, element => element.type === "button")[0].props.onClick();
    assert.deepEqual(opened, [["cat", "project"]]);
    assert.equal(JSON.parse(values.get("pdos-next:my-work:recent-projects:me"))[0], "project");
    assert.equal(values.get("pdos-next:my-work:recent-projects:other"), JSON.stringify(["other-project"]));
  } finally { if (previous === undefined) delete globalThis.localStorage; else globalThis.localStorage = previous; }
});

test("failed and partial reads keep unknown totals and retry instead of claiming empty queues", async () => {
  let fail = true; const fixture = apiFixture({ fail: () => fail }), component = driver(defaultProps(fixture.api));
  component.render(); component.mount(); await tick(); let tree = component.render();
  assert.match(markup(tree), /合成读取失败/); assert.doesNotMatch(markup(tree), /当前没有需要你答复/);
  assert.match(markup(section(tree, "任务期限筛选")), /—/);
  fail = false; elements(tree, element => element.props?.children?.some?.(child => child === "刷新"))[0].props.onClick();
  component.render(); component.mount(); await tick(); tree = component.render();
  assert.match(markup(tree), /任务今日/); assert.doesNotMatch(markup(tree), /合成读取失败/);
  const partial = driver(defaultProps(apiFixture({ unavailable: 1 }).api));
  partial.render(); partial.mount(); await tick(); tree = partial.render();
  assert.match(markup(section(tree, "任务期限筛选")), /—/); assert.match(markup(tree), /列表可能不完整/);
});

test("the shared attention queues stay separate from paused runs and do not issue an obsolete standalone G0 read", async () => {
  const fixture = apiFixture(), component = driver(defaultProps(fixture.api));
  component.render(); component.mount(); await tick(); const tree = component.render();
  assert.equal(elements(tree, element => element.type?.name === "PersonalAttention").length, 1);
  assert.equal(fixture.calls.some(call => call.url.startsWith("v1/personal/g0-reviews")), false);
  assert.match(markup(section(tree, "运行与项目风险")), /需要答复的合成工作|合成风险/);
  assert.ok(fixture.calls.every(call => call.body === undefined));
});

test("principal changes synchronously hide every previous private project, run and promise before effects run", async () => {
  const fixture = apiFixture({ g0Items: [g0Item], promiseItems: [promiseItem] }), component = driver(defaultProps(fixture.api));
  component.render(); component.mount(); await tick(); const loaded = markup(component.render());
  for (const text of ["任务今日", "合成项目", "需要答复的合成工作", "已完成的合成工作", "合成承诺Build"]) assert.ok(loaded.includes(text));
  component.setProps({ session: { name: "另一合成人员", principal_id: "other" } }); const pending = markup(component.render());
  for (const text of ["任务今日", "合成项目", "需要答复的合成工作", "已完成的合成工作", "合成承诺Build"]) assert.equal(pending.includes(text), false, text);
  assert.match(pending, /正在读取/); assert.equal(fixture.calls.length, 6);
});

test("test-start promise records stay outside triage counts and retain explicit receiver and coverage gaps", async () => {
  const fixture = apiFixture({ g0Items: [g0Item], promiseItems: [promiseItem] }), component = driver(defaultProps(fixture.api));
  component.render(); component.mount(); await tick(); const tree = component.render(), panel = markup(section(tree, "承诺与外部等待"));
  assert.match(panel, /我作出的开测承诺记录（已接测试）/); assert.match(panel, /Asia\/Shanghai/); assert.match(panel, /接收方尚未记录/); assert.match(panel, /外部等待与其他通用承诺仍未接入/); assert.match(panel, /进入后仍需选择上述 Build、请求与 Run/);
  assert.match(markup(elements(section(tree, "办理类型"), item => item.type === "button")[0]), />2</);
  assert.equal(elements(section(tree, "办理类型"), item => item.props?.disabled).length, 0); assert.ok(fixture.calls.every(call => call.body === undefined));
});

test("test-start promise read failure leaves tasks and run activity intact", async () => {
  const fixture = apiFixture({ g0Items: [g0Item], promisesFail: () => true }), component = driver(defaultProps(fixture.api));
  component.render(); component.mount(); await tick(); const tree = component.render(), rendered = markup(tree);
  assert.match(markup(section(tree, "承诺与外部等待")), /合成开测承诺读取失败/);
  for (const text of ["任务今日", "需要答复的合成工作", "已完成的合成工作"]) assert.ok(rendered.includes(text));
  assert.doesNotMatch(markup(section(tree, "承诺与外部等待")), /全部 <b>0/);
});
