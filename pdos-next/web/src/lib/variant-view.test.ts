import assert from "node:assert/strict";
import test from "node:test";
import { nativeParentBlocker, nativeRebaseBlocker, nativeSpecBlocker, variantSpec, type Variant } from "./variant-view";
import type { DefinitionReadSpec, DefinitionRevision, DefinitionSpec } from "./product-view";

const spec: DefinitionSpec = { key: "pressure", parameter: "压力", value_type: "number", availability: "known",
  value: "0", lower: null, upper: null, text: null, unit: "Pa", tolerance: "0", test_conditions: ["固定台架"],
  method: "逐字原文", acceptance_criterion: "达到目标", nature: "decided", state: "proposed", owner_id: "human",
  reason: "实际依据", sources: [{ artifact_id: "source", expected_revision: 2, line: 3, quote: "原文零目标" }] };
function definition(id: string, revision: number, variant_id: string | null = null, overrides: Partial<DefinitionRevision> = {}): DefinitionRevision {
  return { id, revision, variant_id, product_id: "product", category_id: "category", status: "draft", sealed: false,
    source_status: "current", specs: [spec], ...overrides } as DefinitionRevision;
}
function modern(fields: Record<string, unknown>): DefinitionReadSpec { return { ...spec, ...fields } as DefinitionReadSpec; }
const product = { id: "product", category_id: "category" };
function variant(definition_id: string | null = null): Variant {
  return { id: "variant", revisions: [{ id: "revision", revision: 3, definition_id, parent_definition_id: "old", parent_revision: 1,
    effective_definition: { specs: [spec] } }] } as Variant;
}

test("legacy override projects only accepted business fields, preserving exact decimals and original references", () => {
  const input = { ...spec, tenant_id: "never-send", qualification: true,
    sources: [{ ...spec.sources[0], status: "active", receipt_id: "never-send" }] };
  const result = variantSpec(input);
  assert.deepEqual(Object.keys(result).sort(), ["key", "parameter", "value_type", "availability", "value", "lower", "upper", "text", "unit", "tolerance", "test_conditions", "method", "acceptance_criterion", "nature", "reason", "sources"].sort());
  assert.equal(result.value, "0"); assert.equal(result.tolerance, "0"); assert.deepEqual(result.sources, spec.sources);
  result.test_conditions.push("独立编辑"); assert.equal(input.test_conditions.length, 1);
  result.sources[0].quote = "编辑摘录"; assert.equal(input.sources[0].quote, "原文零目标");
});
test("complete typed facts and provenance cannot be silently lowered into NativeOverride", () => {
  for (const fields of [
    { value_type: "boolean", text: "false", value: null }, { value_type: "enum", text: "A", value: null },
    { parameter_id: "parameter", parameter_version: 2 }, { condition_note: "固定温度" }, { modality: "must" },
    { exceptions: [{ text: "例外" }] }, { applicable_variants: [{ key: "regional" }] },
    { source_refs: [{ type: "human", id: "person", version: 1, statement: "本人陈述" }] },
    { item_status: "confirmed" }, { origin: "ai_draft" }, { writer_id: "writer" }, { run_id: "run" },
    { confirmed_by: "person" }, { receipt_id: "receipt" }, { prepared_candidate_id: "candidate" },
  ]) {
    assert.match(nativeSpecBlocker(modern(fields))!, /定义条目.*立项提案/);
    assert.throws(() => variantSpec(modern(fields)), /完整规格或固定来源/);
  }
});
test("empty migration defaults preserve old shape, while unknown does not acquire a numeric zero", () => {
  const input = modern({ parameter_id: null, parameter_version: null, item_status: "unknown", condition_note: null,
    modality: null, exceptions: [], applicable_variants: [], source_refs: [], origin: "human", writer_id: null,
    run_id: null, confirmed_by: null, receipt_id: null, availability: "unknown", value: null, tolerance: null });
  const result = variantSpec(input); assert.equal(result.value, null); assert.equal(result.availability, "unknown");
  assert.equal(Object.hasOwn(result, "source_refs"), false); assert.equal(Object.hasOwn(result, "writer_id"), false);
});
test("latest parent is scoped to the same category, product and variant instead of list order", () => {
  const current = definition("current", 4, "base"), other = definition("other", 20, "other");
  const all = [other, definition("foreign-product", 50, "base", { product_id: "foreign" }),
    definition("foreign-category", 60, "base", { category_id: "foreign" }), current, definition("old", 3, "base")];
  assert.equal(nativeParentBlocker(current, all, product), null);
  assert.match(nativeParentBlocker(all[4], all, product)!, /最新定义/);
  assert.match(nativeParentBlocker(all[1], all, product)!, /当前型号/);
  assert.match(nativeParentBlocker(all[2], all, product)!, /当前型号/);
});
test("sealed, published, source-unavailable and modern parents do not enable Native derive", () => {
  for (const changes of [{ sealed: true }, { status: "published" }, { source_status: "needs_recheck" }, { specs: [modern({ modality: "must" })] }] as Partial<DefinitionRevision>[]) {
    const parent = definition("parent", 1, null, changes); assert.ok(nativeParentBlocker(parent, [parent], product));
  }
});
test("G0 comparison remains readable without permitting native rebase, and legacy rebase retains lineage checks", () => {
  const old = definition("old", 1), current = definition("current", 2);
  assert.match(nativeRebaseBlocker(variant("actual-g0-definition"), current, [old, current], product)!, /G0.*三方差异.*项目内变更/);
  assert.equal(nativeRebaseBlocker(variant(), current, [old, current], product), null);
  assert.match(nativeRebaseBlocker(variant(), old, [old], product)!, /较新的父定义/);
  const wrongLineage = definition("current", 2, "another");
  assert.match(nativeRebaseBlocker(variant(), wrongLineage, [old, wrongLineage], product)!, /谱系/);
  const modernOld = definition("old", 1, null, { specs: [modern({ condition_note: "保留原工况" })] });
  assert.match(nativeRebaseBlocker(variant(), current, [modernOld, current], product)!, /完整规格/);
});
