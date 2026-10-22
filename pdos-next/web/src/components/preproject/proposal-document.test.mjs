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
// Explicit test-only override; production never reads this environment variable.
const source = process.env.PDOS_PROPOSAL_DOCUMENT_SOURCE ?? path.join(directory, "proposal-document.tsx");
let hooks = null;
const equalDependencies = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Test-only hook dispatcher executes actual component effects and handlers. */
const react = { ...React,
  useState(initial) {
    if (!hooks) return React.useState(initial);
    const own = hooks, index = own.index++;
    if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial;
    return [own.slots[index], value => { if (!own.disposed) { own.slots[index] = typeof value === "function" ? value(own.slots[index]) : value; own.dirty = true; } }];
  },
  useRef(initial) {
    if (!hooks) return React.useRef(initial);
    const index = hooks.index++;
    return hooks.slots[index] ??= { current: initial };
  },
  useCallback(callback, dependencies) {
    if (!hooks) return React.useCallback(callback, dependencies);
    const index = hooks.index++;
    if (!equalDependencies(hooks.slots[index]?.dependencies, dependencies)) hooks.slots[index] = { callback, dependencies };
    return hooks.slots[index].callback;
  },
  useEffect(effect, dependencies) {
    if (!hooks) return React.useEffect(effect, dependencies);
    const own = hooks, index = own.index++;
    if (!equalDependencies(own.slots[index]?.dependencies, dependencies)) {
      const previous = own.slots[index];
      const entry = { dependencies, cleanup: previous?.cleanup };
      own.slots[index] = entry;
      own.effects.push(() => { entry.cleanup?.(); entry.cleanup = effect(); });
    }
  },
};
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
const container = props => React.createElement("div", null, props.children);
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react
    : name === "next/link" ? props => React.createElement("a", { href: props.href }, props.children)
    : name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : name === "radix-ui" ? { Dialog: Object.fromEntries(["Root", "Portal", "Overlay", "Content", "Title", "Description"].map(key => [key, container])) }
    : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2)))
    : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { fileName: filename, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}
