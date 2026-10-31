import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
let hooks;
const equal = (a, b) => a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
const shim = { ...React,
  useState(initial) { const state = hooks, i = state.index++; if (!(i in state.values)) state.values[i] = typeof initial === "function" ? initial() : initial; return [state.values[i], value => { state.values[i] = typeof value === "function" ? value(state.values[i]) : value; }]; },
  useRef(initial) { const state = hooks, i = state.index++; return state.values[i] ??= { current: initial }; },
  useCallback(value, deps) { const state = hooks, i = state.index++, old = state.values[i]; if (!old || !equal(old.deps, deps)) state.values[i] = { value, deps }; return state.values[i].value; },
  useEffect(effect, deps) { const state = hooks, i = state.index++, old = state.values[i]; if (!old || !equal(old.deps, deps)) state.effects.push(() => { old?.cleanup?.(); state.values[i] = { deps, cleanup: effect() }; }); },
};
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: {} };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (!filename) throw new Error("Test module missing");
  if (modules.has(filename)) return modules.get(filename).exports;
  const value = new Module(filename); modules.set(filename, value);
  value.require = name => name === "react" ? shim : name === "next/link" ? { __esModule: true, default: "a" } : name === "@/components/ui/button" ? { Button: "button" }
    : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => "svg" })
    : name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  value._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return value.exports;
}
const { WorkFollowupAction } = load(path.join(directory, "work-followup-action.tsx"));
const { WorkFollowupCandidate } = load(path.join(directory, "work-followup-candidate.tsx"));
const { workFollowupStart, validWorkFollowupAction } = load(path.join(web, "src/lib/work-followup.ts"));
const { restoreRunStart } = load(path.join(web, "src/lib/run-start-intent.ts"));
const storage = new Map();
globalThis.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
const id = n => `${String(n).padStart(8, "0")}-1111-4111-8111-111111111111`;
const category = id(1), product = id(2), project = id(3), runId = id(4), eventId = id(5), principal = id(6), peer = id(7), taskId = id(8);
const tick = () => new Promise(resolve => setImmediate(resolve));
const text = node => typeof node === "string" || typeof node === "number" ? String(node) : Array.isArray(node) ? node.map(text).join("") : node && typeof node === "object" ? text(node.props?.children) : "";
const nodes = (node, predicate) => !node || typeof node !== "object" ? [] : Array.isArray(node) ? node.flatMap(value => nodes(value, predicate)) : [...(predicate(node) ? [node] : []), ...nodes(node.props?.children, predicate)];
function session(Component, props) {
  const states = new Map(); let tree, live;
  function expand(node, key) {
    if (!node || typeof node !== "object") return node;
    if (Array.isArray(node)) return node.map((value, i) => expand(value, `${key}.${i}`));
    if (typeof node.type === "function") {
      const identity = `${key}:${node.type.name}:${node.key ?? ""}`; live.add(identity);
      let state = states.get(identity); if (!state) { state = { values: [], index: 0, effects: [] }; states.set(identity, state); }
      state.index = 0; state.effects = []; hooks = state;
      let result; try { result = node.type(node.props); } finally { hooks = null; }
      return expand(result, identity);
    }
    return React.cloneElement(node, {}, expand(node.props?.children, `${key}.children`));
  }
  function render() { live = new Set(); tree = expand(React.createElement(Component, props), "root"); for (const [key, state] of states) if (!live.has(key)) { state.values.forEach(value => value?.cleanup?.()); states.delete(key); } return tree; }
  return {
    render, text: () => text(render()), nodes: predicate => nodes(render(), predicate),
    async settle() { for (let i = 0; i < 12; i++) { await tick(); render(); for (const state of states.values()) { const effects = state.effects; state.effects = []; effects.forEach(effect => effect()); } } return tree; },
    async click(label) { const button = nodes(render(), node => typeof node.props?.onClick === "function" && text(node.props.children) === label)[0]; assert.ok(button, label); assert.ok(!button.props.disabled, `${label} enabled`); button.props.onClick({ currentTarget: { focus() {} }, preventDefault() {} }); return this.settle(); },
    unmount() { for (const state of states.values()) state.values.forEach(value => value?.cleanup?.()); states.clear(); },
  };
}
const original = { artifact_id: id(10), expected_revision: 2 };
const source = { citation_id: id(11), source_type: "artifact", source_id: original.artifact_id, source_revision: 2, title: "资料缺口原件" };
const run = { run_id: runId, status: "completed", reverted: false, product_id: product, project_id: project, result: { result: { assistant: { sources: [source] } } } };
const payload = { project_id: project, title: "补齐测试资料", goal: "提供可核对的测试资料", reason: "按已登记原件跟进", outcomes: [{ key: "materials", text: "实际资料包；方法和判据待本人确认", required: true }], sources: [{ id: original.artifact_id, revision: 2, kind: "artifact", position: "line:1;quote_sha256:" + "a".repeat(64) }], plan_task: null, g0_open_item: null };
const command = { command_id: id(12), idempotency_key: id(13), operation: "work.task.create", category_id: category, product_id: product, expected_revision: 4, source_read_set: [original], payload };
const row = () => ({ kind: "work_followup", event_id: eventId, sequence: 1, operation: command.operation, command_id: command.command_id, idempotency_key: command.idempotency_key, state: "pending", command: structuredClone(command), receipt: null, task: null, assignment: { assignee_id: peer, recipient_id: principal } });
const view = () => ({ project: { id: project, revision: 1, owner_id: principal, name: "资料跟进项目", visibility: "category" }, product_revision: 4, members: [{ id: principal, name: "项目负责人", can_write: true }, { id: peer, name: "资料执行人", can_write: true }], tasks: [], commitments: [], updates: [], g0_open_items: [], as_of: "2026-10-29T00:00:00Z" });
function port(candidate, { lose = false } = {}) {
  const calls = [], saved = new Map(); let writes = 0, lost = false;
  const data = view();
  return { calls, data, count: () => writes, async api(route, body) {
    calls.push({ route, body: body && structuredClone(body) });
    if (route.includes("/project-work?")) return structuredClone(data);
    if (route.endsWith("/project-work/inputs")) return { payload: body.payload, required_source_read_set: body.source_read_set, review: { title: body.payload.title ?? "分派", effect: "原生项目工作材料" } };
    if (route.endsWith("/commands/preview")) return { command: { ...body, payload: { ...body.payload, confirmation_token: "native-confirmation-token-0123456789" } }, review: { assignee: "资料执行人", recipient: "项目负责人" }, expires_at: new Date(Date.now() + 60000).toISOString() };
    if (route.endsWith("/commands")) {
      if (saved.has(body.command_id)) return saved.get(body.command_id);
      writes++;
      const receipt = { id: id(20 + writes), operation: body.operation, subject_id: taskId, subject_type: "work_task", subject_revision: writes, result: {} };
      saved.set(body.command_id, receipt);
      if (body.operation === "work.task.create") {
        candidate.state = "adopted"; candidate.receipt = receipt; candidate.task = { id: taskId, revision: 1, title: payload.title, state: "proposed" };
        data.tasks = [{ id: taskId, version_id: taskId, revision: 1, title: payload.title, goal: payload.goal, outcomes: payload.outcomes, state: "proposed", owner_id: principal, assignee_id: null, recipient_id: null, plan_task: null, g0_open_item: null, sources: payload.sources, actual_start: null, submission: null, review: null, history: [] }];
        if (lose && !lost) { lost = true; throw new Error("offline fixture lost response after commit"); }
      } else {
        assert.equal(body.operation, "work.task.assign"); assert.ok(body.payload.confirmation_token);
        candidate.task = { ...candidate.task, revision: 2, state: "assigned" };
        data.tasks[0] = { ...data.tasks[0], revision: 2, state: "assigned", assignee_id: peer, recipient_id: principal };
      }
      return receipt;
    }
    throw new Error("Unexpected test request: " + route);
  } };
}

