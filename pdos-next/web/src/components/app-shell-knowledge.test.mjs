import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Real AppShell and navigation functions with isolated hooks, browser surface
// and child entry components. This is not HTTP, browser or visual acceptance.
const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
let hooks = null, currentEnvironment = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
// Isolated hook driver executes actual AppShell, not a replacement shell.
const react = { ...React,
  useState(initial) {
    const own = hooks, index = own.index++;
    if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial;
    return [own.slots[index], next => {
      if (own.disposed) return;
      const value = typeof next === "function" ? next(own.slots[index]) : next;
      if (!Object.is(value, own.slots[index])) { own.slots[index] = value; own.dirty = true; }
    }];
  },
  useRef(initial) { const own = hooks, index = own.index++; if (!(index in own.slots)) own.slots[index] = { current: initial }; return own.slots[index]; },
  useCallback(callback, deps) { const own = hooks, index = own.index++; if (!same(own.slots[index]?.deps, deps)) own.slots[index] = { callback, deps }; return own.slots[index].callback; },
  useEffect(effect, deps) {
    const own = hooks, index = own.index++;
    if (!same(own.slots[index]?.deps, deps)) {
      const next = { deps, cleanup: own.slots[index]?.cleanup }; own.slots[index] = next;
      own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); });
    }
  },
};
const child = name => Object.defineProperty(function ChildEntry(props) { return React.createElement("div", { "data-entry": name }, props.children); }, "displayName", { value: name });
const entries = Object.fromEntries(["Button", "ConnectedAutomationRules", "MyWork", "ProjectList", "ProjectCockpit", "CategoryArea", "KnowledgeLibrary", "PaiRail", "ObjectSearch"].map(name => [name, child(name)]));
const browserApi = (...args) => currentEnvironment.api(...args);
const childModules = {
  "@/components/ui/button": { Button: entries.Button },
  "@/components/automation-rules": { ConnectedAutomationRules: entries.ConnectedAutomationRules },
  "@/components/my-work": { MyWork: entries.MyWork },
  "@/components/projects/project-list": { ProjectList: entries.ProjectList },
  "@/components/projects/project-cockpit": { ProjectCockpit: entries.ProjectCockpit },
  "@/components/category-workspace": { CategoryArea: entries.CategoryArea },
  "@/components/knowledge/knowledge-library": { KnowledgeLibrary: entries.KnowledgeLibrary },
  "@/components/pai-rail": { PaiRail: entries.PaiRail },
  "@/components/object-search": { ObjectSearch: entries.ObjectSearch },
};
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(extension => filename + extension).find(existsSync);
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_object, name) => String(name) }) };
  if (modules.has(filename)) return modules.get(filename).exports;
  const runtime = new Module(filename); modules.set(filename, runtime);
  runtime.require = name => {
    if (name === "react") return react;
    if (name === "next-themes") return { useTheme: () => ({ theme: "light", resolvedTheme: "light", setTheme() {} }) };
    if (name === "@phosphor-icons/react") return new Proxy({}, { get: () => child("Icon") });
    if (name === "@/lib/browser-api") return { browserApi };
    if (childModules[name]) return childModules[name];
    return name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  };
  runtime._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return runtime.exports;
}
const { AppShell } = load(path.join(directory, "app-shell.tsx"));
const { resolveGlobalLocation } = load(path.join(web, "src/lib/global-navigation.ts"));
const id = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const category = (n, capability = false) => ({ id: id(n), name: `可读品类 ${n}`, purpose: `品类 ${n} 的原用途`, ...(capability === undefined ? {} : { capabilities: { product_management: capability } }) });
const tick = () => new Promise(resolve => setImmediate(resolve));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(child => elements(child, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
function text(tree) {
  if (tree === null || tree === undefined || typeof tree === "boolean") return "";
  if (typeof tree === "string" || typeof tree === "number") return String(tree);
  return Array.isArray(tree) ? tree.map(text).join("") : text(tree.props?.children);
}
function environment(t, search, overrides = {}, initialProps = {}) {
  const state = { who: { name: "合成本人", principal_id: id(4) }, categories: [category(1), category(2)], categoryError: null, ...overrides };
  const calls = [], listeners = new Map(), storage = new Map(), globals = {};
  const location = { search, assign() { assert.fail("This shell check must not navigate a real document"); } };
  const window = { location,
    history: { replaceState(_data, _unused, href) { location.search = href; }, pushState(_data, _unused, href) { location.search = href; } },
    addEventListener(name, callback) { if (!listeners.has(name)) listeners.set(name, new Set()); listeners.get(name).add(callback); },
    removeEventListener(name, callback) { listeners.get(name)?.delete(callback); },
    dispatchEvent(event) { for (const callback of listeners.get(event.type) ?? []) callback(event); }, scrollTo() {},
  };
  const replacements = { window, localStorage: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) },
    requestAnimationFrame: callback => { callback(); return 0; }, cancelAnimationFrame() {},
    PopStateEvent: class { constructor(type) { this.type = type; } }, document: { querySelector: () => null, getElementById: () => null } };
  for (const [name, value] of Object.entries(replacements)) { globals[name] = Object.getOwnPropertyDescriptor(globalThis, name); Object.defineProperty(globalThis, name, { configurable: true, writable: true, value }); }
  const instance = { index: 0, slots: [], effects: [], dirty: false, disposed: false };
  let tree, props = initialProps;
  const api = async (route, ...body) => {
    calls.push({ route, body }); assert.equal(body.length, 0, "Shell load is GET only");
    if (route === "v1/session") return structuredClone(state.who);
    if (route === "v1/categories") { if (state.categoryError) throw state.categoryError; return structuredClone(state.categories); }
    if (route === "v1/personal/projects?page_size=6") return { items: [], next_cursor: null };
    assert.fail(`Shell must not choose/read a first model or execute a child request: ${route}`);
  };
  currentEnvironment = { api };
  function render() { instance.index = 0; instance.effects = []; instance.dirty = false; hooks = instance; try { tree = AppShell(props); } finally { hooks = null; } for (const effect of instance.effects) effect(); }
  function dispose() {
    instance.disposed = true; instance.slots.forEach(slot => slot?.cleanup?.());
    for (const [name, descriptor] of Object.entries(globals)) { if (descriptor) Object.defineProperty(globalThis, name, descriptor); else delete globalThis[name]; }
    currentEnvironment = null;
  }
  t.after(dispose); render();
  return { state, calls, tree: () => tree, nodes: name => elements(tree, node => node.type === entries[name]),
    content: () => elements(tree, node => node.type === "main" && node.props.id === "workspace-content")[0],
    location: () => resolveGlobalLocation(location.search),
    async flush() { for (let i = 0; i < 6; i++) { await tick(); if (instance.dirty) render(); } },
    async click(predicate) { const target = elements(tree, node => typeof node.props?.onClick === "function" && predicate(node))[0]; assert.ok(target, "Actual shell control exists"); target.props.onClick(); render(); await this.flush(); },
    async navigate(next) { location.search = next; window.dispatchEvent(new replacements.PopStateEvent("popstate")); render(); await this.flush(); },
    async setProps(next) { props = { ...props, ...next }; render(); await this.flush(); },
  };
}
function library(env) { const nodes = env.nodes("KnowledgeLibrary"); assert.equal(nodes.length, 1); return nodes[0]; }
function onlyEntry(env, name) { assert.equal(env.nodes(name).length, 1); assert.equal(env.nodes("KnowledgeLibrary").length, 0); }

