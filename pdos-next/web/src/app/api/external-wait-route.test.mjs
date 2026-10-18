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
const root=product+"/project-work",inputs=root+"/inputs";
const operations=["work.task.create","work.task.assign","work.task.accept","work.commitment.accept","work.task.start","work.task.submit","work.task.review","work.status_update.create"];
const command=operation=>({category_id:id(1),product_id:id(2),operation,command_id:id(3),idempotency_key:"original-project-work-key",expected_revision:1,source_read_set:[],payload:{project_id:id(4)}});

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


test("external wait read and inputs preserve exact project scope and original body", async () => {
  const h=harness(), endpoint=root+"/external-waits";
  assert.equal((await h.send(endpoint+"?project_id="+id(4))).status,200);
  const body=command("work.external_wait.record");
  assert.equal((await h.send(endpoint+"/inputs",{method:"POST",body})).status,200);
  assert.equal(h.calls.length,2);
  assert.deepEqual(JSON.parse(h.calls[1].init.body),body);
  assert.equal(h.calls[0].init.cache,"no-store");
});
test("external wait inputs cannot become another work operation or use the generic input entry", async () => {
  for(const [endpoint,operation] of [[root+"/external-waits/inputs","work.task.create"],[inputs,"work.external_wait.record"],[root+"/fulfillment/inputs","work.external_wait.record"]]) {
    const h=harness();assert.equal((await h.send(endpoint,{method:"POST",body:command(operation)})).status,422);assert.equal(h.calls.length,0);
  }
});
test("external wait missing scope and write-to-read are refused before any forwarding", async () => {
  const h=harness(),endpoint=root+"/external-waits";
  assert.equal((await h.send(endpoint)).status,422);
  assert.equal((await h.send(endpoint,{method:"POST",body:command("work.external_wait.record")})).status,405);
  assert.equal(h.calls.length,0);
});
