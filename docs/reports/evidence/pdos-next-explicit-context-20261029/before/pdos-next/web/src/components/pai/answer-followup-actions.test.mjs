import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../.."), dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks;
const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
const shim = { ...React,
  useState(initial) { const h = hooks, i = h.index++; if (!(i in h.values)) h.values[i] = typeof initial === "function" ? initial() : initial; return [h.values[i], value => { h.values[i] = typeof value === "function" ? value(h.values[i]) : value; h.dirty = true; }]; },
  useRef(initial) { const h = hooks, i = h.index++; if (!(i in h.values)) h.values[i] = { current: initial }; return h.values[i]; },
  useCallback(callback, deps) { const h = hooks, i = h.index++; if (!same(h.values[i]?.deps, deps)) h.values[i] = { deps, callback }; return h.values[i].callback; },
  useEffect(effect, deps) { const h = hooks, i = h.index++, old = h.values[i]; if (!old || !same(old.deps, deps)) { h.values[i] = { deps, cleanup: null }; h.effects.push(() => { old?.cleanup?.(); h.values[i].cleanup = effect(); }); } },
};
function load(filename, react = shim) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_t, key) => key }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  const compiled = new Module(filename);
  compiled.require = name => name === "react" ? react : name === "@/components/ui/button" ? { Button: "button" } : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => "i" }) : name.startsWith("@/") ? load(path.join(web, "src", name.slice(2)), react) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name), react) : dependency(name);
  compiled._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return compiled.exports;
}
const { AnswerFollowupActions } = load(path.join(directory, "answer-followup-actions.tsx"));
const { AnswerFollowupActions: StaticFollowup } = load(path.join(directory, "answer-followup-actions.tsx"), React);
const { AnswerSources } = load(path.join(directory, "answer-sources.tsx"), React);
const { RunContinuation } = load(path.join(directory, "run-continuation.tsx"));
const { deeperLookupRequest } = load(path.join(web, "src/lib/answer-followup.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const context = () => ({ root: "v1/agent-runs", run: { run_id: id(1), session_id: id(2), status: "completed", reverted: false, project_id: id(3) }, workState: { version: "agent-work-state/v1", session_id: id(2), revision: 4, focus_objects: [], citations: [{ citation_id: id(5), title: "历史进水案例", source_revision: 3 }], exclusions: [], search_preferences: { scope: "same_category", include_customer_private: false }, search_context: { kind: "project", scoped: true, label: "气密项目" } } });
const words = tree => typeof tree === "string" || typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(words).join("") : tree && typeof tree === "object" ? words(tree.props?.children) : "";
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children), ...nodes(tree.props?.background)];
const tick = () => new Promise(resolve => setImmediate(resolve));
function component(Component, props) {
  const h = { values: [], index: 0, effects: [], dirty: false };
  let tree;
  function render() { h.index = 0; h.effects = []; h.dirty = false; hooks = h; try { tree = Component(props); } finally { hooks = null; } h.effects.forEach(effect => effect()); return tree; }
  return { props, render, tree: () => tree, unmount() { h.values.forEach(v => v?.cleanup?.()); }, async settle() { for (let i = 0; i < 6; i++) { if (!tree || h.dirty) render(); await tick(); } return tree; } };
}
const feedback = () => ({ event: { type: "retrieval_feedback", version: "retrieval-feedback/v1", action: "not_relevant", selection: { kind: "citation", id: id(5) }, source: { source_type: "issue", source_id: id(7) } } });

