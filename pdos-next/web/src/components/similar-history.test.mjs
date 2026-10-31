import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Executes the actual card component's hooks and user controls. Browser layout,
// HTTP and database authority are deliberately left to the shared checkpoint.
const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json"));
const ts = dependency("typescript"), React = dependency("react");
let hooks;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const react = { ...React,
  useState(initial) { const own = hooks, index = own.index++; if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial; return [own.slots[index], value => { own.slots[index] = typeof value === "function" ? value(own.slots[index]) : value; own.dirty = true; }]; },
  useRef(initial) { const own = hooks, index = own.index++; return own.slots[index] ??= { current: initial }; },
  useContext() { return hooks.openPai; },
  useEffect(effect, deps) { const own = hooks, index = own.index++, old = own.slots[index]; if (!same(old?.deps, deps)) { own.slots[index] = { deps }; own.effects.push(() => { old?.cleanup?.(); own.slots[index].cleanup = effect(); }); } },
};
function compile(relative, require) {
  const filename = path.join(directory, relative), mod = new Module(filename); mod.require = require;
  mod._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return mod.exports;
}
const values = compile("../lib/similar-history.ts", dependency);
const { SimilarHistory } = compile("similar-history.tsx", name => name === "react" ? react : name === "@/lib/similar-history" ? values : name === "./similar-history-pai" ? { SimilarHistoryPaiContext: {} } : name.endsWith(".css") ? { __esModule: true, default: {} } : name === "./ui/button" ? { Button: "button" } : name === "@phosphor-icons/react" ? { Sparkle: "i", ArrowSquareOut: "i" } : dependency(name));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const anchor = { issue_id: id(3), version_id: id(4), revision: 1, title: "当前问题", category_id: id(1), product_id: id(2), project_id: id(8) };
const card = (n = 5) => ({ kind: "issue", title: `漏气案例 ${n}`, object_id: id(n + 20), source_id: id(n), source_revision: 3, is_current: true, status: "awaiting_verification", category: "阀件", project: "历史项目", reason: "同编号", root_cause: "未记录", containment: ["已隔离同批样件"], capa_actions: ["更换密封圈"], verification: "待复验：该固定记录未登记有效性决定", differences: [{ field: "型号", status: "different", current: "A", candidate: "B" }, { field: "阶段", status: "unknown", current: "未记录", candidate: "未记录" }], can_prepare_merge: true, object_url: "/?area=cockpit&issue=fixed", object_label: "打开原问题" });
const view = (...items) => ({ version: "similar-history/v1", as_of: "2026-10-29T00:00:00Z", ranking_version: "synthetic-ranking", anchor, items: items.length ? items : [card()], coverage: { status: "current", notice: null } });
const text = tree => typeof tree === "string" || typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(typeof tree.type === "function" ? tree.type(tree.props) : tree.props?.children) : "";
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : typeof tree.type === "function" ? nodes(tree.type(tree.props)) : [tree, ...nodes(tree.props?.children)];
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t, { reading = view(), write = async () => ({}), onMerge, mergeAvailable, openPai, changeId } = {}) {
  const calls = [], own = { slots: [], index: 0, effects: [], dirty: true, openPai };
  const props = { productId: id(2), ...(changeId ? { changeId } : { issueId: id(3) }), versionId: id(4), onMerge, mergeAvailable, api: async (route, body) => { calls.push({ route, body: body && structuredClone(body) }); return body ? write(route, body) : reading; } };
  const component = SimilarHistory(props).type; let tree;
  function render() { own.index = 0; own.effects = []; own.dirty = false; hooks = own; tree = component(props); hooks = null; own.effects.forEach(effect => effect()); }
  render(); t.after(() => own.slots.forEach(slot => slot?.cleanup?.()));
  return { calls, text: () => text(tree), node: label => nodes(tree).find(node => node.type === "button" && text(node) === label), links: () => nodes(tree).filter(node => node.type === "a"),
    async flush() { for (let i = 0; i < 8; i++) { await tick(); if (own.dirty) render(); } },
    async click(label) { const node = this.node(label); assert.ok(node, label); assert.ok(!node.props.disabled, label); node.props.onClick({ currentTarget: { tag: label } }); await this.flush(); },
  };
}

test("opening an issue only reads; cards expose fixed facts, differences and explicit unknowns", async t => {
  const env = environment(t, { reading: { ...view(card(), { ...card(6), kind: "change", title: "历史变更" }), coverage: { status: "partial" } } });
  await env.flush(); assert.equal(env.calls.length, 1); assert.equal(env.calls[0].body, undefined); assert.ok(env.calls[0].route.endsWith(`?version_id=${id(4)}`));
  for (const value of ["漏气案例 5", "历史变更", "相似不代表重复", "未记录", "待复验", "已隔离同批样件", "更换密封圈", "当前：A；历史：B", "不能据此判断相同", "固定 v3", "变更措施", "部分可读资料"]) assert.ok(env.text().includes(value), value);
  assert.equal(env.node("标为重复，核对后确认"), undefined); assert.equal(env.node("让小Pai看看"), undefined);
  assert.equal(env.links()[0].props.target, "_blank"); assert.equal(env.links()[0].props.rel, "noopener noreferrer");
});

