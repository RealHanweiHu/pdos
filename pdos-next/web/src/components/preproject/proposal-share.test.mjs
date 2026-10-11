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
const source = process.env.PDOS_PROPOSAL_SHARE_SOURCE ?? path.join(directory, "proposal-share.tsx");
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
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react
    : name === "next/link" ? props => React.createElement("a", { href: props.href }, props.children)
    : name === "@phosphor-icons/react" ? Object.fromEntries(["ShareNetwork", "LockKey", "CheckCircle", "WarningCircle"].map(key => [key, () => React.createElement("svg")]))
    : name === "radix-ui" ? { Dialog: Object.fromEntries(["Root", "Portal", "Overlay", "Content", "Title", "Description"].map(key => [key, container])) }
    : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2)))
    : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}
const { ProposalShare } = load(path.resolve(source));
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
    const wrapper = ProposalShare(props);
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
function environment(t, props = { categoryId: "category-a", proposalId: "proposal-a", principalId: "owner" }) {
  const saved = { fetch: globalThis.fetch, window: globalThis.window, document: globalThis.document };
  const calls = [], windowEvents = new EventTarget(), documentEvents = new EventTarget(), storage = new Map();
  windowEvents.sessionStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
  documentEvents.visibilityState = "visible";
  globalThis.window = windowEvents; globalThis.document = documentEvents;
  globalThis.fetch = (url, options) => new Promise((resolve, reject) => calls.push({ url, options, resolve, reject, done: false }));
  let mounted = component(props);
  t.after(() => { mounted.unmount(); Object.assign(globalThis, saved); });
  function respond(call, value, status = 200) {
    assert.ok(call, "Expected an actual pending request"); call.done = true;
    call.resolve({ status, ok: status >= 200 && status < 300, json: async () => value });
  }
  const pending = predicate => calls.find(call => !call.done && predicate(call));
  return { tree: () => mounted.tree(), html: () => mounted.html(), flush: () => mounted.flush(), setProps: next => mounted.setProps(next), unmount: () => mounted.unmount(),
    remount(next = props) { mounted.unmount(); mounted = component(next); }, calls, respond, pending, windowEvents, documentEvents, storage };
}
function proposal({ id = "proposal-a", category = "category-a", owner = "owner", revision = 3 } = {}) {
  return { id, category_id: category, owner_id: owner, revision, visibility: "private", private_source_count: 0,
    document_identity: { proposal_id: id, revision: 2, document_digest: `digest-${revision}`, submission_id: "frozen-submission", document_mode: "frozen" } };
}
async function ready(env, doc = proposal()) {
  env.respond(env.pending(call => call.url.endsWith(`/proposals/${doc.id}`)), doc);
  env.respond(env.pending(call => call.url.endsWith("/participants")), { items: [{ id: "owner", name: "Owner" }, { id: "person", name: "Colleague" }] });
  await env.flush();
}
function button(env, label) { return elements(env.tree(), element => element.props?.children === label && typeof element.props.onClick === "function")[0]; }
async function click(env, label) { const found = button(env, label); assert.ok(found, `Missing ${label}`); assert.ok(!found.props.disabled, `${label} disabled`); found.props.onClick(); await env.flush(); }
async function sharePreview(env) {
  const radios = elements(env.tree(), element => element.type === "input" && element.props.type === "radio");
  radios[0].props.onChange(); await env.flush();
  elements(env.tree(), element => element.type === "input" && element.props.type === "checkbox")[0].props.onChange({ target: { checked: true } }); await env.flush();
  elements(env.tree(), element => element.type === "form")[0].props.onSubmit({ preventDefault() {} }); await env.flush();
  return env.pending(call => call.url.endsWith("/commands/preview"));
}
const claim = { id: "claim-a", version: 4, proposal_id: "proposal-a", product_id: null, status: "active", privacy: "private", content: { note: "Synthetic claim" }, statement: "Synthetic statement" };
function prepared(call, { hits = [], claims = [], revision = 3 } = {}) {
  const command = JSON.parse(call.options.body);
  return { command: { ...command, payload: { ...command.payload, confirmation_token: "sealed-confirmation-token" } }, expires_at: "2026-10-11T12:00:00Z", review: {
    operation: command.operation, payload: command.payload, effect: "Server reviewed effect",
    ...(command.operation === "proposal.share" ? { proposal_revision: revision, checks: { hits, claims }, watermark: { sources: [{ type: "snapshot", id: "source-a", version: 2, content_hash: "immutable-hash" }], counts: [["snapshot", "source-a", 2, 1]], links: ["link-a"], audiences: [{ id: "person", access_epoch: 7, expires_at: null }] } } : { claim_revision: 4, affected_targets: [{ type: "proposal_item", id: "item-a", version: 2 }], links: ["link-a"] }),
  } };
}
function receipt(call, id = "receipt-a") {
  const command = JSON.parse(call.options.body);
  return { id, category_id: command.category_id, product_id: null, operation: command.operation, subject_id: command.payload.proposal_id ?? command.payload.claim_id, subject_revision: 5, result: {} };
}
async function withdrawalPreview(env, reason = "Synthetic correction reason") {
  await click(env, "读取可撤回事实");
  env.respond(env.pending(call => call.url.includes("/claims?")), { items: [claim], next_cursor: null }); await env.flush();
  await click(env, "准备撤回此事实");
  env.respond(env.pending(call => call.url.endsWith("/claims/claim-a")), claim); await env.flush();
  elements(env.tree(), element => element.type === "textarea")[0].props.onChange({ target: { value: reason } }); await env.flush();
  elements(env.tree(), element => element.type === "form")[0].props.onSubmit({ preventDefault() {} }); await env.flush();
  const call = env.pending(call => call.url.endsWith("/commands/preview")); env.respond(call, prepared(call)); await env.flush();
}

