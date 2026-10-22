import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ts = createRequire(path.join(web, "package.json"))("typescript");
const compile = file => ts.transpileModule(readFileSync(path.join(web, "src", file), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const matrix = { exports: {} };
runInNewContext(compile("lib/category-matrix.ts"), { module: matrix, exports: matrix.exports, URLSearchParams });
const category = "11111111-1111-4111-8111-111111111111", proposal = "22222222-2222-4222-8222-222222222222";
function harness(options = {}) {
  const helper = { exports: {} }, calls = [];
  runInNewContext(compile("lib/category-research-proxy.ts"), {
    module: helper, exports: helper.exports, Response, URLSearchParams, AbortSignal,
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    require: name => {
      if (name === "@/lib/category-matrix") return matrix.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: () => options.session === false ? undefined : { value: "synthetic-session" } }) };
      throw new Error(`Unexpected import ${name}`);
    },
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (options.failure) throw new Error("synthetic transport failure");
      return Response.json(options.body ?? { unchanged: true }, { status: options.status ?? 200 });
    },
  });
  const routes = Object.fromEntries(["category-matrix", "voices"].map(kind => {
    const routeModule = { exports: {} };
    const file = kind === "voices" ? "app/api/v1/categories/[categoryId]/proposals/[proposalId]/voices/route.ts" : "app/api/v1/categories/[categoryId]/category-matrix/route.ts";
    runInNewContext(compile(file), { module: routeModule, exports: routeModule.exports, require: name => { assert.equal(name, "@/lib/category-research-proxy"); return helper.exports; } });
    return [kind, routeModule.exports];
  }));
  return { calls, async send(kind, query = "", ids = {}, method = "GET") {
    const request = new Request(`http://localhost:3000/api/v1/categories/${category}/${kind}?${query}`, { method });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return routes[kind].GET(request, { params: Promise.resolve({ categoryId: category, ...(kind === "voices" ? { proposalId: proposal } : {}), ...ids }) });
  }, routes };
}

test("both static routes forward exact scoped authenticated GETs without caching or body changes", async () => {
  const h = harness({ body: { exact: "150.000000000001", document: { revision: 7 } } });
  for (const kind of ["category-matrix", "voices"]) {
    const query = kind === "category-matrix" ? "price_breaks=150.000000000001&price_breaks=300" : "";
    const response = await h.send(kind, query);
    assert.equal(response.status, 200); assert.equal(response.headers.get("Cache-Control"), "no-store");
    assert.deepEqual(await response.json(), { exact: "150.000000000001", document: { revision: 7 } });
    const call = h.calls.at(-1), suffix = kind === "voices" ? `proposals/${proposal}/voices` : kind;
    assert.equal(call.url, `http://synthetic-api.invalid/v1/categories/${category}/${suffix}${query ? `?${query}` : ""}`);
    assert.equal(call.init.method, "GET"); assert.equal(call.init.headers.Authorization, "Bearer synthetic-session");
    assert.equal(call.init.cache, "no-store"); assert.equal(call.init.redirect, "error"); assert.equal(call.init.body, undefined);
    assert.deepEqual(Object.keys(h.routes[kind]), ["GET"]);
  }
});
test("matrix defaults pass through and malformed or alternate-scope queries never reach the API", async () => {
  const h = harness(); assert.equal((await h.send("category-matrix")).status, 200);
  for (const query of ["price_breaks=", "price_breaks=150&price_breaks=150", "price_breaks=300&price_breaks=150", "price_breaks=-1", "price_breaks=NaN", "price_breaks=1,2", "price_breaks=1%202", "price_breaks=0", Array.from({ length: 11 }, (_, i) => `price_breaks=${i + 1}`).join("&"), "tenant_id=other", "category_id=other"]) assert.equal((await h.send("category-matrix", query)).status, 422, query);
  assert.equal(h.calls.length, 1);
});
test("voices reject alternate identity, document overrides, pagination and malformed IDs", async () => {
  const h = harness();
  for (const query of [`proposal_id=${proposal}`, "include_history=true", "page_size=1", "document_mode=frozen", "tenant_id=other"]) assert.equal((await h.send("voices", query)).status, 422);
  for (const ids of [{ categoryId: "bad" }, { proposalId: "../other" }]) assert.equal((await h.send("voices", "", ids)).status, 404);
  for (const kind of ["category-matrix", "voices"]) assert.equal((await h.send(kind, "", {}, "POST")).status, 405);
  assert.equal(h.calls.length, 0);
});
test("missing session or server configuration fails closed before forwarding", async () => {
  for (const [options, status] of [[{ session: false }, 401], [{ configured: false }, 503]]) {
    const h = harness(options); assert.equal((await h.send("voices")).status, status); assert.equal(h.calls.length, 0);
  }
});
test("domain refusals and read transport failures stay read failures without retries", async () => {
  for (const status of [403, 404, 409]) {
    const body = { code: "SOURCE_UNAVAILABLE", detail: { reason: "fixed_source_unreadable" } }, h = harness({ status, body });
    const response = await h.send("voices"); assert.equal(response.status, status); assert.deepEqual(await response.json(), body); assert.equal(h.calls.length, 1);
  }
  const h = harness({ failure: true }), response = await h.send("category-matrix");
  assert.equal(response.status, 503); assert.equal((await response.json()).code, "SOURCE_UNAVAILABLE"); assert.equal(h.calls.length, 1);
});
