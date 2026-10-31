import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

/* eslint-disable react-hooks/rules-of-hooks -- Direct dispatcher for the actual work-product hook. */

const directory = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.join(directory, "../../package.json"));
const ts = dependency("typescript"), React = dependency("react");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const shim = { ...React,
  useState(initial) { const state = hooks, index = state.index++; if (!(index in state.values)) state.values[index] = typeof initial === "function" ? initial() : initial; return [state.values[index], value => { state.values[index] = typeof value === "function" ? value(state.values[index]) : value; }]; },
  useRef(initial) { const state = hooks, index = state.index++; if (!(index in state.values)) state.values[index] = { current: initial }; return state.values[index]; },
  useCallback(callback, dependencies) { const state = hooks, index = state.index++, prior = state.values[index]; if (!prior || !same(prior.dependencies, dependencies)) state.values[index] = { callback, dependencies }; return state.values[index].callback; },
};
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? shim : specifier.startsWith("@/") ? load(path.join(directory, "../../..", "src", specifier.slice(2))) : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
  return loaded.exports;
}
const { useWorkProducts } = load(path.join(directory, "use-work-products.ts"));
const run = { run_id: "r1", status: "completed", result: { summary: "真实回复" } };
const product = { id: "p1", root_id: "p1", session_id: "s1", run_id: "r1", category_id: null, kind: "document", title: "真实方案", body: "真实回复", revision: 1, origin: "ai_draft", supersedes_id: null, created_at: "2026-10-27T00:00:00Z" };
const next = { ...product, id: "p2", revision: 2, origin: "human", supersedes_id: "p1" };
const tick = () => new Promise(resolve => setImmediate(resolve));
function session(api) {
  const state = { values: [], index: 0 }, unavailable = [];
  let current;
  function render() { state.index = 0; hooks = state; try { current = useWorkProducts(api, () => unavailable.push(true)); } finally { hooks = null; } return current; }
  return { render, unavailable, async flush() { await tick(); return render(); } };
}

test("existing results open without another write and revisions keep the AI original", async () => {
  const calls = [];
  const c = session(async (path, body) => { calls.push({ path, body }); return path.includes("from-run") ? next : { items: [product] }; });
  await c.flush(); await c.render().load("s1"); await c.flush();
  await c.render().openFromRun(run, "document"); await c.flush(); assert.equal(c.render().openProduct.id, "p1");
  assert.equal(calls.filter(call => call.path.includes("from-run")).length, 0);
  c.render().saved(next); await c.flush(); assert.equal(c.render().openProduct.id, "p2"); assert.equal(c.render().original.id, "p1");
  await c.render().load("s2"); await c.flush(); assert.equal(c.render().openProduct, null);
});

test("conflict reload opens the latest revision without another create", async () => {
  const calls = [];
  const c = session(async path => { calls.push(path); return { items: [product, next] }; });
  await c.render().load("s1"); await c.flush();
  c.render().open(product); await c.flush();
  const latest = await c.render().reload(product); await c.flush();
  assert.equal(latest.id, "p2"); assert.equal(c.render().openProduct.id, "p2");
  assert.equal(c.render().original.id, "p1");
  assert.equal(calls.filter(path => path.includes("from-run")).length, 0);
});

test("unknown create replays its request key and late completion cannot cross sessions", async () => {
  const keys = [];
  const c = session(async (path, body) => {
    if (path.includes("from-run")) { keys.push(body.request_key); if (keys.length === 1) throw Error("lost response"); return next; }
    return { items: [product] };
  });
  await c.render().load("s1"); await c.flush();
  await c.render().openFromRun({ ...run, run_id: "r2" }, "document"); await c.flush();
  await c.render().openFromRun({ ...run, run_id: "r2" }, "document"); await c.flush();
  assert.equal(keys.length, 2); assert.equal(keys[0], keys[1]);
  assert.equal(c.render().items.filter(item => item.id === next.id).length, 1);
  let complete;
  const delayed = session(async path => path.includes("from-run") ? new Promise(resolve => { complete = () => resolve(next); }) : path.includes("session_id=s2") ? { items: [{ ...product, session_id: "s2" }] } : { items: [product] });
  await delayed.render().load("s1"); await delayed.flush();
  const pending = delayed.render().openFromRun({ ...run, run_id: "r2" }, "document");
  await delayed.render().load("s2"); complete(); await pending; await delayed.flush();
  assert.equal(delayed.render().openProduct, null); assert.equal(delayed.render().items.some(item => item.id === next.id), false);
  delayed.render().saved(next); await delayed.flush(); assert.equal(delayed.render().items.some(item => item.id === next.id), false);
});

test("permission failure clears current work products", async () => {
  const c = session(async () => { throw Object.assign(Error("denied"), { status: 403 }); });
  await c.render().load("s1"); await c.flush(); assert.equal(c.unavailable.length, 1); assert.equal(c.render().items.length, 0); assert.equal(c.render().openProduct, null);
});

for (const [name, value] of [["task_result", { version: 1, format: "cases", columns: [{ key: "measures", label: "措施" }], rows: [{ cells: { measures: { status: "to_confirm", text: "待确认" } } }] }], ["comparison", { version: 1, format: "comparison", rows: [] }]]) {
  test(`${name} table creation uses the server body and later opens without another write`, async () => {
    const calls = [], table = { ...product, kind: "table", body: "| 案例 | 措施 |\n| --- | --- |\n| 原服务器结果 | 待确认 |" };
    const c = session(async (path, body) => { calls.push({ path, body }); return path.includes("from-run") ? table : { items: [] }; });
    const current = { ...run, result: { summary: "已整理结果。", result: { assistant: { [name]: value } } } };
    await c.render().load("s1"); await c.flush();
    await c.render().openFromRun(current, "table"); await c.flush();
    assert.equal(c.render().openProduct.kind, "table"); assert.equal(c.render().openProduct.body, table.body);
    const writes = calls.filter(call => call.body); assert.equal(writes.length, 1);
    assert.equal(writes[0].path, "v1/personal/work-products/from-run"); assert.equal(writes[0].body.run_id, run.run_id); assert.equal(writes[0].body.kind, "table");
    assert.equal(writes[0].body.body, undefined); assert.equal(writes[0].body.result, undefined); assert.equal(writes[0].body.sources, undefined);
    c.render().close(); await c.flush();
    await c.render().openFromRun(current, "table"); await c.flush();
    assert.equal(c.render().openProduct.id, table.id); assert.equal(calls.filter(call => call.body).length, 1);
  });
}
