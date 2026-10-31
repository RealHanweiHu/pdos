import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../.."), ts = createRequire(path.join(web, "package.json"))("typescript");
const compile = relative => ts.transpileModule(readFileSync(path.join(web, "src", relative), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12,"0")}`, category = id(1), session = id(2), key = id(3), proposal = id(4);
const original = { expected_revision: 0, request_key: key, action: "rename", title: "原名称😀" };
function harness(options = {}) {
 const loaded = { exports: {} }, calls = [], origins = { exports: {} };
 runInNewContext(compile("lib/request-origin.ts"), { module: origins, exports: origins.exports, URL });
 runInNewContext(compile("lib/pai-session-presentation-proxy.ts"), { module: loaded, exports: loaded.exports, URLSearchParams, Response, AbortSignal, TextDecoder, Uint8Array,
  process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
  require: name => name === "@/lib/request-origin" ? origins.exports : name === "next/headers" ? { cookies: async () => ({ get: () => options.session === false ? undefined : { value: "synthetic-token" } }) } : assert.fail(name),
  fetch: async (url, init) => { calls.push({ url, init }); if (options.failure) throw Error("offline"); return Response.json(options.body ?? { received: true }, { status: options.status ?? 200 }); },
 });
 function request(method, query = "", value = original, headers = {}, stream) {
  const body = method === "POST" ? stream ?? (typeof value === "string" ? value : JSON.stringify(value)) : undefined;
  const req = new Request(`http://localhost/api/synthetic${query ? `?${query}` : ""}`, { method, body, ...(stream ? { duplex: "half" } : {}), headers: { host: "localhost", origin: "http://localhost", "content-type": "application/json", ...headers } });
  Object.defineProperty(req, "nextUrl", { value: new URL(req.url) }); return req;
 }
 return { calls, request, list: (query = "", cat) => loaded.exports.paiConversationsRead(request("GET", query), cat),
  post: (value = original, query = "", cat = category, sid = session, headers = {}, stream) => loaded.exports.paiPresentation(request("POST", query, value, headers, stream), cat, sid),
  recover: (query = "", cat = category, sid = session, reqKey = key) => loaded.exports.paiPresentation(request("GET", query), cat, sid, reqKey), exports: loaded.exports };
}
test("static management transports preserve exact private scope, body and no-store without retries", async () => {
 const h = harness(), raw = JSON.stringify(original, null, 2);
 assert.equal((await h.list("view=archived&q=%25_%26&page_size=2&cursor=" + key, category)).status, 200);
 assert.equal((await h.post(raw, `proposal_id=${proposal}`)).status, 200);
 assert.equal((await h.recover(`proposal_id=${proposal}`)).status, 200);
 assert.equal((await h.list()).status, 200); assert.equal((await h.exports.paiPresentation(h.request("POST"), undefined, session)).status, 200);
 assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-conversations?view=archived&q=%25_%26&page_size=2&cursor=${key}`);
 assert.equal(h.calls[1].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-sessions/${session}/presentation?proposal_id=${proposal}`); assert.equal(h.calls[1].init.body, raw);
 assert.equal(h.calls[2].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-sessions/${session}/presentation/requests/${key}?proposal_id=${proposal}`); assert.equal(h.calls[2].init.body, undefined);
 assert.ok(h.calls[3].url.includes("/personal/agent-conversations")); assert.ok(h.calls[4].url.includes("/personal/agent-sessions/"));
 for (const call of h.calls) { assert.equal(call.init.cache, "no-store"); assert.equal(call.init.redirect, "error"); assert.equal(call.init.headers.Authorization, "Bearer synthetic-token"); }
 assert.equal((await h.recover()).headers.get("Cache-Control"), "private, no-store");
});
test("list and presentation query allowlists reject duplicates, scope forgery and malformed paths before network", async () => {
 const h = harness();
 for (const query of ["view=all", "view=active&view=archived", "page_size=01", "page_size=51", "q=a&q=b", "cursor=bad", "principal_id=x", "project_id=bad", "category_id="+key, "proposal_id=bad"]) assert.equal((await h.list(query, category)).status, 422, query);
 for (const query of ["view=active", "page_size=1", "q=name", "cursor="+key, "proposal_id="+proposal+"&proposal_id="+proposal, "principal_id="+key]) {
  assert.equal((await h.post(original, query)).status, 422); assert.equal((await h.recover(query)).status, 422);
 }
 assert.equal((await h.list(`proposal_id=${proposal}`)).status, 422); assert.equal((await h.exports.paiPresentation(h.request("GET"), undefined, session, key)).status, 200); assert.equal((await h.exports.paiPresentation(h.request("POST", `proposal_id=${proposal}`), undefined, session)).status, 422);
 const prior = h.calls.length; assert.equal((await h.post(original,"","bad")).status,404); assert.equal((await h.post(original,"",category,"bad")).status,404); assert.equal((await h.recover("",category,session,"bad")).status,404); assert.equal(h.calls.length, prior);
 assert.equal((await h.list(new URLSearchParams({q:"😀".repeat(160)}).toString())).status,200); assert.equal((await h.list(new URLSearchParams({q:"😀".repeat(161)}).toString())).status,422);
});
test("project conversation list filters stay category-bound and cannot widen presentation writes", async () => {
 const h = harness(); assert.equal((await h.list(`project_id=${key}`, category)).status, 200);
 assert.equal(new URL(h.calls[0].url).searchParams.get("project_id"), key);
 assert.equal((await h.list(`project_id=${key}`)).status, 422);
 assert.equal((await h.list(`project_id=${key}&project_id=${proposal}`, category)).status, 422);
 assert.equal((await h.post(original, `project_id=${key}`)).status, 422);
 assert.equal((await h.recover(`project_id=${key}`)).status, 422); assert.equal(h.calls.length, 1);
});
test("mutations require same origin, live auth and exact JSON body schema", async () => {
 const h = harness();
 assert.equal((await h.post(original,"",category,session,{origin:"https://other.invalid"})).status,403);
 assert.equal((await h.post(original,"",category,session,{"content-type":"text/plain"})).status,415);
 for(const value of [null, [], {}, { ...original, expected_revision: -1 }, {...original, action:"delete"}, {...original, title:" "}, {...original, title:"😀".repeat(161)}, {...original, tenant_id:key}, {expected_revision:0,request_key:key,action:"rename"}, {...original, action:"pin"}]) assert.equal((await h.post(value)).status,422);
 assert.equal((await h.post("{broken")).status,400); assert.equal(h.calls.length,0);
 for(const [options,status] of [[{session:false},401],[{configured:false},503]]) { const denied=harness(options); assert.equal((await denied.post()).status,status); assert.equal((await denied.recover()).status,status); assert.equal(denied.calls.length,0); }
});
test("8 KiB bound measures real stream bytes even with missing or false content length, rejects invalid UTF8", async () => {
 const h=harness(); const bytes=new TextEncoder().encode("x".repeat(8193));
 const stream=()=>new ReadableStream({start(controller){controller.enqueue(bytes.subarray(0,4096));controller.enqueue(bytes.subarray(4096));controller.close();}});
 assert.equal((await h.post("","",category,session,{},stream())).status,413);
 assert.equal((await h.post("","",category,session,{"content-length":"1"},stream())).status,413);
 assert.equal((await h.post(original,"",category,session,{"content-length":"8193"})).status,413);
 const invalid=new ReadableStream({start(controller){controller.enqueue(new Uint8Array([0xff,0xfe]));controller.close();}});
 assert.equal((await h.post("","",category,session,{},invalid)).status,400); assert.equal(h.calls.length,0);
});
test("unknown POST transport is 503 outcome unknown; actual ACL, conflict and absent receipt statuses remain unchanged", async () => {
 const h=harness({failure:true}); const response=await h.post(); assert.equal(response.status,503); assert.equal((await response.json()).code,"EXTERNAL_OUTCOME_UNKNOWN"); assert.equal(h.calls.length,1);
 const read=await h.recover(); assert.equal(read.status,503); assert.equal((await read.json()).code,"SOURCE_UNAVAILABLE"); assert.equal(h.calls.length,2);
 for(const status of [401,403,404,409,503]) { const value={code:"ACTUAL",detail:{reason:"original"}}, h=harness({status,body:value}); for(const response of [await h.post(),await h.recover(),await h.list()]) {assert.equal(response.status,status);assert.deepEqual(await response.json(),value);} assert.equal(h.calls.length,3); }
});
test("all six isolated routes await real params and expose only their single exact method", async () => {
 for(const cat of [false,true]) for(const kind of ["list","write","recover"]) {
  const root=cat?"categories/[categoryId]":"personal", sub=kind==="list"?"agent-conversations":"agent-sessions/[sessionId]/presentation"+(kind==="recover"?"/requests/[requestKey]":""), name=kind==="list"?"paiConversationsRead":"paiPresentation", method=kind==="write"?"POST":"GET", calls=[], loaded={exports:{}}, req={};
  runInNewContext(compile(`app/api/v1/${root}/${sub}/route.ts`),{module:loaded,exports:loaded.exports,require:n=>{assert.equal(n,"@/lib/pai-session-presentation-proxy");return {[name]:(...args)=>calls.push(args)};}});
  assert.deepEqual(Object.keys(loaded.exports),[method]); await loaded.exports[method](req,{params:Promise.resolve({categoryId:category,sessionId:session,requestKey:key})});
  assert.equal(calls[0][0],req); assert.deepEqual([...calls[0].slice(1)],kind==="list"?(cat?[category]:[]):[cat?category:undefined,session,...(kind==="recover"?[key]:[])]);
 }
 const h=harness(); assert.equal((await h.exports.paiConversationsRead(h.request("POST"))).status,405); assert.equal((await h.exports.paiPresentation(h.request("GET"),category,session)).status,405); assert.equal(h.calls.length,0);
});
