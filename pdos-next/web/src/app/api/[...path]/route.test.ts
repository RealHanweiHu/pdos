import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { ModuleKind, ScriptTarget, transpileModule } from "typescript";
import type { NextRequest } from "next/server";

const category = "dededede-dede-4ded-8ded-dededededede";
const scoped = (path: string) => path.startsWith("v1/categories/") || path === "v1/session" ? path : path.replace(/^v1\//, `v1/categories/${category}/`);
const product = "11111111-2222-4333-8444-555555555555";
const build = "66666666-7777-4888-8999-aaaaaaaaaaaa";
const run = "bbbbbbbb-cccc-4ddd-8eee-ffffffffffff";
const issue = "12345678-1234-4123-8123-123456789abc";
const change = "87654321-4321-4321-8321-cba987654321";
const base = `v1/categories/${category}/products/${product}`;
const options = { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022, esModuleInterop: true };
const compiled = (path: string) => transpileModule(readFileSync(resolve(path), "utf8"), { compilerOptions: options, fileName: path }).outputText;
// Run the actual handler and actual origin guard; only its host I/O is replaced.
const routeSource = compiled("src/app/api/[...path]/route.ts");
const originSource = compiled("src/lib/request-origin.ts");
const transportSource = compiled("src/lib/candidate-transport.ts");
type Handler = (request: NextRequest, context: { params: Promise<{ path: string[] }> }) => Promise<Response>;

function harness(configuration: { token?: string | null; api?: string | null; response?: () => Promise<Response> } = {}) {
  const calls: { url: string; init: RequestInit }[] = [], timeouts: number[] = [];
  const origin = { exports: {} };
  runInNewContext(originSource, { module: origin, exports: origin.exports, URL });
  const dispatchers: { options: Record<string, number> }[] = [];
  class TestAgent {
    readonly options: Record<string, number>;
    constructor(options: Record<string, number>) { this.options = options; dispatchers.push(this); }
  }
  const transport = { exports: {} };
  runInNewContext(transportSource, {
    module: transport, exports: transport.exports,
    require: (name: string) => {
      assert.equal(name, "undici");
      return { Agent: TestAgent };
    },
  });
  assert.equal(dispatchers.length, 1);
  assert.equal(dispatchers[0].options.headersTimeout, 600000);
  assert.equal(dispatchers[0].options.bodyTimeout, 600000);
  const route = { exports: {} };
  runInNewContext(routeSource, {
    module: route, exports: route.exports, URL, URLSearchParams, Response, Headers, TextEncoder,
    process: { env: { PDOS_NEXT_API_URL: configuration.api === null ? undefined : configuration.api ?? "http://synthetic-api.invalid" } },
    AbortSignal: { timeout: (milliseconds: number) => { timeouts.push(milliseconds); return new AbortController().signal; } },
    require: (name: string) => {
      if (name === "@/lib/request-origin") return origin.exports;
      if (name === "@/lib/candidate-transport") return transport.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: (key: string) => {
        assert.equal(key, "pdos-next-session");
        const token = configuration.token === null ? undefined : configuration.token ?? "synthetic-test-session";
        return token ? { value: token } : undefined;
      } }) };
      throw new Error(`Unexpected handler dependency: ${name}`);
    },
    fetch: async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return configuration.response ? configuration.response() : Response.json({ fixed_receipt: "synthetic" });
    },
  });
  const handlers = route.exports as { GET: Handler; POST: Handler };
  async function send(path: string, value: { method?: "GET" | "POST"; query?: string; body?: string; origin?: string | null; host?: string; textFailure?: boolean; unscoped?: boolean } = {}) {
    const method = value.method ?? "GET", headers = new Headers({ host: value.host ?? "localhost:3000" });
    if (value.origin !== null) headers.set("origin", value.origin ?? "http://localhost:3000");
    if (!value.unscoped) path = scoped(path);
    const request = new Request(`http://localhost:3000/api/${path}${value.query ? `?${value.query}` : ""}`, { method, headers, body: value.body });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    const originalText = request.text.bind(request);
    let reads = 0;
    request.text = async () => {
      reads += 1;
      assert.equal(reads, 1, "The incoming body must be read only once");
      if (value.textFailure) throw new Error("synthetic body read failure");
      return originalText();
    };
    const response = await handlers[method](request as NextRequest, { params: Promise.resolve({ path: path.split("/") }) });
    return { response, reads };
  }
  return { calls, timeouts, send, dispatcher: dispatchers[0] };
}

const resourceInspect = `${base}/builds/${build}/resources/inspect`;
test("预算恢复与技能移除仅原样转发显式原请求，读取不重发", async () => {
  for (const root of ["v1/agent-runs", "v1/personal/agent-runs"]) {
    const h = harness();
    const body = JSON.stringify({ goal: "保留工作状态继续核对", idempotency_key: issue,
      restart_from_run_id: run, context_revision: 4,
      excluded_continued_skills: ["public_research"] });
    const result = await h.send(root, { method: "POST", body, unscoped: root.includes("personal") });
    assert.equal(result.response.status, 200); assert.equal(h.calls[0].init.body, body);
    assert.equal(h.calls[0].init.method, "POST");
    await h.send(`${root}/${run}/continuation`, { unscoped: root.includes("personal") });
    assert.equal(h.calls.length, 2); assert.equal(h.calls[1].init.method, "GET");
    assert.equal(h.calls[1].init.body, undefined);
  }
});
test("本人运行反馈按当前范围读写原正文，原请求核对与历史分页保持只读",async()=>{
 const h=harness();const path=`v1/agent-runs/${run}/feedback`;
 const body=JSON.stringify({idempotency_key:issue,categories:["wrong_value"],comment:"Actual issue",skill_load_event_id:null});
 assert.equal((await h.send(path,{method:"POST",body})).response.status,200);assert.equal(h.calls[0].init.body,body);
 assert.equal((await h.send(path,{query:`request_key=${issue}`})).response.status,200);
 assert.ok(h.calls.at(-1)?.url.endsWith(`feedback?request_key=${issue}`));assert.equal(h.calls.at(-1)?.init.method,"GET");
 assert.equal((await h.send(`v1/personal/agent-runs/${run}/feedback`,{unscoped:true,query:"before=9&page_size=25"})).response.status,200);
});
test("反馈拒绝范围覆盖、混合恢复游标与跨站写入，读取失败不会变成保存",async()=>{
 const path=`v1/agent-runs/${run}/feedback`;
 for(const query of ["actor_id=forged","page_size=101","before=0","request_key=invalid",`before=1&request_key=${issue}`,`request_key=${issue}&request_key=${run}`]){
  const h=harness();assert.equal((await h.send(path,{query})).response.status,422);assert.equal(h.calls.length,0);
 }
 const h=harness();assert.equal((await h.send(path,{method:"POST",body:"{}",origin:"https://other.invalid"})).response.status,403);assert.equal(h.calls.length,0);
 const down=harness({response:async()=>{throw new Error("Synthetic unavailable");}});
 assert.equal((await down.send(path)).response.status,503);assert.equal(down.calls.length,1);
});
test("运行过程保持只读分页，个人与品类使用各自当前范围", async () => {
  const h=harness();
  const path=`v1/agent-runs/${run}/process`;
  assert.equal((await h.send(path,{query:"before=25&page_size=20"})).response.status,200);
  assert.equal(h.calls[0].url,`http://synthetic-api.invalid/v1/categories/${category}/agent-runs/${run}/process?before=25&page_size=20`);
  assert.equal(h.calls[0].init.method,"GET");
  assert.equal((await h.send(path,{query:`source_cursor=${product}&receipt_cursor=${build}`})).response.status,200);
  assert.ok(h.calls.at(-1)?.url.endsWith(`source_cursor=${product}&receipt_cursor=${build}`));
  assert.equal((await h.send(`v1/personal/agent-runs/${run}/process`,{unscoped:true})).response.status,200);
});
test("过程入口拒绝写入、伪造范围与错误分页，失败不自动派发", async()=>{
  const path=`v1/agent-runs/${run}/process`;
  for (const query of ["before=0","before=-1","before=abc","before=25&before=30","after=0","cursor=forged","source_cursor=forged","receipt_cursor=forged","page_size=101","actor_id=forged"]) {
    const h=harness(); assert.equal((await h.send(path,{query})).response.status,422); assert.equal(h.calls.length,0);
  }
  const h=harness(); assert.equal((await h.send(path,{method:"POST",body:"{}"})).response.status,405); assert.equal(h.calls.length,0);
  const down=harness({response:async()=>{throw new Error("Synthetic unavailable");}});
  assert.equal((await down.send(path)).response.status,503); assert.equal(down.calls.length,1);
});
test("本人预算读取分页与原回执查询保持实际品类和原正文", async () => {
  const h = harness();
  const read = await h.send("v1/agent-budgets", { query: `page_size=20&cursor=${product}` });
  assert.equal(read.response.status, 200);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-budgets?page_size=20&cursor=${product}`);
  const body = JSON.stringify({ operation: "ai.budget.configure", payload: { action: "stop" } });
  const result = await h.send("v1/agent-budgets/recover", { method: "POST", body });
  assert.equal(result.response.status, 200); assert.equal(result.reads, 1); assert.equal(h.calls.at(-1)?.init.body, body);
});

test("预算入口拒绝身份覆盖、错误方法与跨站请求，回执查询失败保持只读", async () => {
  for (const [path, options, status] of [
    ["v1/agent-budgets", { unscoped: true }, 404], ["v1/agent-budgets", { query: "requester_id=forged" }, 422],
    ["v1/agent-budgets", { query: "page_size=20&page_size=30" }, 422], ["v1/agent-budgets", { query: "page_size=201" }, 422],
    ["v1/agent-budgets", { method: "POST", body: "{}" }, 405], ["v1/agent-budgets/recover", {}, 405],
    ["v1/agent-budgets/recover", { method: "POST", query: "cursor=forged", body: "{}" }, 422],
    ["v1/agent-budgets/recover", { method: "POST", origin: "https://other.invalid", body: "{}" }, 403],
  ] as const) { const h = harness(); assert.equal((await h.send(path, options)).response.status, status); assert.equal(h.calls.length, 0); }
  const h = harness({ response: async () => { throw new Error("synthetic unavailable"); } });
  const result = await h.send("v1/agent-budgets/recover", { method: "POST", body: "{}" });
  assert.equal((await result.response.json()).code, "SOURCE_UNAVAILABLE");
});

test("技能管理读取与原请求恢复保留品类和完整原正文", async () => {
  const h = harness();
  assert.equal((await h.send("v1/agent-skills")).response.status, 200);
  const body = JSON.stringify({ operation: "ai.skill.enable", payload: { enabled: true } });
  const result = await h.send("v1/agent-skills/recover", { method: "POST", body });
  assert.equal(result.response.status, 200); assert.equal(result.reads, 1);
  assert.equal(h.calls.at(-1)?.init.body, body);
  assert.equal(h.calls.at(-1)?.url, `http://synthetic-api.invalid/v1/categories/${category}/agent-skills/recover`);
});