test("initial reads do not choose scope, consent, share, withdraw or invoke an agent", async t => {
  const env = environment(t); await ready(env);
  assert.equal(env.calls.length, 2); assert.ok(env.calls.every(call => call.options.method === "GET"));
  assert.ok(elements(env.tree(), element => element.type === "input").every(input => !input.props.checked));
  assert.equal(elements(env.tree(), element => element.props?.children === "预览共享影响")[0].props.disabled, true);
  assert.ok(env.html().includes("digest-3")); assert.ok(env.html().includes("阅读文档第 2 版"));
});

test("preview uses current command revision and preserves server checks and exact watermark before explicit confirmation", async t => {
  const env = environment(t); await ready(env); const call = await sharePreview(env);
  const body = JSON.parse(call.options.body); assert.equal(body.expected_revision, 3); assert.equal(body.payload.expected_revision, 3); assert.equal(body.payload.deidentified_confirmed, true); assert.deepEqual(body.payload.audience_ids, []);
  env.respond(call, prepared(call)); await env.flush();
  const html = env.html(); for (const value of ["immutable-hash", "source-a", "link-a", "Colleague", "权限版本 7"]) assert.ok(html.includes(value));
  assert.equal(env.calls.filter(call => call.url.endsWith("/commands")).length, 0);
  await click(env, "本人确认共享"); const applied = env.pending(call => call.url.endsWith("/commands"));
  assert.deepEqual(JSON.parse(applied.options.body), prepared(call).command);
});

test("private identity hits block share and changing to withdrawal discards the shared preview", async t => {
  const env = environment(t); await ready(env); const call = await sharePreview(env);
  const hits = [{ kind: "identity", value: "Synthetic customer", claim_id: claim.id }];
  env.respond(call, prepared(call, { hits, claims: [{ ...claim, quote: "Synthetic quote", checks: { hits, overlap_warnings: [{ source_index: 0, characters: 5, quote: "overlap" }] } }] })); await env.flush();
  assert.equal(button(env, "本人确认共享").props.disabled, true); assert.ok(env.html().includes("私有事实编号")); assert.ok(env.html().includes("Synthetic customer")); assert.ok(env.html().includes("overlap"));
  await click(env, "改为准备撤回此事实"); assert.equal(button(env, "本人确认共享"), undefined);
  env.respond(env.pending(call => call.url.endsWith("/claims/claim-a")), claim); await env.flush();
  assert.ok(env.html().includes("撤回原因")); assert.equal(env.calls.filter(call => call.url.endsWith("/commands")).length, 0);
});

