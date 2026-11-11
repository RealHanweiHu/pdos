import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript");
const cache = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return new Proxy({}, { get: (_, key) => String(key) });
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  loaded.require = specifier => specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => null })
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const lib = load(path.join(directory, "lib/run-decisions.ts"));
const { questionOwners } = load(path.join(webRoot, "src/features/categories/preproject/proposal-item-table.tsx"));

const me = "11111111-1111-4111-8111-111111111111", category = "22222222-2222-4222-8222-222222222222", runId = "33333333-3333-4333-8333-333333333333";
const event = n => `${String(n).repeat(8)}-${String(n).repeat(4)}-4${String(n).repeat(3)}-8${String(n).repeat(3)}-${String(n).repeat(12)}`;
const command = (n, operation = "proposal.item.patch") => ({ command_id: event(n), idempotency_key: `agent:${runId}:model:call:${n}`, category_id: category, product_id: null, operation, expected_revision: 2, source_read_set: [], payload: { proposal_id: event(9), prepared_by_run_id: runId, candidate_digest: "a".repeat(64), title: `候选${n}` } });
const candidate = (n, extra = {}) => ({ event_id: event(n), sequence: n, operation: "proposal.item.patch", write_tier: "T0", kind: null, package: true, separate_reason: null, command: command(n), ...extra });
const run = (candidates, extra = {}) => ({ run_id: runId, goal: "整理合成提案\n【当前页面：提案】", status: "completed", error_code: null, reading_token: "completed:0", created_at: "2026-11-09T01:00:00Z", scope: "category", category: { id: category, name: "合成品类" }, product_id: null, proposal_id: null, project_id: null, questions: [], question_sequence: null, needs_review: false, candidates, more_candidates: false, ...extra });
const page = (runs, extra = {}) => ({ version: "personal-run-decisions/v1", principal_id: me, as_of: "2026-11-09T02:00:00Z", runs, total_runs: runs.length, candidate_count: runs.reduce((t, r) => t + r.candidates.length, 0), question_count: runs.reduce((t, r) => t + r.questions.length, 0), truncated: false, unavailable_runs: 0, ...extra });

test("the run read refuses a foreign, partial or widened page instead of showing nothing to decide", () => {
  const item = run([candidate(1), candidate(2, { package: false, separate_reason: "named_decision", write_tier: "T2", command: null })]);
  assert.equal(lib.parseRunDecisions(page([item]), me).runs.length, 1);
  assert.throws(() => lib.parseRunDecisions(page([item]), event(7)));
  assert.throws(() => lib.parseRunDecisions(page([item], { candidate_count: 1 }), me));
  assert.throws(() => lib.parseRunDecisions(page([item], { total_runs: 2 }), me));
  // A named (T2) item may never arrive as a package item with a command.
  assert.throws(() => lib.parseRunDecisions(page([run([candidate(1, { write_tier: "T2" })])]), me));
  // A package command must belong to the run's own category.
  assert.throws(() => lib.parseRunDecisions(page([run([candidate(1, { command: { ...command(1), category_id: event(8) } })])]), me));
  assert.equal(lib.runTitle(item.goal), "整理合成提案");
});

test("all package items are selected by default and a deep link preselects only that version", () => {
  const item = run([candidate(1), candidate(2), candidate(3, { package: false, separate_reason: "separate_entry", command: null })]);
  assert.deepEqual(lib.initialSelection(item, null), [event(1), event(2)]);
  assert.deepEqual(lib.initialSelection(item, event(2)), [event(2)]);
  assert.deepEqual(lib.initialSelection(item, event(3)), []);
  const href = lib.decideHref(runId, event(2));
  assert.deepEqual(lib.decideTarget(href.slice(1)), { runId, eventId: event(2) });
  assert.equal(lib.decideTarget("?area=work&decide=not-a-run"), null);
});

test("each selected item is previewed on its own; a failed or altered preview stays out of the package", async () => {
  const item = run([candidate(1), candidate(2), candidate(3), candidate(4, { package: false, separate_reason: "named_decision", write_tier: "T2", command: null })]);
  const calls = [];
  const api = async (route, body) => {
    calls.push([route, body]);
    if (body.command_id === event(2)) throw Object.assign(new Error("提案版本已变化。"), { status: 409 });
    if (body.command_id === event(3)) return { command: { ...body, payload: { ...body.payload, title: "被改动", confirmation_token: "t3" } }, review: {}, expires_at: "2099-01-01T00:00:00Z" };
    return { command: { ...body, payload: { ...body.payload, confirmation_token: "t1" } }, review: { effect: "保存一条修订" }, expires_at: "2099-01-01T00:00:00Z" };
  };
  const { previews, failures } = await lib.previewPackage(api, item, [event(1), event(2), event(3), event(4)]);
  assert.deepEqual(calls.map(([route]) => route), Array(3).fill(`v1/categories/${category}/commands/preview`));
  assert.deepEqual(calls.map(([, body]) => body), [command(1), command(2), command(3)]);
  assert.deepEqual(previews.map(entry => entry.eventId), [event(1)]);
  assert.equal(previews[0].command.payload.confirmation_token, "t1");
  assert.deepEqual(failures.map(entry => [entry.eventId, entry.message]), [[event(2), "提案版本已变化。"], [event(3), "预览与原候选不一致，请刷新后重新核对。"]]);
});

test("the package posts each item's own token and accepts only a complete per-item result", async () => {
  const item = run([candidate(1), candidate(2)]);
  const previews = [1, 2].map(n => ({ eventId: event(n), operation: "proposal.item.patch", command: { ...command(n), payload: { ...command(n).payload, confirmation_token: `t${n}` } }, review: {}, expiresAt: "2099-01-01T00:00:00Z" }));
  const sent = [];
  const result = { run_id: runId, items: [{ event_id: event(1), operation: "proposal.item.patch", status: "adopted", receipt: { id: event(5), operation: "proposal.item.patch", subject_id: event(9), subject_type: "proposal" } }, { event_id: event(2), operation: "proposal.item.patch", status: "failed", error: { code: "VERSION_CONFLICT", reason: "base_version_moved", message: "条目版本已变化" } }], adopted: 1, refused: 0, failed: 1, unknown: 0, not_attempted: 0 };
  const value = await lib.confirmPackage(async (route, body) => { sent.push([route, body]); return result; }, item, previews);
  assert.equal(sent[0][0], `v1/categories/${category}/agent-runs/${runId}/candidates/confirm`);
  assert.deepEqual(sent[0][1].items.map(entry => [entry.event_id, entry.command.payload.confirmation_token]), [[event(1), "t1"], [event(2), "t2"]]);
  assert.equal(value.adopted, 1);
  assert.throws(() => lib.parsePackageResult({ ...result, items: [...result.items].reverse() }, runId, previews));
  assert.throws(() => lib.parsePackageResult({ ...result, adopted: 2, failed: 0 }, runId, previews));
  assert.throws(() => lib.parsePackageResult({ ...result, items: [result.items[0]] }, runId, previews));
  await assert.rejects(lib.confirmPackage(async () => result, { ...item, category: null, scope: "personal" }, previews));
});

test("question owners list only people who can read the proposal (D337)", () => {
  const people = [{ id: "a", name: "甲", can_read_proposal: true }, { id: "b", name: "乙", can_read_proposal: false }, { id: "c", name: "丙" }];
  assert.deepEqual(questionOwners(people).map(person => person.id), ["a", "c"]);
});