test("个人技能选择只读本人租户目录，不绑定品类或接受范围参数", async () => {
  const h = harness();
  const result = await h.send("v1/personal/agent-skills", { unscoped: true });
  assert.equal(result.response.status, 200);
  assert.equal(h.calls[0].url, "http://synthetic-api.invalid/v1/personal/agent-skills");
  for (const options of [
    { unscoped: true, query: "tenant_id=forged" },
    { unscoped: true, query: "page_size=20" },
    { unscoped: true, method: "POST", body: "{}" },
  ] as const) {
    const rejected = harness();
    const response = await rejected.send("v1/personal/agent-skills", options);
    assert.equal(response.response.status, options.method ? 405 : 422);
    assert.equal(rejected.calls.length, 0);
  }
});

test("技能管理拒绝伪造范围与方法，回执查询失败保持只读含义", async () => {
  for (const [path, options, status] of [
    ["v1/agent-skills", { unscoped: true }, 404], ["v1/agent-skills", { query: "tenant_id=forged" }, 422],
    ["v1/agent-skills", { method: "POST", body: "{}" }, 405], ["v1/agent-skills/recover", {}, 405],
    ["v1/agent-skills/recover", { method: "POST", query: "skill=forged", body: "{}" }, 422],
    ["v1/agent-skills/recover", { method: "POST", origin: "https://other.invalid", body: "{}" }, 403],
  ] as const) { const h = harness(); assert.equal((await h.send(path, options)).response.status, status); assert.equal(h.calls.length, 0); }
  const h = harness({ response: async () => { throw new Error("synthetic unavailable"); } });
  const failed = await h.send("v1/agent-skills/recover", { method: "POST", body: "{}" });
  assert.equal((await failed.response.json()).code, "SOURCE_UNAVAILABLE");
});

test("协议登记和只读原回执核对沿用同一正文与当前品类", async () => {
  const h = harness();
  const body = JSON.stringify({ provider: "synthetic-provider", decision: "批准", idempotency_key: "approved-original" });
  for (const path of ["v1/provider-agreements", "v1/provider-agreements/recover"]) {
    const value = await h.send(path, { method: "POST", body });
    assert.equal(value.response.status, 200); assert.equal(value.reads, 1);
    assert.equal(h.calls.at(-1)?.init.body, body);
    assert.equal(h.calls.at(-1)?.url, `http://synthetic-api.invalid/v1/categories/${category}/${path.slice(3)}`);
  }
  const read = await h.send("v1/provider-agreements", { query: "provider=synthetic-provider&page_size=50&cursor=a-provider" });
  assert.equal(read.response.status, 200);
});

test("协议入口拒绝范围覆盖、重复查询、跨站写入和错误方法", async () => {
  for (const [path, options, status] of [
    ["v1/provider-agreements", { unscoped: true }, 404],
    ["v1/provider-agreements", { query: "tenant_id=forged" }, 422],
    ["v1/provider-agreements", { query: "provider=a&provider=b" }, 422],
    ["v1/provider-agreements", { method: "POST", query: "provider=a", body: "{}" }, 422],
    ["v1/provider-agreements/recover", {}, 405],
    ["v1/provider-agreements/recover", { method: "POST", origin: "https://other.invalid", body: "{}" }, 403],
  ] as const) {
    const h = harness(); const value = await h.send(path, options);
    assert.equal(value.response.status, status); assert.equal(h.calls.length, 0);
  }
});

test("恢复回执传输失败保持只读失败，实际登记失败保留结果未知", async () => {
  const h = harness({ response: async () => { throw new Error("synthetic transport unavailable"); } });
  const recovering = await h.send("v1/provider-agreements/recover", { method: "POST", body: "{}" });
  assert.equal((await recovering.response.json()).code, "SOURCE_UNAVAILABLE");
  const writing = await h.send("v1/provider-agreements", { method: "POST", body: "{}" });
  assert.equal((await writing.response.json()).code, "EXTERNAL_OUTCOME_UNKNOWN");
});

test("小Pai与模型配置要求明确品类、准确方法及各自分页条件", async () => {
  for (const path of ["v1/agent-runs", "v1/model-configuration", `v1/products/${product}/workspace`]) {
    const h = harness();
    const value = await h.send(path, { unscoped: true });
    assert.equal(value.response.status, 404); assert.equal(h.calls.length, 0);
  }
  for (const [path, query] of [
    [`v1/agent-runs/${run}`, "page_size=1"], ["v1/agent-runs", "after=0"],
    [`v1/agent-runs/${run}/events`, `cursor=${issue}`],
    ["v1/model-configuration", "enabled=true"],
  ]) {
    const h = harness(); const value = await h.send(path, { query });
    assert.equal(value.response.status, 422); assert.equal(h.calls.length, 0);
  }
  const h = harness(); const invalid = await h.send("v1/model-configuration", { method: "POST", body: "{}" });
  assert.equal(invalid.response.status, 405); assert.equal(h.calls.length, 0);
  const actual = await h.send("v1/agent-runs", { query: `page_size=50&cursor=${issue}` });
  assert.equal(actual.response.status, 200);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-runs?page_size=50&cursor=${issue}`);
});

test("固定工序资源读回原样转发唯一正文与完整来源结果", async () => {
  const result = { execution_authorized: false, relations: [], required_source_read_set: [{ artifact_id: issue, expected_revision: 1 }] };
  const h = harness({ response: async () => Response.json(result) });
  const body = ' {"project_id":"fixed-project","execution":{"quantity":"0.00000001"},"operation_key":"assembly"}\n';
  const { response, reads } = await h.send(resourceInspect, { method: "POST", body });
  assert.equal(response.status, 200); assert.equal(reads, 1); assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${resourceInspect}`);
  assert.equal(h.calls[0].init.body, body); assert.equal(h.calls[0].init.method, "POST");
  assert.equal(h.calls[0].init.cache, "no-store"); assert.equal(h.calls[0].init.redirect, "error");
  assert.deepEqual(await response.json(), result); assert.deepEqual(h.timeouts, [60000]);
});
test("资源入口仅允许完整产品与轮次UUID和精确只读路径", async () => {
  for (const path of [resourceInspect.replace(product, "-".repeat(36)), resourceInspect.replace(build, "abc"), resourceInspect.replace("/inspect", "/reserve"), `${resourceInspect}/extra`]) {
    const h = harness(), { response, reads } = await h.send(path, { method: "POST", body: "{}" });
    assert.equal(response.status, 404); assert.equal(reads, 0); assert.equal(h.calls.length, 0);
  }
});
test("资源读取的GET和全部查询选择均在读取正文前拒绝", async () => {
  const h = harness(), get = await h.send(resourceInspect);
  assert.equal(get.response.status, 405); assert.equal(get.response.headers.get("allow"), "POST");
  for (const query of ["authority=true", `project_id=${issue}`, "x=1&x=2"]) {
    const denied = await h.send(resourceInspect, { method: "POST", body: "{}", query });
    assert.equal(denied.response.status, 422); assert.equal(denied.reads, 0);
  }
  assert.equal(h.calls.length, 0);
});
test("资源POST保留同源与有效会话守卫", async () => {
  for (const origin of [null, "https://localhost:3000", "http://other.invalid"]) {
    const h = harness(), { response, reads } = await h.send(resourceInspect, { method: "POST", body: "{}", origin });
    assert.equal(response.status, 403); assert.equal(reads, 0); assert.equal(h.calls.length, 0);
  }
  const h = harness({ token: null }), denied = await h.send(resourceInspect, { method: "POST", body: "{}" });
  assert.equal(denied.response.status, 401); assert.equal(denied.reads, 0); assert.equal(h.calls.length, 0);
});
test("资源领域拒绝原样返回并且不补来源或命令", async () => {
  for (const status of [403, 409, 422, 503]) {
    const result = { code: "RESOURCE_BASIS_UNAVAILABLE" }, h = harness({ response: async () => Response.json(result, { status }) });
    const { response } = await h.send(resourceInspect, { method: "POST", body: "{\"tenant_id\":\"invalid-extra\"}" });
    assert.equal(response.status, status); assert.deepEqual(await response.json(), result); assert.equal(h.calls.length, 1);
  }
});
test("资源读取传输失败如实标记未取得读回，不要求恢复业务操作", async () => {
  const h = harness({ response: async () => { throw new Error("synthetic transport failure"); } });
  const { response } = await h.send(resourceInspect, { method: "POST", body: "{}" });
  assert.equal(response.status, 503); assert.equal((await response.json()).code, "SOURCE_UNAVAILABLE");
  assert.equal(h.calls.length, 1);
});

