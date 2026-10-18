import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { transpileModule, ModuleKind, ScriptTarget } from "typescript";
const compile = name => transpileModule(readFileSync(resolve(name), "utf8"), { compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 } }).outputText;
const route = compile("src/app/api/[...path]/route.ts"), guard = compile("src/lib/request-origin.ts"), transport = compile("src/lib/candidate-transport.ts");
const root = "v1/personal/project-work";
const cursor = "00000000-0000-4000-8000-000000000001";
function harness({ loggedIn = true, unavailable = false } = {}) {
  const calls = [], originModule = { exports: {} }, transportModule = { exports: {} }, routeModule = { exports: {} };
  runInNewContext(guard, { module: originModule, exports: originModule.exports, URL });
  runInNewContext(transport, { module: transportModule, exports: transportModule.exports, require: () => ({ Agent: class {} }) });
  runInNewContext(route, {
    module: routeModule, exports: routeModule.exports, URL, URLSearchParams, Response, Headers,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } }, AbortSignal,
    require: name => {
      if (name === "@/lib/request-origin") return originModule.exports;
      if (name === "@/lib/candidate-transport") return transportModule.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: () => loggedIn ? { value: "synthetic-session-substitute" } : undefined }) };
      throw new Error(`Unexpected dependency: ${name}`);
    },
    fetch: async (url, init) => { calls.push({ url, init }); if (unavailable) throw new Error("synthetic transport lost"); return Response.json({ synthetic: true }); },
  });
  return { calls, async send(path = root, { method = "GET", body, raw, origin = "http://localhost:3000" } = {}) {
    const request = new Request(`http://localhost:3000/api/${path}`, { method, headers: { host: "localhost:3000", origin }, ...(raw !== undefined ? { body: raw } : body ? { body: JSON.stringify(body) } : {}) });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return routeModule.exports[method](request, { params: Promise.resolve({ path: path.split("?")[0].split("/") }) });
  } };
}
for (const queue of ["receive", "verify", "tasks", "commitments"]) test(`personal ${queue} forwards only exact authenticated GET`, async () => {
  const h = harness(), response = await h.send(`${root}?queue=${queue}&page_size=1&cursor=${cursor}`);
  assert.equal(response.status, 200); assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${root}?queue=${queue}&page_size=1&cursor=${cursor}`);
  assert.equal(h.calls[0].init.method, "GET"); assert.equal(h.calls[0].init.body, undefined);
  assert.equal(h.calls[0].init.cache, "no-store");
});
test("invalid personal queue, duplicate and alternate scopes never reach backend", async () => {
  const h = harness();
  for (const query of ["", "queue=all", "queue=receive&queue=verify", "queue=tasks&actor_id=other", "queue=tasks&category_id=other", "queue=tasks&page_size=0", "queue=tasks&page_size=101", "queue=tasks&page_size=01", "queue=tasks&cursor=bad", `queue=tasks&cursor=${cursor}&cursor=${cursor}`]) assert.equal((await h.send(`${root}?${query}`)).status, 422, query);
  assert.equal(h.calls.length, 0);
});
test("personal queue does not accept commands or category override", async () => {
  const h = harness(); assert.equal((await h.send(`${root}?queue=tasks`, { method: "POST", body: { operation: "work.task.start" } })).status, 405);
  assert.equal(h.calls.length, 0);
});
test("anonymous and failed personal reads remain unavailable without retry", async () => {
  const anon = harness({ loggedIn: false }); assert.equal((await anon.send(`${root}?queue=tasks`)).status, 401); assert.equal(anon.calls.length, 0);
  const down = harness({ unavailable: true }); assert.equal((await down.send(`${root}?queue=tasks`)).status, 503); assert.equal(down.calls.length, 1);
});
