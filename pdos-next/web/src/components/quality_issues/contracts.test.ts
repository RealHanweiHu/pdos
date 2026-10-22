import assert from "node:assert/strict";
import test from "node:test";
import { canonical, failureProblem, operationProblem, previewProblem, unresolvedAction } from "./contracts";
import { editorIntent, EMPTY_FIELDS, sourceKey } from "./editor";
import { action, context, failure, issue, mergeIntent, preview, source } from "./__tests__/fixtures";

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
test("creation does not take delivery or unrelated revision as stable business failure identity", () => {
  const fields = { ...EMPTY_FIELDS, text: "合成问题", selectedId: failure.failureKey };
  const first = editorIntent("quality.issue.create", fields, null, [failure], [], context).intent;
  const repeated = editorIntent("quality.issue.create", fields, null, [{ ...failure, run: { ...failure.run, revision: 99 }, eventId: "synthetic-second-delivery" }], [], context).intent;
  assert.ok(first?.operation === "quality.issue.create" && repeated?.operation === "quality.issue.create");
  assert.equal(first.failureKey, repeated.failureKey);
  assert.equal(first.runId, repeated.runId);
  assert.equal(first.measurementId, repeated.measurementId);
  assert.notEqual(first.eventId, repeated.eventId);
});
test("source selection binds exact position as well as revision", () => {
  const fields = { ...EMPTY_FIELDS, text: "合成根因结论", sourceId: sourceKey({ ...source, position: "其他位置" }) };
  assert.match(editorIntent("quality.issue.root_cause.decide", fields, issue, [], [], context).problem!, /固定来源/);
});
test("merge preserves exact source version and blocks audience expansion without title matching", () => {
  const original = { ...issue, id: "synthetic-other-issue", revision: 8, failures: [{ ...failure, failureKey: "synthetic-independent-failure" }] };
  const fields = { ...EMPTY_FIELDS, text: "合成归并说明", selectedId: original.id };
  const result = editorIntent("quality.issue.merge", fields, issue, [], [original], context);
  assert.ok(result.intent?.operation === "quality.issue.merge");
  assert.deepEqual(result.intent.sourceIssues, [{ id: original.id, revision: 8 }]);
  assert.equal(original.failures[0].failureKey, "synthetic-independent-failure");
  assert.match(editorIntent("quality.issue.merge", fields, issue, [], [{ ...original, audience: ["other-client"] }], context).problem!, /受众/);
  assert.match(editorIntent("quality.issue.merge", fields, { ...issue, audience: ["internal", "client"] }, [], [original], context).problem!, /扩大任一/);
});
test("completed measures and AI hypothesis cannot imply effective closure", () => {
  const fields = { ...EMPTY_FIELDS, text: "合成关闭" };
  assert.match(editorIntent("quality.issue.close", fields, issue, [], [], context).problem!, /独立有效性/);
  const decided = { ...issue, capa: { ...issue.capa!, effectiveness: { text: "合成有效", actorId: "synthetic-reviewer", actorLabel: "合成具名人", decidedAt: "2026-10-02T17:00:00Z", sources: [source], result: "effective" as const, independent: true, verificationRuns: context.independentVerificationRuns } } };
  assert.equal(editorIntent("quality.issue.close", fields, decided, [], [], context).problem, null);
  assert.match(editorIntent("quality.issue.close", fields, { ...decided, requiresRecheck: true }, [], [], context).problem!, /待重核/);
  assert.match(editorIntent("quality.issue.close", fields, { ...decided, capa: { ...decided.capa, effectiveness: { ...decided.capa.effectiveness, independent: false } } }, [], [], context).problem!, /独立有效性/);
});
test("effectiveness accepts only server-projected independent and current evidence IDs", () => {
  const fields = { ...EMPTY_FIELDS, text: "合成有效性结论", evidenceIds: ["synthetic-verification-evidence"] };
  assert.equal(editorIntent("quality.capa.effectiveness.decide", fields, issue, [], [], context).problem, null);
  assert.match(editorIntent("quality.capa.effectiveness.decide", fields, issue, [], [], { ...context, verificationEvidence: context.verificationEvidence.map(value => ({ ...value, independent: false })) }).problem!, /自证/);
  assert.match(editorIntent("quality.capa.effectiveness.decide", fields, issue, [], [], { ...context, independentVerificationRuns: [] }).problem!, /独立复验/);
});
test("CAPA draft contains unexecuted corrective action and complete fixed verification requirement", () => {
  const fields = { ...EMPTY_FIELDS, text: "合成假设", actionText: "合成措施", ownerId: "synthetic-executor", sourceId: sourceKey(source), method: "合成复验方法", acceptance: "合成原判据", observationUntil: "2026-10-10T17:00:00-07:00" };
  const result = editorIntent("quality.capa.draft", fields, issue, [], [], context);
  assert.ok(result.intent?.operation === "quality.capa.draft");
  assert.deepEqual(result.intent.requirement.requiredFailureIds, [failure.failureKey]);
  assert.equal("completion" in result.intent.actions[0], false);
  assert.match(editorIntent("quality.capa.draft", { ...fields, observationUntil: "2026-10-10T17:00:00" }, issue, [], [], context).problem!, /时区/);
  assert.match(editorIntent("quality.capa.draft", fields, issue, [], [], { ...context, draftIds: null }).problem!, /待接入/);
});
test("actual containment must retain named executor, source and happened-at timezone", () => {
  const fields = { ...EMPTY_FIELDS, text: "合成遏制", ownerId: "synthetic-executor", sourceId: sourceKey(source), occurredAt: "2026-10-02T09:00:00-07:00", timezone: "America/Los_Angeles" };
  const result = editorIntent("quality.issue.containment.record", fields, issue, [], [], context);
  assert.ok(result.intent?.operation === "quality.issue.containment.record");
  assert.equal(result.intent.action.at.source.position, source.position);
  assert.equal(result.intent.action.executorId, fields.ownerId);
  assert.match(editorIntent("quality.issue.containment.record", { ...fields, timezone: "Bogus/Time" }, issue, [], [], context).problem!, /IANA/);
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
test("withdrawn fixed criterion blocks creation and subsequent effectiveness", () => {
  assert.match(failureProblem({ ...failure, criterion: { ...failure.criterion, status: "withdrawn" } })!, /撤回/);
  assert.match(editorIntent("quality.capa.effectiveness.decide", { ...EMPTY_FIELDS, text: "合成决定", evidenceIds: ["synthetic-verification-evidence"] }, { ...issue, failures: [{ ...failure, criterion: { ...failure.criterion, status: "withdrawn" } }] }, [], [], context).problem!, /待重核/);
});
