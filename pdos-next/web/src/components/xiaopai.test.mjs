import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test, { after } from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const browserStorageDescriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
const localValues = new Map();
Object.defineProperty(globalThis, "localStorage", { configurable: true, writable: true, value: { getItem: key => localValues.get(key) ?? null, setItem: (key, value) => localValues.set(key, value), removeItem: key => localValues.delete(key) } });
after(() => { if (browserStorageDescriptor) Object.defineProperty(globalThis, "localStorage", browserStorageDescriptor); else delete globalThis.localStorage; });
let hooks = null;
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- In-memory event dispatcher; SSR forwards hooks unchanged. */
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
  useCallback(callback, dependencies) { return hooks ? callback : React.useCallback(callback, dependencies); },
  useMemo(callback, dependencies) { return hooks ? callback() : React.useMemo(callback, dependencies); },
  useEffect(effect, dependencies) { if (!hooks) React.useEffect(effect, dependencies); else hooks.effects.push(effect); },
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
const { Xiaopai } = load(path.join(directory, "xiaopai.tsx"));
const { PersonalXiaopai } = load(path.join(directory, "category-create/personal-xiaopai.tsx"));
const { FileUpload } = load(path.join(directory, "pai/file-upload.tsx"));
const { SourcePicker, RunSourceBindings, sourcePickerScope } = load(path.join(directory, "pai/source-picker.tsx"));
const { RunContinuation } = load(path.join(directory, "pai/run-continuation.tsx"));
const { SessionHistory } = load(path.join(directory, "pai/session-history.tsx"));
const { PaiRail } = load(path.join(directory, "pai-rail.tsx"));
const { ContextPicker } = load(path.join(directory, "pai/context-picker.tsx"));
const { SkillPicker } = load(path.join(directory, "pai/skill-picker.tsx"));
const { AnswerSources, SourceSnippet, sourceObjectHref } = load(path.join(directory, "pai/answer-sources.tsx"));
const { AnswerComparison } = load(path.join(directory, "pai/answer-comparison.tsx"));
const { loadedSkillFacts, PaiScope, PaiCarry, PaiPolicy, PaiResponse, PaiMessage, PaiDocumentCard } = load(path.join(directory, "pai-conversation.tsx"));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  if (["PaiResponse", "PaiHiddenResponse", "PaiGoal", "PaiDocumentCard", "PaiComposer"].includes(tree.type?.name)) return elements(tree.type(tree.props), predicate);
  return [...(predicate(tree) ? [tree] : []), ...elements([tree.props?.children, tree.props?.headerActions, tree.props?.contextControl], predicate)];
}
function session(props, Component = Xiaopai) {
  const levels = [];
  return { render(next) {
    if (next) props = { ...props, ...next };
    let call = Component, input = props, depth = 0;
    try { for (;;) {
      const prior = levels[depth], key = input.__key ?? "root";
      if (!prior || prior.key !== key) levels[depth] = { values: [], index: 0, effects: [], key };
      const state = levels[depth]; hooks = state; state.index = 0; state.effects = [];
      const tree = call(input);
      if (!tree || typeof tree.type !== "function" || !/^(ScopedXiaopai|PersonalIdentity|ScopedPersonalXiaopai)$/.test(tree.type.name)) return tree;
      call = tree.type; input = { ...tree.props, __key: tree.key }; depth++;
    } } finally { hooks = null; }
  }, mountEffects() { return levels.flatMap(state => state.effects.map(effect => effect())); } };
}
function button(tree, label) { return elements(tree, e => e.props?.children === label && e.props.onClick)[0]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
async function click(component, label) { const found = button(component.render(), label); assert.ok(found, label); found.props.onClick(); await tick(); }
const props = { productId: "product", sources: [], composeOpen: false, onComposeChange() {}, categoryId: "category", categoryName: "真实品类", principalId: "person" };
const run = { session_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", run_id: "server-run", goal: "核对真实资料", status: "running", product_id: "server-product", proposal_id: null, cancel_epoch: 0, reverted: false, result: {} };

for (const [name, Component, root] of [["project", Xiaopai, "v1/agent-runs"], ["personal", PersonalXiaopai, "v1/personal/agent-runs"]]) {
 test(`${name} hidden GET stops all event, candidate and result operations while retaining a new-conversation entry`, async () => {
  const hidden = { run_id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb", session_id: run.session_id, goal: "撤权后保留的原始目标",
   status: "hidden", history_hidden: true, hidden_reason: "source_unavailable", hidden_message: "原回答所依据的资料已不可读，保留你的原话。",
   recorded_at: "2026-10-17T12:34:56.123456+00:00", created_at: null, result: null, versions: {},
   product_id: null, project_id: null, proposal_id: null, session_proposal_id: null,
   conversation: { previous_run_id: null, next_run_id: null, links_unavailable: true }, error_code: null,
   reconciliation: null, process: null, reverted: null, reverted_at: null, reverted_by: null, revert_receipt_id: null, cancel_epoch: null };
  const calls = [], api = async (path, body) => { calls.push({ path, body }); assert.equal(path, `${root}/${hidden.run_id}`); return hidden; };
  const component = session({ ...props, api, onCreated() {} }, Component);
  elements(component.render(), e => e.type === SessionHistory)[0].props.onSelectRun(hidden.run_id, hidden.session_id);
  await tick(); const tree = component.render();
  assert.deepEqual(calls, [{ path: `${root}/${hidden.run_id}`, body: undefined }]);
  assert.ok(elements(tree, e => e.props?.children === hidden.goal).length);
  assert.ok(elements(tree, e => e.props?.children === hidden.hidden_message).length);
  assert.ok(elements(tree, e => e.type === "time" && e.props.dateTime === hidden.recorded_at).length);
  assert.equal(elements(tree, e => ["RunContinuation", "RunCandidates", "RunFeedback", "RunProcess", "RunReconciliation", "WorkProductActions", "RunSourceBindings", "PaiReplyDetails"].includes(e.type?.name)).length, 0);
  assert.equal(typeof elements(tree, e => e.type === PaiScope)[0].props.onNewConversation, "function");
 });
}

test("project case action delegates to the existing start journal and opens its same-session continuation", async () => {
  const id = n => `${String(n).padStart(8, "0")}-1111-4111-8111-111111111111`, calls = [];
  const projectId = id(1), productId = id(2), parentId = id(3), childId = id(4);
  const parent = { ...run, run_id: parentId, project_id: projectId, product_id: productId, status: "completed", result: { summary: "已整理案例", result: { assistant: { task_result: { version: 1, format: "cases", rows: [] }, sources: [] } } } };
  const child = { ...parent, run_id: childId, continued_from_id: parentId, result: { summary: "正在准备复验请求" } };
  const api = async (path, body) => {
    calls.push({ path, body: structuredClone(body) });
    if (body) return { run_id: childId, continued_from_id: parentId };
    if (path.endsWith("/events?after=0&page_size=200")) return { items: [], next_cursor: 0 };
    return path.includes(childId) ? child : parent;
  };
  const component = session({ ...props, projectId, productId, api });
  elements(component.render(), node => node.type === SessionHistory)[0].props.onSelectRun(parentId, parent.session_id); await tick();
  const action = elements(component.render(), node => node.type?.name === "VerificationPreparationAction")[0]; assert.ok(action);
  const intent = { path: "v1/agent-runs", body: { goal: "准备复验请求", idempotency_key: "original-verification-key", continue_from_run_id: parentId, sources: [], verification_action: { selection: { id: id(5), revision: 1, product_id: productId, project_id: projectId, engineering_configuration: { id: id(6), revision: 2 }, manufacturing_configuration: { id: id(7), revision: 3 } }, citation_ids: [id(8)] } } };
  action.props.onStart(intent); await tick();
  const writes = calls.filter(call => call.body !== undefined); assert.equal(writes.length, 1); assert.deepEqual(writes[0], intent);
  const history = elements(component.render(), node => node.type === SessionHistory)[0];
  assert.equal(history.props.currentSessionId, parent.session_id); assert.equal(history.props.currentRunId, childId);
});

test("公司引用只展示服务器来源且渲染时不读原文，历史更新有明确提示", () => {
  const original = globalThis.fetch;
  globalThis.fetch = () => { throw Error("Rendering a citation cannot fetch"); };
  try {
    const html = renderToStaticMarkup(React.createElement(AnswerSources, { answer: {
      lookup: "cited", notice: "资料已更新，请核对当前事实。", sources: [{
        citation_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", title: "<script>标题</script>",
        quote: "<img src=x onerror=alert(1)>", source_revision: 2, currentness: "updated",
        locator: { line_start: 3 }, url: "https://untrusted.invalid/raw",
      }, { citation_id: "forged", title: "不应显示", quote: "伪造行", source_revision: 1 }],
      unknowns: ["复验结果待确认"],
    } }));
    assert.match(html, /来源 · 1/); assert.match(html, /v2 · 第 3 行 · 资料已更新/);
    assert.match(html, /&lt;script&gt;/); assert.match(html, /&lt;img/);
    assert.doesNotMatch(html, /<script>|<img |untrusted.invalid|不应显示/);
    assert.match(html, /复验结果待确认/);
    assert.equal(renderToStaticMarkup(React.createElement(AnswerSources, { answer: { lookup: "not_run" } })), "");
    assert.match(renderToStaticMarkup(React.createElement(AnswerSources, { answer: { lookup: "no_match", notice: "在当前品类中没有找到相关记录" } })), /在当前品类中没有找到相关记录/);
  } finally { globalThis.fetch = original; }
});

test("更新后的引用仅在服务器明确核对原正文仍可读时提供原固定片段入口", () => {
  const source = { citation_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", title: "原知识", quote: "原逐字引用", source_revision: 1, currentness: "updated", url: "/api/v1/personal/agent-runs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/assistant-sources/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb" };
  const original = globalThis.fetch; globalThis.fetch = () => { throw Error("render cannot read a source"); };
  try {
    const html = fixed => renderToStaticMarkup(React.createElement(AnswerSources, { answer: { lookup: "cited", sources: [{ ...source, fixed_body_available: fixed }] } }));
    assert.match(html(true), /资料已更新/); assert.match(html(true), /查看原固定片段/);
    for (const value of [undefined, false, "true", 1]) assert.doesNotMatch(html(value), /查看原固定片段|查看资料段落/);
    const external = renderToStaticMarkup(React.createElement(AnswerSources, { answer: { lookup: "cited", sources: [{ ...source, fixed_body_available: true, url: "https://untrusted.invalid/raw" }] } }));
    assert.doesNotMatch(external, /查看原固定片段|untrusted.invalid/);
  } finally { globalThis.fetch = original; }
});

test("固定资料差异表保留两侧原文、表格定位、公式与未知影响，渲染时不读取原件", () => {
  const original = globalThis.fetch; globalThis.fetch = () => { throw Error("render must not fetch"); };
  const left = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", right = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  const data = { version: 1, format: "comparison", complete: false, citation_ids: [left, right], unmatched: [{ citation_id: right, sheet: "规格", reason: "ambiguous_row_keys", count: 2 }], stats: { changes: 2, unmatched_sections: 2, unaligned_changes: 0 }, alignment_basis: [{ sheet: "规格", key_header: "参数" }], rows: [{
    change_id: "a".repeat(64), kind: "modified", aligned: true, label: "压力条件",
    old: { citation_id: left, quote: "10 bar", value_kind: "text", locator: { native: ['cell:["规格","B2"]'] } },
    new: { citation_id: right, quote: "=A1+A2", value_kind: "formula", locator: { native: ['cell:["规格","C3"]'] } },
    impact: null, questions: ["<script>核对工况</script>"],
  }] };
  try {
    const html = renderToStaticMarkup(React.createElement(AnswerComparison, { value: data }));
    assert.match(html, /差异表，可横向滚动/); assert.match(html, /10 bar/); assert.match(html, /=A1\+A2/);
    assert.match(html, /公式原文（未计算）/); assert.match(html, /待确认/); assert.match(html, /不能视为无变化/);
    assert.match(html, /新版 · 规格：作为行标识的首列有空值或重复/);
    assert.match(html, /规格.*B2/); assert.match(html, /规格.*C3/); assert.doesNotMatch(html, /<script>/);
    assert.match(renderToStaticMarkup(React.createElement(AnswerComparison, { value: { ...data, complete: true } })), /暂不可核对/);
  } finally { globalThis.fetch = original; }
});

