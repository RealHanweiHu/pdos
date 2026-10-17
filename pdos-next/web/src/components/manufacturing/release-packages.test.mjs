import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Actual React component/contract. Transport, browser storage and hooks are IO
// drivers; these checks never attest actual authority, source registration or PG.
const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Explicit isolated hook dispatcher. */
const react = { ...React,
  useState(initial) { if (!hooks) return React.useState(initial); const own = hooks, i = own.index++; if (!(i in own.slots)) own.slots[i] = typeof initial === "function" ? initial() : initial; return [own.slots[i], value => { if (!own.disposed) { own.slots[i] = typeof value === "function" ? value(own.slots[i]) : value; own.dirty = true; } }]; },
  useRef(initial) { if (!hooks) return React.useRef(initial); const i = hooks.index++; if (!(i in hooks.slots)) hooks.slots[i] = { current: initial }; return hooks.slots[i]; },
  useCallback(fn, deps) { if (!hooks) return React.useCallback(fn, deps); const i = hooks.index++; if (!same(hooks.slots[i]?.deps, deps)) hooks.slots[i] = { deps, value: fn }; return hooks.slots[i].value; },
  useMemo(fn, deps) { if (!hooks) return React.useMemo(fn, deps); const i = hooks.index++; if (!same(hooks.slots[i]?.deps, deps)) hooks.slots[i] = { deps, value: fn() }; return hooks.slots[i].value; },
  useEffect(fn, deps) { if (!hooks) return React.useEffect(fn, deps); const own = hooks, i = own.index++; if (!same(own.slots[i]?.deps, deps)) { const old = own.slots[i], next = { deps, cleanup: old?.cleanup }; own.slots[i] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = fn(); }); } },
};
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync);
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_object, key) => String(key) }) };
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { ReleasePackages, ReleasePackageReading } = load(path.join(directory, "release-packages.tsx"));
const { releaseSemantic } = load(path.join(web, "src/lib/releases.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const props = { categoryId: id(1), product: { id: id(2), revision: 3 }, projectId: id(3), principalId: id(4) };
const source = { kind: "artifact", id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const ref = n => ({ id: id(n), revision: 1 });
const range = { quantity: "10", unit: "ea", site: "固定场地", lots: null, lines: null, regions: null };
const configuration = { definition: ref(6), engineering_configuration: ref(7), manufacturing_configuration: ref(8) };
const assemble = "release.package.assemble", engineering = "release.engineering.approve";
function payload(projectId = props.projectId) { return { project_id: projectId, subject_config: configuration, release_scope: range, purpose: "固定发布用途", reason: "本人实际核对材料", sources: [source] }; }
function assessment(discipline, ready = false) { return { discipline, state: ready ? "READY" : "UNKNOWN", checks: [], blocked: [], unknown: ready ? [] : ["RELEASE_POLICY_MISSING"], conditions: [] }; }
function inputs(c, ready = false) {
  const saved = c.operation === assemble, discipline = c.operation === engineering ? "engineering" : "manufacturing";
  return { operation: c.operation, payload: releaseSemantic(c.operation, c.payload), required_source_read_set: c.source_read_set, assessments: [assessment("engineering", ready), assessment("manufacturing", ready)], authority: saved ? {} : { subject_id: props.principalId, operation: c.operation, purpose: c.payload.purpose, authorized: true, qualified: true, roles: [discipline], scope: { product_id: props.product.id, project_id: props.projectId } }, diagnostics: ready ? [] : [{ code: "RELEASE_POLICY_MISSING", detail: "真实放行政策尚未登记" }], candidate: { structural_only: true, status: "unexecuted_candidate", scope: { tenant_id: id(30), product_id: c.product_id, project_id: props.projectId }, category_id: c.category_id, evidence_digest: "a".repeat(64), ...(saved ? { declaration: releaseSemantic(c.operation, c.payload), owner_id: props.principalId, product_revision: 3, policy: ready ? { version: "policy-v1", sources: [source] } : null, objects: [{ ref: { kind: "definition", ...ref(6) }, sha256: "b".repeat(64), product_id: c.product_id }], body_sha256: "c".repeat(64), sources: [source], checks: [], exceptions: [], required_source_read_set: c.source_read_set } : { operation: c.operation, discipline, package: c.payload.package, package_sha256: "d".repeat(64), subject_config: configuration, release_scope: range, purpose: c.payload.purpose, limits: [], policy_version: ready ? "policy-v1" : null, signers: [props.principalId], expiry: null, assessment: assessment(discipline, ready), input_snapshot: releaseSemantic(c.operation, c.payload), prepared_at: "2026-10-17T12:00:00Z", customer_acceptance: null, external_received: false, external_effective: false }) } };
}
function fixed(ready = false) { const c = { operation: assemble, payload: payload(), product_id: props.product.id, category_id: props.categoryId, source_read_set: [{ artifact_id: source.id, expected_revision: 1 }] }; const i = inputs(c, ready); return { id: id(10), revision: 1, project_id: props.projectId, purpose: c.payload.purpose, current: { id: id(10), version: ref(10), epoch: 1 }, applicability: "current", receipt_id: id(11), package: i.candidate, assessments: i.assessments, decisions: [] }; }
function header(detail) { const { package: body, assessments, decisions, ...result } = detail; assert.ok(body && assessments && decisions); return result; }
function preview(c) { const i = inputs(c, true); return { command: { ...structuredClone(c), payload: { ...structuredClone(c.payload), approval_token: "actual-common-token-substitute" } }, approval_token: "actual-common-token-substitute", expires_at: null, write_tier: "T2", named_decision: true, review: { operation: c.operation, after: i.candidate, assessments: i.assessments, required_source_read_set: c.source_read_set, authority: { subject_id: props.principalId, operation: c.operation, purpose: c.payload.purpose, roles: ["engineering"], authorized: true, qualified: true, scope: { product_id: props.product.id, project_id: props.projectId } } } }; }
function elements(node, predicate) { if (!node || typeof node !== "object") return []; if (Array.isArray(node)) return node.flatMap(v => elements(v, predicate)); return [...(predicate(node) ? [node] : []), ...elements(node.props?.children, predicate)]; }
function text(node) { return Array.isArray(node) ? node.map(text).join("") : node && typeof node === "object" ? text(node.props?.children) : typeof node === "string" ? node : ""; }
const tick = () => new Promise(resolve => setImmediate(resolve));
function environment(t, options = {}) {
  const prior = Object.getOwnPropertyDescriptor(globalThis, "localStorage"), storage = new Map();
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value) } });
  const calls = [], api = (route, body) => new Promise((resolve, reject) => calls.push({ route, body: body === undefined ? undefined : structuredClone(body), resolve, reject, done: false }));
  let state, tree, currentProps = { ...props, api, onSaved: () => {}, ...options };
  const dialog = { showModal() {}, close() {} };
  function dispose() { if (state) { state.slots.forEach(v => v?.cleanup?.()); state.disposed = true; } }
  function render() { const node = ReleasePackages(currentProps); if (!state || state.key !== node.key || state.disposed) { dispose(); state = { key: node.key, slots: [], index: 0, effects: [], dirty: true, disposed: false }; } state.index = 0; state.effects = []; state.dirty = false; hooks = state; try { tree = node.type(node.props); } finally { hooks = null; } const modal = elements(tree, n => n.type === "dialog")[0]; if (modal?.props.ref) modal.props.ref.current = dialog; state.effects.forEach(fn => fn()); }
  render(); t.after(() => { dispose(); if (prior) Object.defineProperty(globalThis, "localStorage", prior); else delete globalThis.localStorage; });
  const key = () => `pdos-release-v1:${currentProps.categoryId}:${currentProps.principalId}:${currentProps.product.id}:${currentProps.projectId}`;
  return { calls, storage, tree: () => tree, html: () => renderToStaticMarkup(tree), local: () => JSON.parse(storage.get(key()) ?? "null"),
    pending: fragment => calls.find(c => !c.done && c.route.includes(fragment)), respond(call, value) { assert.ok(call); call.done = true; call.resolve(value); }, reject(call, error) { assert.ok(call); call.done = true; call.reject(error); }, remount() { dispose(); render(); }, setProps(next) { currentProps = { ...currentProps, ...next }; render(); },
    async flush() { for (let i = 0; i < 8; i++) { await tick(); if (state.dirty && !state.disposed) render(); } },
  };
}
function button(env, label) { return elements(env.tree(), n => typeof n.props?.onClick === "function" && text(n.props.children) === label)[0]; }
async function click(env, label) { const node = button(env, label); assert.ok(node, label); assert.ok(!node.props.disabled, label); node.props.onClick(); await env.flush(); }
async function change(env, label, value) { const row = elements(env.tree(), n => n.type === "label" && text(n.props.children).startsWith(label))[0], input = row && elements(row, n => ["select", "textarea"].includes(n.type))[0]; assert.ok(input, label); input.props.onChange({ target: { value } }); await env.flush(); }
async function ready(env, items = []) { await env.flush(); env.respond(env.pending("/release-packages?"), { items: items.map(header), next_cursor: null }); await env.flush(); }
const executes = env => env.calls.filter(c => c.route === "v1/commands");
async function startAssembly(env) { await change(env, "高级材料 JSON", JSON.stringify(payload())); await click(env, "读取并核对本次材料"); const call = env.pending("/release/inputs"); env.respond(call, inputs(call.body)); await env.flush(); }

