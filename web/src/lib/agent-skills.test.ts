import test from "node:test";
import assert from "node:assert/strict";
import { matchSkillReceipt, parseSkillPending, skillPendingKey, type SkillCommand, type SkillReceipt } from "./agent-skills";

const original: SkillCommand = { category_id: "category", product_id: null, command_id: "11111111-2222-4333-8444-555555555555",
  idempotency_key: "approved-original-skill", operation: "ai.skill.enable", expected_revision: 1, source_read_set: [],
  payload: { skill_key: "public_research", expected_revision: 0, enabled: true,
    skill_version: "synthetic-version", skill_digest: "a".repeat(64), confirmation_token: "synthetic-token-for-original-confirmation" } };
const receipt: SkillReceipt = { id: "receipt", operation: "ai.skill.enable", category_id: "category", writer_id: "human",
  requester_id: "human", agent_run_id: null, subject_type: "skill_enablement", subject_revision: 1,
  result: { skill_key: "public_research", enabled: true, qualification_changed: false } };

test("only the exact confirmed skill command is retained for scope-owned recovery", () => {
  assert.deepEqual(parseSkillPending(JSON.stringify(original), "category"), original);
  assert.notEqual(skillPendingKey("human", "a"), skillPendingKey("peer", "a"));
  assert.notEqual(skillPendingKey("human", "a"), skillPendingKey("human", "b"));
  const removed = { ...original, payload: { ...original.payload, enabled: false, skill_version: null, skill_digest: null } };
  assert.deepEqual(parseSkillPending(JSON.stringify(removed), "category"), removed);
});

test("corrupted or expanded local commands cannot masquerade as approved skill toggles", () => {
  for (const value of [null, {}, { ...original, category_id: "other" }, { ...original, operation: "ai.skill.qualify" }, { ...original, command_id: "invalid" }, { ...original, expected_revision: 0 }, { ...original, payload: { ...original.payload, pilot: true } }, { ...original, payload: { ...original.payload, skill_digest: null } }, { ...original, payload: { ...original.payload, confirmation_token: "short" } }]) assert.throws(() => parseSkillPending(JSON.stringify(value), "category"));
});

test("only a same-person receipt for the approved skill state and revision clears pending", () => {
  assert.ok(matchSkillReceipt(receipt, original, "human", "category"));
  for (const change of [{ writer_id: "agent" }, { requester_id: "peer" }, { category_id: "other" }, { agent_run_id: "run" }, { subject_revision: 2 }, { result: { ...receipt.result, enabled: false } }, { result: { ...receipt.result, qualification_changed: true } }, { result: { ...receipt.result, skill_key: "other" } }]) assert.equal(matchSkillReceipt({ ...receipt, ...change }, original, "human", "category"), false);
});