for (const [path, method, query] of [
  ["quality-execution", "GET", `build_id=${build}&run_id=${run}&issue_id=${issue}`],
  ["quality-execution/inputs", "POST", ""],
  ["change-execution", "GET", `issue_id=${issue}&change_id=${change}`],
  ["change-execution/inputs", "POST", ""],
  ["change-execution/captures", "POST", ""],
] as const) {
  test(`合同入口 ${path} 原样转发，深读600秒、写入180秒`, async () => {
    const h = harness(), body = method === "POST" ? '{"capture_key":"original-key","unknown_value":null}' : undefined;
    const { response, reads } = await h.send(`${base}/${path}`, { method, query, body });
    assert.equal(response.status, 200);
    assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${base}/${path}${query ? `?${query}` : ""}`);
    assert.equal(h.calls[0].init.body, body);
    assert.equal(h.calls[0].init.method, method);
    assert.equal(reads, method === "POST" ? 1 : 0);
    assert.deepEqual(h.timeouts, [method === "GET" ? 600000 : 180000]);
    assert.equal((h.calls[0].init as RequestInit & { dispatcher?: unknown }).dispatcher, method === "GET" ? h.dispatcher : undefined);
    assert.equal(h.calls[0].init.cache, "no-store");
    assert.equal(h.calls[0].init.redirect, "error");
    assert.equal(new Headers(h.calls[0].init.headers).get("authorization"), "Bearer synthetic-test-session");
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  });
}

test("新列表允许无筛选或一个精确筛选，不修改UUID大小写", async () => {
  for (const [path, query] of [["quality-execution", ""], ["quality-execution", `issue_id=${issue.toUpperCase()}`], ["change-execution", `change_id=${change}`]]) {
    const h = harness(), { response } = await h.send(`${base}/${path}`, { query });
    assert.equal(response.status, 200);
    assert.ok(h.calls[0].url.endsWith(`${path}${query ? `?${query}` : ""}`));
  }
});

test("新入口产品标识须为规范UUID，未开放的政策和正式变更动作不转发", async () => {
  for (const path of [
    "v1/products/------------------------------------/quality-execution",
    "v1/products/11111111222243338444555555555555/quality-execution",
    `v1/products/${product.slice(0, -1)}g/change-execution`,
    `${base}/quality-execution/captures`, `${base}/quality-execution/policy`,
    `${base}/change-execution/orders`, `${base}/change-execution/captures/extra`,
    `${base}/change-execution/inputs/../captures`,
  ]) {
    const h = harness(), { response, reads } = await h.send(path);
    assert.equal(response.status, 404, path);
    assert.equal(h.calls.length, 0); assert.equal(reads, 0);
  }
});

test("质量与变更筛选拒绝无效UUID、未知键、跨家族键和重复键", async () => {
  for (const [path, query] of [
    ["quality-execution", `build_id=${"-".repeat(36)}`],
    ["quality-execution", `run_id=${run.replace("-", "a")}`],
    ["quality-execution", "issue_id="],
    ["quality-execution", `issue_id=${issue}&issue_id=${issue}`],
    ["quality-execution", `change_id=${change}`],
    ["quality-execution", "authority=true"],
    ["change-execution", `build_id=${build}`],
    ["change-execution", `change_id=${change}%20`],
    ["change-execution", `issue_id=${issue}&issue_id=${change}`],
    ["change-execution", "reason=unexpected"],
  ]) {
    const h = harness(), { response } = await h.send(`${base}/${path}`, { query });
    assert.equal(response.status, 422, `${path}?${query}`); assert.equal(h.calls.length, 0);
  }
});

test("inputs和captures不接受任何query，列表与写入口的HTTP方法不能互换", async () => {
  for (const path of ["quality-execution/inputs", "change-execution/inputs", "change-execution/captures"]) {
    const h = harness(), denied = await h.send(`${base}/${path}`);
    assert.equal(denied.response.status, 405); assert.equal(denied.response.headers.get("allow"), "POST");
    const queried = await h.send(`${base}/${path}`, { method: "POST", query: `issue_id=${issue}`, body: "{}" });
    assert.equal(queried.response.status, 422); assert.equal(queried.reads, 0); assert.equal(h.calls.length, 0);
  }
  for (const path of ["quality-execution", "change-execution"]) {
    const h = harness(), { response, reads } = await h.send(`${base}/${path}`, { method: "POST", body: "{}" });
    assert.equal(response.status, 405); assert.equal(response.headers.get("allow"), "GET");
    assert.equal(reads, 0); assert.equal(h.calls.length, 0);
  }
});

const operations = [
  "quality.issue.create", "quality.issue.merge", "quality.issue.triage", "quality.issue.containment.record",
  "quality.capa.draft", "change.request.create", "change.impact.compute",
];
for (const operation of operations) {
  test(`${operation} 在共同预览与提交均等待180秒，保留原标识、token和字面数值`, async () => {
    for (const path of ["v1/commands/preview", "v1/commands"]) {
      const h = harness();
      const body = ` {"operation":"${operation}","command_id":"original-command","idempotency_key":"original-key","payload":{"confirmation_token":"original-token","quote":"逐字原文","raw":9007199254740993,"unknown":null}}\n`;
      const { response, reads } = await h.send(path, { method: "POST", body });
      assert.equal(response.status, 200); assert.equal(reads, 1); assert.equal(h.calls.length, 1);
      assert.equal(h.calls[0].init.body, body); assert.deepEqual(h.timeouts, [180000]);
      assert.equal(Object.hasOwn(h.calls[0].init, "dispatcher"), false);
    }
  });
}

test("旧结果四命令及写路径保留180秒，深读600秒，其余旧入口不扩等待", async () => {
  for (const operation of ["test.results.import", "test.result.compute", "test.run.review", "test.disposition.decide"]) {
    const h = harness(); await h.send("v1/commands", { method: "POST", body: JSON.stringify({ operation }) });
    assert.deepEqual(h.timeouts, [180000]);
  }
  for (const path of ["verification-results", "verification-results/inputs", "verification-results/captures"]) {
    const h = harness(); await h.send(`${base}/${path}`, { method: path.includes("/") ? "POST" : "GET", body: path.includes("/") ? "{}" : undefined });
    assert.deepEqual(h.timeouts, [path.includes("/") ? 180000 : 600000]);
    assert.equal((h.calls[0].init as RequestInit & { dispatcher?: unknown }).dispatcher, path.includes("/") ? undefined : h.dispatcher);
  }
  for (const operation of ["quality.policy.import", "quality.issue.close", "quality.issue.create.unregistered"]) {
    const h = harness(); await h.send("v1/commands", { method: "POST", body: JSON.stringify({ operation }) });
    assert.deepEqual(h.timeouts, [60000]);
  }
  const h = harness(); await h.send(`${base}/workspace`); assert.deepEqual(h.timeouts, [60000]);
});

test("无会话或无服务配置不会读body或调用后端", async () => {
  for (const [configuration, status] of [[{ token: null }, 401], [{ api: null }, 503]] as const) {
    const h = harness(configuration), { response, reads } = await h.send(`${base}/quality-execution/inputs`, { method: "POST", body: "{}" });
    assert.equal(response.status, status); assert.equal(reads, 0); assert.equal(h.calls.length, 0);
  }
});

test("写请求必须同源，内部URL主机不同但Origin与Host匹配仍遵循实际守卫", async () => {
  for (const origin of [null, "http://other.invalid", "https://localhost:3000"]) {
    const h = harness(), { response, reads } = await h.send(`${base}/change-execution/captures`, { method: "POST", body: "{}", origin });
    assert.equal(response.status, 403); assert.equal(reads, 0); assert.equal(h.calls.length, 0);
  }
  const aliased = harness(), sameHost = await aliased.send(`${base}/change-execution/captures`, { method: "POST", body: "{}", host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000" });
  assert.equal(sameHost.response.status, 200); assert.equal(aliased.calls.length, 1);
  const h = harness(); const { response } = await h.send(`${base}/quality-execution`, { origin: null });
  assert.equal(response.status, 200, "Reads do not perform an action");
});

test("不合法JSON仅原样转发一次，仍由领域DTO拒绝，BFF不生成替代命令", async () => {
  const h = harness({ response: async () => Response.json({ code: "VALIDATION_FAILED" }, { status: 422 }) });
  const body = '{"operation":"quality.issue.create",';
  const { response, reads } = await h.send("v1/commands", { method: "POST", body });
  assert.equal(response.status, 422); assert.equal(reads, 1); assert.equal(h.calls[0].init.body, body);
  assert.equal(h.calls.length, 1); assert.deepEqual(h.timeouts, [60000]);
});

test("后端写回执未知不会重试，也不把服务器内部错误透露给用户", async () => {
  const h = harness({ response: async () => { throw new Error("synthetic private transport detail"); } });
  const body = JSON.stringify({ operation: "quality.issue.triage", command_id: "original", idempotency_key: "original" });
  const { response, reads } = await h.send("v1/commands", { method: "POST", body });
  assert.equal(response.status, 503); assert.equal(reads, 1); assert.equal(h.calls.length, 1);
  const value = await response.json(); assert.equal(value.code, "EXTERNAL_OUTCOME_UNKNOWN"); assert.equal(JSON.stringify(value).includes("private"), false);
});

test("候选完整核对使用独立等待上限，未知结果保留原请求且绝不自动重发", async () => {
  const body = JSON.stringify({
    command_id: "67676767-6767-4676-8676-676767676767",
    idempotency_key: "synthetic-wave17-original-key", product_id: product, expected_revision: 1,
    operation: "quality.capa.verification.candidate.record",
    payload: { issue_id: issue, expected_issue_revision: 6, reason: "保存缺项候选" },
    source_read_set: [{ artifact_id: build, expected_revision: 1 }],
  });
  for (const path of [`${base}/quality-followup/inputs`, "v1/commands/preview", "v1/commands"]) {
    const h = harness({ response: async () => { throw new Error("synthetic private transport detail"); } });
    const { response, reads } = await h.send(path, { method: "POST", body });
    assert.equal(response.status, 503); assert.equal(reads, 1); assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].init.body, body); assert.deepEqual(h.timeouts, [600000]);
    assert.equal((h.calls[0].init as RequestInit & { dispatcher?: unknown }).dispatcher, h.dispatcher);
    assert.equal(h.calls[0].init.cache, "no-store");
    assert.equal(h.calls[0].init.redirect, "error");
    const result = await response.json(); assert.equal(result.code, "EXTERNAL_OUTCOME_UNKNOWN");
    assert.equal(JSON.stringify(result).includes("private"), false);
  }
});

test("读取失败单独说明未发起操作，显式重读才产生下一次请求", async () => {
  const h = harness({ response: async () => { throw new Error("synthetic unavailable read"); } });
  const first = await h.send(`${base}/quality-execution`, { query: `run_id=${run}` });
  assert.equal(first.response.status, 503); assert.equal((await first.response.json()).code, "SOURCE_UNAVAILABLE");
  assert.equal(first.reads, 0); assert.equal(h.calls.length, 1);
  await h.send(`${base}/quality-execution`, { query: `run_id=${run}` }); assert.equal(h.calls.length, 2);
});

test("配对整改与候选历史深读保持同一600秒传输预算，失败不自动重发", async () => {
  for (const path of ["quality-followup", "capa-candidates"]) {
    const h = harness({ response: async () => { throw new Error("private transport detail"); } });
    const { response, reads } = await h.send(`${base}/${path}`, { query: `issue_id=${issue}` });
    assert.equal(response.status, 503); assert.equal((await response.json()).code, "SOURCE_UNAVAILABLE");
    assert.equal(reads, 0); assert.equal(h.calls.length, 1);
    assert.deepEqual(h.timeouts, [600000]);
    assert.equal((h.calls[0].init as RequestInit & { dispatcher?: unknown }).dispatcher, h.dispatcher);
    assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${base}/${path}?issue_id=${issue}`);
  }
});