test("list reads headers only, selected package then reads actual fixed content", async t => {
  const env = environment(t), detail = fixed(); await ready(env, [detail]); assert.equal(env.calls.length, 1);
  await change(env, "已保存固定包", detail.id); const call = env.pending(`/release-packages/${detail.id}`); assert.ok(call); env.respond(call, detail); await env.flush();
  assert.match(env.html(), /固定发布用途|尚无适用政策|尚无具名决定/); assert.equal(executes(env).length, 0);
});

test("UNKNOWN policy assembly saves only on explicit manual button without a T1 token", async t => {
  const env = environment(t); await ready(env); await startAssembly(env); assert.equal(executes(env).length, 0); assert.match(env.html(), /真实放行政策尚未登记/);
  await click(env, "本人保存固定包"); assert.equal(executes(env).length, 1); assert.equal(executes(env)[0].body.operation, assemble); assert.equal(executes(env)[0].body.payload.confirmation_token, undefined); assert.equal(executes(env)[0].body.payload.approval_token, undefined);
  const detail = fixed(); env.respond(executes(env)[0], { id: id(20), operation: assemble, subject_type: "release_package", subject_id: detail.id, subject_revision: 1 }); await env.flush(); await ready(env, [detail]); env.respond(env.pending(`/release-packages/${detail.id}`), detail); await env.flush(); assert.equal(env.local().receipt.id, id(20)); assert.equal(env.local().pending, null); assert.equal(button(env, "读取并核对本次材料").props.disabled, true); assert.match(env.html(), /已保存本次固定包/); assert.equal(executes(env).length, 1);
});

