import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const dir = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(dir, "../../../.."), dep = createRequire(path.join(web, "package.json")), ts = dep("typescript");
const cache = new Map();
function load(filename) {
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = name => name === "react" ? dep("react") : name.startsWith("@/") ? load([".ts", ".tsx"].map(ext => path.join(web, "src", name.slice(2)) + ext).find(file => { try { readFileSync(file); return true; } catch { return false; } })) : dep(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
  return loaded.exports;
}
const { bareEntry, countText, defaultHomeArea, readPendingCount, shellPreferences } = load(path.join(dir, "shell-preferences.ts"));
const me = "11111111-1111-4111-8111-111111111111";

test("default home applies only to a bare entry and unknown values fall back to 我的工作", () => {
  const inbox = shellPreferences({ revision: 2, preferences: { default_home: "inbox", pending_reminders: false } });
  assert.deepEqual(inbox, { default_home: "inbox", pending_reminders: false });
  assert.equal(defaultHomeArea("", inbox), "inbox");
  for (const search of ["?area=work", "?category=c", "?project=p", "?bench=products"]) assert.equal(defaultHomeArea(search, inbox), null, search);
  assert.equal(defaultHomeArea("", shellPreferences({ preferences: { default_home: "settings", pending_reminders: "yes" } })), null);
  assert.deepEqual(shellPreferences(null), { default_home: "work", pending_reminders: true });
  assert.equal(countText(120), "99+");
  // D341: only a bare entry waits for the saved home; any named page shows at once.
  assert.equal(bareEntry(""), true);
  for (const search of ["?area=work", "?category=c", "?project=p", "?bench=products"]) assert.equal(bareEntry(search), false, search);
});

test("pending count sums 要我决定 (with 小Pai runs, once per run)、接收、验证 with GET reads only and refuses another person's queue", async () => {
  const calls = [];
  const page = (queue, total, principal = me) => ({ version: "personal-attention/v1", principal_id: principal, queue, items: [], total_records: total, next_cursor: null, as_of: "2026-11-08T00:00:00Z" });
  const run = id => ({ run_id: id, goal: "合成运行", status: "completed", error_code: null, reading_token: "completed:0", created_at: "2026-11-08T00:00:00Z", scope: "personal", category: null, product_id: null, proposal_id: null, project_id: null, questions: [{ id: "q", question: "合成问题", why: "", options: [], allow_free_text: true }], question_sequence: 2, needs_review: false, candidates: [], more_candidates: false });
  const runs = (principal = me) => ({ version: "personal-run-decisions/v1", principal_id: principal, as_of: "2026-11-08T00:00:00Z", runs: [run("33333333-3333-4333-8333-333333333333"), run("44444444-4444-4444-8444-444444444444")], total_runs: 2, candidate_count: 0, question_count: 2, truncated: false, unavailable_runs: 0 });
  const totals = { decide: 2, receive: 1, verify: 4 };
  const reply = (route, principal) => route.startsWith("v1/personal/run-decisions") ? runs(principal) : page(new URLSearchParams(route.split("?")[1]).get("queue"), totals[new URLSearchParams(route.split("?")[1]).get("queue")], principal);
  const count = await readPendingCount(async (route, body) => { calls.push([route, body]); return reply(route); }, me);
  assert.equal(count, 9);
  assert.deepEqual(calls.map(([route]) => route), [...["decide", "receive", "verify"].map(queue => `v1/personal/attention?queue=${queue}&page_size=1`), "v1/personal/run-decisions"]);
  assert.ok(calls.every(([, body]) => body === undefined));
  await assert.rejects(readPendingCount(async route => reply(route, "22222222-2222-4222-8222-222222222222"), me));
  await assert.rejects(readPendingCount(async route => route.startsWith("v1/personal/run-decisions") ? runs("22222222-2222-4222-8222-222222222222") : reply(route), me));
});
