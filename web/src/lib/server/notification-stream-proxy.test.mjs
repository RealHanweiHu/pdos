import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ts = createRequire(path.join(web, "package.json"))("typescript");
const compile = relative => ts.transpileModule(readFileSync(path.join(web, "src", relative), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const thread = "12345678-1234-4123-8123-123456789abc";

function harness(options = {}) {
  const loaded = { exports: {} }, calls = [];
  runInNewContext(compile("lib/server/notification-stream-proxy.ts"), {
    module: loaded, exports: loaded.exports, URLSearchParams, Response, AbortSignal,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } },
    require: name => { assert.equal(name, "next/headers"); return { cookies: async () => ({ get: () => options.session === false ? undefined : { value: "synthetic-session" } }) }; },
    fetch: async (url, init) => {
      calls.push({ url, init });
      if (options.upstream === "json") return Response.json({ code: "UNAUTHENTICATED" }, { status: 401 });
      const body = new ReadableStream({ start(controller) { controller.enqueue(new TextEncoder().encode("event: ready\ndata: {}\n\n")); controller.close(); } });
      return new Response(body, { status: 200, headers: { "Content-Type": "text/event-stream", "Set-Cookie": "must-not-forward" } });
    },
  });
  return { calls, send(query = "", headers = {}) {
    const request = new Request(`http://localhost/api/v1/personal/notifications/stream${query ? `?${query}` : ""}`, { headers });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return loaded.exports.notificationStream(request);
  } };
}

test("the stream passes through unbuffered with only the session as identity", async () => {
  const h = harness();
  const response = await h.send(`threads=${thread}&since=4.0`, { "Last-Event-ID": "5.1", Authorization: "Bearer caller-controlled" });
  assert.equal(response.status, 200);
  assert.equal(response.headers.get("Content-Type"), "text/event-stream; charset=utf-8");
  assert.equal(response.headers.get("Cache-Control"), "no-store");
  assert.equal(response.headers.get("Set-Cookie"), null);
  assert.equal(await response.text(), "event: ready\ndata: {}\n\n");
  const { url, init } = h.calls[0];
  assert.equal(url, `http://synthetic-api.invalid/v1/personal/notifications/stream?threads=${thread}&since=4.0`);
  assert.equal(init.headers.Authorization, "Bearer synthetic-session");
  assert.equal(init.headers["Last-Event-ID"], "5.1");
  assert.equal(init.redirect, "error");
});

test("bad queries, a missing session and upstream refusals never become a stream", async () => {
  const h = harness();
  for (const query of ["threads=not-a-uuid", `threads=${thread}&threads=${thread}`, "since=1;drop", `recipient_id=${thread}`]) assert.equal((await h.send(query)).status, 422, query);
  assert.equal(h.calls.length, 0);
  assert.equal((await harness({ session: false }).send()).status, 401);
  const refused = await harness({ upstream: "json" }).send();
  assert.equal(refused.status, 401);
  assert.notEqual(refused.headers.get("Content-Type"), "text/event-stream; charset=utf-8");
});
