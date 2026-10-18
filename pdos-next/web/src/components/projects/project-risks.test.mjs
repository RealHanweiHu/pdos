import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Actual component event/hooks and request library; HTTP and localStorage are
// explicit substitutes. This is not browser, server-authority or PostgreSQL proof.
const directory = path.dirname(fileURLToPath(import.meta.url)), root = path.resolve(directory, "../../.."), dependency = createRequire(path.join(root, "package.json"));
const ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const react = { ...React, useState(initial) { const own = hooks, index = own.index++; if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial; return [own.slots[index], value => { if (!own.disposed) { own.slots[index] = typeof value === "function" ? value(own.slots[index]) : value; own.dirty = true; } }]; }, useRef(initial) { const index = hooks.index++; if (!(index in hooks.slots)) hooks.slots[index] = { current: initial }; return hooks.slots[index]; }, useCallback(callback, deps) { const index = hooks.index++; if (!same(hooks.slots[index]?.deps, deps)) hooks.slots[index] = { callback, deps }; return hooks.slots[index].callback; }, useEffect(effect, deps) { const own = hooks, index = own.index++; if (!same(own.slots[index]?.deps, deps)) { const old = own.slots[index], next = { deps, cleanup: old?.cleanup }; own.slots[index] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); } } };
const modules = new Map();
function load(filename) { if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) }; if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync); if (modules.has(filename)) return modules.get(filename).exports; const loaded = new Module(filename); modules.set(filename, loaded); loaded.require = name => name === "react" ? react : name === "@/components/ui/button" ? { Button: props => React.createElement("button", props) } : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(root, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name); loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename); return loaded.exports; }
const { ProjectRisks } = load(path.join(directory, "project-risks.tsx")), { riskStorageKey } = load(path.join(root, "src/lib/project-risks.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) }, source = { kind: "artifact", id: id(5), revision: 1, position: "line:1;quote_sha256:" + "a".repeat(64) }, at = "2030-10-17T12:00:00Z";
function view() { return { project: { id: scope.projectId, revision: 1, name: "实际合成项目", owner_id: id(8), visibility: "category" }, product_revision: 3, members: [{ id: scope.principalId, name: "原具名跟进人", can_write: true }], as_of: at, risks: [{ id: id(6), decision_id: id(7), title: "固定 G0 原风险", note: "原事项待内部跟进", responsible_id: scope.principalId, due_date: "2030-10-17", source: { kind: "question", id: id(9) }, state: "open", current: null, summary: null, can_record: true, blocked: null, history: [], task: { id: id(10), revision: 6, state: "completed" } }] }; }
const nodes = (tree, predicate) => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(value => nodes(value, predicate)) : [...(predicate(tree) ? [tree] : []), ...nodes(tree.props?.children, predicate)];
const words = tree => typeof tree === "string" ? tree : Array.isArray(tree) ? tree.map(words).join("") : tree && typeof tree === "object" ? words(tree.props?.children) : "";
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t, store = new Map()) {
  const previous = globalThis.localStorage, storage = { fail: false, getItem: key => store.get(key) ?? null, setItem(key, value) { if (this.fail) throw new Error("storage unavailable"); store.set(key, value); }, removeItem(key) { store.delete(key); } }; globalThis.localStorage = storage;
  const calls = [], api = (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false })); let refreshed = 0, props = { api, scope, onRefresh: () => { refreshed++; } }, current, tree;
  const dispose = () => { if (current && !current.disposed) { current.slots.forEach(slot => slot?.cleanup?.()); current.disposed = true; } };
  function render() { const element = ProjectRisks(props); if (!current || current.key !== element.key) { dispose(); current = { key: element.key, slots: [], index: 0, effects: [], dirty: false, disposed: false }; } current.index = 0; current.effects = []; current.dirty = false; hooks = current; try { tree = element.type(element.props); } finally { hooks = null; } current.effects.forEach(effect => effect()); }
  render(); t.after(() => { dispose(); globalThis.localStorage = previous; });
  return { store, storage, calls, refreshed: () => refreshed, tree: () => tree, html: () => renderToStaticMarkup(tree), dispose, setProps(next) { props = { ...props, ...next }; render(); }, pending(fragment) { return calls.find(call => !call.done && call.route.includes(fragment)); }, respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, failure) { assert.ok(call); call.done = true; call.reject(failure); }, async flush() { for (let n = 0; n < 9; n++) { await tick(); if (current.dirty && !current.disposed) render(); } } };
}
async function click(env, label) { const node = nodes(env.tree(), value => words(value.props?.children) === label && typeof value.props?.onClick === "function")[0]; assert.ok(node, label); assert.equal(!!node.props.disabled, false, label); node.props.onClick(); await env.flush(); }
async function fill(env, label, value) { const parent = nodes(env.tree(), node => node.type === "label" && words(node).startsWith(label))[0]; assert.ok(parent, label); const input = nodes(parent, node => ["input", "textarea", "select"].includes(node.type))[0]; input.props.onChange({ target: { value } }); await env.flush(); }
async function ready(env, value = view()) { env.respond(env.pending("/risks?"), value); await env.flush(); }
async function draft(env) { await click(env, "登记本条风险跟进结果"); await fill(env, "关闭跟进结果与依据", "已核对实际原件，本条内部跟进已结束"); await fill(env, "办理理由", "本人按原 G0 事项核对登记"); await fill(env, "结果依据来源 JSON", JSON.stringify([source])); }
async function prepare(env) {
  await draft(env); await click(env, "核对此次风险跟进材料"); const call = env.pending("/risks/inputs"), command = call.body, review = { before: null, after: { risk_id: command.payload.risk.id, decision_id: command.payload.risk.decision_id, revision: 1, state: "closed", summary: command.payload.summary } };
  env.respond(call, { payload: command.payload, required_source_read_set: command.source_read_set, review }); await env.flush(); const preview = env.pending("/commands/preview"); env.respond(preview, { command: { ...preview.body, payload: { ...preview.body.payload, confirmation_token: "explicit-common-confirmation-substitute" } }, confirmation_token: "explicit-common-confirmation-substitute", expires_at: "2099-01-01T00:00:00Z", review }); await env.flush();
}
function saved(c) { return { id: id(30), operation: c.operation, subject_id: id(31), subject_revision: 1, subject_type: "risk_followup", result: { id: id(31), revision: 1, status: c.payload.action === "close" ? "closed" : "open", risk_id: c.payload.risk.id, project_id: c.payload.project_id } }; }

