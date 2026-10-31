import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Deterministic dispatcher for real component effects and click handlers.
const directory = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.join(directory, "../../package.json"));
const ts = dependency("typescript"), React = dependency("react");
let hooks;
const same = (a, b) => a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
const shim = { ...React,
  useState(initial) { const h = hooks, i = h.index++; if (!(i in h.values)) h.values[i] = initial; return [h.values[i], value => { h.values[i] = typeof value === "function" ? value(h.values[i]) : value; }]; },
  useRef(initial) { const h = hooks, i = h.index++; if (!(i in h.values)) h.values[i] = { current: initial }; return h.values[i]; },
  useEffect(effect, deps) { const h = hooks, i = h.index++, old = h.values[i]; if (!old || !same(old.deps, deps)) { h.values[i] = { deps, cleanup: null }; h.effects.push(() => { old?.cleanup?.(); h.values[i].cleanup = effect(); }); } },
};
const filename = path.join(directory, "work-state-carry.tsx");
const loaded = new Module(filename);
const scopeFile = path.join(directory, "search-scope.tsx"), scopeModule = new Module(scopeFile);
loaded.require = name => name === "react" ? shim : name.endsWith(".css") ? { carry: "carry" } : name === "./search-scope" ? scopeModule.exports : name === "@/components/ui/button" ? { Button: "button" } : name === "@phosphor-icons/react" ? { Folder: "i", ArrowClockwise: "i" } : dependency(name);
scopeModule.require = loaded.require;
scopeModule._compile(ts.transpileModule(readFileSync(scopeFile, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, scopeFile);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
const { WorkStateCarry } = loaded.exports;
const initial = { version: "agent-work-state/v1", revision: 1, session_id: "s1", root_goal: { text: "保留未知单位" }, current_goal: { text: "继续核对" }, constraints: [{ id: "c1", text: "单位未知" }], exclusions: [], focus_objects: [], completed_count: 0, unfinished: [], notes: [], context_incomplete: false, missing: [] };
const tick = () => new Promise(resolve => setImmediate(resolve));
const text = tree => typeof tree === "string" || typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(tree.props?.children) : "";
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
function session(api) {
  const h = { values: [], index: 0, effects: [] }, unavailable = [];
  const props = { api, root: "v1/personal/agent-runs", sessionId: "s1", onUnavailable: () => unavailable.push(true) };
  let tree;
  function render() { h.index = 0; h.effects = []; hooks = h; tree = WorkStateCarry(props); hooks = null; h.effects.forEach(effect => effect()); return tree; }
  return { render, unavailable, props, async settle() { for (let i = 0; i < 5; i++) { render(); await tick(); } return render(); }, async click(label) { const button = nodes(render()).find(node => node.type === "button" && text(node.props.children) === label); assert.ok(button, label); assert.ok(!button.props.disabled, label); button.props.onClick(); await this.settle(); } };
}

test("opening reads only and explicit removal keeps the original key after a lost reply", async () => {
  const writes = [], calls = []; let state = initial;
  const c = session(async (path, body) => { calls.push({ path, body }); if (!body) return state; writes.push(structuredClone(body)); if (writes.length === 1) throw Error("response lost"); state = { ...initial, revision: 2, constraints: [] }; return state; });
  await c.settle(); assert.equal(writes.length, 0); assert.match(text(c.render()), /单位未知/);
  await c.click("移除约束"); assert.match(text(c.render()), /修改结果待核对/);
  await c.click("核对并重试原请求"); assert.equal(writes.length, 2); assert.deepEqual(writes[0], writes[1]);
  assert.equal(writes[0].expected_revision, 1); assert.equal(writes[0].action, "remove_constraint");
  assert.equal(calls.at(-1).body, undefined); assert.match(text(c.render()), /第 2 版/);
  assert.doesNotMatch(text(c.render()), /约束：单位未知/);
});

test("permission loss hides carried text and prevents stale UI responses crossing sessions", async () => {
  const c = session(async (_path, body) => { if (body) throw Object.assign(Error("denied"), { status: 403 }); return initial; });
  await c.settle(); await c.click("移除约束"); assert.equal(c.unavailable.length, 1);
  assert.doesNotMatch(text(c.render()), /约束：单位未知/);
  let finish;
  const delayed = session(async path => path.includes("/s1/") ? new Promise(resolve => { finish = resolve; }) : { ...initial, session_id: "s2", constraints: [] });
  delayed.render(); delayed.props.sessionId = "s2"; await delayed.settle(); finish(initial); await delayed.settle();
  assert.doesNotMatch(text(delayed.render()), /约束：单位未知/);
});

test("carried citation shows its fixed version and explicit exclusion uses the server citation ID", async () => {
  const writes = [];
  const value = { ...initial, citations: [{ citation_id: "server-citation", title: "气密处理依据", source_revision: 2, currentness: "history" }], citation_directory: { has_more: true } };
  const c = session(async (_path, body) => { if (!body) return value; writes.push(body); return { ...value, revision: 2 }; });
  await c.settle(); assert.equal(writes.length, 0);
  assert.match(text(c.render()), /气密处理依据 · 第 2 版 · 历史依据/);
  assert.match(text(c.render()), /更多引用可在对话中继续读取/);
  await c.click("不相关");
  assert.equal(writes[0].action, "exclude_source"); assert.equal(writes[0].item_id, "server-citation");
});

test("explicit scope edits preserve the same full choice and request key after a lost reply", async () => {
  const value = { ...initial, search_context: { kind: "project", label: "气密项目", scoped: true }, search_preferences: { scope: "same_category", include_customer_private: false } };
  const writes = []; let state = value;
  const c = session(async (_path, body) => { if (!body) return state; writes.push(structuredClone(body)); if (writes.length === 1) throw Error("response lost"); state = { ...value, revision: 2, search_preferences: body.search_preferences }; return state; });
  c.props.background = true; await c.settle(); assert.equal(writes.length, 0);
  const control = nodes(c.render()).find(node => node.type?.name === "SearchScope");
  control.props.onChange({ scope: "current", include_customer_private: false }); await c.settle();
  await c.click("核对并重试原请求");
  assert.equal(writes.length, 2); assert.deepEqual(writes[0], writes[1]);
  assert.equal(writes[0].action, "set_search_scope"); assert.equal("item_id" in writes[0], false);
  assert.deepEqual(writes[0].search_preferences, { scope: "current", include_customer_private: false });
});

test("completion rereads the same session and a late startup read cannot restore the old goal", async () => {
  const calls = [];
  const c = session((path, body) => new Promise(resolve => calls.push({ path, body, resolve })));
  c.props.refreshVersion = "run:pending";
  c.render();
  assert.equal(calls.length, 1);
  c.props.refreshVersion = "run:completed";
  c.render();
  assert.equal(calls.length, 2);
  assert.equal(calls[0].path, calls[1].path);
  calls[1].resolve({ ...initial, revision: 3, current_goal: { text: "按新资料继续核对" } });
  await c.settle();
  calls[0].resolve(initial);
  await c.settle();
  assert.match(text(c.render()), /第 3 版/);
  assert.match(text(c.render()), /当前目标：按新资料继续核对/);
  assert.doesNotMatch(text(c.render()), /当前目标：继续核对/);
  assert.ok(calls.every(call => call.body === undefined));
});

test("candidate summaries display server states and actual receipt references without creating commands", async () => {
  const calls = [], receipt = "00000000-0000-4000-8000-000000000099";
  const candidates = ["pending", "adopted", "cancelled", "unavailable"].map((state, i) => ({
    event_id: "event-" + i, run_id: "run", kind: ["domain", "category", "snapshot", "verification_preparation"][i],
    operation: "PRIVATE_INTERNAL_OPERATION", state, receipt_id: state === "adopted" ? receipt : null,
    command: { payload: "MUST_NOT_RENDER" },
  }));
  const c = session(async (path, body) => { calls.push({ path, body }); return { ...initial, candidates }; });
  await c.settle();
  const value = text(c.render());
  for (const label of ["业务草稿", "新品类", "研究快照", "复验准备", "待本人确认", "已采用", "已取消", "当前不可用", receipt]) assert.ok(value.includes(label), label);
  assert.doesNotMatch(value, /MUST_NOT_RENDER|PRIVATE_INTERNAL_OPERATION/);
  assert.ok(calls.every(call => call.body === undefined));
});

test("explicit refresh replaces a pending summary with the adopted receipt without duplicating a write", async () => {
  let state = "pending";
  const calls = [];
  const c = session(async (path, body) => {
    calls.push({ path, body });
    return { ...initial, candidates: [{ event_id: "same-event", run_id: "same-run", kind: "snapshot",
      operation: "research.snapshot.register", state, receipt_id: state === "adopted" ? "real-receipt" : null }] };
  });
  await c.settle();
  assert.match(text(c.render()), /待本人确认/);
  state = "adopted";
  await c.click("刷新携带内容");
  assert.match(text(c.render()), /已采用.*回执 real-receipt/);
  assert.doesNotMatch(text(c.render()), /待本人确认/);
  assert.ok(calls.every(call => call.body === undefined));
});

test("permission failure on a later refresh clears a stale adopted summary", async () => {
  let revoked = false;
  const c = session(async () => {
    if (revoked) throw Object.assign(Error("current permission lost"), { status: 403 });
    return { ...initial, candidates: [{ event_id: "candidate", run_id: "run", kind: "domain",
      operation: "proposal.create", state: "adopted", receipt_id: "private-old-receipt" }] };
  });
  await c.settle();
  assert.match(text(c.render()), /private-old-receipt/);
  revoked = true;
  await c.click("刷新携带内容");
  assert.doesNotMatch(text(c.render()), /private-old-receipt|已采用/);
});
