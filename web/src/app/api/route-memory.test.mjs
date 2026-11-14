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

test("session deletion forwards the owner's preview and delete, nothing else", async () => {
  const h = harness();
  const personal = `v1/personal/agent-sessions/${session}/deletion`;
  const scoped = `v1/categories/${run}/agent-sessions/${session}/deletion`;
  for (const target of [personal, scoped]) {
    assert.equal((await h.send(target)).status, 200);
    assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/${target}`);
    assert.equal((await h.send(target, "POST", "", { request_key: session })).status, 200);
    assert.deepEqual(JSON.parse(h.calls.at(-1).init.body), { request_key: session });
  }
  const forwarded = h.calls.length;
  assert.equal((await h.send(personal, "GET", `owner_id=${session}`)).status, 422);
  assert.equal((await h.send(`${personal}/extra`)).status, 404);
  assert.equal((await h.send("v1/personal/agent-sessions/x/deletion")).status, 404);
  // D301: scope options take only the kind and an optional search word.
  assert.equal((await h.send("v1/personal/memory/scope-options", "GET", "kind=product&query=气泵")).status, 200);
  assert.equal(new URL(h.calls.at(-1).url).searchParams.get("kind"), "product");
  const options = h.calls.length;
  assert.equal((await h.send("v1/personal/memory/scope-options")).status, 422);
  assert.equal((await h.send("v1/personal/memory/scope-options", "GET", "kind=category")).status, 422);
  assert.equal((await h.send("v1/personal/memory/scope-options", "GET", `kind=proposal&owner_id=${session}`)).status, 422);
  assert.equal((await h.send("v1/personal/memory/scope-options", "POST", "kind=product", {})).status, 405);
  assert.equal(h.calls.length, options);
  // A note's deletion stays POST only.
  assert.equal((await h.send(`v1/personal/memory/notes/${session}/deletion`)).status, 405);
  assert.equal(h.calls.length, forwarded + 1); // Only the one valid scope-options read went out.
});

test("M2a note, candidate and setting paths forward with fixed methods only", async () => {
  const h = harness();
  const note = "33333333-3333-4333-8333-333333333333";
  const gets = ["v1/personal/memory/notes", `v1/personal/memory/notes/${note}/history`, "v1/personal/memory/candidates", "v1/personal/memory/settings", "v1/personal/memory-policy/statistics", `v1/categories/${run}/agent-runs/${run}/memory-candidates`, `v1/personal/agent-runs/${run}/memory-candidates`];
  for (const item of gets) assert.equal((await h.send(item)).status, 200, item);
  const posts = ["v1/personal/memory/notes", "v1/personal/memory/notes/conflicts", `v1/personal/memory/notes/${note}/revisions`, `v1/personal/memory/notes/${note}/deletion`, `v1/personal/memory/candidates/${note}/decision`, "v1/personal/memory/settings"];
  for (const item of posts) assert.equal((await h.send(item, "POST", "", { request_key: session })).status, 200, item);
  assert.equal(h.calls.at(-1).url, "http://synthetic-api.invalid/v1/personal/memory/settings");
  const forwarded = h.calls.length;
  for (const item of [`v1/personal/memory/notes/${note}/deletion`, "v1/personal/memory/notes/conflicts", `v1/personal/memory/candidates/${note}/decision`]) assert.equal((await h.send(item)).status, 405, item);
  for (const item of ["v1/personal/memory/candidates", `v1/personal/memory/notes/${note}/history`, "v1/personal/memory-policy/statistics", `v1/personal/agent-runs/${run}/memory-candidates`]) assert.equal((await h.send(item, "POST", "", {})).status, 405, item);
  assert.equal((await h.send("v1/personal/memory/notes", "GET", `owner_id=${session}`)).status, 422);
  assert.equal((await h.send("v1/personal/memory/notes/not-a-uuid/history")).status, 404);
  assert.equal((await h.send(`v1/categories/${run}/memory/notes`)).status, 404);
  assert.equal(h.calls.length, forwarded);
});