test("UNKNOWN submission remount never dispatches and explicit replay retains command/key", async t => {
  const env = environment(t); await ready(env); await startAssembly(env); await click(env, "本人保存固定包"); const first = executes(env)[0]; env.reject(first, new Error("response lost")); await env.flush(); const stored = structuredClone(env.local());
  env.remount(); await ready(env); assert.equal(executes(env).length, 1); assert.deepEqual(env.local(), stored);
  await click(env, "重放并核对同一原提交"); assert.deepEqual(executes(env)[1].body, first.body);
});

test("unknown policy blocks engineering and manufacturing approvals after fixed read", async t => {
  const env = environment(t), detail = fixed(); await ready(env, [detail]); await change(env, "已保存固定包", detail.id); env.respond(env.pending(`/release-packages/${detail.id}`), detail); await env.flush();
  for (const operation of [engineering, "release.manufacturing.approve"]) { await change(env, "办理内容", operation); const draft = JSON.parse(env.local().drafts[`${operation}:${detail.id}:1`]); draft.reason = "本人明确核对理由"; await change(env, "高级材料 JSON", JSON.stringify(draft)); assert.equal(button(env, "读取并核对本次材料").props.disabled, true); const html = env.html(), declaration = html.match(/<section[^>]*aria-label="本次声明材料"[^>]*>([\s\S]*?)<\/section>/)?.[1]; assert.ok(declaration); assert.match(declaration, new RegExp(`基于固定包 ${detail.id} · v1`)); assert.doesNotMatch(declaration, /<dt>产品定义<\/dt>|<dt>工程配置<\/dt>|<dt>制造配置<\/dt>/); assert.match(html, /<dt>产品定义<\/dt>/); }
  assert.equal(env.calls.filter(c => c.route.endsWith("/release/inputs")).length, 0);
});

