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
const workPath = `v1/personal/agent-sessions/${session}/work-state`;

test("work-state reads and explicit human edits preserve scoped endpoints", async () => {
  const h = harness();
  for (const resource of [workPath, `v1/categories/${run}/agent-sessions/${session}/work-state`]) {
    assert.equal((await h.send(resource)).status, 200);
    assert.equal(h.calls.at(-1).init.method, "GET");
    assert.equal(h.calls.at(-1).init.body, undefined);
    const body = { expected_revision: 3, request_key: session, action: "remove_constraint", item_id: run };
    assert.equal((await h.send(resource, "POST", "", body)).status, 200);
    assert.deepEqual(JSON.parse(h.calls.at(-1).init.body), body);
    assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/${resource}`);
  }
});

test("work state rejects extra scope and non-supported methods before forwarding", async () => {
  const h = harness();
  assert.equal((await h.send(workPath, "GET", "tenant_id=other")).status, 422);
  assert.equal((await h.send(workPath, "POST", `requester_id=${session}`, {})).status, 422);
  assert.equal((await h.send(workPath, "PATCH")).status, 405);
  assert.equal((await h.send("v1/personal/agent-sessions/bad/work-state")).status, 404);
  assert.equal(h.calls.length, 0);
});