const { ProposalDocument } = load(path.resolve(source));
const { ProposalViews } = load(path.join(directory, "proposal-views.tsx"));
const { ProposalVoices } = load(path.join(directory, "proposal-voices.tsx"));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function component(props) {
  let instance, key, inner, tree;
  function unmount() {
    if (!instance) return;
    instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true;
  }
  function render() {
    const wrapper = ProposalDocument(props);
    if (!instance || key !== wrapper.key) {
      unmount(); key = wrapper.key; inner = wrapper;
      instance = { slots: [], index: 0, effects: [], disposed: false, dirty: true };
    }
    instance.index = 0; instance.effects = []; instance.dirty = false;
    hooks = instance;
    try { tree = inner.type(inner.props); } finally { hooks = null; }
    instance.effects.forEach(effect => effect());
  }
  render();
  return {
    async flush() { for (let i = 0; i < 8; i++) { await tick(); if (instance.dirty) render(); } return tree; },
    tree: () => tree,
    html: () => renderToStaticMarkup(tree),
    setProps(next) { props = next; render(); },
    unmount,
  };
}
function environment(t, props = { categoryId: "category-a", proposalId: "proposal-a" }) {
  const saved = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document };
  const calls = [], windowEvents = new EventTarget(), documentEvents = new EventTarget();
  documentEvents.visibilityState = "visible";
  globalThis.window = windowEvents; globalThis.document = documentEvents;
  globalThis.fetch = (url, options) => new Promise((resolve, reject) => calls.push({ url, options, resolve, reject, done: false }));
  const mounted = component(props);
  t.after(() => { mounted.unmount(); Object.assign(globalThis, saved); });
  function respond(call, value, status = 200) {
    assert.ok(call, "Expected an actual pending request"); call.done = true;
    call.resolve({ ok: status >= 200 && status < 300, json: async () => value });
  }
  const pending = predicate => calls.find(call => !call.done && predicate(call));
  return { ...mounted, calls, respond, pending, windowEvents, documentEvents };
}
function proposal({ id = "proposal-a", frozen = false } = {}) {
  const items = [{ item_id: "section-one", version: 1, kind: "section", content: { key: "worth_it", text: "Synthetic document text" }, source_refs: [], origin: "human" }];
  const copy = { title: frozen ? "Frozen title" : "Current title", brief: "Synthetic brief", items, entry_kind: "new_product", target_kind: "new_product" };
  return { id, title: "Current title", brief: "Synthetic current brief", owner_id: "owner", revision: 3, status: frozen ? "in_review" : "draft", visibility: "private", private_source_count: 0, items,
    document_identity: { proposal_id: id, revision: frozen ? 2 : 3, document_digest: "same-frozen-digest", submission_id: frozen ? "submission" : null, document_mode: frozen ? "frozen" : "current" },
    display_document: copy,
    maturity: { spec_count: 1, option_count: 1, required_dispositions: [], freeze_blockers: [] },
    submission: frozen ? { id: "submission", reviewer_id: "reviewer", frozen_document: copy } : null,
    decision: null };
}
function response(doc, view = "spec-benchmark", quote = "VISIBLE_SOURCE") {
  const base = { ...doc.document_identity, view, engine_version: "server", input_digest: "input", context_changes: [] };
  if (view === "positioning") return { ...base, data: { groups: [], unknowns: [], unmapped: [], unavailable: [], unknown_count: 0 } };
  const subject = { type: "proposal", id: doc.id, label: doc.display_document.title };
  const sources = quote ? [{ type: "artifact", id: "source-id", version: 1, line: 1, quote }] : [{ type: "artifact", id: "source-id", version: 1, status: "unavailable" }];
  const data = { subjects: [subject], groups: [{ parameter_id: "parameter", parameter_version: 1, parameter: { key: "pressure", name: "Pressure", value_type: "number" }, unit: "kPa", condition_note: "23 C", test_conditions: [], sample_count: 1, comparable_count: quote ? 1 : 0, unknown_count: quote ? 0 : 1, separation_reasons: [], observations: [{ subject, observation_id: "observation", kind: "spec", value_type: "number", value: quote ? "12" : null, availability: quote ? "known" : "unknown", nature: "observed", evidence_kind: quote ? "observed" : "unknown", comparable: !!quote, source_refs: sources, reasons: quote ? [] : ["source_unavailable"] }] }], unmapped: [], unavailable: [], unknown_count: 0 };
  return { ...base, data };
}
async function loadDocument(env, doc, actor = "owner") {
  for (const call of env.calls.filter(call => !call.done && !call.options.signal?.aborted && call.options.method === "GET" && !call.url.includes("/views/"))) {
    env.respond(call, call.url.endsWith("/session") ? { principal_id: actor }
      : call.url.endsWith("/participants") ? { items: [{ id: "owner", name: "Owner", reviewer_eligible: false, can_write: true }, { id: "reviewer", name: "Reviewer", reviewer_eligible: true, can_write: false }] } : doc);
  }
  await env.flush();
}
async function ready(env, doc = proposal(), actor = "owner") {
  await loadDocument(env, doc, actor);
  env.respond(env.pending(call => call.url.includes("/views/")), response(doc));
  await env.flush(); return doc;
}
async function click(env, label) {
  const button = elements(env.tree(), element => element.props?.children === label && element.props?.onClick)[0];
  assert.ok(button, label); button.props.onClick(); await env.flush();
}
const view = env => elements(env.tree(), element => element.type === ProposalViews)[0];

test("reads only scoped GETs and displays the server document identity", async t => {
  const env = environment(t); const doc = await ready(env);
  assert.equal(env.calls.length, 4);
  assert.ok(env.calls.every(call => call.options.method === "GET" && call.options.signal instanceof AbortSignal));
  assert.equal(env.calls[3].url, "/api/v1/categories/category-a/views/spec-benchmark?proposal_id=proposal-a");
  assert.deepEqual(view(env).props.document, doc.document_identity);
  assert.ok(env.html().includes("VISIBLE_SOURCE"));
});

test("scope remount aborts old reads and ignores responses arriving after abort", async t => {
  const env = environment(t);
  const old = env.calls.slice();
  env.setProps({ categoryId: "category-b", proposalId: "proposal-b" });
  assert.ok(old.every(call => call.options.signal.aborted));
  const next = proposal({ id: "proposal-b" }); await ready(env, next);
  for (const call of old) env.respond(call, call.url.endsWith("/session") ? { principal_id: "owner" } : call.url.endsWith("/participants") ? { items: [] } : proposal());
  await env.flush();
  assert.equal(view(env).props.document.proposal_id, "proposal-b");
  assert.equal(env.calls.filter(call => call.url.includes("/views/")).length, 1);
});

