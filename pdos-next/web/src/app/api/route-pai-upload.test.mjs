import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../.."), ts = createRequire(path.join(web, "package.json"))("typescript");
const compile = relative => ts.transpileModule(readFileSync(path.join(web, "src", relative), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const upload = { exports: {} }, origin = { exports: {} };
runInNewContext(compile("lib/pai-upload.ts"), { module: upload, exports: upload.exports, URLSearchParams, TextEncoder, crypto: webcrypto, btoa, atob });
runInNewContext(compile("lib/request-origin.ts"), { module: origin, exports: origin.exports, URL });
const id = n => `00000000-0000-0000-0000-${n.toString(16).padStart(12, "0")}`;
const category = id(1), product = id(2), proposal = id(3), nonce = id(4), digest = "a".repeat(64);
const body = () => ({ filename: "资料.txt", title: "真实标题", source_label: "真实来源", visibility: "private", content_base64: "eA==", expected_revision: 3, idempotency_key: nonce });
function harness(options = {}) {
  const mod = { exports: {} }, calls = [];
  runInNewContext(compile("lib/pai-upload-proxy.ts"), {
    module: mod, exports: mod.exports, URLSearchParams, Response, TextDecoder, AbortSignal,
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    require: name => name === "@/lib/pai-upload" ? upload.exports : name === "@/lib/request-origin" ? origin.exports : name === "next/headers" ? { cookies: async () => ({ get: key => { assert.equal(key, "pdos-next-session"); return options.session === false ? undefined : { value: "synthetic-session" }; } }) } : assert.fail(name),
    fetch: async (url, init) => { calls.push({ url, init }); if (options.failure) throw Error("synthetic lost response"); return options.html ? new Response("<html>too large</html>", { status: 413, headers: { "Content-Type": "text/html" } }) : Response.json(options.response ?? { original: "metadata" }, { status: options.status ?? 200 }); },
  });
  function request(query, method, raw, customHeaders = {}) {
    const url = `http://localhost/api/upload${query ? `?${query}` : ""}`;
    const req = new Request(url, { method, ...(method === "GET" || method === "HEAD" ? {} : { body: raw ?? JSON.stringify(body()) }), headers: { origin: "http://localhost", host: "localhost", "content-type": "application/json", ...customHeaders } });
    Object.defineProperty(req, "nextUrl", { value: new URL(req.url) }); return req;
  }
  return { calls, mod: mod.exports, request,
    read(query = "", requestKey, cat = category, method = "GET") { return mod.exports.paiUploadRead(request(query, method), cat, requestKey); },
    post({ raw, query = "", cat = category, pid, method = "POST", headers } = {}) { return mod.exports.paiOriginalUpload(request(query, method, raw, headers), cat, pid); },
  };
}
test("target and original-nonce GETs bind explicit Product/proposal and mandatory digest", async () => {
  const h = harness();
  const query = new URLSearchParams({ product_id: product, proposal_id: proposal }).toString();
  assert.equal((await h.read(query)).status, 200);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-upload-target?${query}`);
  assert.equal((await h.read(`${query}&request_digest=${digest}`, nonce)).status, 200);
  assert.equal(h.calls[1].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-upload-receipts/${nonce}?${query}&request_digest=${digest}`);
  for (const call of h.calls) { assert.equal(call.init.method, "GET"); assert.equal(call.init.body, undefined); assert.equal(call.init.cache, "no-store"); assert.equal(call.init.redirect, "error"); }
});
test("read queries reject arbitrary scope, repeated keys, wrong digests and mutations before fetch", async () => {
  const h = harness();
  for (const query of [`product_id=${product}&product_id=${product}`, "product_id=bad", "proposal_id=bad", "principal_id=other", "page_size=20", "q=private", `request_digest=${digest}`]) assert.equal((await h.read(query)).status, 422, query);
  for (const query of ["", "request_digest=BAD", `request_digest=${digest}&request_digest=${digest}`]) assert.equal((await h.read(query, nonce)).status, 422);
  assert.equal((await h.read("", "bad")).status, 404); assert.equal((await h.read("", undefined, "bad")).status, 404);
  assert.equal((await h.read("", undefined, category, "POST")).status, 405); assert.equal(h.calls.length, 0);
});
test("existing Product uploads keep all three visibility choices and exact raw JSON", async () => {
  const h = harness();
  for (const visibility of ["private", "category", "audience"]) {
    const raw = JSON.stringify({ ...body(), visibility }); const response = await h.post({ raw, pid: product });
    assert.equal(response.status, 200); assert.equal(response.headers.get("Cache-Control"), "private, no-store");
    const call = h.calls.at(-1); assert.equal(call.url, `http://synthetic-api.invalid/v1/categories/${category}/products/${product}/originals`); assert.equal(call.init.body, raw); assert.equal(call.init.method, "POST");
  }
  const previous = body(); delete previous.visibility;
  assert.equal((await h.post({ raw: JSON.stringify(previous) })).status, 200);
});
test("write same-origin checks precede forwarding and reject missing/mismatched Origin", async () => {
  const h = harness();
  for (const origin of ["", "http://attacker.invalid", "https://localhost", "null"]) assert.equal((await h.post({ headers: { origin } })).status, 403);
  assert.equal((await h.post({ headers: { host: "other.invalid" } })).status, 403);
  assert.equal(h.calls.length, 0);
});
test("missing auth/config, path or type never forwards upload bytes", async () => {
  for (const [options, status] of [[{ session: false }, 401], [{ configured: false }, 503]]) { const h = harness(options); assert.equal((await h.post()).status, status); assert.equal(h.calls.length, 0); }
  const h = harness(); assert.equal((await h.post({ cat: "bad" })).status, 404); assert.equal((await h.post({ pid: "bad" })).status, 404);
  assert.equal((await h.post({ headers: { "content-type": "text/plain" } })).status, 415);
  assert.equal((await h.post({ query: `product_id=${product}` })).status, 422);
  assert.equal((await h.post({ method: "GET" })).status, 405); assert.equal(h.calls.length, 0);
});
test("8 MiB decoded body survives JSON expansion; one extra decoded byte is rejected before fetch", async () => {
  const h = harness(), exact = Buffer.alloc(upload.exports.MAX_UPLOAD_BYTES).toString("base64");
  assert.equal(exact.length, 11184812);
  const raw = JSON.stringify({ ...body(), content_base64: exact }); assert.ok(Buffer.byteLength(raw) > 10 * 1024 * 1024);
  assert.equal((await h.post({ raw })).status, 200); assert.equal(h.calls.length, 1);
  const extra = JSON.stringify({ ...body(), content_base64: Buffer.alloc(upload.exports.MAX_UPLOAD_BYTES + 1).toString("base64") });
  assert.equal((await h.post({ raw: extra })).status, 413); assert.equal(h.calls.length, 1);
});
test("JSON stream cap is enforced without trusting absent or false Content-Length", async () => {
  const h = harness(), cap = upload.exports.MAX_UPLOAD_JSON_BYTES;
  assert.equal((await h.post({ raw: JSON.stringify(body()), headers: { "content-length": String(cap + 1) } })).status, 413);
  assert.equal((await h.post({ raw: " ".repeat(cap + 1), headers: { "content-length": "1" } })).status, 413);
  const bytes = new TextEncoder().encode(" ".repeat(cap + 1)); let cancelled = false;
  const stream = new ReadableStream({ start(controller) { controller.enqueue(bytes); }, cancel() { cancelled = true; } });
  const request = new Request("http://localhost/api/upload", { method: "POST", body: stream, duplex: "half", headers: { origin: "http://localhost", host: "localhost", "content-type": "application/json" } });
  Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
  assert.equal((await h.mod.paiOriginalUpload(request, category)).status, 413); assert.equal(cancelled, true); assert.equal(h.calls.length, 0);
});
test("invalid/truncated JSON, forged fields and malformed base64 fail before business POST", async () => {
  const h = harness(); assert.equal((await h.post({ raw: "{\"filename\":" })).status, 422);
  for (const changed of [{ ...body(), tenant_id: id(99) }, { ...body(), content_base64: "eA==!" }, { ...body(), filename: "../x.txt" }, { ...body(), expected_revision: 0 }]) assert.equal((await h.post({ raw: JSON.stringify(changed) })).status, 422);
  assert.equal(h.calls.length, 0);
});
test("upstream HTML 413 and domain errors keep status; a lost write response is unknown, never retried", async () => {
  const html = harness({ html: true }); const response = await html.post(); assert.equal(response.status, 413); assert.match(await response.text(), /html/); assert.equal(html.calls.length, 1);
  for (const status of [401, 403, 409, 422]) { const h = harness({ status, response: { code: "FORBIDDEN_SCOPE" } }); assert.equal((await h.post()).status, status); assert.equal(h.calls.length, 1); }
  const h = harness({ failure: true }); const unknown = await h.post(); assert.equal(unknown.status, 503); assert.equal((await unknown.json()).code, "EXTERNAL_OUTCOME_UNKNOWN"); assert.equal(h.calls.length, 1);
});
test("four static routes expose only the intended method and await exact IDs", async () => {
  for (const [relative, method, params, operation, args] of [
    ["app/api/v1/categories/[categoryId]/agent-upload-target/route.ts", "GET", { categoryId: category }, "paiUploadRead", [category]],
    ["app/api/v1/categories/[categoryId]/agent-upload-receipts/[requestKey]/route.ts", "GET", { categoryId: category, requestKey: nonce }, "paiUploadRead", [category, nonce]],
    ["app/api/v1/categories/[categoryId]/originals/route.ts", "POST", { categoryId: category }, "paiOriginalUpload", [category]],
    ["app/api/v1/categories/[categoryId]/products/[productId]/originals/route.ts", "POST", { categoryId: category, productId: product }, "paiOriginalUpload", [category, product]],
  ]) {
    const mod = { exports: {} }, calls = [], request = {};
    runInNewContext(compile(relative), { module: mod, exports: mod.exports, require: name => { assert.equal(name, "@/lib/pai-upload-proxy"); return { [operation]: (...values) => calls.push(values) }; } });
    assert.deepEqual(Object.keys(mod.exports), [method]); await mod.exports[method](request, { params: Promise.resolve(params) }); assert.equal(calls[0][0], request); assert.deepEqual([...calls[0].slice(1)], args);
  }
});
