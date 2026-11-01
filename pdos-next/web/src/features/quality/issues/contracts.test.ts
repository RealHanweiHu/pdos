import assert from "node:assert/strict";
import test from "node:test";
import { canonical, failureProblem, operationProblem, previewProblem, unresolvedAction } from "./contracts";
import { action, context, failure, mergeIntent, preview, source } from "./__tests__/fixtures";

test("preview binds exact material intent and current source/configuration/permission watermark", () => {
  assert.equal(previewProblem(preview, mergeIntent, context, action.nowMs), null);
  assert.match(previewProblem(preview, { ...mergeIntent, reason: "已修改" }, context, action.nowMs)!, /输入已修改/);
  assert.match(previewProblem(preview, mergeIntent, { ...context, key: "synthetic-config-v2" }, action.nowMs)!, /配置/);
  assert.match(previewProblem(preview, mergeIntent, context, Date.parse(preview.expiresAt))!, /到期/);
  assert.match(previewProblem({ ...preview, missing: [{ blocking: true, description: "合成ACL冲突" }] }, mergeIntent, context, action.nowMs)!, /阻塞/);
});
test("T2 denies AI, missing named identity and tier downgrade; merge stays T1", () => {
  assert.match(operationProblem("quality.issue.close", { ...context, actor: { ...context.actor!, kind: "ai" } })!, /具名人/);
  assert.match(operationProblem("quality.issue.close", { ...context, actor: null })!, /具名人/);
  assert.match(operationProblem("quality.issue.close", { ...context, capabilities: { ...context.capabilities, "quality.issue.close": { allowed: true, registered: true, tier: "T0", reason: null } } })!, /分级不得降低/);
  assert.match(operationProblem("quality.issue.merge", { ...context, capabilities: { ...context.capabilities, "quality.issue.merge": { allowed: true, registered: true, tier: "T0", reason: null } } })!, /T1/);
});
test("planned, indeterminate, no measurement value and withdrawn source cannot build failure Issue", () => {
  assert.equal(failureProblem(failure), null);
  assert.match(failureProblem({ ...failure, runStatus: "planned" })!, /计划/);
  assert.match(failureProblem({ ...failure, result: "indeterminate" })!, /不确定/);
  assert.match(failureProblem({ ...failure, rawValue: "" })!, /测量/);
  assert.match(failureProblem({ ...failure, rawValue: null })!, /测量/);
  assert.match(failureProblem({ ...failure, source: { ...source, status: "withdrawn" } })!, /撤回/);
  assert.match(failureProblem({ ...failure, serverVerified: false })!, /核验/);
});
test("canonical JSON ignores object key order while material target revision remains bound", () => {
  assert.equal(canonical({ a: 1, b: 2 }), canonical({ b: 2, a: 1 }));
  assert.notEqual(canonical({ id: "synthetic-issue", revision: 1 }), canonical({ id: "synthetic-issue", revision: 2 }));
});
test("missing committed receipt remains unresolved even if host unknown flag has not yet updated", () => {
  assert.equal(unresolvedAction({ ...action, receipt: { outcome: "committed", receiptId: null, message: "合成缺失回执" } }), true);
  assert.equal(unresolvedAction({ ...action, receipt: { outcome: "unknown", receiptId: null, message: "合成未知" } }), true);
  assert.equal(unresolvedAction({ ...action, receipt: { outcome: "committed", receiptId: "synthetic-receipt", message: "合成已确认" } }), false);
});
test("merge preview cannot omit all preserved independent failures", () => {
  assert.match(previewProblem({ ...preview, preservedFailureKeys: [] }, mergeIntent, context, action.nowMs)!, /失败保留范围/);
});