test("a late view response cannot replace a newer selected view", async t => {
  const env = environment(t), doc = proposal(); await loadDocument(env, doc);
  const old = env.pending(call => call.url.includes("/views/spec-benchmark"));
  view(env).props.onViewChange("positioning"); await env.flush();
  assert.ok(old.options.signal.aborted);
  const current = env.pending(call => call.url.includes("/views/positioning"));
  env.respond(current, response(doc, "positioning")); await env.flush();
  env.respond(old, response(doc)); await env.flush();
  assert.equal(view(env).props.result.view, "positioning");
  assert.equal(env.html().includes("VISIBLE_SOURCE"), false);
});

test("same frozen identity refresh hides old sources and fetches fresh redaction", async t => {
  const env = environment(t), doc = proposal({ frozen: true }); await ready(env, doc, "reviewer");
  assert.ok(env.html().includes("VISIBLE_SOURCE"));
  await click(env, "刷新文档与视图");
  assert.equal(env.html().includes("VISIBLE_SOURCE"), false);
  await loadDocument(env, doc, "reviewer");
  const fresh = env.pending(call => !call.options.signal.aborted && call.url.includes("/views/"));
  env.respond(fresh, response(doc, "spec-benchmark", null)); await env.flush();
  assert.deepEqual(view(env).props.result.document_digest, doc.document_identity.document_digest);
  assert.equal(env.html().includes("VISIBLE_SOURCE"), false);
  assert.ok(env.html().includes("source-id"));
  assert.ok(env.html().includes("来源不可用"));
});

test("failed document or view reads hide old success and retry first reloads the document", async t => {
  const env = environment(t), doc = await ready(env);
  view(env).props.onViewChange("positioning"); await env.flush();
  env.respond(env.pending(call => !call.options.signal.aborted && call.url.includes("/views/")), { message: "view denied" }, 403); await env.flush();
  assert.equal(view(env).props.result, null); assert.ok(env.html().includes("view denied"));
  view(env).props.onRetry(); await env.flush();
  const pendingDoc = env.pending(call => !call.options.signal.aborted && call.url.endsWith(`/proposals/${doc.id}`));
  env.respond(pendingDoc, { message: "document revoked" }, 403); await env.flush();
  assert.equal(view(env), undefined);
  assert.equal(env.html().includes("VISIBLE_SOURCE"), false);
  assert.equal(env.html().includes("Synthetic document text"), false);
  assert.ok(env.html().includes("document revoked"));
});

test("mismatched envelopes are unavailable and never trigger an automatic retry loop", async t => {
  const env = environment(t), doc = proposal(); await loadDocument(env, doc);
  env.respond(env.pending(call => call.url.includes("/views/")), { ...response(doc), submission_id: "wrong-submission" }); await env.flush();
  assert.equal(view(env).props.result, null);
  assert.ok(env.html().includes("视图与当前提案文档不一致"));
  assert.equal(env.calls.length, 4);
});

test("view changes preserve G0 form values and the prepared command for same-key retry", async t => {
  const env = environment(t), doc = proposal({ frozen: true }); await ready(env, doc, "reviewer");
  const rationale = elements(env.tree(), element => element.type === "textarea" && element.props.required)[0];
  rationale.props.onChange({ target: { value: "Synthetic named decision" } }); await env.flush();
  const form = elements(env.tree(), element => element.type === "form")[0];
  form.props.onSubmit({ preventDefault() {} }); await env.flush();
  const preview = env.pending(call => call.url.endsWith("/commands/preview"));
  const command = JSON.parse(preview.options.body);
  assert.equal(command.expected_revision, 3);
  assert.equal(command.payload.expected_revision, 3);
  assert.equal(command.payload.submission_id, "submission");
  assert.equal(view(env).props.document.revision, 2);
  env.respond(preview, { command: { ...command, payload: { ...command.payload, confirmation_token: "fixed-confirmation-token" } }, review: {} }); await env.flush();
  view(env).props.onViewChange("positioning"); await env.flush();
  assert.ok(env.html().includes("Synthetic named decision"));
  await click(env, "确认办理");
  const first = env.pending(call => call.url.endsWith("/commands"));
  first.done = true; first.reject(new Error("synthetic transport failure")); await env.flush();
  await click(env, "确认办理");
  const second = env.pending(call => call.url.endsWith("/commands"));
  assert.equal(first.options.body, second.options.body);
  assert.equal(env.calls.filter(call => call.url.endsWith("/commands/preview")).length, 1);
  env.respond(second, { subject_id: doc.id }); await env.flush();
  assert.ok(env.pending(call => !call.options.signal.aborted && call.url.endsWith(`/proposals/${doc.id}`)));
});

