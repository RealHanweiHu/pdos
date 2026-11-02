import test from "node:test";
import assert from "node:assert/strict";
import { reconciliationNeeded, restoreReconciliation } from "./run-reconciliation";

test("结果未知不是普通待答问题，终态也不重新开启对账", () => {
  assert.equal(reconciliationNeeded({ status: "waiting_input", error_code: "EXTERNAL_OUTCOME_UNKNOWN" }), true);
  assert.equal(reconciliationNeeded({ status: "waiting_input", error_code: null }), false);
  assert.equal(reconciliationNeeded({ status: "failed", error_code: "EXTERNAL_OUTCOME_UNKNOWN" }), false);
});

test("丢失响应只保留原运行、入口与版本，不接受客户端权限或替换目标", () => {
  const value = { run_id: "synthetic-run", root: "v1/agent-runs", expected_cancel_epoch: 0 };
  assert.deepEqual(restoreReconciliation(value, value.run_id, value.root), value);
  assert.equal(restoreReconciliation(value, "another-run", value.root), null);
  assert.equal(restoreReconciliation(value, value.run_id, "v1/personal/agent-runs"), null);
  assert.equal(restoreReconciliation({ ...value, automatic: true }, value.run_id, value.root), null);
  assert.equal(restoreReconciliation({ ...value, expected_cancel_epoch: -1 }, value.run_id, value.root), null);
});
