import assert from "node:assert/strict";
import { createHash, webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";
const ts = createRequire(import.meta.url)("typescript"), loaded = { exports: {} }, fetchCalls = [];
let fetchResponse = () => Response.json({});
runInNewContext(ts.transpileModule(readFileSync(new URL("./pai-upload.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText,
  { module: loaded, exports: loaded.exports, URLSearchParams, TextEncoder, crypto: webcrypto, btoa, atob, fetch: async (...args) => { fetchCalls.push(args); return fetchResponse(...args); } });
const { createUploadIntent, restoreUploadPointer, readUploadTarget, readUploadReceipt, uploadOriginal, paiUploadApi, pythonWhitespaceStrip, validUploadBody, MAX_UPLOAD_BYTES, MAX_UPLOAD_BASE64 } = loaded.exports;
const id = n => `00000000-0000-0000-0000-${n.toString(16).padStart(12, "0")}`;
const scope = { principalId: id(1), categoryId: id(2), productId: null, proposalId: id(3) };
const date = "2026-10-17T12:34:56.123456+00:00";
const clone = value => JSON.parse(JSON.stringify(value));
function target(product = null) { return { version: "agent-upload-target/v1", principal_id: scope.principalId, scope: { category_id: scope.categoryId, product_id: product, proposal_id: scope.proposalId }, as_of: date, target: { kind: product ? "product" : "category", id: product ?? scope.categoryId, revision: 5 }, authorization: { can_write: true, code: null }, constraints: { max_bytes: 8388608, extensions: [".txt", ".md", ".pdf", ".xlsx"], default_visibility: "private" } }; }
function file(content = "真实原字节\n", name = "资料.txt") { const bytes = new TextEncoder().encode(content); return { name, size: bytes.length, arrayBuffer: async () => bytes.slice().buffer }; }
const intent = () => createUploadIntent(file(), { title: " 原标题 ", sourceLabel: " 来源说明 " }, target());
function reading(original, state = "committed") {
  const pointer = original.pointer ?? original;
  return { version: "agent-upload-receipt/v1", principal_id: pointer.principal_id, scope: clone(pointer.scope), as_of: date, request_key: pointer.request_key, request_digest: pointer.request_digest, state,
    receipt: state === "committed" ? { id: id(70), operation: "evidence.original.upload", subject_type: "uploaded_original", subject_id: id(80), subject_revision: 1, writer_id: scope.principalId, requester_id: scope.principalId, created_at: date } : null,
    attempt: state === "not_observed" ? null : { id: id(80), revision: 2, status: state },
    original: state === "committed" ? { id: id(80), revision: 2, title: pointer.metadata.title, filename: pointer.metadata.filename, parse_status: "uploaded", parse_code: null, scan_status: "not_scanned", security: { state: "not_scanned", reasons: ["SCAN_REQUIRED"], epoch: 1, source_state: "active" } } : null,
    source: null };
}
function apiFor(value) { const calls = []; return { calls, api: async (...args) => { calls.push(args); return clone(value); } }; }

test("intent hashes exact bytes and UTF-8 sorted metadata, with a bytes-free nonce pointer", async () => {
  const value = await intent(), content = new TextEncoder().encode("真实原字节\n");
  const hash = createHash("sha256").update(content).digest("hex");
  const canonical = JSON.stringify({ content_hash: hash, expected_revision: 5, filename: "资料.txt", source_label: "来源说明", title: "原标题", visibility: "private" });
  assert.equal(value.pointer.file.content_hash, hash);
  assert.equal(value.pointer.request_digest, createHash("sha256").update(canonical, "utf8").digest("hex"));
  assert.equal(value.body.idempotency_key, value.pointer.request_key); assert.equal(value.body.content_base64, Buffer.from(content).toString("base64"));
  assert.ok(!JSON.stringify(value.pointer).includes("content_base64")); assert.ok(!JSON.stringify(value.pointer).includes(value.body.content_base64));
  assert.deepEqual(clone((await restoreUploadPointer(clone(value.pointer), scope))), clone(value.pointer));
});
test("Python whitespace normalization keeps wire metadata stable and does not remove FEFF", async () => {
  assert.equal(pythonWhitespaceStrip("\u0085\u001c 标题 \u001f\u3000"), "标题");
  assert.equal(pythonWhitespaceStrip("\ufeff标题\ufeff"), "\ufeff标题\ufeff");
  const value = await createUploadIntent(file("x", "\u0085资料.txt\u001c"), { title: "\u0085标题\u001c", sourceLabel: "\u001f来源\u0085" }, target());
  assert.equal(value.body.filename, "资料.txt"); assert.equal(value.body.title, "标题"); assert.equal(value.body.source_label, "来源");
  assert.equal(pythonWhitespaceStrip(value.body.filename), value.body.filename);
});
test("restore never adds bytes, trusts a forged digest or moves an original nonce into a new scope", async () => {
  const value = await intent();
  for (const mutate of [v => { v.request_digest = "0".repeat(64); }, v => { v.metadata.title = "changed"; }, v => { v.content_base64 = "eA=="; }, v => { v.file.bytes = [1]; }, v => { v.request_key = "bad"; }, v => { v.target.revision = 6; }]) { const pointer = clone(value.pointer); mutate(pointer); assert.equal(await restoreUploadPointer(pointer, scope), null); }
  assert.equal(await restoreUploadPointer(value.pointer, { ...scope, principalId: id(99) }), null);
  assert.equal(await restoreUploadPointer(value.pointer, { ...scope, productId: id(99) }), null);
});
test("reselected exact file restores original nonce/body even when target has a newer revision", async () => {
  const original = await intent(), newer = target(); newer.target.revision = 6;
  const restored = await createUploadIntent(file(), { title: "ignored new title", sourceLabel: "ignored source", visibility: "category" }, newer, original.pointer);
  assert.deepEqual(clone(restored), clone(original));
  await assert.rejects(createUploadIntent(file("changed bytes"), {}, newer, original.pointer));
  await assert.rejects(createUploadIntent(file("真实原字节\n", "other.txt"), {}, newer, original.pointer));
});
test("new intent requires current writable target, supported nonempty file and declared source", async () => {
  let reads = 0; const huge = { name: "large.pdf", size: MAX_UPLOAD_BYTES + 1, arrayBuffer: async () => { reads++; return new ArrayBuffer(0); } };
  await assert.rejects(createUploadIntent(huge, { sourceLabel: "来源" }, target())); assert.equal(reads, 0);
  for (const bad of [file(""), file("x", "bad.exe"), file("x", "../bad.txt")]) await assert.rejects(createUploadIntent(bad, { sourceLabel: "来源" }, target()));
  const denied = target(); denied.authorization = { can_write: false, code: "FORBIDDEN_SCOPE" };
  await assert.rejects(createUploadIntent(file(), { sourceLabel: "来源" }, denied));
  await assert.rejects(createUploadIntent(file(), { sourceLabel: "   " }, target()));
});
test("body validation retains all three existing visibility choices and enforces decoded byte bounds", async () => {
  const value = await intent(); for (const visibility of ["private", "category", "audience"]) assert.equal(validUploadBody({ ...value.body, visibility }), true);
  const body = clone(value.body); delete body.visibility; assert.equal(validUploadBody(body), true);
  for (const mutate of [v => { v.tenant_id = id(99); }, v => { v.content_base64 = "eA==!"; }, v => { v.filename = "x.exe"; }, v => { v.visibility = "public"; }, v => { v.expected_revision = 0; }]) { const bad = clone(value.body); mutate(bad); assert.equal(validUploadBody(bad), false); }
  const max = Buffer.alloc(MAX_UPLOAD_BYTES).toString("base64"); assert.equal(max.length, MAX_UPLOAD_BASE64); assert.equal(validUploadBody({ ...value.body, content_base64: max }), true);
  assert.equal(validUploadBody({ ...value.body, content_base64: Buffer.alloc(MAX_UPLOAD_BYTES + 1).toString("base64") }), false);
});
test("target and receipt GETs bind current owner/scope and exact nonce/digest without a body", async () => {
  const h = apiFor(target()); const got = await readUploadTarget(h.api, scope);
  assert.equal(h.calls[0].length, 1); assert.equal(h.calls[0][0], `v1/categories/${scope.categoryId}/agent-upload-target?proposal_id=${scope.proposalId}`); assert.deepEqual(clone(got), target());
  const original = await intent(), history = apiFor(reading(original)); await readUploadReceipt(history.api, scope, original.pointer);
  assert.equal(history.calls[0].length, 1); assert.equal(history.calls[0][0], `v1/categories/${scope.categoryId}/agent-upload-receipts/${original.pointer.request_key}?proposal_id=${scope.proposalId}&request_digest=${original.pointer.request_digest}`);
});
test("all four authoritative receipt states stay distinct and not_observed never becomes failure", async () => {
  const value = await intent();
  for (const state of ["committed", "reserved", "abandoned", "not_observed"]) assert.equal((await readUploadReceipt(apiFor(reading(value, state)).api, scope, value.pointer)).state, state);
  const hidden = reading(value); hidden.original = null; hidden.source = null; hidden.attempt = null;
  assert.equal((await readUploadReceipt(apiFor(hidden).api, scope, value.pointer)).original, null);
});
for (const [name, mutate] of [
  ["different principal", v => { v.principal_id = id(99); }], ["different scope", v => { v.scope.category_id = id(99); }],
  ["different nonce", v => { v.request_key = id(99); }], ["different digest", v => { v.request_digest = "0".repeat(64); }],
  ["missing committed receipt", v => { v.receipt = null; }], ["different receipt owner", v => { v.receipt.requester_id = id(99); }],
  ["different subject", v => { v.original.id = id(99); }], ["uncommitted attempt", v => { v.attempt.status = "reserved"; }],
  ["missing original safety", v => { delete v.original.security; }], ["mixed raw body", v => { v.original.content = "private text"; }],
  ["false not_observed", v => { v.state = "not_observed"; }], ["unsupported state", v => { v.state = "failed"; }],
]) test(`authoritative read fails closed on ${name}`, async () => { const value = await intent(), raw = reading(value); mutate(raw); await assert.rejects(readUploadReceipt(apiFor(raw).api, scope, value.pointer)); });
test("POST response alone never marks success; exact read-back can recover a lost response", async () => {
  const value = await intent(), calls = [], failure = Object.assign(new Error("lost response"), { status: 503, code: "EXTERNAL_OUTCOME_UNKNOWN" });
  const api = async (path, body) => { calls.push({ path, body }); if (body) throw failure; return reading(value); };
  const result = await uploadOriginal(api, scope, value); assert.equal(result.reading.state, "committed"); assert.equal(result.postError.status, 503);
  assert.equal(calls.length, 2); assert.equal(calls[0].path, `v1/categories/${scope.categoryId}/originals`); assert.deepEqual(clone(calls[0].body), clone(value.body)); assert.equal(calls[1].body, undefined);
  const empty = await uploadOriginal(async (_path, body) => body ? { unrelated: true } : reading(value, "not_observed"), scope, value);
  assert.equal(empty.reading.state, "not_observed");
});
test("read-back failure preserves POST phase information without claiming committed", async () => {
  const value = await intent(); let posts = 0;
  await assert.rejects(uploadOriginal(async (_path, body) => { if (body) { posts++; return {}; } throw Object.assign(new Error("scope lost"), { status: 403 }); }, scope, value), failure => failure.status === 403 && failure.postResponseReceived === true && failure.postError === null);
  assert.equal(posts, 1);
});
test("mutated original body is rejected before POST; no automatic new key or file replacement", async () => {
  const value = await intent(), changed = clone(value); changed.body.content_base64 = btoa("different"); let calls = 0;
  await assert.rejects(uploadOriginal(async () => { calls++; }, scope, changed)); assert.equal(calls, 0);
  changed.body = clone(value.body); changed.body.title = "changed title";
  await assert.rejects(uploadOriginal(async () => { calls++; }, scope, changed)); assert.equal(calls, 0);
});
test("dedicated fetch preserves HTML 413/401 status and never automatically retries", async () => {
  for (const status of [413, 401]) {
    const before = fetchCalls.length; fetchResponse = () => new Response("<html>upstream error</html>", { status });
    await assert.rejects(paiUploadApi("v1/categories/test/originals", {}), failure => failure.status === status);
    assert.equal(fetchCalls.length, before + 1);
  }
  fetchResponse = () => new Response("", { status: 200 }); assert.equal(await paiUploadApi("v1/categories/test/originals", {}), null);
});
