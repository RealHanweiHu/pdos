import test from "node:test";
import assert from "node:assert/strict";
import { blankReview, matchesQualificationReceipt, parseQualificationPending, qualificationPendingKey, type QualificationCommand, type QualificationReceipt } from "./skill-qualification";
const category = "00000000-0000-4000-8000-000000000001", principal = "00000000-0000-4000-8000-000000000002";
const command: QualificationCommand = { category_id: category, product_id: null, command_id: category, idempotency_key: category, operation: "ai.skill.review.record", expected_revision: 1, source_read_set: [], payload: { skill_key: "public_research", skill_digest: "a".repeat(64), tool_digest: "b".repeat(64), model_digest: "c".repeat(64), personally_reviewed: true, cases: [{ ...blankReview(), source_ref: "合成案例", conclusion: "本人核对未知" }], confirmation_token: "x".repeat(32) } };
const receipt: QualificationReceipt = { id: category, operation: command.operation, category_id: category, writer_id: principal, requester_id: principal, agent_run_id: null, subject_type: "skill_review", subject_revision: 1, result: { skill_key: "public_research", case_count: 1 } };
test("case review defaults keep unknowns and recovery remains person/category scoped", () => {
  assert.ok(Object.values(blankReview().criteria).every(value => value === "unknown"));
  assert.equal(blankReview().severity, "unknown");
  assert.notEqual(qualificationPendingKey(principal, category), qualificationPendingKey(category, principal));
  assert.deepEqual(parseQualificationPending(JSON.stringify(command), category), command);
  assert.throws(() => parseQualificationPending(JSON.stringify(command), principal));
  assert.throws(() => parseQualificationPending(JSON.stringify({ ...command, payload: { ...command.payload, personally_reviewed: false } }), category));
});
test("recovery binds actual receipt operation, author, skill and case count", () => {
  assert.ok(matchesQualificationReceipt(receipt, command, principal, category));
  for (const patch of [{ writer_id: category }, { category_id: principal }, { operation: "ai.skill.qualify" }, { agent_run_id: category }, { subject_revision: 2 }, { result: { skill_key: "other", case_count: 1 } }]) assert.equal(matchesQualificationReceipt({ ...receipt, ...patch }, command, principal, category), false);
});
test("named qualification recovery checks decision and original control revision", () => {
  const original: QualificationCommand = { ...command, operation: "ai.skill.qualify", payload: { skill_key: "public_research", expected_revision: 4, decision: "撤销", reason: "本人决定", case_refs: [], approval_token: "a".repeat(32) } };
  const actual = { ...receipt, operation: original.operation, subject_type: "skill_qualification", result: { skill_key: "public_research", decision: "撤销", next_revision: 5, case_count: 10 } };
  assert.deepEqual(parseQualificationPending(JSON.stringify(original), category), original);
  assert.ok(matchesQualificationReceipt(actual, original, principal, category));
  assert.equal(matchesQualificationReceipt({ ...actual, result: { ...actual.result, decision: "批准" } }, original, principal, category), false);
});
