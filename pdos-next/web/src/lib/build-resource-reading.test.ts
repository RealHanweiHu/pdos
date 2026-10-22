import assert from "node:assert/strict";
import test from "node:test";
import type { Build } from "./build-preparation-view";
import type { ScopeDraft } from "./build-start-view";
import { resourceInspectBody, resourceReading } from "./build-resource-reading";

const build = { id: "build-1", revision: 2, project_id: "project-1", planned_quantity: "10.00000000", unit: "ea", manufacturing_configuration: { id: "process-1", revision: 3, operations: [{ key: "assembly", name: "装配" }] } } as unknown as Build;
const scope: ScopeDraft = { purpose: "内部试制", quantity: "10", unit: "ea", site: "SYN-LAB", start: "2030-01-01T10:00:00.123456Z", finish: "2030-01-01T11:00:00.234567Z", timezone: "UTC", reason: "本次理由不属于只读输入" };
const body = resourceInspectBody(build, scope, "assembly");
function known() {
  const resource = { id: "resource-1", revision: 4, kind: "fixture" };
  const originals = [{ artifact_id: "artifact-1", expected_revision: 2, line: 3, quote: "明确固定的资源使用声明" }];
  return {
    request: { scope: { tenant_id: "tenant-server", product_id: "product-1", project_id: build.project_id }, build: { id: build.id, revision: build.revision }, process: body.process, execution: body.execution, operation_key: "assembly", resource: null, fact: null },
    state: "known", current: true, nature: "synthetic", fact: { id: "fact-1", revision: 5 }, fact_sha256: "a".repeat(64), facts_revision: "b".repeat(64), valid_until: "2030-01-01T12:00:00Z", fact_valid_until: "2030-01-01T12:00:00Z",
    resources: [{ resource, lifecycle: "active", current: true, originals, acceptance: "unknown", calibration: "unknown", qualification: "unknown" }],
    relations: [{ build: { id: build.id, revision: build.revision }, process: body.process, operation_key: "assembly", resource, units: "0.00000001", relation: "operation_uses_resource", relation_source: { id: "fact-1", revision: 5, kind: "domain", position: "requirements[0].uses[0]" }, relation_originals: originals }],
    required_source_read_set: [{ artifact_id: "artifact-1", expected_revision: 2 }], gaps: ["NATIVE_ACCEPTANCE_OWNER_UNCONNECTED"], negative_enumeration_complete: false, execution_authorized: false,
  };
}
test("only the fixed build/process and explicit scope are sent, retaining microseconds", () => {
  assert.equal(body.expected_build_revision, 2); assert.deepEqual(body.process, { id: "process-1", revision: 3 });
  assert.equal(body.execution.window.start, scope.start); assert.equal(body.execution.quantity, "10");
  assert.equal(Object.hasOwn(body, "tenant_id"), false); assert.equal(Object.hasOwn(body, "reason"), false); assert.equal(Object.hasOwn(body, "authority"), false);
});
test("missing windows, unit conversion, reduced quantity and another process operation are refused", () => {
  for (const patch of [{ start: "" }, { quantity: "9" }, { unit: "kg" }]) assert.throws(() => resourceInspectBody(build, { ...scope, ...patch }, "assembly"));
  assert.throws(() => resourceInspectBody(build, scope, "other"));
});
test("complete relationships and all original references survive reading", () => {
  const value = known();
  value.required_source_read_set.push(...Array.from({ length: 19 }, (_, i) => ({ artifact_id: `basis-${i}`, expected_revision: 1 })));
  const result = resourceReading(value, "product-1", build, body);
  assert.equal(result.required_source_read_set.length, 20); assert.deepEqual(result.relations[0].relation_originals, value.relations[0].relation_originals);
  assert.equal(result.relations[0].units, "0.00000001"); assert.equal(result.execution_authorized, false);
});
test("a response from a different build, process, project or microsecond window is refused", () => {
  for (const change of [(v: ReturnType<typeof known>) => { v.request.build.revision++; }, (v: ReturnType<typeof known>) => { v.request.scope.project_id = "another"; }, (v: ReturnType<typeof known>) => { v.request.process = { ...body.process, revision: 99 }; }, (v: ReturnType<typeof known>) => { v.request.execution = { ...body.execution, window: { ...body.execution.window, start: "2030-01-01T10:00:00.123457Z" } }; }]) {
    const value = known(); change(value); assert.throws(() => resourceReading(value, "product-1", build, body));
  }
});
test("execution or native qualification cannot be inferred or injected through a reading", () => {
  const execution = { ...known(), execution_authorized: true };
  assert.throws(() => resourceReading(execution, "product-1", build, body));
  const qualification = known(); qualification.resources[0].qualification = "accepted";
  assert.throws(() => resourceReading(qualification, "product-1", build, body));
});
test("missing source reads or a relation belonging to another fact cannot be displayed as known", () => {
  const missing = known(); missing.required_source_read_set = [];
  assert.throws(() => resourceReading(missing, "product-1", build, body));
  const another = known(); another.relations[0].relation_source.id = "other-fact";
  assert.throws(() => resourceReading(another, "product-1", build, body));
});
test("hidden or absent basis remains unknown with no discovered resource identity", () => {
  const value = { ...known(), state: "unknown", current: false, nature: "unknown", fact: null, fact_sha256: null, resources: [], relations: [], required_source_read_set: [], valid_until: null, fact_valid_until: null };
  const result = resourceReading(value, "product-1", build, body);
  assert.equal(result.state, "unknown"); assert.equal(result.resources.length, 0); assert.equal(result.negative_enumeration_complete, false);
});
