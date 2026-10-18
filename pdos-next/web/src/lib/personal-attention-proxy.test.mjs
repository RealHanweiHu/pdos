import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const ts = createRequire(path.join(web, "package.json"))("typescript");
const compile = relative => ts.transpileModule(readFileSync(path.join(web, "src", relative), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
function harness(options = {}) {
  const loaded = { exports: {} }, calls = [];
  runInNewContext(compile("lib/personal-attention-proxy.ts"), {
    module: loaded, exports: loaded.exports, URLSearchParams, Response, AbortSignal,
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    require: name => { assert.equal(name, "next/headers"); return { cookies: async () => ({ get: key => { assert.equal(key, "pdos-next-session"); return options.session === false ? undefined : { value: "synthetic-session" }; } }) }; },
    fetch: async (url, init) => { calls.push({ url, init }); if (options.failure) throw Error("synthetic failure"); return Response.json(options.body ?? { version: "personal-attention/v1", items: [] }, { status: options.status ?? 200, headers: { "Set-Cookie": "upstream-private=must-not-forward", "Cache-Control": "public, max-age=999", "Location": "https://other.invalid/", "X-Private": "must-not-forward" } }); },
  });
  return { calls, send(query = "queue=decide", method = "GET") {
    const request = new Request(`http://localhost/api/v1/personal/attention${query ? `?${query}` : ""}`, { method, headers: { Authorization: "Bearer caller-controlled", "X-Principal-ID": "caller-controlled", Cookie: "other=caller-controlled" } });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return loaded.exports.personalAttentionRead(request);
  } };
}
test("all four exact personal reads use only the session cookie as server Bearer identity", async () => {
  const h = harness();
  for (const queue of ["decide", "receive", "verify", "external"]) {
    const response = await h.send(`queue=${queue}&page_size=20&cursor=opaque_cursor-1`);
    assert.equal(response.status, 200); assert.equal(response.headers.get("Cache-Control"), "no-store");
    const { url, init } = h.calls.at(-1); assert.equal(url, `http://synthetic-api.invalid/v1/personal/attention?queue=${queue}&page_size=20&cursor=opaque_cursor-1`);
    assert.equal(init.method, "GET"); assert.deepEqual(Object.keys(init.headers), ["Authorization"]); assert.equal(init.headers.Authorization, "Bearer synthetic-session"); assert.equal(init.body, undefined); assert.equal(init.cache, "no-store"); assert.equal(init.redirect, "error");
    for (const key of ["Set-Cookie", "Location", "X-Private"]) assert.equal(response.headers.get(key), null);
  }
});
test("forbidden identity, duplicates, bad queues and invalid pagination never reach upstream", async () => {
  const h = harness();
  for (const query of ["", "queue=other", "queue=decide&queue=decide", "queue=receive&page_size=0", "queue=receive&page_size=21", "queue=receive&page_size=01", "queue=receive&page_size=1.5", "queue=receive&page_size=20&page_size=20", "queue=verify&cursor=", "queue=verify&cursor=a%2Fb", "queue=verify&cursor=a%2Bb", `queue=verify&cursor=${"a".repeat(2049)}`, "queue=verify&cursor=a&cursor=b", ...["tenant", "tenant_id", "principal_id", "requester", "requester_id", "category", "category_id", "product", "product_id", "project", "project_id", "role"].map(key => `queue=external&${key}=caller-controlled`)]) {
    assert.equal((await h.send(query)).status, 422, query.slice(0, 100));
  }
  assert.equal(h.calls.length, 0);
});
test("bounded opaque cursor is preserved exactly without decoding it into scope", async () => {
  const h = harness(); const cursor = "A_-".repeat(682) + "_-";
  assert.equal(cursor.length, 2048); assert.equal((await h.send(`queue=verify&page_size=1&cursor=${cursor}`)).status, 200); assert.equal(new URL(h.calls[0].url).searchParams.get("cursor"), cursor);
});
test("non-GET methods, missing session and missing configuration fail before networking", async () => {
  const h = harness();
  for (const method of ["HEAD", "POST", "PUT", "PATCH", "DELETE"]) { const response = await h.send("queue=decide", method); assert.equal(response.status, 405); assert.equal(response.headers.get("Allow"), "GET"); }
  assert.equal(h.calls.length, 0);
  for (const [options, status] of [[{ session: false }, 401], [{ configured: false }, 503]]) { const current = harness(options); assert.equal((await current.send()).status, status); assert.equal(current.calls.length, 0); }
});
test("upstream domain outcomes stay exact and unavailable transport is a single failed read", async () => {
  for (const status of [403, 404, 409, 503]) { const body = { code: "FORBIDDEN_SCOPE", detail: { reason: "attention_source_changed" } }, h = harness({ body, status }); const response = await h.send(); assert.equal(response.status, status); assert.deepEqual(await response.json(), body); assert.equal(h.calls.length, 1); }
  const h = harness({ failure: true }); const response = await h.send(); assert.equal(response.status, 503); assert.equal((await response.json()).code, "SOURCE_UNAVAILABLE"); assert.equal(h.calls.length, 1);
});
test("the static route exports GET alone and delegates the actual request to its narrow proxy", async () => {
  const loaded = { exports: {} }, calls = [], request = {};
  runInNewContext(compile("app/api/v1/personal/attention/route.ts"), { module: loaded, exports: loaded.exports, require: name => { assert.equal(name, "@/lib/personal-attention-proxy"); return { personalAttentionRead: value => { calls.push(value); return "actual-result"; } }; } });
  assert.deepEqual(Object.keys(loaded.exports), ["GET"]); assert.equal(await loaded.exports.GET(request), "actual-result"); assert.equal(calls[0], request);
});