test("not-relevant is explicit, recorded without text and only then hides the selected card", async t => {
  let resolve;
  const env = environment(t, { reading: view(card(), card(6)), write: () => new Promise(done => { resolve = done; }) });
  await env.flush(); const control = env.node("不相关"); control.props.onClick(); await env.flush();
  assert.ok(env.text().includes("漏气案例 5")); assert.equal(env.calls.length, 2);
  assert.deepEqual(Object.keys(env.calls[1].body).sort(), ["action", "candidate_kind", "candidate_revision", "candidate_source_id", "request_key", "version_id"]);
  assert.equal(env.calls[1].body.action, "not_relevant"); resolve({}); await env.flush();
  assert.ok(!env.text().includes("漏气案例 5")); assert.ok(env.text().includes("漏气案例 6"));
});

test("lost feedback response retains exact request for retry; another open cannot replace it", async t => {
  let lose = true;
  const env = environment(t, { write: async () => { if (lose) { lose = false; throw Error("response lost"); } return {}; } });
  await env.flush(); await env.click("不相关"); assert.ok(env.text().includes("原反馈请求已保留")); assert.ok(env.text().includes("漏气案例 5"));
  env.links()[0].props.onClick(); await env.flush(); assert.equal(env.calls.length, 2);
  await env.click("重试记录原反馈"); assert.deepEqual(env.calls[1].body, env.calls[2].body); assert.ok(env.text().includes("已收起本次标记为不相关的记录"));
});

test("stale or revoked feedback hides old cards and requires a fresh explicit lookup", async t => {
  for (const status of [403, 409]) {
    const env = environment(t, { write: async () => { throw Object.assign(Error("source changed"), { status }); } });
    await env.flush(); await env.click("不相关"); assert.ok(!env.text().includes("漏气案例 5")); assert.equal(env.node("重试记录原反馈"), undefined);
    assert.ok(env.text().includes(status === 409 ? "重新查找后选择" : "当前访问不可用"));
    await env.click("重新查找"); assert.ok(env.text().includes("漏气案例 5")); assert.equal(env.calls.filter(call => !call.body).length, 2);
  }
});

test("duplicate preparation enters the existing T1 callback after feedback ack, including lost-response retry", async t => {
  const merges = []; let lose = true;
  const env = environment(t, { onMerge: (...args) => merges.push(args), mergeAvailable: () => true, write: async () => { if (lose) { lose = false; throw Error("response lost"); } return {}; } });
  await env.flush(); assert.equal(merges.length, 0); await env.click("标为重复，核对后确认"); assert.equal(merges.length, 0);
  await env.click("重试记录原反馈"); assert.deepEqual(env.calls[1].body, env.calls[2].body); assert.equal(env.calls[2].body.action, "merge_prepared");
  assert.equal(merges.length, 1); assert.equal(merges[0][0].source_id, id(5)); assert.ok(merges[0][1]);
  assert.ok(env.calls.slice(1).every(call => call.route.endsWith("/feedback")), "card never executes a business command itself");
  const forbidden = environment(t, { onMerge: () => assert.fail("no merge authority"), mergeAvailable: () => false }); await forbidden.flush(); assert.equal(forbidden.node("标为重复，核对后确认"), undefined);
});

test("Pai action opens the exact selected pair without feedback writes or Run creation", async t => {
  const selected = [], env = environment(t, { openPai: value => selected.push(value) });
  await env.flush(); assert.equal(selected.length, 0); await env.click("让小Pai看看");
  assert.equal(selected.length, 1); assert.deepEqual(selected[0], { anchor, candidate: card() }); assert.equal(env.calls.length, 1);
});

test("change detail keeps its fixed version, supports explicit feedback and never offers issue merging", async t => {
  const selected = [], change = { ...anchor, kind: "change", change_id: id(3) };
  delete change.issue_id;
  const env = environment(t, { changeId: id(3), reading: { ...view(), anchor: change },
    openPai: value => selected.push(value), onMerge: () => assert.fail("change cannot merge issues"), mergeAvailable: () => true });
  await env.flush(); assert.equal(env.calls.length, 1);
  assert.equal(env.calls[0].route, `v1/products/${id(2)}/change-execution/${id(3)}/similar-history?version_id=${id(4)}`);
  assert.equal(env.node("标为重复，核对后确认"), undefined);
  assert.ok(env.text().includes("与当前变更的结构化差异"));
  await env.click("让小Pai看看"); assert.deepEqual(selected[0], { anchor: change, candidate: card() });
  assert.equal(env.calls.length, 1, "opening Pai does not create a Run");
  await env.click("不相关"); assert.equal(env.calls[1].route, `v1/products/${id(2)}/change-execution/${id(3)}/similar-history/feedback`);
  assert.equal(env.calls[1].body.version_id, id(4)); assert.equal(env.calls[1].body.action, "not_relevant");
});