test("ready engineering uses common named preview and waits for the one explicit decision", async t => {
  const env = environment(t), detail = fixed(true); await ready(env, [detail]); await change(env, "已保存固定包", detail.id); env.respond(env.pending(`/release-packages/${detail.id}`), detail); await env.flush(); await change(env, "办理内容", engineering);
  const draft = JSON.parse(env.local().drafts[`${engineering}:${detail.id}:1`]); draft.reason = "本人具名决定"; await change(env, "高级材料 JSON", JSON.stringify(draft)); await click(env, "读取并核对本次材料"); const request = env.pending("/release/inputs"); env.respond(request, inputs(request.body, true)); await env.flush(); const common = env.pending("v1/commands/preview"); env.respond(common, preview(common.body)); await env.flush(); assert.equal(executes(env).length, 0);
  await click(env, "本人具名确认决定"); assert.equal(executes(env).length, 1); assert.ok(executes(env)[0].body.payload.approval_token);
});

test("existing policy permits actual selected-scope preparation despite whole-package unknown", async t => {
  const env = environment(t), detail = fixed(true); detail.assessments = [assessment("engineering"), assessment("manufacturing")]; await ready(env, [detail]); await change(env, "已保存固定包", detail.id); env.respond(env.pending(`/release-packages/${detail.id}`), detail); await env.flush(); await change(env, "办理内容", engineering);
  const draft = JSON.parse(env.local().drafts[`${engineering}:${detail.id}:1`]); draft.reason = "核对本次明确范围"; await change(env, "高级材料 JSON", JSON.stringify(draft)); assert.equal(button(env, "读取并核对本次材料").props.disabled, false); await click(env, "读取并核对本次材料"); assert.ok(env.pending("/release/inputs")); assert.equal(executes(env).length, 0);
});

test("project switch invalidates in-flight inputs and keeps the original project recovery slot", async t => {
  const env = environment(t); await ready(env); await change(env, "高级材料 JSON", JSON.stringify(payload())); await click(env, "读取并核对本次材料"); const old = env.pending("/release/inputs"), stored = structuredClone(env.local()); env.setProps({ projectId: id(33) }); await ready(env); env.respond(old, inputs(old.body)); await env.flush(); assert.equal(env.calls.filter(c => c.route === "v1/commands/preview").length, 0); assert.equal(executes(env).length, 0);
  env.setProps({ projectId: props.projectId }); await ready(env); assert.deepEqual(env.local(), stored);
});

test("read failure is visible and never becomes an empty successful package list", async t => {
  const env = environment(t); await env.flush(); env.reject(env.pending("/release-packages?"), new Error("实际读取失败")); await env.flush(); assert.match(env.html(), /本项目发布包读取未完成/); assert.equal(button(env, "读取并核对本次材料"), undefined); assert.equal(executes(env).length, 0);
});

test("access loss hides private content while retaining the exact UNKNOWN recovery slot", async t => {
  const env = environment(t); await ready(env); await startAssembly(env); await click(env, "本人保存固定包"); env.reject(executes(env)[0], new Error("response lost")); await env.flush(); const original = structuredClone(env.local()); env.remount(); await env.flush(); env.reject(env.pending("/release-packages?"), { status: 403 }); await env.flush(); assert.deepEqual(env.local(), original); assert.doesNotMatch(env.html(), /本人实际核对材料|固定场地/); assert.equal(button(env, "重放并核对同一原提交"), undefined);
});

test("fixed reading keeps disciplines, unknown scope and external receipt facts separate", () => {
  const detail = fixed(true); detail.package.declaration.release_scope = { ...range, quantity: null, unit: null, lines: [] }; detail.assessments[1] = assessment("manufacturing"); detail.assessments[1].unknown.push("RELEASE_POLICY_OWNER_UNCONNECTED", "DOCUMENT_CONFIGURATION_APPLICABILITY_UNKNOWN", "PUBLICATION_RECHECK_REQUIRED", "RESOURCE_QUALIFICATION_OWNER_UNCONNECTED"); const html = renderToStaticMarkup(React.createElement(ReleasePackageReading, { detail })); assert.match(html, /工程：已满足本范围检查/); assert.match(html, /制造：未知/); assert.match(html, /明确为空，不代表全部/); assert.match(html, /未知／未覆盖/); assert.match(html, /外部接收和实际生效须分别记录/); assert.match(html, /待核：尚无适用的放行政策/); assert.match(html, /待核：放行政策依据尚未接通/); assert.match(html, /待核：文档与配置的适用关系待核对/); assert.match(html, /待核：制造发布依据待复核/); assert.match(html, /待核：资源资格依据尚未接通/); assert.doesNotMatch(html, /<p>[^<]*(?:RELEASE_POLICY_MISSING|OWNER_UNCONNECTED)/); assert.match(html, /<summary>查看诊断代码<\/summary><code>RELEASE_POLICY_MISSING<\/code>/);
});
