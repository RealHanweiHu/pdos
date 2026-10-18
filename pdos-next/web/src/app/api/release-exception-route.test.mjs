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
const root = product + "/release-exceptions", inputs = product + "/release-exception/inputs";
const decide="release.exception.decide",withdraw="release.exception.withdraw";
const ref=n=>({id:id(n),revision:1});
const command=operation=>({category_id:id(1),product_id:id(2),operation,command_id:id(3),idempotency_key:"original-exception-key",expected_revision:5,source_read_set:[],payload:operation===decide?{basis_package:ref(6)}:{exception:ref(6)}});

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


test("exception detail and project history use distinct scoped endpoints",async()=>{
 const h=harness();for(const path of [`${root}?project_id=${id(5)}&history_cursor=${id(6)}`,`${root}/${id(6)}`])assert.equal((await h.send(path)).status,200);assert.equal(h.calls.length,2);
});
for(const path of [root,`${root}?project_id=${id(5)}&project_id=${id(6)}`,`${root}/${id(6)}?project_id=${id(5)}`,`${root}?project_id=${id(5)}&scope=all`])test(`exception query refused before forwarding: ${path}`,async()=>{const h=harness();assert.equal((await h.send(path)).status,422);assert.equal(h.calls.length,0);});
for(const operation of [decide,withdraw])test(`${operation} forwards one unchanged original`,async()=>{const h=harness(),body=command(operation);assert.equal((await h.send(inputs,{method:"POST",body})).status,200);assert.equal(h.calls.length,1);assert.deepEqual(JSON.parse(h.calls[0].init.body),body);});
for(const fault of ["issuer","visibility","version","operation","product","reads","json"])test(`exception ${fault} refused before forwarding`,async()=>{
 const h=harness(),body=command(withdraw);if(fault==="issuer")body.payload.issuer={key:"client-asserted"};if(fault==="visibility")body.payload.visibility="category";if(fault==="version")body.payload.exception.revision=0;if(fault==="operation")body.operation="build.start";if(fault==="product")body.product_id=id(30);if(fault==="reads")body.source_read_set=[{artifact_id:id(9),expected_revision:1},{artifact_id:id(9),expected_revision:2}];assert.equal((await h.send(inputs,{method:"POST",body,...(fault==="json"?{raw:"{"}:{})})).status,422);assert.equal(h.calls.length,0);
});
test("exception keeps same-origin auth and no retry after unavailable transport",async()=>{
 const h=harness();assert.equal((await h.send(inputs,{method:"POST",body:command(decide),origin:"https://other.invalid"})).status,403);assert.equal(h.calls.length,0);const anon=harness({loggedIn:false});assert.equal((await anon.send(`${root}?project_id=${id(5)}`)).status,401);assert.equal(anon.calls.length,0);const down=harness({unavailable:true});assert.equal((await down.send(inputs,{method:"POST",body:command(withdraw)})).status,503);assert.equal(down.calls.length,1);
});
