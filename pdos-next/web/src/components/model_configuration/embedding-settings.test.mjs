import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

// Self-contained tests: installed compiler, local fixtures, no DB/Next build/network.
const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const cache = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (!filename) throw new Error("Owned module not found");
  if (cache.has(filename)) return cache.get(filename).exports;
  const mod = new Module(filename), requireLocal = createRequire(filename); cache.set(filename, mod);
  mod.require = name => name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : requireLocal(name);
  mod._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return mod.exports;
}
const helpers = load(path.join(web, "src/lib/embedding-settings.ts"));
const { EmbeddingProfileEditor, EmbeddingReview, EmbeddingUsage } = load(path.join(directory, "embedding-settings.tsx"));
const id = n => `00000000-0000-0000-0000-${n.toString(16).padStart(12, "0")}`;
const category = id(1), principal = id(2), profileId = id(3), callId = id(4);
const metadata = { base_url: "https://synthetic.invalid/v1", model: "embedding-test", model_version: "v1", dimensions: 512, connection_id: id(5), data_categories: ["internal"], include_customer_original: false };
const payload = () => ({ profile_id: profileId, expected_revision: 0, metadata: structuredClone(metadata), enabled: false, expected_budget_revision: 0, index_budget_micro_usd: 1000000 });
const command = () => helpers.newEmbeddingCommand(category, 7, "embedding.profile.save", payload());
const now = Date.parse("2026-10-29T00:00:00Z");
function preview(original = command()) {
  return { command: { ...structuredClone(original), payload: { ...structuredClone(original.payload), confirmation_token: "synthetic-confirmation-token" } }, expires_at: "2026-10-29T00:05:00Z", review: { provider: "synthetic.invalid", profile_id: profileId, next_revision: 1, next_budget_revision: 1, metadata: structuredClone(metadata), enabled: false, expected_sources: null, estimate_scope: "current_requester_readable", estimated_cost_micro_usd: null, estimate_truncated: false, credential_status: "missing", index_budget_micro_usd: 1000000 } };
}
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));

