import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, i) => Object.is(value, b[i]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Test-only dispatcher exercises the actual component handlers. */
const react = { ...React, useState(initial) { if (!hooks) return React.useState(initial); const own = hooks, i = own.index++; if (!(i in own.slots)) own.slots[i] = typeof initial === "function" ? initial() : initial; return [own.slots[i], value => { if (!own.disposed) { own.slots[i] = typeof value === "function" ? value(own.slots[i]) : value; own.dirty = true; } }]; }, useRef(initial) { if (!hooks) return React.useRef(initial); return hooks.slots[hooks.index++] ??= { current: initial }; }, useEffect(effect, deps) { if (!hooks) return React.useEffect(effect, deps); const own = hooks, i = own.index++; if (!same(own.slots[i]?.deps, deps)) { const prior = own.slots[i], next = { deps, cleanup: prior?.cleanup }; own.slots[i] = next; own.effects.push(() => { next.cleanup?.(); next.cleanup = effect(); }); } } };
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const cache = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (!filename) throw new Error("Missing test module");
  if (cache.has(filename)) return cache.get(filename).exports;
  const value = new Module(filename); cache.set(filename, value);
  value.require = name => name === "react" ? react : name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  value._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename); return value.exports;
}
const { AnswerKnowledgeForm, AnswerKnowledgeActions } = load(path.join(directory, "answer-knowledge.tsx")), lib = load(path.join(web, "src/lib/verified-knowledge.ts"));
const shareLib = load(path.join(web, "src/lib/knowledge-share.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const category = id(1), actor = id(2), run = id(3);
function seed(operation = "category.knowledge.add") { return { command_scope: { category_id: category, product_id: null, expected_revision: 7 }, operation, payload: operation === "knowledge.candidate.create" ? { project_id: null, visibility: "category", title: "经验候选", lesson: "原回答", evidence_summary: "实际依据", applicability_hypothesis: "待本人核对", result_receipts: [], sources: [], reason: "本人整理", answer_origin: { run_id: run, answer_digest: "a".repeat(64) } } : { kind: "verified_answer", content: { title: "核实答案", question: "实际问题", answer: "原回答", draft_origin: "ai_draft" }, answer_origin: { run_id: run, answer_digest: "a".repeat(64) }, ...(operation === "category.knowledge.promote" ? { source_proposal_id: id(4), source_proposal_revision: 3, source_item_refs: [], deidentified_confirmed: false } : {}) }, question: "实际问题", answer: "原回答", basis_count: 2, people: [{ id: actor, name: "本人" }, { id: id(5), name: "同事" }], default_responsible_id: actor, draft_origin: "ai_draft" }; }
const fields = { title: "本人核对标题", answer: "本人核对后回答", review: { responsible_id: actor, applicability_scope: "合成密封用途", review_due_at: "2099-01-01T23:59:59Z" }, deidentified: true };
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const label = tree => typeof tree === "string" ? tree : typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(label).join("") : tree && typeof tree === "object" ? label(tree.props?.children) : "";
const tick = () => new Promise(resolve => setImmediate(resolve));
function memory() { const map = new Map(); return { map, getItem: key => map.get(key) ?? null, setItem: (key, value) => map.set(key, value), removeItem: key => map.delete(key) }; }
function env(t, initial = seed(), storage = memory()) {
  const previous = globalThis.sessionStorage; globalThis.sessionStorage = storage;
  const calls = [], saved = [], instance = { slots: [], index: 0, effects: [], dirty: true, disposed: false };
  const props = { api(route, body) { return new Promise((resolve, reject) => calls.push({ route, body: structuredClone(body), resolve, reject, journal: [...storage.map.values()] })); }, seed: initial, principalId: actor, target: run, onClose() {}, onSaved: () => saved.push(true) };
  let tree;
  const render = () => { instance.index = 0; instance.dirty = false; hooks = instance; try { tree = AnswerKnowledgeForm(props); } finally { hooks = null; } for (const effect of instance.effects.splice(0)) effect(); };
  const flush = async () => { for (let i = 0; i < 12; i++) { if (instance.dirty) render(); await tick(); if (!instance.dirty) break; } };
  const close = () => { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; };
  t.after(() => { close(); globalThis.sessionStorage = previous; }); render();
  return { calls, saved, storage, flush, close, tree: () => tree, html: () => renderToStaticMarkup(tree), find: predicate => nodes(tree).filter(predicate), click: async text => { const node = nodes(tree).find(node => label(node) === text && typeof node.props?.onClick === "function"); assert.ok(node, `Missing ${text}`); assert.equal(node.props.disabled, false); node.props.onClick(); await flush(); }, change: async (type, index, value) => { nodes(tree).filter(node => node.type === type)[index].props.onChange({ target: { value, checked: value } }); await flush(); } };
}
function receipt(command) { return { id: id(20), category_id: category, operation: command.operation, subject_type: "category_knowledge", subject_id: id(21), subject_revision: 1, result: { lineage_id: id(21), entry_id: id(22), version: 1 } }; }
async function fill(e) { await e.change("input", 0, fields.title); await e.change("input", 1, "2099-01-01"); await e.change("textarea", 0, fields.answer); await e.change("textarea", 1, fields.review.applicability_scope); }

test("server seed and Human edit helper preserve the actual answer origin without inventing prepared model fields", () => {
  const original = seed(), before = structuredClone(original), result = lib.answerKnowledgeCommand(lib.parseAnswerSeed(original, category), fields);
  assert.equal(result.command.payload.answer_origin.run_id, run); assert.equal(result.command.payload.answer_origin.answer_digest, "a".repeat(64));
  assert.deepEqual(result.command.payload.knowledge_review, fields.review); assert.equal(result.command.payload.content.draft_origin, "ai_draft");
  assert.equal(result.command.payload.prepared_by_run_id, undefined); assert.equal(result.command.payload.candidate_digest, undefined); assert.equal(result.stage, "execute");
  assert.deepEqual(original, before); assert.throws(() => lib.parseAnswerSeed(original, id(99)));
  assert.throws(() => lib.answerKnowledgeCommand(original, { ...fields, review: { ...fields.review, responsible_id: id(99) } }));
});

test("actual form SSR shows explicit fields, no automatic write, and escapes original answer text", () => {
  const data = seed(); data.answer = '<script>alert("x")</script>';
  const html = renderToStaticMarkup(React.createElement(AnswerKnowledgeForm, { api() { throw new Error("render wrote"); }, seed: data, principalId: actor, target: run, onClose() {} }));
  for (const text of ["AI 草稿", "负责人", "适用范围", "复核日期", "2 项已核来源"]) assert.ok(html.includes(text));
  assert.match(html, /&lt;script&gt;/); assert.doesNotMatch(html, /<script/);
});

test("Human save uses the native command once, then displays an actual knowledge reopen link", async t => {
  const e = env(t); await e.flush(); assert.equal(e.calls.length, 0); await fill(e); await e.click("保存知识");
  assert.equal(e.calls.length, 1); const call = e.calls[0]; assert.equal(call.route, `v1/categories/${category}/commands`); assert.ok(call.journal.length, "journal precedes transport");
  assert.equal(call.body.payload.content.answer, fields.answer); assert.equal(call.body.payload.knowledge_review.applicability_scope, fields.review.applicability_scope);
  call.resolve(receipt(call.body)); await e.flush(); assert.equal(e.saved.length, 1); assert.match(e.html(), /href="\/\?area=knowledge"/); assert.equal(e.storage.map.size, 0);
  assert.ok(!nodes(e.tree()).some(node => label(node) === "保存知识" && node.props?.onClick), "success cannot accidentally save again");
});

test("response loss restores the exact native request key and Human edits before manual replay", async t => {
  const storage = memory(), first = env(t, seed(), storage); await first.flush(); await fill(first); await first.click("保存知识"); const original = first.calls[0].body; first.calls[0].reject(new Error("synthetic lost response")); await first.flush(); first.close();
  const reopened = env(t, seed(), storage); await reopened.flush(); assert.equal(reopened.calls.length, 0); assert.match(reopened.html(), /本人核对后回答/); await reopened.click("核对原保存请求"); assert.deepEqual(reopened.calls[0].body, original);
  reopened.calls[0].resolve(receipt(original)); await reopened.flush(); assert.match(reopened.html(), /知识已保存/);
});

test("native deidentification has the existing single preview/confirm and retains only its exact token delta", async t => {
  const e = env(t, seed("category.knowledge.promote")); await e.flush(); await fill(e); await e.change("input", 2, true); await e.click("保存知识");
  const call = e.calls[0]; assert.equal(call.route, `v1/categories/${category}/commands/preview`); assert.equal(e.calls.length, 1);
  const prepared = { ...structuredClone(call.body), payload: { ...call.body.payload, confirmation_token: "synthetic-fixed-confirmation-token" } };
  call.resolve({ command: prepared, confirmation_token: prepared.payload.confirmation_token, review: { operation: call.body.operation }, expires_at: "2099-01-01T00:00:00Z" }); await e.flush(); await e.click("确认沉淀");
  assert.deepEqual(e.calls[1].body, prepared); assert.equal(e.calls[1].body.command_id, call.body.command_id); assert.equal(e.calls[1].body.idempotency_key, call.body.idempotency_key);
});

test("structured-only real answer candidate uses native inputs then execute with zero invented Artifact refs", async () => {
  const pending = lib.answerKnowledgeCommand(seed("knowledge.candidate.create"), fields), calls = [], stages = [];
  const result = await lib.runAnswerKnowledge(async (route, command) => { calls.push({ route, command }); if (route.endsWith("/inputs")) return { payload: { ...command.payload, candidate: null, project_id: null, knowledge_review: { ...command.payload.knowledge_review, review_due_at: "2099-01-01T23:59:59+00:00" } }, required_source_read_set: [], review: {} }; return { id: id(23), operation: command.operation, subject_type: "knowledge_candidate", subject_id: id(24), subject_revision: 1, result: { id: id(24), candidate_id: id(24), revision: 1, status: "draft", project_id: null } }; }, pending, actor, step => stages.push(step));
  assert.equal(result.stage, "saved"); assert.equal(calls.length, 2); assert.deepEqual(calls[0].command.payload.sources, []); assert.deepEqual(calls[1].command.source_read_set, []); assert.equal(stages[0].command.idempotency_key, pending.command.idempotency_key);
});

test("corrupt pending journal preserves the unknown request and stops new writes", async t => {
  const storage = memory(); storage.setItem(`pdos.answer-knowledge.v1:${actor}:${category}:${run}:category.knowledge.add`, "{}"); const e = env(t, seed(), storage); await e.flush(); assert.equal(e.calls.length, 0); assert.match(e.html(), /存储暂不可用/);
  assert.equal(e.find(node => node.props?.onClick && label(node) === "保存知识")[0].props.disabled, true);
  assert.equal(lib.restoreAnswerKnowledge({}, category), null);
});

test("explicit gap payload contains only server preview identity/digest and the replay key", () => {
  const preview = { kind: "missing_material", run_id: run, feedback_id: null, question: "本次原话", answer: null, search_scope: { category_id: category }, recipient: { id: actor, name: "实际负责人", category_id: category, category_name: "合成品类" }, preview_digest: "a".repeat(64) };
  const request = lib.knowledgeShareRequest(lib.parseKnowledgeShare(preview, category, run), id(40));
  assert.deepEqual(Object.keys(request).sort(), ["feedback_id", "kind", "preview_digest", "request_key", "run_id"]);
  assert.equal(request.question, undefined); assert.equal(request.answer, undefined); assert.equal(request.recipient_id, undefined);
  assert.throws(() => lib.parseKnowledgeShare(preview, id(99), run));
});

function previewShare() { return { kind: "missing_material", run_id: run, feedback_id: null, question: "原实际问题", answer: null, search_scope: { category_id: category }, recipient: { id: actor, name: "实际负责人", category_id: category, category_name: "合成品类" }, preview_digest: "a".repeat(64) }; }
function shareReceipt(body) { return { id: id(80), state: "shared", recipient_id: actor, request_key: body.request_key, run_id: body.run_id, kind: body.kind, feedback_id: body.feedback_id }; }
function actionsEnv(t, { personal = false, storage = memory() } = {}) {
  const previous = globalThis.localStorage; globalThis.localStorage = storage;
  const calls = [], instance = { slots: [], index: 0, effects: [], dirty: true, disposed: false };
  const props = { api(route, body) { return new Promise((resolve, reject) => calls.push({ route, body: structuredClone(body), resolve, reject, journal: [...storage.map.values()] })); }, ...(personal ? {} : { categoryId: category }), principalId: actor, runId: run, runRoot: personal ? "v1/personal/agent-runs" : `v1/categories/${category}/agent-runs` };
  let tree;
  const render = () => { instance.index = 0; instance.dirty = false; hooks = instance; try { const wrapper = AnswerKnowledgeActions(props); tree = wrapper.type(wrapper.props); } finally { hooks = null; } for (const effect of instance.effects.splice(0)) effect(); };
  const flush = async () => { for (let i = 0; i < 12; i++) { if (instance.dirty) render(); await tick(); if (!instance.dirty) break; } };
  const close = () => { instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true; };
  t.after(() => { close(); globalThis.localStorage = previous; }); render();
  const find = text => nodes(tree).find(node => label(node) === text && typeof node.props?.onClick === "function");
  return { calls, props, storage, flush, close, find, tree: () => tree, html: () => renderToStaticMarkup(tree), click: async text => { const node = find(text); assert.ok(node, `Missing ${text}`); assert.equal(!!node.props.disabled, false); node.props.onClick(); await flush(); }, select: async value => { nodes(tree).find(node => node.type === "select").props.onChange({ target: { value } }); await flush(); } };
}

test("personal completed answer requires an explicit current target and keeps the actual original run", async t => {
  const e = actionsEnv(t, { personal: true }); await e.flush();
  assert.equal(e.calls.length, 1); assert.equal(e.calls[0].route, "v1/categories");
  assert.equal(e.find("存为公司知识").props.disabled, true);
  e.calls[0].resolve([{ id: category, name: "合成品类" }]); await e.flush();
  assert.equal(e.find("存为公司知识").props.disabled, true, "One readable category is not implicit consent");
  await e.select(category); await e.click("存为公司知识");
  assert.equal(e.calls.length, 2); assert.equal(e.calls[1].route, `v1/categories/${category}/experience/answer-draft`);
  assert.deepEqual(e.calls[1].body, { run_id: run, kind: "category" });
  e.calls[1].resolve(seed()); await e.flush();
  assert.match(e.html(), /整理核实答案/); assert.equal(e.calls.length, 2, "Opening only reads a draft");
});

test("lost gap response survives refresh; recovery only reads and explicit retry keeps its exact key", async t => {
  const storage = memory(), e = actionsEnv(t, { storage }); await e.flush(); await e.click("请补充资料");
  e.calls[0].resolve(previewShare()); await e.flush();
  const button = e.find("提交补充请求"); button.props.onClick(); button.props.onClick(); await e.flush();
  assert.equal(e.calls.length, 2); const original = e.calls[1];
  assert.match(original.route, /\/gaps$/); assert.equal(original.journal.length, 1, "Journal precedes transport");
  const frozen = JSON.parse(original.journal[0]);
  assert.deepEqual(frozen.request, original.body); assert.equal(frozen.question, undefined); assert.equal(frozen.answer, undefined);
  original.reject(new Error("synthetic lost response")); await e.flush(); e.close();
  const reopened = actionsEnv(t, { storage }); await reopened.flush();
  assert.equal(reopened.calls.length, 1); assert.match(reopened.calls[0].route, /\/gaps\/recover$/);
  assert.deepEqual(reopened.calls[0].body, original.body);
  reopened.calls[0].reject(Object.assign(new Error("尚未查到原请求"), { status: 404 })); await reopened.flush();
  assert.equal(reopened.calls.length, 1, "A recovery miss cannot automatically append");
  await reopened.click("重试原补充请求"); assert.equal(reopened.calls.length, 2);
  assert.deepEqual(reopened.calls[1].body, original.body); assert.match(reopened.calls[1].route, /\/gaps$/);
  reopened.calls[1].resolve(shareReceipt(original.body)); await reopened.flush();
  assert.equal(storage.map.size, 0); assert.match(reopened.html(), /已提交给品类负责人/);
});

test("exact successful gap recovery clears the journal without any replay and rejects another receipt", async t => {
  const storage = memory(), root = `v1/categories/${category}/agent-runs`;
  const pending = shareLib.prepareKnowledgeShare(previewShare(), actor, root, id(90));
  const key = shareLib.knowledgeShareStorage(actor, root, run); storage.setItem(key, JSON.stringify(pending));
  const e = actionsEnv(t, { storage }); await e.flush();
  e.calls[0].resolve({ ...shareReceipt(pending.request), request_key: id(91) }); await e.flush();
  assert.equal(storage.map.size, 1); assert.match(e.html(), /尚未核对/);
  await e.click("读取原请求结果"); e.calls[1].resolve(shareReceipt(pending.request)); await e.flush();
  assert.equal(storage.map.size, 0); assert.ok(e.calls.every(call => call.route.endsWith("/gaps/recover")));
  assert.match(e.html(), /未再次提交/);
});

test("corrupt or foreign gap journals never grant a new write or contain private answer text", async t => {
  const root = `v1/categories/${category}/agent-runs`, original = shareLib.prepareKnowledgeShare(previewShare(), actor, root, id(90));
  assert.equal(shareLib.restoreKnowledgeShare(original, id(99), root, run), null);
  assert.equal(shareLib.restoreKnowledgeShare(original, actor, root, id(99)), null);
  assert.equal(shareLib.restoreKnowledgeShare(original, actor, "v1/personal/agent-runs", run), null);
  const storage = memory(); storage.setItem(shareLib.knowledgeShareStorage(actor, root, run), "{}");
  const e = actionsEnv(t, { storage }); await e.flush();
  assert.equal(e.calls.length, 0); assert.equal(e.find("请补充资料").props.disabled, true);
  assert.equal(storage.map.size, 1); assert.match(e.html(), /记录不完整/);
});

test("unavailable durable journal prevents share transport before any request can become unknown", async t => {
  const storage = memory(), e = actionsEnv(t, { storage }); await e.flush(); await e.click("请补充资料");
  e.calls[0].resolve(previewShare()); await e.flush();
  storage.setItem = () => { throw new Error("synthetic storage unavailable"); };
  await e.click("提交补充请求"); assert.equal(e.calls.length, 1);
  assert.match(e.html(), /storage unavailable/); assert.equal(storage.map.size, 0);
});
