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
const { FileUpload } = load(path.join(directory, "pai/file-upload.tsx"));
const { SourcePicker, RunSourceBindings, sourcePickerScope } = load(path.join(directory, "pai/source-picker.tsx"));
const { RunContinuation } = load(path.join(directory, "pai/run-continuation.tsx"));
const { SessionHistory } = load(path.join(directory, "pai/session-history.tsx"));
const { PaiRail } = load(path.join(directory, "pai-rail.tsx"));
const { loadedSkillFacts, PaiScope, PaiCarry, PaiPolicy } = load(path.join(directory, "pai-conversation.tsx"));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
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
      if (!tree || typeof tree.type !== "function" || !/ScopedXiaopai/.test(tree.type.name)) return tree;
      call = tree.type; input = { ...tree.props, __key: tree.key }; depth++;
    } } finally { hooks = null; }
  }, mountEffects() { return levels.flatMap(state => state.effects.map(effect => effect())); } };
}
function button(tree, label) { return elements(tree, e => e.props?.children === label && e.props.onClick)[0]; }
const tick = () => new Promise(resolve => setImmediate(resolve));
async function click(component, label) { const found = button(component.render(), label); assert.ok(found, label); found.props.onClick(); await tick(); }
const props = { productId: "product", sources: [], composeOpen: false, onComposeChange() {}, categoryId: "category", categoryName: "真实品类", principalId: "person" };
const run = { session_id: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", run_id: "server-run", goal: "核对真实资料", status: "running", product_id: "server-product", proposal_id: null, cancel_epoch: 0, reverted: false, result: {} };

test("小Pai初次呈现不调用API，实际技能记录才生成chips", () => {
  const api = () => { throw Error("Rendering cannot fetch or execute"); };
  const html = renderToStaticMarkup(React.createElement(Xiaopai, { ...props, api }));
  for (const text of ["真实品类", "本次发送携带什么", "开始后按实际加载记录显示", "自动 / 一次确认 / 具名决定"]) assert.ok(html.includes(text), text);
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
  await click(component, "转后台继续"); assert.equal(closed, 1); assert.equal(calls.length, before);
  assert.ok(button(component.render(), "转后台继续")); // Rail closure preserves the mounted thread and confirmation state.
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
