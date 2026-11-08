import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

// D56: the BFF forwards only the four GET export entries with one exact scope parameter.
const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../../..");
const ts = createRequire(path.join(web, "package.json"))("typescript");
const compile = relative => ts.transpileModule(readFileSync(path.join(web, "src", relative), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const category = "11111111-1111-4111-8111-111111111111", product = "22222222-2222-4222-8222-222222222222", id = "33333333-3333-4333-8333-333333333333";
const XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet";
function harness() {
  const loaded = { exports: {} }, calls = [];
  runInNewContext(compile("app/api/[...path]/route.ts"), {
    module: loaded, exports: loaded.exports, URLSearchParams, Response, AbortSignal, Request, Headers, URL,
    process: { env: { PDOS_NEXT_API_URL: "http://synthetic-api.invalid" } },
    require: name => {
      if (name === "next/headers") return { cookies: async () => ({ get: () => ({ value: "synthetic-session" }) }) };
      if (name === "@/lib/server/request-origin") return { sameOrigin: () => "http://synthetic-api.invalid" };
      if (name === "@/lib/server/candidate-transport") return { candidateTransportOptions: () => ({}) };
      if (name === "next/server") return { NextRequest: class {} };
      throw new Error(`unexpected module ${name}`);
    },
    fetch: async (url, init) => {
      calls.push({ url, init });
      return new Response(new Uint8Array([80, 75, 3, 4]), { status: 200, headers: { "Content-Type": XLSX, "Content-Disposition": "attachment; filename*=UTF-8''x.xlsx", "X-PDOS-Export-Id": id, "X-PDOS-Export-Rows": "4", "X-PDOS-Export-AI-Rows": "1", "X-PDOS-Export-AI-Cells": "2", "X-Other": "secret" } });
    },
  });
  return { calls, send(pathname, method = "GET", query = "") {
    const request = new Request(`http://localhost/api/${pathname}${query ? `?${query}` : ""}`, { method, body: method === "GET" ? undefined : "{}", headers: { "Content-Type": "application/json" } });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return (method === "GET" ? loaded.exports.GET : loaded.exports.POST)(request, { params: Promise.resolve({ path: pathname.split("/") }) });
  } };
}

test("export entries forward one exact scope and keep the file and its label counts", async () => {
  const h = harness(), base = `v1/categories/${category}/products/${product}/exports`;
  for (const [kind, key] of [["project", "project_id"], ["bom-diff", "bom_id"], ["test-summary", "build_id"]]) {
    const response = await h.send(`${base}/${kind}`, "GET", `${key}=${id}`);
    assert.equal(response.status, 200);
    assert.equal(h.calls.at(-1).url, `http://synthetic-api.invalid/${base}/${kind}?${key}=${id}`);
    assert.equal(response.headers.get("Content-Type"), XLSX);
    assert.equal(response.headers.get("X-PDOS-Export-AI-Rows"), "1");
    assert.equal(response.headers.get("X-Other"), null);
    assert.deepEqual([...new Uint8Array(await response.arrayBuffer())], [80, 75, 3, 4]);
  }
  assert.equal((await h.send("v1/personal/exports/my-work")).status, 200);
  assert.equal(h.calls.at(-1).url, "http://synthetic-api.invalid/v1/personal/exports/my-work");
  const forwarded = h.calls.length;
  assert.equal((await h.send(`${base}/project`)).status, 422);
  assert.equal((await h.send(`${base}/project`, "GET", `bom_id=${id}`)).status, 422);
  assert.equal((await h.send(`${base}/project`, "GET", `project_id=${id}&project_id=${id}`)).status, 422);
  assert.equal((await h.send(`${base}/project`, "GET", "project_id=not-a-uuid")).status, 422);
  assert.equal((await h.send("v1/personal/exports/my-work", "GET", `project_id=${id}`)).status, 422);
  assert.equal((await h.send(`${base}/project`, "POST", `project_id=${id}`)).status, 405);
  assert.equal((await h.send(`${base}/everything`, "GET", `project_id=${id}`)).status, 404);
  assert.equal(h.calls.length, forwarded);
});
