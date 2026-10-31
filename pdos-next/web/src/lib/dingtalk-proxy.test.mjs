import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const dir = path.dirname(fileURLToPath(import.meta.url)), root = path.resolve(dir, "../.."), dep = createRequire(path.join(root, "package.json")), ts = dep("typescript");
let token = "test-session-token";
const cache = new Map();
function load(filename) { if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync); if (cache.has(filename)) return cache.get(filename).exports; const loaded = new Module(filename); cache.set(filename, loaded); loaded.require = name => name === "next/headers" ? { cookies: async () => ({ get: () => token ? { value: token } : undefined }) } : name.startsWith("@/") ? load(path.join(root, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dep(name); loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename); return loaded.exports; }
const { dingtalkRequest } = load(path.join(dir, "dingtalk-proxy.ts")), id = "00000000-0000-4000-8000-000000000001";
function env(t) { const before = globalThis.fetch, base = process.env.PDOS_NEXT_API_URL; process.env.PDOS_NEXT_API_URL = "http://api.invalid"; const calls = []; globalThis.fetch = async (url, options) => { calls.push({ url, options }); return Response.json({ items: [] }); }; t.after(() => { globalThis.fetch = before; if (base === undefined) delete process.env.PDOS_NEXT_API_URL; else process.env.PDOS_NEXT_API_URL = base; token = "test-session-token"; }); return calls; }
function request(method = "GET", body, search = "", origin = "https://pdos.invalid") { return { method, nextUrl: new URL("https://pdos.invalid/api/" + search), url: "https://pdos.invalid/api/", headers: new Headers({ origin, host: "pdos.invalid" }), text: async () => JSON.stringify(body) }; }
test("authenticated metadata GET is scoped by server session, no browser owner query", async t => { const calls = env(t); const result = await dingtalkRequest(request(), "v1/personal/dingtalk/settings"); assert.equal(result.status, 200); assert.equal(calls[0].url, "http://api.invalid/v1/personal/dingtalk/settings"); assert.equal(calls[0].options.method, "GET"); assert.equal(calls[0].options.body, undefined); assert.equal(calls[0].options.redirect, "error"); const rejected = await dingtalkRequest(request("GET", undefined, "?owner_id=" + id), "v1/personal/dingtalk/settings"); assert.equal(rejected.status, 422); assert.equal(calls.length, 1); });
test("cross-origin or impersonating bind action never reaches API", async t => { const calls = env(t); const path = "v1/personal/dingtalk/bindings/begin"; assert.equal((await dingtalkRequest(request("POST", { application_id: id }, "", "https://evil.invalid"), path)).status, 403); assert.equal((await dingtalkRequest(request("POST", { application_id: id, owner_id: id }), path)).status, 422); assert.equal(calls.length, 0); });
test("reconcile forwards only original metadata query, not resend authority", async t => { const calls = env(t), p = `v1/personal/dingtalk/deliveries/${id}/reconcile`; assert.equal((await dingtalkRequest(request("POST", {}), p)).status, 200); assert.equal(calls[0].url, "http://api.invalid/" + p); assert.equal(calls[0].options.body, "{}"); assert.equal((await dingtalkRequest(request("POST", { resend: true }), p)).status, 422); assert.equal(calls.length, 1); });
test("public provider ingress, wrong method and absent session cannot use personal proxy", async t => { const calls = env(t); assert.equal((await dingtalkRequest(request("POST", {}), `v1/dingtalk/applications/${id}/events`)).status, 404); assert.equal((await dingtalkRequest(request("POST", {}), "v1/personal/dingtalk/settings")).status, 405); token = ""; assert.equal((await dingtalkRequest(request(), "v1/personal/dingtalk/settings")).status, 401); assert.equal(calls.length, 0); });
test("transport loss is unknown and one fetch, never a hidden resubmission", async t => { const calls = env(t); globalThis.fetch = async (url, options) => { calls.push({ url, options }); throw new Error("offline"); }; const value = await dingtalkRequest(request("POST", { binding_id: id, expected_epoch: 1, reason: "本人停用", request_key: id }), "v1/personal/dingtalk/bindings/revoke"); assert.equal(value.status, 503); assert.equal((await value.json()).code, "EXTERNAL_OUTCOME_UNKNOWN"); assert.equal(calls.length, 1); });
test("actual shared BFF routes personal settings through the closed DingTalk adapter", async t => {
  const calls = env(t), route = load(path.join(root, "src/app/api/[...path]/route.ts"));
  const pathValue = "v1/personal/dingtalk/settings";
  const response = await route.GET(request(), { params: Promise.resolve({ path: pathValue.split("/") }) });
  assert.equal(response.status, 200);
  assert.equal(calls.length, 1);
  assert.equal(calls[0].url, "http://api.invalid/" + pathValue);
  assert.equal(calls[0].options.redirect, "error");
});
test("shared BFF routing does not grant unknown personal channel paths or browser identity", async t => {
  const calls = env(t), route = load(path.join(root, "src/app/api/[...path]/route.ts"));
  const unknown = "v1/personal/dingtalk/forged";
  assert.equal((await route.GET(request(), { params: Promise.resolve({ path: unknown.split("/") }) })).status, 404);
  const actual = "v1/personal/dingtalk/settings";
  assert.equal((await route.GET(request("GET", undefined, "?owner_id=" + id), { params: Promise.resolve({ path: actual.split("/") }) })).status, 422);
  assert.equal(calls.length, 0);
});