test("before deep starts the UI names the actual scope, sources and longer effort without inventing an ETA", () => {
  let starts = 0;
  const html = renderToStaticMarkup(React.createElement(StaticFollowup, { context: context(), api: async () => { throw Error("No API during SSR"); }, additionalSources: [{ artifact_id: id(8), expected_revision: 1 }], onContinue: async () => { starts++; }, onState() {} }));
  assert.equal(starts, 0); assert.match(html, /气密项目，不足时补查同品类/); assert.match(html, /更多资料和业务记录/); assert.match(html, /比快查更久/); assert.match(html, /新增 1 份/); assert.doesNotMatch(html.replace(/<[^>]*>/g, ""), /分钟|预计.*秒|00000000/);
});
test("deep click delegates one native deep continuation with no extra confirmation", async () => {
  const writes = [], c = component(AnswerFollowupActions, { context: context(), api: async () => { throw Error("No read needed"); }, onContinue: async value => writes.push(value), onState() {} });
  await c.settle(); const button = nodes(c.tree()).find(v => v.type === "button" && words(v) === "深入查");
  await button.props.onClick(); await c.settle(); assert.equal(writes.length, 1); assert.equal(writes[0].lookup_depth, "deep"); assert.equal(writes[0].continue_from_run_id, id(1));
});
test("exclusion waits for current state and actual feedback identity before collapsing", async () => {
  const calls = [], snapshots = [], states = [], ctx = context(), latest = { ...ctx.workState, revision: 5, exclusions: [{ id: id(5), kind: "citation", reason: "不相关" }] };
  const c = component(AnswerFollowupActions, { context: ctx, api: async (url, body) => { calls.push({ url, body }); return url.includes("/events?") ? { items: [feedback()], next_cursor: 1 } : latest; }, onContinue: async () => {}, onState: value => states.push(value), onSnapshot: value => snapshots.push(value) });
  await c.settle(); const child = nodes(c.tree()).find(v => v.type?.name === "AnswerCorrections");
  const request = { kind: "exclude_source", path: `v1/agent-sessions/${id(2)}/work-state`, body: { expected_revision: 4, request_key: id(9), action: "exclude_source", item_id: id(5) } };
  const saved = await child.props.onExclude(request); await c.settle();
  assert.equal(saved.revision, 5); assert.equal(calls.length, 3); assert.deepEqual(calls[0].body, request.body); assert.equal(calls[1].body, undefined); assert.match(calls[2].url, /\/events\?/);
  assert.equal(states.length, 1); assert.deepEqual(snapshots.at(-1).feedbacks, [{ selection_id: id(5), source_type: "issue", source_id: id(7) }]);
});
test("a later restored exclusion is read back and never re-collapsed from an old replay response", async () => {
  const ctx = context(), snapshots = [], latest = { ...ctx.workState, revision: 6, exclusions: [] }, old = { ...ctx.workState, revision: 5, exclusions: [{ id: id(5), kind: "citation" }] };
  const c = component(AnswerFollowupActions, { context: ctx, api: async (_path, body) => body ? old : latest, onContinue: async () => {}, onState() {}, onSnapshot: value => snapshots.push(value) });
  await c.settle(); const child = nodes(c.tree()).find(v => v.type?.name === "AnswerCorrections");
  await assert.rejects(child.props.onExclude({ kind: "exclude_source", path: "work-state", body: { expected_revision: 4, item_id: id(5) } }), error => error.status === 409);
  assert.deepEqual(snapshots.at(-1).state.exclusions, []);
});
test("source cards collapse with original quotes and anchors intact and restore from current props", () => {
  const answer = { lookup: "cited", sources: [{ citation_id: id(5), title: "固定案例", quote: "<script>原文</script>", source_revision: 3 }] };
  const before = JSON.stringify(answer);
  const html = renderToStaticMarkup(React.createElement(AnswerSources, { answer, collapsedCitationIds: [id(5)] }));
  assert.match(html, /<summary>已收起不相关结果<\/summary>/); assert.doesNotMatch(html, /<details open|<script>/); assert.match(html, /&lt;script&gt;/); assert.ok(html.includes(`assistant-source-${id(5)}-0`)); assert.equal(JSON.stringify(answer), before);
  const restored = renderToStaticMarkup(React.createElement(AnswerSources, { answer, collapsedCitationIds: [] })); assert.doesNotMatch(restored, /已收起不相关结果/);
});

