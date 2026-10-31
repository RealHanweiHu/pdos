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
const category = `v1/categories/${id(1)}/experience`;
const source = {kind:"artifact",id:id(5),revision:2,position:`line:1;quote_sha256:${"a".repeat(64)}`};
const command = (rule=false) => ({category_id:id(1),product_id:id(2),operation:rule?"knowledge.rule.publish":"knowledge.candidate.create",command_id:id(6),idempotency_key:"original-knowledge-request-key",expected_revision:4,source_read_set:[{artifact_id:id(5),expected_revision:2}],payload:rule?{project_id:id(4),candidate:{id:id(7),revision:2},rule:null,title:"配置经验规则",rule_text:"特定配置的内部经验规则",applicability:{target:{kind:"engineering_configuration",id:id(8),revision:3},purpose:"实际用途",differences:["已核实差异"],adopted_rule:"本配置采用规则",conditions:["只对明确用途适用"],decision:"applicable",rationale:"本人核对实际材料",valid_from:"2030-10-17T12:00:00Z",valid_until:null},sources:[source],reason:"具名正式发布"}:{candidate:null,project_id:null,visibility:"private",title:"经验候选",lesson:"实际经验",evidence_summary:"证据摘要",applicability_hypothesis:"仍待适用性核对",result_receipts:[],sources:[source],reason:"保存假设"}});
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


test("F read and explicit draft/share endpoints keep their actual category scope and no-store", async () => {
  for (const path of [category + "/verified-answers", category + "/gaps/weekly?week=2026-10-26", "v1/personal/knowledge-review-reminders"]) {
    const h = harness(), response = await h.send(path); assert.equal(response.status, 200); assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${path}`); assert.equal(response.headers.get("Cache-Control"), "no-store");
  }
  for (const [suffix, body] of [["answer-draft", {run_id:id(10),kind:"category"}], ["review-draft",{entry_id:id(11)}], ["gaps/preview",{run_id:id(10),kind:"missing_material",feedback_id:null}], ["gaps",{run_id:id(10),kind:"missing_material",feedback_id:null,request_key:id(12),preview_digest:"a".repeat(64)}], ["gaps/attributions",{submission_id:id(11),request_key:id(12),reason:"retrieval_miss"}]]) {
    const h=harness(),path=category+"/"+suffix; assert.equal((await h.send(path,{method:"POST",body})).status,200); assert.deepEqual(JSON.parse(h.calls[0].init.body),body);
  }
});
test("F endpoints reject wrong methods, query selectors and browser body/rank/recipient facts", async () => {
  for (const path of [category + "/verified-answers?owner_id="+id(9),category+"/gaps/weekly?week=2026-10-26&week=2026-10-19",category+"/gaps/weekly?from=2026-10-26",category+"/answer-draft?project_id="+id(4)]) {
    const h=harness(), draft=path.includes("answer-draft"); assert.equal((await h.send(path,{method:draft?"POST":"GET",...(draft?{body:{run_id:id(10),kind:"category"}}:{})})).status,422);assert.equal(h.calls.length,0);
  }
  for (const field of ["question","answer","recipient_id","owner_id","tenant_id","ranking_version","source_proof"]) {
    const h=harness();assert.equal((await h.send(category+"/gaps",{method:"POST",body:{run_id:id(10),kind:"missing_material",feedback_id:null,request_key:id(12),preview_digest:"a".repeat(64),[field]:"injected"}})).status,422);assert.equal(h.calls.length,0);
  }
});
test("structured answer candidate accepts native empty Artifact reads only with the closed real-origin/review DTO",async()=>{
  const body=command();body.product_id=null;body.source_read_set=[];body.payload.sources=[];body.payload.answer_origin={run_id:id(10),answer_digest:"a".repeat(64)};body.payload.knowledge_review={responsible_id:id(3),applicability_scope:"实际合成用途",review_due_at:"2099-01-01T00:00:00Z"};
  const h=harness();assert.equal((await h.send(category+"/inputs",{method:"POST",body})).status,200);assert.deepEqual(JSON.parse(h.calls[0].init.body),body);
  for(const mutate of [c=>{delete c.payload.answer_origin;},c=>{delete c.payload.knowledge_review;},c=>{c.payload.answer_origin.audience=[id(3)];},c=>{c.payload.knowledge_review.verified_by=id(3);},c=>{c.payload.knowledge_review.review_due_at="date";}]){const c=structuredClone(body);mutate(c);const reject=harness();assert.equal((await reject.send(category+"/inputs",{method:"POST",body:c})).status,422);assert.equal(reject.calls.length,0);}
});
test("F read/share keeps existing session and same-origin boundaries",async()=>{
  const h=harness({loggedIn:false});assert.equal((await h.send(category+"/verified-answers")).status,401);
  const other=harness();assert.equal((await other.send(category+"/answer-draft",{method:"POST",body:{run_id:id(10),kind:"category"},origin:"http://elsewhere.invalid"})).status,403);assert.equal(other.calls.length,0);
});

test("exact gap recovery keeps same-origin/session and closed DTO while the server reads only", async () => {
  const body = { run_id:id(10), kind:"missing_material", feedback_id:null, request_key:id(12), preview_digest:"a".repeat(64) };
  const h=harness(); const response=await h.send(category+"/gaps/recover",{method:"POST",body});
  assert.equal(response.status,200); assert.equal(h.calls.length,1); assert.deepEqual(JSON.parse(h.calls[0].init.body),body);
  for (const mutate of [b=>{b.recipient_id=id(1);},b=>{b.source_proof=[];}]) { const forged=structuredClone(body);mutate(forged);const denied=harness();assert.equal((await denied.send(category+"/gaps/recover",{method:"POST",body:forged})).status,422);assert.equal(denied.calls.length,0); }
  assert.equal((await harness().send(category+"/gaps/recover")).status,405);
  assert.equal((await harness().send(category+"/gaps/recover?owner_id="+id(1),{method:"POST",body})).status,422);
  assert.equal((await harness().send(category+"/gaps/recover",{method:"POST",body,origin:"http://elsewhere.invalid"})).status,403);
});
