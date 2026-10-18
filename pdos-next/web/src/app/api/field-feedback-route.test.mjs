import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { transpileModule, ModuleKind, ScriptTarget } from "typescript";

const compile = name => transpileModule(readFileSync(resolve(name), "utf8"), {
  compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 },
}).outputText;
const route = compile("src/app/api/[...path]/route.ts");
const guard = compile("src/lib/request-origin.ts");
const transport = compile("src/lib/candidate-transport.ts");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const root=`v1/categories/${id(1)}/products/${id(2)}/field-feedback`, category=`v1/categories/${id(1)}/field-feedback`;
const source={kind:"artifact",id:id(5),revision:2,position:`line:1;quote_sha256:${"a".repeat(64)}`};
const command=()=>({category_id:id(1),product_id:id(2),command_id:id(6),idempotency_key:"original-field-feedback-key",operation:"field.feedback.create",expected_revision:4,source_read_set:[{artifact_id:id(5),expected_revision:2}],payload:{title:"现场异响反馈",description:"客户报告原话",channel:"customer",feedback_kind:"opinion",received_at:"2030-10-17T12:00:00Z",reported:{product_label:null,batch_label:"客户提供标签",configuration_label:null},purpose:"实际调查用途",sources:[source],reason:"保留来源事实",visibility:"private"}});
function harness({ loggedIn = true } = {}) {
  const calls = [], originModule = { exports: {} }, transportModule = { exports: {} }, routeModule = { exports: {} };
  runInNewContext(guard, { module: originModule, exports: originModule.exports, URL });
  runInNewContext(transport, { module: transportModule, exports: transportModule.exports, require: () => ({ Agent: class {} }) });
  runInNewContext(route, {
    module: routeModule, exports: routeModule.exports, URL, URLSearchParams, Response, Headers,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } }, AbortSignal,
    require: name => {
      if (name === "@/lib/request-origin") return originModule.exports;
      if (name === "@/lib/candidate-transport") return transportModule.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: () => loggedIn ? { value: "synthetic-experience-session" } : undefined }) };
      throw new Error(`Unexpected dependency: ${name}`);
    },
    fetch: async (url, init) => { calls.push({ url, init }); return Response.json({ synthetic: true }); },
  });
  return { calls, async send(path, { method = "GET", body, origin = "http://localhost:3000" } = {}) {
    const request = new Request(`http://localhost:3000/api/${path}`, {
      method, headers: { host: "localhost:3000", ...(origin === null ? {} : { origin }) },
      ...(body === undefined ? {} : { body: JSON.stringify(body) }),
    });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return routeModule.exports[method === "POST" ? "POST" : "GET"](request, { params: Promise.resolve({ path: path.split("?")[0].split("/") }) });
  } };
}

test("Field reads preserve actual category and one project without background writes",async()=>{
 for(const path of [root,category,`${root}?project_id=${id(7)}`]){const h=harness();assert.equal((await h.send(path)).status,200);assert.equal(h.calls[0].url,`http://synthetic-api.invalid/${path}`);assert.equal(h.calls[0].init.cache,"no-store");}
 for(const suffix of [`?project_id=${id(7)}&project_id=${id(7)}`,"?owner_id=other","?project_id=wrong"]){const h=harness();assert.equal((await h.send(root+suffix)).status,422);assert.equal(h.calls.length,0);}
});
test("Field original request survives inputs preview and execution with exact key",async()=>{
 for(const path of [root+"/inputs",`v1/categories/${id(1)}/commands/preview`,`v1/categories/${id(1)}/commands`]){const h=harness(),body=command();assert.equal((await h.send(path,{method:"POST",body})).status,200);assert.deepEqual(JSON.parse(h.calls[0].init.body),body);}
 const h=harness(),body={...command(),product_id:null};assert.equal((await h.send(category+"/inputs",{method:"POST",body})).status,200);
});
test("Field namespace rejects fabricated owners scope and mismatched source reads",async()=>{
 for(const body of [{...command(),actor_id:id(9)},{...command(),product_id:id(9)},{...command(),operation:"quality.issue.create"},{...command(),payload:{...command().payload,owner_id:id(9)}},{...command(),source_read_set:[]},{...command(),payload:{...command().payload,sources:[{...source,revision:3}]}}]){const h=harness();assert.equal((await h.send(root+"/inputs",{method:"POST",body})).status,422);assert.equal(h.calls.length,0);}
});
test("Field native change filter forwards exact feedback identity",async()=>{
 const path=`v1/categories/${id(1)}/products/${id(2)}/change-execution?field_feedback_id=${id(8)}`;const h=harness();assert.equal((await h.send(path)).status,200);assert.equal(h.calls[0].url,`http://synthetic-api.invalid/${path}`);
});
