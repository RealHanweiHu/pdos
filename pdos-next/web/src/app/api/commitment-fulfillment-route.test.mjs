import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { transpileModule, ModuleKind, ScriptTarget } from "typescript";

// Actual BFF handler and origin/transport helpers, with an explicit cookie and
// fetch substitute. No network request or domain authorization is exercised.
const web = resolve(dirname(fileURLToPath(import.meta.url)), "../../..");
const compile = name => transpileModule(readFileSync(resolve(web, name), "utf8"), { compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 } }).outputText;
const route = compile("src/app/api/[...path]/route.ts"), guard = compile("src/lib/request-origin.ts"), transport = compile("src/lib/candidate-transport.ts");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const category = `v1/categories/${id(1)}`, product = `${category}/products/${id(2)}`, root = `${product}/project-work/fulfillment`, inputs = `${root}/inputs`;
function command() { return { category_id: id(1), product_id: id(2), operation: "work.commitment.review", command_id: id(3), idempotency_key: "original-commitment-fulfillment-key", expected_revision: 7, source_read_set: [{ artifact_id: id(5), expected_revision: 1 }], payload: { project_id: id(4), commitment: { id: id(6), revision: 2 }, task: { id: id(7), revision: 5 }, submission: { id: id(8), revision: 4 }, expected_review_revision: 0, decision: "returned", checks: [{ key: "report", decision: "unknown", reason: "实际附件待补" }], sources: [{ id: id(5), revision: 1, kind: "artifact", position: "line:1;quote_sha256:" + "a".repeat(64) }], reason: "本人核对本条承诺" } }; }
function harness({ loggedIn = true, unavailable = false } = {}) {
  const calls = [], originModule = { exports: {} }, transportModule = { exports: {} }, routeModule = { exports: {} };
  runInNewContext(guard, { module: originModule, exports: originModule.exports, URL });
  runInNewContext(transport, { module: transportModule, exports: transportModule.exports, require: () => ({ Agent: class {} }) });
  runInNewContext(route, {
    module: routeModule, exports: routeModule.exports, URL, URLSearchParams, Response, Headers, AbortSignal,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } },
    require: name => {
      if (name === "@/lib/request-origin") return originModule.exports;
      if (name === "@/lib/candidate-transport") return transportModule.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: () => loggedIn ? { value: "synthetic-session-substitute" } : undefined }) };
      throw new Error(`Unexpected dependency: ${name}`);
    },
    fetch: async (url, init) => { calls.push({ url, init }); if (unavailable) throw new Error("synthetic response lost"); return Response.json({ synthetic: true }); },
  });
  return { calls, async send(path = root, { method = "GET", body, raw, origin = "http://localhost:3000" } = {}) {
    const request = new Request(`http://localhost:3000/api/${path}`, { method, headers: { host: "localhost:3000", origin }, ...(raw !== undefined ? { body: raw } : body ? { body: JSON.stringify(body) } : {}) });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return routeModule.exports[method](request, { params: Promise.resolve({ path: path.split("?")[0].split("/") }) });
  } };
}

test("fulfillment GET keeps the exact category/product/project and makes one read", async () => { const h = harness(); const response = await h.send(`${root}?project_id=${id(4)}`); assert.equal(response.status, 200); assert.equal(h.calls.length, 1); assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${root}?project_id=${id(4)}`); assert.equal(h.calls[0].init.method, "GET"); assert.equal(h.calls[0].init.body, undefined); assert.equal(h.calls[0].init.cache, "no-store"); });
test("fulfillment inputs preserves all fixed references, original key and source reads", async () => { const h = harness(), body = command(); assert.equal((await h.send(inputs, { method: "POST", body })).status, 200); assert.equal(h.calls.length, 1); assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${inputs}`); assert.deepEqual(JSON.parse(h.calls[0].init.body), body); assert.equal(h.calls[0].init.headers.Authorization, "Bearer synthetic-session-substitute"); });
test("common preview and explicit execute forward the new operation unchanged once each", async () => { for (const suffix of ["/preview", ""]) { const h = harness(), body = command(); if (!suffix) body.payload.confirmation_token = "actual-common-token-substitute"; assert.equal((await h.send(`${category}/commands${suffix}`, { method: "POST", body })).status, 200); assert.equal(h.calls.length, 1); assert.deepEqual(JSON.parse(h.calls[0].init.body), body); assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${category}/commands${suffix}`); } });
test("GET requires one real project and rejects duplicate, invalid and extra query scope", async () => { for (const query of ["", "?project_id=bad", `?project_id=${id(4)}&project_id=${id(9)}`, `?project_id=${id(4)}&scope=all`]) { const h = harness(); assert.equal((await h.send(root + query)).status, 422, query); assert.equal(h.calls.length, 0); } });
test("input query and wrong read/input verbs stop before any upstream call", async () => { const cases = [[`${inputs}?project_id=${id(4)}`, "POST", command(), 422], [inputs, "GET", undefined, 405], [root, "POST", command(), 405]]; for (const [path, method, body, status] of cases) { const h = harness(); const response = await h.send(path, { method, body }); assert.equal(response.status, status); if (status === 405) assert.equal(response.headers.get("Allow"), method === "GET" ? "POST" : "GET"); assert.equal(h.calls.length, 0); } });
test("wrong category/product envelope and client authority are not forwarded through inputs", async () => { for (const fault of ["category", "product", "actor", "duplicate-read", "json"]) { const h = harness(), body = command(); if (fault === "category") body.category_id = id(9); if (fault === "product") body.product_id = id(9); if (fault === "actor") body.payload.actor_id = id(9); if (fault === "duplicate-read") body.source_read_set.push({ artifact_id: id(5), expected_revision: 2 }); assert.equal((await h.send(inputs, { method: "POST", body, ...(fault === "json" ? { raw: "{" } : {}) })).status, 422, fault); assert.equal(h.calls.length, 0); } });
test("only the new fulfillment input accepts review and old task input retains its operation boundary", async () => { const h = harness(); assert.equal((await h.send(`${product}/project-work/inputs`, { method: "POST", body: command() })).status, 422); const old = command(); old.operation = "work.task.review"; assert.equal((await h.send(inputs, { method: "POST", body: old })).status, 422); assert.equal(h.calls.length, 0); assert.equal((await h.send(`${product}/project-work/inputs`, { method: "POST", body: old })).status, 200); assert.equal(h.calls.length, 1); });
test("invented fulfillment children and missing category cannot reach the upstream service", async () => { for (const path of [`${root}/reviews?project_id=${id(4)}`, `${root}/inputs/execute`, `v1/products/${id(2)}/project-work/fulfillment?project_id=${id(4)}`]) { const h = harness(); assert.equal((await h.send(path)).status, 404); assert.equal(h.calls.length, 0); } });
test("auth and origin remain required and unknown sends are not retried", async () => { const h = harness(); assert.equal((await h.send(inputs, { method: "POST", body: command(), origin: "https://other.invalid" })).status, 403); assert.equal(h.calls.length, 0); const anon = harness({ loggedIn: false }); assert.equal((await anon.send(`${root}?project_id=${id(4)}`)).status, 401); assert.equal(anon.calls.length, 0); const down = harness({ unavailable: true }); const response = await down.send(inputs, { method: "POST", body: command() }); assert.equal(response.status, 503); assert.equal((await response.json()).code, "EXTERNAL_OUTCOME_UNKNOWN"); assert.equal(down.calls.length, 1); });
