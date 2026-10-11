import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const webRoot = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ts = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"))("typescript");
const compiled = file => ts.transpileModule(readFileSync(path.join(webRoot, file), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
}).outputText;
// Execute the actual BFF, origin guard and transport policy; only host IO is replaced.
const routeSource = compiled("src/app/api/[...path]/route.ts");
const originSource = compiled("src/lib/request-origin.ts");
const transportSource = compiled("src/lib/candidate-transport.ts");
const run = "11111111-1111-4111-8111-111111111111";
const call = "22222222-2222-4222-8222-222222222222";
const root = "v1/personal/agent-runs";
function harness(options = {}) {
  const calls = [];
  const origin = { exports: {} }, transport = { exports: {} }, route = { exports: {} };
  runInNewContext(originSource, { module: origin, exports: origin.exports, URL });
  runInNewContext(transportSource, { module: transport, exports: transport.exports,
    require: name => { assert.equal(name, "undici"); return { Agent: class {} }; } });
  runInNewContext(routeSource, { module: route, exports: route.exports, URL, URLSearchParams, Response, Headers,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } },
    AbortSignal: { timeout: () => new AbortController().signal },
    require: name => {
      if (name === "@/lib/request-origin") return origin.exports;
      if (name === "@/lib/candidate-transport") return transport.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: () => ({ value: "synthetic-session" }) }) };
      throw Error(`Unexpected import ${name}`);
    },
    fetch: async (url, init) => { calls.push({ url, init }); return Response.json(options.response ?? { transport_only: true }); },
  });
  return { calls, async send(endpoint, { method = "GET", query = "", body, origin = "http://localhost:3000" } = {}) {
    const headers = new Headers({ host: "localhost:3000", origin });
    const request = new Request(`http://localhost:3000/api/${endpoint}${query ? `?${query}` : ""}`, { method, headers, body });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return route.exports[method === "GET" ? "GET" : "POST"](request, { params: Promise.resolve({ path: endpoint.split("/") }) });
  } };
}

test("personal routes preserve the real unscoped URL, body, credentials and pagination", async () => {
  const h = harness();
  for (const [endpoint, method, query] of [
    [root, "GET", `page_size=50&cursor=${run}`], [root, "POST", ""], [`${root}/${run}`, "GET", ""],
    [`${root}/${run}/events`, "GET", "after=0&page_size=200"], [`${root}/${run}/answers`, "POST", ""],
    [`${root}/${run}/cancel`, "POST", ""], [`${root}/${run}/calls/${call}/recover`, "POST", ""],
  ]) {
    const body = method === "POST" ? JSON.stringify({ goal: "合成输入", idempotency_key: "same-request" }) : undefined;
    const response = await h.send(endpoint, { method, query, body }); assert.equal(response.status, 200);
    const sent = h.calls.at(-1); assert.equal(sent.url, `http://synthetic-api.invalid/${endpoint}${query ? `?${query}` : ""}`);
    assert.equal(sent.init.method, method); assert.equal(sent.init.body, body); assert.equal(sent.init.headers.Authorization, "Bearer synthetic-session");
    assert.equal(sent.init.cache, "no-store"); assert.equal(sent.init.redirect, "error");
  }
});
test("personal UUID, path and method violations cannot reach the backend", async () => {
  const h = harness();
  for (const [endpoint, method] of [
    [`${root}/${"-".repeat(36)}`, "GET"], [`${root}/${run}/calls/${"a".repeat(36)}/recover`, "POST"],
    [`${root}/not-a-run`, "GET"], [`${root}/${run}/events/extra`, "GET"], [`${root}/${run}/model`, "POST"],
    [`${root}/${run}`, "POST"], [`${root}/${run}/events`, "POST"], [`${root}/${run}/answers`, "GET"],
    [`${root}/${run}/cancel`, "GET"], [root, "DELETE"],
  ]) assert.ok([404, 405, 422].includes((await h.send(endpoint, { method })).status), `${method} ${endpoint}`);
  assert.equal(h.calls.length, 0);
});
test("personal pagination rejects extra scope, duplicate keys and noncanonical values", async () => {
  const h = harness();
  for (const query of ["category_id=" + run, "product_id=" + run, "tenant_id=" + run, "page_size=201", "page_size=0", "page_size=-1", "page_size=01", "page_size=1&page_size=2", "cursor=invalid", "after=0"]) {
    assert.equal((await h.send(root, { query })).status, 422, query);
  }
  for (const query of ["cursor=" + run, "after=-1", "after=1.2", "after=9007199254740992", "after=0&after=1", "scope=" + run]) {
    assert.equal((await h.send(`${root}/${run}/events`, { query })).status, 422, query);
  }
  assert.equal((await h.send(`${root}/${run}`, { query: "page_size=1" })).status, 422);
  assert.equal((await h.send(root, { method: "POST", query: "page_size=1", body: "{}" })).status, 422);
  assert.equal(h.calls.length, 0);
});
test("preview and the two exact seed endpoints enforce methods and reject query scope", async () => {
  const h = harness();
  const body = JSON.stringify({ key: "test", name: "测试", purpose: "用途", deidentified_confirmed: true, idempotency_key: "same-preview" });
  assert.equal((await h.send("v1/categories/preview", { method: "POST", body })).status, 200);
  assert.equal(h.calls[0].url, "http://synthetic-api.invalid/v1/categories/preview"); assert.equal(h.calls[0].init.body, body);
  for (const seed of ["auto-tire-inflator", "bicycle-pump"]) {
    assert.equal((await h.send(`v1/category-seeds/${seed}`)).status, 200);
    assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/v1/category-seeds/${seed}`);
    assert.equal((await h.send(`v1/category-seeds/${seed}`, { method: "POST", body: "{}" })).status, 405);
    assert.equal((await h.send(`v1/category-seeds/${seed}`, { query: `category_id=${run}` })).status, 422);
  }
  assert.equal((await h.send("v1/categories/preview")).status, 405);
  assert.equal((await h.send("v1/categories/preview", { method: "POST", body, query: `category_id=${run}` })).status, 422);
  assert.equal((await h.send("v1/category-seeds/unknown")).status, 404);
  assert.equal((await h.send("v1/categories/preview", { method: "POST", body, origin: "https://foreign.invalid" })).status, 403);
  assert.equal(h.calls.length, 3);
});
test("committed category receipt passes through even when continuation awaits delivery", async () => {
  const receipt = { subject_id: run, id: call, continuation_state: "awaiting_delivery" };
  const h = harness({ response: receipt });
  const response = await h.send("v1/categories", { method: "POST", body: "{}" });
  assert.equal(response.status, 200); assert.deepEqual(await response.json(), receipt); assert.equal(h.calls.length, 1);
});