test("valid category without PM capability mounts the real KnowledgeLibrary entry with nil-product defaults", async t => {
  const env = environment(t, `?area=knowledge&category=${id(1)}`); await env.flush(); const entry = library(env);
  assert.deepEqual(env.location(), { area: "knowledge", categoryId: id(1), projectId: "" });
  assert.equal(entry.key, `${id(4)}:${id(1)}`); assert.equal(entry.props.categoryId, id(1)); assert.equal(entry.props.categoryName, "可读品类 1");
  assert.equal(entry.props.principalId, id(4)); assert.equal(entry.props.api, browserApi); assert.equal(Object.hasOwn(entry.props, "productId"), false);
  assert.equal(env.nodes("CategoryArea").length, 0); assert.deepEqual(env.calls.map(call => call.route), ["v1/session", "v1/categories", "v1/personal/projects?page_size=6"]);
});
test("knowledge does not require product-management capabilities to have been supplied", async t => {
  const env = environment(t, `?area=knowledge&category=${id(1)}`, { categories: [{ id: id(1), name: "普通可读品类", purpose: "原用途" }] });
  await env.flush(); assert.equal(library(env).props.categoryName, "普通可读品类");
});
test("unselected category stays on its picker and only an explicit selection mounts the library", async t => {
  const env = environment(t, "?area=knowledge"); await env.flush();
  assert.equal(env.nodes("KnowledgeLibrary").length, 0); assert.equal(env.nodes("CategoryArea").length, 0);
  assert.ok(text(env.content()).includes("可读品类 1")); assert.ok(text(env.content()).includes("可读品类 2"));
  await env.click(node => node.type === "button" && text(node).includes("可读品类 2"));
  assert.equal(library(env).props.categoryId, id(2)); assert.equal(env.calls.length, 3);
});
test("a category absent from the readable list does not mount a guessed library", async t => {
  const env = environment(t, `?area=knowledge&category=${id(99)}`); await env.flush(); assert.equal(env.nodes("KnowledgeLibrary").length, 0);
  assert.ok(text(env.content()).includes("可读品类 1"));
});
test("explicit legacy knowledge bench plus product retains CategoryArea without mounting the new entry", async t => {
  const env = environment(t, `?area=knowledge&category=${id(1)}&bench=knowledge&product=${id(20)}&view=sources`); await env.flush();
  onlyEntry(env, "CategoryArea"); const entry = env.nodes("CategoryArea")[0]; assert.equal(entry.props.area, "knowledge"); assert.equal(entry.props.categoryId, id(1)); assert.equal(entry.props.categories.length, 2);
});
test("knowledge bench without a product still mounts the category library", async t => {
  const env = environment(t, `?area=knowledge&category=${id(1)}&bench=knowledge&view=sources`); await env.flush(); assert.equal(library(env).props.categoryId, id(1));
});
test("category read failure mounts neither library nor legacy workbench and retry uses fresh data", async t => {
  const env = environment(t, `?area=knowledge&category=${id(1)}`, { categoryError: new Error("category read unavailable") }); await env.flush();
  assert.equal(env.nodes("KnowledgeLibrary").length, 0); assert.equal(env.nodes("CategoryArea").length, 0); assert.ok(text(env.content()).includes("category read unavailable"));
  env.state.categoryError = null; await env.click(node => node.type === entries.Button && text(node) === "重新读取");
  assert.equal(library(env).props.categoryId, id(1)); assert.equal(env.calls.length, 6);
});
test("document mode preserves document children and never mounts the library even with knowledge URL", async t => {
  const document = React.createElement("section", { "data-document": "actual-child" }, "已选文档正文");
  const env = environment(t, `?area=knowledge&category=${id(1)}`, {}, { documentPage: { categoryId: id(1) }, children: document }); await env.flush();
  assert.equal(env.nodes("KnowledgeLibrary").length, 0); assert.equal(env.nodes("CategoryArea").length, 0); assert.equal(env.content().props.children, document);
});
for (const [area, entry] of [["work", "MyWork"], ["projects", "ProjectList"], ["cockpit", "ProjectCockpit"]]) test(`${area} keeps its own real shell entry instead of the knowledge library`, async t => {
  const env = environment(t, `?area=${area}&category=${id(1)}${area === "cockpit" ? `&project=${id(30)}` : ""}`); await env.flush(); onlyEntry(env, entry);
});
test("category route change replaces the keyed principal/category binding and leaving knowledge removes it", async t => {
  const env = environment(t, `?area=knowledge&category=${id(1)}`); await env.flush(); const old = library(env);
  await env.navigate(`?area=knowledge&category=${id(2)}`); const next = library(env);
  assert.notEqual(next.key, old.key); assert.equal(next.props.categoryId, id(2)); assert.equal(next.props.categoryName, "可读品类 2"); assert.equal(next.props.principalId, id(4));
  await env.navigate("?area=work"); onlyEntry(env, "MyWork"); assert.equal(env.calls.length, 3);
});
test("an actual shell refresh replaces identity/category props and keyed library with the current session", async t => {
  const env = environment(t, `?area=knowledge&category=${id(1)}`, { categories: [{ id: id(1), name: "原品类名", purpose: "原用途" }] }); await env.flush(); const old = library(env);
  env.state.who = { name: "刷新后本人", principal_id: id(44) }; env.state.categories = [{ id: id(1), name: "刷新后品类名", purpose: "原用途", capabilities: { product_management: false } }];
  await env.click(node => node.props["aria-label"] === "重新读取品类权限"); const fresh = library(env);
  assert.notEqual(fresh.key, old.key); assert.equal(fresh.key, `${id(44)}:${id(1)}`); assert.equal(fresh.props.principalId, id(44)); assert.equal(fresh.props.categoryName, "刷新后品类名");
  assert.equal(env.calls.length, 6); assert.equal(env.calls.some(call => call.route.includes("/products")), false);
});
