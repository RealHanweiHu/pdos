import assert from "node:assert/strict";
import test from "node:test";
import { coverageGaps, eventTimeProblems, fixedContextKey, handoffProblems, incompleteResultItems, measurementProblems, previewProblem, resultStatusNames, runStatusNames, startProblems, type MeasurementInput } from "./contracts";
import { context, coverageA, eventTime, intent, measurement, prepared, request, run, sampleA, sampleB, source } from "./__tests__/fixtures";

const clock = Date.parse("2026-10-02T02:00:00Z");
const key = fixedContextKey(context, request, [sampleA, sampleB]);

test("partial reception covers only explicit pairs and preserves next responsibility", () => {
  assert.deepEqual(handoffProblems(request, [sampleA, sampleB], coverageA, intent.action === "handoff.accept" ? intent.returnedItems : [], "handoff.accept"), []);
  assert.match(handoffProblems(request, [sampleA, sampleB], coverageA, [], "handoff.accept").join(" "), /逐项记录/);
});

test("documents affect only their declared tests, and do not prove physical readiness", () => {
  const coverageB = { sampleIds: [sampleB.id], testItemIds: ["test-b"], pairs: [{ sampleId: sampleB.id, testItemId: "test-b" }] };
  assert.match(handoffProblems(request, [sampleA, sampleB], coverageB, [], "handoff.accept").join(" "), /资料尚未齐套/);
  assert.match(handoffProblems(request, [{ ...sampleA, availability: "unknown" }], coverageA, [], "handoff.accept").join(" "), /当前可用性/);
  assert.match(handoffProblems(request, [], coverageA, [], "handoff.accept").join(" "), /真实配置/);
});

test("incomplete documentation can be offered, while acceptance still blocks affected tests", () => {
  const partial = { sampleIds: [sampleB.id], testItemIds: ["test-b"], pairs: [{ sampleId: sampleB.id, testItemId: "test-b" }] };
  assert.deepEqual(handoffProblems(request, [sampleA, sampleB], partial, [], "handoff.offer"), []);
  assert.match(handoffProblems(request, [sampleA, sampleB], partial, [], "handoff.accept").join(" "), /资料尚未齐套/);
});

test("accepting every offered pair still requires a reason for remaining original quantity gaps", () => {
  const limited = { ...request, testItems: [{ ...request.testItems[0], method: { ...request.testItems[0].method, sampleQuantity: 2, cavities: ["1", "2"] } }], documents: [request.documents[0]], offeredCoverage: coverageA };
  assert.match(handoffProblems(limited, [sampleA], coverageA, [], "handoff.accept").join(" "), /数量或模穴仍有差距/);
  assert.deepEqual(handoffProblems(limited, [sampleA], coverageA, [], "handoff.accept", "真实样件按明确部分范围接收", "next-person"), []);
});

test("second partial reception excludes already accepted pairs from returns and duplicate acceptance", () => {
  const continued = { ...request, status: "accepted" as const, acceptedCoverage: coverageA, documents: request.documents.map(doc => ({ ...doc, status: "current" as const })) };
  const next = { sampleIds: [sampleB.id], testItemIds: ["test-b"], pairs: [{ sampleId: sampleB.id, testItemId: "test-b" }] };
  assert.deepEqual(handoffProblems(continued, [sampleA, sampleB], next, [], "handoff.accept", "原请求剩余样件待补", "next-person"), []);
  assert.match(handoffProblems(continued, [sampleA, sampleB], coverageA, [], "handoff.accept").join(" "), /重复接收/);
  assert.match(handoffProblems(continued, [sampleA, sampleB], coverageA, [{ kind: "coverage", id: "sample-a:test-a", reason: "错误退回", nextOwnerId: "next-person" }], "handoff.return").join(" "), /尚未接收/);
});

test("planned configuration cannot stand in for actual configuration or a source", () => {
  assert.match(handoffProblems(request, [{ ...sampleA, actualConfiguration: { id: "", revision: 0 } }], coverageA, [], "handoff.offer").join(" "), /真实配置/);
  assert.match(handoffProblems(request, [{ ...sampleA, source: null }], coverageA, [], "handoff.offer").join(" "), /来源/);
});

test("selected IDs without explicit pair coverage are rejected", () => {
  assert.match(handoffProblems(request, [sampleA], { ...coverageA, pairs: [] }, [], "handoff.offer").join(" "), /对应覆盖/);
});

test("expired, edited or drifted previews cannot be confirmed", () => {
  assert.equal(previewProblem(prepared(key), intent, key, clock), null);
  assert.match(previewProblem(prepared(key), intent, key, Date.parse("2026-10-03T00:00:00Z")) ?? "", /过期/);
  assert.match(previewProblem(prepared(key), { ...intent, request: { id: request.id, revision: 3 } }, key, clock) ?? "", /变化/);
  const driftedKey = fixedContextKey(context, request, [{ ...sampleA, actualConfiguration: { id: "actual-a", revision: 4 } }, sampleB]);
  assert.match(previewProblem(prepared(key), intent, driftedKey, clock) ?? "", /变化/);
});

test("port and role drift invalidate snapshots even when caller watermark is unchanged", () => {
  assert.notEqual(key, fixedContextKey({ ...context, portReady: false }, request, [sampleA, sampleB]));
  assert.notEqual(key, fixedContextKey({ ...context, capabilities: { ...context.capabilities, accept: false } }, request, [sampleA, sampleB]));
});

