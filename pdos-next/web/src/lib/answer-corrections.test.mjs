import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import test from "node:test";
const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json")), ts = dependency("typescript");
function load(filename) {
  const compiled = new Module(filename);
  compiled.require = name => name === "./search-preferences" ? load(path.join(directory, "search-preferences.ts")) : dependency(name);
  compiled._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
  return compiled.exports;
}
const { answerCorrection, restoreAnswerCorrection, canCorrectAnswer, correctionSources, exclusionApplied } = load(path.join(directory, "answer-corrections.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const context = () => ({ root: "v1/agent-runs", run: { run_id: id(1), session_id: id(2), status: "completed", reverted: false, project_id: id(3), conversation: { next_run_id: null } }, workState: { version: "agent-work-state/v1", session_id: id(2), revision: 4, focus_objects: [{ id: id(4), kind: "artifact", version: 2, title: "复验报告" }], citations: [{ citation_id: id(5), title: "历史进水问题", source_revision: 3 }], exclusions: [], search_preferences: { scope: "current", include_customer_private: false }, search_context: { kind: "project", scoped: true, label: "气密项目" } } });

test("supplement carries the actual user condition as a closed native continuation", () => {
  const c = context(), value = answerCorrection(c, { action: "supplement", text: "  只补充缺失的温度，样本数未知。  ", sources: [{ artifact_id: id(8), expected_revision: 2 }] }, id(9));
  assert.deepEqual(value, { kind: "continue", path: "v1/agent-runs", body: { goal: "只补充缺失的温度，样本数未知。", idempotency_key: id(9), continue_from_run_id: id(1), sources: [{ artifact_id: id(8), expected_revision: 2 }] } });
  assert.equal("product_id" in value.body, false); assert.equal("session_id" in value.body, false); assert.equal("search_preferences" in value.body, false);
  assert.deepEqual(restoreAnswerCorrection(JSON.parse(JSON.stringify(value)), c), value);
});
test("same-category correction is a server search choice and preserves the customer choice", () => {
  for (const include of [false, true]) {
    const c = context(); c.workState.search_preferences.include_customer_private = include;
    const value = answerCorrection(c, { action: "same_category", text: "继续找同类进水案例" }, id(9));
    assert.deepEqual(value.body.search_preferences, { scope: "same_category", include_customer_private: include });
    assert.equal(c.workState.search_preferences.scope, "current");
    assert.deepEqual(restoreAnswerCorrection(value, c), value);
  }
});
test("personal/category scope does not offer the project category fallback", () => {
  const c = context(); c.run.project_id = null; c.workState.search_context = { kind: "personal", scoped: false, label: "本人范围" };
  assert.throws(() => answerCorrection(c, { action: "same_category" }, id(9)), /项目或提案/);
  assert.equal(answerCorrection(c, { action: "supplement", text: "补充温度" }, id(9)).kind, "continue");
});
test("active, reverted, superseded and other-session answers cannot emit new corrections", () => {
  const values = [context(), context(), context(), context()]; values[0].run.status = "running"; values[1].run.reverted = true; values[2].run.conversation.next_run_id = id(88); values[3].workState.session_id = id(77);
  for (const c of values) { assert.equal(canCorrectAnswer(c), false); assert.throws(() => answerCorrection(c, { action: "supplement", text: "条件" }, id(9))); }
});
test("exclusion posts the exact carried CID or artifact ID with its actual state revision", () => {
  for (const sourceId of [id(4), id(5)]) {
    const c = context(); c.root = `v1/categories/${id(7)}/agent-runs`;
    const value = answerCorrection(c, { action: "exclude_source", sourceId }, id(9));
    assert.deepEqual(value, { kind: "exclude_source", path: `v1/categories/${id(7)}/agent-sessions/${id(2)}/work-state`, body: { expected_revision: 4, request_key: id(9), action: "exclude_source", item_id: sourceId } });
    const updated = { ...c.workState, revision: 5, exclusions: [{ id: sourceId, reason: "用户标记不相关" }] };
    assert.equal(exclusionApplied(value, updated, c), true);
    assert.deepEqual(restoreAnswerCorrection(value, { ...c, workState: updated }), value);
  }
});
test("unseen, already excluded or unversioned source cannot form an exclusion", () => {
  const c = context(); assert.throws(() => answerCorrection(c, { action: "exclude_source", sourceId: id(99) }, id(9)));
  c.workState.exclusions = [{ id: id(5), reason: "不相关" }];
  assert.throws(() => answerCorrection(c, { action: "exclude_source", sourceId: id(5) }, id(9)));
  c.workState.focus_objects.push({ id: id(44), kind: "project", title: "其他项目", version: 1 }, { id: id(45), kind: "artifact", version: null });
  assert.deepEqual(correctionSources(c.workState), [{ id: id(4), title: "复验报告", revision: 2 }]);
});
test("collapse requires the actual returned session, new revision and matching exclusion", () => {
  const c = context(), request = answerCorrection(c, { action: "exclude_source", sourceId: id(5) }, id(9));
  for (const state of [c.workState, { ...c.workState, revision: 5 }, { ...c.workState, revision: 5, session_id: id(99), exclusions: [{ id: id(5) }] }]) assert.equal(exclusionApplied(request, state, c), false);
});
test("unsupported object, current-version and source-only filters never degrade to prompt text", () => {
  for (const action of ["replace_focus", "current_only", "source_only", "version"]) assert.throws(() => answerCorrection(context(), { action, text: "按这些条件重查" }, id(9)), /尚未接入/);
});
test("invalid conditions and source references are rejected before delegation", () => {
  for (const action of [{ action: "supplement", text: " " }, { action: "supplement", text: "x".repeat(8001) }, { action: "supplement", text: "温度", sources: [{ artifact_id: id(4), expected_revision: 0 }] }, { action: "supplement", text: "温度", sources: [{ artifact_id: id(4), expected_revision: 1, audience: "all" }] }]) assert.throws(() => answerCorrection(context(), action, id(9)));
});
test("replay rejects extra scope, policy and fake filter fields and another run/root", () => {
  const c = context(), value = answerCorrection(c, { action: "same_category" }, id(9));
  for (const mutate of [v => { v.body.product_id = id(4); }, v => { v.body.session_id = id(2); }, v => { v.body.sources = [{ artifact_id: id(4), expected_revision: 1, approved: true }]; }, v => { v.body.source_only = [id(4)]; }, v => { v.body.search_preferences.audience = "all"; }, v => { v.body.continue_from_run_id = id(88); }, v => { v.path = "v1/personal/agent-runs"; }]) { const copy = structuredClone(value); mutate(copy); assert.equal(restoreAnswerCorrection(copy, c), null); }
});
