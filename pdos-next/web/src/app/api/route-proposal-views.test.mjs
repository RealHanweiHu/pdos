import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ts = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"))("typescript");
const compiled = file => ts.transpileModule(readFileSync(file, "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
}).outputText;
// Test-only source selection. The production BFF does not read this override.
const routeSource = compiled(process.env.PDOS_PROPOSAL_VIEWS_BFF_SOURCE ?? path.join(webRoot, "src/app/api/[...path]/route.ts"));
const originSource = compiled(path.join(webRoot, "src/lib/request-origin.ts"));
const transportSource = compiled(path.join(webRoot, "src/lib/candidate-transport.ts"));
const category = "11111111-1111-4111-8111-111111111111";
const proposal = "22222222-2222-4222-8222-222222222222";
const parameter = "33333333-3333-4333-8333-333333333333";
const otherParameter = "AAAAAAAA-AAAA-4AAA-8AAA-AAAAAAAAAAAA";
const root = `v1/categories/${category}`;
const views = ["positioning", "spec-benchmark", "feature-config", "definition-maturity"];
function harness(options = {}) {
  const calls = [];
  const origin = { exports: {} }, transport = { exports: {} }, route = { exports: {} };
  runInNewContext(originSource, { module: origin, exports: origin.exports, URL });
  runInNewContext(transportSource, { module: transport, exports: transport.exports,
    require: name => { assert.equal(name, "undici"); return { Agent: class {} }; } });
  runInNewContext(routeSource, { module: route, exports: route.exports, URL, URLSearchParams, Response, Headers,
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    AbortSignal: { timeout: () => new AbortController().signal },
    require: name => {
      if (name === "@/lib/request-origin") return origin.exports;
      if (name === "@/lib/candidate-transport") return transport.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: () => options.session === false ? undefined : { value: "synthetic-session" } }) };
      throw Error(`Unexpected import ${name}`);
    },
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (options.transportFailure) throw Error("Synthetic connection failure");
      return Response.json(options.response ?? { transport_only: true }, { status: options.status ?? 200 });
    },
  });
  return { calls, async send(endpoint, { method = "GET", query = "", body, origin = "http://localhost:3000" } = {}) {
    const request = new Request(`http://localhost:3000/api/${endpoint}${query ? `?${query}` : ""}`, { method, headers: { host: "localhost:3000", origin }, body });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return route.exports[method === "GET" ? "GET" : "POST"](request, { params: Promise.resolve({ path: endpoint.split("/") }) });
  } };
}

