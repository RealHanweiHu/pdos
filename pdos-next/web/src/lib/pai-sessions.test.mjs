import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const require = createRequire(import.meta.url), ts = require("typescript"), compiled = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./pai-sessions.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { module: compiled, exports: compiled.exports, URLSearchParams });
const { readSessionList, readSessionRuns } = compiled.exports;
const id = n => `00000000-0000-0000-0000-${n.toString(16).padStart(12, "0")}`;
const scope = { principalId: id(1), categoryId: id(2), proposalId: id(3) };
const time = "2026-10-17T12:34:56.123456789+00:00";
const older = "2026-10-17T12:34:56.123456788+00:00";
const clone = value => JSON.parse(JSON.stringify(value));
const pageScope = () => ({ category_id: scope.categoryId, proposal_id: scope.proposalId });
function head(n = 201, created_at = time) {
  return { run_id: id(n), goal: "保留实际研究目标与未知条件", status: "completed", error_code: null, created_at, continued_from_id: n === 201 ? id(202) : null, reverted: false };
}
function meta() {
  return { session_id: id(100), revision: 1, created_at: "2026-10-16T00:00:00+00:00",
    scope: { category_id: scope.categoryId, product_id: id(4), proposal_id: scope.proposalId }, run_count: 2 };
}
function list() {
  return { version: "agent-session-list/v1", principal_id: scope.principalId, scope: pageScope(), as_of: time,
    items: [{ ...meta(), latest_run: head(), matched_run: null }], next_cursor: null };
}
function runs() {
  return { version: "agent-session-runs/v1", principal_id: scope.principalId, scope: pageScope(), as_of: time, session: meta(), items: [
    { ...head(), conversation: { previous_run_id: id(202), next_run_id: null } },
    { ...head(202, older), conversation: { previous_run_id: null, next_run_id: id(201) } },
  ], next_cursor: null };
}
function apiFor(value) {
  const calls = [];
  const api = async (...args) => { calls.push(args); assert.equal(args.length, 1, "Every reader call has only a GET path"); return clone(value); };
  return { api, calls };
}
const base = `v1/categories/${scope.categoryId}/agent-sessions`;

test("real Session identity groups Run metadata without inventing a title, session status or authority", async () => {
  const raw = list(), transport = apiFor(raw), value = await readSessionList(transport.api, scope);
  assert.equal(transport.calls[0][0], `${base}?page_size=20&proposal_id=${scope.proposalId}`);
  assert.deepEqual(clone(value), raw);
  assert.equal(value.items[0].run_count, 2);
  assert.equal(value.items[0].latest_run.goal, raw.items[0].latest_run.goal);
  assert.equal(value.items[0].latest_run.created_at, time);
  for (const key of ["title", "status", "can_continue", "pinned", "archived", "result"]) assert.equal(key in value.items[0], false);
});

test("personal entry remains private and empty search becomes an unfiltered GET", async () => {
  const raw = list(); raw.scope = { category_id: null, proposal_id: null };
  raw.items[0].scope = { category_id: null, product_id: null, proposal_id: null };
  for (const categoryId of [null, ""]) {
    const transport = apiFor(raw);
    await readSessionList(transport.api, { principalId: scope.principalId, categoryId }, { q: "  " });
    assert.equal(transport.calls[0][0], "v1/personal/agent-sessions?page_size=20");
  }
});

test("search remains literal and preserves the actual matched Run independently of latest", async () => {
  const raw = list(), q = "%_\\ 原值";
  raw.items[0].matched_run = { ...head(202, older), goal: `较早目标含 ${q} 作为原文字面内容`, match_kind: "goal" };
  const transport = apiFor(raw), value = await readSessionList(transport.api, scope, { q: `  ${q}  `, pageSize: 1 });
  const url = new URL(transport.calls[0][0], "https://synthetic.invalid/");
  assert.equal(url.searchParams.get("q"), q);
  assert.equal(url.searchParams.get("page_size"), "1");
  assert.equal(value.items[0].matched_run.run_id, id(202));
  assert.equal(value.items[0].latest_run.run_id, id(201));
  assert.equal(transport.calls.length, 1, "No N+1 Run body or event reads");
});

test("Run and Session UUID search spellings are interpreted only by the server", async () => {
  for (const [kind, query] of [["run_id", id(201).toUpperCase()], ["session_id", id(100).toUpperCase()],
    ["run_id", id(201).replaceAll("-", "")], ["session_id", `{${id(100)}}`]]) {
    const raw = list(); raw.items[0].matched_run = { ...head(), match_kind: kind };
    await readSessionList(apiFor(raw).api, scope, { q: query });
  }
});

