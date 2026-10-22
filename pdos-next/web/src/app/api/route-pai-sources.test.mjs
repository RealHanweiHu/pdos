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
const id = n => `00000000-0000-0000-0000-${n.toString(16).padStart(12, "0")}`;
const category = id(1), run = id(2), product = id(3), proposal = id(4), cursor = id(5);
function harness(options = {}) {
  const loaded = { exports: {} }, calls = [];
  runInNewContext(compile("lib/pai-sources-proxy.ts"), {
    module: loaded, exports: loaded.exports, URLSearchParams, Response, AbortSignal,
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    require: name => { assert.equal(name, "next/headers"); return { cookies: async () => ({ get: key => { assert.equal(key, "pdos-next-session"); return options.session === false ? undefined : { value: "synthetic-session" }; } }) }; },
    fetch: async (url, init) => { calls.push({ url, init }); if (options.failure) throw Error("synthetic failure"); return Response.json(options.body ?? { exact: "metadata" }, { status: options.status ?? 200 }); },
  });
  return { calls, send(query = "", categoryId = category, runId, method = "GET") {
    const request = new Request(`http://localhost/api/sources${query ? `?${query}` : ""}`, { method });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return loaded.exports.paiSourcesRead(request, categoryId, runId);
  } };
}
test("catalog forwards only exact category/Product/proposal/cursor parameters as a private GET", async () => {
  const h = harness(), query = new URLSearchParams({ page_size: "20", product_id: product, proposal_id: proposal, cursor }).toString();
  const response = await h.send(query);
  assert.equal(response.status, 200); assert.equal(response.headers.get("Cache-Control"), "private, no-store");
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-input-sources?${query}`);
  assert.equal(h.calls[0].init.method, "GET"); assert.equal(h.calls[0].init.body, undefined);
  assert.equal(h.calls[0].init.cache, "no-store"); assert.equal(h.calls[0].init.redirect, "error");
  assert.equal(h.calls[0].init.headers.Authorization, "Bearer synthetic-session");
});
test("actual Run bindings use the exact Run and accept no query at all", async () => {
  const h = harness(); assert.equal((await h.send("", category, run)).status, 200);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-runs/${run}/source-bindings`);
  for (const query of [`product_id=${product}`, `proposal_id=${proposal}`, "page_size=1", `cursor=${cursor}`, "q=private"]) assert.equal((await h.send(query, category, run)).status, 422);
  assert.equal(h.calls.length, 1);
});
test("unrecognized, repeated or malformed list parameters fail before network access", async () => {
  const h = harness();
  for (const query of ["page_size=0", "page_size=51", "page_size=01", "page_size=1.5", "page_size=1&page_size=2", "product_id=bad", `product_id=${product}&product_id=${product}`, "proposal_id=bad", "cursor=bad", "category_id=other", "principal_id=other", "tenant_id=other", "artifact_id=other", "q=private", "include_content=true"]) assert.equal((await h.send(query)).status, 422, query);
  assert.equal(h.calls.length, 0);
});
test("invalid path identities and mutation methods cannot reach upstream", async () => {
  const h = harness(); assert.equal((await h.send("", "bad")).status, 404); assert.equal((await h.send("", category, "bad")).status, 404);
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) { const response = await h.send("", category, run, method); assert.equal(response.status, 405); assert.equal(response.headers.get("Allow"), "GET"); }
  assert.equal(h.calls.length, 0);
});
test("missing session/configuration never creates a fallback read", async () => {
  for (const [options, status] of [[{ session: false }, 401], [{ configured: false }, 503]]) { const h = harness(options); assert.equal((await h.send()).status, status); assert.equal(h.calls.length, 0); }
});
test("domain failures are preserved and unavailable transport is not retried", async () => {
  for (const status of [403, 404, 409, 422, 503]) {
    const body = { code: "SOURCE_UNAVAILABLE", message: "真实领域失败", detail: { reason: "fixed_source_unavailable" } }, h = harness({ status, body });
    const response = await h.send(); assert.equal(response.status, status); assert.deepEqual(await response.json(), body); assert.equal(h.calls.length, 1);
  }
  const h = harness({ failure: true }); const response = await h.send(); assert.equal(response.status, 503); assert.equal((await response.json()).code, "SOURCE_UNAVAILABLE"); assert.equal(h.calls.length, 1);
});
test("both static modules export only GET and await exact route parameters", async () => {
  for (const [relative, params, args] of [
    ["app/api/v1/categories/[categoryId]/agent-input-sources/route.ts", { categoryId: category }, [category]],
    ["app/api/v1/categories/[categoryId]/agent-runs/[runId]/source-bindings/route.ts", { categoryId: category, runId: run }, [category, run]],
  ]) {
    const loaded = { exports: {} }, calls = [], request = {};
    runInNewContext(compile(relative), { module: loaded, exports: loaded.exports, require: name => { assert.equal(name, "@/lib/pai-sources-proxy"); return { paiSourcesRead: (...values) => calls.push(values) }; } });
    assert.deepEqual(Object.keys(loaded.exports), ["GET"]); await loaded.exports.GET(request, { params: Promise.resolve(params) });
    assert.equal(calls[0][0], request); assert.deepEqual([...calls[0].slice(1)], args);
  }
});