test("body读取失败不调用后端，响应流失败也不重发已提交请求", async () => {
  const unread = harness(), failed = await unread.send(`${base}/change-execution/captures`, { method: "POST", body: "{}", textFailure: true });
  assert.equal(failed.response.status, 503); assert.equal(failed.reads, 1); assert.equal(unread.calls.length, 0);
  const stream = harness({ response: async () => new Response(new ReadableStream({ start(controller) { controller.error(new Error("synthetic response lost")); } })) });
  const lost = await stream.send("v1/commands", { method: "POST", body: JSON.stringify({ operation: "change.request.create" }) });
  assert.equal(lost.response.status, 503); assert.equal((await lost.response.json()).code, "EXTERNAL_OUTCOME_UNKNOWN"); assert.equal(stream.calls.length, 1);
});

test("领域403/409/422回执保留状态与正文，下载响应头兼容原入口", async () => {
  for (const status of [403, 409, 422]) {
    const h = harness({ response: async () => Response.json({ code: "EXACT_DOMAIN_GUARD", status }, { status }) });
    const { response } = await h.send(`${base}/quality-execution/inputs`, { method: "POST", body: "{}" });
    assert.equal(response.status, status); assert.deepEqual(await response.json(), { code: "EXACT_DOMAIN_GUARD", status }); assert.equal(h.calls.length, 1);
  }
  const h = harness({ response: async () => new Response("retained original", { headers: { "Content-Type": "application/octet-stream", "Content-Disposition": 'attachment; filename="original.txt"' } }) });
  const { response } = await h.send(`${base}/originals/${issue}/download`);
  assert.equal(await response.text(), "retained original"); assert.equal(response.headers.get("content-disposition"), 'attachment; filename="original.txt"');
});

test("事实读取只接受一个Issue，保持GET与600秒原件等待", async () => {
  const h = harness(), value = await h.send(`${base}/capa-facts`, { query: `issue_id=${issue}` });
  assert.equal(value.response.status, 200); assert.equal(value.reads, 0); assert.equal(h.calls.length, 1);
  assert.deepEqual(h.timeouts, [600000]); assert.equal(h.calls[0].init.method, "GET");
  assert.equal((h.calls[0].init as RequestInit & { dispatcher?: unknown }).dispatcher, h.dispatcher);
  for (const query of ["", `issue_id=${issue}&revision=6`, `issue_id=${issue}&issue_id=${issue}`, `issue_id=invalid`]) {
    const denied = harness(), value = await denied.send(`${base}/capa-facts`, { query });
    assert.equal(value.response.status, 422); assert.equal(denied.calls.length, 0);
  }
});
test("事实候选查询只允许唯一显式UUID，不默认选择并保留单次600秒原查询", async () => {
  for (const query of [`issue_id=${issue}&candidate_id=${change}`, `candidate_id=${change.toUpperCase()}&issue_id=${issue}`]) {
    const h = harness(), value = await h.send(`${base}/capa-facts`, { query });
    assert.equal(value.response.status, 200); assert.equal(value.reads, 0); assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${base}/capa-facts?${query}`);
    assert.deepEqual(h.timeouts, [600000]);
    assert.equal((h.calls[0].init as RequestInit & { dispatcher?: unknown }).dispatcher, h.dispatcher);
    assert.equal(h.calls[0].init.cache, "no-store"); assert.equal(h.calls[0].init.redirect, "error");
  }
  for (const query of [`candidate_id=${change}`, `issue_id=${issue}&candidate_id=`, `issue_id=${issue}&candidate_id=invalid`,
    `issue_id=${issue}&candidate_id=${change}&candidate_id=${change}`, `issue_id=${issue}&candidate_id=${change}&revision=1`,
    `issue_id=${issue}&candidate_id=${change}&qualified=true`]) {
    const h = harness(), value = await h.send(`${base}/capa-facts`, { query });
    assert.equal(value.response.status, 422); assert.equal(value.reads, 0); assert.equal(h.calls.length, 0);
  }
  for (const path of [`${base}/capa-candidates`, `${base}/quality-followup`, `${base}/capa-facts/inputs`]) {
    const h = harness(), value = await h.send(path, { method: path.endsWith("/inputs") ? "POST" : "GET", query: `issue_id=${issue}&candidate_id=${change}`, body: path.endsWith("/inputs") ? "{}" : undefined });
    assert.equal(value.response.status, 422); assert.equal(value.reads, 0); assert.equal(h.calls.length, 0);
  }
});

test("观察和具名复核输入保留完整原体，公共预览与保存仅转发一次", async () => {
  for (const operation of ["quality.capa.observation.record", "quality.capa.verification.review"]) {
    const body = JSON.stringify({ command_id: run, idempotency_key: "wave18-retained-request", product_id: product,
      expected_revision: 1, operation, payload: { issue_id: issue, expected_issue_revision: 6, capa_id: change },
      source_read_set: [{ artifact_id: build, expected_revision: 1 }] });
    for (const path of [`${base}/capa-facts/inputs`, "v1/commands/preview", "v1/commands"]) {
      const h = harness(), value = await h.send(path, { method: "POST", body });
      assert.equal(value.response.status, 200); assert.equal(value.reads, 1); assert.equal(h.calls.length, 1);
      assert.equal(h.calls[0].init.body, body); assert.deepEqual(h.timeouts, [600000]);
      assert.equal((h.calls[0].init as RequestInit & { dispatcher?: unknown }).dispatcher, h.dispatcher);
    }
  }
});

test("事实输入拒绝可信规则发布、旧族操作、跨产品与错误方法", async () => {
  for (const operation of ["quality.capa.verification.rule.import", "professional.authority.import", "quality.capa.followup.link"]) {
    const body = JSON.stringify({ command_id: run, idempotency_key: "wave18-retained-request", product_id: product,
      expected_revision: 1, operation, payload: { issue_id: issue, expected_issue_revision: 6 }, source_read_set: [{ artifact_id: build, expected_revision: 1 }] });
    const h = harness(), value = await h.send(`${base}/capa-facts/inputs`, { method: "POST", body });
    assert.equal(value.response.status, 422); assert.equal(h.calls.length, 0);
  }
  for (const [path, method] of [[`${base}/capa-facts`, "POST"], [`${base}/capa-facts/inputs`, "GET"]] as const) {
    const h = harness(), value = await h.send(path, { method });
    assert.equal(value.response.status, 405); assert.equal(h.calls.length, 0);
  }
});

test("事实超时保留UNKNOWN且不重发，读取失败保留READ_UNAVAILABLE", async () => {
  const lost = harness({ response: async () => { throw new Error("synthetic connection lost"); } });
  const body = JSON.stringify({ operation: "quality.capa.observation.record", original_value: "unchanged" });
  const value = await lost.send("v1/commands", { method: "POST", body });
  assert.equal(value.response.status, 503); assert.equal((await value.response.json()).code, "EXTERNAL_OUTCOME_UNKNOWN");
  assert.equal(lost.calls.length, 1); assert.equal(lost.calls[0].init.body, body);
  const unread = harness({ response: async () => { throw new Error("synthetic read lost"); } });
  const read = await unread.send(`${base}/capa-facts`, { query: `issue_id=${issue}` });
  assert.equal(read.response.status, 503); assert.equal((await read.response.json()).code, "SOURCE_UNAVAILABLE");
  assert.equal(unread.calls.length, 1); assert.equal(read.reads, 0);
});

test("个人项目投影与运行摘要保留原路径及分页条件", async () => {
  const h = harness();
  for (const path of ["v1/personal/projects", `v1/personal/projects/${product}`, "v1/personal/run-activity"]) {
    const query = path.endsWith("run-activity") ? `page_size=12&waiting=true&cursor=${run}` : path.endsWith("projects") ? `page_size=100&cursor=${product}` : undefined;
    const response = await h.send(path, { unscoped: true, query });
    assert.equal(response.response.status, 200);
    assert.equal(h.calls.at(-1)?.url, `http://synthetic-api.invalid/${path}${query ? `?${query}` : ""}`);
  }
});

