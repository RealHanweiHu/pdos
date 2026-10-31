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


test("summary feed allows only own metadata GET pagination", async () => { const h = harness(); const response = await h.send(`v1/personal/inbox/summaries?page_size=25&cursor=${id(9)}`); assert.equal(response.status, 200); assert.equal(h.calls.length, 1); assert.ok(String(h.calls[0].url).includes("/v1/personal/inbox/summaries")); assert.equal(h.calls[0].init.method, "GET"); });
test("summary feed rejects writes and caller supplied authority before transport", async () => { for (const path of ["v1/personal/inbox/summaries?owner_id=" + id(9), "v1/personal/inbox/summaries?category_id=" + id(9), "v1/personal/inbox/summaries?page_size=101"]) { const h = harness(); assert.equal((await h.send(path)).status, 422); assert.equal(h.calls.length, 0); } const h = harness(); assert.equal((await h.send("v1/personal/inbox/summaries", { method: "POST", body: {} })).status, 405); assert.equal(h.calls.length, 0); });
test("summary feed is unavailable without the actual login cookie", async () => { const h = harness({ loggedIn: false }); assert.equal((await h.send("v1/personal/inbox/summaries")).status, 401); assert.equal(h.calls.length, 0); });
test("summary template options forward only same-cookie GET category/product narrowing", async () => { const h = harness(); assert.equal((await h.send(`v1/personal/inbox/summary-options?category_id=${id(1)}&product_id=${id(2)}`)).status, 200); assert.equal(h.calls[0].init.method, "GET"); assert.ok(String(h.calls[0].url).includes(`category_id=${id(1)}`)); assert.ok(String(h.calls[0].url).includes(`product_id=${id(2)}`)); });
test("summary template route rejects identity/role/query injection and all writes before forwarding", async () => { for (const query of [`owner_id=${id(1)}`, "role=quality", "category_id=bad", `category_id=${id(1)}&category_id=${id(2)}`, "page_size=10"]) { const h = harness(); assert.equal((await h.send(`v1/personal/inbox/summary-options?${query}`)).status, 422); assert.equal(h.calls.length, 0); } const h = harness(); assert.equal((await h.send("v1/personal/inbox/summary-options", { method: "POST", body: {} })).status, 405); assert.equal(h.calls.length, 0); });