test("the answer CTA keeps discussion separate from an explicit Human original selection", async () => {
  storage.clear(); const p = port(row()), started = [];
  const props = { api: p.api, categoryId: category, principalId: principal, run, onStart: value => started.push(value) };
  const ui = session(WorkFollowupAction, props);
  try {
    await ui.settle(); assert.equal(p.calls.length, 0);
    await ui.click("准备资料跟进任务");
    let start = ui.nodes(n => n.type === "button" && text(n.props.children) === "开始准备任务")[0];
    assert.equal(start.props.disabled, true); assert.equal(started.length, 0);
    const checkboxes = ui.nodes(n => n.type === "input" && n.props.type === "checkbox");
    assert.equal(checkboxes[0].props.checked, true); assert.equal(checkboxes[1].props.checked, false);
    checkboxes[1].props.onChange({ target: { checked: true } });
    const selects = ui.nodes(n => n.type === "select"); selects[0].props.onChange({ target: { value: peer } }); selects[1].props.onChange({ target: { value: principal } });
    await ui.settle(); await ui.click("开始准备任务");
    assert.equal(started.length, 1);
    assert.deepEqual(started[0].body.work_followup_action, { project_id: project, citation_ids: [source.citation_id], assignment: { assignee_id: peer, recipient_id: principal } });
    assert.deepEqual(started[0].body.sources, [original]);
    assert.equal(started[0].body.product_id, undefined); assert.equal(started[0].body.project_id, undefined);
    assert.equal(p.calls.filter(value => value.body).length, 0);
  } finally { ui.unmount(); }
});