test("个人视图只读，拒绝伪造范围和无效分页", async () => {
  for (const input of [
    { path: "v1/personal/projects", method: "POST" as const, status: 405 },
    { path: "v1/personal/projects", query: "category_id=" + category, status: 422 },
    { path: "v1/personal/projects", query: "page_size=201", status: 422 },
    { path: "v1/personal/projects", query: "cursor=bad", status: 422 },
    { path: `v1/personal/projects/${product}`, query: "page_size=1", status: 422 },
    { path: "v1/personal/run-activity", query: "waiting=unknown", status: 422 },
  ]) {
    const h = harness();
    assert.equal((await h.send(input.path, { ...input, unscoped: true })).response.status, input.status);
    assert.equal(h.calls.length, 0);
  }
});

test("对象搜索保持个人只读路径和文字，不放行伪造范围或无效条件", async () => {
  const h = harness();
  const query = new URLSearchParams({ q: "100%_充气", kind: "project", page_size: "20", cursor: `project:${product}:0123456789abcdef` }).toString();
  assert.equal((await h.send("v1/personal/search", { unscoped: true, query })).response.status, 200);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/personal/search?${query}`);
  for (const value of [
    { method: "POST" as const, query: "q=x", status: 405 },
    { query: "", status: 422 }, { query: "q=%20", status: 422 },
    { query: "q=x&q=y", status: 422 }, { query: "q=x&kind=claim", status: 422 },
    { query: "q=x&page_size=101", status: 422 }, { query: "q=x&cursor=bad", status: 422 },
    { query: `q=x&category_id=${category}`, status: 422 }, { query: "q=x&tenant_id=other", status: 422 },
  ]) {
    const invalid = harness();
    assert.equal((await invalid.send("v1/personal/search", { ...value, unscoped: true })).response.status, value.status);
    assert.equal(invalid.calls.length, 0);
  }
});

test("项目计划直达保留品类、型号和具体项目，只允许无额外条件的读取", async () => {
  const path = `${base}/projects/${run}`, h = harness();
  const result = await h.send(path);
  assert.equal(result.response.status, 200);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${path}`);
  for (const options of [{ method: "POST" as const, status: 405 }, { query: "project_id=" + issue, status: 422 }]) {
    const invalid = harness();
    assert.equal((await invalid.send(path, options)).response.status, options.status);
    assert.equal(invalid.calls.length, 0);
  }
  const invalid = harness();
  assert.equal((await invalid.send(`${base}/projects/not-a-project`)).response.status, 404);
  assert.equal(invalid.calls.length, 0);
});

test("案例审阅按明确技能读取并用完整原请求只读恢复", async () => {
  const h = harness();
  assert.equal((await h.send("v1/agent-skill-qualification", { query: "skill_key=public_research" })).response.status, 200);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-skill-qualification?skill_key=public_research`);
  const body = JSON.stringify({ operation: "ai.skill.qualify", payload: { decision: "撤销" } });
  assert.equal((await h.send("v1/agent-skill-qualification/recover", { method: "POST", body })).response.status, 200);
  assert.equal(h.calls.at(-1)?.init.body, body);
});
test("审阅入口拒绝伪造人和租户范围以及重复或不明确选择", async () => {
  for (const [path, options, status] of [
    ["v1/agent-skill-qualification", {}, 422], ["v1/agent-skill-qualification", { query: "skill_key=public_research&reviewed_by=forged" }, 422],
    ["v1/agent-skill-qualification", { query: "skill_key=a&skill_key=b" }, 422], ["v1/agent-skill-qualification", { query: "skill_key=a&cursor=bad" }, 422],
    ["v1/agent-skill-qualification", { unscoped: true, query: "skill_key=a" }, 404], ["v1/agent-skill-qualification/recover", {}, 405],
  ] as const) { const h = harness(); assert.equal((await h.send(path, options)).response.status, status); assert.equal(h.calls.length, 0); }
});

test("MCP 准入、分页和只读原回执按当前品类转发", async () => {
  const h = harness();
  assert.equal((await h.send("v1/agent-mcp", { query: `page_size=20&cursor=${product}` })).response.status, 200);
  assert.equal((await h.send(`v1/agent-mcp/${product}`, { query: `tool_cursor=lookup&grant_cursor=${build}&page_size=10` })).response.status, 200);
  assert.equal((await h.send(`v1/agent-mcp/${product}/history`, { query: `cursor=${build}` })).response.status, 200);
  const body = JSON.stringify({ operation: "mcp.connector.allow", payload: { active: false } });
  assert.equal((await h.send("v1/agent-mcp/recover", { method: "POST", body })).response.status, 200);
  assert.equal(h.calls.at(-1)?.url, `http://synthetic-api.invalid/v1/categories/${category}/agent-mcp/recover`);
  assert.equal(h.calls.at(-1)?.init.body, body);
});
test("MCP 读取不接受伪造范围、异常游标或写入方法", async () => {
  for (const [path, options, status] of [
    ["v1/agent-mcp", { unscoped: true }, 404], ["v1/agent-mcp", { query: "tenant_id=forged" }, 422],
    ["v1/agent-mcp", { query: "page_size=101" }, 422], ["v1/agent-mcp", { query: "cursor=bad" }, 422],
    [`v1/agent-mcp/${product}`, { query: "tool_cursor=a&tool_cursor=b" }, 422],
    [`v1/agent-mcp/${product}/history`, { query: "grant_cursor=bad" }, 422],
    ["v1/agent-mcp/recover", {}, 405], ["v1/agent-mcp", { method: "POST", body: "{}" }, 405],
    ["v1/agent-mcp/recover", { method: "POST", origin: "https://other.invalid", body: "{}" }, 403],
  ] as const) { const h = harness(); assert.equal((await h.send(path, options)).response.status, status); assert.equal(h.calls.length, 0); }
  const h = harness({ response: async () => { throw new Error("synthetic unavailable"); } });
  assert.equal((await (await h.send("v1/agent-mcp/recover", { method: "POST", body: "{}" })).response.json()).code, "SOURCE_UNAVAILABLE");
});

test("原运行对账按原范围读取分页并提交同一技术版本", async () => {
  const h = harness();
  const path = `v1/agent-runs/${run}/reconciliation`;
  assert.equal((await h.send(path, { query: `page_size=20&call_cursor=${product}&receipt_cursor=${build}` })).response.status, 200);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/categories/${category}/agent-runs/${run}/reconciliation?page_size=20&call_cursor=${product}&receipt_cursor=${build}`);
  const body = JSON.stringify({ expected_cancel_epoch: 0 });
  assert.equal((await h.send(path, { method: "POST", body })).response.status, 200);
  assert.equal(h.calls.at(-1)?.init.body, body);
  assert.equal((await h.send(`v1/personal/agent-runs/${run}/reconciliation`, { unscoped: true })).response.status, 200);
});

test("对账入口拒绝伪造范围、重复游标与跨站提交", async () => {
  const path = `v1/agent-runs/${run}/reconciliation`;
  for (const [options, status] of [
    [{ query: "tenant_id=forged" }, 422], [{ query: "call_cursor=bad" }, 422],
    [{ query: `call_cursor=${product}&call_cursor=${build}` }, 422], [{ query: "page_size=101" }, 422],
    [{ method: "POST", query: "automatic=true", body: "{}" }, 422],
    [{ method: "POST", origin: "https://other.invalid", body: "{}" }, 403],
  ] as const) { const h = harness(); assert.equal((await h.send(path, options)).response.status, status); assert.equal(h.calls.length, 0); }
});


test("后续工作按当前品类或个人入口只读恢复，原继续请求正文保持不变",async()=>{
 for(const root of ["v1/agent-runs","v1/personal/agent-runs"]){
  const h=harness(),value=await h.send(`${root}/${run}/continuation`,{unscoped:root.includes("personal")});
  assert.equal(value.response.status,200);assert.equal(h.calls.length,1);
  assert.equal(h.calls[0].init.method,"GET");
  const body=JSON.stringify({goal:"继续原工作",idempotency_key:issue,continue_from_run_id:run});
  const saved=await h.send(root,{method:"POST",body,unscoped:root.includes("personal")});
  assert.equal(saved.response.status,200);assert.equal(h.calls[1].init.body,body);
 }
});
test("后续记录拒绝查询范围伪造及直接写入，读取失败不自动派发",async()=>{
 for(const request of [{method:"POST" as const},{query:`requester_id=${issue}`},{query:`page_size=2`}]){
  const h=harness(),value=await h.send(`v1/agent-runs/${run}/continuation`,request);
  assert.ok([405,422].includes(value.response.status));assert.equal(h.calls.length,0);
 }
 const h=harness({response:async()=>{throw new Error("synthetic unavailable");}});
 assert.equal((await h.send(`v1/agent-runs/${run}/continuation`)).response.status,503);
 assert.equal(h.calls.length,1);assert.equal(h.calls[0].init.method,"GET");
});

test("项目试制列表原样转发单一项目筛选，产品总览仍可读取", async () => {
  const h = harness();
  for (const query of ["", `project_id=${issue}`]) {
    const result = await h.send(`${base}/builds`, { query });
    assert.equal(result.response.status, 200);
    assert.equal(h.calls.at(-1)?.url, `http://synthetic-api.invalid/${base}/builds${query ? `?${query}` : ""}`);
    assert.equal(h.calls.at(-1)?.init.method, "GET");
    assert.equal(result.response.headers.get("Cache-Control"), "no-store");
  }
});

test("项目试制列表拒绝重复、无效或额外筛选，不将读取变成写入", async () => {
  const h = harness();
  for (const query of [`project_id=`, "project_id=bad", `project_id=${issue}&project_id=${change}`, `tenant_id=${issue}`, `project_id=${issue}&build_id=${build}`]) {
    assert.equal((await h.send(`${base}/builds`, { query })).response.status, 422, query);
  }
  assert.equal((await h.send(`${base}/builds`, { method: "POST", body: "{}" })).response.status, 405);
  assert.equal(h.calls.length, 0);
});

