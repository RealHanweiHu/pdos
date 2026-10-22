import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ts = createRequire(path.join(web, "package.json"))("typescript");
const compile = relative => ts.transpileModule(readFileSync(path.join(web, "src", relative), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const category = "11111111-1111-4111-8111-111111111111", session = "22222222-2222-4222-8222-222222222222", cursor = "33333333-3333-4333-8333-333333333333";
function harness(options = {}) {
  const loaded = { exports: {} }, calls = [];
  runInNewContext(compile("lib/pai-sessions-proxy.ts"), {
    module: loaded, exports: loaded.exports, URLSearchParams, Response, AbortSignal,
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    require: name => { assert.equal(name, "next/headers"); return { cookies: async () => ({ get: key => { assert.equal(key, "pdos-next-session"); return options.session === false ? undefined : { value: "synthetic-session" }; } }) }; },
    fetch: async (url, init) => { calls.push({ url, init }); if (options.failure) throw Error("synthetic failure"); return Response.json(options.body ?? { version: "agent-session-list/v1", items: [] }, { status: options.status ?? 200 }); },
  });
  return { calls, proxy: loaded.exports.paiSessionsRead, send(query = "", categoryId, sessionId, method = "GET") {
    const request = new Request(`http://localhost/api/sessions${query ? `?${query}` : ""}`, { method });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return loaded.exports.paiSessionsRead(request, categoryId, sessionId);
  } };
}
test("personal and category reads bind exact scope and never carry a mutation body", async () => {
  const h = harness();
  for (const [cat, sid, suffix] of [[undefined, undefined, "personal/agent-sessions"], [category, undefined, `categories/${category}/agent-sessions`], [undefined, session, `personal/agent-sessions/${session}/runs`], [category, session, `categories/${category}/agent-sessions/${session}/runs`]]) {
    const response = await h.send(`page_size=2&cursor=${cursor}`, cat, sid);
    assert.equal(response.status, 200); assert.equal(response.headers.get("Cache-Control"), "no-store");
    const { url, init } = h.calls.at(-1); assert.equal(url, `http://synthetic-api.invalid/v1/${suffix}?page_size=2&cursor=${cursor}`);
    assert.equal(init.method, "GET"); assert.equal(init.headers.Authorization, "Bearer synthetic-session"); assert.equal(init.body, undefined); assert.equal(init.cache, "no-store"); assert.equal(init.redirect, "error");
  }
});
test("search literal characters are encoded and proposal scope stays category-bound", async () => {
  const h = harness(), q = "原值%_\\ &? #", query = new URLSearchParams({ q, proposal_id: cursor }).toString();
  assert.equal((await h.send(query, category)).status, 200);
  const url = new URL(h.calls[0].url); assert.equal(url.searchParams.get("q"), q); assert.equal(url.searchParams.get("proposal_id"), cursor);
  assert.equal((await h.send(`proposal_id=${cursor}`)).status, 422);
  assert.equal((await h.send("q=history", category, session)).status, 422);
  assert.equal(h.calls.length, 1);
});
test("search length matches the API Unicode-character bound", async () => {
  const h = harness();
  assert.equal((await h.send(new URLSearchParams({ q: "🧪".repeat(160) }).toString(), category)).status, 200);
  assert.equal((await h.send(new URLSearchParams({ q: "🧪".repeat(161) }).toString(), category)).status, 422);
  assert.equal(h.calls.length, 1);
});
test("unknown, repeated and malformed queries fail before network access", async () => {
  const h = harness();
  for (const query of ["page_size=0", "page_size=51", "page_size=01", "page_size=1.5", "page_size=1&page_size=2", "q=a&q=b", `q=${"x".repeat(161)}`, "cursor=bad", `cursor=${cursor}&cursor=${cursor}`, "proposal_id=bad", "tenant_id=other", "principal_id=other", "category_id=other", "product_id=other", "session_id=other", "status=completed"]) assert.equal((await h.send(query, category)).status, 422, query);
  assert.equal(h.calls.length, 0);
});
test("malformed route identity and all non-read methods never reach the API", async () => {
  const h = harness(); assert.equal((await h.send("", "bad")).status, 404); assert.equal((await h.send("", category, "bad")).status, 404);
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) { const response = await h.send("", category, session, method); assert.equal(response.status, 405); assert.equal(response.headers.get("Allow"), "GET"); }
  assert.equal(h.calls.length, 0);
});
test("missing identity or configuration fails closed before network access", async () => {
  for (const [options, status] of [[{ session: false }, 401], [{ configured: false }, 503]]) { const h = harness(options); assert.equal((await h.send()).status, status); assert.equal(h.calls.length, 0); }
});
test("domain rejection and unavailable transport keep the actual outcome without retry", async () => {
  for (const status of [403, 404, 409, 503]) { const body = { code: "FORBIDDEN_SCOPE", detail: { reason: "session_not_readable" } }, h = harness({ body, status }); const response = await h.send(); assert.equal(response.status, status); assert.deepEqual(await response.json(), body); assert.equal(h.calls.length, 1); }
  const h = harness({ failure: true }); assert.equal((await h.send()).status, 503); assert.equal(h.calls.length, 1);
});
test("all four static route modules expose only GET and await the real route parameters", async () => {
  for (const [relative, params, args] of [
    ["app/api/v1/personal/agent-sessions/route.ts", {}, []],
    ["app/api/v1/personal/agent-sessions/[sessionId]/runs/route.ts", { sessionId: session }, [undefined, session]],
    ["app/api/v1/categories/[categoryId]/agent-sessions/route.ts", { categoryId: category }, [category]],
    ["app/api/v1/categories/[categoryId]/agent-sessions/[sessionId]/runs/route.ts", { categoryId: category, sessionId: session }, [category, session]],
  ]) {
    const loaded = { exports: {} }, calls = [], request = {};
    runInNewContext(compile(relative), { module: loaded, exports: loaded.exports, require: name => { assert.equal(name, "@/lib/pai-sessions-proxy"); return { paiSessionsRead: (...values) => calls.push(values) }; } });
    assert.deepEqual(Object.keys(loaded.exports), ["GET"]); await loaded.exports.GET(request, { params: Promise.resolve(params) });
    assert.equal(calls[0][0], request); assert.deepEqual([...calls[0].slice(1)], args);
  }
});
