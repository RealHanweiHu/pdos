import test from "node:test";
import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createServer, type ServerResponse } from "node:http";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import { Agent, type Dispatcher } from "undici";
import { ModuleKind, ScriptTarget, transpileModule } from "typescript";

const source = transpileModule(
  readFileSync(resolve("src/lib/candidate-transport.ts"), "utf8"),
  { compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 } },
).outputText;
type Transport = { candidateTransportOptions(candidate: boolean): { dispatcher?: Dispatcher } };

function actualTransport(agent: typeof Agent): Transport {
  const helperModule = { exports: {} };
  runInNewContext(source, {
    module: helperModule, exports: helperModule.exports,
    require: (name: string) => {
      assert.equal(name, "undici");
      return { Agent: agent };
    },
  });
  return helperModule.exports as Transport;
}

test("实际候选helper仅opt-in固定600秒Agent，不修改全局dispatcher", () => {
  const constructed: { options: Agent.Options }[] = [];
  class ObservedAgent {
    readonly options: Agent.Options;
    constructor(options: Agent.Options) { this.options = options; constructed.push(this); }
  }
  const helper = actualTransport(ObservedAgent as unknown as typeof Agent);
  assert.equal(constructed.length, 1);
  assert.equal(constructed[0].options.headersTimeout, 600000);
  assert.equal(constructed[0].options.bodyTimeout, 600000);
  assert.equal(Object.hasOwn(helper.candidateTransportOptions(false), "dispatcher"), false);
  assert.equal(helper.candidateTransportOptions(true).dispatcher, constructed[0]);
  assert.equal(helper.candidateTransportOptions(true).dispatcher,
    helper.candidateTransportOptions(true).dispatcher);
});

// This isolated ephemeral server serves synthetic bytes only, never a PDOS endpoint.
async function syntheticServer(mode: "headers" | "body", run: (
  url: string, requests: () => number,
) => Promise<void>) {
  let requests = 0;
  const timers = new Set<ReturnType<typeof setTimeout>>();
  const responses = new Set<ServerResponse>();
  const server = createServer((_request, response) => {
    requests += 1;
    responses.add(response);
    response.on("close", () => responses.delete(response));
    const timer = setTimeout(() => {
      timers.delete(timer);
      if (!response.destroyed) response.end(mode === "headers" ? "synthetic" : "-body");
    }, 1500);
    timers.add(timer);
    if (mode === "body") {
      response.writeHead(200, { "Content-Type": "text/plain" });
      response.write("synthetic");
    }
  });
  await new Promise<void>((resolveListen, reject) => {
    server.once("error", reject);
    server.listen(0, "127.0.0.1", resolveListen);
  });
  const address = server.address();
  assert.ok(address && typeof address !== "string");
  try {
    await run(`http://127.0.0.1:${address.port}/synthetic`, () => requests);
  } finally {
    for (const timer of timers) clearTimeout(timer);
    for (const response of responses) response.destroy();
    server.closeAllConnections();
    await new Promise<void>((resolveClose, reject) => {
      server.close(error => error ? reject(error) : resolveClose());
    });
  }
}

function timeoutCode(error: unknown): string | undefined {
  if (!(error instanceof Error)) return undefined;
  const cause = error.cause as { code?: string } | undefined;
  return cause?.code;
}

for (const mode of ["headers", "body"] as const) {
  test(`实际Node fetch ${mode}独立计时可先于Abort到期，候选Agent允许短合成等待`, async () => {
    const narrow = new Agent({
      headersTimeout: mode === "headers" ? 100 : 5000,
      bodyTimeout: mode === "body" ? 100 : 5000,
    });
    const helper = actualTransport(Agent);
    const candidate = helper.candidateTransportOptions(true);
    assert.ok(candidate.dispatcher);
    try {
      await syntheticServer(mode, async (url, requests) => {
        const signal = AbortSignal.timeout(5000);
        await assert.rejects(async () => {
          const response = await fetch(url, { ...{ dispatcher: narrow }, signal });
          await response.arrayBuffer();
        }, error => {
          assert.equal(signal.aborted, false, "The transport timer, not Abort, must reject");
          assert.equal(timeoutCode(error), mode === "headers"
            ? "UND_ERR_HEADERS_TIMEOUT" : "UND_ERR_BODY_TIMEOUT");
          return true;
        });
        assert.equal(requests(), 1, "No transport retry is allowed");
        const response = await fetch(url, {
          ...candidate, signal: AbortSignal.timeout(5000),
          cache: "no-store", redirect: "error",
        });
        assert.equal(response.status, 200);
        assert.equal(await response.text(), mode === "headers" ? "synthetic" : "synthetic-body");
        assert.equal(requests(), 2, "The second request is explicitly initiated by the test");
      });
    } finally {
      await narrow.destroy();
      await candidate.dispatcher.destroy();
    }
  });
}

test("候选Agent仍服从较短的整体Abort上限，一次请求无重试", async () => {
  const helper = actualTransport(Agent);
  const candidate = helper.candidateTransportOptions(true);
  assert.ok(candidate.dispatcher);
  try {
    await syntheticServer("headers", async (url, requests) => {
      await assert.rejects(fetch(url, {
        ...candidate, signal: AbortSignal.timeout(100),
      }), error => {
        assert.ok(error instanceof Error);
        assert.equal(error.name, "TimeoutError");
        return true;
      });
      assert.equal(requests(), 1);
    });
  } finally {
    await candidate.dispatcher.destroy();
  }
});
