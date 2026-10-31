import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript");
const React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- In-memory event dispatcher; SSR forwards hooks unchanged. */
const reactShim = { ...React,
  useState(initial) {
    if (!hooks) return React.useState(initial);
    const own = hooks, index = own.index++;
    if (!(index in own.values)) own.values[index] = typeof initial === "function" ? initial() : initial;
    return [own.values[index], value => { own.values[index] = typeof value === "function" ? value(own.values[index]) : value; }];
  },
  useRef(initial) {
    if (!hooks) return React.useRef(initial);
    const index = hooks.index++;
    if (!(index in hooks.values)) hooks.values[index] = { current: initial };
    return hooks.values[index];
  },
  useEffect(effect, dependencies) { if (!hooks) React.useEffect(effect, dependencies); else hooks.effects.push(effect); },
  useCallback(callback, dependencies) { return hooks ? callback : React.useCallback(callback, dependencies); },
};
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? reactShim
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier.endsWith(".module.css") ? { __esModule: true, default: new Proxy({}, { get: (_target, key) => String(key) }) }
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}
const { CategoryCreateForm } = load(path.join(directory, "category-create-form.tsx"));
const { SessionHistory } = load(path.join(directory, "../pai/session-history.tsx"));
const { PaiScope } = load(path.join(directory, "../pai-conversation.tsx"));
const { RunContinuation } = load(path.join(directory, "../pai/run-continuation.tsx"));
const { PersonalXiaopai } = load(path.join(directory, "personal-xiaopai.tsx"));
const { SkillPicker } = load(path.join(directory, "../pai/skill-picker.tsx"));
const { ClarificationForm, ClarificationDialog, panelVisible } = load(path.join(directory, "clarification.tsx"));
const { adoptedCategory, asCandidate, selectedInput, RequestRejected, personalApi } = load(path.join(directory, "contracts.ts"));
const candidate = { type: "category_candidate", cancel_epoch: 0, candidate_digest: "a".repeat(64),
  input: { key: "test-pump", name: "合成气泵", purpose: "公开便携充气用途", groups: {
    knowledge: [{ kind: "competitor", content: { name: "合成竞品" }, source_refs: [{ type: "snapshot", id: "snapshot-id", version: 1 }] }],
    parameters: [{ key: "pressure", name: "压力", value_type: "number" }],
    snapshot_refs: [{ call_id: "read-id", content_hash: "b".repeat(64) }],
  } }, source: { model_call_id: "model-id", skill: { key: "category-create", digest: "source-digest" } }, snapshots: [{ snapshot_id: "snapshot-id", read_call_id: "read-id" }] };
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  if (["PaiResponse", "PaiDocumentCard", "PaiComposer"].includes(tree.type?.name)) return elements(tree.type(tree.props), predicate);
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
function session(Component, props) {
  if (Component === PersonalXiaopai) props = { principalId: "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa", ...props };
  const levels = []; let lastState, cleanups = [];
  return { render() {
    let call = Component, input = props, depth = 0;
    try { for (;;) {
      const key = input.__key ?? "root";
      if (!levels[depth] || levels[depth].key !== key) levels[depth] = { values: [], index: 0, effects: [], key };
      const state = levels[depth]; hooks = state; state.index = 0; state.effects = []; lastState = state;
      const tree = call(input);
      if (!tree || typeof tree.type !== "function" || !/PersonalIdentity|ScopedPersonalXiaopai/.test(tree.type.name)) return tree;
      call = tree.type; input = { ...tree.props, __key: tree.key }; depth++;
    } } finally { hooks = null; }
  }, mountEffects() { cleanups = levels.flatMap(state => state.effects.map(effect => effect())); },
    lastEffect() { return lastState.effects.at(-1)(); }, unmount() { cleanups.forEach(cleanup => cleanup?.()); } };
}
function button(tree, label) { return elements(tree, element => (element.props?.children === label || element.props?.["aria-label"]?.startsWith(`${label}：`)) && element.props?.onClick)[0]; }
globalThis.requestAnimationFrame = callback => { callback(); return 0; };
const tick = () => new Promise(resolve => setImmediate(resolve));
async function click(component, label) { const found = button(component.render(), label); assert.ok(found, label); found.props.onClick(); await tick(); }
function check(component, index, checked = true) { elements(component.render(), element => element.type === "input" && element.props.type === "checkbox")[index].props.onChange({ target: { checked } }); }
function preview(dto) { return { payload: dto, confirmation_token: "server-token", expires_at: "2099-01-01T00:00:00+00:00", origin: dto.prepared_by_run_id ? "ai_draft" : "human", writer_id: "writer", groups: Object.fromEntries(Object.entries(dto.groups).map(([key, value]) => [key, { selected_count: value.length, available_count: value.length }])) }; }