test("比较来源续读保留服务器签发的差异定位，不接受额外查询字段", async () => {
  const original = globalThis.fetch, calls = [];
  const url = "/api/v1/personal/agent-runs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/assistant-sources/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb?change_id=" + "a".repeat(64);
  try {
    globalThis.fetch = async path => { calls.push(path); return Response.json({ text: "固定差异段落", next_cursor: null }); };
    const component = session({ url, onUnavailable() {} }, SourceSnippet); component.render(); component.mountEffects();
    await button(component.render(), "查看资料段落").props.onClick();
    const query = new URL(calls[0], "http://localhost").searchParams;
    assert.equal(query.get("change_id"), "a".repeat(64)); assert.equal(query.get("cursor"), "0"); assert.equal(query.get("page_chars"), "1600");
    const invalid = session({ url: url + "&tenant_id=other", onUnavailable() {} }, SourceSnippet); invalid.render(); invalid.mountEffects();
    await button(invalid.render(), "查看资料段落").props.onClick(); assert.equal(calls.length, 1);
  } finally { globalThis.fetch = original; }
});

test("手动续读引用使用有界同源页，撤权清正文，卸载后的迟到响应不再显示", async () => {
  const original = globalThis.fetch, calls = [];
  const url = "/api/v1/personal/agent-runs/aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa/assistant-sources/bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
  let unavailable = 0;
  try {
    globalThis.fetch = async (path, init) => {
      calls.push({ path, init });
      return calls.length === 1 ? Response.json({ text: "当前可读正文", next_cursor: 30 }) : new Response("", { status: 403 });
    };
    const component = session({ url, onUnavailable: () => { unavailable++; } }, SourceSnippet);
    component.render(); component.mountEffects();
    assert.equal(calls.length, 0);
    await button(component.render(), "查看资料段落").props.onClick();
    assert.equal(elements(component.render(), e => e.type === "pre")[0].props.children, "当前可读正文");
    await button(component.render(), "继续读取").props.onClick();
    assert.equal(elements(component.render(), e => e.type === "pre").length, 0);
    assert.equal(unavailable, 1);
    assert.equal(calls[1].path, `${url}?cursor=30&page_chars=1600`);
    assert.equal(calls[0].init.credentials, "same-origin"); assert.equal(calls[0].init.cache, "no-store");
    let changed = 0;
    globalThis.fetch = async () => Response.json({ code: "SOURCE_STALE" }, { status: 409 });
    const updated = session({ url, onUnavailable: () => { unavailable++; }, onChanged: () => { changed++; } }, SourceSnippet);
    updated.render(); updated.mountEffects();
    await button(updated.render(), "查看资料段落").props.onClick();
    assert.equal(changed, 1); assert.equal(unavailable, 1);
    let finish;
    globalThis.fetch = () => new Promise(resolve => { finish = resolve; });
    const late = session({ url, onUnavailable: () => { unavailable++; } }, SourceSnippet);
    late.render(); const cleanups = late.mountEffects();
    const pending = button(late.render(), "查看资料段落").props.onClick();
    cleanups.forEach(cleanup => cleanup?.());
    finish(Response.json({ text: "不再显示的旧正文", next_cursor: null })); await pending;
    assert.equal(elements(late.render(), e => e.type === "pre").length, 0);
    assert.equal(unavailable, 1);
  } finally { globalThis.fetch = original; }
});

