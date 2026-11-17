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
const filename = path.join(directory, "memory-usage.tsx");
const loaded = new Module(filename);
loaded.require = name => name === "react" ? shim : name.endsWith(".css") ? { runDetails: "details", lookupNote: "note" } : dependency(name);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
const { MemoryUsage } = loaded.exports;
const tick = () => new Promise(resolve => setImmediate(resolve));
const text = tree => typeof tree === "string" || typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(tree.props?.children) : "";
function view(api, props) {
  const h = { values: [], index: 0, effects: [] };
  function render() { h.index = 0; h.effects = []; hooks = h; const tree = MemoryUsage({ api, root: "v1/personal/agent-runs", runId: "r1", status: "completed", ...props }); hooks = null; h.effects.forEach(effect => effect()); return tree; }
  return { render, async settle() { for (let i = 0; i < 4; i++) { render(); await tick(); } return render(); } };
}
const usage = { version: "memory-usage/v1", run_id: "r1", count: 2, withheld: 1, note: "这些是你本人以往的工作记录，只作背景，不是回答依据。",
  items: [{ run_id: "e1", session_id: "s0", as_of: "2026-10-31T08:00:00+00:00", goal: "比较三家气泵供应商", scope: { kind: "category", title: "汽车充气泵" } }],
  sessions: [{ session_id: "s9" }] };

test("a finished answer shows how many memory records it used, read-only", async () => {
  const calls = [];
  const v = view(async (path, body) => { calls.push({ path, body }); return usage; });
  const value = text(await v.settle());
  assert.match(value, /用到了 2 条记忆/);
  assert.match(value, /2026-10-31 · 汽车充气泵 · 比较三家气泵供应商/);
  assert.match(value, /另外 1 个会话/); assert.match(value, /另有 1 条当前不可读/);
  assert.match(value, /不是回答依据/);
  assert.deepEqual(calls, [{ path: "v1/personal/agent-runs/r1/memory-usage", body: undefined }]);
});

test("no line when nothing was used, the run is unfinished, or the read is refused", async () => {
  assert.equal(await view(async () => ({ ...usage, count: 0, items: [], sessions: [] })).settle(), null);
  const calls = [];
  assert.equal(await view(async path => { calls.push(path); return usage; }, { status: "running" }).settle(), null);
  assert.equal(calls.length, 0);
  assert.equal(await view(async () => { throw Object.assign(Error("denied"), { status: 403 }); }).settle(), null);
  assert.equal(await view(async () => ({ ...usage, run_id: "other" })).settle(), null);
});

test("used notes are listed by zone and a purged note shows no text", async () => {
  const value = text(await view(async () => ({ ...usage, count: 4, notes: [
    { note_id: "n1", zone: "constraints", kind_label: "口径", text: "回答先给结论" },
    { note_id: "n2", zone: "aliases", kind_label: "叫法", text: "我说“气嘴”指气门嘴", changed_since: true },
    { note_id: "n3", zone: "background", deleted: true },
  ] })).settle());
  assert.match(value, /用到了 4 条记忆/);
  assert.match(value, /口径 · 回答先给结论/);
  assert.match(value, /叫法 · 我说“气嘴”指气门嘴（之后已修改）/);
  assert.match(value, /已删除，正文已清除/);
});

test("team notes a run used are listed apart from the owner's own memory", async () => {
  const team = { ...usage, count: 4, scope_notes: [
    { note_id: "t1", revision: 1, zone: "constraint", kind_label: "约定", statement: "给该客户的报告一律英文", anchor: { kind_label: "项目", title: "便携气泵" }, state: "active", changed_since: false },
    { note_id: "t2", revision: 1, zone: "background", kind_label: "关注点", statement: "评审必问跌落测试", anchor: { kind_label: "品类", title: null }, state: "withdrawn", changed_since: true },
  ] };
  const value = text(await view(async () => team).settle());
  assert.match(value, /用到了 4 条记忆/);
  assert.match(value, /团队备忘 · 约定 · 给该客户的报告一律英文（项目 便携气泵）/);
  assert.match(value, /团队备忘 · 关注点 · 评审必问跌落测试（之后已停用或撤回）/);
});
