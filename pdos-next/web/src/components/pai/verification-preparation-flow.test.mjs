import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
let hooks;
const equal = (a, b) => a && b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
const shim = { ...React,
  useState(initial) { const state = hooks, i = state.index++; if (!(i in state.values)) state.values[i] = typeof initial === "function" ? initial() : initial; return [state.values[i], value => { state.values[i] = typeof value === "function" ? value(state.values[i]) : value; }]; },
  useRef(initial) { const state = hooks, i = state.index++; return state.values[i] ??= { current: initial }; },
  useCallback(value, deps) { const state = hooks, i = state.index++, old = state.values[i]; if (!old || !equal(old.deps, deps)) state.values[i] = { value, deps }; return state.values[i].value; },
  useEffect(effect, deps) { const state = hooks, i = state.index++, old = state.values[i]; if (!old || !equal(old.deps, deps)) state.effects.push(() => { old?.cleanup?.(); state.values[i] = { deps, cleanup: effect() }; }); },
};
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: {} };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (!filename) throw new Error("Test module missing");
  if (modules.has(filename)) return modules.get(filename).exports;
  const value = new Module(filename); modules.set(filename, value);
  value.require = name => name === "react" ? shim : name === "next/link" ? { __esModule: true, default: "a" } : name === "@/components/ui/button" ? { Button: "button" }
    : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => "svg" })
    : name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  value._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return value.exports;
}
const { RunCandidates } = load(path.join(directory, "run-candidates.tsx"));
const { VerificationPreparationAction } = load(path.join(directory, "verification-preparation-action.tsx"));
const storage = new Map();
globalThis.localStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
const id = n => `${String(n).padStart(8, "0")}-1111-4111-8111-111111111111`;
const category = id(1), product = id(2), project = id(3), runId = id(4), eventId = id(5), buildId = id(6), prepId = id(7);
const tick = () => new Promise(resolve => setImmediate(resolve));
const text = node => typeof node === "string" || typeof node === "number" ? String(node) : Array.isArray(node) ? node.map(text).join("") : node && typeof node === "object" ? text(node.props?.children) : "";
const nodes = (node, predicate) => !node || typeof node !== "object" ? [] : Array.isArray(node) ? node.flatMap(value => nodes(value, predicate)) : [...(predicate(node) ? [node] : []), ...nodes(node.props?.children, predicate)];
function session(Component, props) {
  const states = new Map(); let tree, live;
  function expand(node, key) {
    if (!node || typeof node !== "object") return node;
    if (Array.isArray(node)) return node.map((value, i) => expand(value, `${key}.${i}`));
    if (typeof node.type === "function") {
      const identity = `${key}:${node.type.name}:${node.key ?? ""}`; live.add(identity);
      let state = states.get(identity); if (!state) { state = { values: [], index: 0, effects: [] }; states.set(identity, state); }
      state.index = 0; state.effects = []; hooks = state;
      let result; try { result = node.type(node.props); } finally { hooks = null; }
      return expand(result, identity);
    }
    return React.cloneElement(node, {}, expand(node.props?.children, `${key}.children`));
  }
  function render() { live = new Set(); tree = expand(React.createElement(Component, props), "root"); for (const [key, state] of states) if (!live.has(key)) { state.values.forEach(value => value?.cleanup?.()); states.delete(key); } return tree; }
  return {
    render, text: () => text(render()), nodes: predicate => nodes(render(), predicate),
    async settle() { for (let i = 0; i < 12; i++) { await tick(); render(); for (const state of states.values()) { const effects = state.effects; state.effects = []; effects.forEach(effect => effect()); } } return tree; },
    async click(label) { const button = nodes(render(), node => typeof node.props?.onClick === "function" && text(node.props.children) === label)[0]; assert.ok(button, label); assert.ok(!button.props.disabled, `${label} enabled`); button.props.onClick({ currentTarget: { focus() {} }, preventDefault() {} }); return this.settle(); },
    unmount() { for (const state of states.values()) state.values.forEach(value => value?.cleanup?.()); states.clear(); },
  };
}
const source = { artifact_id: id(10), expected_revision: 2 }, authoritySource = { artifact_id: id(11), expected_revision: 3 };
const build = { id: buildId, revision: 2, project_id: project, project_revision: 1, project_name: "合成项目", name: "密封复验 D16-03", purpose: "复验", status: "planned", type: "prototype", source_status: "current", planned_quantity: "6", unit: "件", planned_start: null, planned_end: null, created_at: "2026-10-29T00:00:00Z", previous_build_id: null, owner_id: id(12), visibility: "category", required_source_read_set: [source], engineering_configuration: { id: id(13), revision: 3, name: "工程配置A", status: "draft" }, manufacturing_configuration: { id: id(14), revision: 4, name: "制造配置B", status: "draft" } };
const target = { id: buildId, revision: 2, product_id: product, project_id: project, engineering_configuration: { id: id(13), revision: 3 }, manufacturing_configuration: { id: id(14), revision: 4 } };
const payload = { request_id: id(15), expected_request_revision: 0, build_id: buildId, expected_build_revision: 2, title: "更换密封圈复验", purpose: "核对改善措施后的气密性", return_form: "测试记录", reason: "沿用已选历史经验准备", sources: [{ ...source, line: 1, quote: "压力保持十分钟" }], items: [{ id: "pressure", feature: "气密性", sample_count: 6, method: null, criterion: null, criterion_source: null, criterion_text: null }] };
const command = { command_id: id(16), idempotency_key: "real-model-call-and-response-index", category_id: category, product_id: product, operation: "verification.preparation.record", expected_revision: 5, source_read_set: [source], payload };
const receipt = { id: id(17), subject_id: prepId, subject_revision: 1, subject_type: "verification_preparation", operation: command.operation, result: {} };
const fixed = { receipt_id: receipt.id, preparation_id: prepId, expected_preparation_revision: 1, preparation_sha256: "a".repeat(64) };
const candidate = { kind: "verification_preparation", target, event_id: eventId, sequence: 1, operation: command.operation, command_id: command.command_id, idempotency_key: command.idempotency_key, state: "pending", command, receipt: null, preparation: null, basis_count: 2 };
const preparation = { ...payload, id: prepId, revision: 1, build_revision: 2, project_id: project, sha256: fixed.preparation_sha256, input_snapshot: payload, source_status: "current", required_source_read_set: [source], capabilities: { request_create: true }, authority: { request_create: { required_source_read_set: [authoritySource] } } };
function port({ preparationMode = "success", requestMode = "success", unrelatedRequest = false, multipleBuilds = false } = {}) {
  let adopted = false, saved = null; const calls = [], posts = [];
  return { calls, posts, async api(route, body) {
    calls.push({ route, body });
    if (route.includes("/candidates")) return { run_id: runId, items: [{ ...candidate, ...(adopted ? { state: "adopted", receipt, preparation: fixed } : {}) }], next_cursor: null };
    if (route.includes("/builds?")) return { items: [build, ...(multipleBuilds ? [{ ...build, id: id(30), name: "另一轮复验" }] : [])], unavailable_count: 0, has_more: false };
    if (route.endsWith("/workspace")) return { product: { id: product, revision: 6 } };
    if (route.includes("/verification-professional")) return { preparations: adopted ? [preparation] : [], requests: saved ? [...(unrelatedRequest ? [{ ...saved, id: id(28), request_id: id(29) }] : []), saved] : [], current_by_request: {}, has_more: false, unavailable_count: 0 };
    if (route.endsWith("/preview")) return { command: { ...body, payload: { ...body.payload, confirmation_token: "real-native-preview-token" } }, expires_at: "2099-01-01T00:00:00Z", review: { effect: "保存本次准备", after: { input_snapshot: payload } } };
    assert.equal(route, "v1/commands"); posts.push(structuredClone(body));
    if (body.operation === "verification.preparation.record") { adopted = true; if (preparationMode === "after_commit" && posts.length === 1) throw Error("Failed to fetch"); return receipt; }
    assert.equal(body.operation, "verification.request.create");
    if (requestMode === "before_commit" && posts.filter(row => row.operation === body.operation).length === 1) throw Error("Failed to fetch");
    saved = { id: id(18), request_id: body.payload.request_id, revision: 1, preparation_id: prepId, preparation_revision: 1, preparation_sha256: fixed.preparation_sha256, project_id: project, status: "draft", zero_occupancy: true, is_current: true, items: payload.items, documents: [] };
    if (requestMode === "after_commit" && posts.filter(row => row.operation === body.operation).length === 1) throw Error("Failed to fetch");
    return { id: id(19), subject_id: saved.id, subject_type: "verification_request", operation: body.operation, result: {} };
  } };
}
const panel = api => session(RunCandidates, { api, categoryId: category, principalId: "owner", runId, eventSequence: 1 });
async function adopt(view) { await view.settle(); await view.click("核对并预览"); await view.click("确认保存"); }