test("rendering makes no model or write requests and preserves sealed source reading", () => {
  let calls = 0; const api = () => { calls++; throw Error("render must not call API"); };
  const output = renderToStaticMarkup(React.createElement(CategoryCreateForm, { candidate, runId: "run-id", api, onCreated() {} }));
  for (const text of [candidate.input.name, candidate.input.purpose, candidate.candidate_digest, "model-id", "source-digest", "read-id"]) assert.ok(output.includes(text), text);
  assert.equal((output.match(/type="checkbox"/g) ?? []).length, 4);
  assert.equal(output.includes("<textarea"), true);
  assert.equal(calls, 0);
  assert.ok(renderToStaticMarkup(React.createElement(PersonalXiaopai, { api, onCreated() {} })).includes("执行需要已配置的模型和运行授权"));
  assert.equal(calls, 0);
});
test("manual create previews key/name/purpose then separately confirms with server token", async () => {
  const calls = [], created = [];
  const component = session(CategoryCreateForm, { api: async (path, dto) => { calls.push({ path, dto: structuredClone(dto) }); return path.endsWith("preview") ? preview(dto) : { subject_id: "new-category" }; }, onCreated: value => created.push(value) });
  const fields = elements(component.render(), e => (e.type === "input" && !e.props.type) || e.type === "textarea");
  ["manual-key", "人工品类", "人工用途"].forEach((value, index) => fields[index].props.onChange({ target: { value } }));
  check(component, 0);
  await click(component, "查看创建预览");
  assert.equal(calls.length, 1); assert.equal(calls[0].path, "v1/categories/preview");
  assert.equal(calls[0].dto.key, "manual-key"); assert.equal(calls[0].dto.deidentified_confirmed, true);
  assert.deepEqual(calls[0].dto.groups, { knowledge: [], parameters: [], snapshot_refs: [] });
  assert.equal("confirmed" in calls[0].dto, false); assert.equal("confirmation_token" in calls[0].dto, false);
  await click(component, "本人确认并创建品类");
  assert.equal(calls[1].path, "v1/categories"); assert.equal(calls[1].dto.confirmation_token, "server-token");
  assert.equal(calls[0].dto.idempotency_key, calls[1].dto.idempotency_key);
  assert.deepEqual(created, [{ id: "new-category", name: "人工品类", purpose: "人工用途" }]);
});
test("whole-group adoption preserves sealed content, original run and digest across failed create retry", async () => {
  const calls = []; let attempts = 0;
  const component = session(CategoryCreateForm, { candidate, runId: "original-run", onCreated() {}, api: async (path, dto) => {
    calls.push({ path, dto: structuredClone(dto) });
    if (path.endsWith("preview")) return preview(dto);
    if (++attempts === 1) throw Error("lost response");
    return { subject_id: "created" };
  } });
  check(component, 1, false); check(component, 3);
  await click(component, "查看创建预览");
  const dto = calls[0].dto;
  assert.equal(dto.prepared_by_run_id, "original-run"); assert.equal(dto.candidate_digest, candidate.candidate_digest);
  assert.deepEqual(dto.groups.knowledge, candidate.input.groups.knowledge); assert.deepEqual(dto.groups.parameters, []);
  await click(component, "本人确认并创建品类");
  assert.equal(button(component.render(), "返回修改并重新预览"), undefined);
  await click(component, "使用原请求重试创建");
  assert.deepEqual(calls[1], calls[2]); assert.equal(calls.filter(call => call.path.endsWith("preview")).length, 1);
});
test("snapshot-dependent knowledge cannot survive omission of research group", () => {
  assert.throws(() => selectedInput(candidate, { knowledge: true, parameters: true, snapshot_refs: false }), /同时取消初始知识/);
  assert.deepEqual(selectedInput(candidate, { knowledge: false, parameters: true, snapshot_refs: false }).groups,
    { knowledge: [], parameters: candidate.input.groups.parameters, snapshot_refs: [] });
  for (const item of [
    { kind: "voice", source_refs: [], content: { representative_refs: [{ type: "snapshot", id: "snapshot" }] } },
    { kind: "competitor", source_refs: [], content: { prices: [{ source_ref: { type: "snapshot", id: "snapshot" } }] } },
  ]) assert.throws(() => selectedInput({ ...candidate, input: { ...candidate.input, groups: { ...candidate.input.groups, knowledge: [item] } } },
    { knowledge: true, parameters: true, snapshot_refs: false }), /同时取消初始知识/);
});
test("revoked run cannot preview and malformed events cannot become candidates", async () => {
  let writes = 0;
  const component = session(CategoryCreateForm, { candidate, runId: "run", disabled: true, api: async () => { writes++; }, onCreated() {} });
  check(component, 3); await click(component, "查看创建预览"); assert.equal(writes, 0);
  assert.equal(asCandidate({ ...candidate, candidate_digest: "client invented" }), null);
  assert.equal(asCandidate({ ...candidate, input: { ...candidate.input, groups: {} } }), null);
  assert.deepEqual(asCandidate(candidate), candidate);
});
test("definite expired confirmation allows explicit new preview; uncertain outcomes retain original request", async () => {
  const calls = [];
  const component = session(CategoryCreateForm, { candidate, runId: "run", onCreated() {}, api: async (path, dto) => {
    calls.push({ path, dto: structuredClone(dto) });
    if (path.endsWith("preview")) return preview(dto); throw new RequestRejected("确认已过期");
  } });
  check(component, 1, false); check(component, 3); await click(component, "查看创建预览"); await click(component, "本人确认并创建品类");
  await click(component, "返回修改并重新预览"); assert.ok(button(component.render(), "查看创建预览"));
  assert.equal(calls.length, 2); // No automatic preview or candidate regeneration.
  await click(component, "查看创建预览");
  assert.deepEqual(calls[0].dto.groups, calls[2].dto.groups); assert.deepEqual(calls[2].dto.groups.parameters, []);
  assert.equal(calls[2].dto.candidate_digest, candidate.candidate_digest);
  assert.notEqual(calls[0].dto.idempotency_key, calls[2].dto.idempotency_key);
});

