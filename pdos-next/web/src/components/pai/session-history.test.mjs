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
const { SessionHistory } = load(path.join(directory, "session-history.tsx"));
const tick = () => new Promise(resolve => setImmediate(resolve));
const uuid = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const principal = uuid(101), category = uuid(102), proposal = uuid(103), sid = uuid(20), runId = uuid(60);
const scope = { categoryId: category, proposalId: proposal };
const time = "2026-10-17T01:02:03.123456+00:00";
const head = (id = runId, goal = "核对原目标") => ({ run_id: id, goal, status: "completed", error_code: null, created_at: time, continued_from_id: null, reverted: false });
const meta = (id = sid) => ({ session_id: id, revision: 1, created_at: time, scope: { category_id: category, product_id: null, proposal_id: proposal }, run_count: 1 });
const presentation = (overrides = {}) => ({ id: null, revision: 0, title: null, pinned: false, archived: false, created_at: null, ...overrides });
const item = (id = sid, run = head(), p = presentation()) => ({ ...meta(id), scope: { ...meta(id).scope, project_id: null }, latest_run: run, matched_run: null, presentation: p });
const list = (items = [item()], next_cursor = null) => ({ version: "agent-conversation-list/v1", principal_id: principal, scope: { category_id: category, proposal_id: proposal }, as_of: time, items, next_cursor });
const runs = (id = sid, values = [head()]) => ({ version: "agent-session-runs/v1", principal_id: principal, scope: { category_id: category, proposal_id: proposal }, as_of: time,
  session: { ...meta(id), run_count: values.length }, items: values.map(value => ({ ...value, conversation: { previous_run_id: value.continued_from_id, next_run_id: null } })), next_cursor: null });
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
const text = tree => !tree || typeof tree === "boolean" ? "" : typeof tree !== "object" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : text(tree.props?.children);
function component(initial) {
  let props = { principalId: principal, scope, onClearSelection() {}, onSelectRun() {}, ...initial };
  const levels = [];
  function render(next) {
    if (next) props = { ...props, ...next };
    let call = SessionHistory, input = props, depth = 0;
    try { for (;;) {
      const key = input.__key ?? "root";
      if (!levels[depth] || levels[depth].key !== key) {
        levels.slice(depth).forEach(state => state?.values.forEach(value => value?.cleanup?.()));
        levels.length = depth; levels[depth] = { key, values: [], effects: [], index: 0 };
      }
      hooks = levels[depth]; hooks.index = 0; hooks.effects = [];
      const tree = call(input);
      if (!tree || typeof tree.type !== "function" || !/HistoryIdentity|HistoryPages/.test(tree.type.name)) return tree;
      call = tree.type; input = { ...tree.props, __key: tree.key }; depth++;
    } } finally { hooks = null; }
  }
  function effects() { levels.forEach(state => { const scheduled = state.effects; state.effects = []; scheduled.forEach(effect => effect()); }); }
  return { render, unmount() { levels.forEach(state => state?.values.forEach(value => value?.cleanup?.())); levels.length = 0; }, async flush() { render(); effects(); await tick(); const tree = render(); effects(); return tree; }, effects };
}
const namedButton = (c, label) => elements(c.render(), e => e.props?.onClick && text(e) === label)[0];
async function click(c, label) { const target = namedButton(c, label); assert.ok(target, label); target.props.onClick(); return c.flush(); }
const sessionButton = (c, index = 0) => elements(c.render(), e => e.type === "button" && e.props.className === "session")[index];
const runButton = c => elements(c.render(), e => e.type === "button" && e.props.className === "run")[0];
const search = c => elements(c.render(), e => e.type === "input" && e.props.type === "search")[0];