test("preview transport failure retries the exact request and synchronous double submit sends once", async t => {
  const env = environment(t); await ready(env); const call = await sharePreview(env);
  call.done = true; call.reject(new Error("offline")); await env.flush();
  const retry = button(env, "重试原请求"); retry.props.onClick(); retry.props.onClick(); await env.flush();
  const next = env.pending(call => call.url.endsWith("/commands/preview")); assert.equal(next.options.body, call.options.body);
  assert.equal(env.calls.filter(call => call.url.endsWith("/commands/preview")).length, 2);
});

test("unknown apply outcome locks edits and retry reuses sealed token and idempotency key", async t => {
  const env = environment(t); await ready(env); const call = await sharePreview(env); env.respond(call, prepared(call)); await env.flush();
  await click(env, "本人确认共享"); const applied = env.pending(call => call.url.endsWith("/commands")); applied.done = true; applied.reject(new Error("connection lost")); await env.flush();
  assert.equal(button(env, "放弃本次预览并刷新"), undefined); assert.equal(button(env, "取消本次预览").props.disabled, true);
  await click(env, "重试原请求"); const retry = env.pending(call => call.url.endsWith("/commands")); assert.equal(retry.options.body, applied.options.body); assert.equal(env.calls.filter(call => call.url.endsWith("/commands/preview")).length, 1);
});

test("proven confirmation rejection rereads and previews the same operation with the same key before a new human confirmation", async t => {
  const env = environment(t); await ready(env); const call = await sharePreview(env); env.respond(call, prepared(call)); await env.flush(); await click(env, "本人确认共享");
  env.respond(env.pending(call => call.url.endsWith("/commands")), { code: "CONFIRMATION_REQUIRED", message: "Confirmation expired", detail: { reason: "CONFIRMATION_REQUIRED" } }, 409); await env.flush();
  assert.equal(env.calls.length, 4); assert.equal(env.storage.size, 1);
  await click(env, "重新读取并预览原操作"); assert.equal(button(env, "本人确认共享"), undefined);
  await ready(env, proposal({ revision: 6 })); const next = env.pending(call => call.url.endsWith("/commands/preview"));
  assert.equal(JSON.parse(next.options.body).idempotency_key, JSON.parse(call.options.body).idempotency_key); assert.equal(JSON.parse(next.options.body).command_id, JSON.parse(call.options.body).command_id); assert.equal(JSON.parse(next.options.body).payload.expected_revision, 6);
  const newPreview = prepared(next, { revision: 6 }); newPreview.command.payload.confirmation_token = "new-sealed-confirmation-token"; env.respond(next, newPreview); await env.flush(); assert.equal(env.calls.filter(call => call.url.endsWith("/commands")).length, 1);
  await click(env, "本人确认共享"); const retry = env.pending(call => call.url.endsWith("/commands"));
  assert.equal(JSON.parse(retry.options.body).payload.expected_revision, 6); assert.equal(JSON.parse(retry.options.body).payload.confirmation_token, "new-sealed-confirmation-token"); env.respond(retry, receipt(retry)); await env.flush(); assert.equal(env.storage.size, 0);
});

test("withdrawal receipt invalidates previews before reread and notification failure cannot undo success", async t => {
  const env = environment(t, { categoryId: "category-a", proposalId: "proposal-a", principalId: "owner", onChanged: async () => { throw new Error("page failed"); } }); await ready(env); await withdrawalPreview(env);
  await click(env, "本人确认撤回"); const applied = env.pending(call => call.url.endsWith("/commands"));
  const body = JSON.parse(applied.options.body); assert.equal(body.payload.expected_version, 4); assert.equal(body.payload.reason, "Synthetic correction reason");
  env.respond(applied, receipt(applied)); await env.flush(); assert.equal(button(env, "本人确认撤回"), undefined); assert.equal(button(env, "本人确认共享"), undefined); assert.ok(env.html().includes("事实已撤回，引用条目值保留"));
  await ready(env, proposal({ revision: 7 })); assert.ok(env.html().includes("digest-7")); assert.ok(env.html().includes("操作已成功；提案页面刷新失败")); assert.equal(button(env, "重试原请求"), undefined);
  const next = await sharePreview(env); assert.equal(JSON.parse(next.options.body).payload.expected_revision, 7);
});