test("actual preparation card uses native preview/confirm then one Human request command and reopening only reads", async () => {
  storage.clear(); const p = port(), view = panel(p.api);
  try {
    await view.settle(); assert.equal(p.posts.length, 0); assert.match(view.text(), /更换密封圈复验|工程配置A/);
    await view.click("核对并预览"); assert.equal(p.posts.length, 0);
    assert.equal(p.calls.find(row => row.route.endsWith("/preview")).body.payload.prepared_by_run_id, undefined);
    await view.click("确认保存"); assert.equal(p.posts.length, 1); assert.match(view.text(), /已保存 v1/);
    await view.click("创建复验请求"); assert.equal(p.posts.length, 2);
    const native = p.posts[1]; assert.equal(native.operation, "verification.request.create");
    assert.equal(native.payload.preparation_id, prepId); assert.equal(native.payload.preparation_sha256, fixed.preparation_sha256);
    assert.equal(native.expected_revision, 6); assert.deepEqual(native.source_read_set, [source, authoritySource]);
    assert.equal(native.payload.prepared_event_id, undefined); assert.equal(native.payload.prepared_by_run_id, undefined);
    assert.match(view.text(), /打开复验请求/); assert.ok(p.calls.every(row => !row.route.includes("agent-runs") || row.body === undefined));
    await view.click("刷新材料"); assert.equal(p.posts.length, 2); assert.equal(storage.size, 0);
    assert.equal(view.nodes(node => text(node.props?.children) === "创建复验请求")[0].props.disabled, true);
  } finally { view.unmount(); }
});
test("lost preparation response is recovered from the actual candidate receipt without reposting", async () => {
  storage.clear(); const p = port({ preparationMode: "after_commit" }), view = panel(p.api);
  try { await adopt(view); assert.equal(p.posts.length, 1); assert.equal(storage.size, 1); await view.click("刷新材料"); assert.equal(p.posts.length, 1); assert.equal(storage.size, 0); assert.match(view.text(), /已保存 v1/); } finally { view.unmount(); }
});
test("lost request response reads the actual saved request, clears the original journal and never calls a model or posts twice", async () => {
  storage.clear(); const p = port({ requestMode: "after_commit" }), view = panel(p.api);
  try { await adopt(view); await view.click("创建复验请求"); assert.equal(p.posts.length, 2); assert.equal(storage.size, 1); await view.click("刷新材料"); assert.equal(p.posts.length, 2); assert.equal(storage.size, 0); assert.match(view.text(), /已读回复验请求|打开复验请求/); } finally { view.unmount(); }
});
test("request recovery selects its original logical request even when another request uses the same preparation", async () => {
  storage.clear(); const p = port({ requestMode: "after_commit", unrelatedRequest: true }), view = panel(p.api);
  try { await adopt(view); await view.click("创建复验请求"); assert.equal(storage.size, 1); await view.click("刷新材料"); assert.equal(p.posts.length, 2); assert.equal(storage.size, 0); assert.match(view.text(), /已读回复验请求/); } finally { view.unmount(); }
});
test("an uncommitted native request is replayed only by explicit click with exactly the same original body", async () => {
  storage.clear(); const p = port({ requestMode: "before_commit" }), view = panel(p.api);
  try { await adopt(view); await view.click("创建复验请求"); const original = structuredClone(p.posts[1]); assert.equal(storage.size, 1); await view.click("核对原请求"); assert.equal(p.posts.length, 3); assert.deepEqual(p.posts[2], original); assert.equal(storage.size, 0); assert.match(view.text(), /打开复验请求/); } finally { view.unmount(); }
});
test("case action reads current project Builds before explicit selection and delegates one closed continuation intent", async () => {
  storage.clear(); const p = port(), started = [];
  const run = { run_id: runId, status: "completed", reverted: false, product_id: product, project_id: project, result: { result: { assistant: { task_result: { version: 1, format: "cases", rows: [{ cells: { measures: { status: "recorded", citation_id: id(20) } } }] }, sources: [{ citation_id: id(20), title: "历史密封问题", source_revision: 3 }] } } } };
  const view = session(VerificationPreparationAction, { api: p.api, categoryId: category, run, additionalSources: [source], initialBuildId: buildId, onStart: value => started.push(value) });
  try { await view.settle(); assert.equal(p.calls.length, 0); await view.click("准备复验请求"); assert.match(view.text(), /工程配置A|制造配置B/); assert.equal(started.length, 0); await view.click("开始准备"); assert.equal(started.length, 1); assert.deepEqual(started[0].body.verification_action, { selection: target, citation_ids: [id(20)] }); assert.equal(started[0].body.product_id, undefined); assert.equal(started[0].body.project_id, undefined); assert.equal(started[0].body.continue_from_run_id, runId); assert.equal(p.posts.length, 0); } finally { view.unmount(); }
});

