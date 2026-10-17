import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { transpileModule, ModuleKind, ScriptTarget } from "typescript";

const compile = name => transpileModule(readFileSync(resolve(name), "utf8"), { compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 } }).outputText;
const route = compile("src/app/api/[...path]/route.ts"), guard = compile("src/lib/request-origin.ts"), transport = compile("src/lib/candidate-transport.ts");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const root = `v1/categories/${id(1)}/products/${id(2)}/pilots`;
const command = operation => ({ category_id: id(1), product_id: id(2), operation, command_id: id(3), idempotency_key: "original-pilot-key", expected_revision: 5, source_read_set: [], payload: operation === "npi.pilot.create" ? { project_id: id(5), details: {} } : { pilot_id: id(6), expected_pilot_revision: 1, record: {} } });
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

test("Pilot project history and a fixed root are read-only exact routes", async () => {
  const h = harness();
  assert.equal((await h.send(`${root}?project_id=${id(5)}&history_cursor=${id(6)}`)).status, 200);
  assert.equal((await h.send(`${root}/${id(6)}`)).status, 200);
  assert.ok(h.calls.every(c => c.init.method === "GET" && c.init.body === undefined));
});
for (const path of [root, `${root}?project_id=${id(5)}&project_id=${id(6)}`, `${root}/${id(6)}?revision=1`, `${root}/inputs?project_id=${id(5)}`])
  test(`ambiguous or invented Pilot scope is rejected: ${path}`, async () => {
    const h = harness(); assert.ok([405, 422].includes((await h.send(path)).status)); assert.equal(h.calls.length, 0);
  });
for (const operation of ["npi.pilot.create", "npi.pilot.result.record"])
  test(`${operation} inputs preserve original key and unresolved reads for the actual owner`, async () => {
    const h = harness(), body = command(operation);
    assert.equal((await h.send(`${root}/inputs`, { method: "POST", body })).status, 200);
    assert.equal(h.calls.length, 1); assert.deepEqual(JSON.parse(h.calls[0].init.body), body);
  });
for (const fault of ["product", "operation", "reads", "revision", "malformed"])
  test(`Pilot inputs reject ${fault} before forwarding`, async () => {
    const h = harness(), body = command("npi.pilot.result.record");
    if (fault === "product") body.product_id = id(20);
    if (fault === "operation") body.operation = "build.start";
    if (fault === "reads") body.source_read_set = [{ artifact_id: id(8), expected_revision: 1 }, { artifact_id: id(8), expected_revision: 2 }];
    if (fault === "revision") body.payload.expected_pilot_revision = 0;
    const response = await h.send(`${root}/inputs`, { method: "POST", body, ...(fault === "malformed" ? { raw: "{" } : {}) });
    assert.equal(response.status, 422); assert.equal(h.calls.length, 0);
  });
test("Pilot inputs retain same-origin and authenticated session", async () => {
  const h = harness(); assert.equal((await h.send(`${root}/inputs`, { method: "POST", body: command("npi.pilot.create"), origin: "https://other.invalid" })).status, 403); assert.equal(h.calls.length, 0);
  const anon = harness({ loggedIn: false }); assert.equal((await anon.send(`${root}?project_id=${id(5)}`)).status, 401); assert.equal(anon.calls.length, 0);
});
test("Pilot transport failure preserves the original request without automatic retry", async () => {
  const h = harness({ unavailable: true });
  assert.equal((await h.send(`${root}/inputs`, { method: "POST", body: command("npi.pilot.create") })).status, 503);
  assert.equal(h.calls.length, 1);
});
