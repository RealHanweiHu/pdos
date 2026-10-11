import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { ModuleKind, ScriptTarget, transpileModule } from "typescript";
import type { NextRequest } from "next/server";

const category = "dededede-dede-4ded-8ded-dededededede";
const scoped = (path: string) => path.startsWith("v1/categories/") || path === "v1/session" ? path : path.replace(/^v1\//, `v1/categories/${category}/`);
const product = "abcdefab-2222-4333-8444-555555555555";
const issue = "12345678-1234-4123-8123-123456789abc";
const artifact = "abcdefab-cdef-4abc-8def-abcdefabcdef";
const otherProduct = "99999999-8888-4777-8666-555555555555";
const actor = "23232323-2323-4232-8232-232323232323";
const action = "34343434-3434-4343-8343-343434343434";
const capa = "45454545-4545-4454-8454-454545454545";
const formalVersion = "56565656-5656-4565-8565-565656565656";
const endpoint = `v1/categories/${category}/products/${product}/quality-followup`;
const operations = [
  "quality.issue.root_cause.decide",
  "quality.capa.actions.complete",
  "quality.capa.followup.link",
] as const;
type Operation = typeof operations[number];
const options = {
  module: ModuleKind.CommonJS,
  target: ScriptTarget.ES2022,
  esModuleInterop: true,
};
const compiled = (path: string) => transpileModule(
  readFileSync(resolve(path), "utf8"), { compilerOptions: options, fileName: path },
).outputText;
// The same actual route/origin-guard VM protocol as route.test.ts, without executing it.
// Only cookie/config/transport host IO is replaced; there is no copied validation policy.
const routeSource = compiled("src/app/api/[...path]/route.ts");
const originSource = compiled("src/lib/request-origin.ts");
const transportSource = compiled("src/lib/candidate-transport.ts");
type Handler = (
  request: NextRequest,
  context: { params: Promise<{ path: string[] }> },
) => Promise<Response>;

function harness(configuration: {
  token?: string | null;
  api?: string | null;
  response?: () => Promise<Response>;
} = {}) {
  const calls: { url: string; init: RequestInit }[] = [];
  const timeouts: number[] = [];
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
    process: { env: {
      PDOS_NEXT_API_URL: configuration.api === null
        ? undefined : configuration.api ?? "http://synthetic-api.invalid",
    } },
    AbortSignal: { timeout: (milliseconds: number) => {
      timeouts.push(milliseconds);
      return new AbortController().signal;
    } },
    require: (name: string) => {
      if (name === "@/lib/request-origin") return origin.exports;
      if (name === "@/lib/candidate-transport") return transport.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: (key: string) => {
        assert.equal(key, "pdos-next-session");
        const token = configuration.token === null
          ? undefined : configuration.token ?? "synthetic-test-session";
        return token ? { value: token } : undefined;
      } }) };
      throw new Error(`Unexpected handler dependency: ${name}`);
    },
    fetch: async (url: string, init: RequestInit) => {
      calls.push({ url, init });
      return configuration.response
        ? configuration.response() : Response.json({ transport_only: "synthetic" });
    },
  });
  const handlers = route.exports as { GET: Handler; POST: Handler };
  async function send(path: string, value: {
    method?: "GET" | "POST";
    query?: string;
    body?: string;
    origin?: string | null;
    host?: string;
    textFailure?: boolean;
  } = {}) {
    const method = value.method ?? "GET";
    const headers = new Headers({ host: value.host ?? "localhost:3000" });
    if (value.origin !== null) headers.set("origin", value.origin ?? "http://localhost:3000");
    path = scoped(path);
    const request = new Request(
      `http://localhost:3000/api/${path}${value.query ? `?${value.query}` : ""}`,
      { method, headers, body: value.body },
    );
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    const originalText = request.text.bind(request);
    let reads = 0;
    request.text = async () => {
      reads += 1;
      assert.equal(reads, 1, "The incoming body must be read once");
      if (value.textFailure) throw new Error("synthetic body read failure");
      return originalText();
    };
    const response = await handlers[method](request as NextRequest, {
      params: Promise.resolve({ path: path.split("/") }),
    });
    return { response, reads };
  }
  return { calls, timeouts, send, dispatcher: dispatchers[0] };
}

