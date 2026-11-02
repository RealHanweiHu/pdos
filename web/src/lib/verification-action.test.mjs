import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import test from "node:test";
const require = createRequire(import.meta.url), ts = require("typescript");
const compiledModule = new Module(import.meta.filename);
compiledModule._compile(ts.transpileModule(readFileSync(new URL("./verification-action.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, import.meta.filename);
const { verificationAnswerSources, verificationBuildRef, validVerificationAction, verificationStart } = compiledModule.exports;
const id = n => `${String(n).padStart(8, "0")}-1111-4111-8111-111111111111`;
const selection = { id: id(1), revision: 2, product_id: id(2), project_id: id(3), engineering_configuration: { id: id(4), revision: 3 }, manufacturing_configuration: { id: id(5), revision: 4 } };
const run = { run_id: id(6), status: "completed", reverted: false, product_id: id(2), project_id: id(3), result: { result: { assistant: { task_result: { version: 1, format: "cases", rows: [{ cells: { root_cause: { status: "recorded", citation_id: id(7) }, measures: { status: "recorded", citation_id: id(7) }, missing: { status: "to_confirm", citation_id: id(8) } } }] }, sources: [{ citation_id: id(7), title: "合成历史问题", source_revision: 2 }, { citation_id: id(8), title: "未选择的其他资料", source_revision: 1 }] } } } };

test("case action selects only the server case cells' actual source identities", () => {
  assert.deepEqual(verificationAnswerSources(run), [{ citation_id: id(7), title: "合成历史问题", source_revision: 2 }]);
  for (const patch of [{ reverted: true }, { status: "running" }, { product_id: null }, { project_id: null }, { result: { result: { assistant: { task_result: { version: 1, format: "review", rows: [] }, sources: [] } } } }]) assert.deepEqual(verificationAnswerSources({ ...run, ...patch }), []);
});
test("the continuation preserves fixed Build/config references and selected definitions without client authority fields", () => {
  const original = verificationStart(run, selection, [id(7)], [{ artifact_id: id(9), expected_revision: 4, title: "display only" }], "same-original-key", "密封复验");
  assert.deepEqual(Object.keys(original.body).sort(), ["continue_from_run_id", "goal", "idempotency_key", "sources", "verification_action"].sort());
  assert.equal(original.body.continue_from_run_id, run.run_id);
  assert.deepEqual(original.body.verification_action, { selection, citation_ids: [id(7)] });
  assert.deepEqual(original.body.sources, [{ artifact_id: id(9), expected_revision: 4 }]);
  assert.match(original.body.goal, /密封复验/); assert.ok(!original.body.goal.includes(selection.id));
  assert.throws(() => verificationStart(run, { ...selection, project_id: id(20) }, [id(7)], [], "key", "轮次"));
  assert.throws(() => verificationStart(run, selection, [id(8)], [], "key", "轮次"));
});
test("closed selection/action metadata reject hidden authority, duplicates and unfixed versions", () => {
  assert.equal(verificationBuildRef(selection), true);
  assert.equal(validVerificationAction({ selection, citation_ids: [id(7)] }), true);
  for (const value of [{ selection, citation_ids: [] }, { selection, citation_ids: [id(7), id(7)] }, { selection, citation_ids: [id(7)], audience: "category" }, { selection: { ...selection, revision: 0 }, citation_ids: [id(7)] }, { selection: { ...selection, engineering_configuration: { ...selection.engineering_configuration, permission: true } }, citation_ids: [id(7)] }]) assert.equal(validVerificationAction(value), false);
});
