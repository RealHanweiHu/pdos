import assert from "node:assert/strict";
import test from "node:test";
import { isLatestDefinition, specificationValue, type DefinitionRevision, type DefinitionReadSpec } from "./product-view";

test("typed definitions display false, enum, exact zero and unknown without truthiness loss", () => {
  const spec = { availability: "known", value_type: "boolean", text: "false" } as DefinitionReadSpec;
  assert.equal(specificationValue(spec), "否");
  assert.equal(specificationValue({ ...spec, value_type: "enum", text: "matte" }), "matte");
  assert.equal(specificationValue({ ...spec, value_type: "number", value: "0.000000000000", tolerance: null, unit: "PSI" }).trim(), "0 PSI");
  assert.equal(specificationValue({ ...spec, availability: "unknown" }), "未知 / 待确认");
});

test("a newer definition in another variant, product or category is not this definition's successor", () => {
  const base = { category_id: "category", product_id: "product", variant_id: null, revision: 3 } as DefinitionRevision;
  const others = [
    { ...base, variant_id: "variant", revision: 20 },
    { ...base, product_id: "other", revision: 30 },
    { ...base, category_id: "other", revision: 40 },
  ];
  assert.equal(isLatestDefinition(base, others), true);
  assert.equal(isLatestDefinition(base, [...others, { ...base, revision: 4 }]), false);
});
