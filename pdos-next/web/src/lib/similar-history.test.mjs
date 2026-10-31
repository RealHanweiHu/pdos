import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import { runInNewContext } from "node:vm";

const web = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript");
function load(relative, require = dependency, extras = {}) {
  const mod = { exports: {} };
  runInNewContext(ts.transpileModule(readFileSync(path.join(web, "src", relative), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText,
    { module: mod, exports: mod.exports, require, Response, URL, URLSearchParams, AbortSignal, ...extras });
  return mod.exports;
}
const values = load("lib/similar-history.ts"), origin = load("lib/request-origin.ts");
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), issueId: id(3) };
const feedback = () => ({ version_id: id(4), candidate_kind: "issue", candidate_source_id: id(5), candidate_revision: 2, action: "not_relevant", request_key: id(6) });

function harness(options = {}) {
  const calls = [];
  const proxy = load("lib/similar-history-proxy.ts", name => name === "./similar-history" ? values : name === "./request-origin" ? origin : name === "next/headers" ? { cookies: async () => ({ get: key => { assert.equal(key, "pdos-next-session"); return options.session === false ? undefined : { value: "synthetic-session" }; } }) } : dependency(name), {
    process: { env: { PDOS_NEXT_API_URL: options.configured === false ? undefined : "http://synthetic-api.invalid" } },
    fetch: async (url, init) => {
      calls.push({ url, init }); if (options.failure) throw Error("synthetic transport failure");
      return Response.json(options.body ?? { items: [] }, { status: options.status ?? 200, headers: { "Set-Cookie": "upstream-private=discard", "Cache-Control": "public", "Location": "https://other.invalid/", "X-Private": "discard" } });
    },
  });
  return { calls, send({ query = `version_id=${id(4)}`, body, raw, origin = "http://localhost:3000", contentType = "application/json", params = scope } = {}) {
    const writing = body !== undefined || raw !== undefined;
    const request = new Request(`http://localhost:3000/api/v1/similar-history${query ? `?${query}` : ""}`, { method: writing ? "POST" : "GET", headers: { origin, host: "localhost:3000", "Content-Type": contentType, Authorization: "Bearer caller-forgery", "X-Principal-ID": "caller-forgery" }, body: writing ? raw ?? JSON.stringify(body) : undefined });
    Object.defineProperty(request, "nextUrl", { value: new URL(request.url) });
    return options.suggestions ? proxy.similarHistorySuggestionsProxy(request, Promise.resolve(params))
      : proxy.similarHistoryProxy(request, Promise.resolve(params), writing, options.kind ?? "issue");
  } };
}

test("fixed-version read forwards server session only and does not expose upstream private headers", async () => {
  const h = harness(), response = await h.send();
  assert.equal(response.status, 200); assert.equal(response.headers.get("cache-control"), "no-store");
  for (const header of ["Set-Cookie", "Location", "X-Private"]) assert.equal(response.headers.get(header), null);
  assert.equal(h.calls.length, 1);
  const { url, init } = h.calls[0];
  assert.equal(url, `http://synthetic-api.invalid/v1/categories/${id(1)}/products/${id(2)}/quality-issues/${id(3)}/similar-history?version_id=${id(4)}`);
  assert.equal(init.method, "GET"); assert.equal(init.body, undefined); assert.equal(init.redirect, "error"); assert.equal(init.cache, "no-store");
  assert.deepEqual(Object.keys(init.headers), ["Authorization"]); assert.equal(init.headers.Authorization, "Bearer synthetic-session");
});

test("read rejects guessed scope, duplicate fixed version and viewer overrides before networking", async () => {
  const h = harness();
  for (const query of ["", "version_id=latest", `version_id=${id(4)}&version_id=${id(4)}`, ...["tenant_id", "viewer_id", "requester_id", "query", "limit", "project_id"].map(key => `version_id=${id(4)}&${key}=forged`)]) assert.equal((await h.send({ query })).status, 422, query);
  assert.equal((await h.send({ params: { ...scope, issueId: "not-an-issue-id" } })).status, 422);
  assert.equal(h.calls.length, 0);
});

