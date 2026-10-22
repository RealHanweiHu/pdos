import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test, { after, beforeEach } from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- In-memory event dispatcher; SSR forwards hooks unchanged. */
const same = (a, b) => a && b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const shim = { ...React,
  useState(initial) {
    if (!hooks) return React.useState(initial);
    const state = hooks, index = state.index++;
    if (!(index in state.values)) state.values[index] = typeof initial === "function" ? initial() : initial;
    return [state.values[index], value => { state.values[index] = typeof value === "function" ? value(state.values[index]) : value; }];
  },
  useRef(initial) {
    if (!hooks) return React.useRef(initial);
    const state = hooks, index = state.index++;
    if (!(index in state.values)) state.values[index] = { current: initial };
    return state.values[index];
  },
  useCallback(callback, dependencies) {
    if (!hooks) return React.useCallback(callback, dependencies);
    const state = hooks, index = state.index++, prior = state.values[index];
    if (!prior || !same(prior.dependencies, dependencies)) state.values[index] = { dependencies, callback };
    return state.values[index].callback;
  },
  useEffect(effect, dependencies) {
    if (!hooks) return React.useEffect(effect, dependencies);
    const state = hooks, index = state.index++, prior = state.values[index];
    if (!prior || !same(prior.dependencies, dependencies)) {
      state.values[index] = { dependencies, cleanup: prior?.cleanup };
      state.effects.push(() => { state.values[index].cleanup?.(); state.values[index].cleanup = effect(); });
    }
  },
};
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const cache = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? shim
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier.endsWith(".module.css") ? { __esModule: true, default: new Proxy({}, { get: (_target, key) => String(key) }) }
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { fileName: filename, compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}
const { FileUpload } = load(path.join(directory, "file-upload.tsx"));
const { createUploadIntent } = load(path.join(webRoot, "src/lib/pai-upload.ts"));
const storageDescriptor = Object.getOwnPropertyDescriptor(globalThis, "localStorage"), storage = new Map();
let storageFails = false;
Object.defineProperty(globalThis, "localStorage", { configurable: true, writable: true, value: { getItem: key => storage.get(key) ?? null, setItem(key, value) { if (storageFails) throw Error("storage denied"); storage.set(key, value); }, removeItem: key => storage.delete(key) } });
after(() => { if (storageDescriptor) Object.defineProperty(globalThis, "localStorage", storageDescriptor); else delete globalThis.localStorage; });
beforeEach(() => { storage.clear(); storageFails = false; });
const uuid = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`;
const scope = { principalId: uuid(100), categoryId: uuid(101), productId: null, proposalId: null }, time = "2026-10-17T01:02:03Z";
const target = (current = scope, canWrite = true, revision = 4) => ({ version: "agent-upload-target/v1", principal_id: current.principalId,
  scope: { category_id: current.categoryId, product_id: current.productId, proposal_id: current.proposalId }, as_of: time,
  target: { kind: current.productId ? "product" : "category", id: current.productId ?? current.categoryId, revision }, authorization: { can_write: canWrite, code: canWrite ? null : "FORBIDDEN_SCOPE" },
  constraints: { max_bytes: 8388608, extensions: [".txt", ".md", ".pdf", ".xlsx"], default_visibility: "private" } });
const smallFile = (name = "原规格.txt", text = "真实文件字节") => { const bytes = new TextEncoder().encode(text); return { name, size: bytes.length, arrayBuffer: async () => bytes.buffer.slice(0) }; };
const keyFor = current => `pdos-next:pai-upload:${JSON.stringify([current.principalId, current.categoryId, current.productId, current.proposalId])}`;
function receipt(path, state = "committed", current = scope, available = false) {
  const url = new URL(path, "https://local.invalid/"), request_key = url.pathname.split("/").at(-1), request_digest = url.searchParams.get("request_digest");
  const committed = state === "committed";
  return { version: "agent-upload-receipt/v1", principal_id: current.principalId, scope: { category_id: current.categoryId, product_id: current.productId, proposal_id: current.proposalId }, as_of: time, request_key, request_digest, state,
    receipt: committed ? { id: uuid(201), operation: "evidence.original.upload", subject_type: "uploaded_original", subject_id: uuid(202), subject_revision: 1, writer_id: current.principalId, requester_id: current.principalId, created_at: time } : null,
    attempt: state === "not_observed" ? null : { id: uuid(202), revision: 1, status: state },
    original: committed ? { id: uuid(202), revision: 2, title: "原件实际标题", filename: "原规格.txt", parse_status: "parsed", parse_code: null, scan_status: available ? "clean" : "not_scanned", security: { state: available ? "clean" : "not_scanned", reasons: available ? [] : ["SCAN_REQUIRED"], epoch: 3, source_state: "active" } } : null,
    source: committed ? { artifact_id: uuid(203), artifact_revision: 6, title: "登记资料实际标题", product_id: current.productId, status: "active", original: { id: uuid(202), revision: 2, filename: "原规格.txt", parse_status: "parsed", parse_code: null, scan_status: available ? "clean" : "not_scanned" }, availability: { available, code: available ? null : "ORIGINAL_SECURITY_BLOCKED" } } : null };
}
function server(current = scope) {
  const calls = []; const state = { value: "not_observed", canWrite: true, targetRevision: 4, postFailure: null, receiptFailure: null, available: false };
  const read = async (path, body) => { calls.push({ path, body: structuredClone(body) });
    if (path.includes("agent-upload-target")) return target(current, state.canWrite, state.targetRevision);
    if (path.includes("agent-upload-receipts")) { if (state.receiptFailure) throw state.receiptFailure; return receipt(path, state.value, current, state.available); }
    assert.ok(body); if (state.postFailure) { state.value = "reserved"; throw state.postFailure; }
    state.value = "committed"; return { id: uuid(201), operation: "evidence.original.upload", subject_type: "uploaded_original", subject_id: uuid(202), subject_revision: 1 };
  };
  return { calls, state, api: read, uploadApi: read };
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
const text = tree => !tree || typeof tree === "boolean" ? "" : typeof tree !== "object" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : text(tree.props?.children);
function component(initial) {
  let props = { scope, ...initial }; const levels = [];
  function render(next) {
    if (next) props = { ...props, ...next };
    let call = FileUpload, input = props, depth = 0;
    try { for (;;) {
      const key = input.__key ?? "root";
      if (!levels[depth] || levels[depth].key !== key) {
        levels.slice(depth).forEach(state => state?.values.forEach(value => value?.cleanup?.()));
        levels.length = depth; levels[depth] = { key, values: [], effects: [], index: 0 };
      }
      hooks = levels[depth]; hooks.index = 0; hooks.effects = [];
      const tree = call(input);
      if (!tree || typeof tree.type !== "function" || tree.type.name !== "ScopedFileUpload") return tree;
      call = tree.type; input = { ...tree.props, __key: tree.key }; depth++;
    } } finally { hooks = null; }
  }
  function effects() { levels.forEach(state => { const scheduled = state.effects; state.effects = []; scheduled.forEach(effect => effect()); }); }
  return { render, unmount() { levels.forEach(state => state.values.forEach(value => value?.cleanup?.())); }, async flush() { render(); effects(); await tick(); const tree = render(); effects(); return tree; } };
}
const named = (c, label) => elements(c.render(), e => e.props?.onClick && text(e) === label)[0];
async function settle(c) { for (let count = 0; count < 15; count++) await c.flush(); return c.render(); }
async function click(c, label) { const found = named(c, label); assert.ok(found, label); found.props.onClick(); return settle(c); }
const fileInput = c => elements(c.render(), e => e.type === "input" && e.props.type === "file")[0];
async function open(c) { await settle(c); await click(c, "上传新文件"); }
function choose(c, file = smallFile()) { fileInput(c).props.onChange({ target: { files: [file] } }); }
function metadata(c) { const fields = elements(c.render(), e => e.type === "input" && !e.props.type); fields[0].props.onChange({ target: { value: "人工标题" } }); fields[1].props.onChange({ target: { value: "本人提供的客户规格" } }); }
function reading(c) { const element = elements(c.render(), e => e.type?.name === "UploadReading")[0]; return element ? renderToStaticMarkup(React.createElement(element.type, element.props)) : ""; }

test("opening only reads actual target; file controls have no nested form or required constraint", async () => {
  const s = server(), c = component(s);
  assert.equal(s.calls.length, 0); await open(c);
  assert.equal(s.calls.length, 1); assert.ok(s.calls[0].path.includes("agent-upload-target")); assert.equal(s.calls[0].body, undefined);
  const tree = c.render(); assert.equal(elements(tree, e => e.type === "form").length, 0);
  assert.ok(elements(tree, e => e.type === "input").every(e => !e.props.required));
  assert.ok(elements(tree, e => e.props?.onClick).every(e => e.props.type === "button"));
  assert.match(text(tree), /当前品类资料根/); assert.match(text(tree), /仅本人/); assert.match(text(tree), /发送只使用已登记来源中手选/);
});

test("new upload keeps private scope and persists only pointer before the original POST, then reads authoritative receipt", async () => {
  const s = server(), c = component(s); await open(c); choose(c); metadata(c);
  await click(c, "本人确认上传");
  const posts = s.calls.filter(call => call.body); assert.equal(posts.length, 1); assert.equal(posts[0].path, `v1/categories/${scope.categoryId}/originals`);
  assert.equal(posts[0].body.visibility, "private"); assert.equal(posts[0].body.expected_revision, 4); assert.equal(posts[0].body.source_label, "本人提供的客户规格");
  const pointer = JSON.parse(storage.get(keyFor(scope))); assert.equal(pointer.request_key, posts[0].body.idempotency_key); assert.ok(!JSON.stringify(pointer).includes("content_base64")); assert.ok(!JSON.stringify(pointer).includes("真实文件字节"));
  assert.match(reading(c), /已读回原件保存回执/); assert.match(reading(c), /原件版本 v2/); assert.match(reading(c), /当前尚无可选择的可用登记来源/);
  assert.equal(named(c, "核对并重试原上传"), undefined); assert.ok(named(c, "上传另一份文件"));
});

test("readable source uses Artifact revision and explicit manual picker guidance, without creating a Run", async () => {
  const s = server(); s.state.available = true; const c = component(s); await open(c); choose(c); metadata(c); await click(c, "本人确认上传");
  assert.match(reading(c), /可用登记来源 v6/); assert.match(reading(c), /刷新后手动选择/); assert.ok(!s.calls.some(call => /agent-runs|commands/.test(call.path)));
});

test("target write denial disables chooser while preserving honest read-only state", async () => {
  const s = server(); s.state.canWrite = false; const c = component(s); await open(c);
  assert.equal(fileInput(c).props.disabled, true); assert.match(text(c.render()), /只有读取权限/); assert.equal(s.calls.filter(call => call.body).length, 0);
});

test("identity, scope or API changes while file encoding is pending cannot issue a POST", async () => {
  for (const kind of ["scope", "api", "unmount"]) {
    storage.clear(); const s = server(), c = component(s); await open(c); let finish;
    const bytes = new TextEncoder().encode("pending-bytes"); choose(c, { name: "原规格.txt", size: bytes.length, arrayBuffer: () => new Promise(resolve => { finish = resolve; }) }); metadata(c);
    named(c, "本人确认上传").props.onClick(); await c.flush(); assert.ok(finish);
    if (kind === "scope") c.render({ scope: { ...scope, productId: uuid(999) } });
    else if (kind === "api") { c.render({ api: async () => target() }); await c.flush(); }
    else c.unmount();
    finish(bytes.buffer); await settle(c); assert.equal(s.calls.filter(call => call.body).length, 0);
  }
});

test("committed pointer reload only reads GET and a failed receipt read cannot resend a known accepted upload", async () => {
  const s = server(), c = component(s); await open(c); choose(c); metadata(c); await click(c, "本人确认上传"); c.unmount();
  const count = s.calls.filter(call => call.body).length, reopened = component(s); await settle(reopened);
  assert.match(reading(reopened), /已读回原件保存回执/); assert.equal(s.calls.filter(call => call.body).length, count);
  s.state.receiptFailure = Object.assign(Error("读取被拒绝"), { status: 403 }); await click(reopened, "核对原上传记录");
  assert.ok(!text(reopened.render()).includes("原规格.txt")); assert.ok(storage.get(keyFor(scope))); assert.equal(s.calls.filter(call => call.body).length, count);
});

test("reserved response keeps nonce and original metadata; retry requires reselected matching bytes and never follows target revision", async () => {
  const s = server(); s.state.postFailure = Object.assign(Error("响应丢失"), { status: 500 });
  const c = component(s); await open(c); choose(c); metadata(c); await click(c, "本人确认上传");
  const original = structuredClone(s.calls.find(call => call.body)); assert.match(reading(c), /结果仍待核对/);
  assert.equal(fileInput(c).props.value, undefined); assert.equal(named(c, "核对并重试原上传").props.disabled, true);
  choose(c, smallFile("原规格.txt", "different-content")); await click(c, "核对并重试原上传"); assert.equal(s.calls.filter(call => call.body).length, 1);
  s.state.postFailure = null; s.state.targetRevision = 9; await click(c, "核对上传目标"); choose(c); await click(c, "核对并重试原上传");
  const posts = s.calls.filter(call => call.body); assert.equal(posts.length, 2); assert.deepEqual(posts[0], original); assert.deepEqual(posts[1], posts[0]);
});

test("storage failure permits explicit upload with a memory-only warning and keeps the same nonce", async () => {
  storageFails = true; const s = server(); s.state.postFailure = Object.assign(Error("响应未知"), { status: 500 }); const c = component(s);
  await open(c); choose(c); metadata(c); await click(c, "本人确认上传"); assert.match(text(c.render()), /原请求仅暂存在此页/);
  assert.equal(storage.size, 0); choose(c); s.state.postFailure = null; await click(c, "核对并重试原上传");
  const posts = s.calls.filter(call => call.body); assert.equal(posts.length, 2); assert.deepEqual(posts[0], posts[1]);
});

test("explicit rejection plus not_observed permits reselection but a lone not_observed never invents failure", async () => {
  const s = server();
  const uploadApi = async (path, body) => { if (body) { s.calls.push({ path, body }); throw Object.assign(Error("超过接收大小"), { status: 413 }); } return receipt(path, "not_observed"); };
  const c = component({ ...s, uploadApi }); await open(c); choose(c); metadata(c); await click(c, "本人确认上传");
  assert.equal(storage.has(keyFor(scope)), false); assert.match(text(c.render()), /已被明确拒绝/); assert.equal(named(c, "核对原上传记录"), undefined);
  const intent = await createUploadIntent(smallFile(), { title: "原标题", sourceLabel: "原说明" }, target()); storage.set(keyFor(scope), JSON.stringify(intent.pointer));
  const reopened = component(s); await settle(reopened); assert.match(reading(reopened), /尚未观察到/); assert.match(reading(reopened), /不表示上传失败/); assert.equal(s.calls.filter(call => call.body).length, 1);
});

test("known POST response followed by GET403 preserves the pointer and uses read-back wording", async () => {
  const s = server(), c = component(s); await open(c); choose(c); metadata(c);
  s.state.receiptFailure = Object.assign(Error("回读不可用"), { status: 403 }); await click(c, "本人确认上传");
  assert.ok(storage.get(keyFor(scope))); assert.match(text(c.render()), /已收到上传响应，回读暂不可用/); assert.ok(!text(c.render()).includes("人工标题"));
  const count = s.calls.filter(call => call.body).length; s.state.receiptFailure = null; await click(c, "核对原上传记录"); assert.match(reading(c), /已读回原件保存回执/); assert.equal(s.calls.filter(call => call.body).length, count);
});

test("nonJSON500 stays unknown with reserved record; explicit same-byte retry retains the original nonce", async () => {
  const s = server(), savedFetch = globalThis.fetch; let first = true;
  globalThis.fetch = async (url, options) => {
    const path = String(url).replace(/^\/api\//, "");
    if (options.method === "POST") {
      const body = JSON.parse(options.body); s.calls.push({ path, body });
      if (first) { first = false; s.state.value = "reserved"; return new Response("<h1>Internal Server Error</h1>", { status: 500 }); }
      s.state.value = "committed"; return new Response(JSON.stringify({ id: uuid(201), operation: "evidence.original.upload", subject_type: "uploaded_original", subject_id: uuid(202), subject_revision: 1 }), { status: 200 });
    }
    return new Response(JSON.stringify(receipt(path, s.state.value)), { status: 200 });
  };
  try {
    const c = component({ api: s.api }); await open(c); choose(c); metadata(c); await click(c, "本人确认上传");
    assert.match(reading(c), /结果仍待核对/); assert.ok(storage.get(keyFor(scope))); assert.ok(!text(c.render()).includes("Internal Server Error"));
    choose(c); await click(c, "核对并重试原上传");
    const posts = s.calls.filter(call => call.body); assert.equal(posts.length, 2); assert.deepEqual(posts[0], posts[1]); assert.match(reading(c), /已读回原件保存回执/);
  } finally { globalThis.fetch = savedFetch; }
});

test("scope switch after intent persistence but before library hash validation completes also gates the actual POST", async () => {
  const s = server(), c = component(s); await open(c); choose(c); metadata(c);
  const normalSet = globalThis.localStorage.setItem;
  globalThis.localStorage.setItem = (key, value) => { normalSet(key, value); c.render({ scope: { ...scope, productId: uuid(999) } }); };
  try { named(c, "本人确认上传").props.onClick(); await settle(c); assert.equal(s.calls.filter(call => call.body).length, 0); assert.ok(storage.get(keyFor(scope))); }
  finally { globalThis.localStorage.setItem = normalSet; }
});

test("abandoned is a terminal preparation record; starting another file only removes the local pointer", async () => {
  const intent = await createUploadIntent(smallFile(), { title: "原标题", sourceLabel: "原说明" }, target()); storage.set(keyFor(scope), JSON.stringify(intent.pointer));
  const s = server(); s.state.value = "abandoned"; const c = component(s); await settle(c);
  assert.match(reading(c), /已明确终止/); await click(c, "上传另一份文件"); assert.equal(storage.has(keyFor(scope)), false); assert.equal(s.calls.filter(call => call.body).length, 0); assert.match(text(c.render()), /服务器原件与回执保留/);
});

test("corrupt local pointer is retained and cannot be overwritten by a new POST", async () => {
  storage.set(keyFor(scope), "invalid-json"); const s = server(), c = component(s); await settle(c);
  assert.equal(storage.get(keyFor(scope)), "invalid-json"); assert.match(text(c.render()), /未覆盖该记录/); assert.equal(fileInput(c), undefined); assert.equal(s.calls.filter(call => call.body).length, 0);
});