const source = {
  kind: "artifact", id: artifact, revision: 1,
  position: `line:1;quote_sha256:${"a".repeat(64)}`,
};
function command(operation: Operation): Record<string, unknown> {
  const target = { issue_id: issue, expected_issue_revision: 4 };
  const payload = operation === operations[0]
    ? { ...target, text: "合成根因提议，原文 11.0000", sources: [source] }
    : operation === operations[1]
      ? { ...target, completions: [{
        id: action, text: "已观察的合成调查事实", executor_id: actor, evidence: [source],
        at: { occurred_at: "2026-10-03T01:02:03+00:00", original_timezone: "UTC", source },
      }] }
      : { ...target, capa_id: capa, action_id: action,
        output_refs: [{ kind: "verification_request", id: formalVersion, revision: 1, key: null }],
        sources: [{ artifact_id: artifact, expected_revision: 1, line: 1, quote: "精确原文" }],
        reason: "保存真实输出引用；适用性仍未知",
      };
  return {
    command_id: "67676767-6767-4676-8676-676767676767",
    idempotency_key: "synthetic-wave16-original-key",
    product_id: product, expected_revision: 1, operation, payload,
    source_read_set: [{ artifact_id: artifact, expected_revision: 1 }],
  };
}

function assertForwarded(h: ReturnType<typeof harness>, body: string | undefined) {
  assert.equal(h.calls.length, 1);
  assert.deepEqual(h.timeouts, [body === undefined ? 600000 : 180000]);
  assert.equal(h.calls[0].init.body, body);
  assert.equal(h.calls[0].init.cache, "no-store");
  assert.equal(h.calls[0].init.redirect, "error");
  assert.equal((h.calls[0].init as RequestInit & { dispatcher?: unknown }).dispatcher, body === undefined ? h.dispatcher : undefined);
  assert.equal(new Headers(h.calls[0].init.headers).get("authorization"),
    "Bearer synthetic-test-session");
}

