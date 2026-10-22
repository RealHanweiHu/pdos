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
const product = `v1/categories/${id(1)}/products/${id(2)}`;
const root = `${product}/experience`, inputs = `${root}/inputs`, category = `v1/categories/${id(1)}/experience`;
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

test("experience category and product reads accept one optional actual project without changing the scope", async () => {
  for (const path of [root, category, `${root}?project_id=${id(4)}`, `${category}?project_id=${id(4)}`]) { const h = harness(), response = await h.send(path); assert.equal(response.status, 200); assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${path}`); assert.equal(response.headers.get("Cache-Control"), "no-store"); assert.equal(h.calls[0].init.cache, "no-store"); }
});
test("experience reads reject duplicate invalid or extraneous selectors and material inputs accept no query", async () => {
  for (const query of ["?project_id=", "?project_id=wrong", `?project_id=${id(4)}&project_id=${id(4)}`, `?project_id=${id(4)}&owner_id=${id(9)}`, `?category_id=${id(9)}`, "?page_size=100", "?cursor=opaque", "?include_history=true"]) { const h = harness(); assert.equal((await h.send(root + query)).status, 422); assert.equal(h.calls.length, 0); }
  const h = harness(); assert.equal((await h.send(inputs + `?project_id=${id(4)}`, { method: "POST", body: command() })).status, 422); assert.equal(h.calls.length, 0);
});
test("experience read and material methods are separate and never write through GET", async () => {
  for (const [path, method, allow] of [[root, "POST", "GET"], [root, "DELETE", "GET"], [inputs, "GET", "POST"], [inputs, "PUT", "POST"]]) { const h = harness(), response = await h.send(path, { method, ...(method === "GET" ? {} : { body: command() }) }); assert.equal(response.status, 405); assert.equal(response.headers.get("Allow"), allow); assert.equal(h.calls.length, 0); }
});
test("product candidate and rule inputs preserve the complete original request and current session", async () => {
  for (const rule of [false, true]) { const h = harness(), body = command(rule); assert.equal((await h.send(inputs, { method: "POST", body })).status, 200); assert.deepEqual(JSON.parse(h.calls[0].init.body), body); assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${inputs}`); assert.equal(h.calls[0].init.headers.Authorization, "Bearer synthetic-experience-session"); }
  const h = harness(), body = { ...command(), product_id: null }; assert.equal((await h.send(category + "/inputs", { method: "POST", body })).status, 200); assert.deepEqual(JSON.parse(h.calls[0].init.body), body); assert.equal(JSON.parse(h.calls[0].init.body).payload.project_id, null);
});
test("category candidate cannot acquire a fabricated product or project and formal publication needs both", async () => {
  for (const body of [command(), { ...command(), product_id: null, payload: { ...command().payload, project_id: id(4) } }, { ...command(true), product_id: null }, { ...command(true), payload: { ...command(true).payload, project_id: null } }]) { const h = harness(); const path = body.product_id === null ? category + "/inputs" : body.operation === "knowledge.candidate.create" ? category + "/inputs" : inputs; assert.equal((await h.send(path, { method: "POST", body })).status, 422); assert.equal(h.calls.length, 0); }
});
test("knowledge inputs reject foreign operations, URL scope changes and fabricated authority fields", async () => {
  const original = command(true);
  for (const body of [{ ...original, operation: "work.task.create" }, { ...original, category_id: id(99) }, { ...original, product_id: id(99) }, { ...original, actor_id: id(99) }, { ...original, payload: { ...original.payload, author_id: id(99) } }, { ...original, payload: { ...original.payload, owner_id: id(99) } }, { ...original, payload: { ...original.payload, confirmation_token: "not-a-T2-approval-token" } }, { ...original, payload: { ...original.payload, applicability: { ...original.payload.applicability, assessor_id: id(99) } } }, { ...original, source_read_set: [] }, { ...original, source_read_set: [...original.source_read_set, original.source_read_set[0]] }, { ...original, payload: { ...original.payload, sources: [{ ...source, revision: 3 }] } }]) { const h = harness(); assert.equal((await h.send(inputs, { method: "POST", body })).status, 422); assert.equal(h.calls.length, 0); }
});
test("common knowledge preview and execution forward the exact real T2 approval command without reconstructing payload", async () => {
  const body = command(true); body.payload.approval_token = "actual-common-T2-approval-substitute";
  for (const path of [`v1/categories/${id(1)}/commands/preview`, `v1/categories/${id(1)}/commands`]) { const h = harness(); assert.equal((await h.send(path, { method: "POST", body })).status, 200); assert.deepEqual(JSON.parse(h.calls[0].init.body), body); }
  const h = harness(); assert.equal((await h.send(`v1/categories/${id(1)}/commands`, { method: "POST", body: { ...body, category_id: id(99) } })).status, 422); assert.equal(h.calls.length, 0);
});
test("experience material preserves origin and session boundaries", async () => {
  for (const origin of [null, "http://elsewhere.invalid", "https://localhost:3000"]) { const h = harness(); assert.equal((await h.send(inputs, { method: "POST", body: command(), origin })).status, 403); assert.equal(h.calls.length, 0); }
  const h = harness({ loggedIn: false }); assert.equal((await h.send(root)).status, 401); assert.equal((await h.send(inputs, { method: "POST", body: command() })).status, 401); assert.equal(h.calls.length, 0);
});