test("successful withdrawal followed by denied reread hides old material but keeps actual receipt", async t => {
  const env = environment(t); await ready(env); await withdrawalPreview(env); await click(env, "本人确认撤回"); const call = env.pending(call => call.url.endsWith("/commands")); env.respond(call, receipt(call)); await env.flush();
  env.respond(env.pending(call => call.url.endsWith("/proposals/proposal-a")), { message: "Access revoked" }, 403); await env.flush();
  assert.ok(env.html().includes("receipt-a")); assert.ok(!env.html().includes("Synthetic statement")); assert.ok(!env.html().includes("digest-3")); assert.equal(button(env, "重试原请求"), undefined);
});

test("signed consumption denial shows actual failure, never alters content or fabricates withdrawal", async t => {
  const env = environment(t); await ready(env); await withdrawalPreview(env); await click(env, "本人确认撤回");
  env.respond(env.pending(call => call.url.endsWith("/commands")), { code: "UNDO_BLOCKED_BY_DEPENDENCY", message: "已签署决定消费的事实不能撤回。", detail: { reason: "consumed_by_decision" } }, 409); await env.flush();
  assert.ok(env.html().includes("已签署决定消费的事实不能撤回")); assert.ok(!env.html().includes("事实已撤回，引用条目值保留")); assert.ok(env.calls.every(call => !call.options.body || !JSON.parse(call.options.body).operation.includes("patch")));
});

test("scope and principal changes abort requests and reject late old-scope previews", async t => {
  const env = environment(t); await ready(env); const call = await sharePreview(env);
  env.setProps({ categoryId: "category-b", proposalId: "proposal-b", principalId: "other" }); await env.flush(); assert.equal(call.options.signal.aborted, true);
  env.respond(call, prepared(call, { hits: [{ kind: "identity", value: "OLD SECRET" }] })); await env.flush();
  await ready(env, proposal({ id: "proposal-b", category: "category-b", owner: "other" }));
  assert.ok(!env.html().includes("OLD SECRET")); assert.equal(button(env, "本人确认共享"), undefined); assert.ok(elements(env.tree(), element => element.type === "input").every(input => !input.props.checked));
  assert.ok(env.calls.slice(3).every(call => call.url.startsWith("/api/v1/categories/category-b/")));
});

test("unexpected prepared payload is rejected instead of applying a different audience", async t => {
  const env = environment(t); await ready(env); const call = await sharePreview(env); const response = prepared(call); response.command.payload.audience_ids = ["wrong-person"];
  env.respond(call, response); await env.flush(); assert.equal(button(env, "本人确认共享"), undefined); assert.ok(env.html().includes("返回预览与原请求不一致"));
});

test("paginated candidates stay in the proposal and product-bound candidates are not given invented revisions", async t => {
  const env = environment(t); await ready(env); await click(env, "读取可撤回事实"); const first = env.pending(call => call.url.includes("/claims?"));
  assert.ok(first.url.includes("proposal_id=proposal-a")); env.respond(first, { items: [{ ...claim, product_id: "product-a" }], next_cursor: "next" }); await env.flush(); assert.equal(button(env, "准备撤回此事实"), undefined); assert.ok(env.html().includes("型号范围"));
  await click(env, "读取下一页"); const next = env.pending(call => call.url.includes("cursor=next")); env.respond(next, { items: [{ ...claim, id: "wrong", proposal_id: "other-proposal", statement: "FOREIGN SECRET" }], next_cursor: null }); await env.flush();
  assert.ok(!env.html().includes("FOREIGN SECRET")); assert.ok(env.html().includes("事实列表与当前提案不一致"));
});

test("semantic payload key order does not invalidate an unchanged server preview", async t => {
  const env = environment(t); await ready(env); const call = await sharePreview(env); const response = prepared(call);
  response.command.payload = Object.fromEntries(Object.entries(response.command.payload).reverse());
  env.respond(call, response); await env.flush(); assert.ok(button(env, "本人确认共享"));
});

