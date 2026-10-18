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
const root=product+"/project-work";

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


test("project activity forwards only a scoped GET and an opaque bounded cursor",async()=>{const h=harness();const query="?project_id="+id(4)+"&page_size=20&cursor=eyJzY29wZSI6MX0";assert.equal((await h.send(root+"/activity"+query)).status,200);assert.equal(h.calls.length,1);assert.equal(h.calls[0].init.method,"GET");assert.equal(h.calls[0].init.body,undefined);assert.ok(h.calls[0].url.endsWith("/project-work/activity"+query));});
for(const query of ["","?project_id="+id(4)+"&project_id="+id(5),"?project_id="+id(4)+"&scope=all","?project_id="+id(4)+"&cursor=bad%3D","?project_id="+id(4)+"&page_size=0","?project_id="+id(4)+"&page_size=101"])test("activity rejects invalid or rebound query "+query,async()=>{const h=harness();assert.equal((await h.send(root+"/activity"+query)).status,422);assert.equal(h.calls.length,0);});
test("project activity has no write or synthetic inputs endpoint",async()=>{for(const path of [root+"/activity?project_id="+id(4),root+"/activity/inputs"]){const h=harness();assert.ok([404,405].includes((await h.send(path,{method:"POST",body:{}})).status));assert.equal(h.calls.length,0);}});
test("activity retains auth and single-attempt transport failure",async()=>{const h=harness({loggedIn:false});assert.equal((await h.send(root+"/activity?project_id="+id(4))).status,401);assert.equal(h.calls.length,0);const down=harness({unavailable:true});assert.equal((await down.send(root+"/activity?project_id="+id(4))).status,503);assert.equal(down.calls.length,1);});


test("project run history forwards one explicit project only on category collections", async () => {
  const h=harness(); const path=`v1/categories/${id(1)}/agent-runs?project_id=${id(4)}&page_size=20`;
  assert.equal((await h.send(path)).status,200); assert.equal(h.calls.length,1);
  assert.ok(h.calls[0].url.endsWith(path)); assert.equal(h.calls[0].init.method,"GET");
  for (const rejected of [
    `v1/categories/${id(1)}/agent-runs?project_id=${id(4)}&project_id=${id(5)}`,
    `v1/categories/${id(1)}/agent-runs?project_id=invalid`,
    `v1/categories/${id(1)}/agent-runs/${id(9)}/events?project_id=${id(4)}`,
    `v1/personal/agent-runs?project_id=${id(4)}`,
  ]) { const invalid=harness(); assert.equal((await invalid.send(rejected)).status,422); assert.equal(invalid.calls.length,0); }
});
