import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
let hooks, timerContext;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const react = { ...React,
  useState(initial) { const own = hooks, index = own.index++; if (!(index in own.slots)) own.slots[index] = initial; return [own.slots[index], value => { own.slots[index] = typeof value === "function" ? value(own.slots[index]) : value; own.dirty = true; }]; },
  useEffect(effect, deps) { const own = hooks, index = own.index++, old = own.slots[index]; if (!same(old?.deps, deps)) { own.slots[index] = { deps }; own.effects.push(() => { old?.cleanup?.(); own.slots[index].cleanup = effect(); }); } },
};
const modules = new Map();
function load(relative) {
  if (modules.has(relative)) return modules.get(relative);
  const mod = { exports: {} }, filename = path.join(web, "src", relative);
  const require = name => name === "react" ? react : name === "./ui/button" ? { Button: "button" }
    : name === "@phosphor-icons/react" ? { Sparkle: "i", ArrowSquareOut: "i" }
      : name === "./similar-history-pai" ? { SimilarHistoryPaiContext: {} }
        : name.endsWith(".css") ? { __esModule: true, default: {} }
          : name.startsWith("@/") ? load(`${name.slice(2)}.ts`)
            : name === "./similar-history" ? load("components/similar-history.tsx") : dependency(name);
  runInNewContext(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText,
    { module: mod, exports: mod.exports, require, URLSearchParams, Error,
      setTimeout: (callback, delay) => { const id = ++timerContext.next; timerContext.timers.set(id, { callback, delay }); return id; },
      clearTimeout: id => timerContext.timers.delete(id) });
  modules.set(relative, mod.exports); return mod.exports;
}
const { SimilarHistoryTitle } = load("components/similar-history-title.tsx");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const card = n => ({ kind: "issue", title: `可读历史${n}`, source_id: id(n + 20), object_id: id(n + 40), source_revision: 3, is_current: true, status: "open", category: "阀件", project: "历史项目", reason: "同失效词", root_cause: "未记录", containment: ["未记录"], capa_actions: ["未记录"], verification: "待复验", differences: [], can_prepare_merge: true, object_url: "/?area=cockpit&issue=actual", object_label: "打开原问题" });
const view = (title, kind = "issue", project = id(3), count = 1) => ({ version: "similar-history/v1", as_of: "2026-10-29T00:00:00Z", anchor: { kind: `${kind}_draft`, title, category_id: id(1), product_id: id(2), project_id: project }, items: Array.from({ length: count }, (_, n) => card(n)), coverage: { status: "current", notice: null } });
const text = tree => typeof tree === "string" || typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(typeof tree.type === "function" ? tree.type(tree.props) : tree.props?.children) : "";
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : typeof tree.type === "function" ? nodes(tree.type(tree.props)) : [tree, ...nodes(tree.props?.children)];
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t, initial = {}) {
  const calls = [], own = { slots: [], index: 0, effects: [], dirty: true }, timers = new Map();
  timerContext = { timers, next: 0 };
  let props = { productId: id(2), projectId: id(3), kind: "issue", title: "", api: (route, body) => new Promise((resolve, reject) => calls.push({ route, body, resolve, reject })), ...initial }, tree;
  function render() { own.index = 0; own.effects = []; own.dirty = false; hooks = own; tree = SimilarHistoryTitle(props); hooks = null; own.effects.forEach(effect => effect()); }
  render(); t.after(() => own.slots.forEach(slot => slot?.cleanup?.()));
  return { calls, timers, tree: () => tree, text: () => text(tree), nodes: () => nodes(tree),
    setProps(next) { props = { ...props, ...next }; render(); },
    async flush() { for (let i = 0; i < 6; i++) { await tick(); if (own.dirty) render(); } },
    async fire() { const queued = [...timers.values()]; timers.clear(); queued.forEach(timer => { assert.equal(timer.delay, 400); timer.callback(); }); await this.flush(); },
    async respond(index, reading) { calls[index].resolve(reading); await this.flush(); },
    async click(label) { const node = nodes(tree).find(node => node.type === "button" && text(node) === label); assert.ok(node, label); node.props.onClick(); await this.flush(); },
  };
}