test("authoritative access denial hides prior private preview while retaining the original retry request", async t => {
  const env = environment(t); await ready(env); const call = await sharePreview(env);
  env.respond(call, prepared(call, { claims: [{ ...claim, quote: "PRIVATE QUOTE", checks: { hits: [] } }] })); await env.flush();
  await click(env, "本人确认共享"); const apply = env.pending(call => call.url.endsWith("/commands")); env.respond(apply, { message: "Access revoked" }, 403); await env.flush();
  assert.ok(!env.html().includes("PRIVATE QUOTE")); assert.ok(!env.html().includes("Synthetic statement")); assert.equal(button(env, "本人确认共享"), undefined);
  await click(env, "重试原请求"); assert.equal(env.pending(call => call.url.endsWith("/commands")).options.body, apply.options.body);
});

test("late applied receipt from a prior scope never refreshes the new proposal or calls its parent", async t => {
  let notifications = 0;
  const env = environment(t, { categoryId: "category-a", proposalId: "proposal-a", principalId: "owner", onChanged: () => notifications++ });
  await ready(env); const preview = await sharePreview(env); env.respond(preview, prepared(preview)); await env.flush(); await click(env, "本人确认共享");
  const apply = env.pending(call => call.url.endsWith("/commands"));
  env.setProps({ categoryId: "category-b", proposalId: "proposal-b", principalId: "owner", onChanged: () => notifications++ }); await env.flush();
  env.respond(apply, receipt(apply, "OLD RECEIPT")); await env.flush();
  assert.equal(apply.options.signal.aborted, true); assert.equal(notifications, 0); assert.ok(!env.html().includes("OLD RECEIPT"));
  assert.equal(env.calls.length, 6); await ready(env, proposal({ id: "proposal-b", category: "category-b" }));
});

test("apply is durably journaled before sending and remount only offers exact-request recovery", async t => {
  const env = environment(t); await ready(env); const preview = await sharePreview(env);
  env.respond(preview, prepared(preview, { claims: [{ ...claim, quote: "DO NOT STORE CLAIM TEXT", checks: { hits: [] } }] })); await env.flush();
  await click(env, "本人确认共享"); const apply = env.pending(call => call.url.endsWith("/commands"));
  assert.equal(env.storage.size, 1); const saved = [...env.storage.values()][0]; assert.ok(!saved.includes("DO NOT STORE CLAIM TEXT")); assert.ok(!saved.includes("Synthetic claim")); assert.deepEqual(JSON.parse(saved).command, JSON.parse(apply.options.body));
  env.remount(); await env.flush(); assert.equal(apply.options.signal.aborted, true); await ready(env);
  assert.equal(env.calls.filter(call => call.url.endsWith("/commands")).length, 1); assert.ok(button(env, "重试原请求")); assert.equal(button(env, "读取可撤回事实").props.disabled, true);
  await click(env, "重试原请求"); const replay = env.calls.filter(call => call.url.endsWith("/commands")).at(-1); assert.equal(replay.options.body, apply.options.body);
  env.respond(replay, receipt(replay)); await env.flush(); assert.equal(env.storage.size, 0); assert.ok(env.html().includes("共享成功"));
});

test("withdrawal journal survives unknown outcome without persisting fetched claim content", async t => {
  const env = environment(t); await ready(env); await withdrawalPreview(env); await click(env, "本人确认撤回");
  const apply = env.pending(call => call.url.endsWith("/commands")); apply.done = true; apply.reject(new Error("offline")); await env.flush();
  assert.ok(![...env.storage.values()][0].includes("Synthetic statement")); assert.ok(![...env.storage.values()][0].includes("Synthetic claim"));
  env.remount(); await env.flush(); await ready(env); await click(env, "重试原请求"); const replay = env.pending(call => call.url.endsWith("/commands")); assert.equal(replay.options.body, apply.options.body);
  env.respond(replay, receipt(replay)); await env.flush(); assert.equal(env.storage.size, 0); assert.ok(env.html().includes("事实已撤回"));
});

test("matching receipt notifies parent immediately while local document GET is still pending", async t => {
  const events = [];
  const env = environment(t, { categoryId: "category-a", proposalId: "proposal-a", principalId: "owner", onChanged: value => { events.push(value.id); throw new Error("parent failure"); } });
  await ready(env); await withdrawalPreview(env); await click(env, "本人确认撤回"); const apply = env.pending(call => call.url.endsWith("/commands")); env.respond(apply, receipt(apply)); await env.flush();
  assert.deepEqual(events, ["receipt-a"]); assert.ok(env.pending(call => call.url.endsWith("/proposals/proposal-a"))); assert.equal(button(env, "本人确认撤回"), undefined); assert.ok(env.html().includes("事实已撤回")); assert.ok(env.html().includes("页面刷新失败")); assert.equal(env.storage.size, 0);
});