const sessionId = "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb";
const runId = "11111111-1111-4111-8111-111111111111";
const adoption = { type: "category_adopted", proof_version: 1, run_id: runId, candidate_digest: candidate.candidate_digest,
  category_id: "22222222-2222-4222-8222-222222222222", receipt_id: "33333333-3333-4333-8333-333333333333",
  candidate_event_id: "44444444-4444-4444-8444-444444444444", input_ref: "55555555-5555-4555-8555-555555555555", cancel_epoch: 0 };
async function openHistory(component, goal = "已有个人任务", id = runId) {
  if (goal === "新的运行") id = "99999999-9999-4999-8999-999999999999";
  elements(component.render(), e => e.type === SessionHistory)[0].props.onSelectRun(id, sessionId); await tick();
}
test("refresh and reopen read actual adoption receipt and open the saved category editor beside the conversation", async () => {
  const opened = [], calls = [];
  const api = async (path, body) => {
    calls.push({ path, body }); assert.equal(body, undefined);
    if (path.includes("?page_size=50")) return { items: [{ run_id: runId, goal: "已有个人任务", status: "waiting_input" }], next_cursor: null };
    if (path.includes("/events")) return { items: [
      { sequence: 1, event: { type: "needs_input", questions: [{ id: "old-question", question: "旧问题", why: "旧原因", options: [], allow_free_text: true }] } },
      { sequence: 2, event: candidate }, { sequence: 3, event: adoption }], next_cursor: 3 };
    return { session_id: sessionId, run_id: runId, status: "waiting_input", cancel_epoch: 0, reverted: false };
  };
  for (let reopen = 0; reopen < 2; reopen++) {
    const component = session(PersonalXiaopai, { api, onCreated: value => opened.push(value) });
    await openHistory(component);
    assert.equal(elements(component.render(), e => e.type === CategoryCreateForm).length, 0);
    assert.equal(elements(component.render(), e => e.type === "legend" && e.props.children === "旧问题").length, 0);
    assert.ok(elements(component.render(), e => Array.isArray(e.props?.children) && e.props.children.includes(adoption.receipt_id)).length);
    await click(component, "刷新实际结果");
    assert.equal(elements(component.render(), e => e.type === CategoryCreateForm).length, 0);
    await click(component, "返回编辑");
    assert.ok(elements(component.render(), e => e.type?.name === "CategoryMetadataEditor" && e.props.categoryId === adoption.category_id && e.props.embedded).length);
    assert.ok(elements(component.render(), e => e.props?.["aria-label"] === "小Pai 对话线程").length);
  }
  assert.equal(opened.length, 0); assert.ok(calls.every(call => call.path.startsWith("v1/personal/agent-runs")));
});
test("an adoption from another run cannot suppress the current run candidate", async () => {
  const otherRun = "99999999-9999-4999-8999-999999999999";
  assert.equal(adoptedCategory(adoption, otherRun), null);
  const component = session(PersonalXiaopai, { onCreated() {}, api: async path => {
    if (path.includes("?page_size=50")) return { items: [{ run_id: otherRun, goal: "已有个人任务", status: "completed" }], next_cursor: null };
    if (path.includes("/events")) return { items: [{ sequence: 1, event: candidate }, { sequence: 2, event: adoption }], next_cursor: 2 };
    return { session_id: sessionId, run_id: otherRun, status: "completed", cancel_epoch: 0, reverted: false };
  } });
  await openHistory(component, "已有个人任务", otherRun);
  await click(component, "查看与编辑");
  const form = elements(component.render(), e => e.type === CategoryCreateForm)[0];
  assert.equal(form.props.runId, otherRun); assert.equal(button(component.render(), "进入已创建品类"), undefined);
});
test("committed creation awaiting signal delivery renders success and cannot submit again", async () => {
  const created = [];
  const component = session(CategoryCreateForm, { candidate, runId, onCreated: value => created.push(value), api: async (path, dto) => path.endsWith("preview")
    ? preview(dto) : { subject_id: adoption.category_id, id: adoption.receipt_id, continuation_state: "awaiting_delivery" } });
  check(component, 3); await click(component, "查看创建预览"); await click(component, "本人确认并创建品类");
  assert.equal(created[0].id, adoption.category_id); assert.equal(created[0].continuationState, "awaiting_delivery");
  assert.equal(button(component.render(), "使用原请求重试创建"), undefined);
  assert.ok(elements(component.render(), e => e.props?.role === "status")[0].props.children.includes("小 Pai 的后续通知等待派送，创建回执已保存。"));
});
test("switching away while creation is pending cannot navigate using the old run response", async () => {
  let complete; const created = [];
  const component = session(CategoryCreateForm, { candidate, runId, onCreated: value => created.push(value), api: async (path, dto) => path.endsWith("preview")
    ? preview(dto) : new Promise(resolve => { complete = resolve; }) });
  component.render(); component.mountEffects();
  check(component, 3); await click(component, "查看创建预览"); await click(component, "本人确认并创建品类");
  component.unmount(); complete({ subject_id: adoption.category_id, id: adoption.receipt_id }); await tick();
  assert.equal(created.length, 0);
});
test("personalApi preserves real HTTP status for permission cleanup", async t => {
  const before = globalThis.fetch; t.after(() => { globalThis.fetch = before; });
  for (const status of [401, 403]) {
    globalThis.fetch = async () => ({ ok: false, status, json: async () => ({ message: "synthetic denied" }) });
    await assert.rejects(personalApi("v1/synthetic"), error => { assert.equal(error.status, status); return true; });
  }
});

