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
      if (name === "@/lib/server/request-origin") return { sameOrigin: () => "http://synthetic-api.invalid" };
      if (name === "@/lib/server/candidate-transport") return { candidateTransportOptions: () => ({}) };
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

test("memory endpoints forward only the owner's fixed paths and methods", async () => {
  const h = harness();
  const mode = `v1/categories/${run}/agent-sessions/${session}/memory-mode`;
  const usage = `v1/personal/agent-runs/${run}/memory-usage`;
  const marks = `v1/personal/memory/episodes/${run}/marks`;
  assert.equal((await h.send(mode)).status, 200);
  const change = { expected_revision: 0, request_key: session, memory_off: true };
  assert.equal((await h.send(mode, "POST", "", change)).status, 200);
  assert.deepEqual(JSON.parse(h.calls.at(-1).init.body), change);
  assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/${mode}`);
  assert.equal((await h.send(usage)).status, 200);
  assert.equal((await h.send(marks, "POST", "", { request_key: session, kind: "pin" })).status, 200);
  assert.equal((await h.send("v1/personal/memory-policy")).status, 200);
  const forwarded = h.calls.length;
  assert.equal((await h.send(usage, "POST", "", {})).status, 405);
  assert.equal((await h.send(marks)).status, 405);
  assert.equal((await h.send(mode, "GET", `owner_id=${session}`)).status, 422);
  assert.equal((await h.send(`v1/personal/agent-runs/${run}/memory-usage/extra`)).status, 404);
  assert.equal((await h.send("v1/categories/bad/agent-sessions/x/memory-mode")).status, 404);
  assert.equal(h.calls.length, forwarded);
});
