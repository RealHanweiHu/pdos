import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Actual component/contract and React elements; hooks, transport, storage and
// the dialog DOM are explicit test drivers. No browser, HTTP or qualification.
const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Isolated hook dispatcher, never product implementation. */
const react = { ...React,
  useState(initial) {
    if (!hooks) return React.useState(initial);
    const own = hooks, index = own.index++;
    if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial;
    return [own.slots[index], next => { if (!own.disposed) { own.slots[index] = typeof next === "function" ? next(own.slots[index]) : next; own.dirty = true; } }];
  },
  useRef(initial) {
    if (!hooks) return React.useRef(initial);
    const index = hooks.index++;
    if (!(index in hooks.slots)) hooks.slots[index] = { current: initial };
    return hooks.slots[index];
  },
  useCallback(callback, deps) {
    if (!hooks) return React.useCallback(callback, deps);
    const index = hooks.index++;
    if (!same(hooks.slots[index]?.deps, deps)) hooks.slots[index] = { deps, callback };
    return hooks.slots[index].callback;
  },
  useEffect(effect, deps) {
    if (!hooks) return React.useEffect(effect, deps);
    const own = hooks, index = own.index++;
    if (!same(own.slots[index]?.deps, deps)) {
      const previous = own.slots[index], next = { deps, cleanup: previous?.cleanup };
      own.slots[index] = next;
      own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); });
    }
  },
};
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react
    : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2)))
    : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { ManufacturingPublication } = load(path.join(directory, "manufacturing-publication.tsx"));
