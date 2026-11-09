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
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { fileName: filename, compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
// D37 ⑦ / D76 / D41: overview and manager cockpit render server read models only.
const { ProjectOverviewView } = load(path.join(directory, "project-overview.tsx"));
const { ProjectManagerCockpit } = load(path.join(directory, "project-manager-cockpit.tsx"));
const lib = load(path.join(webRoot, "src/lib/project-cockpit.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: id(3) };
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
const person = (n, name) => ({ id: id(n), name });
const unavailable = reason => ({ available: false, reason });
function overview(changes = {}) {
  return {
    version: "project-overview/v1", as_of: "2026-11-09T08:00:00Z", rules: [{ id: "cockpit.actions", version: 1, text: "需要办理规则" }],
    project: { id: scope.projectId, revision: 1, name: "合成项目", status: "active", visibility: "category", owner: person(10, "合成负责人"), product: { id: scope.productId, name: "合成型号" } },
    stage: { available: true, reason: null, stages: [{ key: "concept", name: "概念", status: "passed" }, { key: "planning", name: "计划", status: "current" }], current: { key: "planning", name: "计划" }, completed: false },
    health: { state: "pending_approval", label: "待批准", reason: "出口条件已具备，等待具名阶段决定", rule: { id: "project.health.pending_approval", version: 1 }, basis: { gate_state: "READY", conditions: [], overdue_commitments: [], review_pending: true, stage_adopted: true } },
    next_node: { name: "计划出口", times: { task_key: null, baseline: null, forecast: null, commitments: [], actual: null }, slip: { state: "unknown", reason: "关联门禁里程碑没有可读预测" }, exit_conditions: [{ key: "baseline", label: "当前计划的具名批准基线", state: "UNKNOWN", state_label: "未知" }], exit_outcomes: { available: false, label: "阶段节点未建", reason: "阶段节点与框架出口成果尚未建立（W6 ④ D36）" } },
    actions: { available: true, partial_reasons: [], items: [
      { kind: "decide", kind_label: "待决定", type: "stage_review", title: "阶段评审待具名决定：计划", reason: "只由项目负责人具名办理", responsible: person(10, "合成负责人"), due_at: null, target: { view: "gates", panel: null }, source: { type: "stage_review", id: null, revision: null } },
      { kind: "receive", kind_label: "待接收", type: "task_assigned", title: "合成图纸交付", reason: "等待承接人承接", responsible: person(11, "合成承接人"), due_at: null, target: { view: "tasks", panel: null }, source: { type: "task", id: id(20), revision: 2 } },
    ] },
    next_build: { available: true, build: null, not_started: 0, unavailable_count: 0 },
    key_commitments: [],
    risks: { risks: [], issues: unavailable("品质问题暂不可读"), overdue_waits: [], due_soon: [], window_days: 7 },
    team: { available: true, members: [{ principal_id: id(10), name: "合成负责人", is_owner: true, roles: ["项目经理"], lead_roles: [], open_tasks: 0 }], vacant_roles: ["品质"], roles_without_lead: [], load_note: "负载按本项目中承接人未完成的任务计数；工时未知，不合计。" },
    status_update: { latest: null, cycle: unavailable("状态更新周期尚未接入（由自动化规则提供）") },
    agent_duty: { available: true, window_days: 7, items: [], total: 0, revocable: false, revocation_note: "当前这些写入不能按运行撤回。", counts_as_todo: false },
    ...changes,
  };
}

test("overview reads one scoped model and shows missing parts as text, never as zero or invented outcomes", async () => {
  const calls = [], opened = [];
  const component = driver(ProjectOverviewView, { api: async path => { calls.push(path); return overview(); }, scope, principalId: id(10), onOpen: (...args) => opened.push(args), onWriteUpdate() {} });
  assert.match(markup(component.render()), /正在读取项目概览/);
  component.mount(); await tick(); const tree = component.render(); const html = markup(tree);
  assert.deepEqual(calls, [`v1/categories/${scope.categoryId}/products/${scope.productId}/projects/${scope.projectId}/overview`]);
  for (const text of ["待批准", "阶段节点未建", "品质问题暂不可读", "状态更新周期尚未接入", "空缺角色：品质", "工时未知", "只读，不计入待办", "P0/P1 分级未建", "合成承接人", "合成负责人（本人）"]) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html, /%|完成率|任务完成/);
  // 直接办理入口 locate the original record; the owner's own item says 去办理.
  const handles = elements(tree, e => e.type === "button" && e.props.className === "handle");
  assert.equal(handles.length, 2); assert.equal(handles[0].props.children[0], "去办理"); assert.equal(handles[1].props.children[0], "查看");
  handles[0].props.onClick(); handles[1].props.onClick();
  assert.deepEqual(opened, [["gates", null], ["tasks", null]]);
});

test("overview rejects a model for another project and keeps a retry instead of an empty page", async () => {
  let wrong = true;
  const component = driver(ProjectOverviewView, { api: async () => wrong ? overview({ project: { ...overview().project, id: id(99) } }) : overview(), scope, principalId: id(10), onOpen() {}, onWriteUpdate() {} });
  component.render(); component.mount(); await tick(); let tree = component.render();
  assert.match(markup(tree), /无法核对/); assert.doesNotMatch(markup(tree), /需要办理/);
  wrong = false; elements(tree, e => e.type === "button" && e.props.children === "重新读取")[0].props.onClick();
  component.render(); component.mount(); await tick(); tree = component.render();
  assert.match(markup(tree), /需要办理/);
});

function row(n, health, changes = {}) {
  return { project: { id: id(n), name: `合成项目 ${n}`, status: "active", visibility: "category", owner: person(10, "合成负责人"), category: { id: id(1), name: "合成品类" }, product: { id: id(2), name: "合成型号" }, set: null },
    stage: { adopted: true, stages: [{ name: "概念", status: "passed" }, { name: "计划", status: "current" }], current: "计划", completed: false },
    health: { state: health, label: { blocked: "有阻塞", unknown: "待核对", risk: "有风险", pending_approval: "待批准", normal: "正常" }[health], reason: "规则原因", rule: { id: `project.health.${health}`, version: 1 } },
    next_node: { name: "计划出口", times: { baseline: "2026-12-01", forecast: "2026-12-10", commitments: [], actual: null }, slip: { state: "late", reason: "预测晚于基线", against: ["基线"] } },
    exit_conditions: [{ key: "g0", label: "G0 立项决定与定义来源", state: "READY", state_label: "满足" }], exit_outcomes: { available: false, label: "阶段节点未建" },
    latest_update: { first_sentence: "样机已装配。", actor: person(10, "合成负责人"), created_at: "2026-11-08T00:00:00Z" }, risk_count: 2, review_pending: false, my_decision: false, ...changes };
}
const tiers = [["blocked", "有阻塞"], ["unknown", "待核对"], ["risk", "有风险"], ["pending_approval", "待批准"], ["normal", "正常"]];
function cockpit(rows) {
  return { version: "project-cockpit/v1", as_of: "2026-11-09T08:00:00Z", rules: [{ id: "cockpit.exit_conditions", version: 1, text: "出口条件规则" }],
    summary: { active: rows.length, health: tiers.map(([state, label]) => ({ state, label, count: rows.filter(r => r.health.state === state).length })), slipped_nodes: 1, my_stage_decisions: 1,
      resource_conflicts: unavailable("资源冲突读集尚未接入"), status_updates_missing: unavailable("周期未接入"), agent_exceptions: unavailable("例外未接入") },
    items: rows, unavailable_count: 0 };
}

test("cockpit is one line of text counts and health-grouped rows compared by exit conditions", async () => {
  const rows = [row(3, "blocked"), row(4, "pending_approval", { my_decision: true, review_pending: true, project: { ...row(4, "normal").project, set: { id: id(30), name: "合成项目集" } } }), row(5, "normal", { next_node: { ...row(5, "normal").next_node, slip: { state: "on_track", reason: "预测不晚于基线与承诺" } } })];
  const opened = [];
  const component = driver(ProjectManagerCockpit, { api: async () => cockpit(rows), principalId: id(10), onOpenProject: (...args) => opened.push(args) });
  component.render(); component.mount(); await tick(); let tree = component.render(); let html = markup(tree);
  for (const text of ["在办", "滑期节点", "待我决定的阶段评审", "资源冲突", "未接入", "出口条件", "G0 立项决定与定义来源 · 满足", "出口成果：阶段节点未建", "样机已装配。", "风险"]) assert.ok(html.includes(text), text);
  assert.doesNotMatch(html.replace(/<details class="rules">[\s\S]*<\/details>/, ""), /%|任务数|完成率/);
  // Grouped in the server's tier order; the unconnected metrics are never shown as 0.
  assert.deepEqual(elements(tree, e => e.type === "section" && e.props["aria-label"]?.endsWith("项目")).map(e => e.props["aria-label"]), ["有阻塞项目", "待批准项目", "正常项目"]);
  assert.equal(elements(tree, e => e.props?.className === "unavailable").length, 3);
  // Counts filter the rows; nothing in the cockpit writes.
  elements(tree, e => e.type === "button" && e.props["aria-pressed"] !== undefined && String(e.props.children).includes("待我决定"))[0].props.onClick(); tree = component.render();
  const shown = elements(tree, e => e.type?.name === "Row"); assert.equal(shown.length, 1);
  elements(shown[0].type(shown[0].props), e => e.type === "button" && e.props.className === "name")[0].props.onClick();
  assert.deepEqual(opened, [[id(1), id(4)]]);
  html = markup(tree); assert.match(html, /待我决定/);
});

test("cockpit filters by set, category and owner, and saved views stay per viewer", () => {
  const rows = [row(3, "risk", { project: { ...row(3, "risk").project, set: { id: id(30), name: "集" } } }), row(4, "normal", { project: { ...row(4, "normal").project, owner: person(11, "他人"), category: { id: id(9), name: "另一品类" } } })];
  assert.deepEqual(lib.filterRows(rows, { ...lib.emptyView, set: id(30) }).map(r => r.project.id), [id(3)]);
  assert.deepEqual(lib.filterRows(rows, { ...lib.emptyView, set: lib.UNSET }).map(r => r.project.id), [id(4)]);
  assert.deepEqual(lib.filterRows(rows, { ...lib.emptyView, category: id(9) }).map(r => r.project.id), [id(4)]);
  assert.deepEqual(lib.filterRows(rows, { ...lib.emptyView, owner: id(10) }).map(r => r.project.id), [id(3)]);
  assert.deepEqual(lib.filterRows(rows, { ...lib.emptyView, focus: "health:risk" }).map(r => r.project.id), [id(3)]);
  const store = new Map(), storage = { getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value) };
  const views = lib.saveView([], " 我的风险项目 ", { ...lib.emptyView, focus: "health:risk" });
  assert.equal(lib.writeSavedViews(storage, id(10), views), true);
  assert.deepEqual(lib.readSavedViews(storage, id(10)).map(v => v.name), ["我的风险项目"]);
  assert.deepEqual(lib.readSavedViews(storage, id(11)), []);
  store.set(lib.savedViewsKey(id(10)), "{bad json"); assert.deepEqual(lib.readSavedViews(storage, id(10)), []);
  assert.equal(lib.writeSavedViews({ setItem() { throw new Error("blocked"); } }, id(10), views), false);
  assert.deepEqual(lib.readSavedViews(null, id(10)), []);
});

test("cockpit hides prior rows synchronously on identity change and refuses malformed rows", async () => {
  const pending = [];
  const component = driver(ProjectManagerCockpit, { api: () => new Promise(resolve => pending.push(resolve)), principalId: id(10), onOpenProject() {} });
  component.render(); component.mount(); pending[0](cockpit([row(3, "normal")])); await tick();
  assert.match(markup(component.render()), /合成项目 3/);
  component.setProps({ principalId: id(11) }); assert.doesNotMatch(markup(component.render()), /合成项目 3/);
  assert.throws(() => lib.parseCockpit(cockpit([row(3, "normal"), row(3, "normal")])), /无法核对/);
  assert.throws(() => lib.parseCockpit({ ...cockpit([]), version: "other" }), /无法核对/);
  assert.equal(lib.slipText({ state: "late", reason: "预测晚于基线" }), "已滑期 · 预测晚于基线");
  assert.equal(lib.dateText(null), "未知"); assert.equal(lib.dateText("2026-11-09"), "11月09日");
});
