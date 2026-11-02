import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ts = createRequire(path.join(web, "package.json"))("typescript");
const code = ts.transpileModule(readFileSync(path.join(web, "src/app/api/v1/categories/[categoryId]/competitors/[entryId]/segment-assignment/route.ts"), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const cursor = "11111111-1111-4111-8111-111111111111";
function harness(options = {}) {
  const route = { exports: {} }, calls = [];
  runInNewContext(code, {
    module: route, exports: route.exports, URLSearchParams, Response, AbortSignal,
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    require: name => { assert.equal(name, "next/headers"); return { cookies: async () => ({ get: key => { assert.equal(key, "pdos-next-session"); return options.session === false ? undefined : { value: "synthetic-session" }; } }) }; },
    fetch: async (url, init) => { calls.push({ url, init }); if (options.failure) throw new Error("synthetic failure"); return Response.json(options.body ?? { version: "competitor-segment-assignment/v1", can_edit: false, selected_segments: [] }, { status: options.status ?? 200 }); },
  });
  return { calls, exports: route.exports, send(query = "") {
    const request = new Request(`http://localhost:3000/api/v1/categories/11111111-1111-4111-8111-111111111111/competitors/11111111-1111-4111-8111-111111111111/segment-assignment${query ? `?${query}` : ""}`);
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return route.exports.GET(request, { params: Promise.resolve({ categoryId: options.category ?? cursor, entryId: options.entry ?? cursor }) });
  } };
}
test("exact fixed competitor read preserves authorization, response and no-store", async () => {
  const h = harness(), response = await h.send();
  assert.equal(response.status, 200); assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.deepEqual(await response.json(), { version: "competitor-segment-assignment/v1", can_edit: false, selected_segments: [] });
  assert.deepEqual(Object.keys(h.exports), ["GET"]);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/categories/${cursor}/competitors/${cursor}/segment-assignment`);
  assert.equal(h.calls[0].init.headers.Authorization, "Bearer synthetic-session");
  assert.equal(h.calls[0].init.cache, "no-store"); assert.equal(h.calls[0].init.redirect, "error"); assert.equal(h.calls[0].init.body, undefined);
});
test("invalid fixed identities and alternate scope never reach the domain", async () => {
  for (const options of [{category:"bad"},{entry:"bad"}]) { const h=harness(options); assert.equal((await h.send()).status,404); assert.equal(h.calls.length,0); }
  const h=harness(); for (const query of ["category_id=other","entry_id=other","cursor=bad","page_size=20","version=2"]) assert.equal((await h.send(query)).status,422);
  assert.equal(h.calls.length,0);
});
test("caller session and configured backend are required", async () => {
  for (const [options,status] of [[{session:false},401],[{configured:false},503]]) { const h=harness(options); assert.equal((await h.send()).status,status); assert.equal(h.calls.length,0); }
});
test("domain permission, changed version and source failures retain their details", async () => {
  for (const status of [403,404,409]) { const body={code:"SOURCE_STALE",message:"refresh"},h=harness({body,status}),response=await h.send(); assert.equal(response.status,status); assert.deepEqual(await response.json(),body); }
});
test("transport failure stays unavailable without retries or writes", async () => {
  const h=harness({failure:true}),response=await h.send(); assert.equal(response.status,503); assert.equal(h.calls.length,1);
});
