import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { transpileModule, ModuleKind, ScriptTarget } from "typescript";

const compile = name => transpileModule(readFileSync(resolve(name), "utf8"), { compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 } }).outputText;
const route = compile("src/app/api/[...path]/route.ts"), guard = compile("src/lib/server/request-origin.ts"), transport = compile("src/lib/server/candidate-transport.ts");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const product = `v1/categories/${id(1)}/products/${id(2)}`;
const overview = `${product}/projects/${id(4)}/overview`, cockpit = "v1/personal/project-cockpit";

function harness({ loggedIn = true, unavailable = false } = {}) {
  const calls = [], originModule = { exports: {} }, transportModule = { exports: {} }, routeModule = { exports: {} };
  runInNewContext(guard, { module: originModule, exports: originModule.exports, URL });
  runInNewContext(transport, { module: transportModule, exports: transportModule.exports, require: () => ({ Agent: class {} }) });
  runInNewContext(route, {
    module: routeModule, exports: routeModule.exports, URL, URLSearchParams, Response, Headers,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } }, AbortSignal,
    require: name => {
      if (name === "@/lib/server/request-origin") return originModule.exports;
      if (name === "@/lib/server/candidate-transport") return transportModule.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: () => loggedIn ? { value: "synthetic-session-substitute" } : undefined }) };
      throw new Error(`Unexpected dependency: ${name}`);
    },
    fetch: async (url, init) => { calls.push({ url, init }); if (unavailable) throw new Error("synthetic transport lost"); return Response.json({ synthetic: true }); },
  });
  return { calls, async send(path = overview, { method = "GET", body, raw, origin = "http://localhost:3000" } = {}) {
    const request = new Request(`http://localhost:3000/api/${path}`, { method, headers: { host: "localhost:3000", origin }, ...(raw !== undefined ? { body: raw } : body ? { body: JSON.stringify(body) } : {}) });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return routeModule.exports[method](request, { params: Promise.resolve({ path: path.split("?")[0].split("/") }) });
  } };
}


// D37 ⑦: the overview and the manager cockpit are GET-only read models without query parameters.
test("project overview and manager cockpit forward one scoped GET each", async () => {
  for (const path of [overview, cockpit]) {
    const h = harness(); assert.equal((await h.send(path)).status, 200); assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].init.method, "GET"); assert.equal(h.calls[0].init.body, undefined);
    assert.ok(h.calls[0].url.endsWith(path), h.calls[0].url);
  }
});
test("overview and cockpit refuse writes and any query parameter", async () => {
  for (const path of [overview, cockpit]) {
    const writing = harness(); assert.equal((await writing.send(path, { method: "POST", body: {} })).status, 405); assert.equal(writing.calls.length, 0);
    for (const query of ["?project_id=" + id(5), "?category_id=" + id(1), "?page_size=10"]) { const h = harness(); assert.equal((await h.send(path + query)).status, 422); assert.equal(h.calls.length, 0); }
  }
});
test("overview path requires real identifiers and keeps login and transport failures", async () => {
  for (const path of [`${product}/projects/not-a-project/overview`, `v1/categories/${id(1)}/products/${id(2)}/projects/${id(4)}/overview/extra`]) { const h = harness(); assert.ok([403, 404, 422].includes((await h.send(path)).status)); assert.equal(h.calls.length, 0); }
  const anonymous = harness({ loggedIn: false }); assert.equal((await anonymous.send(cockpit)).status, 401); assert.equal(anonymous.calls.length, 0);
  const down = harness({ unavailable: true }); assert.equal((await down.send(overview)).status, 503); assert.equal(down.calls.length, 1);
});