test("selected Session runs keep precise chronology and actual continuation links", async () => {
  const raw = runs(), transport = apiFor(raw), value = await readSessionRuns(transport.api, scope, id(100));
  assert.equal(transport.calls[0][0], `${base}/${id(100)}/runs?page_size=20&proposal_id=${scope.proposalId}`);
  assert.deepEqual(clone(value), raw);
  assert.deepEqual(value.items.map(item => item.run_id), [id(201), id(202)]);
  assert.ok(value.items[0].created_at > value.items[1].created_at, "Microseconds are kept even within one JavaScript millisecond");
});

test("pagination returns exact server anchors and permits neighbors outside the page", async () => {
  const raw = runs(); raw.items = [raw.items[0]]; raw.next_cursor = raw.items[0].run_id;
  const value = await readSessionRuns(apiFor(raw).api, scope, id(100), { pageSize: 1 });
  assert.equal(value.items[0].conversation.previous_run_id, id(202));
  assert.equal(value.next_cursor, id(201));
  const tail = runs(); tail.items = []; const transport = apiFor(tail);
  assert.equal((await readSessionRuns(transport.api, scope, id(100), { cursor: id(202), pageSize: 1 })).items.length, 0);
  assert.match(transport.calls[0][0], new RegExp(`cursor=${id(202)}`));
  const sessionPage = list(); sessionPage.next_cursor = id(100);
  assert.equal((await readSessionList(apiFor(sessionPage).api, scope, { pageSize: 1 })).next_cursor, id(100));
});

test("invalid identity, scope, selection or query cannot initiate a request", async () => {
  const transport = apiFor(list());
  for (const bad of [{ ...scope, principalId: "other" }, { ...scope, categoryId: "../category" }, { ...scope, proposalId: "bad" }, { ...scope, categoryId: null }]) await assert.rejects(readSessionList(transport.api, bad));
  for (const options of [{ pageSize: 0 }, { pageSize: 51 }, { pageSize: 1.1 }, { pageSize: null }, { cursor: "invalid" }, { q: "x".repeat(161) }, { q: null }, { unknown: true }]) await assert.rejects(readSessionList(transport.api, scope, options));
  await assert.rejects(readSessionRuns(transport.api, scope, "not-session"));
  await assert.rejects(readSessionRuns(transport.api, scope, id(100), { q: "not-supported" }));
  assert.equal(transport.calls.length, 0);
});

test("query length uses Unicode code points and never slices the user's literal query", async () => {
  const raw = list(), q = "😀".repeat(160); raw.items[0].latest_run.goal = q; raw.items[0].matched_run = { ...head(), goal: q, match_kind: "goal" };
  const transport = apiFor(raw); await readSessionList(transport.api, scope, { q });
  assert.equal(new URL(transport.calls[0][0], "https://synthetic.invalid/").searchParams.get("q"), q);
});

for (const [name, mutate] of [
  ["wrong DTO version", value => { value.version = "agent-session-list/v2"; }],
  ["different current principal", value => { value.principal_id = id(999); }],
  ["different envelope category", value => { value.scope.category_id = id(999); }],
  ["missing proposal filter echo", value => { delete value.scope.proposal_id; }],
  ["different proposal filter echo", value => { value.scope.proposal_id = null; }],
  ["different Session category", value => { value.items[0].scope.category_id = id(999); }],
  ["different Session proposal", value => { value.items[0].scope.proposal_id = id(999); }],
  ["invalid product identity", value => { value.items[0].scope.product_id = "unknown"; }],
  ["nonpositive Session revision", value => { value.items[0].revision = 0; }],
  ["missing latest Run", value => { delete value.items[0].latest_run; }],
  ["missing Run state", value => { delete value.items[0].latest_run.status; }],
  ["unknown Run state", value => { value.items[0].latest_run.status = "archived"; }],
  ["missing explicit error field", value => { delete value.items[0].latest_run.error_code; }],
  ["zero readable Run count", value => { value.items[0].run_count = 0; }],
  ["Run self continuation", value => { value.items[0].latest_run.continued_from_id = id(201); }],
  ["duplicate Session", value => { value.items.push(clone(value.items[0])); }],
  ["unexpected Run body", value => { value.items[0].latest_run.result = { secret: "must not be accepted" }; }],
  ["unexpected envelope body", value => { value.body = "must not be accepted"; }],
  ["invalid calendar timestamp", value => { value.as_of = "2026-02-30T00:00:00Z"; }],
  ["timestamp without timezone", value => { value.items[0].created_at = "2026-10-17T12:34:56"; }],
  ["unsearched matched Run", value => { value.items[0].matched_run = { ...head(), match_kind: "goal" }; }],
  ["cursor not the final Session", value => { value.next_cursor = id(999); }],
]) test(`list rejects ${name}`, async () => { const raw = list(); mutate(raw); await assert.rejects(readSessionList(apiFor(raw).api, scope)); });

