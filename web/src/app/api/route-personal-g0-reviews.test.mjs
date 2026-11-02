import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ts = createRequire(path.join(web, "package.json"))("typescript");
const code = ts.transpileModule(readFileSync(path.join(web, "src/app/api/v1/personal/g0-reviews/route.ts"), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const cursor = "11111111-1111-4111-8111-111111111111";
function harness(options = {}) {
  const route = { exports: {} }, calls = [];
  runInNewContext(code, {
    module: route, exports: route.exports, URLSearchParams, Response, AbortSignal,
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    require: name => { assert.equal(name, "next/headers"); return { cookies: async () => ({ get: key => { assert.equal(key, "pdos-next-session"); return options.session === false ? undefined : { value: "synthetic-session" }; } }) }; },
    fetch: async (url, init) => { calls.push({ url, init }); if (options.failure) throw new Error("synthetic failure"); return Response.json(options.body ?? { total_pending: 2, items: [{ submission: { id: cursor, revision: 3 } }] }, { status: options.status ?? 200 }); },
  });
  return { calls, exports: route.exports, send(query = "") {
    const request = new Request(`http://localhost:3000/api/v1/personal/g0-reviews${query ? `?${query}` : ""}`);
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return route.exports.GET(request);
  } };
}
test("personal G0 queue forwards the exact authenticated paginated GET and unchanged body", async () => {
  const h = harness(), query = `page_size=1&cursor=${cursor}`, response = await h.send(query);
  assert.equal(response.status, 200); assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), { total_pending: 2, items: [{ submission: { id: cursor, revision: 3 } }] });
  assert.deepEqual(Object.keys(h.exports), ["GET"]);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/personal/g0-reviews?${query}`);
  assert.equal(h.calls[0].init.method, "GET"); assert.equal(h.calls[0].init.headers.Authorization, "Bearer synthetic-session");
  assert.equal(h.calls[0].init.body, undefined); assert.equal(h.calls[0].init.cache, "no-store"); assert.equal(h.calls[0].init.redirect, "error");
});
test("default read is accepted while malformed pagination and alternate scopes never reach the API", async () => {
  const h = harness(); assert.equal((await h.send()).status, 200);
  for (const query of ["page_size=0", "page_size=101", "page_size=1.5", "page_size=01", "page_size=1&page_size=2", "cursor=bad", `cursor=${cursor}&cursor=${cursor}`, "tenant_id=other", "requester_id=other", "category_id=other", "proposal_id=other", "status=approved"]) assert.equal((await h.send(query)).status, 422, query);
  assert.equal(h.calls.length, 1);
});
test("missing caller session or backend configuration fails closed before any network read", async () => {
  for (const [options, status] of [[{ session: false }, 401], [{ configured: false }, 503]]) {
    const h = harness(options); assert.equal((await h.send()).status, status); assert.equal(h.calls.length, 0);
  }
});
test("actual authorization and stale cursor errors keep their status and details", async () => {
  for (const status of [403, 404, 409]) {
    const body = { code: "SOURCE_STALE", detail: { reason: "review_cursor_unavailable" } }, h = harness({ body, status });
    const response = await h.send(`cursor=${cursor}`); assert.equal(response.status, status); assert.deepEqual(await response.json(), body); assert.equal(h.calls.length, 1);
  }
});
test("read transport failure stays unavailable and never retries or creates a command", async () => {
  const h = harness({ failure: true }), response = await h.send();
  assert.equal(response.status, 503); assert.equal((await response.json()).code, "SOURCE_UNAVAILABLE"); assert.equal(h.calls.length, 1);
});