test("小Pai初次呈现不调用API，实际技能记录才生成chips", () => {
  const api = () => { throw Error("Rendering cannot fetch or execute"); };
  const html = renderToStaticMarkup(React.createElement(Xiaopai, { ...props, api }));
  for (const text of ["真实品类", "本次发送携带什么", "新对话", "会话信息", "自动 / 一次确认 / 具名决定"]) assert.ok(html.includes(text), text);
  assert.ok(!html.includes("public_research"));
  const skills = loadedSkillFacts([{ event: { type: "model_started", key: "not-loaded" } },
    { event: { type: "skill_loaded", key: "public_research", version: "v1" } },
    { event: { type: "skill_loaded", key: "public_research", version: "v1" } }]);
  assert.deepEqual(skills, [{ key: "public_research", version: "v1" }]);
  const scope = renderToStaticMarkup(React.createElement(PaiScope, { scope: "真实范围", skills, hasRun: true }));
  assert.match(scope, /公开研究 · v1/); assert.ok(!scope.includes("not-loaded"));
});

test("转后台只收起同一运行，从历史返回只读原记录", async () => {
  const calls = []; let closed = 0;
  const component = session({ ...props, onBackground() { closed++; }, api: async (path, body) => {
    calls.push({ path, body }); assert.equal(body, undefined);
    if (path.includes("?page_size")) return { items: [{ ...run, created_at: "2026-10-17T00:00:00Z" }], next_cursor: null };
    if (path.includes("/events")) return { items: [{ sequence: 1, event: { type: "skill_loaded", key: "public_research", version: "v1" } }], next_cursor: 1 };
    return run;
  } });
  const open = () => elements(component.render(), e => e.type === SessionHistory)[0].props.onSelectRun(run.run_id, run.session_id);
  open(); await tick();
  const before = calls.length;
  const scope = elements(component.render(), e => e.type === PaiScope)[0].props;
  assert.equal(scope.scope, "真实品类 · 运行绑定型号"); assert.equal(scope.skills[0].key, "public_research");
  scope.onBackground(); await tick(); assert.equal(closed, 1); assert.equal(calls.length, before);
  assert.equal(typeof elements(component.render(), e => e.type === PaiScope)[0].props.onBackground, "function"); // Rail closure preserves the mounted thread and confirmation state.
  open(); await tick();
  assert.ok(calls.slice(before).every(call => call.path.includes("/server-run")));
  assert.equal(calls.some(call => call.body), false);
});