test("rejected ports, enlarged scopes and changed pair scopes block confirmation", () => {
  assert.match(previewProblem({ ...prepared(key), allowed: false }, intent, key, clock) ?? "", /不可办理/);
  assert.match(previewProblem({ ...prepared(key), missing: [{ kind: "integration", blocking: true, description: "无真实样件 port" }] }, intent, key, clock) ?? "", /阻塞/);
  assert.match(previewProblem({ ...prepared(key), scope: { ...prepared(key).scope, samples: [sampleA, sampleB] } }, intent, key, clock) ?? "", /实际样件/);
  assert.match(previewProblem({ ...prepared(key), scope: { ...prepared(key).scope, coverage: { ...coverageA, pairs: [] } } }, intent, key, clock) ?? "", /对应范围/);
});

test("measurement preserves its raw string and validates exact sample and method versions", () => {
  assert.deepEqual(measurementProblems(measurement, run, request), []);
  assert.equal(measurement.rawValue, "001.2300");
  assert.match(measurementProblems({ ...measurement, sample: { ...sampleA, actualConfiguration: { id: "actual-a", revision: 4 } } }, run, request).join(" "), /固定版本/);
  assert.match(measurementProblems({ ...measurement, method: { id: "method-a", revision: 2 } }, run, request).join(" "), /方法版本/);
});

test("unknown readings require explicit missing fields and never infer pass", () => {
  const unknown: MeasurementInput = { ...measurement, rawValue: "", unit: "", conditions: "", equipment: "", environment: "", observedAt: null, originalTimezone: null, method: null, sourcePosition: null, missing: ["rawValue", "unit", "conditions", "equipment", "environment", "method", "sourcePosition", "observedAt", "originalTimezone"] };
  assert.deepEqual(measurementProblems(unknown, run, request), []);
  assert.match(measurementProblems({ ...unknown, missing: [] }, run, request).join(" "), /明确声明缺项/);
  assert.equal("computedResult" in unknown, false);
});

test("source gaps and contradictory known/missing declarations are rejected", () => {
  assert.match(measurementProblems({ ...measurement, sourcePosition: { ...source, revision: Number.NaN } }, run, request).join(" "), /有效版本/);
  assert.match(measurementProblems({ ...measurement, missing: ["rawValue"] }, run, request).join(" "), /原始读数/);
});

test("missing or unzoned observation time cannot be silently replaced with submit time", () => {
  assert.match(measurementProblems({ ...measurement, observedAt: null }, run, request).join(" "), /真实观测时间/);
  assert.match(measurementProblems({ ...measurement, observedAt: "2026-10-02T09:00:00" }, run, request).join(" "), /时区偏移/);
  assert.match(measurementProblems({ ...measurement, originalTimezone: "factory-unknown" }, run, request).join(" "), /IANA/);
});

test("partial result completion follows the exact run pairs rather than a cartesian guess", () => {
  const partialRun = { ...run, samples: [sampleA, sampleB], coverage: { sampleIds: [sampleA.id, sampleB.id], testItemIds: ["test-a", "test-b"], pairs: [{ sampleId: sampleA.id, testItemId: "test-a" }, { sampleId: sampleB.id, testItemId: "test-b" }] } };
  assert.deepEqual(incompleteResultItems(partialRun, [measurement]), ["test-b"]);
  assert.deepEqual(incompleteResultItems(run, [measurement]), []);
});

test("one run can cover a valid subset while retaining original quantity and cavity gaps", () => {
  const gaps = coverageGaps(request, [sampleA], coverageA);
  assert.match(gaps.join(" "), /合成破坏测试/);
  assert.match(gaps.join(" "), /0\/2/);
  assert.match(gaps.join(" "), /1、2/);
});

test("execution statuses and result outcomes remain distinct dimensions", () => {
  assert.equal("pass" in runStatusNames, false);
  assert.equal("running" in resultStatusNames, false);
  assert.equal(runStatusNames.results_pending, "等待结果核对");
  assert.equal(resultStatusNames.indeterminate, "不确定");
});

test("real event times need offset, original timezone and a fixed source", () => {
  assert.deepEqual(eventTimeProblems(eventTime, "部分返回"), []);
  assert.match(eventTimeProblems({ ...eventTime, occurredAt: "2026-10-02T09:00:00" }, "部分返回").join(" "), /时区偏移/);
  assert.match(eventTimeProblems({ ...eventTime, originalTimezone: "factory-unknown" }, "部分返回").join(" "), /IANA/);
  assert.match(eventTimeProblems({ ...eventTime, source: { ...source, locator: "" } }, "部分返回").join(" "), /精确位置/);
});

test("named start binds the current server actor and server resource versions", () => {
  const execution = { equipment: context.startResources.equipment[0], calibration: context.startResources.calibration[0], executorId: "server-human", environment: "23℃", conditions: "干燥" };
  assert.deepEqual(startProblems({ time: eventTime, execution }, context), []);
  assert.match(startProblems({ time: eventTime, execution: { ...execution, executorId: "payload-admin" } }, context).join(" "), /当前具名身份/);
  assert.match(startProblems({ time: eventTime, execution: { ...execution, calibration: { ...execution.calibration, revision: 2 } } }, context).join(" "), /固定来源版本/);
});