const materialBody = () => JSON.stringify({ change_id: change, expected_change_revision: 2, source: { id: issue, revision: 1, kind: "artifact", position: `line:3;quote_sha256:${"a".repeat(64)}` } });
const fieldMaterialDraft = () => ({ change_id: change, expected_change_revision: 2, field_intent: { kind: "field_intent", feedback: { id: issue, revision: 3 }, executor_id: run }, item: { id: build, discipline: "engineering", selection: { objects: [{ kind: "engineering_configuration", id: product, revision: 1, key: null }], units: [`object:engineering_configuration:${product}:1:`], conditions: ["仅本项目的固定用途"], sources: [{ id: issue, revision: 1, kind: "artifact", position: `line:3;quote_sha256:${"a".repeat(64)}` }] }, intent: { id: run, kind: "new_engineering_configuration", basis: [{ kind: "engineering_configuration", id: product, revision: 1, key: null }], description: "未来建立明确的新工程配置" }, verification_requirement: "新配置另行实际复验" }, status: "applicable", valid_until: null as string | null, reason: "本人明确本项未来计划" });
test("正式变更读取只放行当前项目列表与唯一指定变更上下文", async () => {
  for (const [path, query] of [["change-execution", `project_id=${issue}`], ["change-execution", `project_id=${issue}&change_id=${change}`], ["change-execution/order-context", `change_id=${change}`]]) {
    const h = harness(), result = await h.send(`${base}/${path}`, { query });
    assert.equal(result.response.status, 200); assert.equal(result.reads, 0); assert.equal(h.calls.length, 1);
    assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${base}/${path}?${query}`); assert.equal(h.calls[0].init.method, "GET"); assert.deepEqual(h.timeouts, [600000]);
  }
});
test("正式变更上下文拒绝缺失重复或混用范围，未开放的相似路径仍不转发", async () => {
  for (const [path, query] of [["change-execution/order-context", ""], ["change-execution/order-context", `change_id=${change}&change_id=${change}`], ["change-execution/order-context", `change_id=${change}&project_id=${issue}`], ["change-execution/order-context", `issue_id=${issue}`], ["change-execution", `project_id=${issue}&project_id=${change}`], ["change-execution", "project_id=invalid"], ["quality-execution", `project_id=${issue}`]]) {
    const h = harness(), result = await h.send(`${base}/${path}`, { query }); assert.equal(result.response.status, 422, `${path}?${query}`); assert.equal(result.reads, 0); assert.equal(h.calls.length, 0);
  }
  for (const path of ["change-execution/order-context/extra", "change-execution/selection-material/extra", "change-execution/policy", "quality-execution/order-context", "quality-execution/selection-material"]) {
    const h = harness(); assert.equal((await h.send(`${base}/${path}`)).response.status, 404, path); assert.equal(h.calls.length, 0);
  }
  const h = harness(), wrongMethod = await h.send(`${base}/change-execution/order-context`, { method: "POST", body: materialBody() });
  assert.equal(wrongMethod.response.status, 405); assert.equal(wrongMethod.response.headers.get("allow"), "GET"); assert.equal(wrongMethod.reads, 0); assert.equal(h.calls.length, 0);
});
test("适用性材料读取保持精确原正文与一次同源POST，不保存或重写候选", async () => {
  const h = harness(), body = ` \n${materialBody()}\n`, result = await h.send(`${base}/change-execution/selection-material`, { method: "POST", body });
  assert.equal(result.response.status, 200); assert.equal(result.reads, 1); assert.equal(h.calls.length, 1); assert.equal(h.calls[0].init.body, body);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${base}/change-execution/selection-material`); assert.equal(h.calls[0].init.method, "POST"); assert.deepEqual(h.timeouts, [180000]);
  const get = harness(); assert.equal((await get.send(`${base}/change-execution/selection-material`)).response.status, 405); assert.equal(get.calls.length, 0);
  const queried = harness(), queryResult = await queried.send(`${base}/change-execution/selection-material`, { method: "POST", query: `change_id=${change}`, body });
  assert.equal(queryResult.response.status, 422); assert.equal(queryResult.reads, 0); assert.equal(queried.calls.length, 0);
});
test("适用性材料入口拒绝非精确变更版本、非整行来源与客户端权限标记", async () => {
  const valid = JSON.parse(materialBody());
  for (const value of [null, {}, { ...valid, expected_change_revision: "2" }, { ...valid, expected_change_revision: true }, { ...valid, expected_change_revision: 0 }, { ...valid, expected_change_revision: 2147483648 }, { ...valid, change_id: "invalid" }, { ...valid, project_id: issue }, { ...valid, qualified: true }, { ...valid, source: { ...valid.source, kind: "domain" } }, { ...valid, source: { ...valid.source, position: "line:0;quote_sha256:" + "a".repeat(64) } }, { ...valid, source: { ...valid.source, position: "line:3;quote_sha256:short" } }, { ...valid, source: { ...valid.source, revision: "1" } }, { ...valid, source: { ...valid.source, authorized: true } }]) {
    const h = harness(), result = await h.send(`${base}/change-execution/selection-material`, { method: "POST", body: JSON.stringify(value) });
    assert.equal(result.response.status, 422, JSON.stringify(value)); assert.equal(result.reads, 1); assert.equal(h.calls.length, 0);
  }
  const invalid = harness(); assert.equal((await invalid.send(`${base}/change-execution/selection-material`, { method: "POST", body: "not-json" })).response.status, 422); assert.equal(invalid.calls.length, 0);
});
test("现场未来计划材料分支完整转发本人声明原文，保留空截止时间且不代作领域决定", async () => {
  for (const [status, deadline] of [["applicable", null], ["unknown", "2026-10-18T12:00:00+08:00"], ["not_applicable", undefined]] as const) {
    const draft = { ...fieldMaterialDraft(), status, valid_until: deadline }, body = ` \n${JSON.stringify(draft)}\n`, h = harness(), result = await h.send(`${base}/change-execution/selection-material`, { method: "POST", body });
    assert.equal(result.response.status, 200); assert.equal(result.reads, 1); assert.equal(h.calls.length, 1); assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${base}/change-execution/selection-material`); assert.equal(h.calls[0].init.method, "POST"); assert.equal(h.calls[0].init.body, body); assert.deepEqual(h.timeouts, [180000]);
  }
});
test("现场材料草拟拒绝混用来源分支、伪范围、错误反馈执行人和不完整计划", async () => {
  const valid = fieldMaterialDraft(), target = valid.field_intent, item = valid.item, missing = ["change_id", "expected_change_revision", "field_intent", "item", "status", "reason"].map(key => Object.fromEntries(Object.entries(valid).filter(([field]) => field !== key)));
  const invalid: unknown[] = [
    ...missing, { ...valid, source: JSON.parse(materialBody()).source }, { ...valid, source: null },
    ...["scope", "tenant_id", "category_id", "product_id", "project_id", "purpose", "qualified", "authorized", "owner_id"].map(key => ({ ...valid, [key]: key === "scope" ? { tenant_id: product, project_id: issue } : issue })),
    { ...valid, expected_change_revision: "2" }, { ...valid, field_intent: null }, { ...valid, field_intent: { ...target, kind: "capa_action" } }, { ...valid, field_intent: { ...target, executor_id: "not-a-person-id" } }, { ...valid, field_intent: { ...target, executor_id: null } }, { ...valid, field_intent: { ...target, feedback: { id: "not-feedback", revision: 3 } } },
    ...["3", true, 0].map(revision => ({ ...valid, field_intent: { ...target, feedback: { ...target.feedback, revision } } })),
    { ...valid, field_intent: { ...target, feedback: { ...target.feedback, qualified: true } } }, { ...valid, field_intent: { ...target, scope: { project_id: issue } } },
    { ...valid, status: "approved" }, { ...valid, reason: " " }, { ...valid, valid_until: "2026-10-18T12:00:00" }, { ...valid, valid_until: "invalid" },
    { ...valid, item: {} }, { ...valid, item: { ...item, id: "not-item" } }, { ...valid, item: { ...item, discipline: "self-approved" } }, { ...valid, item: { ...item, selection: null } }, { ...valid, item: { ...item, selection: { ...item.selection, objects: [] } } }, { ...valid, item: { ...item, selection: { ...item.selection, sources: [] } } }, { ...valid, item: { ...item, intent: { ...item.intent, basis: [] } } }, { ...valid, item: { ...item, intent: { ...item.intent, kind: "arbitrary-action" } } }, { ...valid, item: { ...item, verification_requirement: "" } },
  ];
  for (const value of invalid) { const h = harness(), result = await h.send(`${base}/change-execution/selection-material`, { method: "POST", body: JSON.stringify(value) }); assert.equal(result.response.status, 422, JSON.stringify(value)); assert.equal(result.reads, 1); assert.equal(h.calls.length, 0); }
});
test("适用性材料只读传输失败与真实共同提交未知分别报告，读取不冒充待保存", async () => {
  const reading = harness({ response: async () => { throw new Error("synthetic unavailable"); } });
  const result = await reading.send(`${base}/change-execution/selection-material`, { method: "POST", body: materialBody() });
  assert.equal(result.response.status, 503); assert.equal((await result.response.json()).code, "SOURCE_UNAVAILABLE"); assert.equal(reading.calls.length, 1);
  const write = harness({ response: async () => { throw new Error("synthetic unavailable"); } });
  const committed = await write.send("v1/commands", { method: "POST", body: JSON.stringify({ operation: "change.selection.decide" }) });
  assert.equal(committed.response.status, 503); assert.equal((await committed.response.json()).code, "EXTERNAL_OUTCOME_UNKNOWN"); assert.equal(write.calls.length, 1);
  const crossOrigin = harness(), rejected = await crossOrigin.send(`${base}/change-execution/selection-material`, { method: "POST", body: materialBody(), origin: "https://other.invalid" });
  assert.equal(rejected.response.status, 403); assert.equal(rejected.reads, 0); assert.equal(crossOrigin.calls.length, 0);
});
test("变更适用性、准备、批准与实施使用共同长命令等待，原正文令牌不改写", async () => {
  for (const operation of ["change.selection.decide", "change.order.prepare", "change.order.approve", "change.implementation.record", "change.effectivity.record", "change.verification.record", "change.close"]) for (const path of ["v1/commands/preview", "v1/commands"]) {
    const h = harness(), body = ` {"operation":"${operation}","command_id":"original-command","idempotency_key":"original-key","payload":{"approval_token":"original-approval","confirmation_token":"original-confirmation","unknown":null}}\n`;
    assert.equal((await h.send(path, { method: "POST", body })).response.status, 200); assert.equal(h.calls[0].init.body, body); assert.deepEqual(h.timeouts, [180000]);
  }
  for (const operation of ["change.policy.import", "change.selection.decide.unregistered"]) {
    const h = harness(); await h.send("v1/commands", { method: "POST", body: JSON.stringify({ operation }) }); assert.deepEqual(h.timeouts, [60000]);
  }
});

const implementationCapturePath = `${base}/change-execution/implementation-captures`;
const implementationCaptureInput = () => ({ capture_key: "original-capture-key", change_id: change, expected_change_revision: 6, visibility: "private", order_id: build, item_id: run, source: { id: issue, revision: 2, kind: "artifact", position: `line:3;quote_sha256:${"a".repeat(64)}` } });

test("实施捕获只转发一次精确原正文，保留品类会话、180秒等待和真实捕获响应", async () => {
  const returned = ` {"id":"${build}","fact_id":"${run}","fact":{"outcome":"unknown","note":"原件仍记载未知"},"expires_at":null}\n`;
  const h = harness({ response: async () => new Response(returned, { status: 201, headers: { "Content-Type": "application/json; charset=utf-8" } }) });
  const body = ` \n${JSON.stringify(implementationCaptureInput())}\n`, result = await h.send(implementationCapturePath, { method: "POST", body });
  assert.equal(result.response.status, 201); assert.equal(result.reads, 1); assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${implementationCapturePath}`); assert.equal(h.calls[0].init.method, "POST"); assert.equal(h.calls[0].init.body, body);
  assert.equal(new Headers(h.calls[0].init.headers).get("authorization"), "Bearer synthetic-test-session");
  assert.equal(new Headers(h.calls[0].init.headers).get("content-type"), "application/json");
  assert.equal(h.calls[0].init.cache, "no-store"); assert.equal(h.calls[0].init.redirect, "error"); assert.deepEqual(h.timeouts, [180000]);
  assert.equal(Object.hasOwn(h.calls[0].init, "dispatcher"), false);
  assert.equal(result.response.headers.get("cache-control"), "no-store"); assert.equal(result.response.headers.get("x-content-type-options"), "nosniff");
  assert.equal(result.response.headers.get("content-type"), "application/json; charset=utf-8"); assert.equal(await result.response.text(), returned);
});

