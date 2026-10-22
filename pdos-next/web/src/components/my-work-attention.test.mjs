import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Real parser, hook and components. React scheduling and transport are explicit
// substitutes; these checks establish neither browser access nor domain rights.
const directory = path.dirname(fileURLToPath(import.meta.url)), root = path.resolve(directory, "../.."), dependency = createRequire(path.join(root, "package.json"));
const ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const react = { ...React,
  useState(initial) { const own = hooks, index = own.index++; if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial; return [own.slots[index], value => { if (!own.disposed) { own.slots[index] = typeof value === "function" ? value(own.slots[index]) : value; own.dirty = true; } }]; },
  useRef(initial) { const index = hooks.index++; if (!(index in hooks.slots)) hooks.slots[index] = { current: initial }; return hooks.slots[index]; },
  useCallback(callback, deps) { const index = hooks.index++; if (!same(hooks.slots[index]?.deps, deps)) hooks.slots[index] = { callback, deps }; return hooks.slots[index].callback; },
  useEffect(effect, deps) { const own = hooks, index = own.index++; if (!same(own.slots[index]?.deps, deps)) { const before = own.slots[index], next = { deps, cleanup: before?.cleanup }; own.slots[index] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); } },
};
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react : name === "@/components/ui/button" ? { Button: props => React.createElement("button", props) } : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(root, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { usePersonalAttention, parsePersonalAttention, personalAttentionHref } = load(path.join(root, "src/lib/personal-attention.ts"));
const { PersonalAttention, PersonalAttentionQueue } = load(path.join(directory, "my-work-attention.tsx"));
const id = number => `00000000-0000-4000-8000-${String(number).padStart(12, "0")}`, principalId = id(1), at = "2030-10-17T12:00:00Z";
function item(number = 10, queue = "receive") { return { id: `work_task:${id(number)}`, kind: "work_task", queue, source: { id: id(number), version_id: id(number + 100), revision: 2, epoch: null }, category: { id: id(2), name: "精密电机" }, product: { id: id(3), name: "当前产品" }, project: { id: id(4), name: "当前受控项目" }, title: `具名事项 ${number}`, reason: "当前原始记录指定本人接收", state: "assigned", responsible: { id: principalId, name: "当前本人" }, responsibility: "具名接收人", recorded_at: at, due_at: null, valid_until: null, blocked: null, target: "project", details: {} }; }
function page(queue = "receive", items = [item(10, queue)], next_cursor = null, total_records = items.length, actor = principalId) { return { version: "personal-attention/v1", principal_id: actor, as_of: at, queue, total_records, items, next_cursor }; }
function transport() { const calls = []; return { calls, api: (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject, done: false })) }; }
const nodes = (tree, predicate) => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(value => nodes(value, predicate)) : [...(predicate(tree) ? [tree] : []), ...nodes(tree.props?.children, predicate)];
const words = tree => typeof tree === "string" ? tree : Array.isArray(tree) ? tree.map(words).join("") : tree && typeof tree === "object" ? words(tree.props?.children) : "";
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t, input = {}, full = false) {
  const network = transport(), own = { slots: [], index: 0, effects: [], dirty: false, disposed: false };
  let props = { api: network.api, principalId, reload: 0, queue: "receive", ...input }, state, tree;
  // eslint-disable-next-line react-hooks/rules-of-hooks -- This isolated hook runner installs and flushes the test hook shim.
  function render() { own.index = 0; own.effects = []; own.dirty = false; hooks = own; try { if (full) tree = PersonalAttention(props); else { state = usePersonalAttention(props.api, props.principalId, props.reload, props.queue); tree = PersonalAttentionQueue({ queue: props.queue, state }); } } finally { hooks = null; } own.effects.forEach(effect => effect()); }
  const dispose = () => { if (!own.disposed) { own.slots.forEach(slot => slot?.cleanup?.()); own.disposed = true; } };
  render(); t.after(dispose);
  return { ...network, state: () => state, tree: () => tree, html: () => renderToStaticMarkup(tree), dispose, setProps(next) { props = { ...props, ...next }; render(); }, pending(route) { return network.calls.find(call => !call.done && (route === undefined || call.route.includes(route))); }, respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, error) { assert.ok(call); call.done = true; call.reject(error); }, async flush() { for (let number = 0; number < 9; number++) { await tick(); if (own.dirty && !own.disposed) render(); } } };
}
async function click(env, label) { const button = nodes(env.tree(), node => typeof node.props?.onClick === "function" && words(node.props.children) === label)[0]; assert.ok(button, label); assert.equal(!!button.props.disabled, false); button.props.onClick(); await env.flush(); }
async function ready(env, value = page()) { await env.flush(); env.respond(env.pending(), value); await env.flush(); }

