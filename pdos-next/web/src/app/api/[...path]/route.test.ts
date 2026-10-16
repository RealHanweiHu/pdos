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
    module: route, exports: route.exports, URL, URLSearchParams, Response, Headers,
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
  for (const operation of ["quality.policy.import", "change.order.approve", "quality.issue.close", "quality.issue.create.unregistered"]) {
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