test("one readable Build is preselected and displayed; starting confirms that target", async () => {
  const p = port(), started = [];
  const run = { run_id: runId, status: "completed", reverted: false, product_id: product, project_id: project, result: { result: { assistant: { task_result: { version: 1, format: "cases", rows: [{ cells: { measures: { status: "recorded", citation_id: id(20) } } }] }, sources: [{ citation_id: id(20), title: "历史问题", source_revision: 1 }] } } } };
  const view = session(VerificationPreparationAction, { api: p.api, categoryId: category, run, onStart: value => started.push(value) });
  try {
    await view.settle(); await view.click("准备复验请求");
    const select = view.nodes(node => node.type === "select")[0]; assert.equal(select.props.value, buildId);
    assert.equal(view.nodes(node => text(node.props?.children) === "开始准备")[0].props.disabled, false);
    assert.match(view.text(), /工程配置A|制造配置B/);
    await view.click("开始准备"); assert.equal(started.length, 1); assert.deepEqual(started[0].body.verification_action.selection, target);
    const checkbox = view.nodes(node => node.type === "input" && node.props.type === "checkbox")[0];
    checkbox.props.onChange({ target: { checked: false } }); await view.settle();
    assert.equal(view.nodes(node => text(node.props?.children) === "开始准备")[0].props.disabled, true);
    assert.equal(started.length, 1);
  } finally { view.unmount(); }
});

test("multiple readable Builds without page context leave the target for user selection", async () => {
  const p = port({ multipleBuilds: true });
  const run = { run_id: runId, status: "completed", reverted: false, product_id: product, project_id: project, result: { result: { assistant: { task_result: { version: 1, format: "cases", rows: [{ cells: { measures: { status: "recorded", citation_id: id(20) } } }] }, sources: [{ citation_id: id(20), title: "历史问题", source_revision: 1 }] } } } };
  const view = session(VerificationPreparationAction, { api: p.api, categoryId: category, run, onStart() { throw Error("No target selected"); } });
  try { await view.settle(); await view.click("准备复验请求"); assert.equal(view.nodes(node => node.type === "select")[0].props.value, ""); assert.equal(view.nodes(node => text(node.props?.children) === "开始准备")[0].props.disabled, true); } finally { view.unmount(); }
});
