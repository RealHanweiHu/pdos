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
const session = "11111111-1111-4111-8111-111111111111", run = "22222222-2222-4222-8222-222222222222";
function harness(options = {}) {
  const loaded = { exports: {} }, calls = [];
  runInNewContext(compile("app/api/[...path]/route.ts"), {
    module: loaded, exports: loaded.exports, URLSearchParams, Response, AbortSignal, Request, Headers,
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    require: name => {
      if (name === "next/headers") return { cookies: async () => ({ get: key => { assert.equal(key, "pdos-next-session"); return options.session === false ? undefined : { value: "synthetic-session" }; } }) };
      if (name === "@/lib/request-origin") return { sameOrigin: () => "http://synthetic-api.invalid" };
      if (name === "@/lib/candidate-transport") return { candidateTransportOptions: () => ({}) };
      if (name === "next/server") return { NextRequest: class {} };
      throw new Error(`unexpected module ${name}`);
    },
    fetch: async (url, init) => { calls.push({ url, init }); return Response.json(options.body ?? { items: [] }, { status: options.status ?? 200 }); },
  });
  return { calls, async send(pathname, method = "GET", query = "", body) {
    const request = new Request(`http://localhost/api/${pathname}${query ? `?${query}` : ""}`, { method, body: body === undefined ? undefined : JSON.stringify(body), headers: { "Content-Type": "application/json" } });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    const forward = method === "GET" ? loaded.exports.GET : loaded.exports.POST;
    return forward(request, { params: Promise.resolve({ path: pathname.split("/") }) });
  } };
}
const workPath = "v1/personal/work-products";

test("work-product list and detail reads preserve the exact session and method", async () => {
  const h = harness();
  for (const [path, expected] of [[`${workPath}?session_id=${session}`, `${workPath}?session_id=${session}`], [`${workPath}/${run}`, `${workPath}/${run}`]]) {
    const [pathname, query] = path.split("?");
    const response = await h.send(pathname, "GET", query);
    assert.equal(response.status, 200);
    const { url, init } = h.calls.at(-1);
    assert.equal(url, `http://synthetic-api.invalid/${expected}`);
    assert.equal(init.method, "GET"); assert.equal(init.body, undefined); assert.equal(init.cache, "no-store");
  }
  assert.equal(h.calls.length, 2);
});

test("from-run and revisions use POST without a query and preserve the body", async () => {
  const h = harness();
  for (const [path, body] of [[`${workPath}/from-run`, { run_id: run, kind: "document", request_key: session }], [`${workPath}/${run}/revisions`, { expected_revision: 2, title: "人工", body: "正文", request_key: session }]]) {
    const response = await h.send(path, "POST", "", body);
    assert.equal(response.status, 200);
    const { url, init } = h.calls.at(-1);
    assert.equal(url, `http://synthetic-api.invalid/${path}`); assert.equal(init.method, "POST");
    assert.deepEqual(JSON.parse(init.body), body);
  }
  assert.equal(h.calls.length, 2);
});

test("invalid queries and methods fail before any upstream call", async () => {
  const h = harness();
  for (const query of ["session_id=bad", `session_id=${session}&session_id=${session}`, "tenant_id=other"]) {
    const response = await h.send(workPath, "GET", query);
    assert.equal(response.status, 422, query);
  }
  for (const method of ["PUT", "PATCH", "DELETE"]) {
    const response = await h.send(workPath, method);
    assert.equal(response.status, 405); assert.equal(response.headers.get("Allow"), "GET");
  }
  for (const method of ["POST", "PUT", "PATCH", "DELETE"]) {
    const response = await h.send(`${workPath}/${run}`, method);
    assert.equal(response.status, 405); assert.equal(response.headers.get("Allow"), "GET");
  }
  assert.equal(h.calls.length, 0);
});

test("missing identity or configuration fails closed", async () => {
  for (const [options, status] of [[{ session: false }, 401], [{ configured: false }, 503]]) {
    const h = harness(options); assert.equal((await h.send(workPath)).status, status); assert.equal(h.calls.length, 0);
  }
});