test("start recovery stays in the selected project and rejects date or T0 assertions", () => {
  const request = workFollowupStart(run, [source.citation_id], [original], id(40));
  assert.ok(restoreRunStart(request, undefined, project));
  assert.equal(restoreRunStart(request, undefined, id(99)), null);
  assert.equal(restoreRunStart({ ...request, body: { ...request.body, verification_action: {} } }, undefined, project), null);
  assert.equal(validWorkFollowupAction({ ...request.body.work_followup_action, due_date: "2026-11-01" }), false);
  assert.equal(validWorkFollowupAction({ ...request.body.work_followup_action, qualification: "T0" }), false);
  assert.throws(() => workFollowupStart(run, [source.citation_id], [], id(40)), /原件/);
});

test("task creation and selected-person assignment use their original independent confirmations", async () => {
  storage.clear(); const candidate = row(), p = port(candidate);
  const ui = session(WorkFollowupCandidate, { api: p.api, categoryId: category, principalId: principal, candidate, onRefresh() {} });
  try {
    await ui.settle(); assert.equal(p.count(), 0);
    assert.match(ui.text(), /方法和判据待本人确认/);
    await ui.click("核对任务材料"); assert.equal(p.count(), 0);
    assert.equal(p.calls.some(value => value.route.endsWith("/commands/preview")), false);
    await ui.click("确认创建任务"); assert.equal(p.count(), 1); assert.match(ui.text(), /任务已创建/);
    assert.deepEqual(p.calls.find(value => value.route.endsWith("/commands")).body, command);
    await ui.click("核对分派"); assert.equal(p.count(), 1);
    assert.match(ui.text(), /执行人：资料执行人；成果接收人：项目负责人/);
    assert.ok(p.calls.some(value => value.route.endsWith("/commands/preview")));
    await ui.click("确认分派"); assert.equal(p.count(), 2);
    assert.match(ui.text(), /已分派，待本人承接/);
    const assigned = p.calls.filter(value => value.route.endsWith("/commands"))[1].body;
    assert.equal(assigned.operation, "work.task.assign"); assert.equal(assigned.payload.assignee_id, peer);
    assert.equal(assigned.payload.recipient_id, principal); assert.equal(assigned.payload.promised_at, undefined);
    assert.equal(p.data.commitments.length, 0);
  } finally { ui.unmount(); }
});

test("a lost native create response retains the same request and refresh never resends", async () => {
  storage.clear(); const candidate = row(), p = port(candidate, { lose: true });
  const props = { api: p.api, categoryId: category, principalId: principal, candidate, onRefresh() {} };
  let ui = session(WorkFollowupCandidate, props);
  try {
    await ui.settle(); await ui.click("核对任务材料"); await ui.click("确认创建任务");
    assert.equal(p.count(), 1); assert.match(ui.text(), /原请求结果待核实/);
    const before = p.calls.length; ui.unmount(); ui = session(WorkFollowupCandidate, props); await ui.settle();
    assert.equal(p.calls.length, before);
    await ui.click("核对原请求"); assert.equal(p.count(), 1);
    const posts = p.calls.filter(value => value.route.endsWith("/commands"));
    assert.equal(posts.length, 2); assert.deepEqual(posts[0].body, posts[1].body);
    assert.match(ui.text(), /已取得本次创建回执/);
  } finally { ui.unmount(); }
});


test("a denied native material check hides the old draft and does not create a task", async () => {
  storage.clear(); const candidate = row(), p = port(candidate);
  const api = async (route, body) => {
    if (route.endsWith("/project-work/inputs")) throw Object.assign(new Error("source no longer readable"), { status: 403 });
    return p.api(route, body);
  };
  const ui = session(WorkFollowupCandidate, { api, categoryId: category, principalId: principal, candidate, onRefresh() {} });
  try {
    await ui.settle(); await ui.click("核对任务材料");
    assert.equal(p.count(), 0); assert.match(ui.text(), /source no longer readable/);
    assert.doesNotMatch(ui.text(), /补齐测试资料|提供可核对的测试资料/);
    assert.equal(ui.nodes(n => n.type === "button").length, 0);
  } finally { ui.unmount(); }
});
