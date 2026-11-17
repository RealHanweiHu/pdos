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
const category = "11111111-1111-4111-8111-111111111111", object = "22222222-2222-4222-8222-222222222222";
function harness() {
  const loaded = { exports: {} }, calls = [];
  runInNewContext(compile("app/api/[...path]/route.ts"), {
    module: loaded, exports: loaded.exports, URLSearchParams, Response, AbortSignal, Request, Headers,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } },
    require: name => {
      if (name === "next/headers") return { cookies: async () => ({ get: () => ({ value: "synthetic-session" }) }) };
      if (name === "@/lib/server/request-origin") return { sameOrigin: () => "http://synthetic-api.invalid" };
      if (name === "@/lib/server/candidate-transport") return { candidateTransportOptions: () => ({}) };
      if (name === "next/server") return { NextRequest: class {} };
      throw new Error(`unexpected module ${name}`);
    },
    fetch: async (url, init) => { calls.push({ url, init }); return Response.json({ notes: [] }); },
  });
  return { calls, async send(pathname, method = "GET", query = "", body) {
    const request = new Request(`http://localhost/api/${pathname}${query ? `?${query}` : ""}`, { method, body: body === undefined ? undefined : JSON.stringify(body), headers: { "Content-Type": "application/json" } });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return (method === "GET" ? loaded.exports.GET : loaded.exports.POST)(request, { params: Promise.resolve({ path: pathname.split("/") }) });
  } };
}

test("scope note paths are read-only, fixed to the path scope, and forwarded unchanged", async () => {
  const h = harness();
  const root = `v1/categories/${category}`;
  const reads = [
    `${root}/scope-notes/category/${category}`, `${root}/scope-notes/project/${object}`, `${root}/scope-notes/proposal/${object}/all`,
    `${root}/scope-notes/product/${object}`, `${root}/scope-note-items/${object}`, `${root}/scope-recent/project/${object}`, `${root}/scope-note-sources/project/${object}`,
  ];
  for (const item of reads) {
    assert.equal((await h.send(item)).status, 200, item);
    assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/${item}`);
  }
  const forwarded = h.calls.length;
  // Writes never go through these paths: they are common commands with one confirmation.
  assert.equal((await h.send(reads[0], "POST", "", { statement: "直接写" })).status, 405);
  assert.equal((await h.send(reads[0], "GET", `owner_id=${object}`)).status, 422);
  for (const bad of [`${root}/scope-notes/session/${object}`, `${root}/scope-notes/project/${object}/all/extra`, `${root}/scope-note-items/${object}/history`, `${root}/scope-notes/project/not-an-id`, `v1/personal/scope-notes/category/${category}`]) {
    assert.equal((await h.send(bad)).status, 404, bad);
  }
  assert.equal(h.calls.length, forwarded);
});