test("variant G0 uses the frozen target and sends the named identity for explicit review", async t => {
  const env = environment(t), doc = proposal({ frozen: true });
  doc.display_document.entry_kind = "derivative";
  doc.display_document.target_kind = "new_variant";
  doc.target_kind = "new_product"; // Current metadata cannot replace the frozen review target.
  await ready(env, doc, "reviewer");
  const label = name => elements(env.tree(), element => element.type === "label" && Array.isArray(element.props.children) && element.props.children[0] === name)[0];
  elements(label("新变体名称"), element => element.type === "input")[0].props.onChange({ target: { value: "客户限定版本" } });
  elements(label("变体类别"), element => element.type === "select")[0].props.onChange({ target: { value: "customer" } });
  await env.flush();
  elements(env.tree(), element => element.type === "form")[0].props.onSubmit({ preventDefault() {} });
  await env.flush();
  const call = env.pending(item => item.url.endsWith("/commands/preview"));
  const command = JSON.parse(call.options.body);
  assert.deepEqual(command.payload.new_identity, { name: "客户限定版本", variant_kind: "customer" });
  assert.equal("target_kind" in command.payload, false);
  env.respond(call, { command, review: { target_kind: "new_variant", identity_name: "客户限定版本", variant_kind: "customer" } });
  await env.flush();
  assert.ok(env.html().includes("客户限定版本 · 客户变体"));
});

test("foreground refresh is read-only, hidden pages do not refresh, and cleanup removes listeners", async t => {
  const env = environment(t); await ready(env);
  env.documentEvents.visibilityState = "hidden";
  env.windowEvents.dispatchEvent(new Event("focus")); env.documentEvents.dispatchEvent(new Event("visibilitychange"));
  await new Promise(resolve => setTimeout(resolve, 5)); await env.flush();
  assert.equal(env.calls.length, 4);
  env.documentEvents.visibilityState = "visible";
  env.documentEvents.dispatchEvent(new Event("visibilitychange")); env.windowEvents.dispatchEvent(new Event("focus"));
  await new Promise(resolve => setTimeout(resolve, 5)); await env.flush();
  assert.equal(env.calls.length, 7);
  assert.ok(env.calls.every(call => call.options.method === "GET"));
  env.unmount();
  env.windowEvents.dispatchEvent(new Event("focus"));
  await new Promise(resolve => setTimeout(resolve, 5));
  assert.equal(env.calls.length, 7);
});

test("superseded same-scope reload cannot replace a newer source projection", async t => {
  const env = environment(t), doc = await ready(env);
  await click(env, "刷新文档与视图");
  const oldReads = env.calls.filter(call => !call.done);
  await click(env, "刷新文档与视图");
  assert.ok(oldReads.every(call => call.options.signal.aborted));
  await loadDocument(env, doc);
  env.respond(env.pending(call => !call.options.signal.aborted && call.url.includes("/views/")), response(doc, "spec-benchmark", null)); await env.flush();
  for (const call of oldReads) env.respond(call, { message: "stale denied response" }, 403);
  await env.flush();
  assert.equal(env.html().includes("stale denied response"), false);
  assert.equal(env.html().includes("VISIBLE_SOURCE"), false);
  assert.ok(env.html().includes("source-id"));
});

test("late confirmed write from an unmounted scope does not reload or replace the new proposal", async t => {
  const env = environment(t), doc = proposal({ frozen: true }); await ready(env, doc, "reviewer");
  elements(env.tree(), element => element.type === "form")[0].props.onSubmit({ preventDefault() {} }); await env.flush();
  const preview = env.pending(call => call.url.endsWith("/commands/preview"));
  env.respond(preview, { command: JSON.parse(preview.options.body), review: {} }); await env.flush();
  await click(env, "确认办理");
  const oldPost = env.pending(call => call.url.endsWith("/commands"));
  env.setProps({ categoryId: "category-b", proposalId: "proposal-b" });
  await ready(env, proposal({ id: "proposal-b" }));
  env.respond(oldPost, { subject_id: "proposal-a" }); await env.flush();
  assert.equal(view(env).props.document.proposal_id, "proposal-b");
  assert.equal(env.calls.filter(call => call.url.endsWith("/proposals/proposal-a")).length, 1);
  assert.equal(elements(env.tree(), element => element.props?.children === "确认办理").length, 0);
});

test("missing identity or unreadable frozen copy cannot fall back to current document content", async t => {
  const env = environment(t), doc = proposal({ frozen: true });
  doc.submission.frozen_document = null;
  await loadDocument(env, doc, "reviewer");
  assert.equal(view(env), undefined);
  assert.equal(env.calls.some(call => call.url.includes("/views/")), false);
  assert.equal(env.html().includes("Synthetic document text"), false);
  assert.ok(env.html().includes("未提供可读的提案文档身份"));
});