test("单Issue列表需要issue_id，当前版和指定正整数历史版原样转发", async () => {
  for (const query of [
    `issue_id=${issue}`, `revision=1&issue_id=${issue.toUpperCase()}`,
    `issue_id=${issue}&revision=2147483647`,
  ]) {
    const h = harness();
    const { response, reads } = await h.send(endpoint, { query, origin: null });
    assert.equal(response.status, 200);
    assert.equal(reads, 0);
    assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${endpoint}?${query}`);
    assertForwarded(h, undefined);
    assert.equal(response.headers.get("cache-control"), "no-store");
    assert.equal(response.headers.get("x-content-type-options"), "nosniff");
  }
});

test("列表拒缺Issue、无效UUID、重复未知query和非有界正整数revision", async () => {
  for (const query of [
    "", "revision=1", "issue_id=", `issue_id=${"-".repeat(36)}`,
    `issue_id=${issue}&issue_id=${issue}`, `issue_id=${issue}&revision=1&revision=1`,
    `issue_id=${issue}&build_id=${product}`, `issue_id=${issue}&authority=true`,
    ...["", "0", "-1", "1.5", "1e2", "01", "%201", "2147483648", "9007199254740992"].map(
      revision => `issue_id=${issue}&revision=${revision}`,
    ),
  ]) {
    const h = harness();
    const { response, reads } = await h.send(endpoint, { query });
    assert.equal(response.status, 422, query);
    assert.equal(reads, 0);
    assert.equal(h.calls.length, 0);
    assert.deepEqual(h.timeouts, []);
  }
});

test("三个操作的Product/Issue/Artifact版本允许int32上限，超过上限不转发", async () => {
  for (const operation of operations) {
    const original = command(operation);
    const payload = original.payload as Record<string, unknown>;
    const upper = {
      ...original, expected_revision: 2147483647,
      payload: { ...payload, expected_issue_revision: 2147483647 },
      source_read_set: [{ artifact_id: artifact, expected_revision: 2147483647 }],
    };
    const body = JSON.stringify(upper);
    const h = harness();
    const accepted = await h.send(`${endpoint}/inputs`, { method: "POST", body });
    assert.equal(accepted.response.status, 200);
    assert.equal(accepted.reads, 1);
    assertForwarded(h, body);
    for (const revision of [2147483648, 9007199254740992]) {
      for (const value of [
        { ...upper, expected_revision: revision },
        { ...upper, payload: { ...upper.payload, expected_issue_revision: revision } },
        { ...upper, source_read_set: [{ artifact_id: artifact, expected_revision: revision }] },
      ]) {
        const rejected = harness();
        const result = await rejected.send(`${endpoint}/inputs`, {
          method: "POST", body: JSON.stringify(value),
        });
        assert.equal(result.response.status, 422);
        assert.equal(result.reads, 1);
        assert.equal(rejected.calls.length, 0);
        assert.deepEqual(rejected.timeouts, []);
      }
    }
  }
});

test("列表/inputs方法严格分离，inputs拒绝一切query且不读正文", async () => {
  for (const [path, method, allow] of [
    [endpoint, "POST", "GET"], [`${endpoint}/inputs`, "GET", "POST"],
  ] as const) {
    const h = harness();
    const { response, reads } = await h.send(path, {
      method, query: method === "POST" ? `issue_id=${issue}` : "",
      body: method === "POST" ? "{}" : undefined,
    });
    assert.equal(response.status, 405);
    assert.equal(response.headers.get("allow"), allow);
    assert.equal(reads, 0);
    assert.equal(h.calls.length, 0);
  }
  for (const query of [`issue_id=${issue}`, "revision=1", "unknown=true"]) {
    const h = harness();
    const { response, reads } = await h.send(`${endpoint}/inputs`, {
      method: "POST", query, body: JSON.stringify(command(operations[0])),
    });
    assert.equal(response.status, 422);
    assert.equal(reads, 0);
    assert.equal(h.calls.length, 0);
  }
});

test("新增家族只开放真实单Issue读与inputs，产品须为完整UUID", async () => {
  for (const path of [
    "v1/products/------------------------------------/quality-followup",
    `v1/products/${product.slice(0, -1)}g/quality-followup`,
    `${endpoint}/candidates`, `${endpoint}/classify`, `${endpoint}/inputs/extra`,
    `${endpoint}/effectiveness`, `${endpoint}/close`,
  ]) {
    const h = harness();
    const { response, reads } = await h.send(path, { query: `issue_id=${issue}` });
    assert.equal(response.status, 404, path);
    assert.equal(reads, 0);
    assert.equal(h.calls.length, 0);
  }
});

for (const operation of operations) {
  test(`${operation} inputs转发完整Command原正文一次，保持私有token与原值字符串`, async () => {
    const value = command(operation);
    const payload = value.payload as Record<string, unknown>;
    const proofField = operation === operations[0] ? "approval_token" : "confirmation_token";
    value.payload = { ...payload, [proofField]: "synthetic-exact-proof-value" };
    const body = ` \n${JSON.stringify(value, null, 2)}\n `;
    const h = harness();
    const { response, reads } = await h.send(`${endpoint}/inputs`, { method: "POST", body });
    assert.equal(response.status, 200);
    assert.equal(reads, 1);
    assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${endpoint}/inputs`);
    assertForwarded(h, body);
  });

  test(`${operation} inputs必须同产品且Command/Issue/读集严格成形`, async () => {
    const original = command(operation);
    const without = (key: string) => Object.fromEntries(
      Object.entries(original).filter(([name]) => name !== key),
    );
    const mutations: Record<string, unknown>[] = [
      ...Object.keys(original).map(without),
      { ...original, command_id: "invalid-command" },
      { ...original, idempotency_key: "short" },
      { ...original, idempotency_key: "x".repeat(161) },
      { ...original, product_id: otherProduct },
      { ...original, product_id: product + " " },
      { ...original, expected_revision: 0 },
      { ...original, expected_revision: true },
      { ...original, expected_revision: "1" },
      { ...original, expected_revision: 1.5 },
      { ...original, expected_revision: 2147483648 },
      { ...original, expected_revision: 9007199254740992 },
      { ...original, payload: [] },
      { ...original, payload: null },
      { ...original, payload: {} },
      { ...original, payload: { issue_id: "not-uuid", expected_issue_revision: 4 } },
      { ...original, payload: { issue_id: issue, expected_issue_revision: 0 } },
      { ...original, payload: { issue_id: issue, expected_issue_revision: "4" } },
      { ...original, payload: { issue_id: issue, expected_issue_revision: true } },
      { ...original, payload: { issue_id: issue, expected_issue_revision: 4.5 } },
      { ...original, payload: { issue_id: issue, expected_issue_revision: 2147483648 } },
      { ...original, payload: { issue_id: issue, expected_issue_revision: 9007199254740992 } },
      { ...original, actor_id: actor },
      { ...original, authority: { qualified: true } },
      { ...original, operation: "quality.capa.effectiveness.decide" },
    ];
    for (const value of mutations) {
      const h = harness();
      const { response, reads } = await h.send(`${endpoint}/inputs`, {
        method: "POST", body: JSON.stringify(value),
      });
      assert.equal(response.status, 422, JSON.stringify(value));
      assert.equal(reads, 1);
      assert.equal(h.calls.length, 0);
      assert.deepEqual(h.timeouts, []);
    }
  });

  test(`${operation} 完整唯一fixed Artifact读集，包括超过20条，不补空读集或合并重复`, async () => {
    const reads = Array.from({ length: 21 }, (_, index) => ({
      artifact_id: `aaaaaaaa-bbbb-4ccc-8ddd-${(index + 1).toString(16).padStart(12, "0")}`,
      expected_revision: index + 1,
    }));
    for (const set of [[reads[0]], reads, [...reads, { artifact_id: "99999999-aaaa-4bbb-8ccc-dddddddddddd", expected_revision: 1 }]]) {
      const h = harness();
      const body = JSON.stringify({ ...command(operation), source_read_set: set });
      const result = await h.send(`${endpoint}/inputs`, { method: "POST", body });
      assert.equal(result.response.status, 200);
      assert.equal(result.reads, 1);
      assertForwarded(h, body);
    }
    for (const set of [
      null, {}, [],
      [reads[0], reads[0]],
      [reads[0], { ...reads[0], artifact_id: reads[0].artifact_id.toUpperCase() }],
      [reads[0], { ...reads[0], expected_revision: reads[0].expected_revision + 1 }],
      [{ artifact_id: artifact }], [{ artifact_id: artifact, expected_revision: 0 }],
      [{ artifact_id: artifact, expected_revision: "1" }],
      [{ artifact_id: artifact, expected_revision: true }],
      [{ artifact_id: artifact, expected_revision: 1.5 }],
      [{ artifact_id: artifact, expected_revision: 2147483648 }],
      [{ artifact_id: artifact, expected_revision: 9007199254740992 }],
      [{ artifact_id: "not-an-artifact", expected_revision: 1 }],
      [{ ...reads[0], approved: true }],
    ]) {
      const h = harness();
      const { response, reads: bodyReads } = await h.send(`${endpoint}/inputs`, {
        method: "POST", body: JSON.stringify({ ...command(operation), source_read_set: set }),
      });
      assert.equal(response.status, 422);
      assert.equal(bodyReads, 1);
      assert.equal(h.calls.length, 0);
    }
  });

  for (const path of ["v1/commands/preview", "v1/commands"]) {
    test(`${operation} ${path}原请求使用180秒且无补命令/重试`, async () => {
      const value = command(operation);
      const payload = value.payload as Record<string, unknown>;
      value.payload = { ...payload,
        [operation === operations[0] ? "approval_token" : "confirmation_token"]:
          "synthetic-proof-preserved-exactly",
      };
      const body = `  ${JSON.stringify(value)}\n`;
      const h = harness();
      const { response, reads } = await h.send(path, { method: "POST", body });
      assert.equal(response.status, 200);
      assert.equal(reads, 1);
      assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${scoped(path)}`);
      assertForwarded(h, body);
    });
  }
}

test("inputs拒非对象与非法JSON，共同命令非法JSON仍交领域按旧行为拒绝", async () => {
  for (const body of ["", "null", "[]", '"not-command"', "true", "1", '{"operation":']) {
    const h = harness();
    const { response, reads } = await h.send(`${endpoint}/inputs`, { method: "POST", body });
    assert.equal(response.status, 422);
    assert.equal(reads, 1);
    assert.equal(h.calls.length, 0);
  }
  const body = '{"operation":"quality.capa.actions.complete",';
  const h = harness({ response: async () => Response.json(
    { code: "VALIDATION_FAILED" }, { status: 422 },
  ) });
  const { response, reads } = await h.send("v1/commands", { method: "POST", body });
  assert.equal(response.status, 422);
  assert.equal(reads, 1);
  assert.equal(h.calls.length, 1);
  assert.equal(h.calls[0].init.body, body);
  assert.deepEqual(h.timeouts, [60000]);
});

test("payload政策/资格事实由领域拒绝，BFF不根据它们生成批准", async () => {
  const body = JSON.stringify({ ...command(operations[1]), payload: {
    issue_id: issue, expected_issue_revision: 4,
    completions: [], qualified: true, action_fulfilled: true, effective: true,
  } });
  const h = harness({ response: async () => Response.json(
    { code: "VALIDATION_FAILED", message: "未接收客户端政策事实" }, { status: 422 },
  ) });
  const { response, reads } = await h.send(`${endpoint}/inputs`, { method: "POST", body });
  assert.equal(response.status, 422);
  assert.equal(reads, 1);
  assert.equal((await response.json()).code, "VALIDATION_FAILED");
  assertForwarded(h, body);
});

test("共同命令保留JSON字面原值，BFF不会解析后再序列化或替换token", async () => {
  const value = command(operations[0]);
  const body = JSON.stringify(value).replace('"text":"合成根因提议，原文 11.0000"',
    '"text":"合成根因提议，原文 11.0000","transport_probe":9007199254740993');
  const h = harness({ response: async () => Response.json(
    { code: "VALIDATION_FAILED" }, { status: 422 },
  ) });
  const { response, reads } = await h.send("v1/commands/preview", { method: "POST", body });
  assert.equal(response.status, 422, "The domain still rejects extra payload fields");
  assert.equal(reads, 1);
  assert.ok(body.includes("9007199254740993"));
  assertForwarded(h, body);
});

test("产品UUID可不同大小写但跨产品的inputs不转发", async () => {
  const h = harness();
  const body = JSON.stringify({ ...command(operations[0]), product_id: product.toUpperCase() });
  const { response } = await h.send(endpoint.replace(product, product.toUpperCase()) + "/inputs", {
    method: "POST", body,
  });
  assert.equal(response.status, 200);
  assertForwarded(h, body);
});

test("无会话/无服务配置不读取正文，401和配置失能不重试", async () => {
  for (const [configuration, status] of [[{ token: null }, 401], [{ api: null }, 503]] as const) {
    const h = harness(configuration);
    const { response, reads } = await h.send(`${endpoint}/inputs`, {
      method: "POST", body: JSON.stringify(command(operations[0])),
    });
    assert.equal(response.status, status);
    assert.equal(reads, 0);
    assert.equal(h.calls.length, 0);
    assert.deepEqual(h.timeouts, []);
  }
});

test("全部新写入口使用真实同源guard，拒绝时无body/后端IO", async () => {
  for (const path of [`${endpoint}/inputs`, "v1/commands/preview", "v1/commands"]) {
    for (const origin of [null, "http://other.invalid", "https://localhost:3000"]) {
      const h = harness();
      const { response, reads } = await h.send(path, {
        method: "POST", origin, body: JSON.stringify(command(operations[0])),
      });
      assert.equal(response.status, 403);
      assert.equal(reads, 0);
      assert.equal(h.calls.length, 0);
    }
  }
});

test("后端401/403/409/422/503领域错误完整保留，不自行恢复或再确认", async () => {
  for (const status of [401, 403, 409, 422, 503]) {
    const payload = { code: "EXACT_DOMAIN_GUARD", message: "需要当前资格或来源重核", status };
    const h = harness({ response: async () => Response.json(payload, { status }) });
    const body = JSON.stringify(command(operations[2]));
    const { response, reads } = await h.send(`${endpoint}/inputs`, { method: "POST", body });
    assert.equal(response.status, status);
    assert.deepEqual(await response.json(), payload);
    assert.equal(reads, 1);
    assertForwarded(h, body);
  }
});

test("未知写结果只回RESULT_UNKNOWN，保留原命令且一次fetch无隐藏重试", async () => {
  for (const path of [`${endpoint}/inputs`, "v1/commands/preview", "v1/commands"]) {
    const h = harness({ response: async () => { throw new Error("private synthetic IO detail"); } });
    const body = JSON.stringify(command(operations[1]));
    const { response, reads } = await h.send(path, { method: "POST", body });
    assert.equal(response.status, 503);
    const value = await response.json();
    assert.equal(value.code, "EXTERNAL_OUTCOME_UNKNOWN");
    assert.equal(JSON.stringify(value).includes("private"), false);
    assert.equal(reads, 1);
    assertForwarded(h, body);
  }
});

test("GET失败只读失能，显式重新读取才发下一次fetch", async () => {
  const h = harness({ response: async () => { throw new Error("private read detail"); } });
  const first = await h.send(endpoint, { query: `issue_id=${issue}` });
  assert.equal(first.response.status, 503);
  assert.equal((await first.response.json()).code, "SOURCE_UNAVAILABLE");
  assert.equal(first.reads, 0);
  assert.equal(h.calls.length, 1);
  const second = await h.send(endpoint, { query: `issue_id=${issue}` });
  assert.equal(second.response.status, 503);
  assert.equal(h.calls.length, 2);
});

test("正文读取或回包流失败不重发不重建审批材料", async () => {
  const body = JSON.stringify(command(operations[2]));
  const unread = harness();
  const failed = await unread.send(`${endpoint}/inputs`, {
    method: "POST", body, textFailure: true,
  });
  assert.equal(failed.response.status, 503);
  assert.equal((await failed.response.json()).code, "EXTERNAL_OUTCOME_UNKNOWN");
  assert.equal(failed.reads, 1);
  assert.equal(unread.calls.length, 0);
  const stream = harness({ response: async () => new Response(new ReadableStream({
    start(controller) { controller.error(new Error("synthetic lost response")); },
  })) });
  const lost = await stream.send("v1/commands", { method: "POST", body });
  assert.equal(lost.response.status, 503);
  assert.equal((await lost.response.json()).code, "EXTERNAL_OUTCOME_UNKNOWN");
  assert.equal(lost.reads, 1);
  assertForwarded(stream, body);
});