test("feedback is a bounded explicit append and never forwards viewer, text or alternate commands", async () => {
  const h = harness(), body = feedback();
  assert.equal((await h.send({ query: "", body })).status, 200);
  assert.equal(h.calls[0].init.method, "POST"); assert.deepEqual(JSON.parse(h.calls[0].init.body), body);
  for (const bad of [
    { ...body, tenant_id: id(7) }, { ...body, viewer_id: id(7) }, { ...body, query: "private query" }, { ...body, text: "private explanation" },
    { ...body, action: "merge" }, { ...body, candidate_kind: "document" }, { ...body, candidate_revision: "2" }, { ...body, candidate_revision: 0 }, { ...body, candidate_revision: 2.5 },
    { ...body, candidate_revision: 2147483648 }, { ...body, request_key: "arbitrary" },
  ]) assert.equal((await h.send({ query: "", body: bad })).status, 422);
  assert.equal((await h.send({ query: "", body, origin: "http://other.invalid" })).status, 403);
  assert.equal((await h.send({ query: "", body, contentType: "text/plain" })).status, 422);
  assert.equal((await h.send({ query: "", raw: "[invalid" })).status, 422);
  assert.equal((await h.send({ query: "", raw: "x".repeat(4097) })).status, 422);
  assert.equal((await h.send({ query: "viewer_id=forged", body })).status, 422);
  assert.equal(h.calls.length, 1);
});

test("missing session and unavailable transport remain explicit; original stale outcomes are preserved", async () => {
  for (const [options, status, calls] of [[{ session: false }, 401, 0], [{ configured: false }, 503, 0], [{ failure: true }, 503, 1]]) {
    const h = harness(options); assert.equal((await h.send()).status, status); assert.equal(h.calls.length, calls);
  }
  for (const status of [403, 404, 409, 503]) {
    const body = { code: "SOURCE_STALE", message: "re-read fixed source" }, h = harness({ status, body });
    const response = await h.send({ query: "", body: feedback() }); assert.equal(response.status, status); assert.deepEqual(await response.json(), body); assert.equal(h.calls.length, 1);
  }
});

test("static BFF routes expose GET for reads and POST for explicit feedback alone", async () => {
  const request = {}, params = Promise.resolve(scope), calls = [];
  const require = name => { assert.equal(name, "@/lib/similar-history-proxy"); return { similarHistoryProxy: (...args) => { calls.push(args); return "handled"; } }; };
  const base = "app/api/v1/categories/[categoryId]/products/[productId]/quality-issues/[issueId]/similar-history";
  const reading = load(`${base}/route.ts`, require), writing = load(`${base}/feedback/route.ts`, require);
  assert.deepEqual(Object.keys(reading), ["GET"]); assert.deepEqual(Object.keys(writing), ["POST"]);
  assert.equal(await reading.GET(request, { params }), "handled"); assert.equal(await writing.POST(request, { params }), "handled");
  assert.equal(calls[0][0], request); assert.equal(calls[0][1], params); assert.equal(calls[1][2], true);
});

test("Pai prefill is a natural comparison request while metadata retains both fixed objects", () => {
  const { similarHistoryMaterial } = load("components/similar-history-pai.tsx");
  const anchor = { issue_id: id(3), version_id: id(4), revision: 7, title: "当前接口漏气", category_id: id(1), product_id: id(2), project_id: id(8) };
  const candidate = { kind: "change", object_id: id(9), source_id: id(10), source_revision: 3, title: "历史变更措施" };
  const material = similarHistoryMaterial({ anchor, candidate }, id(11));
  assert.equal(material.id, anchor.issue_id); assert.equal(material.kind, "quality_issue"); assert.equal(material.version, 7); assert.equal(material.request.id, id(11));
  for (const value of [anchor.title, candidate.title, "v7", "v3", "案例表", "差异", "可参考措施", "缺少的信息"]) assert.ok(material.request.prompt.includes(value));
  for (const value of [anchor.issue_id, anchor.version_id, candidate.object_id, candidate.source_id, "服务器", "权限", "固定版本", "待重读", "重复", "已验证"]) assert.ok(!material.request.prompt.includes(value));
  assert.ok(material.request.prompt.length < 120);
  assert.deepEqual(JSON.parse(JSON.stringify(material.draft)), { selection_kind: "unverified_object_metadata", current: { kind: "issue", object_id: id(3), version_id: id(4), revision: 7 }, candidate: { kind: "change", object_id: id(9), version_id: id(10), revision: 3 } });
  assert.equal(material.sources, undefined); assert.equal(material.run_id, undefined);
});