function native(t, overrides = {}) {
  const previous = Object.getOwnPropertyDescriptor(globalThis, "localStorage"), store = new Map();
  Object.defineProperty(globalThis, "localStorage", { configurable: true, value: { getItem: key => store.get(key) ?? null, setItem: (key, value) => store.set(key, value), removeItem: key => store.delete(key) } });
  const calls = [], opened = [], ctx = overrides.context ?? context();
  const api = (url, body) => new Promise((resolve, reject) => calls.push({ url, body, resolve, reject, done: false }));
  const c = component(RunContinuation, { root: ctx.root, run: ctx.run, principalId: id(8), api, presentation: "composer", answerActions: true, onOpen: async runId => opened.push(runId), ...overrides.props });
  c.render();
  t.after(() => { c.unmount(); if (previous) Object.defineProperty(globalThis, "localStorage", previous); else delete globalThis.localStorage; });
  return { ...c, calls, store, opened, current: () => calls.find(v => !v.done), respond(value) { const call = this.current(); assert.ok(call); call.done = true; call.resolve(value); }, reject(error) { const call = this.current(); call.done = true; call.reject(error); }, async ready() { await c.settle(); this.respond({ run_id: id(1), owner_id: id(8), can_continue: true, existing: null }); await c.settle(); const carry = nodes(c.tree()).find(v => v.type?.name === "WorkStateCarry"); assert.ok(carry); carry.props.onChange(ctx.workState); await c.settle(); return nodes(c.tree()).find(v => v.type?.name === "AnswerFollowupActions"); } };
}
test("native journal preserves deep after a lost response, replays exact body and opens actual next Run", async t => {
  const c = native(t), actions = await c.ready(); assert.ok(actions);
  const original = deeperLookupRequest(id(1), "继续核对更多工况", id(9), [{ artifact_id: id(20), expected_revision: 2 }]);
  const sent = actions.props.onContinue(original).catch(() => {}); await c.settle();
  c.respond({ run_id: id(1), owner_id: id(8), can_continue: true, existing: null }); await c.settle();
  const write = c.current(); assert.deepEqual(write.body, original); c.reject(Error("response lost")); await sent; await c.settle();
  assert.equal(JSON.parse([...c.store.values()].find(v => v.includes('"request"'))).request.lookup_depth, "deep");
  const retry = nodes(c.tree()).find(v => v.type === "button" && words(v) === "核对并重试原请求"); assert.ok(retry); retry.props.onClick(); await c.settle();
  c.respond({ run_id: id(1), owner_id: id(8), can_continue: true, existing: null }); await c.settle();
  assert.deepEqual(c.current().body, original); c.respond({ run_id: id(30), continued_from_id: id(1) }); await c.settle(); assert.deepEqual(c.opened, [id(30)]);
});
test("reload restores deep journal and an already accepted continuation opens with zero repost", async t => {
  const c = native(t), body = deeperLookupRequest(id(1), "继续深入查", id(9));
  c.store.set(`pdos:continuation:${id(8)}:v1/agent-runs:${id(1)}`, JSON.stringify({ root: "v1/agent-runs", owner_id: id(8), request: body }));
  await c.settle(); c.respond({ run_id: id(1), owner_id: id(8), can_continue: false, existing: { run_id: id(30), goal: body.goal, idempotency_key: id(9) } }); await c.settle();
  const open = nodes(c.tree()).find(v => v.type === "button" && words(v) === "打开已保存的后续工作"); assert.ok(open); await open.props.onClick(); await c.settle();
  assert.deepEqual(c.opened, [id(30)]); assert.equal(c.calls.every(call => call.body === undefined), true);
});

test("native deep actions strip picker titles and preserve fixed selected versions", async t => {
  const c = native(t, { props: { additionalSources: [{ artifact_id: id(20), expected_revision: 2, title: "显示名称" }] } });
  const actions = await c.ready();
  assert.deepEqual(actions.props.additionalSources, [{ artifact_id: id(20), expected_revision: 2 }]);
  const body = deeperLookupRequest(id(1), "", id(9), actions.props.additionalSources);
  const sent = actions.props.onContinue(body); await c.settle();
  c.respond({ run_id: id(1), owner_id: id(8), can_continue: true, existing: null }); await c.settle();
  assert.deepEqual(c.current().body.sources, [{ artifact_id: id(20), expected_revision: 2 }]);
  c.respond({ run_id: id(30), continued_from_id: id(1) }); await sent; await c.settle();
  assert.deepEqual(c.opened, [id(30)]);
});
test("personal deep follows its actual native endpoint and journal without copying project scope", async t => {
  const ctx = context(); ctx.root = "v1/personal/agent-runs"; ctx.run.project_id = null;
  ctx.workState.search_context = { kind: "personal", scoped: false, label: "本人可读范围" };
  const c = native(t, { context: ctx }), actions = await c.ready();
  const body = deeperLookupRequest(id(1), "继续查找", id(9));
  const sent = actions.props.onContinue(body); await c.settle();
  c.respond({ run_id: id(1), owner_id: id(8), can_continue: true, existing: null }); await c.settle();
  assert.equal(c.current().url, "v1/personal/agent-runs");
  assert.deepEqual(c.current().body, body); assert.equal("project_id" in c.current().body, false);
  const stored = JSON.parse([...c.store.values()].find(v => v.includes('"request"')));
  assert.equal(stored.root, ctx.root); assert.equal(stored.request.lookup_depth, "deep");
  c.respond({ run_id: id(30), continued_from_id: id(1) }); await sent; await c.settle();
  assert.deepEqual(c.opened, [id(30)]);
});