for (const view of views) test(`${view} forwards the exact scoped GET and every parameter occurrence`, async () => {
  const envelope = { view, proposal_id: proposal, revision: 2, document_mode: "frozen", document_digest: "actual-digest", submission_id: "actual-submission", data: { untouched: true } };
  const h = harness({ response: envelope });
  const query = `parameter_ids=${parameter}&proposal_id=${proposal}&parameter_ids=${otherParameter}&parameter_ids=${parameter}`;
  const result = await h.send(`${root}/views/${view}`, { query });
  assert.equal(result.status, 200); assert.deepEqual(await result.json(), envelope);
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${root}/views/${view}?${query}`);
  assert.equal(h.calls[0].init.method, "GET"); assert.equal(h.calls[0].init.body, undefined);
  assert.equal(h.calls[0].init.headers.Authorization, "Bearer synthetic-session");
  assert.equal(h.calls[0].init.cache, "no-store"); assert.equal(h.calls[0].init.redirect, "error");
  assert.equal(result.headers.get("Cache-Control"), "no-store");
});

test("parameter filters are optional but a single valid proposal id is mandatory for every view", async () => {
  const h = harness();
  for (const view of views) {
    const endpoint = `${root}/views/${view}`;
    assert.equal((await h.send(endpoint, { query: `proposal_id=${proposal}` })).status, 200);
    for (const query of ["", `parameter_ids=${parameter}`, "proposal_id=", "proposal_id=invalid", `proposal_id=${"a".repeat(36)}`, `proposal_id=${proposal}&proposal_id=${proposal}`, `proposal_id=${proposal}&proposal_id=${parameter}`]) {
      assert.equal((await h.send(endpoint, { query })).status, 422, `${view}: ${query}`);
    }
  }
  assert.equal(h.calls.length, 4);
});

test("each repeated parameter is validated and extra scope or query keys are rejected", async () => {
  const h = harness();
  for (const suffix of [
    "parameter_ids=", "parameter_ids=invalid", `parameter_ids=${"-".repeat(36)}`,
    `parameter_ids=${parameter}&parameter_ids=invalid`, `parameter_ids=${parameter},${otherParameter}`,
    `parameter_ids[]=${parameter}`, `parameter_id=${parameter}`, `category_id=${category}`, `tenant_id=${category}`,
    `product_id=${parameter}`, `run_id=${parameter}`, "page_size=10", `cursor=${parameter}`, "include_history=true", "view=positioning",
  ]) assert.equal((await h.send(`${root}/views/spec-benchmark`, { query: `proposal_id=${proposal}&${suffix}` })).status, 422, suffix);
  assert.equal(h.calls.length, 0);
});

test("only the four exact scoped paths are opened", async () => {
  const h = harness();
  for (const endpoint of [
    `${root}/views/unknown`, `${root}/views/Positioning`, `${root}/views/DEFINITION-MATURITY`, `${root}/views/positioning/extra`,
    `${root}/views/positioning/`, `${root}/views`, `v1/views/positioning`, `v1/categories/invalid/views/positioning`,
    `${root}/products/${parameter}/views/positioning`, `${root}/views/spec-benchmark/apply`,
  ]) assert.equal((await h.send(endpoint, { query: `proposal_id=${proposal}` })).status, 404, endpoint);
  assert.equal(h.calls.length, 0);
});

test("views reject writes and other methods without forwarding", async () => {
  const h = harness();
  for (const view of views) for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    const result = await h.send(`${root}/views/${view}`, { method, query: `proposal_id=${proposal}`, body: "{}" });
    assert.equal(result.status, 405, `${method} ${view}`);
    assert.equal(result.headers.get("Allow"), "GET");
  }
  assert.equal(h.calls.length, 0);
});

test("existing proposal collection, document, items and participants reads preserve their URLs", async () => {
  const h = harness();
  for (const [endpoint, query] of [
    [`${root}/proposals`, `page_size=20&cursor=${proposal}`], [`${root}/proposals/${proposal}`, ""],
    [`${root}/proposals/${proposal}/items`, "include_history=true"], [`${root}/proposals/${proposal}/participants`, ""],
  ]) {
    assert.equal((await h.send(endpoint, { query })).status, 200);
    assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/${endpoint}${query ? `?${query}` : ""}`);
    assert.equal((await h.send(endpoint, { method: "POST", body: "{}" })).status, 405);
  }
  assert.equal((await h.send(`${root}/proposals`, { query: `parameter_ids=${parameter}` })).status, 422);
  assert.equal((await h.send(`${root}/proposals`, { query: "page_size=10&page_size=20" })).status, 422);
  assert.equal(h.calls.length, 4);
});

test("session and configuration requirements still guard the new reads", async () => {
  for (const [options, status] of [[{ session: false }, 401], [{ configured: false }, 503]]) {
    const h = harness(options);
    assert.equal((await h.send(`${root}/views/positioning`, { query: `proposal_id=${proposal}` })).status, status);
    assert.equal(h.calls.length, 0);
  }
});

test("backend denial and read transport failure never become a successful view", async () => {
  const denial = { code: "FORBIDDEN_SCOPE", message: "Synthetic denied source" };
  const h = harness({ response: denial, status: 403 });
  const response = await h.send(`${root}/views/feature-config`, { query: `proposal_id=${proposal}` });
  assert.equal(response.status, 403); assert.deepEqual(await response.json(), denial);
  const unavailable = harness({ transportFailure: true });
  const failed = await unavailable.send(`${root}/views/spec-benchmark`, { query: `proposal_id=${proposal}` });
  assert.equal(failed.status, 503); assert.equal((await failed.json()).code, "SOURCE_UNAVAILABLE");
  assert.equal(unavailable.calls.length, 1);
});

test("existing command body and same-origin write protection remain unchanged", async () => {
  const h = harness();
  const body = JSON.stringify({ operation: "proposal.item.patch", idempotency_key: "synthetic-original-key" });
  assert.equal((await h.send(`${root}/commands`, { method: "POST", body })).status, 200);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${root}/commands`);
  assert.equal(h.calls[0].init.body, body);
  assert.equal((await h.send(`${root}/commands`, { method: "POST", body, origin: "https://foreign.invalid" })).status, 403);
  assert.equal(h.calls.length, 1);
});