test("opening and two explicit selections only read GET metadata; original goals, readable counts and identities stay distinct", async () => {
  const calls = [], selected = []; let cleared = 0;
  const api = async (path, body) => { calls.push({ path, body }); return path.includes("/runs?") ? runs() : list(); };
  const c = component({ api, onClearSelection() { cleared++; }, onSelectRun(...value) { selected.push(value); }, currentSessionId: sid, currentRunId: runId });
  assert.ok(!renderToStaticMarkup(React.createElement(SessionHistory, { api, principalId: principal, scope, onSelectRun() {}, onClearSelection() {} })).includes("核对原目标"));
  assert.equal(calls.length, 0); await c.flush();
  assert.equal(calls.length, 1); assert.ok(calls[0].path.startsWith(`v1/categories/${category}/agent-conversations?`));
  assert.equal(new URLSearchParams(calls[0].path.split("?")[1]).get("proposal_id"), proposal);
  assert.match(text(c.render()), /最新原目标核对原目标1 项可读工作/);
  assert.equal(selected.length, 0); assert.equal(runButton(c), undefined);
  const card = sessionButton(c); assert.ok(card.props.title.includes(sid)); assert.ok(!text(card).includes(sid));
  card.props.onClick(); await c.flush(); assert.equal(calls.length, 2); assert.equal(selected.length, 0); assert.equal(cleared, 1);
  assert.equal(text(runButton(c)).includes(runId), false); assert.ok(text(c.render()).includes(runId)); // collapsed identity details retain the exact original record.
  runButton(c).props.onClick(); assert.deepEqual(selected, [[runId, sid]]);
  assert.ok(calls.every(call => call.body === undefined)); assert.ok(!calls.some(call => /agent-runs|commands/.test(call.path)));
});

test("server search includes historic matched_run; Unicode limit counts characters and old search replies stay hidden", async () => {
  const calls = []; let late;
  const c = component({ api: async path => {
    calls.push(path); const q = new URLSearchParams(path.split("?")[1]).get("q");
    if (!q) return list();
    if (q === "旧搜索") return new Promise(resolve => { late = resolve; });
    const row = { ...item(), run_count: 2, matched_run: { ...head(uuid(59), "历史原目标"), match_kind: "goal" } };
    return list([row]);
  } });
  await c.flush(); search(c).props.onChange({ target: { value: "旧搜索" } }); await c.flush();
  assert.equal(sessionButton(c), undefined);
  search(c).props.onChange({ target: { value: "😀".repeat(160) } }); await c.flush();
  assert.match(text(c.render()), /命中原目标：历史原目标（历史工作）/);
  assert.equal([...new URLSearchParams(calls.at(-1).split("?")[1]).get("q")].length, 160);
  assert.equal(search(c).props.maxLength, undefined);
  late(list([item(sid, head(runId, "不能回来"))])); await tick(); assert.ok(!text(c.render()).includes("不能回来"));
  const count = calls.length; search(c).props.onChange({ target: { value: "😀".repeat(161) } }); await c.flush();
  assert.equal(calls.length, count); assert.match(text(c.render()), /最多 160 个字符/); assert.equal(sessionButton(c), undefined);
});

test("permission or protocol failure in Session runs hides the old goals; explicit 503 retains only verified list metadata", async () => {
  let status = 403, cleared = 0;
  const c = component({ api: async path => { if (path.includes("/runs?")) throw Object.assign(Error("读取受限"), { status }); return list(); }, onClearSelection() { cleared++; } });
  await c.flush(); sessionButton(c).props.onClick(); await c.flush();
  assert.equal(sessionButton(c), undefined); assert.match(text(c.render()), /刷新会话以重新核对可读范围/); assert.equal(cleared, 2);
  status = 503; await click(c, "刷新会话"); sessionButton(c).props.onClick(); await c.flush();
  assert.ok(sessionButton(c)); assert.equal(runButton(c), undefined); assert.match(text(c.render()), /读取受限/); assert.ok(namedButton(c, "重新读取会话工作"));
});