test("会话入口携带真实范围，失败刷新清除旧正文和技能，携带区保留来源语义", async () => {
  let fail = false;
  const component = session({ ...props, proposalId: "proposal", api: async path => {
    if (fail) throw Error("权限已变化");
    if (path.includes("/events")) return { items: [{ sequence: 1, event: { type: "skill_loaded", key: "public_research", version: "v1" } }], next_cursor: 1 };
    return { ...run, proposal_id: "proposal", result: { summary: "私有正文" } };
  } });
  const history = elements(component.render(), e => e.type === SessionHistory)[0];
  assert.deepEqual(history.props.scope, { categoryId: "category", proposalId: "proposal" });
  history.props.onSelectRun(run.run_id, run.session_id); await tick();
  assert.ok(elements(component.render(), e => e.props?.children === "私有正文").length);
  fail = true; await click(component, "核对当前状态");
  assert.equal(elements(component.render(), e => e.props?.children === "私有正文").length, 0);
  assert.deepEqual(elements(component.render(), e => e.type === PaiScope)[0].props.skills, []);
  assert.ok(button(component.render(), "核对所选运行"));
  const html = renderToStaticMarkup(React.createElement(PaiCarry, { scope: "当前品类", objects: ["来源甲 · 版本 3"] }));
  assert.match(html, /来源甲 · 版本 3/); assert.match(html, /发送后由服务器/);
  assert.ok(!/T[012]|token/.test(renderToStaticMarkup(React.createElement(PaiPolicy))));
});

test("提案页恢复同一绑定链的空提案祖先并拒绝其他运行", async () => {
  const component = session({ ...props, proposalId: "proposal", api: async path => {
    if (path.includes("/events")) return { items: [], next_cursor: 0 };
    if (path.includes("other-run")) return { ...run, run_id: "other-run", session_proposal_id: null, result: { summary: "不应显示" } };
    return { ...run, session_proposal_id: "proposal", result: { summary: "绑定前的真实正文" } };
  } });
  const select = id => elements(component.render(), e => e.type === SessionHistory)[0].props.onSelectRun(id, run.session_id);
  select(run.run_id); await tick();
  assert.ok(elements(component.render(), e => e.props?.children === "绑定前的真实正文").length);
  select("other-run"); await tick();
  assert.equal(elements(component.render(), e => e.props?.children === "不应显示").length, 0);
  assert.ok(elements(component.render(), e => e.props?.children === "运行不属于当前提案，请刷新本提案的运行历史。").length);
});