test("claim pagination 403 erases private list and proposal context", async t => {
  const env = environment(t); await ready(env); await click(env, "读取可撤回事实"); env.respond(env.pending(call => call.url.includes("/claims?")), { items: [claim], next_cursor: "next" }); await env.flush(); assert.ok(env.html().includes("Synthetic statement"));
  await click(env, "读取下一页"); env.respond(env.pending(call => call.url.includes("cursor=next")), { message: "Access revoked", detail: { hits: [{ kind: "identity", value: "DO NOT RENDER" }] } }, 403); await env.flush();
  assert.ok(!env.html().includes("Synthetic statement")); assert.ok(!env.html().includes("digest-3")); assert.ok(!env.html().includes("DO NOT RENDER")); assert.equal(button(env, "准备撤回此事实"), undefined);
});

test("claim detail 401 erases the retained private list and preview hit text", async t => {
  const env = environment(t); await ready(env); await click(env, "读取可撤回事实"); env.respond(env.pending(call => call.url.includes("/claims?")), { items: [claim], next_cursor: null }); await env.flush();
  await click(env, "准备撤回此事实"); env.respond(env.pending(call => call.url.endsWith("/claims/claim-a")), { message: "Session ended" }, 401); await env.flush();
  assert.ok(!env.html().includes("Synthetic statement")); assert.ok(!env.html().includes("digest-3")); assert.equal(button(env, "准备撤回此事实"), undefined); assert.ok(env.html().includes("Session ended"));
});

test("session journal is isolated by actor, category and proposal and never overwritten by another scope", async t => {
  const env = environment(t); await ready(env); const preview = await sharePreview(env); env.respond(preview, prepared(preview)); await env.flush(); await click(env, "本人确认共享");
  const saved = [...env.storage.entries()][0];
  env.remount({ categoryId: "category-a", proposalId: "proposal-a", principalId: "another-person" }); await env.flush(); await ready(env, proposal({ owner: "another-person" }));
  assert.equal(button(env, "重试原请求"), undefined); assert.deepEqual([...env.storage.entries()][0], saved);
  env.remount(); await env.flush(); await ready(env); assert.ok(button(env, "重试原请求"));
});

test("storage write failure prevents the apply network request", async t => {
  const env = environment(t); await ready(env); const preview = await sharePreview(env); env.respond(preview, prepared(preview)); await env.flush();
  env.windowEvents.sessionStorage.setItem = () => { throw new Error("Storage unavailable"); };
  await click(env, "本人确认共享"); assert.equal(env.calls.filter(call => call.url.endsWith("/commands")).length, 0); assert.ok(env.html().includes("Storage unavailable"));
});

test("mismatched receipt and network/5xx errors retain original journal without offering new preview", async t => {
  const env = environment(t); await ready(env); const preview = await sharePreview(env); env.respond(preview, prepared(preview)); await env.flush(); await click(env, "本人确认共享");
  const apply = env.pending(call => call.url.endsWith("/commands")); const original = [...env.storage.values()][0]; env.respond(apply, { ...receipt(apply), subject_id: "wrong" }); await env.flush();
  assert.equal([...env.storage.values()][0], original); assert.equal(button(env, "重新读取并预览原操作"), undefined);
  await click(env, "重试原请求"); env.respond(env.pending(call => call.url.endsWith("/commands")), { code: "CONFIRMATION_REQUIRED", detail: { reason: "CONFIRMATION_REQUIRED" }, message: "Ambiguous gateway failure" }, 503); await env.flush();
  assert.equal([...env.storage.values()][0], original); assert.equal(button(env, "重新读取并预览原操作"), undefined);
});