test("switching Session discards late work heads; accepted continuation refresh does not clear parent's newly read Run", async () => {
  let resolveOld, cleared = 0; const secondId = uuid(19), secondRun = uuid(59);
  const c = component({ api: async path => path.includes(`/` + sid + `/runs?`) ? new Promise(resolve => { resolveOld = resolve; }) : path.includes("/runs?") ? runs(secondId, [head(secondRun, "另一次真实目标")]) : list([item(), item(secondId, head(secondRun))]), onClearSelection() { cleared++; } });
  await c.flush(); sessionButton(c).props.onClick(); await c.flush(); sessionButton(c, 1).props.onClick(); await c.flush();
  assert.match(text(runButton(c)), /另一次真实目标/);
  resolveOld(runs()); await tick(); assert.match(text(runButton(c)), /另一次真实目标/);
  const prior = cleared; c.render({ refreshVersion: 1, currentSessionId: secondId, currentRunId: secondRun });
  assert.equal(sessionButton(c), undefined); assert.equal(runButton(c), undefined);
  await c.flush(); assert.equal(cleared, prior); assert.equal(runButton(c), undefined); // never auto-select the first or latest Run.
});

test("explicit paging deduplicates changed snapshots; invalid cursor requires a fresh list and can be retried", async () => {
  const page = Array.from({ length: 20 }, (_, index) => item(uuid(20 - index), head(uuid(100 + 20 - index))));
  let fail = false;
  const c = component({ api: async path => { if (path.includes("cursor=")) { if (fail) throw Object.assign(Error("游标已失效"), { status: 403 }); return list([page[18], item(uuid(0), head(uuid(100)))]) } return list(page, uuid(1)); } });
  await c.flush(); await click(c, "加载更多会话");
  assert.equal(elements(c.render(), e => e.type === "button" && e.props.className === "session").length, 21);
  await click(c, "刷新会话"); fail = true; await click(c, "加载更多会话");
  assert.equal(sessionButton(c), undefined); assert.match(text(c.render()), /游标已失效/);
  fail = false; await click(c, "刷新会话"); assert.ok(sessionButton(c));
});

test("API, principal and category changes hide previous private metadata during render and ignore late responses", async () => {
  let resolveOld;
  const api = async path => path.includes("/runs?") ? new Promise(resolve => { resolveOld = resolve; }) : list();
  const c = component({ api }); await c.flush(); sessionButton(c).props.onClick(); await c.flush();
  const changed = c.render({ principalId: uuid(104), scope: { categoryId: uuid(105) } }); assert.ok(!text(changed).includes("核对原目标"));
  resolveOld(runs()); await tick(); assert.ok(!text(c.render()).includes("核对原目标"));
  assert.equal(c.render({ api: async () => { throw Error("new identity unavailable"); } }), null);
  await c.flush(); assert.ok(!text(c.render()).includes("核对原目标"));
});

test("missing principal resolves actual identity with GET before reading personal Sessions", async () => {
  const calls = [];
  const c = component({ principalId: undefined, scope: { categoryId: null }, api: async (path, body) => {
    calls.push({ path, body });
    if (path === "v1/session") return { principal_id: principal };
    const value = list(); value.scope = { category_id: null, proposal_id: null };
    value.items[0].scope = { category_id: null, product_id: null, proposal_id: null, project_id: null };
    return value;
  } });
  assert.equal(calls.length, 0); await c.flush(); await c.flush();
  assert.equal(calls[0].path, "v1/session"); assert.ok(calls[1].path.startsWith("v1/personal/agent-conversations?"));
  assert.ok(sessionButton(c)); assert.ok(calls.every(call => call.body === undefined));
});

const receipt = (body, options = {}) => ({ version: "agent-session-presentation/v1", principal_id: principal, scope: { category_id: category, proposal_id: proposal }, session: { session_id: sid, category_id: category, product_id: null, proposal_id: proposal, project_id: null }, presentation: { id: uuid(301), revision: body.expected_revision + 1, title: body.action === "rename" ? body.title : null, pinned: body.action === "pin", archived: body.action === "archive", created_at: time, action: body.action, request_key: body.request_key, ...options } });
const nameInput = c => elements(c.render(), e => e.type === "input" && e.props["aria-label"] === "会话名称")[0];
async function rename(c, title) {
  await click(c, "重命名"); nameInput(c).props.onChange({ target: { value: title } }); await c.flush();
  elements(c.render(), e => e.type === "form")[0].props.onSubmit({ preventDefault() {} }); return c.flush();
}