test("会话与Run不匹配拒绝结果，身份和API切换同步清除原线程", async () => {
  const api = async path => path.includes("/events") ? { items: [], next_cursor: 0 } : { ...run, result: { summary: "原私有结果" } };
  const component = session({ ...props, api });
  const select = () => elements(component.render(), e => e.type === SessionHistory)[0].props.onSelectRun(run.run_id, run.session_id);
  select(); await tick();
  assert.ok(elements(component.render(), e => e.props?.children === "原私有结果").length);
  assert.equal(elements(component.render({ principalId: "different" }), e => e.props?.children === "原私有结果").length, 0);
  elements(component.render(), e => e.type === SessionHistory)[0].props.onSelectRun(run.run_id, "wrong-session"); await tick();
  assert.equal(elements(component.render(), e => e.props?.children === "原私有结果").length, 0);
  const changed = component.render({ api: async () => { throw Error("new API"); } });
  assert.equal(changed, null);
});

test("展开与缩回工作区保留同一小Pai组件、范围、运行和挂载key", () => {
  const component = session({ open: true, onClose() {}, categoryId: "category", categoryName: "当前品类",
    paiContext: { categoryId: "category", productId: "product", sources: [] }, focusRun: { categoryId: "category", runId: "same-run" },
    session: { name: "实际用户", principal_id: "person" }, onCreated() {},
  }, PaiRail);
  const before = elements(component.render(), element => element.type === Xiaopai)[0];
  elements(component.render(), element => element.props?.["aria-label"] === "展开小Pai 对话工作区")[0].props.onClick();
  assert.equal(component.render().props["aria-label"], "小Pai 对话工作区");
  const expanded = elements(component.render(), element => element.type === Xiaopai)[0];
  assert.equal(expanded.type, before.type); assert.equal(expanded.key, before.key);
  assert.equal(expanded.props.initialRunId, "same-run"); assert.equal(expanded.props.categoryId, before.props.categoryId);
  elements(component.render(), element => element.props?.["aria-label"] === "缩回小Pai 工作栏")[0].props.onClick();
  assert.equal(component.render().props["aria-label"], "小Pai 工作栏");
  assert.equal(elements(component.render(), element => element.type === Xiaopai)[0].key, before.key);
});

test("明确续接仍打开同Session的具体Run，更新会话列表不会清除已读child结果", async () => {
  const calls = []; let child = false;
  const component = session({ ...props, api: async (path, body) => {
    calls.push({ path, body });
    if (path.includes("/events")) return { items: [], next_cursor: 0 };
    return { ...run, run_id: child ? "child-run" : run.run_id, result: { summary: child ? "续接实际结果" : "原结果" } };
  } });
  elements(component.render(), e => e.type === SessionHistory)[0].props.onSelectRun(run.run_id, run.session_id); await tick();
  const before = elements(component.render(), e => e.type === SessionHistory)[0].props.refreshVersion;
  child = true;
  await elements(component.render(), e => e.type === RunContinuation)[0].props.onOpen("child-run");
  const tree = component.render(), history = elements(tree, e => e.type === SessionHistory)[0];
  assert.equal(history.props.currentSessionId, run.session_id); assert.equal(history.props.currentRunId, "child-run");
  assert.equal(history.props.refreshVersion, before + 1);
  const transcript = elements(tree, e => e.type?.name === "ConversationHistory")[0];
  const previousMaterials = transcript.props.renderMaterials(run);
  const previousCandidate = elements(previousMaterials, e => e.type?.name === "RunCandidates")[0];
  assert.equal(previousCandidate.props.runId, run.run_id);
  assert.equal(previousCandidate.props.categoryId, props.categoryId);
  assert.equal(previousCandidate.props.principalId, props.principalId);
  assert.equal(typeof previousCandidate.props.onEditMaterial, "function");
  assert.ok(elements(tree, e => e.props?.children === "续接实际结果").length);
  assert.ok(calls.every(call => call.body === undefined));
});

test("搜索或切换清理线程后，旧Run迟到详情不能恢复结果、候选或技能", async () => {
  let resolveOld;
  const component = session({ ...props, api: async () => new Promise(resolve => { resolveOld = resolve; }) });
  const history = elements(component.render(), e => e.type === SessionHistory)[0].props;
  history.onSelectRun(run.run_id, run.session_id); await tick(); history.onClearSelection();
  resolveOld({ ...run, result: { summary: "迟到的私有结果" } }); await tick();
  const tree = component.render(); assert.equal(elements(tree, e => e.props?.children === "迟到的私有结果").length, 0);
  assert.equal(elements(tree, e => e.type === RunContinuation).length, 0);
  assert.deepEqual(elements(tree, e => e.type === PaiScope)[0].props.skills, []);
});

function selectFixedSource(component, id = "11111111-1111-4111-8111-111111111111", revision = 3) {
  const picker = elements(component.render(), element => element.type === SourcePicker)[0];
  picker.props.onChange({ scope: sourcePickerScope(picker.props.scope), items: [{ artifact_id: id, expected_revision: revision, title: "固定来源名称" }] });
}
function submitNewWork(component) {
  elements(component.render(), e => e.type === "textarea")[0].props.onChange({ target: { value: "核对固定来源与版本" } });
  elements(component.render(), e => e.type === "form")[0].props.onSubmit({ preventDefault() {} });
}

