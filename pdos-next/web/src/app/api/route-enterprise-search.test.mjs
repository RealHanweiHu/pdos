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
const session = "11111111-1111-4111-8111-111111111111";
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

test("enterprise retrieval forwards only explicit POST queries under the selected path scope", async () => {
  const h = harness();
  for (const resource of ["v1/personal/enterprise-search", `v1/categories/${session}/enterprise-search`]) {
    const body = { query: "D16-01漏气怎么处理", source_types: ["artifact"], limit: 10 };
    assert.equal((await h.send(resource, "POST", "", body)).status, 200);
    assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/${resource}`);
    assert.equal(h.calls.at(-1).init.method, "POST");
    assert.equal(h.calls.at(-1).init.cache, "no-store");
    assert.deepEqual(JSON.parse(h.calls.at(-1).init.body), body);
  }
});

test("enterprise search rejects methods, URL scope, and missing identity without contacting upstream", async () => {
  const h = harness();
  assert.equal((await h.send("v1/personal/enterprise-search")).status, 405);
  assert.equal((await h.send("v1/personal/enterprise-search", "POST", "tenant_id=other", {})).status, 422);
  assert.equal(h.calls.length, 0);
  const anonymous = harness({ session: false });
  assert.equal((await anonymous.send("v1/personal/enterprise-search", "POST", "", { query: "漏气" })).status, 401);
  assert.equal(anonymous.calls.length, 0);
  const revoked = harness({ status: 403 });
  assert.equal((await revoked.send("v1/personal/enterprise-search", "POST", "", { query: "漏气" })).status, 403);
});

test("citation reader forwards bounded GET pages and never accepts scope or duplicate parameters", async () => {
  for (const scope of ["personal", `categories/${session}`]) {
    const resource = `v1/${scope}/agent-runs/${session}/assistant-sources/${session}`;
    const h = harness({ body: { text: "可读片段", next_cursor: 20 } });
    assert.equal((await h.send(resource, "GET", "cursor=10&page_chars=20")).status, 200);
    assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${resource}?cursor=10&page_chars=20`);
    assert.equal(h.calls[0].init.method, "GET");
    assert.equal(h.calls[0].init.cache, "no-store");
    for (const query of ["tenant_id=other", "cursor=0&cursor=1", "page_chars=2001", "cursor=-1", "page_chars=0", "cursor=nan", "change_id=bad", `change_id=${"a".repeat(64)}&change_id=${"a".repeat(64)}`]) {
      assert.equal((await h.send(resource, "GET", query)).status, 422, query);
    }
    assert.equal((await h.send(resource, "POST", "", {})).status, 405);
    assert.equal(h.calls.length, 1);
    assert.equal((await h.send(resource, "GET", `change_id=${"a".repeat(64)}&page_chars=500`)).status, 200);
    assert.match(h.calls[1].url, new RegExp(`change_id=${"a".repeat(64)}&page_chars=500$`));
    const denied = harness({ status: 403 });
    assert.equal((await denied.send(resource)).status, 403);
    const anonymous = harness({ session: false });
    assert.equal((await anonymous.send(resource)).status, 401);
    assert.equal(anonymous.calls.length, 0);
  }
});