test("change BFF uses fixed native identities, preserves explicit feedback and rejects merging", async () => {
  const h = harness({ kind: "change" }), params = { categoryId: id(1), productId: id(2), changeId: id(3) };
  assert.equal((await h.send({ params })).status, 200);
  assert.equal(h.calls[0].url, `http://synthetic-api.invalid/v1/categories/${id(1)}/products/${id(2)}/change-execution/${id(3)}/similar-history?version_id=${id(4)}`);
  assert.equal((await h.send({ params, query: "", body: feedback() })).status, 200);
  assert.ok(h.calls[1].url.endsWith(`/change-execution/${id(3)}/similar-history/feedback`));
  assert.equal((await h.send({ params, query: "", body: { ...feedback(), action: "merge_prepared" } })).status, 422);
  assert.equal(h.calls.length, 2);
});

test("title BFF accepts only bounded title and real selectors; no alternate identity or body is forwarded", async () => {
  const h = harness({ suggestions: true });
  const query = new URLSearchParams({ kind: "change", title: "  接口漏气  ", project_id: id(8) }).toString();
  assert.equal((await h.send({ query })).status, 200);
  const request = h.calls[0], url = new URL(request.url);
  assert.ok(url.pathname.endsWith(`/products/${id(2)}/similar-history`));
  assert.equal(url.searchParams.get("title"), "接口漏气"); assert.equal(url.searchParams.get("project_id"), id(8));
  assert.equal(request.init.method, "GET"); assert.equal(request.init.body, undefined);
  assert.deepEqual(Object.keys(request.init.headers), ["Authorization"]);
  for (const bad of ["", "kind=issue&title=", "kind=issue&title=%20", "kind=artifact&title=x", "kind=issue&title=x&title=y", "kind=issue&title=x&viewer_id=forged", "kind=issue&title=x&project_id=invalid", `kind=issue&title=${"x".repeat(241)}`, "kind=issue&title=x&version_id=latest"])
    assert.equal((await h.send({ query: bad })).status, 422, bad);
  assert.equal(h.calls.length, 1);
  assert.equal((await h.send({ query: new URLSearchParams({ kind: "issue", title: "🙂".repeat(240) }).toString() })).status, 200);
});

test("completion routes expose saved Change feedback and title GET only", async () => {
  const calls = [], params = Promise.resolve({ categoryId: id(1), productId: id(2), changeId: id(3) }), request = {};
  const require = name => { assert.equal(name, "@/lib/similar-history-proxy"); return { similarHistoryProxy: (...args) => calls.push(args), similarHistorySuggestionsProxy: (...args) => calls.push(args) }; };
  const base = "app/api/v1/categories/[categoryId]/products/[productId]";
  const reading = load(`${base}/change-execution/[changeId]/similar-history/route.ts`, require);
  const writing = load(`${base}/change-execution/[changeId]/similar-history/feedback/route.ts`, require);
  const title = load(`${base}/similar-history/route.ts`, require);
  assert.deepEqual(Object.keys(reading), ["GET"]); assert.deepEqual(Object.keys(writing), ["POST"]); assert.deepEqual(Object.keys(title), ["GET"]);
  await reading.GET(request, { params }); await writing.POST(request, { params }); await title.GET(request, { params });
  assert.deepEqual(calls.map(args => args.slice(2)), [[false, "change"], [true, "change"], []]);
});

test("Change Pai prefill preserves the actual selected pair without pretending it is a quality issue", () => {
  const { similarHistoryMaterial } = load("components/similar-history-pai.tsx");
  const anchor = { kind: "change", change_id: id(3), version_id: id(4), revision: 2, title: "当前变更", category_id: id(1), product_id: id(2), project_id: id(8) };
  const candidate = { kind: "issue", object_id: id(9), source_id: id(10), source_revision: 3, title: "历史问题" };
  const material = similarHistoryMaterial({ anchor, candidate }, id(11));
  assert.equal(material.kind, "change_request"); assert.equal(material.id, anchor.change_id); assert.equal(material.version, 2);
  assert.equal(material.draft.current.kind, "change"); assert.equal(material.draft.current.version_id, anchor.version_id);
  assert.equal(material.draft.selection_kind, "unverified_object_metadata"); assert.equal(material.sources, undefined); assert.equal(material.run_id, undefined);
  assert.ok(material.request.prompt.includes("案例表")); assert.ok(!material.request.prompt.includes(anchor.change_id));
});
