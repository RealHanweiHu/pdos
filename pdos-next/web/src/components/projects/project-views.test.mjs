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
const reactShim = { ...React, useState(initial) {
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
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const presentation = load(path.join(webRoot, "src/lib/project-presentation.ts"));
const { ProjectList } = load(path.join(directory, "project-list.tsx"));
const { ProjectWorkspace } = load(path.join(directory, "project-workspace.tsx"));
const { ProjectCockpit } = load(path.join(directory, "project-cockpit.tsx"));
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
  assert.equal(groups.length, 1); assert.match(groups[0].label, /待接入/);
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
test("switching list/board/timeline and filtering consumes the same GET read set, without business writes", async () => {
  const calls = [];
  const component = driver(ProjectList, { principalId: "me", onOpenProject() {}, onOpenWorkbench() {}, api: async (path, body) => { calls.push({ path, body }); return { items: entries, next_cursor: null, unavailable_count: 0, as_of: "2026-10-17T00:00:00Z" }; } });
  component.render(); component.mount(); await tick();
  let tree = component.render(); assert.match(markup(tree), /合成项目 one/); assert.match(markup(tree), /合成项目 two/);
  const viewButtons = () => elements(tree, e => e.type === "button" && e.props["aria-pressed"] !== undefined);
  viewButtons()[1].props.onClick(); tree = component.render(); assert.match(markup(tree), /看板只展示/);
  viewButtons()[2].props.onClick(); tree = component.render();
  for (const label of ["基线", "预测", "承诺", "实际"]) assert.ok(markup(tree).includes(label));
  assert.equal(elements(tree, e => e.props?.draggable).length, 0);
  elements(tree, e => e.type === "input" && e.props.type === "checkbox")[0].props.onChange({ target: { checked: true } });
  tree = component.render(); assert.match(markup(tree), /合成项目 one/); assert.doesNotMatch(markup(tree), /合成项目 two/);
  assert.deepEqual(calls, [{ path: "v1/personal/projects?page_size=100", body: undefined }]);
});
test("project read errors keep retry and filters, and never masquerade as an empty portfolio", async () => {
  let fail = true; const calls = [];
  const component = driver(ProjectList, { onOpenProject() {}, onOpenWorkbench() {}, api: async (path, body) => { calls.push({ path, body }); if (fail) throw new Error("合成读取失败"); return { items: entries, next_cursor: null, unavailable_count: 0 }; } });
  component.render(); component.mount(); await tick(); let tree = component.render();
  assert.match(markup(tree), /合成读取失败/); assert.doesNotMatch(markup(tree), /暂无可见项目/);
  elements(tree, e => e.type === "input" && e.props["aria-label"] === "搜索项目")[0].props.onChange({ target: { value: "two" } });
  fail = false; tree = component.render(); elements(tree, e => e.type === "button" && e.props["aria-label"] === "刷新项目")[0].props.onClick();
  component.render(); component.mount(); await tick(); tree = component.render();
  assert.match(markup(tree), /合成项目 two/); assert.doesNotMatch(markup(tree), /合成项目 one/);
  assert.ok(calls.every(call => call.body === undefined));
});
test("workspace retains Build and commitments, separates maturity, and all execution links keep project scope", () => {
  const props = { entry: entries[0], api: async () => {}, session: { name: "合成人员", principal_id: "me" }, today: "2026-10-17", readVersion: 3, onBack() {}, onOpenWorkbench() {} };
  const component = driver(ProjectWorkspace, props); let tree = component.render();
  assert.match(markup(tree), /下一 Build/); assert.match(markup(tree), /关键承诺/);
  for (const anchor of elements(tree, e => e.type === "a")) {
    const params = new URLSearchParams(anchor.props.href); assert.equal(params.get("project"), "one"); assert.equal(params.get("product"), "model");
  }
  elements(tree, e => e.props?.id === "project-tab-gates")[0].props.onClick(); tree = component.render();
  for (const label of ["产品验证", "制造", "交付适用性", "下一阶段进入条件"]) assert.ok(markup(tree).includes(label));
  assert.doesNotMatch(markup(tree), /EVT|DVT|PVT|READY|BLOCKED/);
  elements(tree, e => e.props?.id === "project-tab-builds")[0].props.onClick(); tree = component.render();
  const summary = elements(tree, e => e.props?.projectId === "one" && e.props?.principalId === "me")[0]; assert.ok(summary); assert.equal(summary.props.api, props.api); assert.equal(summary.props.categoryId, "cat"); assert.equal(summary.props.productId, "model"); assert.equal(summary.props.readVersion, 3);
});
test("one real activity stream occupies the now right column after the status entry, and leaves when the tab changes", () => {
  const props = { entry: entries[0], api: async () => {}, session: { name: "本人", principal_id: "me" }, today: "2026-10-18", readVersion: 5, onBack() {}, onOpenWorkbench() {} };
  const component = driver(ProjectWorkspace, props); let tree = component.render();
  const activity = elements(tree, e => e.type === ProjectActivity); assert.equal(activity.length, 1);
  const grid = elements(tree, e => e.props?.className === "workspaceGrid")[0], right = grid.props.children[1], children = React.Children.toArray(right.props.children);
  const promptIndex = children.findIndex(e => e.props?.className === "updatePrompt"), slotIndex = children.findIndex(e => e.props?.className === "activitySlot");
  assert.ok(promptIndex >= 0); assert.equal(slotIndex, promptIndex + 1); assert.equal(elements(children[slotIndex], e => e.type === ProjectActivity).length, 1);
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
test("engineering, manufacturing preparation and pilot readings stay in their project tab with the current identity and refresh binding", () => {
  const api = async () => {}, props = { entry: entries[0], api, session: { name: "本人", principal_id: "me" }, today: "2026-10-18", readVersion: 7, onBack() {}, onOpenWorkbench() {} };
  const component = driver(ProjectWorkspace, props);
  let tree = component.render();
  assert.equal(elements(tree, e => e.type?.name === "ProjectManufacturingPreparation").length, 0);
  assert.equal(elements(tree, e => e.type?.name === "ProjectBuildEngineering").length, 0);
  assert.equal(elements(tree, e => e.type?.name === "ProjectPilots").length, 0);
  elements(tree, e => e.props?.id === "project-tab-prep")[0].props.onClick(); tree = component.render();
  const [panel] = elements(tree, e => e.type?.name === "ProjectManufacturingPreparation");
  assert.ok(panel); assert.equal(panel.props.api, api); assert.equal(panel.props.categoryId, "cat"); assert.equal(panel.props.productId, "model"); assert.equal(panel.props.projectId, "one"); assert.equal(panel.props.principalId, "me"); assert.equal(panel.props.readVersion, 7);
  const [engineering] = elements(tree, e => e.type?.name === "ProjectBuildEngineering");
  assert.ok(engineering); assert.deepEqual(engineering.props, panel.props);
  const [pilots] = elements(tree, e => e.type?.name === "ProjectPilots"); assert.ok(pilots); assert.deepEqual(pilots.props, panel.props);
  assert.match(markup(tree), /草稿不代替当前准备度或正式发布/);
  assert.equal(elements(tree, e => e.type === ProjectActivity).length, 0);
  elements(tree, e => e.props?.id === "project-tab-now")[0].props.onClick(); tree = component.render();
  assert.equal(elements(tree, e => e.type?.name === "ProjectManufacturingPreparation").length, 0);
  assert.equal(elements(tree, e => e.type?.name === "ProjectBuildEngineering").length, 0);
  assert.equal(elements(tree, e => e.type?.name === "ProjectPilots").length, 0);
});
test("fixed release packages and external handoffs load only in review, preserve refresh identity, and retain scoped professional actions", () => {
  const api = async () => {}, props = { entry: entries[0], api, session: { name: "本人", principal_id: "me" }, today: "2026-10-18", readVersion: 9, onBack() {}, onOpenWorkbench() {} };
  const component = driver(ProjectWorkspace, props); let tree = component.render();
  const panes = current => elements(current, e => e.type?.name === "ProjectReleasePackages");
  const handoffs = current => elements(current, e => e.type?.name === "ProjectExternalHandoffs");
  assert.equal(panes(tree).length, 0);
  assert.equal(handoffs(tree).length, 0);
  elements(tree, e => e.props?.id === "project-tab-review")[0].props.onClick(); tree = component.render();
  assert.equal(panes(tree).length, 1);
  assert.deepEqual(panes(tree)[0].props, { api, categoryId: "cat", productId: "model", projectId: "one", principalId: "me", readVersion: 9 });
  assert.equal(handoffs(tree).length, 1); assert.deepEqual(handoffs(tree)[0].props, panes(tree)[0].props);
  assert.match(markup(tree), /阶段正式评审读集尚未接入/);
  const anchors = elements(tree, e => e.type === "a"); assert.equal(anchors.length, 3);
  for (const anchor of anchors) { const params = new URLSearchParams(anchor.props.href); assert.equal(params.get("project"), "one"); assert.equal(params.get("category"), "cat"); assert.equal(params.get("product"), "model"); }
  const release = anchors.find(e => e.props.children === "发布包、专业决定与外部移交办理"); assert.equal(new URLSearchParams(release.props.href).get("view"), "builds"); assert.equal(new URLSearchParams(release.props.href).get("task"), "prepare");
  const next = entry("next"), nextApi = async () => {}; next.category.id = "next-cat"; next.product.id = "next-model";
  component.setProps({ entry: next, api: nextApi, session: { name: "另一人", principal_id: "other" }, readVersion: 10 }); tree = component.render();
  assert.deepEqual(panes(tree)[0].props, { api: nextApi, categoryId: "next-cat", productId: "next-model", projectId: "next", principalId: "other", readVersion: 10 });
  assert.deepEqual(handoffs(tree)[0].props, panes(tree)[0].props);
  elements(tree, e => e.props?.id === "project-tab-now")[0].props.onClick(); tree = component.render(); assert.equal(panes(tree).length, 0);
  assert.equal(handoffs(tree).length, 0);
});
test("workspace primary tabs stay in front, secondary entries open from 更多, and arrow keys stay inside the visible group", () => {
  const component = driver(ProjectWorkspace, { entry: entries[0], api: async () => {}, session: { name: "本人", principal_id: "me" }, today: "2026-10-18", onBack() {}, onOpenWorkbench() {} });
  let tree = component.render();
  const primary = () => elements(tree, element => element.props?.role === "tablist" && element.props["aria-label"] === "项目工作区视图")[0];
  const more = () => elements(tree, element => element.props?.id === "project-more")[0];
  assert.deepEqual(elements(primary(), element => element.props?.role === "tab").map(element => element.props.children), ["现在", "Builds", "问题", "工作"]);
  assert.equal(more().props.hidden, true);
  assert.match(markup(more()), /工程与制造准备/);
  assert.match(markup(more()), /阶段与门禁/);
  assert.match(markup(more()), /尚未接入/);
  assert.match(markup(more()), /评审与交接/);
  assert.match(markup(more()), /资料/);
  assert.doesNotMatch(markup(primary()), /阶段与门禁|工程与制造准备|评审与交接|资料/);
  primary().props.onKeyDown({ key: "ArrowRight", preventDefault() {} }); tree = component.render();
  assert.equal(elements(tree, element => element.props?.id === "project-tab-builds")[0].props["aria-selected"], true);
  primary().props.onKeyDown({ key: "End", preventDefault() {} }); tree = component.render();
  assert.equal(elements(tree, element => element.props?.id === "project-tab-plan")[0].props["aria-selected"], true);
  primary().props.onKeyDown({ key: "Home", preventDefault() {} }); tree = component.render();
  assert.equal(elements(tree, element => element.props?.id === "project-tab-now")[0].props["aria-selected"], true);
  elements(tree, element => element.props?.["aria-controls"] === "project-more")[0].props.onClick(); tree = component.render();
  assert.equal(more().props.hidden, false);
  more().props.onKeyDown({ key: "ArrowRight", preventDefault() {} }); tree = component.render();
  assert.equal(elements(tree, element => element.props?.id === "project-tab-prep")[0].props["aria-selected"], true);
  more().props.onKeyDown({ key: "ArrowRight", preventDefault() {} }); tree = component.render();
  assert.equal(elements(tree, element => element.props?.id === "project-tab-gates")[0].props["aria-selected"], true);
  assert.match(markup(tree), /尚未接入。阶段模板与门禁规则结果还没有读集/);
  elements(tree, element => element.props?.id === "project-tab-issues")[0].props.onClick(); tree = component.render();
  const issue = elements(tree, element => element.type === "a").find(element => element.props.children?.[0] === "办理本项目问题与变更" || element.props.children === "办理本项目问题与变更");
  assert.equal(new URLSearchParams(issue.props.href).get("view"), "issues");
  elements(tree, element => element.props?.id === "project-tab-builds")[0].props.onClick(); tree = component.render();
  elements(tree, element => element.type === "button" && element.props.children?.[0] === "打开工程与制造准备")[0].props.onClick(); tree = component.render();
  assert.equal(elements(tree, element => element.props?.id === "project-tab-prep")[0].props["aria-selected"], true);
  assert.match(markup(tree), /草稿不代替当前准备度或正式发布/);
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