test("proved confirmation rejection survives remount and requires explicit reread, not automatic apply", async t => {
  const env = environment(t); await ready(env); const preview = await sharePreview(env); env.respond(preview, prepared(preview)); await env.flush(); await click(env, "本人确认共享");
  env.respond(env.pending(call => call.url.endsWith("/commands")), { code: "CONFIRMATION_REQUIRED", detail: { reason: "CONFIRMATION_SCOPE_CHANGED" }, message: "Scope changed" }, 409); await env.flush();
  assert.equal(JSON.parse([...env.storage.values()][0]).outcome, "confirmation_rejected"); env.remount(); await env.flush(); await ready(env);
  assert.ok(button(env, "重新读取并预览原操作")); assert.equal(env.calls.filter(call => call.url.endsWith("/commands")).length, 1); assert.equal(env.calls.filter(call => call.url.endsWith("/commands/preview")).length, 1);
});

test("corrupt or body-bearing journal is preserved and blocks new requests", async t => {
  const env = environment(t); await ready(env); const preview = await sharePreview(env); env.respond(preview, prepared(preview)); await env.flush(); await click(env, "本人确认共享");
  const [key, raw] = [...env.storage.entries()][0], value = JSON.parse(raw); value.command.payload.content = "UNTRUSTED STORED CLAIM BODY"; env.storage.set(key, JSON.stringify(value));
  env.remount(); await env.flush(); await ready(env);
  assert.ok(env.html().includes("已暂停新请求")); assert.ok(!env.html().includes("UNTRUSTED STORED CLAIM BODY")); assert.equal(button(env, "读取可撤回事实").props.disabled, true); assert.equal(button(env, "重试原请求"), undefined); assert.equal(env.storage.size, 1);
});

test("share version conflict survives remount and explicitly re-previews current revision with original identity", async t => {
  const env = environment(t); await ready(env); const preview = await sharePreview(env); env.respond(preview, prepared(preview)); await env.flush(); await click(env, "本人确认共享");
  const apply = env.pending(call => call.url.endsWith("/commands")), original = JSON.parse(apply.options.body);
  env.respond(apply, { code: "VERSION_CONFLICT", detail: { reason: "evidence_version_moved" }, message: "引用版本已变化，请重新核对。" }, 409); await env.flush();
  assert.equal(JSON.parse([...env.storage.values()][0]).outcome, "version_rejected");
  env.remount(); await env.flush(); await ready(env, proposal({ revision: 8 }));
  assert.ok(button(env, "重新读取并预览原操作")); assert.equal(env.calls.filter(call => call.url.endsWith("/commands")).length, 1);
  await click(env, "重新读取并预览原操作"); await ready(env, proposal({ revision: 9 }));
  const next = env.pending(call => call.url.endsWith("/commands/preview")), body = JSON.parse(next.options.body);
  assert.equal(body.command_id, original.command_id); assert.equal(body.idempotency_key, original.idempotency_key); assert.equal(body.expected_revision, 9); assert.equal(body.payload.expected_revision, 9); assert.equal(body.payload.confirmation_token, undefined);
  const newPreview = prepared(next, { revision: 9 }); newPreview.command.payload.confirmation_token = "replacement-sealed-confirmation-token";
  env.respond(next, newPreview); await env.flush(); assert.equal(env.calls.filter(call => call.url.endsWith("/commands")).length, 1);
  await click(env, "本人确认共享"); const retry = env.pending(call => call.url.endsWith("/commands")); assert.deepEqual(JSON.parse(retry.options.body), newPreview.command);
  env.respond(retry, receipt(retry)); await env.flush(); assert.equal(env.storage.size, 0); assert.ok(env.html().includes("共享成功"));
});

