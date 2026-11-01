import test from "node:test";
import assert from "node:assert/strict";
import { budgetPendingKey, dollars, matchBudgetReceipt, microDollars, parseBudgetPending, validLimits, type BudgetCommand, type BudgetReceipt } from "./agent-budgets";

const limits = { limit_micro_usd: 1250001, input_token_limit: 100000, output_token_limit: 10000, call_limit: 20 };
const original: BudgetCommand = { category_id: "category", product_id: null, command_id: "11111111-2222-4333-8444-555555555555",
  idempotency_key: "approved-budget-original", operation: "ai.budget.configure", expected_revision: 1, source_read_set: [],
  payload: { action: "allocate", expected_active_digest: "a".repeat(64), limits, confirmation_token: "synthetic-approved-budget-token" } };
const receipt: BudgetReceipt = { id: "receipt", operation: "ai.budget.configure", subject_type: "agent_budget", subject_id: "wallet", subject_revision: 1,
  category_id: "category", writer_id: "human", requester_id: "human", agent_run_id: null,
  result: { action: "allocate", scope: "requester", requester_id: "human", expected_active_digest: "a".repeat(64), control_revision: 0, next_revision: 1, limits, retired_budgets: [], existing_usage_preserved: true, allocated_budget_id: "wallet" } };

test("USD amounts roundtrip every stored micro-dollar exactly without binary rounding", () => {
  for (const value of [0, 1, 999999, 1000000, 1250001, 2147483647]) assert.equal(microDollars(dollars(value)), value);
  assert.equal(microDollars(" 0.000001 "), 1);
  for (const value of ["", "-1", "1e2", "1,000", "1.0000001", "2147.483648", "NaN"]) assert.throws(() => microDollars(value));
  assert.ok(validLimits({ ...limits, limit_micro_usd: 0 }));
  for (const changed of [{ call_limit: 0 }, { input_token_limit: 1.5 }, { output_token_limit: NaN }, { requester_id: "forged" }]) assert.equal(validLimits({ ...limits, ...changed }), false);
});

test("scope-owned recovery retains only a complete original budget configuration command", () => {
  assert.deepEqual(parseBudgetPending(JSON.stringify(original), "category"), original);
  const stop = { ...original, payload: { ...original.payload, action: "stop", limits: null } };
  assert.deepEqual(parseBudgetPending(JSON.stringify(stop), "category"), stop);
  assert.notEqual(budgetPendingKey("human", "a"), budgetPendingKey("peer", "a"));
  assert.notEqual(budgetPendingKey("human", "a"), budgetPendingKey("human", "b"));
  for (const value of [null, {}, { ...original, category_id: "other" }, { ...original, operation: "other" }, { ...original, payload: { ...original.payload, requester_id: "peer" } }, { ...original, payload: { ...original.payload, action: "stop" } }, { ...original, payload: { ...original.payload, expected_active_digest: "invalid" } }]) assert.throws(() => parseBudgetPending(JSON.stringify(value), "category"));
});

test("receipt matching preserves original owner, scope, state watermark and exact limits", () => {
  assert.ok(matchBudgetReceipt(receipt, original, "human", "category"));
  const later: BudgetReceipt = { ...receipt, subject_revision: 3,
    result: { ...receipt.result, control_revision: 2, next_revision: 3 } };
  assert.ok(matchBudgetReceipt(later, original, "human", "category"));
  for (const change of [{ writer_id: "agent" }, { category_id: "other" }, { agent_run_id: "run" }, { result: { ...receipt.result, limits: { ...limits, limit_micro_usd: limits.limit_micro_usd + 1 } } }, { result: { ...receipt.result, requester_id: "peer" } }, { result: { ...receipt.result, existing_usage_preserved: false } }, { result: { ...receipt.result, expected_active_digest: "b".repeat(64) } }]) assert.equal(matchBudgetReceipt({ ...receipt, ...change } as BudgetReceipt, original, "human", "category"), false);
  const stopped: BudgetCommand = { ...original, payload: { ...original.payload, action: "stop", limits: null } };
  const stoppedReceipt: BudgetReceipt = { ...receipt, subject_revision: 2, result: { ...receipt.result, control_revision: 1, next_revision: 2, action: "stop", limits: null, allocated_budget_id: null, retired_budgets: [{ id: "wallet", previous_revision: 1, next_revision: 2 }] } };
  assert.ok(matchBudgetReceipt(stoppedReceipt, stopped, "human", "category"));
  assert.equal(matchBudgetReceipt({ ...stoppedReceipt, subject_revision: 3 }, stopped, "human", "category"), false);
});