test("new Run submits exactly pinned Artifact versions; next prop revision cannot silently update them", async () => {
  const calls = [], artifactId = "11111111-1111-4111-8111-111111111111";
  const component = session({ ...props, sources: [{ id: artifactId, title: "旧props来源", revision: 3, status: "active" }], api: async (path, body) => {
    calls.push({ path, body: structuredClone(body) });
    if (body) return { run_id: run.run_id };
    if (path.includes("/events")) return { items: [], next_cursor: 0 };
    return run;
  } });
  selectFixedSource(component, artifactId, 3);
  component.render({ sources: [{ id: artifactId, title: "后续Current", revision: 9, status: "active" }] });
  submitNewWork(component); await tick();
  assert.equal(calls[0].path, "v1/agent-runs"); assert.deepEqual(calls[0].body.sources, [{ artifact_id: artifactId, expected_revision: 3 }]);
  assert.equal(calls[0].body.product_id, null); assert.equal("title" in calls[0].body.sources[0], false);
  const actual = elements(component.render(), e => e.type === RunSourceBindings)[0].props;
  assert.equal(actual.runId, run.run_id); assert.equal(actual.sessionId, run.session_id); assert.equal(actual.scope.productId, run.product_id);
});

test("definite 409 start rejection clears pinned sources and catalog, while 503 retains exact original request", async () => {
  for (const status of [409, 503]) {
    const calls = []; const component = session({ ...props, api: async (path, body) => { calls.push({ path, body: structuredClone(body) }); throw Object.assign(Error("来源暂不可用"), { status }); } });
    selectFixedSource(component);
    const beforeKey = elements(component.render(), e => e.type === SourcePicker)[0].key;
    submitNewWork(component); await tick();
    const tree = component.render(), picker = elements(tree, e => e.type === SourcePicker)[0];
    if (status === 409) {
      assert.equal(picker.props.value, null); assert.notEqual(picker.key, beforeKey);
      assert.equal(button(tree, "重试原请求"), undefined);
      assert.ok(elements(tree, e => typeof e.props?.children === "string" && e.props.children.includes("重新核对范围并选择固定来源")).length);
    } else {
      assert.equal(picker.props.value.items[0].expected_revision, 3); assert.equal(picker.key, beforeKey);
      assert.ok(elements(tree, e => Array.isArray(e.props?.children) && e.props.children.includes("原请求携带 ")).length);
      await click(component, "重试原请求"); assert.equal(calls.length, 2); assert.deepEqual(calls[0], calls[1]);
    }
  }
});

test("restored unknown start shows original fixed product and sources without posting or borrowing the composer selection", async () => {
  const originalStorage = globalThis.localStorage;
  const product = "22222222-2222-4222-8222-222222222222", artifact = "11111111-1111-4111-8111-111111111111";
  const original = { path: "v1/agent-runs", body: { goal: "原型号的未明受理请求", idempotency_key: "original-fixed-request-key", product_id: product, sources: [{ artifact_id: artifact, expected_revision: 2 }] } };
  globalThis.localStorage = { getItem: () => JSON.stringify(original) };
  let calls = 0;
  try {
    const component = session({ ...props, productId: "33333333-3333-4333-8333-333333333333", api: async () => { calls++; throw Error("No automatic POST or GET"); } });
    component.render(); const cleanups = component.mountEffects(); await tick();
    const html = renderToStaticMarkup(React.createElement("div", {}, component.render().props.children));
    assert.ok(html.includes(product)); assert.ok(html.includes(artifact)); assert.match(html, /固定版本 2/);
    assert.match(html, /原请求携带 1 份固定来源/); assert.match(html, /不是当前输入框的选择/);
    assert.equal(elements(component.render(), e => e.type === SourcePicker)[0].props.value, null); assert.equal(calls, 0);
    cleanups.forEach(cleanup => cleanup?.());
  } finally { globalThis.localStorage = originalStorage; }
});

test("accepted new Run followed by GET403 keeps acceptance truthful and never exposes or resends the old request", async () => {
  const calls = [];
  const component = session({ ...props, api: async (path, body) => {
    calls.push({ path, body });
    if (body) return { run_id: run.run_id };
    throw Object.assign(Error("当前结果已不可读"), { status: 403 });
  } });
  selectFixedSource(component); submitNewWork(component); await tick();
  const tree = component.render();
  assert.equal(calls.filter(call => call.body).length, 1); assert.equal(button(tree, "重试原请求"), undefined);
  assert.ok(elements(tree, e => e.props?.children === "新工作已保存，实际运行资料暂不可读；不会重新提交原委派。").length);
  assert.equal(elements(tree, e => typeof e.props?.children === "string" && e.props.children.includes("原新工作请求已被明确拒绝")).length, 0);
  assert.equal(elements(tree, e => e.type === SourcePicker)[0].props.value, null);
  assert.equal(elements(tree, e => e.type === RunSourceBindings).length, 0);
});

test("file upload stays scoped to the new-work composer and does not add files to Run start or continuation payloads", async () => {
  const calls = [], component = session({ ...props, proposalId: "proposal", api: async (path, body) => {
    calls.push({ path, body }); if (body) return { run_id: run.run_id };
    if (path.includes("/events")) return { items: [], next_cursor: 0 }; return { ...run, proposal_id: "proposal" };
  } });
  const uploader = elements(component.render(), e => e.type === FileUpload)[0].props;
  assert.deepEqual(uploader.scope, { principalId: props.principalId, categoryId: props.categoryId, productId: null, proposalId: "proposal" });
  assert.equal(uploader.onPendingChange, undefined); assert.equal(uploader.disabled, false);
  submitNewWork(component); await tick(); assert.deepEqual(calls[0].body.sources, []); assert.equal("content_base64" in calls[0].body, false);
  const continuation = elements(component.render(), e => e.type === RunContinuation)[0]; assert.equal(continuation.props.files, undefined);
});