test("a search response requires a known server explanation and consistent Run metadata", async () => {
  for (const matched of [null, { ...head(), match_kind: "invented" }]) {
    const raw = list(); raw.items[0].matched_run = matched;
    await assert.rejects(readSessionList(apiFor(raw).api, scope, { q: "unmatched" }));
  }
  const raw = list(); raw.items[0].matched_run = { ...head(), goal: "不同实际目标", match_kind: "run_id" };
  await assert.rejects(readSessionList(apiFor(raw).api, scope, { q: id(201) }));
});

test("the reader accepts the server's Unicode goal match without duplicating database collation", async () => {
  const raw = list(), q = "ı";
  raw.items[0].latest_run.goal = "I — the database owns this match";
  raw.items[0].matched_run = { ...raw.items[0].latest_run, match_kind: "goal" };
  const transport = apiFor(raw), value = await readSessionList(transport.api, scope, { q });
  assert.equal(value.items[0].matched_run.goal, raw.items[0].latest_run.goal);
  assert.equal(new URL(transport.calls[0][0], "https://synthetic.invalid/").searchParams.get("q"), q);
});

for (const [name, mutate] of [
  ["different selected Session", value => { value.session.session_id = id(999); }],
  ["different detail principal", value => { value.principal_id = id(999); }],
  ["different detail category", value => { value.scope.category_id = id(999); }],
  ["different Session proposal", value => { value.session.scope.proposal_id = id(999); }],
  ["duplicate Run", value => { value.items.push(clone(value.items[0])); }],
  ["Run count smaller than returned page", value => { value.session.run_count = 1; }],
  ["missing conversation", value => { delete value.items[0].conversation; }],
  ["different fixed previous Run", value => { value.items[0].conversation.previous_run_id = null; }],
  ["next Run points to itself", value => { value.items[0].conversation.next_run_id = value.items[0].run_id; }],
  ["inconsistent visible reverse link", value => { value.items[1].conversation.next_run_id = null; }],
  ["reversed precise time order", value => { value.items.reverse(); }],
  ["cursor not final returned Run", value => { value.next_cursor = id(201); }],
  ["missing explicit reverted fact", value => { delete value.items[0].reverted; }],
  ["source body mixed into metadata", value => { value.items[0].sources = [{ quote: "private" }]; }],
]) test(`Run page rejects ${name}`, async () => { const raw = runs(); mutate(raw); await assert.rejects(readSessionRuns(apiFor(raw).api, scope, id(100))); });

test("page length, ordering and input anchor are never silently accepted or repaired", async () => {
  await assert.rejects(readSessionRuns(apiFor(runs()).api, scope, id(100), { pageSize: 1 }));
  const empty = runs(); empty.items = [];
  await assert.rejects(readSessionRuns(apiFor(empty).api, scope, id(100)));
  const cursor = list();
  await assert.rejects(readSessionList(apiFor(cursor).api, scope, { cursor: id(100) }));
  const reused = list(); const second = { ...clone(reused.items[0]), session_id: id(99), created_at: "2026-10-15T00:00:00Z" };
  reused.items.push(second);
  await assert.rejects(readSessionList(apiFor(reused).api, scope), "One Run cannot become two Sessions");
});

test("no filter permits distinct real proposal Sessions without rebinding them to the current page", async () => {
  const raw = list(); raw.scope.proposal_id = null;
  const result = await readSessionList(apiFor(raw).api, { ...scope, proposalId: undefined });
  assert.equal(result.items[0].scope.proposal_id, scope.proposalId);
});

test("failures propagate without old response fallback, retries, storage or Run reads", async () => {
  const calls = [], failure = Object.assign(new Error("范围已经失效"), { status: 403 });
  const api = async path => { calls.push(path); throw failure; };
  await assert.rejects(readSessionList(api, scope), error => error === failure);
  await assert.rejects(readSessionRuns(api, scope, id(100)), error => error === failure);
  assert.equal(calls.length, 2);
  assert.ok(calls.every(path => !path.includes("agent-runs")));
});
