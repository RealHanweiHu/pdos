import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
const react = { ...React, useState(initial) { const own = hooks, index = own.index++; if (!(index in own.values)) own.values[index] = initial; return [own.values[index], value => { own.values[index] = typeof value === "function" ? value(own.values[index]) : value; }]; }, useEffect(effect, deps) { const own = hooks, index = own.index++; if (!same(own.values[index]?.deps, deps)) { const previous = own.values[index]; own.values[index] = { deps }; own.effects.push(() => { previous?.cleanup?.(); own.values[index].cleanup = effect(); }); } } };
const cache = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync);
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = name => name === "react" ? react : name === "@/components/ui/button" ? { Button: props => React.createElement("button", props) }
    : name === "./project-workspace" ? { ProjectWorkspace: props => React.createElement("div", { "data-project-workspace": props.entry.project.id }) }
    : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { ProjectCockpit } = load(path.join(directory, "project-cockpit.tsx"));
const entry = { category: { id: "actual-category", name: "Category" }, product: { id: "product", name: "Product" }, project: { id: "actual-project", name: "Project", owner_id: "owner", visibility: "category", status: "active", revision: 1, created_at: "2026-10-18T01:00:00Z", source_status: "current", definition: { title: "Definition", revision: 1 }, plan: null, plan_state: "not_created", work_packages: [], task_count: null, latest_status_update: { id: "update", revision: 1, actor: { id: "owner", name: "Named owner" }, fact_summary: "PRIVATE_NAMED_SUMMARY", next_steps: "Next", task_refs: [], created_at: "2026-10-18T01:00:00Z", receipt_id: "receipt" } }, openItems: [], openItemsError: "" };
function driver(location) {
  const state = { index: 0, values: [], effects: [] }, requests = [];
  let props = { api: () => new Promise(resolve => requests.push(resolve)), session: { principal_id: "owner", name: "Owner" }, location, onOpenProject() {}, onOpenOverview() {}, onOpenWorkbench() {} };
  return { requests, setProps(next) { props = { ...props, ...next }; }, render() { state.index = 0; state.effects = []; hooks = state; let tree; try { tree = ProjectCockpit(props); } finally { hooks = null; } const html = renderToStaticMarkup(tree); state.effects.forEach(effect => effect()); return html; }, async ready() { this.render(); requests.shift()({ items: [entry], next_cursor: null, unavailable_count: 0, as_of: "2026-10-18T01:00:00Z" }); await new Promise(resolve => setImmediate(resolve)); return this.render(); } };
}
test("a project in another category never becomes the requested category workspace", async () => {
  const env = driver({ area: "cockpit", categoryId: "different-category", projectId: "actual-project" });
  const html = await env.ready(); assert.match(html, /此项目当前不可见/); assert.doesNotMatch(html, /PRIVATE_NAMED_SUMMARY|data-project-workspace/);
});
test("principal and requested-project changes hide the previous named summary synchronously", async () => {
  const env = driver({ area: "cockpit", categoryId: "", projectId: "" });
  assert.match(await env.ready(), /PRIVATE_NAMED_SUMMARY/);
  env.setProps({ session: { principal_id: "another-user", name: "Another" } }); assert.doesNotMatch(env.render(), /PRIVATE_NAMED_SUMMARY/);
  env.setProps({ location: { area: "cockpit", categoryId: "actual-category", projectId: "different-project" } }); assert.doesNotMatch(env.render(), /PRIVATE_NAMED_SUMMARY/);
});
