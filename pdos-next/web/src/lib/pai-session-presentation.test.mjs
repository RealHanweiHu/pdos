import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";
const ts = createRequire(import.meta.url)("typescript"), loaded = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./pai-session-presentation.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: loaded, exports: loaded.exports, URLSearchParams });
const { readConversations, writePresentation, recoverPresentation } = loaded.exports;
const id = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12,"0")}`;
const scope = { principalId: id(1), categoryId: id(2), proposalId: id(3) }, stamp = "2026-10-17T12:34:56.123456+00:00";
const clone = x => JSON.parse(JSON.stringify(x));
const zero = () => ({ id: null, revision: 0, title: null, pinned: false, archived: false, created_at: null });
const saved = overrides => ({ ...zero(), id: id(301), revision: 1, created_at: stamp, ...overrides });
const row = (n = 100, p = zero()) => ({ session_id: id(n), revision: 1, created_at: stamp, scope: { category_id: id(2), product_id: null, proposal_id: id(3), project_id: id(4) }, run_count: 1, presentation: p,
 latest_run: { run_id: id(n+100), goal: "不可改写原目标", status: "completed", error_code: null, created_at: stamp, continued_from_id: null, reverted: false }, matched_run: null });
const page = (items = [row()]) => ({ version: "agent-conversation-list/v1", principal_id: id(1), scope: { category_id: id(2), proposal_id: id(3) }, as_of: stamp, items, next_cursor: null });
const request = (action = "rename") => ({ sessionId: id(100), body: { action, expected_revision: 0, request_key: id(900), ...(action === "rename" ? { title: "自定义名称" } : {}) } });
const receipt = req => ({ version: "agent-session-presentation/v1", principal_id: id(1), scope: page().scope, session: { session_id: req.sessionId, ...row().scope }, presentation: { ...saved({ title: req.body.title ?? null, pinned: req.body.action === "pin", archived: req.body.action === "archive" }), action: req.body.action, request_key: req.body.request_key } });

test("project list selector is sent and checked against both envelope and each actual Session", async () => {
 const selected = { ...scope, projectId: id(4) }, raw = page(), calls = [];
 raw.scope.project_id = id(4);
 await readConversations(async path => { calls.push(path); return raw; }, selected);
 assert.equal(new URLSearchParams(calls[0].split("?")[1]).get("project_id"), id(4));
 for (const mutate of [value => value.scope.project_id = id(5), value => value.items[0].scope.project_id = id(5)]) {
  const bad = clone(raw); mutate(bad); await assert.rejects(readConversations(async () => bad, selected));
 }
 const req = request(), original = receipt(req), writeCalls = [];
 await writePresentation(async (...args) => { writeCalls.push(args); return original; }, selected, req);
 assert.ok(!writeCalls[0][0].includes("project_id"), "original write scope and request identity remain unchanged");
 original.session.project_id = id(5);
 await assert.rejects(writePresentation(async () => original, selected, req), error => error.status === 503);
});

test("managed list preserves revision-zero facts and actual project scope without enriching legacy DTOs", async () => {
 const original = page(), calls = []; const value = await readConversations(async (...args) => { calls.push(args); return original; }, scope);
 assert.equal(value, original); assert.deepEqual(clone(value.items[0].presentation), zero()); assert.equal(value.items[0].scope.project_id, id(4));
 assert.equal(calls[0][0], `v1/categories/${id(2)}/agent-conversations?view=active&page_size=20&proposal_id=${id(3)}`); assert.equal(calls[0].length, 1);
});
test("managed conversation preserves hidden goals and the real work-state timestamp only", async () => {
 const original = page(); const head = original.items[0].latest_run;
 Object.assign(head, { status: "hidden", history_hidden: true, created_at: null, recorded_at: stamp, reverted: null,
  hidden_message: "原回答已隐藏，保留你的原话。" });
 const value = await readConversations(async () => original, scope);
 assert.equal(value.items[0].latest_run.goal, "不可改写原目标");
 assert.equal(value.items[0].latest_run.created_at, null);
 for (const mutate of [x => x.created_at = stamp, x => x.reverted = false, x => x.recorded_at = "invalid", x => x.versions = {}]) {
  const bad = clone(original); mutate(bad.items[0].latest_run);
  await assert.rejects(readConversations(async () => bad, scope));
 }
});
test("title-only search has no invented matched Run, server pin ordering precedes original chronology", async () => {
 const p = page([row(50, saved({ title: "名称命中", pinned: true })), row(100)]); const value = await readConversations(async () => p, scope);
 assert.equal(value.items[0].session_id, id(50));
 const found = page([row(50, saved({ title: "名称命中" }))]); assert.equal((await readConversations(async () => found, scope, { q: "名称" })).items[0].matched_run, null);
 const reversed = page([row(100), row(50, saved({ pinned: true }))]); await assert.rejects(readConversations(async () => reversed, scope));
});
test("DTO identity, shape, archive, metadata and cursor mismatches fail closed", async () => {
 const invalid = [x => x.principal_id = id(88), x => x.scope.proposal_id = null, x => x.items[0].scope.category_id = id(88), x => delete x.items[0].scope.project_id,
  x => x.items[0].presentation.pinned = true, x => x.items[0].presentation.id = id(99), x => x.items[0].presentation.title = "伪造", x => x.items[0].presentation.created_at = stamp,
  x => x.items[0].presentation.archived = true, x => x.items[0].presentation = saved({ title: " " }), x => x.items[0].presentation = saved({ created_at: "2026-02-30T00:00:00Z" }), x => x.next_cursor = id(500), x => x.items.push(x.items[0]), x => x.items[0].result = {}];
 for (const mutate of invalid) { const p = page(); mutate(p); await assert.rejects(readConversations(async () => p, scope)); }
 const archive = page([row(100, saved({ archived: true }))]); assert.equal((await readConversations(async () => archive, scope, { view: "archived" })).items[0].presentation.archived, true);
});
test("search keeps the original historical match head and validates exact relationship", async () => {
 const p = page(); p.items[0].run_count = 2; p.items[0].matched_run = { ...p.items[0].latest_run, run_id: id(800), goal: "历史原目标", match_kind: "goal" };
 assert.equal((await readConversations(async () => p, scope, { q: "历史" })).items[0].matched_run.goal, "历史原目标");
 p.items[0].matched_run.created_at = "2026-10-18T00:00:00Z"; await assert.rejects(readConversations(async () => p, scope, { q: "历史" }));
});
test("exact write and read-only recovery bind principal, scope, session, immutable revision and original request", async () => {
 const req = request(), original = receipt(req), calls = []; const api = async (...args) => { calls.push(args); return original; };
 assert.equal(await writePresentation(api, scope, req), original); assert.equal(calls[0][1], req.body);
 assert.equal(await recoverPresentation(api, scope, req), original); assert.equal(calls[1].length, 1); assert.ok(calls[1][0].includes(`/requests/${req.body.request_key}?proposal_id=`));
 for (const mutate of [x => x.presentation.request_key = id(89), x => x.presentation.revision = 2, x => x.presentation.action = "archive", x => x.presentation.title = "当前名称", x => x.session.session_id = id(88), x => x.principal_id = id(88), x => x.scope.proposal_id = null]) {
  const value = clone(original); mutate(value); await assert.rejects(writePresentation(async () => value, scope, req), e => e.status === 503); await assert.rejects(recoverPresentation(async () => value, scope, req));
 }
});
test("invalid bodies never reach transport; reset is explicit null and transport status remains factual", async () => {
 let calls = 0; const api = async () => { calls++; return {}; };
 for (const body of [{ ...request().body, expected_revision: -1 }, { ...request().body, title: " " }, { ...request().body, title: "😀".repeat(161) }, { ...request("pin").body, title: null }, { ...request().body, action: "delete" }, { ...request().body, title: " padded " }, { action: "rename", expected_revision: 0, request_key: id(900) }]) await assert.rejects(writePresentation(api, scope, { sessionId: id(100), body }));
 assert.equal(calls, 0); const req = request(); req.body.title = null; assert.equal((await writePresentation(async () => receipt(req), scope, req)).presentation.title, null);
 for (const status of [403, 404, 409, 503]) { const failure = Object.assign(Error("actual"), { status }); await assert.rejects(writePresentation(async () => { throw failure; }, scope, request()), e => e === failure); }
});