test("typed parsing preserves nullable facts and rejects a foreign identity even for empty reads", () => {
  const value = page(); value.items[0].source = { id: id(10), version_id: null, revision: null, epoch: null };
  assert.equal(parsePersonalAttention(value, principalId, "receive").items[0].source.revision, null);
  const invalid = [page("receive", [], null, 0, id(99)), page("verify"), page(), page(), page(), page(), page()];
  invalid[2].items[0].responsible.id = id(99); invalid[3].items[0].source.revision = 0; invalid[4].items[0].id = `work_task:${id(11)}`; invalid[5].items[0].recorded_at = "2030-10-17T12:00:00"; invalid[6].items[0].details = { arbitrary: { nested: { object: { forbidden: true } } } };
  for (const sample of invalid) assert.throws(() => parsePersonalAttention(sample, principalId, "receive"), /不能显示为空或零/);
});
test("navigation uses only the actual original project or proposal, never a details-supplied href", () => {
  const value = item(); value.details = { href: "https://untrusted.invalid/execute", can_approve: true };
  assert.equal(personalAttentionHref(value), `/?area=cockpit&category=${id(2)}&project=${id(4)}`);
  value.target = "proposal"; value.product = null; value.project = null;
  assert.equal(personalAttentionHref(value), `/categories/${id(2)}/proposals/${id(10)}`);
  assert.doesNotThrow(() => parsePersonalAttention(page("receive", [value]), principalId, "receive"));
});
test("first failure stays unknown; retry can establish a truly empty queue", async t => {
  const env = environment(t); assert.match(env.html(), /数量未取得|正在读取/); await env.flush(); env.reject(env.pending(), new Error("当前资料暂不可读")); await env.flush();
  assert.match(env.html(), /注意项读取失败：当前资料暂不可读/); assert.doesNotMatch(env.html(), /共 0 条|暂无此类注意项/); assert.equal(env.state().totalRecords, null);
  await click(env, "重新读取注意项"); await ready(env, page("receive", [])); assert.match(env.html(), /共 0 条|暂无此类注意项/); assert.ok(env.calls.every(call => call.body === undefined));
});
test("subsequent page errors preserve records and exact cursor for retry", async t => {
  const env = environment(t); await ready(env, page("receive", [item()], "opaque_cursor-1", 2)); await click(env, "读取后续页"); const failed = env.pending();
  assert.equal(failed.route, "v1/personal/attention?queue=receive&page_size=20&cursor=opaque_cursor-1"); env.reject(failed, new Error("后页暂不可读")); await env.flush();
  assert.match(env.html(), /具名事项 10|后页暂不可读/); assert.equal(env.state().items.length, 1); await click(env, "重试后续页"); assert.equal(env.pending().route, failed.route);
  env.respond(env.pending(), page("receive", [item(11)], null, 2)); await env.flush(); assert.equal(env.state().items.length, 2); assert.doesNotMatch(env.html(), /后页暂不可读|读取后续页/);
});
test("duplicate records and cursor loops do not append or discard current records", async t => {
  const env = environment(t); await ready(env, page("receive", [item()], "first", 3)); await click(env, "读取后续页"); env.respond(env.pending(), page("receive", [item(11)], "first", 3)); await env.flush();
  assert.equal(env.state().items.length, 1); assert.match(env.html(), /重复游标或记录/); await click(env, "重试后续页"); env.respond(env.pending(), page("receive", [item()], "second", 3)); await env.flush();
  assert.equal(env.state().items.length, 1); await click(env, "重试后续页"); env.respond(env.pending(), page("receive", [item(11)], "second", 3)); await env.flush(); await click(env, "读取后续页"); env.respond(env.pending(), page("receive", [item(12)], "first", 3)); await env.flush(); assert.equal(env.state().items.length, 2); assert.equal(env.state().nextCursor, "second");
});
test("queue and identity changes hide old records synchronously and ignore late responses", async t => {
  const env = environment(t); await ready(env, page("receive", [item()], "next", 2)); await click(env, "读取后续页"); const old = env.pending(); env.setProps({ queue: "verify" });
  assert.equal(env.state().items.length, 0); assert.equal(env.state().totalRecords, null); await env.flush(); env.respond(old, page("receive", [item(11)], null, 2)); await env.flush(); assert.doesNotMatch(env.html(), /具名事项 10|具名事项 11/);
  const verify = env.pending("queue=verify"); env.setProps({ principalId: id(99) }); assert.equal(env.state().items.length, 0); await env.flush(); env.respond(verify, page("verify", [item(12, "verify")])); await env.flush(); assert.equal(env.state().items.length, 0);
  env.respond(env.pending("queue=verify"), page("verify", [], null, 0, id(99))); await env.flush(); assert.equal(env.state().totalRecords, 0);
});
test("transport and reload isolate their reads; unmount does not retain a late response", async t => {
  const env = environment(t); await ready(env); env.setProps({ reload: 1 }); assert.equal(env.state().items.length, 0); await env.flush(); const old = env.pending(); const replacement = transport(); env.setProps({ api: replacement.api }); assert.equal(env.state().totalRecords, null); await env.flush();
  env.respond(old, page("receive", [item(11)])); await env.flush(); assert.equal(env.state().items.length, 0); replacement.calls[0].resolve(page("receive", [item(12)])); await env.flush(); assert.equal(env.state().items[0].source.id, id(12));
  env.setProps({ reload: 2 }); await env.flush(); env.dispose(); replacement.calls[1].resolve(page("receive", [item(13)])); await env.flush(); assert.equal(env.state().items.length, 0); assert.equal(replacement.calls.length, 2);
});
test("403 on a later page clears earlier private items and requires a new initial read", async t => {
  const env = environment(t); await ready(env, page("receive", [item()], "next", 2)); await click(env, "读取后续页"); env.reject(env.pending(), Object.assign(new Error("原记录已变化，请刷新"), { status: 403 })); await env.flush();
  assert.equal(env.state().status, "error"); assert.equal(env.state().items.length, 0); assert.equal(env.state().totalRecords, null); assert.equal(env.state().nextCursor, null); assert.doesNotMatch(env.html(), /具名事项|共 0 条|暂无此类注意项/);
  await click(env, "重新读取注意项"); assert.equal(env.pending().route, "v1/personal/attention?queue=receive&page_size=20");
});
test("four groups retain per-card blocking, real source facts and actual external stages", async t => {
  const env = environment(t, {}, true); await env.flush(); assert.equal(env.calls.length, 4);
  for (const queue of ["decide", "receive", "verify", "external"]) {
    const value = item(10 + ["decide", "receive", "verify", "external"].indexOf(queue), queue);
    if (queue === "external") { value.kind = "external_handoff"; value.id = `${value.kind}:${value.source.id}`; value.source.epoch = 3; value.responsibility = "original_owner"; value.details = { coverage_count: 3, sent_state: "succeeded", accepted_state: "unknown", effective_state: "not_recorded", command_body: "不可泄露的原始内容" }; value.blocked = { code: "DELIVERY_UNKNOWN", message: "当前外部接收结果未知" }; value.valid_until = "2030-10-18T12:00:00Z"; }
    env.respond(env.pending(`queue=${queue}`), page(queue, [value]));
  }
  await env.flush(); const html = env.html();
  for (const expected of ["要我决定", "要我接收", "要我验证", "等外部回复", "当前责任人", "本人关系", "具名接收人", "来源版本 v2", "当前水位 3", "当前办理授权有效至", "原移交负责人", "待补范围 3 项", "已成功", "结果未知", "未登记", "DELIVERY_UNKNOWN", "查看原项目"]) assert.ok(html.includes(expected), expected);
  assert.equal((html.match(/aria-label=/g) ?? []).length, 4); assert.doesNotMatch(html, /不可泄露的原始内容|可审批|批准通过|独立阻塞队列/); assert.ok(env.calls.every(call => call.body === undefined));
});
