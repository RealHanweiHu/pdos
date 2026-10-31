import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Isolated component state harness; SSR delegates unchanged. */
const reactShim = { ...React, useMemo(factory, dependencies) { return hooks ? factory() : React.useMemo(factory, dependencies); }, useCallback(callback, dependencies) { return hooks ? callback : React.useCallback(callback, dependencies); }, useState(initial) {
  if (!hooks) return React.useState(initial);
  const own = hooks, index = own.index++;
  if (!(index in own.values)) own.values[index] = typeof initial === "function" ? initial() : initial;
  return [own.values[index], next => { own.values[index] = typeof next === "function" ? next(own.values[index]) : next; }];
}, useEffect(callback, dependencies) { if (!hooks) return React.useEffect(callback, dependencies); hooks.effects.push(callback); } };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const cache = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? reactShim
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier === "./project-build-summary" ? { ProjectBuildSummary: props => React.createElement("div", { "data-project-build-summary": props.projectId }) }
    : specifier === "@/components/workspace" ? { Workspace: props => React.createElement("div", { "data-editor-panel": props.embeddedPanel, "data-product": props.fixedProductId }) }
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { fileName: filename, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const presentation = load(path.join(webRoot, "src/lib/project-presentation.ts"));
const { ProjectList } = load(path.join(directory, "project-list.tsx"));
const { ProjectDirectoryView } = load(path.join(directory, "project-directory-view.tsx"));
const { ProjectWorkspace } = load(path.join(directory, "project-workspace.tsx"));
const { ProjectCockpit } = load(path.join(directory, "project-cockpit.tsx"));
const { ProjectProfessional } = load(path.join(directory, "project-professional.tsx"));
const { ProjectActivity } = load(path.join(directory, "project-activity.tsx"));
function entry(id, owner = "me", earliest = "2026-10-24T00:00:00Z", latest = "2026-10-28T00:00:00Z") {
  return { category: { id: "cat", name: "合成品类" }, product: { id: "model", name: "合成型号" },
    project: { id, name: `合成项目 ${id}`, owner_id: owner, owner_name: "合成负责人", status: "active", purpose: "用途", scope: "范围", visibility: "category", revision: 1,
      source_status: "current", created_at: "2026-10-17T00:00:00Z", definition: { id: "definition", title: "固定定义", revision: 1 },
      plan_state: "available", plan: { id: "plan", revision: 1, forecast: { earliest_finish: earliest, latest_finish: latest } }, work_packages: [], task_count: 0 }, openItems: [], openItemsError: "" };
}
const entries = [entry("one"), entry("two", "other")];
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
function driver(Component, props) {
  const state = { index: 0, values: [], effects: [] };
  return { render() { hooks = state; state.index = 0; state.effects = []; try { return Component(props); } finally { hooks = null; } }, setProps(next) { props = { ...props, ...next }; }, mount() { return state.effects.map(effect => effect()); } };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
const markup = tree => renderToStaticMarkup(tree);

test("project filters retain the authorized identity, and ownership is not inferred from visibility", () => {
  assert.deepEqual(presentation.filterProjects(entries, { query: "", categoryId: "", ownerId: "me" }).map(e => e.project.id), ["one"]);
  assert.deepEqual(presentation.filterProjects(entries, { query: "two", categoryId: "cat", ownerId: "" }).map(e => e.project.id), ["two"]);
  assert.equal(presentation.filterProjects(entries, { query: "", categoryId: "other", ownerId: "" }).length, 0);
});
test("missing stage templates do not become a six-stage plan or a health decision", () => {
  const before = structuredClone(entries), groups = presentation.groupProjects(entries, "stage");
  assert.equal(groups.length, 1); assert.equal(groups[0].label, "阶段未采用");
  assert.deepEqual(entries, before);
});
test("unknown, single-sided and reversed finish bounds cannot be drawn as a fabricated interval", () => {
  const axis = presentation.forecastAxis(entries); assert.ok(axis);
  assert.ok(presentation.forecastPosition(entries[0], axis).width > 0);
  assert.equal(presentation.forecastPosition(entry("single", "me", null), axis), null);
  assert.equal(presentation.forecastPosition(entry("reverse", "me", "2026-10-29", "2026-10-24"), axis), null);
  const unavailable = entry("unavailable"); unavailable.project.plan_state = "unavailable";
  assert.equal(presentation.forecastAxis([unavailable]), null);
  assert.deepEqual(presentation.projectForecast(entry("invalid", "me", "bad date", null)), { earliest: null, latest: null });
});
test("the approved three views use one authorized read set and open the correct project or plan", async () => {
  const calls = [], opened = [];
  const component = driver(ProjectList, { principalId: "me", onOpenProject: (...scope) => opened.push(["project", ...scope]), onOpenPlan: (...scope) => opened.push(["plan", ...scope]), api: async (path, body) => { calls.push({ path, body }); return { items: entries, next_cursor: null, unavailable_count: 0, as_of: "2026-10-17T00:00:00Z" }; } });
  component.render(); component.mount(); await tick();
  const page = driver(ProjectDirectoryView, component.render().props);
  let tree = page.render(); assert.match(markup(tree), /合成项目 one/); assert.match(markup(tree), /合成项目 two/);
  assert.doesNotMatch(markup(tree), /我负责的|项目数据说明|读取于/);
  const viewButtons = () => elements(tree, e => e.type === "button" && e.props["aria-pressed"] !== undefined);
  viewButtons()[1].props.onClick(); tree = page.render(); assert.match(markup(tree), /看板用于查看/);
  elements(tree, e => e.type === "button" && e.props.className === undefined && elements(e, child => child.type === "h2").length > 0)[0].props.onClick();
  assert.deepEqual(opened.pop(), ["project", "cat", "one"]);
  viewButtons()[2].props.onClick(); tree = page.render();
  for (const label of ["基线", "预测", "承诺", "实际"]) assert.ok(markup(tree).includes(label));
  elements(tree, e => e.type === "button" && e.props.className === "textLink")[0].props.onClick();
  assert.deepEqual(opened.pop(), ["plan", "cat", "one"]);
  assert.equal(elements(tree, e => e.props?.draggable).length, 0);
  assert.deepEqual(calls, [{ path: "v1/personal/projects?page_size=100", body: undefined }]);
});
test("project read errors retain retry without masquerading as an empty portfolio", async () => {
  let fail = true; const calls = [];
  const component = driver(ProjectList, { onOpenProject() {}, api: async (path, body) => { calls.push({ path, body }); if (fail) throw new Error("合成读取失败"); return { items: entries, next_cursor: null, unavailable_count: 0 }; } });
  component.render(); component.mount(); await tick(); let tree = component.render();
  assert.match(markup(tree), /合成读取失败/); assert.doesNotMatch(markup(tree), /暂无可见项目/);
  fail = false; elements(tree, e => e.props?.children === "重新读取")[0].props.onClick();
  component.render(); component.mount(); await tick(); tree = component.render();
  assert.match(markup(tree), /合成项目 one/); assert.match(markup(tree), /合成项目 two/);
  assert.ok(calls.every(call => call.body === undefined));
});
test("directory identity changes hide prior entries before the next read completes", async () => {
  const component = driver(ProjectList, { principalId: "me", onOpenProject() {}, api: async () => ({ items: entries, next_cursor: null, unavailable_count: 0 }) });
  component.render(); component.mount(); await tick(); assert.match(markup(component.render()), /合成项目 one/);
  component.setProps({ principalId: "other" });
  const html = markup(component.render()); assert.match(html, /正在读取/); assert.doesNotMatch(html, /合成项目 one/);
});
test("workspace retains Build and commitments, separates maturity, and all execution links keep project scope", () => {
  const props = { entry: entries[0], api: async () => {}, session: { name: "合成人员", principal_id: "me" }, today: "2026-10-17", readVersion: 3, initialView: "now", onBack() {}, onOpenWorkbench() {} };
  const component = driver(ProjectWorkspace, props); let tree = component.render();
  assert.match(markup(tree), /试制轮次/); assert.match(markup(tree), /关键承诺/);
  for (const anchor of elements(tree, e => e.type === "a")) {
    const params = new URLSearchParams(anchor.props.href); assert.equal(params.get("project"), "one"); assert.equal(params.get("product"), "model");
  }
  elements(tree, e => e.props?.id === "project-tab-gates")[0].props.onClick(); tree = component.render();
  const governance = elements(tree, e => e.type?.name === "ProjectGovernance")[0]; assert.ok(governance); assert.equal(governance.props.projectId, "one"); assert.equal(governance.props.categoryId, "cat");
  assert.doesNotMatch(markup(tree), /EVT|DVT|PVT|READY|BLOCKED/);
  elements(tree, e => e.props?.id === "project-tab-builds")[0].props.onClick(); tree = component.render();
  const summary = elements(tree, e => e.props?.projectId === "one" && e.props?.principalId === "me")[0]; assert.ok(summary); assert.equal(summary.props.api, props.api); assert.equal(summary.props.categoryId, "cat"); assert.equal(summary.props.productId, "model"); assert.equal(summary.props.readVersion, 3);
});
test("one real activity stream occupies the overview main column and leaves when the tab changes", () => {
  const props = { entry: entries[0], api: async () => {}, session: { name: "本人", principal_id: "me" }, today: "2026-10-18", readVersion: 5, initialView: "now", onBack() {}, onOpenWorkbench() {} };
  const component = driver(ProjectWorkspace, props); let tree = component.render();
  const activity = elements(tree, e => e.type === ProjectActivity); assert.equal(activity.length, 1);
  const grid = elements(tree, e => e.props?.className === "workspaceGrid")[0], main = grid.props.children[0], right = grid.props.children[1];
  assert.equal(elements(main, e => e.type === ProjectActivity).length, 1);
  assert.equal(elements(right, e => e.props?.className === "updatePrompt").length, 1);
  assert.equal(activity[0].props.api, props.api); assert.equal(activity[0].props.readVersion, 5); assert.deepEqual(activity[0].props.scope, { categoryId: "cat", productId: "model", projectId: "one", principalId: "me" });
  assert.doesNotMatch(markup(tree), /项目已建立|更早的具名更新可进入工作与计划查看/);
  elements(tree, e => e.props?.id === "project-tab-plan")[0].props.onClick(); tree = component.render(); assert.equal(elements(tree, e => e.type === ProjectActivity).length, 0);
  elements(tree, e => e.props?.id === "project-tab-now")[0].props.onClick();
  const updated = entry("next"); updated.category.id = "next-cat"; updated.product.id = "next-model"; const nextApi = async () => {};
  component.setProps({ entry: updated, api: nextApi, session: { name: "另一人", principal_id: "other" }, readVersion: 6 }); tree = component.render();
  const next = elements(tree, e => e.type === ProjectActivity); assert.equal(next.length, 1); assert.equal(next[0].props.api, nextApi); assert.equal(next[0].props.readVersion, 6); assert.deepEqual(next[0].props.scope, { categoryId: "next-cat", productId: "next-model", projectId: "next", principalId: "other" });
});
test("cockpit delegates activity to the workspace instead of appending a duplicate stream, preserving refresh inputs", async () => {
  const calls = [], api = async (path, body) => { calls.push({ path, body }); return { items: [entries[0]], next_cursor: null, unavailable_count: 0 }; };
  const session = { name: "本人", principal_id: "me" }, onOpenWorkbench = () => {}, component = driver(ProjectCockpit, { api, session, location: { area: "cockpit", categoryId: "cat", projectId: "one" }, onOpenProject() {}, onOpenOverview() {}, onOpenWorkbench });
  component.render(); component.mount(); await tick(); let tree = component.render();
  assert.equal(tree.type, ProjectWorkspace); assert.equal(elements(tree, e => e.type === ProjectActivity).length, 0); assert.equal(tree.props.api, api); assert.equal(tree.props.session, session); assert.equal(tree.props.onOpenWorkbench, onOpenWorkbench); assert.equal(tree.props.readVersion, 0);
  tree.props.onRefresh(); assert.match(markup(component.render()), /正在读取项目经营总览/); component.mount(); await tick(); tree = component.render(); assert.equal(tree.type, ProjectWorkspace); assert.equal(tree.props.readVersion, 1); assert.ok(calls.every(call => call.body === undefined));
});
test("professional summaries retain explicit project scope while maintenance is mounted only on demand", () => {
  const scope = { api: async () => {}, categoryId: "cat", productId: "model", projectId: "one", principalId: "me", readVersion: 9 };
  for (const [view, panel, componentName] of [["prep", "build", "ProjectBuildEngineering"], ["prep", "manufacturing", "ProjectManufacturingPreparation"], ["builds", "pilots", "ProjectPilots"], ["review", "packages", "ProjectReleasePackages"], ["review", "external", "ProjectExternalHandoffs"]]) {
    const component = driver(ProjectProfessional, { ...scope, view, initialPanel: panel });
    let tree = component.render();
    const summary = elements(tree, e => e.type?.name === componentName)[0];
    assert.ok(summary); assert.deepEqual(summary.props, scope);
    assert.equal(elements(tree, e => e.props?.embeddedPanel).length, 0);
    elements(tree, e => e.props?.className === "editorToggle")[0].props.onClick();
    tree = component.render();
    const editor = elements(tree, e => e.props?.embeddedPanel === panel)[0];
    assert.ok(editor); assert.equal(editor.props.fixedProductId, scope.productId); assert.equal(editor.props.projectId, scope.projectId); assert.equal(editor.props.categoryId, scope.categoryId);
    editor.props.onSaved(); tree = component.render();
    assert.equal(elements(tree, e => e.type?.name === componentName)[0].props.readVersion, scope.readVersion + 1);
    assert.equal(elements(tree, e => e.props?.embeddedPanel === panel)[0].key, editor.key);
  }
});
test("the main project view delegates professional work without losing scope across tab changes", () => {
  const props = { entry: entries[0], api: async () => {}, session: { name: "本人", principal_id: "me" }, today: "2026-10-18", readVersion: 7, onBack() {}, onOpenWorkbench() {} };
  const component = driver(ProjectWorkspace, props); let tree = component.render();
  assert.equal(elements(tree, e => e.type === ProjectProfessional).length, 0);
  elements(tree, e => e.props?.id === "project-tab-prep")[0].props.onClick(); tree = component.render();
  const pane = elements(tree, e => e.type === ProjectProfessional)[0];
  assert.equal(pane.props.projectId, "one"); assert.equal(pane.props.productId, "model"); assert.equal(pane.props.categoryId, "cat"); assert.equal(pane.props.principalId, "me"); assert.equal(pane.props.api, props.api);
  elements(tree, e => e.props?.id === "project-tab-now")[0].props.onClick(); tree = component.render();
  const retained = elements(tree, e => e.props?.className === "professionalSlot")[0];
  assert.equal(retained.props.hidden, true); assert.equal(elements(retained, e => e.type === ProjectProfessional).length, 1);
});
test("cockpit task read failures remain unknown rather than claiming zero risks or no conflicts", async () => {
  const unreadable = entry("one"); unreadable.openItemsError = "合成任务权限待核对";
  const component = driver(ProjectCockpit, { api: async () => ({ items: [unreadable], next_cursor: null, unavailable_count: 0 }), session: { name: "本人", principal_id: "me" }, location: { area: "cockpit", categoryId: "", projectId: "" }, onOpenProject() {}, onOpenOverview() {}, onOpenWorkbench() {} });
  component.render(); component.mount(); await tick(); const html = markup(component.render());
  assert.match(html, /合成任务权限待核对/); assert.match(html, /未完整读取/); assert.doesNotMatch(html, /无开放风险或到期冲突/); assert.match(html, /可见项目/);
});
test("cockpit identity, category, project and API changes synchronously hide prior private reads", async () => {
  const pending = [], api = path => new Promise(resolve => pending.push({ path, resolve }));
  const props = { api, session: { name: "本人", principal_id: "me" }, location: { area: "cockpit", categoryId: "cat", projectId: "one" }, onOpenProject() {}, onOpenOverview() {}, onOpenWorkbench() {} };
  const component = driver(ProjectCockpit, props); component.render(); const cleanup = component.mount(); pending[0].resolve({ items: [entries[0]], next_cursor: null, unavailable_count: 0 }); await tick(); assert.match(markup(component.render()), /合成项目 one/);
  component.setProps({ session: { name: "另一人", principal_id: "other" } }); assert.match(markup(component.render()), /正在读取/); cleanup.forEach(fn => fn?.()); component.mount();
  component.setProps({ location: { ...props.location, categoryId: "other-category" } }); assert.doesNotMatch(markup(component.render()), /合成项目 one/);
  pending[1].resolve({ items: [entries[0]], next_cursor: null, unavailable_count: 0 }); await tick(); assert.doesNotMatch(markup(component.render()), /合成项目 one/);
  component.setProps({ api: async () => ({ items: entries, next_cursor: null, unavailable_count: 0 }), location: { ...props.location, projectId: "two" } }); assert.match(markup(component.render()), /正在读取/);
});