test("signed-consumption rejection persists without private display and explicit ending unlocks the next action", async t => {
  const env = environment(t); await ready(env); await withdrawalPreview(env); await click(env, "本人确认撤回");
  const apply = env.pending(call => call.url.endsWith("/commands"));
  env.respond(apply, { code: "UNDO_BLOCKED_BY_DEPENDENCY", detail: { reason: "consumed_by_decision" }, message: "已签署决定消费的事实不能撤回。" }, 409); await env.flush();
  assert.equal(JSON.parse([...env.storage.values()][0]).outcome, "terminal_rejected");
  assert.ok(!env.html().includes("Synthetic statement")); assert.ok(!env.html().includes("Synthetic correction reason")); assert.ok(![...env.storage.values()][0].includes("Synthetic claim"));
  assert.equal(button(env, "重试原请求"), undefined); assert.equal(button(env, "重新读取并预览原操作"), undefined);
  env.remount(); await env.flush(); await ready(env); assert.ok(button(env, "结束这项已拒绝操作")); assert.equal(env.storage.size, 1);
  await click(env, "结束这项已拒绝操作"); assert.equal(env.storage.size, 0); assert.equal(env.calls.filter(call => call.url.endsWith("/commands")).length, 1); await ready(env);
  assert.equal(button(env, "结束这项已拒绝操作"), undefined); assert.equal(button(env, "读取可撤回事实").props.disabled, false);
  const next = await sharePreview(env); assert.notEqual(JSON.parse(next.options.body).idempotency_key, JSON.parse(apply.options.body).idempotency_key); assert.equal(JSON.parse(next.options.body).operation, "proposal.share");
});

test("terminal preview denial also has an explicit end without creating an apply journal", async t => {
  const env = environment(t); await ready(env); await click(env, "读取可撤回事实"); env.respond(env.pending(call => call.url.includes("/claims?")), { items: [claim], next_cursor: null }); await env.flush();
  await click(env, "准备撤回此事实"); env.respond(env.pending(call => call.url.endsWith("/claims/claim-a")), claim); await env.flush();
  elements(env.tree(), element => element.type === "textarea")[0].props.onChange({ target: { value: "Named reason" } }); await env.flush(); elements(env.tree(), element => element.type === "form")[0].props.onSubmit({ preventDefault() {} }); await env.flush();
  env.respond(env.pending(call => call.url.endsWith("/commands/preview")), { code: "UNDO_BLOCKED_BY_DEPENDENCY", detail: { reason: "consumed_by_decision" }, message: "已签署决定消费的事实不能撤回。" }, 409); await env.flush();
  assert.ok(button(env, "结束这项已拒绝操作")); assert.equal(env.storage.size, 0); assert.ok(!env.html().includes("Synthetic statement"));
  await click(env, "结束这项已拒绝操作"); await ready(env); assert.equal(button(env, "读取可撤回事实").props.disabled, false); assert.ok(env.calls.every(call => !call.url.endsWith("/commands")));
});

test("withdrawal reason is trimmed before preview so normalized sealed payload remains identical", async t => {
  const env = environment(t); await ready(env); await withdrawalPreview(env, "  Synthetic correction reason \n\t");
  const preview = env.calls.find(call => call.url.endsWith("/commands/preview")); assert.equal(JSON.parse(preview.options.body).payload.reason, "Synthetic correction reason"); assert.ok(button(env, "本人确认撤回"));
  await click(env, "本人确认撤回"); const apply = env.pending(call => call.url.endsWith("/commands")); assert.equal(JSON.parse(apply.options.body).payload.reason, "Synthetic correction reason");
});

for (const [code, reason, status] of [
  ["VERSION_CONFLICT", "proposal_locked", 409],
  ["VALIDATION_FAILED", "evidence_version_moved", 409],
  ["UNDO_BLOCKED_BY_DEPENDENCY", "other_dependency", 409],
  ["UNDO_BLOCKED_BY_DEPENDENCY", "consumed_by_decision", 503],
  ["VERSION_CONFLICT", "evidence_version_moved", 403],
]) test(`unproven ${status} ${code}/${reason} retains exact journal and cannot end or reprepare`, async t => {
  const env = environment(t); await ready(env);
  if (code === "VERSION_CONFLICT" || reason === "evidence_version_moved") {
    const preview = await sharePreview(env); env.respond(preview, prepared(preview)); await env.flush(); await click(env, "本人确认共享");
  } else { await withdrawalPreview(env); await click(env, "本人确认撤回"); }
  const apply = env.pending(call => call.url.endsWith("/commands")), saved = [...env.storage.values()][0];
  env.respond(apply, { code, detail: { reason }, message: "Synthetic rejected request" }, status); await env.flush();
  assert.equal([...env.storage.values()][0], saved); assert.equal(button(env, "结束这项已拒绝操作"), undefined); assert.equal(button(env, "重新读取并预览原操作"), undefined);
  await click(env, "重试原请求"); assert.equal(env.pending(call => call.url.endsWith("/commands")).options.body, apply.options.body);
});