test("实施捕获沿用DTO的8至160字符原key和可省略private，不加严为UUID或改写正文", async () => {
  const omitted = { ...implementationCaptureInput() } as Omit<ReturnType<typeof implementationCaptureInput>, "visibility"> & { visibility?: string }; delete omitted.visibility;
  for (const value of [omitted, ...["private", "category", "audience"].map(visibility => ({ ...implementationCaptureInput(), visibility })), ...["same-key", "x".repeat(160), "🔧".repeat(160)].map(capture_key => ({ ...implementationCaptureInput(), capture_key })), { ...implementationCaptureInput(), expected_change_revision: 2147483647, source: { ...implementationCaptureInput().source, revision: 2147483647 } }]) {
    const body = JSON.stringify(value), h = harness(), result = await h.send(implementationCapturePath, { method: "POST", body });
    assert.equal(result.response.status, 200); assert.equal(result.reads, 1); assert.equal(h.calls.length, 1); assert.equal(h.calls[0].init.body, body);
  }
});

test("实施捕获GET、任何query和相似路径都在读取正文前拒绝", async () => {
  const h = harness(), get = await h.send(implementationCapturePath);
  assert.equal(get.response.status, 405); assert.equal(get.response.headers.get("allow"), "POST"); assert.equal(get.reads, 0); assert.equal(h.calls.length, 0);
  for (const query of [`change_id=${change}`, `project_id=${issue}`, "capture_key=original-capture-key", "authorized=true", "x=1&x=2"]) {
    const queried = harness(), result = await queried.send(implementationCapturePath, { method: "POST", query, body: JSON.stringify(implementationCaptureInput()) });
    assert.equal(result.response.status, 422, query); assert.equal(result.reads, 0); assert.equal(queried.calls.length, 0);
  }
  for (const path of [implementationCapturePath + "/extra", implementationCapturePath + "/recover", implementationCapturePath.replace("implementation-captures", "implementation-capture"), implementationCapturePath.replace("change-execution", "quality-execution"), implementationCapturePath.replace(product, "-".repeat(36))]) {
    const denied = harness(), result = await denied.send(path, { method: "POST", body: JSON.stringify(implementationCaptureInput()) });
    assert.equal(result.response.status, 404, path); assert.equal(result.reads, 0); assert.equal(denied.calls.length, 0);
  }
  const unscoped = harness(), result = await unscoped.send(`v1/products/${product}/change-execution/implementation-captures`, { method: "POST", unscoped: true, body: JSON.stringify(implementationCaptureInput()) });
  assert.equal(result.response.status, 404); assert.equal(result.reads, 0); assert.equal(unscoped.calls.length, 0);
});

test("实施捕获拒绝缺项、额外scope或身份权限以及不合DTO的key、标识和版本", async () => {
  const valid = implementationCaptureInput();
  const invalid: unknown[] = [null, [], {}, { ...valid, capture_key: "1234567" }, { ...valid, capture_key: "x".repeat(161) }, { ...valid, capture_key: 12345678 }, { ...valid, capture_key: null }, { ...valid, visibility: "product" }, { ...valid, visibility: null }];
  for (const key of ["capture_key", "change_id", "expected_change_revision", "order_id", "item_id", "source"]) invalid.push(Object.fromEntries(Object.entries(valid).filter(([name]) => name !== key)));
  for (const key of ["change_id", "order_id", "item_id"]) invalid.push({ ...valid, [key]: "invalid" });
  for (const expected_change_revision of [0, -1, 1.5, "6", true, null, 2147483648]) invalid.push({ ...valid, expected_change_revision });
  for (const extra of [{ scope: { product_id: product, project_id: issue } }, { tenant_id: issue }, { category_id: category }, { product_id: product }, { project_id: issue }, { actor_id: issue }, { requester_id: issue }, { authorized: true }, { qualified: true }, { fact: { outcome: "succeeded" } }, { source_read_set: [] }]) invalid.push({ ...valid, ...extra });
  for (const value of invalid) {
    const h = harness(), result = await h.send(implementationCapturePath, { method: "POST", body: JSON.stringify(value) });
    assert.equal(result.response.status, 422, JSON.stringify(value)); assert.equal(result.reads, 1); assert.equal(h.calls.length, 0);
  }
  const malformed = harness(), result = await malformed.send(implementationCapturePath, { method: "POST", body: "not-json" });
  assert.equal(result.response.status, 422); assert.equal(result.reads, 1); assert.equal(malformed.calls.length, 0);
});

test("实施捕获source仅接受四字段精确artifact整行，拒绝版本错型和伪造来源权限", async () => {
  const valid = implementationCaptureInput(), actual = valid.source;
  for (const source of [null, {}, { ...actual, id: "invalid" }, { ...actual, revision: 0 }, { ...actual, revision: -1 }, { ...actual, revision: 1.5 }, { ...actual, revision: "2" }, { ...actual, revision: true }, { ...actual, revision: 2147483648 }, { ...actual, kind: "domain" }, { ...actual, kind: "command" }, { ...actual, position: "line:0;quote_sha256:" + "a".repeat(64) }, { ...actual, position: "line:3;quote_sha256:short" }, { ...actual, position: "line:3;quote_sha256:" + "A".repeat(64) }, { ...actual, position: "line:3;quote_sha256:" + "a".repeat(64) + ";authorized:true" }, { ...actual, original_id: null }, { ...actual, authorized: true }]) {
    const h = harness(), result = await h.send(implementationCapturePath, { method: "POST", body: JSON.stringify({ ...valid, source }) });
    assert.equal(result.response.status, 422, JSON.stringify(source)); assert.equal(result.reads, 1); assert.equal(h.calls.length, 0);
  }
});

test("实施捕获保留同源与cookie会话守卫，未配置或无法读body时不调用后端", async () => {
  const body = JSON.stringify(implementationCaptureInput());
  for (const origin of [null, "https://localhost:3000", "http://other.invalid"]) {
    const h = harness(), result = await h.send(implementationCapturePath, { method: "POST", body, origin });
    assert.equal(result.response.status, 403); assert.equal(result.reads, 0); assert.equal(h.calls.length, 0);
  }
  for (const [configuration, status] of [[{ token: null }, 401], [{ api: null }, 503]] as const) {
    const h = harness(configuration), result = await h.send(implementationCapturePath, { method: "POST", body });
    assert.equal(result.response.status, status); assert.equal(result.reads, 0); assert.equal(h.calls.length, 0);
  }
  const aliased = harness(), allowed = await aliased.send(implementationCapturePath, { method: "POST", body, host: "127.0.0.1:3000", origin: "http://127.0.0.1:3000" });
  assert.equal(allowed.response.status, 200); assert.equal(aliased.calls.length, 1);
  const unread = harness(), failed = await unread.send(implementationCapturePath, { method: "POST", body, textFailure: true });
  assert.equal(failed.response.status, 503); assert.equal(failed.reads, 1); assert.equal(unread.calls.length, 0);
});

