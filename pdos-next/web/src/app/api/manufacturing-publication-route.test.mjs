import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { transpileModule, ModuleKind, ScriptTarget } from "typescript";

const compile = name => transpileModule(readFileSync(resolve(name), "utf8"), { compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 } }).outputText;
const route = compile("src/app/api/[...path]/route.ts"), guard = compile("src/lib/request-origin.ts"), transport = compile("src/lib/candidate-transport.ts");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const root = `v1/categories/${id(1)}/products/${id(2)}/manufacturing-publications`;
const command = () => ({ category_id: id(1), product_id: id(2), operation: "npi.manufacturing_baseline.publish", command_id: id(3), idempotency_key: id(4), expected_revision: 5, source_read_set: [{ artifact_id: id(8), expected_revision: 1 }], payload: { project_id: id(5), baseline: { kind: "manufacturing_baseline", id: id(6), revision: 2 } } });
function harness({ loggedIn = true, unavailable = false } = {}) {
  const calls = [], originModule = { exports: {} }, transportModule = { exports: {} }, routeModule = { exports: {} };
  runInNewContext(guard, { module: originModule, exports: originModule.exports, URL });
  runInNewContext(transport, { module: transportModule, exports: transportModule.exports, require: name => { assert.equal(name, "undici"); return { Agent: class {} }; } });
  runInNewContext(route, {
    module: routeModule, exports: routeModule.exports, URL, URLSearchParams, Response, Headers,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } }, AbortSignal,
    require: name => {
      if (name === "@/lib/request-origin") return originModule.exports;
      if (name === "@/lib/candidate-transport") return transportModule.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: () => loggedIn ? { value: "synthetic-session-substitute" } : undefined }) };
      throw new Error(`Unexpected dependency: ${name}`);
    },
    fetch: async (url, init) => { calls.push({ url, init }); if (unavailable) throw new Error("synthetic transport lost"); return Response.json({ receipt: "synthetic" }); },
  });
  return { calls, async send(path = root, { method = "GET", body, origin = "http://localhost:3000" } = {}) {
    const request = new Request(`http://localhost:3000/api/${path}`, { method, headers: { host: "localhost:3000", origin }, ...(body ? { body: JSON.stringify(body) } : {}) });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return routeModule.exports[method](request, { params: Promise.resolve({ path: path.split("?")[0].split("/") }) });
  } };
}

test("publication history forwards exact project and opaque cursor as a read", async () => {
  const h = harness(); const response = await h.send(`${root}?project_id=${id(5)}&history_cursor=prior%3Acursor`);
  assert.equal(response.status, 200); assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].init.method, "GET"); assert.equal(h.calls[0].init.body, undefined);
  assert.match(h.calls[0].url, /history_cursor=prior%3Acursor/);
});
for (const path of [`${root}?project_id=${id(5)}&project_id=${id(6)}`, root, `${root}/${id(9)}?revision=0`, `${root}/inputs?project_id=${id(5)}`])
  test(`ambiguous or missing publication scope cannot reach host: ${path}`, async () => {
    const h = harness(), response = await h.send(path);
    assert.ok([405, 422].includes(response.status)); assert.equal(h.calls.length, 0);
  });
test("inputs preserve the actual original command and key", async () => {
  const h = harness(), body = command();
  assert.equal((await h.send(`${root}/inputs`, { method: "POST", body })).status, 200);
  assert.equal(h.calls.length, 1); assert.deepEqual(JSON.parse(h.calls[0].init.body), body);
});
for (const fault of ["product", "baseline", "operation"])
  test(`publication inputs reject ${fault} substitution`, async () => {
    const h = harness(), body = command();
    if (fault === "product") body.product_id = id(20);
    if (fault === "baseline") body.payload.baseline.kind = "work_instruction";
    if (fault === "operation") body.operation = "build.start";
    assert.equal((await h.send(`${root}/inputs`, { method: "POST", body })).status, 422);
    assert.equal(h.calls.length, 0);
  });
test("publication input retains same-origin and session guards", async () => {
  const h = harness(); assert.equal((await h.send(`${root}/inputs`, { method: "POST", body: command(), origin: "https://other.invalid" })).status, 403); assert.equal(h.calls.length, 0);
  const anonymous = harness({ loggedIn: false }); assert.equal((await anonymous.send(`${root}?project_id=${id(5)}`)).status, 401); assert.equal(anonymous.calls.length, 0);
});
test("uncertain POST and unavailable GET are distinguished without a transport retry", async () => {
  const h = harness({ unavailable: true }); const post = await h.send(`${root}/inputs`, { method: "POST", body: command() });
  assert.equal(post.status, 503); assert.equal((await post.json()).code, "EXTERNAL_OUTCOME_UNKNOWN"); assert.equal(h.calls.length, 1);
  const get = await h.send(`${root}?project_id=${id(5)}`); assert.equal(get.status, 503); assert.equal((await get.json()).code, "SOURCE_UNAVAILABLE"); assert.equal(h.calls.length, 2);
});