test("manual methods stay pinned across an unknown start and exact original retry", async () => {
  const calls = [], component = session({ ...props, api: async (path, body) => {
    calls.push({ path, body: structuredClone(body) }); throw Object.assign(Error("回传丢失"), { status: 503 });
  } });
  const chosen = [{ key: "gap_check", version: "0.2.0-draft", digest: "a".repeat(64) }];
  elements(component.render(), e => e.type === SkillPicker)[0].props.onChange(chosen);
  submitNewWork(component); await tick();
  assert.deepEqual(calls[0].body.requested_skills, chosen);
  assert.equal(elements(component.render(), e => e.type === SkillPicker)[0].props.disabled, true);
  await click(component, "重试原请求");
  assert.deepEqual(calls[1], calls[0]);
});

test("personal rail explicitly selects a project without inference, then resets on identity/page change", () => {
  const component = session({ open: true, onClose() {}, categoryId: "", categoryName: "", paiContext: null, focusRun: null,
    session: { name: "本人", principal_id: "person" }, onCreated() {} }, PaiRail);
  const choice = { categoryId: "category", categoryName: "品类", productId: "product", projectId: "project", projectName: "真实项目" };
  elements(component.render(), e => e.type === ContextPicker)[0].props.onChange(choice);
  const bound = elements(component.render(), e => e.type === Xiaopai)[0];
  assert.equal(bound.props.projectId, choice.projectId); assert.equal(bound.props.productId, choice.productId);
  assert.equal(bound.props.categoryId, choice.categoryId); assert.equal(bound.props.initialRunId, undefined);
  component.render({ session: { name: "另一人", principal_id: "peer" } });
  assert.equal(elements(component.render(), e => e.type === Xiaopai).length, 0);
  assert.equal(elements(component.render(), e => e.type === ContextPicker)[0].props.value, undefined);
});

test("material editor survives folding and continuation; denied reads clear it and fresh authorized reads recover", async () => {
 const {RunCandidates}=load(path.join(directory,"pai/run-candidates.tsx"));
 const {PaiMaterialWorkspace}=load(path.join(directory,"pai/material-workspace.tsx"));
 let denied=false;
 const component=session({...props,api:async(path,body)=>{
  if(body)return {run_id:run.run_id};
  if(denied)throw Object.assign(Error("权限已撤回"),{status:403});
  if(path.includes("/events"))return {items:[],next_cursor:0};return run;
 }});
 submitNewWork(component);await tick();
 const draft={event_id:"candidate-event",state:"pending",command:{operation:"category.knowledge.add",payload:{kind:"voice"}}};
 elements(component.render(),e=>e.type===RunCandidates)[0].props.onEditMaterial(draft);
 let editor=elements(component.render(),e=>e.type===PaiMaterialWorkspace)[0];assert.equal(editor.props.open,true);
 assert.equal(component.render().props["data-mobile-view"],"editor");
 editor.props.onMobileChat();assert.equal(component.render().props["data-mobile-view"],"chat");assert.equal(elements(component.render(),e=>e.type===PaiMaterialWorkspace)[0].props.open,true);
 elements(component.render(),e=>e.type?.name==="PaiMobileWorkspaceSwitch"&&e.props.view==="editor")[0].props.onClick();assert.equal(component.render().props["data-mobile-view"],"editor");
 editor.props.onContextChange(draft.event_id,{kind:"voice",title:"未保存声音",draft:{label:"人工输入"}});
 editor.props.onClose();editor=elements(component.render(),e=>e.type===PaiMaterialWorkspace)[0];assert.equal(editor.props.open,false);assert.equal(editor.key,draft.event_id);
 elements(component.render(),e=>e.type===RunCandidates)[0].props.onEditMaterial(draft);
 editor=elements(component.render(),e=>e.type===PaiMaterialWorkspace)[0];assert.equal(editor.props.open,true);
 let continuation=elements(component.render(),e=>e.type===RunContinuation)[0];assert.match(continuation.props.contextText,/人工输入/);
 await continuation.props.onOpen(run.run_id);assert.equal(elements(component.render(),e=>e.type===PaiMaterialWorkspace)[0].key,draft.event_id);
 denied=true;await click(component,"核对当前状态");assert.equal(elements(component.render(),e=>e.type===PaiMaterialWorkspace).length,0);
 denied=false;submitNewWork(component);await tick();
 elements(component.render(),e=>e.type===RunCandidates)[0].props.onEditMaterial(draft);
 assert.equal(elements(component.render(),e=>e.type===PaiMaterialWorkspace).length,1);
 continuation=elements(component.render(),e=>e.type===RunContinuation)[0];assert.doesNotMatch(continuation.props.contextText,/人工输入/);
});


