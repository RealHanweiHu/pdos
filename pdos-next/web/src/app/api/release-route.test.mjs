import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { transpileModule, ModuleKind, ScriptTarget } from "typescript";

const compile = name => transpileModule(readFileSync(resolve(name), "utf8"), { compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 } }).outputText;
const route = compile("src/app/api/[...path]/route.ts"), guard = compile("src/lib/request-origin.ts"), transport = compile("src/lib/candidate-transport.ts");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const product = `v1/categories/${id(1)}/products/${id(2)}`;
const root = product + "/release-packages", inputs = product + "/release/inputs";
const command = operation => ({ category_id: id(1), product_id: id(2), operation, command_id: id(3), idempotency_key: "original-release-key", expected_revision: 5, source_read_set: [], payload: operation === "release.package.assemble" ? { project_id: id(5) } : { package: { id: id(6), revision: 2 } } });
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


test("fixed release history and detail use scoped reads", async () => {
  const h = harness();
  assert.equal((await h.send(`${root}?project_id=${id(5)}&history_cursor=${id(6)}`)).status, 200);
  assert.equal((await h.send(`${root}/${id(6)}`)).status, 200);
  assert.ok(h.calls.every(c => c.init.method === "GET" && c.init.body === undefined));
});
for (const path of [root, `${root}?project_id=${id(5)}&project_id=${id(6)}`, `${root}/${id(6)}?revision=1`, `${inputs}?project_id=${id(5)}`])
  test(`ambiguous release range is rejected: ${path}`, async () => {
    const h = harness(); assert.ok([405, 422].includes((await h.send(path)).status)); assert.equal(h.calls.length, 0);
  });
for (const operation of ["release.package.assemble", "release.engineering.approve", "release.manufacturing.approve"])
  test(`${operation} forwards the original unresolved owner request once`, async () => {
    const h = harness(), body = command(operation);
    assert.equal((await h.send(inputs, { method: "POST", body })).status, 200);
    assert.equal(h.calls.length, 1); assert.deepEqual(JSON.parse(h.calls[0].init.body), body);
  });
for (const fault of ["product", "operation", "reads", "revision", "malformed"])
  test(`release rejects ${fault} before forwarding`, async () => {
    const h = harness(), body = command("release.manufacturing.approve");
    if (fault === "product") body.product_id = id(20);
    if (fault === "operation") body.operation = "build.start";
    if (fault === "reads") body.source_read_set = [{ artifact_id: id(8), expected_revision: 1 }, { artifact_id: id(8), expected_revision: 2 }];
    if (fault === "revision") body.payload.package.revision = 0;
    assert.equal((await h.send(inputs, { method: "POST", body, ...(fault === "malformed" ? { raw: "{" } : {}) })).status, 422);
    assert.equal(h.calls.length, 0);
  });
test("release keeps authenticated same-origin scope and one attempt on transport failure", async () => {
  const h = harness(); assert.equal((await h.send(inputs, { method: "POST", body: command("release.package.assemble"), origin: "https://other.invalid" })).status, 403); assert.equal(h.calls.length, 0);
  const anon = harness({ loggedIn: false }); assert.equal((await anon.send(`${root}?project_id=${id(5)}`)).status, 401); assert.equal(anon.calls.length, 0);
  const down = harness({ unavailable: true }); assert.equal((await down.send(inputs, { method: "POST", body: command("release.package.assemble") })).status, 503); assert.equal(down.calls.length, 1);
});