test("independent metadata accepts explicit endpoint/connection and enforces original selection", () => {
  assert.equal(helpers.validEmbeddingMetadata(metadata), true);
  for (const base_url of ["http://localhost:8123/v1", "http://127.0.0.1:8123/v1", "http://[::1]:8123/v1"]) assert.equal(helpers.validEmbeddingMetadata({ ...metadata, base_url }), true);
  for (const patch of [{ connection_id: "" }, { dimensions: 0 }, { dimensions: 2001 }, { dimensions: 1.2 }, { model: "bad model" }, { base_url: "http://remote.invalid" }, { base_url: "https://key@synthetic.invalid" }, { base_url: "https://synthetic.invalid?q=key" }, { base_url: "https://synthetic.invalid/#key" }, { data_categories: [] }, { data_categories: ["internal", "internal"] }, { data_categories: ["customer_original"] }, { include_customer_original: true }, { secret_reference: "must-not-be-accepted" }]) assert.equal(helpers.validEmbeddingMetadata({ ...metadata, ...patch }), false, JSON.stringify(patch));
  assert.equal(helpers.validEmbeddingMetadata({ ...metadata, data_categories: ["customer_original"], include_customer_original: true }), true);
});
test("USD conversion is exact to microdollars without floating rounding or silent overflow", () => {
  for (const [text, amount] of [["0", 0], ["0.000001", 1], ["1.234567", 1234567], ["2147.483647", 2147483647]]) assert.equal(helpers.embeddingMicroDollars(text), amount);
  for (const value of ["", "-1", "01", "1e2", "0.0000001", "2147.483648", "Infinity", " "]) assert.throws(() => helpers.embeddingMicroDollars(value));
  assert.equal(helpers.embeddingDollars(1000000), "1"); assert.equal(helpers.embeddingDollars(1), "0.000001"); assert.equal(helpers.embeddingDollars(0), "0");
});
test("COMMON commands bind true category revision with no product, reads or inferred chat credential", () => {
  const value = command(); assert.equal(value.category_id, category); assert.equal(value.expected_revision, 7); assert.equal(value.product_id, null); assert.deepEqual(value.source_read_set, []); assert.equal(value.operation, "embedding.profile.save"); assert.equal(value.payload.metadata.connection_id, metadata.connection_id);
  for (const revision of [0, -1, undefined, 1.2]) assert.throws(() => helpers.newEmbeddingCommand(category, revision, value.operation, payload()));
  assert.throws(() => helpers.newEmbeddingCommand(category, 1, value.operation, { ...payload(), confirmation_token: "synthetic-confirmation-token" }));
});
test("preview retains exact original command and rejects substituted scope, budget, categories and expired proof", () => {
  const original = command(), good = preview(original); assert.equal(helpers.validEmbeddingPreview(good, original, now), true);
  const changed = mutation => { const value = structuredClone(good); mutation(value); assert.equal(helpers.validEmbeddingPreview(value, original, now), false); };
  for (const mutation of [v => { v.command.category_id = id(9); }, v => { v.command.command_id = id(9); }, v => { v.command.idempotency_key = id(9); }, v => { v.command.expected_revision++; }, v => { v.command.product_id = id(9); }, v => { v.command.source_read_set = [{ id: id(9) }]; }, v => { v.command.payload.enabled = true; }, v => { v.command.payload.metadata.connection_id = id(9); }, v => { v.command.payload.metadata.data_categories = ["customer_original"]; }, v => { v.command.payload.index_budget_micro_usd++; }, v => { v.review.metadata.model = "other"; }, v => { v.review.next_budget_revision++; }, v => { v.expires_at = "2026-10-28T23:00:00Z"; }, v => { v.command.payload.confirmation_token = "short"; }, v => { v.confirmation_token = "other-token"; }]) changed(mutation);
});
test("enabled preview must expose source/price estimate and independently bound credential", () => {
  const original = command(); original.payload.enabled = true;
  const value = preview(original); Object.assign(value.review, { enabled: true, expected_sources: 12, estimated_cost_micro_usd: 3500, credential_status: "bound" });
  assert.equal(helpers.validEmbeddingPreview(value, original, now), true);
  for (const patch of [{ provider: undefined }, { credential_status: "missing" }, { expected_sources: null }, { estimated_cost_micro_usd: null }, { estimate_scope: "all_tenant" }]) assert.equal(helpers.validEmbeddingPreview({ ...value, review: { ...value.review, ...patch } }, original, now), false);
});
test("restoration keeps the same confirmed request and rejects altered envelope or extra secret fields", () => {
  const confirmed = preview().command;
  assert.deepEqual(helpers.parseEmbeddingPending(JSON.stringify(confirmed), category), confirmed);
  for (const value of [{ ...confirmed, category_id: id(9) }, { ...confirmed, product_id: id(9) }, { ...confirmed, extra: true }, { ...confirmed, operation: "model.configuration.save" }, { ...confirmed, payload: { ...confirmed.payload, confirmation_token: undefined } }, { ...confirmed, payload: { ...confirmed.payload, secret_reference: "must-not-restore" } }]) assert.throws(() => helpers.parseEmbeddingPending(JSON.stringify(value), category));
});
test("receipt binding requires matching human, operation, subject revision and profile result", () => {
  const original = preview().command;
  const receipt = { id: id(11), operation: original.operation, category_id: category, writer_id: principal, requester_id: principal, agent_run_id: null, subject_type: "embedding_profile", subject_revision: 1, result: { profile_id: profileId, enabled: false } };
  assert.equal(helpers.embeddingReceiptMatches(receipt, original, principal), true);
  for (const patch of [{ category_id: id(9) }, { writer_id: id(9) }, { requester_id: id(9) }, { agent_run_id: id(9) }, { subject_revision: 2 }, { subject_type: "model_configuration" }, { result: { profile_id: id(9), enabled: false } }]) assert.equal(helpers.embeddingReceiptMatches({ ...receipt, ...patch }, original, principal), false);
});
test("new profile defaults to internal only, customer originals off and disabled with no secret input", () => {
  let calls = 0; const html = render(EmbeddingProfileEditor, { profile: null, budget: null, onPreview: async () => { calls++; } });
  assert.match(html, /id="[^"]+-internal"[^>]*checked=""/);
  for (const key of ["customer", "original", "enabled"]) assert.doesNotMatch(html, new RegExp(`id="[^\"]+-${key}"[^>]*checked`));
  for (const text of ["独立凭据连接 ID", "聊天连接不会自动复用", "核对配置并预览"]) assert.ok(html.includes(text));
  assert.equal(html.includes('type="password"'), false); assert.equal(html.includes("API Key"), false); assert.equal(html.includes("secret_reference"), false); assert.equal(calls, 0);
  const ids = [...html.matchAll(/id="([^"]+)"/g)].map(match => match[1]); assert.equal(new Set(ids).size, ids.length); for (const id of ids) assert.ok(html.includes(`for="${id}"`));
});
test("disabled editor cannot submit and preview hides public connection id while showing real decision fields", () => {
  const html = render(EmbeddingProfileEditor, { profile: null, budget: null, disabled: true, onPreview: async () => {} }); assert.match(html, /<fieldset disabled=""/); assert.match(html, /<button[^>]*disabled=""/);
  const review = render(EmbeddingReview, { preview: preview() }); for (const value of [metadata.base_url, metadata.model, "512", "内部资料", "客户原件", "预计来源", "预计费用", "关键词"]) assert.ok(review.includes(value)); assert.equal(review.includes(metadata.connection_id), false);
});
const call = { call_id: callId, revision: 3, batch_id: id(6), profile_version_id: id(7), attempt: 1, state: "unknown_usage", batch_state: "completed", last_error: "synthetic-redacted", provider: "synthetic.invalid", data_categories: ["internal"], source_count: 2, character_count: 600, reserved_micro_usd: 500, charged_micro_usd: 500, input_tokens: null, usage_known: false, created_at: "2026-10-29T00:00:00Z" };
test("only unknown calls expose original-fee reconciliation; no raw error/vector/storage field renders", () => {
  const reading = { category_revision: 7, default_retrieval: "keyword", scope: "current_requester_readable", budget: { revision: 1, limit_micro_usd: 1000000, held_micro_usd: 0, spent_micro_usd: 500 }, profiles: [], profiles_truncated: false, batch_counts: { completed: 1 }, calls: [call], next_cursor: null };
  const html = render(EmbeddingUsage, { reading, disabled: false, onPreview: async () => {}, onMore() {} });
  for (const text of ["保守占账", "核对这次原调用费用", "对账凭证引用", "不会重发", "实际输入 tokens"]) assert.ok(html.includes(text));
  assert.equal(html.includes(call.last_error), false);
  for (const state of ["completed", "started", "reconciled", "failed"]) assert.equal(helpers.canReconcileEmbeddingCall({ ...call, state }), false);
  assert.equal(helpers.canReconcileEmbeddingCall({ ...call, state: "unknown" }), true);
  assert.equal(render(EmbeddingUsage, { reading: { ...reading, calls: [{ ...call, state: "reconciled" }] }, disabled: false, onPreview: async () => {}, onMore() {} }).includes("对账凭证引用"), false);
});
test("reconciliation preview binds exact original call revision, usage and evidence with no reissue operation", () => {
  const original = helpers.newEmbeddingCommand(category, 7, "embedding.call.reconcile", { call_id: callId, expected_revision: 3, input_tokens: 22, actual_micro_usd: 100, evidence_ref: "synthetic-ledger-1" });
  const value = { command: { ...original, payload: { ...original.payload, confirmation_token: "synthetic-confirmation-token" } }, expires_at: "2026-10-29T00:05:00Z", review: { call_id: callId, state: "unknown_usage", charged_micro_usd: 500, actual_micro_usd: 100, input_tokens: 22, evidence_ref: "synthetic-ledger-1" } };
  assert.equal(helpers.validEmbeddingPreview(value, original, now), true);
  for (const patch of [{ call_id: id(9) }, { actual_micro_usd: 101 }, { input_tokens: 23 }, { evidence_ref: "other" }, { state: "completed" }]) assert.equal(helpers.validEmbeddingPreview({ ...value, review: { ...value.review, ...patch } }, original, now), false);
});
const compile = relative => ts.transpileModule(readFileSync(path.join(web, "src", relative), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function proxyHarness(options = {}) {
  const loaded = { exports: {} }, calls = [];
  runInNewContext(compile("lib/embedding-settings-proxy.ts"), { module: loaded, exports: loaded.exports, URLSearchParams, Response, AbortSignal, process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } }, require: name => { assert.equal(name, "next/headers"); return { cookies: async () => ({ get: () => options.session === false ? undefined : { value: "synthetic-session" } }) }; }, fetch: async (url, init) => { calls.push({ url, init }); if (options.failure) throw Error("synthetic"); return Response.json(options.body ?? { metadata_only: true }, { status: options.status ?? 200 }); } });
  return { calls, send(query = "", categoryId = category, method = "GET") { const request = new Request(`http://localhost/api/embedding${query ? `?${query}` : ""}`, { method }); Object.defineProperty(request, "nextUrl", { value: new URL(request.url) }); return loaded.exports.embeddingSettingsRead(request, categoryId); } };
}
test("page BFF forwards only metadata GET with explicit category/pagination and never embedding/body", async () => {
  const h = proxyHarness(), response = await h.send(`after=${callId}&page_size=20`); assert.equal(response.status, 200); assert.equal(response.headers.get("Cache-Control"), "private, no-store"); assert.equal(h.calls.length, 1); const request = h.calls[0]; assert.equal(request.url, `http://synthetic-api.invalid/v1/categories/${category}/embedding-profile?after=${callId}&page_size=20`); assert.equal(request.init.method, "GET"); assert.equal(request.init.body, undefined); assert.equal(request.init.cache, "no-store"); assert.equal(request.init.redirect, "error"); assert.equal(request.init.headers.Authorization, "Bearer synthetic-session");
});
test("BFF rejects arbitrary scope, query embeddings, duplicate cursors and methods before upstream", async () => {
  const h = proxyHarness(); for (const query of ["q=private", "query=private", "include_text=true", "tenant_id=other", `category_id=${category}`, "after=bad", `after=${callId}&after=${callId}`, "page_size=0", "page_size=101", "page_size=01", "page_size=1&page_size=2"]) assert.equal((await h.send(query)).status, 422, query);
  assert.equal((await h.send("", "bad")).status, 404); for (const method of ["POST", "PUT", "DELETE"]) assert.equal((await h.send("", category, method)).status, 405); assert.equal(h.calls.length, 0);
});
test("BFF keeps session/domain denial and service errors visible without retries or fallback", async () => {
  for (const [options, status] of [[{ session: false }, 401], [{ configured: false }, 503], [{ failure: true }, 503], [{ status: 403, body: { code: "FORBIDDEN_SCOPE" } }, 403], [{ status: 409 }, 409]]) { const h = proxyHarness(options); assert.equal((await h.send()).status, status); assert.equal(h.calls.length, options.session === false || options.configured === false ? 0 : 1); }
});
test("exact Next 16 route awaits params and exports GET only", async () => {
  const loaded = { exports: {} }, calls = [], request = {};
  runInNewContext(compile("app/api/v1/categories/[categoryId]/embedding-profile/route.ts"), { module: loaded, exports: loaded.exports, require: name => { assert.equal(name, "@/lib/embedding-settings-proxy"); return { embeddingSettingsRead: (...args) => calls.push(args) }; } });
  assert.deepEqual(Object.keys(loaded.exports), ["GET"]); await loaded.exports.GET(request, { params: Promise.resolve({ categoryId: category }) }); assert.equal(calls[0][0], request); assert.equal(calls[0][1], category);
});