const { newPublicationCommand, validPublicationCommand } = load(path.join(directory, "publication-contract.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { categoryId: id(1), principalId: id(2), projectId: id(3), product: { id: id(4), revision: 7 } };
const operation = "npi.manufacturing_baseline.publish";
const source = { artifact_id: id(8), expected_revision: 2, line: 1, quote: "合成固定原文  精确空格" };
function baseline(projectId = scope.projectId) {
  const input = { project_id: projectId, process: { id: id(6), revision: 2 }, title: "本项目固定基线", previous_id: null, expected_previous_revision: null, visibility: "category", reason: "合成固定资料", sources: [source], operations: [{ operation_key: "assemble", work_instruction: null, control_plan: null }], risk_notes: null, packaging_label_basis: null };
  return { schema_version: "pdos-manufacturing-preparation-v1", id: id(5), kind: "manufacturing_baseline", revision: 1, series_id: id(5), project_id: projectId, owner_id: scope.principalId, visibility: "category", title: input.title, status: "draft", purpose: "固定项目用途", process: input.process, operation_key: null, previous_id: null, previous_revision: null, created_at: "2026-10-17T10:00:00Z", is_current: true, source_status: "current", required_source_read_set: [{ artifact_id: source.artifact_id, expected_revision: source.expected_revision }], sources: [source], receipt_id: id(9), manufacturing_release: null, qualification: "unknown", negative_enumeration_complete: false, body: { schema_version: "pdos-manufacturing-preparation-v1", kind: "manufacturing_baseline", status: "draft", input, scope: { project_id: projectId, purpose: "固定项目用途" }, process_snapshot: { id: id(6), revision: 2, name: "固定制造配置", site: "内部合成现场", line: null, operations: [{ key: "assemble", name: "装配" }] }, document_bindings: [], gaps: [], qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false } };
}
const preparation = (projectId, versions = [baseline(projectId)]) => ({ schema_version: "pdos-manufacturing-preparation-v1", versions, has_more: false, unavailable_count: 0, qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false });
const history = (versions = [], cursor = null) => ({ schema_version: "pdos-manufacturing-publication-v1", versions, history_page: { next_cursor: cursor } });
function review(command) {
  const declaration = structuredClone(command.payload); delete declaration.approval_token;
  declaration.applicability = { site: null, lines: null, conditions: null, valid_from: null, valid_until: null, ...declaration.applicability };
  return { operation, before: null, after: { revision: (command.payload.expected_previous_revision ?? 0) + 1, status: "published", body: { declaration, baseline_snapshot: baseline(command.payload.project_id).body, process_snapshot: baseline(command.payload.project_id).body.process_snapshot, documents: [], qualification: "unknown", manufacturing_release: null } }, effect: "固定本版资料，不授制造放行", authority: { subject_id: scope.principalId, operation, purpose: command.payload.purpose, authorized: true, qualified: true, roles: ["manufacturing"], scope: { product_id: command.product_id, project_id: command.payload.project_id } }, reason: command.payload.reason, gaps: [{ code: "resource_requirements_unknown", detail: "资源要求仍未知" }], required_source_read_set: command.source_read_set };
}
function prepared(command) { return { command: { ...structuredClone(command), payload: { ...structuredClone(command.payload), approval_token: "actual-server-token-substitute-0001" } }, expires_at: null, write_tier: "T2", named_decision: true, review: review(command) }; }
const receipt = command => ({ id: id(20), operation, subject_type: "manufacturing_publication", subject_id: command?.payload.previous_id ? id(23) : id(21), subject_revision: (command?.payload.expected_previous_revision ?? 0) + 1 });
function publication(n = 21, projectId = scope.projectId, revision = 1) {
  return { schema_version: "pdos-manufacturing-publication-v1", id: id(n), revision, series_id: id(n), project_id: projectId, owner_id: scope.principalId, visibility: "category", status: "published", purpose: "固定项目用途", body: { baseline_snapshot: baseline(projectId).body, process_snapshot: baseline(projectId).body.process_snapshot, documents: [], qualification: "unknown", manufacturing_release: null }, gaps: [{ code: "unknown", detail: "固定缺项仍保留" }], baseline: { kind: "manufacturing_baseline", id: id(5), revision: 1 }, process: { id: id(6), revision: 2 }, receipt_id: id(20), created_at: "2026-10-17T11:00:00Z", is_current: true, source_status: "current", qualification: "unknown", manufacturing_release: null };
}
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
function text(tree) { return Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(tree.props?.children) : typeof tree === "string" || typeof tree === "number" ? String(tree) : ""; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function storage() {
  const values = new Map();
  return { values, writes: [], failSet: false, failRemove: false, getItem(key) { return values.get(key) ?? null; }, setItem(key, value) { if (this.failSet) throw new Error("synthetic storage unavailable"); this.writes.push({ key, value }); values.set(key, value); }, removeItem(key) { if (this.failRemove) throw new Error("synthetic storage removal unavailable"); values.delete(key); } };
}
function environment(t, options = {}) {
  const local = options.storage ?? storage(), priorStorage = Object.getOwnPropertyDescriptor(globalThis, "localStorage");
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: local });
  const calls = [], api = (route, body) => new Promise((resolve, reject) => calls.push({ route, body: body === undefined ? undefined : structuredClone(body), resolve, reject, done: false }));
  let saved = 0, props = { ...scope, api, onSaved: () => { saved += 1; }, ...options.props }, state, tree;
  const dialog = { opens: 0, closes: 0, showModal() { this.opens += 1; }, close() { this.closes += 1; } };
  const fresh = key => ({ key, slots: [], index: 0, effects: [], disposed: false, dirty: true });
  function dispose() { if (state) { state.slots.forEach(slot => slot?.cleanup?.()); state.disposed = true; } }
  function render() {
    const element = ManufacturingPublication(props);
    if (!state || state.key !== element.key || state.disposed) { dispose(); state = fresh(element.key); }
    state.index = 0; state.effects = []; state.dirty = false; hooks = state;
    try { tree = element.type(element.props); } finally { hooks = null; }
    const node = elements(tree, child => child.type === "dialog")[0];
    if (node?.props.ref) node.props.ref.current = dialog;
    state.effects.forEach(effect => effect());
  }
  render();
  t.after(() => { dispose(); if (priorStorage) Object.defineProperty(globalThis, "localStorage", priorStorage); else delete globalThis.localStorage; });
  return { calls, storage: local, dialog, saved: () => saved, tree: () => tree, html: () => renderToStaticMarkup(tree), props: () => props, key: () => `pdos-manufacturing-publication-v1:${props.categoryId}:${props.principalId}:${props.product.id}:${props.projectId ?? ""}`,
    local: () => JSON.parse(local.getItem(`pdos-manufacturing-publication-v1:${props.categoryId}:${props.principalId}:${props.product.id}:${props.projectId ?? ""}`) ?? "null"),
    setProps(next) { props = { ...props, ...next }; render(); }, unmount: dispose, remount() { dispose(); render(); },
    pending(fragment) { return calls.find(call => !call.done && call.route.includes(fragment)); },
    respond(call, value) { assert.ok(call, "expected pending transport call"); call.done = true; call.resolve(value); },
    reject(call, error) { assert.ok(call, "expected pending transport call"); call.done = true; call.reject(error); },
    async flush() { for (let i = 0; i < 7; i++) { await tick(); if (state.dirty && !state.disposed) render(); } },
  };
}
function button(env, label) { return elements(env.tree(), node => typeof node.props?.onClick === "function" && text(node.props.children) === label)[0]; }
async function click(env, label) { const found = button(env, label); assert.ok(found, label); assert.ok(!found.props.disabled, `${label} must be enabled`); found.props.onClick(); await env.flush(); }
function field(env, label) {
  const parent = elements(env.tree(), node => node.type === "label" && elements(node, child => child.type === "span" && child.props.children === label).length)[0];
  const found = elements(parent, node => ["select", "textarea"].includes(node.type))[0];
  assert.ok(found, label); return found;
}
async function change(env, label, value) {
  const found = field(env, label); assert.ok(!found.props.disabled, `${label} must be enabled`);
  found.props.onChange({ target: { value } }); await env.flush();
}
async function ready(env, { versions = [], cursor = null, baselines, projects } = {}) {
  await env.flush(); const projectId = env.props().projectId ?? "";
  env.respond(env.pending("/projects"), { items: projects ?? [{ id: projectId || scope.projectId, name: "真实上下文合成项目" }] }); await env.flush();
  const selected = projectId || field(env, "项目").props.value;
  if (selected) { env.respond(env.pending("/manufacturing-preparations?"), preparation(selected, baselines)); env.respond(env.pending("/manufacturing-publications?"), history(versions, cursor)); await env.flush(); }
}
async function selectDraft(env) { await change(env, "固定制造基线", id(5)); await change(env, "本次发布说明", "本人保留固定范围与未知项"); }
async function preview(env) {
  await click(env, "核对具名发布");
  const inputs = env.pending("/inputs"); assert.ok(inputs); assert.equal(validPublicationCommand(inputs.body), true);
  env.respond(inputs, { command: inputs.body, review: review(inputs.body) }); await env.flush();
  const call = env.pending("v1/commands/preview"); assert.ok(call);
  env.respond(call, prepared(call.body)); await env.flush();
  return env.local().pending.command;
}
const executions = env => env.calls.filter(call => call.route === "v1/commands");

test("failed initial reading stays an error and cannot become an empty successful publication list", async t => {
  const env = environment(t); await env.flush();
  env.reject(env.pending("/projects"), new Error("项目读取失败，尚未核实")); await env.flush();
  assert.match(env.html(), /项目读取失败，尚未核实/);
  assert.doesNotMatch(env.html(), /已取得第|已具名发布|尚无发布记录/);
  assert.equal(button(env, "核对具名发布").props.disabled, true);
  assert.ok(env.calls.every(call => call.body === undefined));
  await click(env, "刷新发布资料"); await ready(env);
  assert.match(env.html(), /本项目固定基线/);
});

test("actual selections and inputs produce a visible named preview; no decision POST precedes explicit confirmation", async t => {
  const env = environment(t); await ready(env); await selectDraft(env); await preview(env);
  assert.equal(env.dialog.opens, 1);
  assert.match(env.html(), /具名发布这版制造基线|资源要求仍未知|固定制造配置/);
  assert.equal(executions(env).length, 0);
  assert.equal(env.local().pending.stage, "preview");
  await click(env, "本人确认并具名发布");
  assert.equal(executions(env).length, 1);
  const sent = executions(env)[0].body;
  assert.equal(env.local().pending.stage, "execute");
  assert.deepEqual(sent, env.local().pending.command);
  assert.equal(sent.payload.approval_token, "actual-server-token-substitute-0001");
});

test("UNKNOWN preserves exact command/key/token through refresh and remount without auto POST", async t => {
  const env = environment(t); await ready(env); await selectDraft(env); await preview(env);
  await click(env, "本人确认并具名发布"); const first = executions(env)[0];
  env.reject(first, new Error("合成保存响应丢失")); await env.flush();
  const original = structuredClone(env.local());
  assert.match(env.html(), /保存结果尚未核实/);
  await click(env, "刷新发布资料"); await ready(env);
  assert.deepEqual(env.local(), original); assert.equal(executions(env).length, 1);
  env.remount(); await ready(env);
  assert.deepEqual(env.local(), original); assert.equal(executions(env).length, 1);
  assert.match(env.html(), /核对原保存请求/);
  await click(env, "核对原保存请求");
  assert.equal(executions(env).length, 2);
  assert.deepEqual(executions(env)[1].body, first.body);
});

for (const status of [401, 403]) test(`actual ${status} failure clears persisted and rendered private state`, async t => {
  const env = environment(t); await ready(env, { versions: [publication()] }); await selectDraft(env); await preview(env);
  await click(env, "本人确认并具名发布");
  env.reject(executions(env)[0], Object.assign(new Error("当前权限已失效"), { status })); await env.flush();
  assert.equal(env.storage.getItem(env.key()), null);
  assert.match(env.html(), /已清除本机私有材料/);
  assert.doesNotMatch(env.html(), /本人保留固定范围与未知项|本项目固定基线|已发布的固定版本|具名发布这版制造基线/);
  assert.equal(button(env, "核对具名发布").props.disabled, true);
});

test("known success persists its receipt and performs only readonly refresh/remount/fixed-content reads", async t => {
  const env = environment(t); await ready(env); await selectDraft(env); await preview(env); await click(env, "本人确认并具名发布");
  env.respond(executions(env)[0], receipt()); await env.flush(); await ready(env, { versions: [publication()] });
  assert.equal(env.saved(), 1); assert.equal(env.local().pending, null); assert.deepEqual(env.local().receipt, receipt());
  const writes = executions(env).length;
  env.remount(); await ready(env, { versions: [publication()] });
  await click(env, "回读固定内容"); env.respond(env.pending(`/manufacturing-publications/${id(21)}`), publication()); await env.flush();
  assert.match(env.html(), /固定发布 v1|固定缺项仍保留/);
  assert.equal(executions(env).length, writes);
  assert.ok(env.calls.slice(env.calls.findIndex(call => call.route === "v1/commands") + 1).every(call => call.body === undefined));
});

test("scope changes and unmount dispose inputs callbacks before they can preview, save or mutate the next scope", async t => {
  const env = environment(t); await ready(env); await selectDraft(env); await click(env, "核对具名发布");
  const old = env.pending("/inputs"), original = structuredClone(env.local());
  env.setProps({ projectId: id(33) }); await ready(env);
  env.respond(old, { command: old.body, review: review(old.body) }); await env.flush();
  assert.equal(env.calls.filter(call => call.route === "v1/commands/preview").length, 0);
  assert.equal(env.local(), null); assert.doesNotMatch(env.html(), /本人保留固定范围与未知项/);
  env.setProps({ projectId: scope.projectId }); await ready(env);
  assert.deepEqual(env.local(), original);
  await click(env, "继续核对原请求"); const pending = env.pending("/inputs"); env.unmount();
  env.respond(pending, { command: pending.body, review: review(pending.body) }); await env.flush();
  assert.equal(env.calls.filter(call => call.route === "v1/commands/preview").length, 0); assert.equal(executions(env).length, 0);
});

test("storage failure prevents both first request submission and irreversible named execution", async t => {
  const env = environment(t); await ready(env); await selectDraft(env);
  env.storage.failSet = true;
  assert.doesNotThrow(() => button(env, "核对具名发布").props.onClick()); await env.flush();
  assert.equal(env.calls.filter(call => call.body !== undefined).length, 0);
  assert.match(env.html(), /本机无法保存原请求/);
  env.storage.failSet = false; await preview(env);
  const original = structuredClone(env.local()); env.storage.failSet = true;
  assert.doesNotThrow(() => button(env, "本人确认并具名发布").props.onClick()); await env.flush();
  assert.equal(executions(env).length, 0); assert.deepEqual(env.local(), original);
  assert.match(text(elements(env.tree(), node => node.type === "dialog")[0]), /本机无法保存原请求/);
});

test("403 with unavailable storage deletion still clears page state, denies actions and reports retained local data honestly", async t => {
  const env = environment(t); await ready(env, { versions: [publication()] }); await selectDraft(env); await preview(env);
  await click(env, "本人确认并具名发布");
  const original = env.storage.getItem(env.key()); env.storage.failRemove = true;
  env.reject(executions(env)[0], Object.assign(new Error("合成权限失效"), { status: 403 })); await env.flush();
  assert.equal(env.storage.getItem(env.key()), original);
  assert.match(env.html(), /页面私有材料已清除|浏览器存储暂无法清理/);
  assert.doesNotMatch(env.html(), /已清除本机私有材料|本人保留固定范围与未知项|本项目固定基线|已发布的固定版本|具名发布这版制造基线/);
  assert.equal(button(env, "核对具名发布").props.disabled, true);
  assert.equal(env.saved(), 0); assert.equal(executions(env).length, 1);
});

test("storage failure when adopting inputs stops before preview and preserves the recoverable original phase", async t => {
  const env = environment(t); await ready(env); await selectDraft(env); await click(env, "核对具名发布");
  const original = structuredClone(env.local()), inputs = env.pending("/inputs");
  env.storage.failSet = true;
  env.respond(inputs, { command: inputs.body, review: review(inputs.body) }); await env.flush();
  assert.equal(env.calls.filter(call => call.route === "v1/commands/preview").length, 0);
  assert.equal(executions(env).length, 0); assert.deepEqual(env.local(), original);
  assert.match(env.html(), /原请求未能持久保留|本机无法保存原请求/);
});

for (const stage of ["preview", "execute"]) test(`late ${stage} response cannot write state or storage after a different project mounts`, async t => {
  const env = environment(t); await ready(env); await selectDraft(env);
  let late;
  if (stage === "preview") {
    await click(env, "核对具名发布"); const inputs = env.pending("/inputs");
    env.respond(inputs, { command: inputs.body, review: review(inputs.body) }); await env.flush();
    late = env.pending("v1/commands/preview");
  } else {
    await preview(env); await click(env, "本人确认并具名发布"); late = executions(env)[0];
  }
  const originalKey = env.key(), original = env.storage.getItem(originalKey);
  env.setProps({ projectId: id(34) }); await ready(env);
  env.respond(late, stage === "preview" ? prepared(late.body) : receipt()); await env.flush();
  assert.equal(env.saved(), 0); assert.equal(env.local(), null);
  assert.equal(env.storage.getItem(originalKey), original);
  assert.equal(env.dialog.opens, stage === "preview" ? 0 : 1);
  assert.doesNotMatch(env.html(), /已取得第|具名发布这版制造基线|已具名发布/);
});

test("historical paging preserves its actual project and exact original cursor, deduplicating saved versions", async t => {
  const env = environment(t), cursor = "原分页/+?=&空间"; await ready(env, { versions: [publication()], cursor });
  await click(env, "读取更早发布记录");
  const call = env.pending("history_cursor="), query = new URL(call.route, "https://example.test").searchParams;
  assert.equal(query.get("project_id"), scope.projectId); assert.equal(query.get("history_cursor"), cursor); assert.equal(call.body, undefined);
  env.respond(call, history([publication(), publication(22)], null)); await env.flush();
  assert.equal(elements(env.tree(), node => typeof node.props?.onClick === "function" && text(node.props.children) === "回读固定内容").length, 2);
  assert.equal(button(env, "读取更早发布记录"), undefined); assert.equal(executions(env).length, 0);
});

test("reading v1 then v2 of the same baseline shows each fixed publication reason without changing history", async t => {
  const first = { ...publication(21, scope.projectId, 1), is_current: false }, second = publication(22, scope.projectId, 2);
  first.body.declaration = { reason: "第一版具名发布说明" }; second.body.declaration = { reason: "第二版续接发布说明" };
  assert.deepEqual(first.body.baseline_snapshot, second.body.baseline_snapshot);
  const fixedHistory = structuredClone([first, second]), env = environment(t);
  await ready(env, { versions: [first, second] });
  for (const [index, version] of [first, second].entries()) {
    const reads = elements(env.tree(), node => typeof node.props?.onClick === "function" && text(node.props.children) === "回读固定内容");
    assert.equal(reads.length, 2); assert.equal(reads[index].props.disabled, false);
    reads[index].props.onClick(); await env.flush();
    const call = env.pending(`/manufacturing-publications/${version.id}?revision=${version.revision}`);
    assert.ok(call); assert.equal(call.body, undefined);
    env.respond(call, version); await env.flush();
    assert.ok(env.html().includes(`发布说明：${version.body.declaration.reason}`));
    assert.ok(!env.html().includes([second, first][index].body.declaration.reason));
  }
  assert.deepEqual([first, second], fixedHistory); assert.equal(executions(env).length, 0);
});

test("only the current row can start a successor, whose preview and receipt keep the exact previous version", async t => {
  const current = publication(21, scope.projectId, 3), old = { ...publication(22, scope.projectId, 2), is_current: false };
  const env = environment(t); await ready(env, { versions: [current, old] });
  assert.equal(elements(env.tree(), node => typeof node.props?.onClick === "function" && text(node.props.children) === "从此版续接").length, 1);
  await click(env, "从此版续接");
  assert.deepEqual(env.local().previous, { id: current.id, revision: 3 });
  assert.equal(field(env, "固定制造基线").props.value, current.baseline.id);
  assert.match(env.html(), /将续接固定发布 v3，生成 v4/);
  await change(env, "本次发布说明", "本人核对续接固定发布");
  const approved = await preview(env);
  assert.equal(approved.payload.previous_id, current.id); assert.equal(approved.payload.expected_previous_revision, 3);
  assert.equal(executions(env).length, 0);
  assert.equal(field(env, "项目").props.disabled, true); assert.equal(field(env, "固定制造基线").props.disabled, true);
  assert.equal(button(env, "从此版续接").props.disabled, true);
  await click(env, "本人确认并具名发布");
  assert.deepEqual(executions(env)[0].body, prepared(approved).command);
  env.respond(executions(env)[0], receipt(approved)); await env.flush();
  await ready(env, { versions: [publication(23, scope.projectId, 4), { ...current, is_current: false }] });
  assert.equal(env.local().receipt.subject_revision, 4); assert.equal(env.saved(), 1);
  assert.match(env.html(), /已取得第4版发布回执/);
  assert.match(env.html(), /已续接固定发布 v3，成功发布 v4/);
  assert.doesNotMatch(env.html(), /将续接固定发布|所选前版已不是当前发布/);
  assert.equal(button(env, "核对具名发布").props.disabled, true);
  const requests = env.calls.length, saved = structuredClone(env.local());
  button(env, "核对具名发布").props.onClick(); await env.flush();
  assert.equal(env.calls.length, requests); assert.deepEqual(env.local(), saved);
  await click(env, "从此版续接");
  assert.equal(env.local().receipt, null); assert.equal(env.local().pending, null);
  assert.deepEqual(env.local().previous, { id: id(23), revision: 4 });
  assert.match(env.html(), /将续接固定发布 v4，生成 v5/);
  assert.equal(button(env, "核对具名发布").props.disabled, false);
  await click(env, "核对具名发布");
  assert.equal(env.pending("/inputs").body.payload.previous_id, id(23));
  assert.equal(env.pending("/inputs").body.payload.expected_previous_revision, 4);
  assert.equal(executions(env).length, 1);
});

test("a successor preserves an already selected baseline and allows another fixed baseline in the same project", async t => {
  const current = publication(21, scope.projectId, 4), other = baseline();
  other.id = id(42); other.revision = 2; other.title = other.body.input.title = "本项目另一版固定基线";
  const env = environment(t); await ready(env, { versions: [current], baselines: [baseline(), other] });
  await change(env, "固定制造基线", other.id); await click(env, "从此版续接");
  assert.equal(env.local().baseline, other.id);
  const previous = structuredClone(env.local().previous);
  await change(env, "固定制造基线", id(5)); assert.deepEqual(env.local().previous, previous);
  await change(env, "固定制造基线", other.id); await change(env, "本次发布说明", "续接并固定本项目另一版基线");
  const approved = await preview(env);
  assert.deepEqual(approved.payload.baseline, { kind: "manufacturing_baseline", id: other.id, revision: other.revision });
  assert.equal(approved.payload.previous_id, current.id); assert.equal(approved.payload.expected_previous_revision, 4);
  assert.equal(executions(env).length, 0);
});

for (const fault of ["missing", "historical", "revision"]) test(`a selected predecessor becoming ${fault} cannot silently submit an initial publication`, async t => {
  const current = publication(21, scope.projectId, 3), env = environment(t);
  await ready(env, { versions: [current] }); await click(env, "从此版续接");
  await change(env, "本次发布说明", "保留精确前版，等待当前状态核对");
  const original = structuredClone(env.local());
  await click(env, "刷新发布资料");
  const changed = fault === "missing" ? [] : [{ ...current, is_current: fault !== "historical", revision: fault === "revision" ? 4 : 3 }];
  await ready(env, { versions: changed });
  assert.equal(button(env, "核对具名发布").props.disabled, true);
  assert.match(env.html(), /所选前版已不是当前发布/);
  // Invoke the actual event guard as well as checking the disabled control.
  button(env, "核对具名发布").props.onClick(); await env.flush();
  assert.deepEqual(env.local(), original); assert.equal(env.calls.filter(call => call.body !== undefined).length, 0);
});

test("changing the project clears the predecessor and the next project starts with its own initial request", async t => {
  const otherProject = id(33), projects = [{ id: scope.projectId, name: "原项目" }, { id: otherProject, name: "另一项目" }];
  const env = environment(t, { props: { projectId: undefined } }); await ready(env, { projects });
  await change(env, "项目", scope.projectId); await ready(env, { projects, versions: [publication(21, scope.projectId, 3)] });
  await click(env, "从此版续接"); await change(env, "本次发布说明", "只属原项目的续接说明");
  await change(env, "项目", otherProject); await ready(env, { projects, baselines: [baseline(otherProject)] });
  assert.equal(env.local().project, otherProject); assert.equal(env.local().previous, null);
  assert.equal(env.local().baseline, ""); assert.equal(env.local().reason, "");
  assert.doesNotMatch(env.html(), /将续接固定发布|只属原项目的续接说明/);
  await selectDraft(env); await click(env, "核对具名发布");
  const command = env.pending("/inputs").body;
  assert.equal(command.payload.project_id, otherProject); assert.equal(command.payload.previous_id, null);
  assert.equal(command.payload.expected_previous_revision, null); assert.equal(executions(env).length, 0);
});

test("successor drafts and UNKNOWN recovery preserve the predecessor and exact authorized command through remount", async t => {
  const current = publication(21, scope.projectId, 6), env = environment(t);
  await ready(env, { versions: [current] }); await click(env, "从此版续接");
  await change(env, "本次发布说明", "本人核对第七版固定内容");
  const draft = structuredClone(env.local()); env.remount(); await ready(env, { versions: [current] });
  assert.deepEqual(env.local(), draft); assert.equal(env.calls.filter(call => call.body !== undefined).length, 0);
  await preview(env); await click(env, "本人确认并具名发布");
  const first = executions(env)[0]; env.reject(first, new Error("合成续版保存响应丢失")); await env.flush();
  const original = structuredClone(env.local());
  env.remount(); await ready(env, { versions: [{ ...current, is_current: false }, publication(24, scope.projectId, 7)] });
  assert.deepEqual(env.local(), original); assert.equal(executions(env).length, 1);
  assert.equal(button(env, "从此版续接").props.disabled, true);
  assert.equal(field(env, "固定制造基线").props.disabled, true); assert.equal(field(env, "项目").props.disabled, true);
  await click(env, "核对原保存请求");
  assert.equal(executions(env).length, 2); assert.deepEqual(executions(env)[1].body, first.body);
  assert.equal(executions(env)[1].body.payload.previous_id, current.id);
  assert.equal(executions(env)[1].body.payload.expected_previous_revision, 6);
  assert.equal(executions(env)[1].body.payload.approval_token, original.pending.command.payload.approval_token);
});

function savedPending({ previous, commandPrevious = null, projectId = scope.projectId } = {}) {
  const command = newPublicationCommand(scope.categoryId, scope.product.id, scope.product.revision, baseline(projectId), "保留本人的原发布请求");
  if (commandPrevious) { command.payload.previous_id = commandPrevious.id; command.payload.expected_previous_revision = commandPrevious.revision; }
  const value = { project: projectId, baseline: id(5), reason: command.payload.reason, pending: { stage: "execute", command: prepared(command).command }, receipt: null };
  if (previous !== undefined) value.previous = previous;
  const local = storage(), key = `pdos-manufacturing-publication-v1:${scope.categoryId}:${scope.principalId}:${scope.product.id}:${scope.projectId}`;
  local.setItem(key, JSON.stringify(value)); return { local, value };
}

test("legacy initial UNKNOWN requests without a previous field recover their original key and token", async t => {
  const saved = savedPending(), env = environment(t, { storage: saved.local }); await ready(env);
  assert.equal(env.local().previous, null); assert.deepEqual(env.local().pending, saved.value.pending);
  assert.equal(executions(env).length, 0); await click(env, "核对原保存请求");
  assert.deepEqual(executions(env)[0].body, saved.value.pending.command);
  assert.equal(executions(env)[0].body.payload.previous_id, null); assert.equal(executions(env)[0].body.payload.expected_previous_revision, null);
});

for (const fault of ["legacy-successor", "id", "revision", "project"]) test(`stored ${fault} mismatch cannot be adopted as a recoverable publication request`, async t => {
  const previous = { id: id(21), revision: 3 };
  const saved = savedPending({ previous: fault === "legacy-successor" ? undefined : previous, commandPrevious: fault === "id" ? { ...previous, id: id(22) } : fault === "revision" ? { ...previous, revision: 4 } : previous, projectId: fault === "project" ? id(33) : scope.projectId });
  const env = environment(t, { storage: saved.local }); await ready(env, { versions: [publication(21, scope.projectId, 3)] });
  assert.equal(button(env, "核对原保存请求"), undefined); assert.equal(executions(env).length, 0);
  assert.equal(field(env, "固定制造基线").props.value, "");
  assert.doesNotMatch(env.html(), /将续接固定发布|保留本人的原发布请求/);
  // Rejected storage remains available for explicit investigation; no new key is made.
  assert.deepEqual(env.local(), saved.value);
});