test("rename, reset, pin, archive and restore use exact server revisions and reread Current; goals stay immutable", async () => {
  const calls = []; let p = presentation();
  const api = async (path, body) => {
    calls.push({ path, body });
    if (body) { const r = receipt(body, { ...p, id: uuid(301), revision: body.expected_revision + 1, created_at: time, action: body.action, request_key: body.request_key,
      ...(body.action === "rename" ? { title: body.title } : body.action === "pin" ? { pinned: true } : body.action === "archive" ? { archived: true } : body.action === "restore" ? { archived: false } : { pinned: false }) });
      p = Object.fromEntries(Object.entries(r.presentation).filter(([field]) => field !== "action" && field !== "request_key")); return r;
    }
    const view = new URLSearchParams(path.split("?")[1]).get("view"); return list(p.archived === (view === "archived") ? [item(sid, head(), p)] : []);
  };
  const c = component({ api }); await c.flush(); await rename(c, "  我的名称  "); await c.flush();
  assert.match(text(sessionButton(c)), /会话名称我的名称最新原目标：核对原目标/);
  assert.deepEqual(Object.keys(calls.find(x => x.body).body).sort(), ["action", "expected_revision", "request_key", "title"]);
  assert.equal(calls.find(x => x.body).body.title, "我的名称"); assert.equal(calls.find(x => x.body).body.expected_revision, 0);
  await click(c, "重命名"); await click(c, "恢复原目标名称"); await c.flush(); assert.match(text(sessionButton(c)), /最新原目标核对原目标/);
  await click(c, "置顶"); await c.flush(); assert.match(text(sessionButton(c)), /已置顶/);
  await click(c, "取消置顶"); await c.flush(); assert.ok(!text(sessionButton(c)).includes("已置顶"));
  await click(c, "归档"); await c.flush(); assert.equal(sessionButton(c), undefined);
  await click(c, "已归档"); assert.ok(sessionButton(c)); await click(c, "恢复会话"); await c.flush(); assert.equal(sessionButton(c), undefined);
  await click(c, "未归档"); assert.ok(sessionButton(c));
  assert.deepEqual(calls.filter(x => x.body).map(x => x.body.expected_revision), [0, 1, 2, 3, 4, 5]);
  assert.ok(calls.every(x => !/delete|cancel|agent-runs|commands/.test(x.path))); assert.ok(calls.filter(x => x.body).every(x => new URLSearchParams(x.path.split("?")[1]).get("proposal_id") === proposal));
});

test("unknown write survives same-identity refresh; read recovery never resubmits and explicit retry preserves exact original body", async () => {
  const calls = []; let saved;
  const api = async (path, body) => {
    calls.push({ path, body });
    if (body) { if (!saved) { saved = body; throw Object.assign(Error("结果尚未核对"), { status: 503 }); } assert.equal(body, saved); return receipt(body); }
    if (path.includes("/requests/")) throw Object.assign(Error("暂无回执"), { status: 404 });
    return list();
  };
  const c = component({ api }); await c.flush(); await rename(c, "不确定名称");
  assert.ok(namedButton(c, "查询原请求回执")); assert.equal(calls.filter(x => x.body).length, 1);
  await click(c, "刷新会话"); assert.ok(namedButton(c, "查询原请求回执")); assert.equal(nameInput(c), undefined); assert.equal(calls.filter(x => x.body).length, 1);
  await click(c, "查询原请求回执"); assert.equal(calls.filter(x => x.body).length, 1); assert.ok(calls.at(-1).path.includes(`/requests/${saved.request_key}?`));
  assert.match(text(c.render()), /尚未查到原请求回执/); await click(c, "重试原请求"); await c.flush(); assert.equal(calls.filter(x => x.body).length, 2);
  assert.equal(namedButton(c, "查询原请求回执"), undefined); assert.match(text(sessionButton(c)), /最新原目标核对原目标/); // receipt never overwrites server Current.
});