test("personal parent binds continuation identity and permission cleanup", async () => {
  const component = session(PersonalXiaopai, { onCreated() {}, api: async (path, body) => {
    if (body) return { run_id: "run", session_id: sessionId };
    if (path.includes("/events")) return { items: [], next_cursor: 0 };
    return { run_id: "run", session_id: sessionId, status: "completed", cancel_epoch: 0, reverted: false };
  } });
  await startPersonal(component);
  const continuation = elements(component.render(), e => e.type === RunContinuation)[0];
  assert.ok(continuation); assert.equal(continuation.props.principalId, "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa");
  assert.equal(typeof continuation.props.onUnavailable, "function");
});

test("skill utility buttons are explicit non-submit controls", () => {
  const html = renderToStaticMarkup(React.createElement(SkillPicker, { api: async () => { throw Error("not called"); }, value: [], onChange() {}, disabled: false }));
  assert.match(html, /type="button"[^>]*>清除选择/); assert.match(html, /type="button"[^>]*>刷新技能/);
});

test("personal start retries the identical request and never fans out another model call", async () => {
  const calls = []; let count = 0;
  const component = session(PersonalXiaopai, { onCreated() {}, api: async (path, body) => {
    calls.push({ path, body: structuredClone(body) });
    if (body && ++count === 1) throw Error("network failed");
    if (body) return { session_id: sessionId, run_id: "run" };
    if (path.includes("/events")) return { items: [], next_cursor: 0 };
    if (path.includes("?page_size=50")) return { items: [], next_cursor: null };
    return { session_id: sessionId, run_id: "run", status: "completed", cancel_epoch: 0, reverted: false };
  } });
  elements(component.render(), e => e.type === "textarea")[0].props.onChange({ target: { value: "合成新品类研究" } });
  elements(component.render(), e => e.type === "form")[0].props.onSubmit({ preventDefault() {} }); await tick();
  await click(component, "重试同一请求");
  assert.deepEqual(calls[0], calls[1]); assert.equal(calls.filter(call => call.body).length, 2);
  assert.ok(calls.every(call => call.path.startsWith("v1/personal/agent-runs")));
  assert.equal("category_id" in calls[0].body, false);
  assert.equal(button(component.render(), "重试同一请求"), undefined);
});
test("successful personal start followed by read failure cannot resend start", async () => {
  let writes = 0;
  const component = session(PersonalXiaopai, { onCreated() {}, api: async (_path, body) => { if (body) { writes++; return { session_id: sessionId, run_id: "run" }; } throw Error("read failed"); } });
  elements(component.render(), e => e.type === "textarea")[0].props.onChange({ target: { value: "合成新品类研究" } });
  elements(component.render(), e => e.type === "form")[0].props.onSubmit({ preventDefault() {} }); await tick();
  assert.equal(writes, 1); assert.equal(button(component.render(), "重试同一请求"), undefined);
});