test("legacy responses without document identity remain unavailable", async t => {
  const env = environment(t), doc = proposal();
  delete doc.document_identity;
  await loadDocument(env, doc);
  assert.equal(view(env), undefined);
  assert.equal(env.calls.some(call => call.url.includes("/views/")), false);
  assert.ok(env.html().includes("未提供可读的提案文档身份"));
});

test("document chips switch only returned item groups and never submit a domain command", async t => {
  const env = environment(t), doc = proposal({ frozen: true });
  doc.display_document.items.push(
    { item_id: "risk", version: 1, kind: "risk", content: { statement: "RETURNED_RISK" }, source_refs: [], origin: "ai_draft" },
    { item_id: "option", version: 1, kind: "option", content: { name: "RETURNED_OPTION" }, source_refs: [], origin: "human" },
  );
  await ready(env, doc, "reviewer");
  const chips = () => elements(env.tree(), item => item.props?.["aria-label"] === "提案文档视图")[0];
  assert.equal(elements(chips(), item => item.type === "button").length, 8);
  assert.equal(env.html().includes("RETURNED_RISK"), false);
  elements(chips(), item => item.type === "button" && item.props.children[0] === "风险")[0].props.onClick(); await env.flush();
  const content = renderToStaticMarkup(elements(env.tree(), item => item.props?.className === "documentContent")[0]);
  assert.ok(content.includes("RETURNED_RISK")); assert.equal(content.includes("RETURNED_OPTION"), false);
  elements(chips(), item => item.type === "button" && item.props.children[0] === "用户声音")[0].props.onClick(); await env.flush();
  const voices = elements(env.tree(), item => item.type === ProposalVoices)[0];
  assert.ok(voices);
  assert.equal(voices.props.categoryId, "category-a");
  assert.equal(voices.props.proposalId, doc.id);
  assert.deepEqual(voices.props.document, doc.document_identity);
  assert.ok(voices.props.readVersion > 0);
  assert.ok(env.calls.every(call => call.options.method === "GET")); assert.equal(env.calls.length, 4);
});

test("key specification table preserves decimal bounds, false, unknowns and returned source identity", async t => {
  const env = environment(t), doc = proposal({ frozen: true });
  doc.display_document.items.push(
    { item_id: "spec", version: 3, kind: "spec", content: { parameter: "压力下限", parameter_version: 2, value_type: "range", availability: "known", lower: "123.45678901234567890", upper: null, unit: "kPa", condition_note: "23 C", item_status: "ai_draft" }, source_refs: [{ type: "snapshot", id: "SPEC_EXACT_SOURCE", version: 7 }], origin: "ai_draft" },
    { item_id: "boolean", version: 1, kind: "spec", content: { parameter: "自停", value_type: "boolean", availability: "known", value: false, item_status: "unknown" }, source_refs: [], origin: "human" },
    { item_id: "unknown", version: 1, kind: "spec", content: { parameter: "温升", value_type: "number", availability: "unknown", item_status: "unknown" }, source_refs: [], origin: "human" },
  );
  await ready(env, doc, "reviewer"); const html = env.html();
  for (const text of ["≥123.45678901234567890", "SPEC_EXACT_SOURCE", "值未知", ">无 ", "字典版本", "工况未定"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes("确认此条"), false); assert.ok(env.calls.every(call => call.options.method === "GET"));
});

test("document-tab changes retain the named G0 form and immutable prepared request", async t => {
  const env = environment(t); await ready(env, proposal({ frozen: true }), "reviewer");
  elements(env.tree(), item => item.type === "textarea" && item.props.required)[0].props.onChange({ target: { value: "PRESERVED_REASON" } }); await env.flush();
  elements(env.tree(), item => item.type === "form")[0].props.onSubmit({ preventDefault() {} }); await env.flush();
  const preview = env.pending(call => call.url.endsWith("/commands/preview"));
  const command = JSON.parse(preview.options.body); env.respond(preview, { command, review: {} }); await env.flush();
  const chips = elements(env.tree(), item => item.props?.["aria-label"] === "提案文档视图")[0];
  elements(chips, item => item.type === "button" && item.props.children[0] === "证据")[0].props.onClick(); await env.flush();
  assert.ok(env.html().includes("PRESERVED_REASON")); await click(env, "确认办理");
  assert.deepEqual(JSON.parse(env.pending(call => call.url.endsWith("/commands")).options.body), command);
});
