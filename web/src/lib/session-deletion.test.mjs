import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const ts = createRequire(import.meta.url)("typescript");
const loaded = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./session-deletion.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: loaded, exports: loaded.exports });
const { deletionPath, validPreview, validDeleted, deletedSummary } = loaded.exports;
const session = "11111111-1111-4111-8111-111111111111", category = "22222222-2222-4222-8222-222222222222";
const counts = { episodes: 2, marks: 1, index_rows: 3, vectors: 0, candidates: 1 };
const notice = { now: "立即清除…", by_retention: "按保留期清除…", kept: "仍然保留…" };
const preview = { version: "agent-session-deletion/v1", session_id: session, deleted: false, will_remove: counts, kept: { runs: 2, receipts: 1, adopted_notes: 0 }, blocked: null, notice };
const deleted = { version: "agent-session-deletion/v1", session_id: session, deleted: true, deleted_at: "2026-11-13T08:00:00+00:00", removed: counts, notice };

test("deletion path is fixed to the owner's personal or category Session", () => {
  assert.equal(deletionPath(null, session), `v1/personal/agent-sessions/${session}/deletion`);
  assert.equal(deletionPath(category, session), `v1/categories/${category}/agent-sessions/${session}/deletion`);
  assert.throws(() => deletionPath(null, "../other"));
  assert.throws(() => deletionPath("bad", session));
});

test("preview and result are accepted only in their exact shape for this Session", () => {
  assert.equal(validPreview(preview, session), true);
  assert.equal(validPreview({ ...preview, blocked: { reason_key: "session_run_active", message: "请先停止" } }, session), true);
  assert.equal(validPreview(preview, category), false);
  assert.equal(validPreview({ ...preview, deleted: true }, session), false);
  assert.equal(validPreview({ ...preview, notice: { ...notice, kept: "" } }, session), false);
  assert.equal(validPreview({ ...preview, will_remove: { ...counts, episodes: -1 } }, session), false);
  assert.equal(validDeleted(deleted, session), true);
  assert.equal(validDeleted(preview, session), false);
  assert.equal(validDeleted({ ...deleted, removed: { episodes: 1 } }, session), false);
  assert.match(deletedSummary(deleted), /情景记录 2 条.*未采纳的记忆提议 1 条/);
});
