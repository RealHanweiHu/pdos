import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Test-only state/effect dispatcher; SSR delegates unchanged. */
const reactShim = { ...React,
  useState(initial) {
    if (!hooks) return React.useState(initial);
    const own = hooks, index = own.index++;
    if (!(index in own.values)) own.values[index] = typeof initial === "function" ? initial() : initial;
    return [own.values[index], value => { own.values[index] = typeof value === "function" ? value(own.values[index]) : value; }];
  },
  useRef(initial) {
    if (!hooks) return React.useRef(initial);
    const index = hooks.index++;
    if (!(index in hooks.values)) hooks.values[index] = { current: initial };
    return hooks.values[index];
  },
  useCallback(callback, dependencies) { return hooks ? callback : React.useCallback(callback, dependencies); },
  useEffect(callback, dependencies) { if (!hooks) React.useEffect(callback, dependencies); else hooks.effects.push(callback); },
};
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule:true, default:new Proxy({}, {get:(_,key)=>String(key)}) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? reactShim
    : specifier === "@phosphor-icons/react" ? Object.fromEntries(["ArrowClockwise", "CalendarBlank", "CheckCircle", "Plus", "Trash"].map(key => [key, () => React.createElement("svg")]))
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}
const { ProjectPlanning } = load(path.join(directory, "project-planning.tsx"));
const { restorePlanningDraft, projectCreationMoved, planningStorageKey } = load(path.join(directory, "project-planning-state.ts"));
const { blankProjectDraft, buildSchedule } = load(path.join(webRoot, "src/lib/project-plan-view.ts"));
const product = { id: "11111111-1111-4111-8111-111111111111", name: "合成型号", purpose: "合成用途", revision: 4 };
const principal = "22222222-2222-4222-8222-222222222222";
const storageKey = `pdos-next:project-plan:${principal}:${product.id}`;
const draft = { ...blankProjectDraft(product.purpose), name: "历史创建名称", scope: "原范围", definitionId: "old-definition", visibility: "category",
  projectId: "existing-project", startUtc: "2026-10-12T01:00", timezone: "Asia/Shanghai", calendarVersion: "retained-v3", holidays: "2026-10-15",
  tasks: [{ key: "task-1", title: "原工程任务", discipline: "engineering", depends_on: [], minimum: "30", maximum: "60", basis: "本人合成估计" },
    { key: "task-2", title: "原 NPI 任务", discipline: "npi", depends_on: ["task-1"], minimum: "", maximum: "", basis: "尚未知" }], reason: "保留的首计划说明" };
const project = { id: draft.projectId, name: "G0 项目", purpose: "项目用途", scope: "G0 范围", owner_id: principal, visibility: "category", revision: 2,
  source_status: "current", definition: { id: "definition", title: "固定定义", revision: 2 }, required_source_read_set: [{ artifact_id: "proof", expected_revision: 3 }],
  proposals: [], plan: null, tasks: [], work_packages: [] };