test("personal skill choice is pinned to the original pending start and clears after acceptance", async () => {
  const calls = [];
  const component = session(PersonalXiaopai, { onCreated() {}, api: async (path, body) => {
    if (body) {
      calls.push(structuredClone(body));
      if (calls.length === 1) throw Error("synthetic lost response");
      return { run_id: "run", session_id: sessionId };
    }
    if (path.includes("/events")) return { items: [], next_cursor: 0 };
    return { run_id: "run", session_id: sessionId, status: "completed", cancel_epoch: 0 };
  } });
  const picker = () => elements(component.render(), e => e.type === SkillPicker)[0];
  assert.equal(picker().props.resource, "v1/personal/agent-skills");
  const choice = { key: "gap_check", version: "fixed@1", digest: "a".repeat(64) };
  picker().props.onChange([choice]);
  await startPersonal(component);
  assert.deepEqual(calls[0].requested_skills, [choice]);
  assert.equal(picker().props.disabled, true);
  await click(component, "重试同一请求");
  assert.deepEqual(calls[1], calls[0]);
  assert.equal(picker(), undefined, "A continuing conversation uses only its continuation composer");
  elements(component.render(), e => typeof e.props?.onNewConversation === "function")[0].props.onNewConversation();
  assert.deepEqual(picker().props.value, []);
});

const questions = [
  { id: "market", question: "目标市场？", why: "用于核对法规", options: [{ value: "eu", label: "欧盟" }, { value: "us", label: "美国" }],
    recommended: { value: "eu", reason: "已知用途集中在欧洲" }, depends_on: [], allow_free_text: true },
  { id: "scope", question: "研究范围？", why: "先明确范围", options: [], recommended: null, depends_on: ["market"], allow_free_text: true },
];
const visiblePanel = () => ({ isConnected: true, ownerDocument: { visibilityState: "visible", defaultView: { innerHeight: 800, innerWidth: 1200 } },
  closest: () => null, checkVisibility: () => true, getBoundingClientRect: () => ({ width: 600, height: 400, top: 0, left: 0, right: 600, bottom: 400 }) });