test("实施捕获传输或响应流丢失报告结果未知，仅显式同key请求原样重放一次", async () => {
  const body = ` \n${JSON.stringify(implementationCaptureInput())}\n`;
  for (const response of [async (): Promise<Response> => { throw new Error("synthetic private capture transport detail"); }, async () => new Response(new ReadableStream({ start(controller) { controller.error(new Error("synthetic private response detail")); } }))]) {
    const h = harness({ response }), result = await h.send(implementationCapturePath, { method: "POST", body });
    assert.equal(result.response.status, 503); assert.equal(result.reads, 1); assert.equal(h.calls.length, 1); assert.equal(h.calls[0].init.body, body); assert.deepEqual(h.timeouts, [180000]);
    const value = await result.response.json(); assert.equal(value.code, "EXTERNAL_OUTCOME_UNKNOWN"); assert.equal(JSON.stringify(value).includes("private"), false);
  }
  let responses = 0;
  const replay = harness({ response: async () => { responses += 1; if (responses === 1) throw new Error("synthetic unknown outcome"); return Response.json({ id: build, fact_id: run }); } });
  assert.equal((await replay.send(implementationCapturePath, { method: "POST", body })).response.status, 503); assert.equal(replay.calls.length, 1);
  const resolved = await replay.send(implementationCapturePath, { method: "POST", body });
  assert.equal(resolved.response.status, 200); assert.equal(resolved.reads, 1); assert.equal(replay.calls.length, 2); assert.deepEqual(await resolved.response.json(), { id: build, fact_id: run });
  assert.deepEqual(replay.calls.map(call => call.init.body), [body, body]); assert.deepEqual(replay.timeouts, [180000, 180000]);
});

test("实施捕获的实际领域失败保留原状态和逐字正文，不伪造捕获或改写为结果未知", async () => {
  for (const status of [401, 403, 409, 422, 500, 503]) {
    const body = ` {"code":"IMPLEMENTATION_OWNER_MISMATCH","status":${status},"untouched":9007199254740993}\n`;
    const h = harness({ response: async () => new Response(body, { status, headers: { "Content-Type": "application/json" } }) });
    const result = await h.send(implementationCapturePath, { method: "POST", body: JSON.stringify(implementationCaptureInput()) });
    assert.equal(result.response.status, status); assert.equal(await result.response.text(), body); assert.equal(h.calls.length, 1);
  }
});

test("实际采用与关闭读取固定Change目录；材料只读提交原文且不能夹带批准token", async () => {
  const directory = `${base}/change-execution/completion-context`;
  const h = harness();
  assert.equal((await h.send(directory, { query: `change_id=${change}` })).response.status, 200);
  assert.equal(h.calls.length, 1);
  for (const query of ["", `change_id=${change}&project_id=${issue}`, `change_id=${change}&change_id=${change}`]) {
    const denied = harness();
    assert.equal((await denied.send(directory, { query })).response.status, 422);
    assert.equal(denied.calls.length, 0);
  }
  const material = `${base}/change-execution/completion-material`;
  const value = { operation: "change.close", payload: { change_id: change, expected_change_revision: 8, visibility: "category", text: "具名核对通过后分别关闭" } };
  const body = ` \n${JSON.stringify(value)}\n`, prepared = harness();
  assert.equal((await prepared.send(material, { method: "POST", body })).response.status, 200);
  assert.equal(prepared.calls[0].init.body, body);
  const nullable = harness();
  assert.equal((await nullable.send(material, { method: "POST", body: JSON.stringify({ ...value, payload: { ...value.payload, approval_token: null } }) })).response.status, 200);
  for (const invalid of [{ ...value, authorized: true }, { ...value, operation: "change.order.approve" }, { ...value, payload: { ...value.payload, approval_token: "synthetic-not-a-real-token" } }]) {
    const denied = harness();
    assert.equal((await denied.send(material, { method: "POST", body: JSON.stringify(invalid) })).response.status, 422);
    assert.equal(denied.calls.length, 0);
  }
});

test("采用复核材料保留同源和会话守卫；传输失败只报告读取失败", async () => {
  const path = `${base}/change-execution/completion-material`;
  const body = JSON.stringify({ operation: "change.close", payload: { change_id: change, expected_change_revision: 8, visibility: "category", text: "Separate named close" } });
  const cross = harness();
  assert.equal((await cross.send(path, { method: "POST", body, origin: "http://other.invalid" })).response.status, 403);
  assert.equal(cross.calls.length, 0);
  const unsigned = harness({ token: null });
  assert.equal((await unsigned.send(path, { method: "POST", body })).response.status, 401);
  assert.equal(unsigned.calls.length, 0);
  const lost = harness({ response: async () => { throw new Error("private transport detail"); } });
  const response = (await lost.send(path, { method: "POST", body })).response;
  assert.equal(response.status, 503);
  assert.equal((await response.json()).code, "SOURCE_UNAVAILABLE");
  assert.equal(lost.calls.length, 1);
});

test("品类资料维护、可分派成员与提案筛选保留品类范围", async () => {
 const h=harness();
 assert.equal((await h.send("v1/metadata")).response.status,200);
 const body=JSON.stringify({name:"名称",purpose:"场景",expected_revision:2,idempotency_key:run});
 assert.equal((await h.send("v1/metadata",{method:"POST",body})).response.status,200);
 assert.equal(h.calls.at(-1)?.init.body,body);
 assert.equal((await h.send("v1/participants")).response.status,200);
 assert.equal((await h.send("v1/participants",{method:"POST",body})).response.status,405);
 assert.equal((await h.send("v1/proposals",{query:"q=搜索&status=draft&page_size=50"})).response.status,200);
 assert.ok(h.calls.at(-1)?.url.includes(`categories/${category}/proposals?`));
 const before=h.calls.length;
 assert.equal((await h.send("v1/proposals",{query:"status=unknown"})).response.status,422);
 assert.equal((await h.send("v1/proposals",{query:"q=a&q=b"})).response.status,422);
 assert.equal((await h.send("v1/metadata",{query:`category_id=${category}`})).response.status,422);
 assert.equal(h.calls.length,before);
});


test("组织消息代理保留原请求，只接受个人入口和明确分页", async () => {
  const h=harness(), path="v1/personal/inbox/conversations";
  const body=JSON.stringify({category_id:category,recipients:[run],title:"合成主题",body:"合成消息",request_key:issue});
  assert.equal((await h.send(path,{method:"POST",body,unscoped:true})).response.status,200);
  assert.equal(h.calls[0].init.body,body);
  assert.equal((await h.send(`${path}/${run}/messages`,{query:"before=8&page_size=20",unscoped:true})).response.status,200);
  assert.equal((await h.send("v1/personal/inbox/states",{unscoped:true})).response.status,200);
  for(const query of ["principal_id="+run,"page_size=200","cursor="+issue+"&cursor="+run]) {
    const isolated=harness();assert.equal((await isolated.send(path,{query,unscoped:true})).response.status,422);assert.equal(isolated.calls.length,0);
  }
  const cross=harness();assert.equal((await cross.send(path,{method:"POST",body,origin:"https://untrusted.invalid",unscoped:true})).response.status,403);assert.equal(cross.calls.length,0);
});
test("NPI 任务模板必须读取实际项目，拒绝无范围和写请求",async()=>{
 const path=`${base}/project-work/templates`,h=harness();
 assert.equal((await h.send(path,{query:`project_id=${issue}`})).response.status,200);
 for(const value of [{},{query:`project_id=${issue}&principal_id=${run}`},{method:"POST" as const,body:"{}"}]){const isolated=harness();assert.notEqual((await isolated.send(path,value)).response.status,200);assert.equal(isolated.calls.length,0)}
});

test("shared project sets use only the authenticated organization routes", async () => {
  const h = harness();
  assert.equal((await h.send("v1/project-sets", { unscoped:true })).response.status,200);
  const body = JSON.stringify({ name:"合成共享项目集",expected_revision:0,request_key:run });
  assert.equal((await h.send("v1/project-sets", { unscoped:true,method:"POST",body })).response.status,200);
  assert.equal(h.calls.at(-1)?.init.body,body);
  assert.equal((await h.send("v1/project-sets/move", { unscoped:true,method:"POST",body:JSON.stringify({set_id:run,projects:[],request_key:issue}) })).response.status,200);
  assert.equal((await h.send("v1/project-sets", { unscoped:true,query:`tenant_id=${run}` })).response.status,422);
  assert.equal((await h.send("v1/project-sets/move", { unscoped:true })).response.status,405);
  assert.equal((await h.send("v1/project-sets", { unscoped:true,method:"POST",body,origin:"http://untrusted.invalid" })).response.status,403);
});


test("model provider credentials require same-origin POST and stay out of URLs", async () => {
  const h = harness();
  assert.equal((await h.send("v1/model-connections")).response.status, 200);
  const body = JSON.stringify({ request_id: "synthetic-request", api_key: "synthetic-private-key" });
  assert.equal((await h.send("v1/model-connections", { method: "POST", body })).response.status, 200);
  assert.equal(h.calls[1].init.body, body);
  assert.equal(h.calls[1].init.cache, "no-store");
  assert.equal(h.calls[1].url.includes("synthetic-private-key"), false);
  const denied = harness();
  assert.equal((await denied.send("v1/model-connections", { method: "POST", body, origin: "https://other.invalid" })).response.status, 403);
  assert.equal((await denied.send("v1/model-connections", { query: "api_key=synthetic-private-key" })).response.status, 422);
  assert.equal((await denied.send("v1/model-connections", { method: "POST", body: "x".repeat(32769) })).response.status, 413);
  assert.equal(denied.calls.length, 0);
});