const pending = (operation, stage = "execute") => ({ stage, command: { command_id: "original-command", idempotency_key: "original-key", operation,
  product_id: product.id, expected_revision: 4, source_read_set: project.required_source_read_set, payload: { project_id: project.id, confirmation_token: "original-token" } } });
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
function session(props) {
  const element = ProjectPlanning(props), state = { index: 0, values: [], effects: [] };
  return { render() { hooks = state; state.index = 0; state.effects = []; try { return element.type(element.props); } finally { hooks = null; } },
    mount() { state.effects.forEach(effect => effect()); } };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
async function withStorage(local, callback) {
  const original = globalThis.localStorage, entries = new Map([[storageKey, JSON.stringify(local)], ["unrelated-plan", "untouched"]]);
  globalThis.localStorage = { getItem: key => entries.get(key) ?? null, setItem: (key, value) => entries.set(key, value) };
  try { await callback(entries); } finally { globalThis.localStorage = original; }
}
async function mounted(local, api, callback, extraProps = {}) {
  await withStorage(local, async entries => {
    const component = session({ product, principalId: principal, api, onSaved() {}, ...extraProps });
    component.render(); component.mount(); await tick(); await callback(component, entries);
  });
}

test("direct project hydration reads only that project and migrates only its matching legacy input", async () => {
  const calls = [];
  await mounted({ draft, pending: null }, async (path, body) => {
    calls.push({ path, body }); return { items: [project], has_more: false, unavailable_count: 0 };
  }, async (component, entries) => {
    assert.deepEqual(calls, [{ path: `v1/products/${product.id}/projects/${project.id}`, body: undefined }]);
    assert.deepEqual(JSON.parse(entries.get(planningStorageKey(principal, product.id, project.id))), { draft, pending: null });
    assert.deepEqual(JSON.parse(entries.get(storageKey)), { draft, pending: null });
    const tree = component.render();
    assert.ok(elements(tree, e => e.type === "select" && e.props.value === project.id && e.props.disabled).length);
    assert.ok(elements(tree, e => e.type?.name === "PlanTaskEditor" && e.props.draft.tasks[0].title === "原工程任务").length);
    assert.equal(elements(tree, e => e.props?.id === `project-editor-pane-${product.id}`)[0].props.hidden, true);
  }, { projectId: project.id, categoryId: "synthetic-category" });
});

test("other project input and unknown pending save remain in their old cache, never populate the direct editor", async () => {
  const local = { draft: { ...draft, projectId: "another-project" }, pending: pending("work.plan.propose") };
  local.pending.command.payload.project_id = "another-project";
  const calls = [];
  await mounted(local, async (path, body) => { calls.push({ path, body }); return { items: [project], has_more: false, unavailable_count: 0 }; }, async (component, entries) => {
    const tree = component.render();
    assert.deepEqual(JSON.parse(entries.get(storageKey)), local);
    assert.equal(entries.has(planningStorageKey(principal, product.id, project.id)), false);
    assert.equal(elements(tree, e => e.props?.children === "按原请求重试").length, 0);
    assert.equal(elements(tree, e => e.type?.name === "PlanTaskEditor" && e.props.draft.tasks[0].title === "原工程任务").length, 0);
    assert.equal(calls.filter(call => call.body).length, 0);
  }, { projectId: project.id });
});

test("direct cache binding rejects a pending request to another project while preserving the original value", () => {
  const local = { draft, pending: pending("work.plan.apply") };
  local.pending.command.payload.project_id = "another-project";
  const before = structuredClone(local);
  assert.equal(restorePlanningDraft(local, product.id, project.id), null);
  assert.deepEqual(local, before);
  assert.notEqual(planningStorageKey(principal, product.id, project.id), planningStorageKey(principal, product.id, "another-project"));
});

test("direct project reload retains the unknown original save and only an explicit retry replays it unchanged", async () => {
  const waiting = pending("work.plan.apply"), calls = [];
  await mounted({ draft, pending: waiting }, async (path, body) => {
    calls.push({ path, body });
    return body ? { id: "original-receipt", subject_type: "plan_revision", subject_id: "actual-plan" }
      : { items: [project], has_more: false, unavailable_count: 0 };
  }, async (component, entries) => {
    const scopedKey = planningStorageKey(principal, product.id, project.id);
    assert.equal(calls.filter(call => call.body).length, 0);
    assert.deepEqual(JSON.parse(entries.get(scopedKey)), { draft, pending: waiting });
    const retry = elements(component.render(), e => e.props?.children === "按原请求重试")[0];
    await retry.props.onClick(); await tick();
    assert.deepEqual(calls.filter(call => call.body), [{ path: "v1/commands", body: waiting.command }]);
    assert.deepEqual(JSON.parse(entries.get(scopedKey)), { draft, pending: null });
  }, { projectId: project.id });
});

test("direct read failure keeps input, avoids a false empty project and refreshes without issuing a command", async () => {
  let fails = true; const calls = [];
  await mounted({ draft, pending: null }, async (path, body) => {
    calls.push({ path, body });
    if (fails) throw Object.assign(new Error("合成项目暂不可读"), { status: 503 });
    return { items: [project], has_more: false, unavailable_count: 0 };
  }, async (component, entries) => {
    let tree = component.render();
    assert.ok(elements(tree, e => e.props?.role === "alert" && e.props.children === "合成项目暂不可读").length);
    assert.equal(elements(tree, e => e.type === "p" && String(e.props.children).includes("当前范围尚无可见项目")).length, 0);
    assert.deepEqual(JSON.parse(entries.get(storageKey)), { draft, pending: null });
    fails = false;
    elements(tree, e => e.props?.children?.some?.(child => child === "刷新项目"))[0].props.onClick();
    await tick(); tree = component.render();
    assert.ok(elements(tree, e => e.type === "h4" && e.props.children === project.name).length);
    assert.equal(calls.filter(call => call.body).length, 0);
  }, { projectId: project.id });
});

for (const stage of ["preview", "execute"]) test(`retire ${stage} project.create only, preserving every plan draft field`, () => {
  const local = { draft, pending: pending("project.create", stage) }, before = structuredClone(local);
  const restored = restorePlanningDraft(local, product.id);
  assert.equal(restored.retiredCreation, true); assert.equal(restored.pending, null); assert.deepEqual(restored.draft, draft); assert.deepEqual(local, before);
});
test("malformed retired command cannot discard a valid plan draft", () => {
  const restored = restorePlanningDraft({ draft, pending: { command: { operation: "project.create" } } }, product.id);
  assert.deepEqual(restored.draft, draft); assert.equal(restored.pending, null);
});
for (const [operation, stage] of [["work.plan.propose", "execute"], ["work.plan.apply", "preview"], ["work.plan.apply", "execute"]]) {
  test(`retain exact ${operation} ${stage} retry and source set`, () => {
    const local = { draft, pending: pending(operation, stage) };
    assert.deepEqual(restorePlanningDraft(local, product.id), { ...local, retiredCreation: false });
    assert.equal(restorePlanningDraft(local, "another-product"), null);
  });
}
test("retired cache hydration persists request removal, renders G0 guidance and performs read-only project refresh", async () => {
  const calls = [];
  await mounted({ draft, pending: pending("project.create") }, async (path, body) => { calls.push({ path, body }); return { items: [project], has_more: false, unavailable_count: 0 }; }, async (component, entries) => {
    assert.deepEqual(calls, [{ path: `v1/products/${product.id}/projects`, body: undefined }]);
    assert.deepEqual(JSON.parse(entries.get(storageKey)), { draft, pending: null }); assert.equal(entries.get("unrelated-plan"), "untouched");
    const tree = component.render();
    assert.ok(elements(tree, e => e.props?.role === "status" && e.props.children === projectCreationMoved).length);
    assert.equal(elements(tree, e => e.props?.children === "按原请求重试").length, 0);
    assert.equal(elements(tree, e => e.type === "input" && e.props.value === "历史创建名称").length, 0);
    assert.equal(elements(tree, e => e.type === "form").length, 1);
    assert.ok(elements(tree, e => e.type === "h4" && e.props.children === "G0 项目").length);
    assert.ok(elements(tree, e => e.type?.name === "PlanTaskEditor" && e.props.draft.tasks[0].title === "原工程任务").length);
  });
});
test("retained first-plan request retries unchanged without rebuilding or replacing its draft", async () => {
  const waiting = pending("work.plan.propose"), calls = [];
  await mounted({ draft, pending: waiting }, async (path, body) => { calls.push({ path, body }); if (body) return { id: "receipt", subject_type: "plan_proposal", subject_id: "proposal" }; return { items: [project], has_more: false, unavailable_count: 0 }; }, async (component, entries) => {
    const retry = elements(component.render(), e => e.props?.children === "按原请求重试")[0]; await retry.props.onClick(); await tick();
    const writes = calls.filter(call => call.body); assert.equal(writes.length, 1); assert.deepEqual(writes[0], { path: "v1/commands", body: waiting.command });
    assert.deepEqual(JSON.parse(entries.get(storageKey)), { draft, pending: null });
  });
});
test("existing G0 project can still save a first-plan proposal using pinned source reads", async () => {
  const calls = [];
  await mounted({ draft, pending: null }, async (path, body) => { calls.push({ path, body }); if (body) return { id: "receipt", subject_type: "plan_proposal", subject_id: "proposal" }; return { items: [project], has_more: false, unavailable_count: 0 }; }, async component => {
    elements(component.render(), e => e.type === "form")[0].props.onSubmit({ preventDefault() {} }); await tick();
    const writes = calls.filter(call => call.body); assert.equal(writes.length, 1); assert.equal(writes[0].body.operation, "work.plan.propose");
    assert.deepEqual(writes[0].body.source_read_set, project.required_source_read_set);
    assert.deepEqual(writes[0].body.payload, { project_id: project.id, expected_project_revision: project.revision, base_plan_id: null, resource_demands: [], schedule: buildSchedule(draft), reason: draft.reason });
  });
});
test("first-plan apply still previews then executes the exact confirmed request", async () => {
  const calls = [], schedule = buildSchedule(draft);
  const forecast = { calendar_ref: schedule.calendar, tasks: [], earliest_finish: null, latest_finish: null, warnings: [] };
  const proposal = { id: "proposal", revision: 1, reason: "合成计划", input_snapshot: schedule, forecast, project_revision: project.revision };
  await mounted({ draft, pending: null }, async (path, body) => {
    calls.push({ path, body });
    if (!body) return { items: [{ ...project, proposals: [proposal] }], has_more: false, unavailable_count: 0 };
    if (path.endsWith("preview")) return { command: { ...body, payload: { ...body.payload, confirmation_token: "plan-token" } },
      confirmation_token: "plan-token", expires_at: "2099-01-01T00:00:00Z",
      review: { operation: "work.plan.apply", name: project.name, effect: "应用首计划", forecast, input_snapshot: schedule } };
    return { id: "receipt", subject_type: "plan_revision", subject_id: "plan" };
  }, async component => {
    elements(component.render(), e => e.type?.name === "PlanAlternatives")[0].props.onApply(proposal, { focus() {} }); await tick();
    const confirmed = elements(component.render(), e => e.props?.children === "确认应用此计划")[0];
    assert.ok(confirmed); confirmed.props.onClick(); await tick();
    const writes = calls.filter(call => call.body); assert.equal(writes.length, 2);
    assert.equal(writes[0].path, "v1/commands/preview"); assert.equal(writes[1].path, "v1/commands");
    assert.equal(writes[0].body.operation, "work.plan.apply");
    assert.deepEqual(writes[1].body, { ...writes[0].body, payload: { ...writes[0].body.payload, confirmation_token: "plan-token" } });
  });
});
test("initial rendering exposes G0 route guidance without a project creation control or network write", () => {
  const output = renderToStaticMarkup(React.createElement(ProjectPlanning, { product, principalId: principal, api: () => { throw Error("No render IO"); }, onSaved() {} }));
  assert.ok(output.includes("编辑计划候选")); assert.ok(output.includes("准备计划候选"));
  assert.match(output, /id="project-editor-pane-[^"]+" hidden/);
  assert.equal(output.includes("核对范围并建立项目"), false); assert.equal(output.includes("项目名称<input"), false);
});

test("a newly added task never reuses the key of a removed historical task", async()=>{
  await mounted({draft,pending:null},async()=>({items:[project],has_more:false,unavailable_count:0}),async component=>{
    const editor=elements(component.render(),e=>e.type?.name==="PlanTaskEditor")[0];
    editor.props.onChange({...draft,tasks:[draft.tasks[0]]});
    elements(component.render(),e=>e.props?.children?.some?.(c=>c==="新增任务"))[0].props.onClick();
    const next=elements(component.render(),e=>e.type?.name==="PlanTaskEditor")[0].props.draft.tasks;
    assert.equal(next.length,2);assert.notEqual(next[1].key,draft.tasks[1].key);assert.notEqual(next[1].key,draft.tasks[0].key);
  });
});
