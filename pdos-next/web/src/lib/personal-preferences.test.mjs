import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import test from "node:test";
import path from "node:path";
import { fileURLToPath } from "node:url";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript");
function compile(relative, require) {
  const filename = path.join(web, relative), loaded = new Module(filename);
  loaded.require = require;
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
  return loaded.exports;
}
const values = compile("src/lib/personal-preferences.ts", dependency);
const uuid = "11111111-1111-4111-8111-111111111111";
test("finite explicit DTO rejects identities, inferred authority, coercions and oversized favorites", () => {
  const body = { expected_revision: 0, preferences: values.newPersonalPreferences() };
  assert.equal(values.validPreferenceSave(body), true);
  for (const preferences of [
    { ...body.preferences, requester_id: uuid }, { ...body.preferences, role: "administrator" },
    { ...body.preferences, answer_language: ["en"] }, { ...body.preferences, role: ["quality"] },
    { ...body.preferences, response_detail: ["brief"] }, { ...body.preferences, department: "a\nb" },
    { ...body.preferences, department: "a".repeat(81) }, { ...body.preferences, favorite_category_ids: [uuid, uuid.toUpperCase()] },
    { ...body.preferences, favorite_project_ids: Array.from({ length: 11 }, () => uuid) },
  ]) assert.equal(values.validPreferenceSave({ ...body, preferences }), false);
  for (const expected_revision of [-1, 0.5, true, "1", 2147483647]) assert.equal(values.validPreferenceSave({ ...body, expected_revision }), false);
  assert.equal(values.validPreferenceSave({ ...body, tenant_id: uuid }), false);
});

test("navigation lookup validates finite unique query and pagination without supplying authority", () => {
  assert.equal(values.preferenceOptionsQuery(new URLSearchParams("kind=project&query=泵&page_size=30")).get("query"), "泵");
  for (const query of ["", "kind=category&kind=project", "kind=other", "kind=category&tenant_id=x", "kind=project&requester_id=x", "kind=category&page_size=0", "kind=project&cursor=bad"]) assert.equal(values.preferenceOptionsQuery(new URLSearchParams(query)), null, query);
});

function harness(options = {}) {
  const calls = [];
  const proxy = compile("src/lib/personal-preferences-proxy.ts", name => {
    assert.equal(name, "next/headers");
    return { cookies: async () => ({ get: () => options.noSession ? undefined : { value: "synthetic-self-session" } }) };
  });
  const originalFetch = globalThis.fetch, originalBase = process.env.PDOS_NEXT_API_URL;
  process.env.PDOS_NEXT_API_URL = "http://synthetic-api.invalid";
  globalThis.fetch = async (url, init) => {
    calls.push({ url, init });
    if (options.failure) throw Error("synthetic transport failure");
    return Response.json(options.body ?? { revision: 2 }, { status: options.status ?? 200 });
  };
  const require = name => name === "@/lib/personal-preferences" ? values : name === "@/lib/personal-preferences-proxy" ? proxy : name === "@/lib/request-origin" ? { sameOrigin: request => request.headers.get("origin") === "http://localhost:3000" } : dependency(name);
  const root = compile("src/app/api/v1/personal/preferences/route.ts", require), lookup = compile("src/app/api/v1/personal/preferences/options/route.ts", require);
  return { calls, root, lookup, request(query = "", body, origin = "http://localhost:3000") {
    const request = new Request(`http://localhost:3000/api/v1/personal/preferences${query}`, { method: body === undefined ? "GET" : "POST", headers: { origin, host: "localhost:3000", "content-type": "application/json" }, body: body === undefined ? undefined : JSON.stringify(body) });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) }); return request;
  }, close() { globalThis.fetch = originalFetch; if (originalBase === undefined) delete process.env.PDOS_NEXT_API_URL; else process.env.PDOS_NEXT_API_URL = originalBase; } };
}

test("authenticated personal BFF forwards only explicit valid reads/writes and preserves errors", async () => {
  const h = harness({ status: 409, body: { code: "VERSION_CONFLICT", message: "refresh" } });
  try {
    const body = { expected_revision: 1, preferences: { ...values.newPersonalPreferences(), role: "quality" } };
    const saved = await h.root.POST(h.request("", body));
    assert.equal(saved.status, 409); assert.equal((await saved.json()).code, "VERSION_CONFLICT");
    assert.equal(saved.headers.get("cache-control"), "no-store");
    assert.equal(h.calls[0].url, "http://synthetic-api.invalid/v1/personal/preferences");
    assert.equal(h.calls[0].init.headers.Authorization, "Bearer synthetic-self-session");
    assert.deepEqual(JSON.parse(h.calls[0].init.body), body);
    assert.equal(h.calls[0].init.redirect, "error");
    assert.equal((await h.root.GET(h.request())).status, 409);
    assert.equal(h.calls[1].init.method, "GET"); assert.equal(h.calls[1].init.body, undefined);
    assert.equal((await h.lookup.GET(h.request("?kind=project&query=pump"))).status, 409);
    assert.equal(h.calls[2].url, "http://synthetic-api.invalid/v1/personal/preferences/options?kind=project&query=pump");
    assert.equal((await h.root.POST(h.request("", body, "http://other.invalid"))).status, 403);
    assert.equal((await h.root.POST(h.request("", { ...body, requester_id: uuid }))).status, 422);
    assert.equal((await h.root.GET(h.request("?tenant_id=other"))).status, 422);
    assert.equal((await h.lookup.GET(h.request("?kind=project&requester_id=other"))).status, 422);
    assert.equal(h.calls.length, 3);
  } finally { h.close(); }
});

test("missing session or backend failure remains unavailable and never retries writes", async () => {
  for (const [options, expected] of [[{ noSession: true }, 401], [{ failure: true }, 503]]) {
    const h = harness(options);
    try {
      const response = await h.root.GET(h.request()); assert.equal(response.status, expected);
      assert.equal(h.calls.length, options.noSession ? 0 : 1);
    } finally { h.close(); }
  }
});