test("risk read failure remains a failure; only an actual empty response renders empty", async t => {
  const env = environment(t); await env.flush(); env.reject(env.pending("/risks?"), new Error("读取失败")); await env.flush(); assert.match(env.html(), /风险跟进读取失败/); assert.doesNotMatch(env.html(), /尚无可读 G0 风险/);
  await click(env, "刷新风险跟进"); await ready(env, { ...view(), risks: [] }); assert.match(env.html(), /尚无可读 G0 风险/); assert.ok(env.calls.every(call => call.body === undefined));
});
test("task completion and original due date do not imply risk closure or personal commitment", async t => {
  const env = environment(t), value = view(); value.risks.push({ ...structuredClone(value.risks[0]), id: id(40), responsible_id: id(41), can_record: false }); await ready(env, value);
  assert.match(env.html(), /任务已验收/); assert.match(env.html(), /内部跟进中/); assert.match(env.html(), /原跟进期限/); assert.match(env.html(), /原跟进期限也不是个人承诺/); assert.match(env.html(), /不代表专业风险接受或放行/);
  assert.equal(nodes(env.tree(), node => words(node.props?.children) === "登记本条风险跟进结果" && typeof node.props?.onClick === "function").length, 1); assert.ok(env.calls.every(call => call.body === undefined));
});
test("unknown and blocked facts stay visible and cannot become editable open records", async t => {
  const env = environment(t), value = view(); value.risks[0] = { ...value.risks[0], state: "unknown", can_record: false, blocked: { code: "followup_unavailable", message: "原跟进资料不可读取" } }; await ready(env, value);
  assert.match(env.html(), /跟进状态未知/); assert.match(env.html(), /原跟进资料不可读取/); assert.doesNotMatch(env.html(), /尚未登记跟进结果/); assert.equal(nodes(env.tree(), node => words(node.props?.children) === "登记本条风险跟进结果" && typeof node.props?.onClick === "function").length, 0); assert.ok(env.calls.every(call => call.body === undefined));
});
test("material preparation shows explicit before/after and does not save until one confirmation", async t => {
  const env = environment(t); await ready(env); await prepare(env); assert.equal(env.calls.filter(call => call.body !== undefined).length, 2); assert.equal(env.calls.filter(call => call.route.endsWith("/commands")).length, 0); assert.match(env.html(), /登记前/); assert.match(env.html(), /登记后/); assert.match(env.html(), /内部跟进已关闭/);
  await click(env, "确认保存风险跟进"); const execute = env.pending("/commands"); assert.equal(execute.body.operation, "work.risk.followup.record"); assert.deepEqual(execute.body.payload.risk, { id: id(6), decision_id: id(7) }); assert.equal(execute.body.payload.current, null); assert.deepEqual(JSON.parse(env.store.get(riskStorageKey(scope))).pending.command, execute.body); assert.equal("due_date" in execute.body.payload, false);
  env.respond(execute, saved(execute.body)); await env.flush(); assert.equal(env.refreshed(), 1); await ready(env); assert.match(env.html(), /已保存具名风险跟进/); assert.doesNotMatch(env.html(), /本次风险跟进表|旧结果不会套用新版本/);
  await click(env, "刷新风险跟进"); await ready(env); assert.equal(env.calls.filter(call => call.route.endsWith("/commands")).length, 1);
});
test("response-loss remount makes no POST and explicit recovery replays the original body and key", async t => {
  const store = new Map(), first = environment(t, store); await ready(first); await prepare(first); await click(first, "确认保存风险跟进"); const execute = first.pending("/commands"); first.reject(execute, new Error("合成响应丢失")); await first.flush(); assert.match(first.html(), /保存结果尚待核实/); first.dispose();
  const next = environment(t, store); await ready(next); assert.ok(next.calls.every(call => call.body === undefined)); assert.match(next.html(), /风险跟进保存结果待核实/); await click(next, "按原请求核对风险跟进保存结果"); assert.deepEqual(next.pending("/commands").body, execute.body);
});
test("local persistence failure before inputs or confirmation prevents the dependent POST", async t => {
  const env = environment(t); await ready(env); await draft(env); env.storage.fail = true; const button = nodes(env.tree(), value => words(value.props?.children) === "核对此次风险跟进材料" && typeof value.props?.onClick === "function")[0]; assert.doesNotThrow(() => button.props.onClick()); await env.flush(); assert.match(env.html(), /本机保存失败/); assert.ok(env.calls.every(call => call.body === undefined));
});
test("local persistence failure at confirmation preserves the prepared request and sends no command", async t => {
  const env = environment(t); await ready(env); await prepare(env); env.storage.fail = true; const button = nodes(env.tree(), value => words(value.props?.children) === "确认保存风险跟进" && typeof value.props?.onClick === "function")[0]; assert.doesNotThrow(() => button.props.onClick()); await env.flush(); assert.match(env.html(), /本机保存失败/); assert.match(env.html(), /确认本条风险跟进登记/); assert.equal(env.calls.filter(call => call.route.endsWith("/commands")).length, 0); assert.equal(JSON.parse(env.store.get(riskStorageKey(scope))).pending.stage, "preview");
});
test("403 hides and removes local private draft and any prepared confirmation", async t => {
  const env = environment(t); await ready(env); await prepare(env); await click(env, "刷新风险跟进"); env.reject(env.pending("/risks?"), Object.assign(new Error("访问撤销"), { status: 403 })); await env.flush();
  assert.equal(env.store.has(riskStorageKey(scope)), false); assert.doesNotMatch(env.html(), /固定 G0 原风险|已核对实际原件|确认本条风险跟进登记/); assert.match(env.html(), /已清除本机私有风险跟进材料/);
});
test("scope and identity changes dispose old material callbacks without preview or save", async t => {
  const env = environment(t); await ready(env); await draft(env); await click(env, "核对此次风险跟进材料"); const input = env.pending("/risks/inputs"); env.setProps({ scope: { ...scope, projectId: id(99), principalId: id(98) } }); await env.flush(); env.respond(input, { payload: input.body.payload, required_source_read_set: input.body.source_read_set, review: {} }); await env.flush();
  assert.equal(env.calls.filter(call => call.route.endsWith("/commands/preview")).length, 0); assert.equal(env.calls.filter(call => call.route.endsWith("/commands")).length, 0); assert.doesNotMatch(env.html(), /已核对实际原件/); assert.ok(env.calls.at(-1).route.includes(`project_id=${id(99)}`));
});
test("API replacement invalidates late preview and leaves the old saved request for explicit recovery", async t => {
  const env = environment(t); await ready(env); await draft(env); await click(env, "核对此次风险跟进材料"); const input = env.pending("/risks/inputs"); env.respond(input, { payload: input.body.payload, required_source_read_set: input.body.source_read_set, review: {} }); await env.flush(); const preview = env.pending("/commands/preview");
  const newCalls = [], replacement = (route, body) => new Promise((resolve, reject) => newCalls.push({ route, body, resolve, reject })); env.setProps({ api: replacement }); await env.flush(); env.respond(preview, { command: { ...preview.body, payload: { ...preview.body.payload, confirmation_token: "explicit-common-confirmation-substitute" } }, expires_at: "2099-01-01T00:00:00Z", review: {} }); await env.flush();
  assert.doesNotMatch(env.html(), /确认本条风险跟进登记/); assert.ok(newCalls.every(call => call.body === undefined)); assert.equal(env.calls.filter(call => call.route.endsWith("/commands")).length, 0);
});
test("current followup drift disables the old draft and prepared confirmation without retargeting", async t => {
  const env = environment(t); await ready(env); await prepare(env); await click(env, "刷新风险跟进"); const actual = view(), old = actual.risks[0], entry = { id: id(50), revision: 1, action: "close", state: "closed", summary: "另一已保存记录", actor_id: scope.principalId, created_at: at, receipt_id: id(51) }; actual.risks[0] = { ...old, state: "closed", current: { id: entry.id, revision: 1 }, summary: entry.summary, history: [entry] }; await ready(env, actual);
  assert.match(env.html(), /旧结果不会套用新版本/); assert.equal(nodes(env.tree(), node => words(node.props?.children) === "确认保存风险跟进" && typeof node.props?.onClick === "function")[0].props.disabled, true); assert.equal(env.calls.filter(call => call.route.endsWith("/commands")).length, 0);
});
test("reopen is selected from the existing closed risk and retains its precise prior version", async t => {
  const env = environment(t), actual = view(), entry = { id: id(50), revision: 2, action: "close", state: "closed", summary: "此前内部结束", actor_id: scope.principalId, created_at: at, receipt_id: id(51) }; actual.risks[0] = { ...actual.risks[0], state: "closed", current: { id: entry.id, revision: 2 }, summary: entry.summary, history: [entry] }; await ready(env, actual);
  assert.match(env.html(), /风险跟进历史/); await click(env, "重开本条风险跟进"); await fill(env, "重开跟进原因与下一步", "新材料表明需继续内部跟进"); await fill(env, "办理理由", "本人核对新增原件"); await fill(env, "结果依据来源 JSON", JSON.stringify([source])); await click(env, "核对此次风险跟进材料"); const input = env.pending("/risks/inputs"); assert.equal(input.body.payload.action, "reopen"); assert.deepEqual(input.body.payload.current, { id: entry.id, revision: 2 }); assert.deepEqual(input.body.payload.risk, { id: id(6), decision_id: id(7) });
});
