/** Synthetic records exclusively for isolated checks. Business components never import these. */
import type { BuildRef, Coverage, EventTime, MeasurementInput, PreparedVerificationAction, SampleRef, SourcePosition, TestRun, VerificationContext, VerificationIntent, VerificationRequest } from "../contracts";

export const source: SourcePosition = { originalId: "synthetic-original", revision: 1, kind: "original", locator: "lines:1-2" };
export const build: BuildRef = { id: "synthetic-build", revision: 1, projectId: "synthetic-project", productId: "synthetic-product", engineeringConfiguration: { id: "engineering-plan", revision: 1 }, manufacturingConfiguration: { id: "manufacturing-plan", revision: 2 } };
export const sampleA: SampleRef = { id: "sample-a", revision: 1, label: "合成样件 A", buildId: build.id, actualConfiguration: { id: "actual-a", revision: 3 }, cavity: "1", availability: "available", source };
export const sampleB: SampleRef = { ...sampleA, id: "sample-b", label: "合成样件 B", actualConfiguration: { id: "actual-b", revision: 1 }, cavity: "2" };
export const coverageA: Coverage = { sampleIds: [sampleA.id], testItemIds: ["test-a"], pairs: [{ sampleId: sampleA.id, testItemId: "test-a" }] };
export const request: VerificationRequest = {
  id: "request-a", revision: 2, title: "合成试模验证", status: "offered", build, material: "合成材料", expectedAt: null, expectedTimezone: null, returnFormat: "逐项原始记录", methodPreparation: "方法候选已准备", tentativeWindow: "仅为暂定",
  testItems: [
    { id: "test-a", title: "合成尺寸", method: { id: "method-a", revision: 1, title: "合成尺寸方法", criterion: "1～2", unit: "mm", conditions: "23℃", equipmentRequirement: "量具", sampleQuantity: 1, cavities: ["1"], destructive: false, source }, documentIds: ["doc-a"] },
    { id: "test-b", title: "合成破坏测试", method: { id: "method-b", revision: 1, title: "合成破坏方法", criterion: "不破损", unit: "N", conditions: "干燥", equipmentRequirement: "试验机", sampleQuantity: 2, cavities: ["1", "2"], destructive: true, source }, documentIds: ["doc-b"] },
  ],
  documents: [{ id: "doc-a", revision: 1, title: "合成当前图纸", status: "current", source, affectedTestItemIds: ["test-a"] }, { id: "doc-b", revision: 1, title: "合成漂移图纸", status: "stale", source, affectedTestItemIds: ["test-b"] }],
  offeredCoverage: { sampleIds: [sampleA.id, sampleB.id], testItemIds: ["test-a", "test-b"], pairs: [{ sampleId: sampleA.id, testItemId: "test-a" }, { sampleId: sampleB.id, testItemId: "test-b" }] }, acceptedCoverage: null,
  times: [{ kind: "sample_ready", at: "2026-10-02T01:00:00Z", timezone: "Asia/Shanghai", source, scope: "sample-a" }],
};
export const context: VerificationContext = { version: "synthetic-watermark", portReady: true, executor: { id: "server-human", label: "合成具名人员" }, startResources: { equipment: [{ ...source, originalId: "equipment-a", kind: "equipment" }], calibration: [{ ...source, originalId: "calibration-a", kind: "calibration" }] }, capabilities: { offer: true, accept: true, returnItems: true, planRun: true, startRun: true, recordResults: true } };
export const run: TestRun = { id: "run-a", revision: 1, requestId: request.id, title: "合成测试 Run", status: "planned", result: "pending", samples: [sampleA], coverage: coverageA, measurements: [], times: [], incompleteTestItemIds: ["test-a"] };
export const measurement: MeasurementInput = { testItemId: "test-a", sample: sampleA, rawValue: "001.2300", unit: "mm", conditions: "23℃", equipment: "量具原件 v1", environment: "23℃，干燥", observedAt: "2026-10-02T09:00:00+08:00", originalTimezone: "Asia/Shanghai", method: { id: "method-a", revision: 1 }, sourcePosition: source, missing: [], note: "原始字符串" };
export const eventTime: EventTime = { occurredAt: "2026-10-02T09:00:00+08:00", originalTimezone: "Asia/Shanghai", source };
export const intent: VerificationIntent = { action: "handoff.accept", time: eventTime, request: { id: request.id, revision: request.revision }, build, samples: [sampleA], coverage: coverageA, partialReason: "按明确部分范围接收", nextOwnerId: "next-person", returnedItems: [{ kind: "coverage", id: "sample-b:test-b", reason: "资料漂移", nextOwnerId: "next-person" }] };
export function prepared(contextKey: string): PreparedVerificationAction { return { token: "synthetic-token", digest: "synthetic-digest", expiresAt: "2026-10-03T00:00:00Z", contextKey, intent, scope: { projectId: build.projectId, productId: build.productId, request: intent.request, samples: [sampleA], coverage: coverageA }, allowed: true, summary: "只接收样件 A 与尺寸测试对应范围", missing: [] }; }