test("unsaved Issue and Change titles debounce GET only, with no guessed object or feedback", async t => {
  const env = environment(t); assert.equal(env.tree(), null); assert.equal(env.timers.size, 0);
  env.setProps({ title: "漏" }); env.setProps({ title: "  接口漏气  " }); assert.equal(env.timers.size, 1); assert.equal(env.calls.length, 0);
  await env.fire(); assert.equal(env.calls.length, 1); assert.equal(env.calls[0].body, undefined);
  const query = new URL(`https://local.invalid/${env.calls[0].route}`).searchParams;
  assert.equal(query.get("title"), "接口漏气"); assert.equal(query.get("kind"), "issue"); assert.equal(query.get("project_id"), id(3));
  assert.deepEqual([...query.keys()].sort(), ["kind", "project_id", "title"]);
  await env.respond(0, view("接口漏气")); assert.ok(env.text().includes("可读历史0"));
  env.setProps({ kind: "change", title: "更换接口" }); assert.ok(!env.text().includes("可读历史0"));
  await env.fire(); await env.respond(1, view("更换接口", "change"));
  assert.ok(env.calls[1].route.includes("kind=change")); assert.ok(env.calls.every(call => call.body === undefined));
});

test("draft suggestions reuse bounded cards and expose only actual object links", async t => {
  const env = environment(t, { title: "漏气" }); await env.fire();
  await env.respond(0, { ...view("漏气", "issue", id(3), 6), coverage: { status: "partial" } });
  for (const value of ["未记录", "待复验", "部分可读资料", "找到 5 条", "相似不代表重复"]) assert.ok(env.text().includes(value), value);
  assert.ok(!env.text().includes("可读历史5"));
  for (const label of ["不相关", "标为重复", "让小Pai看看"]) assert.ok(!env.text().includes(label));
  const links = env.nodes().filter(node => node.type === "a"); assert.equal(links.length, 5);
  assert.ok(links.every(node => node.props.href === "/?area=cockpit&issue=actual" && !node.props.onClick));
  assert.equal(env.calls.length, 1);
});

test("title changes hide old results immediately and late reads cannot replace the latest title", async t => {
  const env = environment(t, { title: "旧标题" }); await env.fire();
  env.setProps({ title: "新标题" }); await env.fire();
  await env.respond(1, view("新标题")); assert.ok(env.text().includes("可读历史0"));
  await env.respond(0, { ...view("旧标题"), items: [{ ...card(0), title: "迟到的旧结果" }] });
  assert.ok(!env.text().includes("迟到的旧结果"));
  env.setProps({ projectId: id(9) }); assert.ok(!env.text().includes("可读历史0"));
  await env.fire(); assert.ok(env.calls[2].route.includes(`project_id=${id(9)}`));
});

test("revoked refresh and mismatched scope never leave stale cards visible", async t => {
  const env = environment(t, { title: "漏气" }); await env.fire(); await env.respond(0, view("漏气"));
  await env.click("重新查找标题"); assert.ok(!env.text().includes("可读历史0")); await env.fire();
  env.calls[1].reject(Object.assign(Error("当前无权读取"), { status: 403 })); await env.flush();
  assert.ok(env.text().includes("当前无权读取")); assert.ok(!env.text().includes("可读历史0"));
  await env.click("重新查找标题"); await env.fire(); await env.respond(2, view("漏气", "issue", id(9)));
  assert.ok(env.text().includes("标题或范围已变化")); assert.ok(!env.text().includes("可读历史0"));
});

test("empty and overlong titles make no lookup and are not silently truncated", async t => {
  const env = environment(t, { title: "x".repeat(241) }); assert.equal(env.timers.size, 0); assert.ok(env.text().includes("缩短至240"));
  env.setProps({ title: "🙂".repeat(240) }); await env.fire(); assert.equal(env.calls.length, 1);
  assert.equal(new URL(`https://local.invalid/${env.calls[0].route}`).searchParams.get("title"), "🙂".repeat(240));
  env.setProps({ title: "  " }); assert.equal(env.tree(), null); await env.respond(0, view("🙂".repeat(240)));
  assert.equal(env.tree(), null); assert.ok(env.calls.every(call => call.body === undefined));
});