const dialogue = component => elements(component.render(), e => e.type === ClarificationDialog)[0];
const inlineQuestions = component => elements(component.render(), e => e.type === ClarificationForm)[0];
async function startPersonal(component) {
  elements(component.render(), e => e.type === "textarea")[0].props.onChange({ target: { value: "新品类研究" } });
  elements(component.render(), e => e.type === "form")[0].props.onSubmit({ preventDefault() {} }); await tick();
}
function capturePoll(component) {
  const original = globalThis.setInterval;
  let poll;
  globalThis.setInterval = callback => { poll = callback; return -1; };
  try { component.render(); component.lastEffect(); } finally { globalThis.setInterval = original; }
  assert.ok(poll); return async () => { poll(); await tick(); };
}
test("clarification exposes actual recommendation reasons and dependencies without selecting an answer", () => {
  const html = renderToStaticMarkup(React.createElement(ClarificationForm, { questions, answers: {}, disabled: false, prefix: "test", onAnswer() {}, onSubmit() {} }));
  for (const text of ["建议：", "欧盟", "已知用途集中在欧洲", "依赖问题：", "目标市场？", "补充答复"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes("checked="), false); assert.match(html, /<button[^>]*disabled=""/);
});
test("panel visibility excludes background, detached, hidden and offscreen panels", () => {
  assert.equal(panelVisible(null), false); const panel = visiblePanel(); assert.equal(panelVisible(panel), true);
  panel.ownerDocument.visibilityState = "hidden"; assert.equal(panelVisible(panel), false);
  panel.ownerDocument.visibilityState = "visible"; panel.isConnected = false; assert.equal(panelVisible(panel), false);
  panel.isConnected = true; panel.checkVisibility = () => false; assert.equal(panelVisible(panel), false);
  panel.checkVisibility = () => true; panel.getBoundingClientRect = () => ({ width: 600, height: 400, top: 1000, bottom: 1400, left: 0, right: 600 });
  assert.equal(panelVisible(panel), false);
});
test("only a new live visible interrupt opens; closing, repeat polls and hidden delivery preserve inline answers", async () => {
  let status = "running", events = [];
  const component = session(PersonalXiaopai, { onCreated() {}, api: async (path, body) => {
    if (body) return { session_id: sessionId, run_id: runId };
    if (path.includes("?page_size=50")) return { items: [], next_cursor: null };
    if (path.includes("/events")) return { items: events, next_cursor: events.at(-1)?.sequence ?? 0 };
    return { session_id: sessionId, run_id: runId, status, cancel_epoch: 0, reverted: false };
  } });
  const panel = visiblePanel(); component.render().props.ref.current = panel;
  await startPersonal(component); const poll = capturePoll(component);
  status = "waiting_input"; events = [{ sequence: 10, event: { type: "needs_input", questions } }]; await poll();
  assert.equal(dialogue(component).props.open, true); assert.deepEqual(inlineQuestions(component).props.answers, {});
  dialogue(component).props.onClose(); inlineQuestions(component).props.onAnswer("market", "us"); await poll();
  assert.equal(dialogue(component).props.open, false); assert.equal(inlineQuestions(component).props.answers.market, "us");
  events = [{ sequence: 11, event: { type: "needs_input", questions } }]; await poll();
  assert.equal(dialogue(component).props.open, true); assert.deepEqual(inlineQuestions(component).props.answers, {});
  panel.ownerDocument.visibilityState = "hidden"; events = [{ sequence: 12, event: { type: "needs_input", questions } }]; await poll();
  assert.equal(dialogue(component).props.open, false);
  panel.ownerDocument.visibilityState = "visible"; await poll(); assert.equal(dialogue(component).props.open, false);
  events.push({ sequence: 13, event: candidate }); await poll(); assert.equal(dialogue(component), undefined); assert.equal(inlineQuestions(component), undefined);
});
test("history and manual refresh restore unanswered questions inline without opening old dialogs", async () => {
  let sequence = 20;
  const component = session(PersonalXiaopai, { onCreated() {}, api: async path => {
    if (path.includes("?page_size=50")) return { items: [{ run_id: runId, goal: "已有个人任务", status: "waiting_input" }], next_cursor: null };
    if (path.includes("/events")) return { items: [{ sequence, event: { type: "needs_input", questions } }], next_cursor: sequence };
    return { session_id: sessionId, run_id: runId, status: "waiting_input", cancel_epoch: 0, reverted: false };
  } });
  component.render().props.ref.current = visiblePanel(); await openHistory(component);
  assert.equal(dialogue(component).props.open, false); assert.deepEqual(inlineQuestions(component).props.answers, {});
  sequence++; await click(component, "刷新实际结果"); assert.equal(dialogue(component).props.open, false);
});
test("closed dialog answers use the actual original run and preserve a failed answer request for retry", async () => {
  const requests = []; let failed = false;
  const component = session(PersonalXiaopai, { onCreated() {}, api: async (path, body) => {
    if (body) {
      requests.push({ path, body: structuredClone(body) });
      if (path.endsWith("/answers") && !failed) { failed = true; throw Error("answer response lost"); }
      return { session_id: sessionId, run_id: runId };
    }
    if (path.includes("?page_size=50")) return { items: [], next_cursor: null };
    if (path.includes("/events")) return { items: [{ sequence: 30, event: { type: "needs_input", questions } }], next_cursor: 30 };
    return { session_id: sessionId, run_id: runId, status: "waiting_input", cancel_epoch: 0, reverted: false };
  } });
  component.render().props.ref.current = visiblePanel(); await startPersonal(component);
  assert.equal(dialogue(component).props.open, true); dialogue(component).props.onClose();
  inlineQuestions(component).props.onAnswer("market", "us"); inlineQuestions(component).props.onAnswer("scope", "保留本人自由答复");
  inlineQuestions(component).props.onSubmit(); await tick(); await click(component, "重试同一请求");
  assert.deepEqual(requests[1], requests[2]); assert.equal(requests[1].path, `v1/personal/agent-runs/${runId}/answers`);
  assert.deepEqual(requests[1].body.answers, { market: "us", scope: "保留本人自由答复" });
  assert.equal(dialogue(component).props.open, false);
});
test("late poll for a previous run cannot open or replace the current run questions", async () => {
  const other = "99999999-9999-4999-8999-999999999999";
  let oldPending = false, resolveOld;
  const component = session(PersonalXiaopai, { onCreated() {}, api: async (path, body) => {
    if (body) return { session_id: sessionId, run_id: runId };
    if (path.includes("?page_size=50")) return { items: [{ run_id: other, goal: "新的运行", status: "waiting_input" }], next_cursor: null };
    if (path.includes("/events")) return { items: path.includes(other) ? [{ sequence: 1, event: { type: "needs_input", questions } }] : [], next_cursor: 1 };
    if (path.endsWith(other)) return { session_id: sessionId, run_id: other, status: "waiting_input", cancel_epoch: 0, reverted: false };
    if (oldPending) return new Promise(resolve => { resolveOld = resolve; });
    return { session_id: sessionId, run_id: runId, status: "running", cancel_epoch: 0, reverted: false };
  } });
  component.render().props.ref.current = visiblePanel(); await startPersonal(component); const poll = capturePoll(component);
  oldPending = true; await poll(); await openHistory(component, "新的运行");
  resolveOld({ run_id: runId, status: "waiting_input", cancel_epoch: 0, reverted: false }); await tick();
  assert.equal(dialogue(component).props.open, false); assert.equal(inlineQuestions(component).props.questions[0].id, "market");
  inlineQuestions(component).props.onAnswer("market", "eu"); assert.equal(inlineQuestions(component).props.answers.market, "eu");
});
test("failed run refresh hides material but restores the original confirmation token and creation key", async () => {
  let readFails = false, creates = 0;
  const requests = [], opened = [];
  const api = async (path, body) => {
    if (body) {
      requests.push({ path, body: structuredClone(body) });
      if (path.endsWith("preview")) return preview(body);
      if (++creates === 1) throw Error("creation response lost");
      return { subject_id: adoption.category_id, id: adoption.receipt_id };
    }
    if (path.includes("?page_size=50")) return { items: [{ run_id: runId, goal: "已有个人任务", status: "completed" }], next_cursor: null };
    if (readFails) throw Error("temporary read failure");
    if (path.includes("/events")) return { items: [{ sequence: 1, event: candidate }], next_cursor: 1 };
    return { session_id: sessionId, run_id: runId, status: "completed", cancel_epoch: 0, reverted: false };
  };
  const parent = session(PersonalXiaopai, { api, onCreated: value => opened.push(value) });
  await openHistory(parent);
  await click(parent, "查看与编辑");
  const original = session(CategoryCreateForm, elements(parent.render(), e => e.type === CategoryCreateForm)[0].props);
  check(original, 3); await click(original, "查看创建预览"); await click(original, "本人确认并创建品类");
  readFails = true; await click(parent, "刷新实际结果"); assert.equal(elements(parent.render(), e => e.type === CategoryCreateForm).length, 0);
  readFails = false; await click(parent, "刷新实际结果"); await click(parent, "查看与编辑");
  const restoredProps = elements(parent.render(), e => e.type === CategoryCreateForm)[0].props;
  const restored = session(CategoryCreateForm, restoredProps);
  await click(restored, "使用原请求重试创建");
  assert.equal(requests.length, 3); assert.deepEqual(requests[1], requests[2]); assert.equal(opened[0].id, adoption.category_id);
  const anotherRun = session(CategoryCreateForm, { ...restoredProps, runId: "other-run" });
  assert.equal(button(anotherRun.render(), "使用原请求重试创建"), undefined);
  assert.equal(elements(anotherRun.render(), e => e.type === "input" && e.props.type === "checkbox").at(-1).props.checked, false);
});
test("dialog dismissal returns keyboard focus to inline answering without submitting", () => {
  let closed = 0, focused = 0, prevented = 0, submitted = 0;
  const tree = ClarificationDialog({ open: true, questions, answers: {}, disabled: false,
    onAnswer() {}, onSubmit() { submitted++; }, onClose() { closed++; }, onReturnFocus() { focused++; } });
  tree.props.onOpenChange(false);
  elements(tree, e => e.props?.onCloseAutoFocus)[0].props.onCloseAutoFocus({ preventDefault() { prevented++; } });
  assert.equal(closed, 1); assert.equal(focused, 1); assert.equal(prevented, 1); assert.equal(submitted, 0);
});

test("personal background keeps the original run, issues no request and leaves later questions inline", async () => {
  let status = "running", events = [];
  const calls = [];
  const component = session(PersonalXiaopai, { onCreated() {}, api: async (path, body) => {
    calls.push({ path, body });
    if (body) return { session_id: sessionId, run_id: runId };
    if (path.includes("?page_size=50")) return { items: [{ run_id: runId, goal: "新品类研究", status }], next_cursor: null };
    if (path.includes("/events")) return { items: events, next_cursor: events.at(-1)?.sequence ?? 0 };
    return { session_id: sessionId, run_id: runId, goal: "新品类研究", status, cancel_epoch: 0, reverted: false };
  } });
  component.render().props.ref.current = visiblePanel();
  await startPersonal(component);
  const count = calls.length;
  elements(component.render(), e => e.type === PaiScope)[0].props.onBackground(); await tick();
  assert.equal(calls.length, count);
  const poll = capturePoll(component);
  status = "waiting_input"; events = [{ sequence: 1, event: { type: "needs_input", questions } }];
  await poll();
  assert.equal(dialogue(component), undefined);
  assert.equal(calls.filter(call => call.body).length, 1);
  await click(component, "返回当前工作");
  assert.equal(dialogue(component).props.open, false);
  assert.equal(inlineQuestions(component).props.questions[0].id, "market");
  assert.ok(calls.filter(call => !call.body && !call.path.includes("?page_size=50")).every(call => call.path.includes(runId)));
});


test("个人对话的输入区停止仍只取消本人当前运行", async () => {
  const writes = []; let stopped = false;
  const component = session(PersonalXiaopai, {onCreated() {}, api: async (path, body) => {
    if (body) { writes.push({path,body}); if (path.endsWith("/cancel")) stopped=true; return {session_id:sessionId,run_id:runId}; }
    if (path.includes("/events")) return {items:[],next_cursor:0};
    return {session_id:sessionId,run_id:runId,goal:"本地合成",status:stopped ? "cancelled" : "running",cancel_epoch:0,reverted:false};
  }});
  await startPersonal(component);
  const before=writes.length;
  const continuation=elements(component.render(),e=>e.type===RunContinuation)[0];
  continuation.props.onStop(); continuation.props.onStop(); await tick();
  assert.equal(writes.length,before+1);assert.equal(writes.at(-1).path,`v1/personal/agent-runs/${runId}/cancel`);
  assert.equal(elements(component.render(),e=>e.type===RunContinuation)[0].props.onStop,undefined);
});


test("category creation preset sends the current enabled skill explicitly", async t => {
  const priorDocument = globalThis.document;
  globalThis.document = { visibilityState: "visible", addEventListener() {}, removeEventListener() {} };
  t.after(() => { globalThis.document = priorDocument; });
  const calls = [], choice = { skill_key: "category_framing", skill_version: "current@1", skill_digest: "a".repeat(64), enabled: true, available: true };
  const component = session(PersonalXiaopai, { presetSkillKeys: ["category_framing"], onCreated() {}, api: async (path, body) => {
    if (path === "v1/personal/agent-skills") return { items: [choice, { ...choice, skill_key: "disabled", enabled: false }] };
    if (body) { calls.push(body); return { session_id: sessionId, run_id: "run" }; }
    if (path.includes("/events")) return { items: [], next_cursor: 0 };
    if (path.includes("?page_size=50")) return { items: [], next_cursor: null };
    return { session_id: sessionId, run_id: "run", status: "completed", cancel_epoch: 0, reverted: false };
  } });
  component.render(); component.mountEffects(); await tick();
  await startPersonal(component);
  assert.deepEqual(calls[0].requested_skills, [{ key: choice.skill_key, version: choice.skill_version, digest: choice.skill_digest }]);
  component.unmount();
});

test("unavailable preset skills do not block a personal request", async t => {
  const priorDocument = globalThis.document;
  globalThis.document = { visibilityState: "visible", addEventListener() {}, removeEventListener() {} };
  t.after(() => { globalThis.document = priorDocument; });
  const calls = [];
  const component = session(PersonalXiaopai, { presetSkillKeys: ["category_framing"], onCreated() {}, api: async (path, body) => {
    if (path === "v1/personal/agent-skills") throw Error("unavailable");
    if (body) { calls.push(body); return { session_id: sessionId, run_id: "run" }; }
    if (path.includes("/events")) return { items: [], next_cursor: 0 };
    if (path.includes("?page_size=50")) return { items: [], next_cursor: null };
    return { session_id: sessionId, run_id: "run", status: "completed", cancel_epoch: 0, reverted: false };
  } });
  component.render(); component.mountEffects(); await tick();
  await startPersonal(component);
  assert.deepEqual(calls[0].requested_skills ?? [], []);
  component.unmount();
});
