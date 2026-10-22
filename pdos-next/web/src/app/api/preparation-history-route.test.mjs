import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { runInNewContext } from "node:vm";
import test from "node:test";
import { transpileModule, ModuleKind, ScriptTarget } from "typescript";

const compile = name => transpileModule(readFileSync(resolve(name), "utf8"), { compilerOptions: { module: ModuleKind.CommonJS, target: ScriptTarget.ES2022 } }).outputText;
const route = compile("src/app/api/[...path]/route.ts"), guard = compile("src/lib/request-origin.ts"), transport = compile("src/lib/candidate-transport.ts");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const root = `v1/categories/${id(1)}/products/${id(2)}/manufacturing-preparations`;

function harness({ loggedIn = true, unavailable = false } = {}) {
  const calls = [], originModule = { exports: {} }, transportModule = { exports: {} }, routeModule = { exports: {} };
  runInNewContext(guard, { module: originModule, exports: originModule.exports, URL });
  runInNewContext(transport, { module: transportModule, exports: transportModule.exports, require: () => ({ Agent: class {} }) });
  runInNewContext(route, {
    module: routeModule, exports: routeModule.exports, URL, URLSearchParams, Response, Headers, AbortSignal,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } },
    require: name => {
      if (name === "@/lib/request-origin") return originModule.exports;
      if (name === "@/lib/candidate-transport") return transportModule.exports;
      if (name === "next/headers") return { cookies: async () => ({ get: () => loggedIn ? { value: "synthetic-session-substitute" } : undefined }) };
      throw new Error(`Unexpected dependency: ${name}`);
    },
    fetch: async (url, init) => { calls.push({ url, init }); if (unavailable) throw new Error("synthetic transport unavailable"); return Response.json({ synthetic: true }); },
  });
  return { calls, async send(path, method = "GET") {
    const request = new Request(`http://localhost:3000/api/${path}`, { method, headers: { host: "localhost:3000", origin: "http://localhost:3000" }, ...(method === "POST" ? { body: "{}" } : {}) });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return routeModule.exports[method](request, { params: Promise.resolve({ path: path.split("?")[0].split("/") }) });
  } };
}

test("preparation history forwards the original opaque cursor and scope once without decoding", async () => {
  const h = harness(), cursor = "opaque:/+_=文档", params = new URLSearchParams({ project_id: id(3), process_id: id(4), history_cursor: cursor });
  assert.equal((await h.send(`${root}?${params}`)).status, 200); assert.equal(h.calls.length, 1);
  const url = new URL(h.calls[0].url); assert.equal(url.searchParams.get("history_cursor"), cursor); assert.equal(url.searchParams.get("project_id"), id(3)); assert.equal(url.searchParams.get("process_id"), id(4));
  assert.equal(h.calls[0].init.method, "GET"); assert.equal(h.calls[0].init.body, undefined);
});
test("preparation fixed children retain exact kind, identity and revision without a history query", async () => {
  const h = harness();
  for (const kind of ["work_instruction", "control_plan"]) assert.equal((await h.send(`${root}/${kind}/${id(5)}?revision=1`)).status, 200);
  assert.equal(h.calls.length, 2); assert.equal(new URL(h.calls[0].url).searchParams.get("revision"), "1");
});
for (const [name, query] of [
  ["no project", "history_cursor=original"],
  ["duplicate project", `project_id=${id(3)}&project_id=${id(4)}`],
  ["duplicate cursor", `project_id=${id(3)}&history_cursor=first&history_cursor=second`],
  ["empty cursor", `project_id=${id(3)}&history_cursor=`],
  ["oversized cursor", `project_id=${id(3)}&history_cursor=${"a".repeat(2001)}`],
  ["invalid process", `project_id=${id(3)}&process_id=wrong`],
  ["unknown query", `project_id=${id(3)}&page=2`],
]) test(`preparation ${name} is rejected before forwarding`, async () => {
  const h = harness(); assert.equal((await h.send(`${root}?${query}`)).status, 422); assert.equal(h.calls.length, 0);
});
test("history cursor is not accepted by a fixed version or inputs endpoint", async () => {
  const h = harness(); assert.equal((await h.send(`${root}/work_instruction/${id(5)}?revision=1&history_cursor=original`)).status, 422);
  assert.equal((await h.send(`${root}/inputs?history_cursor=original`, "POST")).status, 422); assert.equal(h.calls.length, 0);
});
test("preparation reads keep authentication and unavailable transport has no automatic retry", async () => {
  const anonymous = harness({ loggedIn: false }); assert.equal((await anonymous.send(`${root}?project_id=${id(3)}`)).status, 401); assert.equal(anonymous.calls.length, 0);
  const unavailable = harness({ unavailable: true }); assert.equal((await unavailable.send(`${root}?project_id=${id(3)}&history_cursor=original`)).status, 503); assert.equal(unavailable.calls.length, 1);
});
