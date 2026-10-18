import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { transpileModule, ModuleKind, ScriptTarget } from "typescript";

const compile = name => transpileModule(readFileSync(resolve(name), "utf8"), { compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 } }).outputText;
const route = compile("src/app/api/[...path]/route.ts"), guard = compile("src/lib/request-origin.ts"), transport = compile("src/lib/candidate-transport.ts");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const root = `v1/categories/${id(1)}/automation-rules`;
const detail = root + '/' + id(2), trigger = detail + '/trigger';
const original = { expected_rule_revision: 2, version_id: id(3), idempotency_key: 'original-manual-trigger' };

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


test("only exact category rule reads are forwarded", async () => {
  const h = harness();
  assert.equal((await h.send(root)).status, 200);
  assert.equal((await h.send(detail)).status, 200);
  assert.equal(h.calls.length, 2);
  assert.equal((await h.send(root + '?owner_id=' + id(5))).status, 422);
  assert.equal((await h.send(detail + '/history')).status, 404);
  assert.equal((await h.send(root, { method: 'POST', body: original })).status, 405);
  assert.equal(h.calls.length, 2);
});
test("manual trigger keeps original bytes and performs one transport attempt", async () => {
  const h = harness();
  assert.equal((await h.send(trigger, { method: 'POST', body: original })).status, 200);
  assert.deepEqual(JSON.parse(h.calls[0].init.body), original);
  const down = harness({ unavailable: true });
  const response = await down.send(trigger, { method: 'POST', body: original });
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, 'EXTERNAL_OUTCOME_UNKNOWN');
  assert.equal(down.calls.length, 1);
});
for (const fault of ['extra-authority', 'version', 'revision', 'empty-key', 'long-key', 'json']) test('manual trigger rejects ' + fault, async () => {
  const h = harness(), body = { ...original };
  if (fault === 'extra-authority') body.owner_id = id(8);
  if (fault === 'version') body.version_id = 'not-a-version';
  if (fault === 'revision') body.expected_rule_revision = 0;
  if (fault === 'empty-key') body.idempotency_key = '        ';
  if (fault === 'long-key') body.idempotency_key = 'a'.repeat(121);
  assert.equal((await h.send(trigger, { method: 'POST', body, ...(fault === 'json' ? { raw: '{' } : {}) })).status, 422);
  assert.equal(h.calls.length, 0);
});
test("manual rule authorization and origin guards precede forwarding", async () => {
  const anon = harness({ loggedIn: false });
  assert.equal((await anon.send(root)).status, 401);
  const h = harness();
  assert.equal((await h.send(trigger, { method: 'POST', body: original, origin: 'https://other.invalid' })).status, 403);
  assert.equal(h.calls.length, 0);
});