test("original receipt recovery is read-only and refreshes actual Current, even if Current has a newer name", async () => {
  let original, p = presentation(); const calls = [];
  const api = async (path, body) => {
    calls.push({ path, body });
    if (body) { original = body; throw Object.assign(Error("断线"), { status: 503 }); }
    if (path.includes("/requests/")) { p = presentation({ id: uuid(301), revision: 9, created_at: time, title: "更新后的名称" }); return receipt(original); }
    return list([item(sid, head(), p)]);
  };
  const c = component({ api }); await c.flush(); await rename(c, "原请求名称"); await click(c, "查询原请求回执"); await c.flush();
  assert.equal(calls.filter(x => x.body).length, 1); assert.match(text(sessionButton(c)), /更新后的名称/); assert.ok(!text(sessionButton(c)).includes("原请求名称"));
});

test("409 clears mutation pointer and only refreshes; failed scope reads hide cached rows", async () => {
  const calls = []; let denied = false;
  const c = component({ api: async (path, body) => {
    calls.push({ path, body }); if (body) { denied = true; throw Object.assign(Error("冲突"), { status: 409 }); }
    if (denied) throw Object.assign(Error("权限已变化"), { status: 403 }); return list();
  } });
  await c.flush(); await click(c, "置顶"); await c.flush(); assert.equal(calls.filter(x => x.body).length, 1);
  assert.equal(namedButton(c, "重试原请求"), undefined); assert.equal(sessionButton(c), undefined); assert.match(text(c.render()), /会话已发生变化/); assert.match(text(c.render()), /权限已变化/);
});

test("refresh and identity transitions discard late mutation receipts, original request state and editor by the appropriate boundary", async () => {
  let complete, body, reads = 0;
  const api = async (path, value) => { if (value) { body = value; return new Promise(resolve => { complete = resolve; }); } reads++; return list(); };
  const c = component({ api }); await c.flush(); await rename(c, "迟到名称"); await click(c, "刷新会话");
  assert.ok(namedButton(c, "查询原请求回执")); const prior = reads; complete(receipt(body)); await tick(); await c.flush();
  assert.equal(reads, prior); assert.ok(namedButton(c, "查询原请求回执"));
  const changed = c.render({ scope: { ...scope, projectId: uuid(999) } }); assert.ok(!text(changed).includes(body.request_key)); c.effects(); await c.flush(); assert.equal(namedButton(c, "查询原请求回执"), undefined);
  await click(c, "重命名"); assert.ok(nameInput(c)); c.render({ refreshVersion: 2 }); assert.equal(nameInput(c), undefined);
  c.unmount(); complete(receipt(body)); await tick();
});


test("unknown original pointers cannot cross principal, category, proposal, project, transport or unmount", async () => {
  for (const changed of [{ principalId: uuid(800) }, { scope: { ...scope, categoryId: uuid(801) } }, { scope: { ...scope, proposalId: uuid(802) } }, { scope: { ...scope, projectId: uuid(803) } }, { api: async () => list() }]) {
    const calls = [];
    const c = component({ api: async (path, body) => { calls.push({ path, body }); if (body) throw Object.assign(Error("未知结果"), { status: 503 }); return list(); } });
    await c.flush(); await click(c, "置顶"); assert.ok(namedButton(c, "查询原请求回执"));
    assert.ok(!text(c.render(changed)).includes("原请求已保留")); c.effects(); await c.flush(); assert.equal(namedButton(c, "重试原请求"), undefined);
    assert.equal(calls.filter(x => x.body).length, 1); c.unmount();
  }
});

test("a late read recovery after refresh cannot apply its receipt or clear the retained original pointer", async () => {
  let original, finish; let reads = 0;
  const api = async (path, body) => { if (body) { original = body; throw Object.assign(Error("结果未知"), { status: 503 }); } if (path.includes("/requests/")) return new Promise(resolve => { finish = resolve; }); reads++; return list(); };
  const c = component({ api }); await c.flush(); await click(c, "置顶"); await click(c, "查询原请求回执"); await click(c, "刷新会话");
  const prior = reads; finish(receipt(original)); await tick(); await c.flush(); assert.equal(reads, prior); assert.ok(namedButton(c, "查询原请求回执")); assert.ok(text(c.render()).includes(original.request_key));
});
