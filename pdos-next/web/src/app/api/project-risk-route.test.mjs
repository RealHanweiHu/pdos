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
const root = `${product}/project-work`, risks = `${root}/risks`, inputs = `${risks}/inputs`;
const command = () => ({
  category_id: id(1), product_id: id(2), operation: "work.risk.followup.record",
  command_id: id(3), idempotency_key: "original-risk-followup-key", expected_revision: 4,
  source_read_set: [{ artifact_id: id(5), expected_revision: 2 }],
  payload: {
    project_id: id(4), risk: { id: id(6), decision_id: id(7) }, current: null,
    action: "close", summary: "自有合成材料已核对，仅结束内部风险跟进。", reason: "登记本次跟进结果。",
    sources: [{ kind: "artifact", id: id(5), revision: 2, position: `line:1;quote_sha256:${"a".repeat(64)}` }],
  },
});

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
      if (name === "next/headers") return { cookies: async () => ({ get: () => loggedIn ? { value: "synthetic-risk-session" } : undefined }) };
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

test("risk reads preserve one actual project and inputs preserve the original command", async () => {
  const h = harness(), body = command();
  const read = await h.send(`${risks}?project_id=${id(4)}`);
  assert.equal(read.status, 200);
  assert.equal((await h.send(inputs, { method: "POST", body })).status, 200);
  assert.equal(h.calls.length, 2);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/${risks}?project_id=${id(4)}`);
  assert.equal(h.calls[1].url, `http://synthetic-api.invalid/${inputs}`);
  assert.deepEqual(JSON.parse(h.calls[1].init.body), body);
  assert.equal(h.calls[1].init.headers.Authorization, "Bearer synthetic-risk-session");
  assert.equal(h.calls[0].init.cache, "no-store");
  assert.equal(read.headers.get("Cache-Control"), "no-store");
});

test("risk read rejects absent duplicate invalid or additional project selectors", async () => {
  for (const suffix of ["", "?project_id=", "?project_id=wrong", `?project_id=${id(4)}&project_id=${id(4)}`, `?project_id=${id(4)}&project_id=${id(8)}`, `?project_id=${id(4)}&owner_id=${id(9)}`, `?project_id=${id(4)}&category_id=${id(9)}`, `?project_id=${id(4)}&product_id=${id(9)}`, `?project_id=${id(4)}&page_size=20`, `?project_id=${id(4)}&cursor=opaque`]) {
    const h = harness();
    assert.equal((await h.send(risks + suffix)).status, 422, suffix);
    assert.equal(h.calls.length, 0, suffix);
  }
});

test("risk routes keep read and material methods separate and inputs have no query override", async () => {
  for (const [path, options, allow] of [[risks, { method: "POST", body: command() }, "GET"], [`${risks}?project_id=${id(4)}`, { method: "DELETE" }, "GET"], [inputs, {}, "POST"], [inputs, { method: "PUT", body: command() }, "POST"]]) {
    const h = harness(), response = await h.send(path, options);
    assert.equal(response.status, 405);
    assert.equal(response.headers.get("Allow"), allow);
    assert.equal(h.calls.length, 0);
  }
  for (const query of [`?project_id=${id(4)}`, "?allow_override=true"]) {
    const h = harness();
    assert.equal((await h.send(inputs + query, { method: "POST", body: command() })).status, 422);
    assert.equal(h.calls.length, 0);
  }
});

test("risk inputs accept only risk follow-up and refuse other material entry points", async () => {
  for (const operation of ["work.task.create", "work.commitment.review", "work.external_wait.record", "risk.approve"]) {
    const h = harness();
    assert.equal((await h.send(inputs, { method: "POST", body: { ...command(), operation } })).status, 422);
    assert.equal(h.calls.length, 0);
  }
  for (const path of [`${root}/inputs`, `${root}/fulfillment/inputs`, `${root}/external-waits/inputs`]) {
    const h = harness();
    assert.equal((await h.send(path, { method: "POST", body: command() })).status, 422);
    assert.equal(h.calls.length, 0);
  }
});

test("risk material cannot change URL category or product or inject another authority", async () => {
  const original = command();
  for (const body of [{ ...original, category_id: id(8) }, { ...original, product_id: id(8) }, { ...original, payload: { ...original.payload, actor_id: id(9) } }, { ...original, payload: { ...original.payload, owner_id: id(9) } }, { ...original, payload: { ...original.payload, visibility: "category" } }]) {
    const h = harness();
    assert.equal((await h.send(inputs, { method: "POST", body })).status, 422);
    assert.equal(h.calls.length, 0);
  }
});

test("risk material uses the current session and requires the request origin", async () => {
  for (const origin of [null, "http://elsewhere.invalid", "https://localhost:3000"]) {
    const h = harness();
    assert.equal((await h.send(inputs, { method: "POST", body: command(), origin })).status, 403);
    assert.equal(h.calls.length, 0);
  }
  const h = harness({ loggedIn: false });
  assert.equal((await h.send(`${risks}?project_id=${id(4)}`)).status, 401);
  assert.equal((await h.send(inputs, { method: "POST", body: command() })).status, 401);
  assert.equal(h.calls.length, 0);
});
