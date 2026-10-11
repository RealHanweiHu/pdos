import assert from "node:assert/strict";
import test from "node:test";
import { emptyItem, itemProblem, itemSummary } from "./definition-item-editor";
import { specificationValue, type DefinitionReadSpec } from "./product-view";
import { numericShapeProblem, numericValueText } from "./spec-bound-values";

test("source bounds display as explicit constraints without a fabricated endpoint", () => {
  assert.equal(numericValueText(null, null, "75"), "≤75");
  assert.equal(numericValueText(null, "0", null), "≥0");
  assert.equal(numericValueText(null, null, "0"), "≤0");
  assert.equal(numericValueText(null, "-5.25", "0"), "-5.25 ～ 0");
  assert.equal(numericValueText("0", null, null), "0");
  assert.equal(numericValueText(null, null, null), "未知");
});

test("the dictionary number type accepts bounds and rejects mixed scalar or missing values", () => {
  for (const type of ["number", "range"]) {
    assert.equal(numericShapeProblem(type, null, null, "75"), null);
    assert.equal(numericShapeProblem(type, null, "0", null), null);
    assert.ok(numericShapeProblem(type, "0", null, "75"));
    assert.ok(numericShapeProblem(type, null, null, null));
    assert.ok(numericShapeProblem(type, null, null, "75", "unrelated text"));
  }
  assert.equal(numericShapeProblem("number", "0", null, null), null);
  assert.ok(numericShapeProblem("range", "0", null, null));
});

test("item and full-definition views preserve number-bound identity and exact decimal display", () => {
  const item = { ...emptyItem(), key: "noise_level", parameter: "噪声", availability: "known" as const,
    upper: "75.000000000000", unit: "dB(A)", exceptions: [{ text: "启动后三秒除外" }] };
  assert.equal(itemProblem(item, []), null);
  assert.equal(itemSummary(item), "≤75.000000000000 dB(A)");
  const displayed = specificationValue({ ...item, value_type: "number", text: null, sources: [],
    method: null, state: "needs_confirmation", origin: "human", writer_id: "owner", run_id: null,
    confirmed_by: null, receipt_id: null, source_refs: [] } as DefinitionReadSpec);
  assert.equal(displayed.trim(), "≤75 dB(A)");
  assert.deepEqual(item.exceptions, [{ text: "启动后三秒除外" }]);
  assert.equal(item.lower, null); assert.equal(item.value, null);
});