test("实际回复与失败保持真实，消息和材料使用同一简洁对话表面", () => {
  const response = renderToStaticMarkup(React.createElement(PaiMessage, { from: "pai" }, React.createElement(PaiResponse, { run: { ...run, status: "completed", result: { summary: "已整理实际资料" } } })));
  assert.match(response, /已整理实际资料/);
  assert.ok(!response.includes("执行完成"));
  const failure = renderToStaticMarkup(React.createElement(PaiResponse, { run: { ...run, status: "failed", error_code: "INTERNAL_ERROR" } }));
  assert.match(failure, /没能完成回复/);
  assert.ok(!failure.includes("INTERNAL_ERROR"));
  const user = renderToStaticMarkup(React.createElement(PaiMessage, { from: "user" }, "你好"));
  assert.ok(!user.includes('>你<'));
  let opened = 0;
  const card = PaiDocumentCard({ title: "实际提案", metadata: "立项提案 · 已保存", action: "返回编辑", onOpen: () => opened++ });
  const open = elements(card, item => item.props?.["aria-label"] === "返回编辑：实际提案")[0];
  assert.ok(open); assert.equal(opened, 0); open.props.onClick(); assert.equal(opened, 1);
});


test("输入区停止只取消当前运行，不发送新消息，终态恢复普通输入", async () => {
  const calls = []; let stopped = false;
  const component = session({ ...props, api: async (path, body) => {
    calls.push({path,body});
    if (body) { assert.equal(path, "v1/agent-runs/server-run/cancel"); stopped = true; return {run_id:run.run_id}; }
    if (path.includes("/events")) return {items:[],next_cursor:0};
    return {...run,status:stopped ? "cancelled" : "running"};
  }});
  elements(component.render(),e=>e.type===SessionHistory)[0].props.onSelectRun(run.run_id,run.session_id); await tick();
  assert.equal(button(component.render(), "停止后续执行"), undefined);
  const continuation = elements(component.render(),e=>e.type===RunContinuation)[0];
  continuation.props.onStop(); continuation.props.onStop(); await tick();
  assert.equal(calls.filter(call=>call.body).length,1);
  assert.deepEqual(calls.find(call=>call.body).body,{});
  assert.equal(elements(component.render(),e=>e.type===RunContinuation)[0].props.onStop,undefined);
  assert.equal(elements(component.render(),e=>e.type===PaiScope)[0].props.onBackground,undefined);
});


test("only completed server-grounded general replies show the lookup note", () => {
  for (const summary of ["你好", "段落一" + "字".repeat(410) + "\n\n段落二"]) {
    const result = { summary, result: { assistant: { lookup: "not_run" } } };
    const render = status => renderToStaticMarkup(React.createElement(PaiResponse, { run: { status, reverted: false, result } }));
    assert.ok(render("completed").includes("未查公司资料"));
    assert.equal(render("partial").includes("未查公司资料"), false);
  }
  const html = renderToStaticMarkup(React.createElement(PaiResponse, { run: { status: "completed", reverted: false, result: { summary: "有业务读取" } } }));
  assert.equal(html.includes("未查公司资料"), false);
});


test("关联引用保留固定版本并只打开服务器当前对象路径，不接受任意链接或混合目标", () => {
  const id = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";
  const params = new URLSearchParams({ area: "cockpit", category: id, product: id, project: id, projectView: "issues", panel: "quality", build: id, issue: id });
  const href = `/?${params}`;
  assert.equal(sourceObjectHref(href), href);
  const fieldParams = new URLSearchParams({ area: "cockpit", category: id, product: id, project: id, projectView: "feedback", panel: "field", feedback: id });
  const fieldHref = `/?${fieldParams}`;
  assert.equal(sourceObjectHref(fieldHref), fieldHref);
  assert.equal(sourceObjectHref(fieldHref + "&change=" + id), null);
  assert.equal(sourceObjectHref(fieldHref.replace("&feedback=" + id, "")), null);
  const fieldHtml = renderToStaticMarkup(React.createElement(AnswerSources, { answer: { lookup: "cited", sources: [{ citation_id: id, title: "现场反馈固定v1", source_revision: 1, quote: "客户报告", relation: { type: "field_response" }, object_url: fieldHref, object_label: "查看当前现场反馈" }] } }));
  assert.match(fieldHtml, /此反馈的独立跟进/);
  assert.match(fieldHtml, /查看当前现场反馈/);
  const source = { citation_id: id, title: "固定问题 v2", source_revision: 2, quote: "原登记结论", currentness: "history", relation: { type: "change_issue" }, object_url: href, object_label: "查看当前问题" };
  const html = renderToStaticMarkup(React.createElement(AnswerSources, { answer: { lookup: "cited", sources: [source] } }));
  assert.match(html, /显式关联 · 变更依据中的问题/);
  assert.match(html, /原登记结论/);
  assert.match(html, /历史版本/);
  assert.match(html, /查看当前问题/);
  assert.match(html, /本回答保留引用的固定版本/);
  for (const invalid of ["javascript:alert(1)", "https://example.com/?" + params, "/?" + params + "&issue=" + id, "/?" + params + "&run=" + id, "/?" + params + "&writer=someone", "/?" + params + "#x", href.replace(id, "-".repeat(36)), href.replace("quality", "unknown"), href.replace("&build=" + id, "")]) {
    assert.equal(sourceObjectHref(invalid), null);
  }
  const malformed = renderToStaticMarkup(React.createElement(AnswerSources, { answer: { lookup: "cited", sources: [{ ...source, relation: { type: "__proto__" }, object_url: "https://example.com", object_label: {} }] } }));
  assert.doesNotMatch(malformed, /<a |显式关联/);
});
