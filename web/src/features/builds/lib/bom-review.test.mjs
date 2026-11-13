import assert from "node:assert/strict";
import { webcrypto } from "node:crypto";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

// Pure view helpers only; the difference, rules and conversion are the server's.
const ts = createRequire(import.meta.url)("typescript");
function load(url) {
  const loaded = { exports: {} };
  runInNewContext(ts.transpileModule(readFileSync(url, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: loaded, exports: loaded.exports, crypto: webcrypto });
  return loaded.exports;
}
const review = load(new URL("./bom-review.ts", import.meta.url));
const preparation = load(new URL("../../../lib/build-preparation-view.ts", import.meta.url));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const snapshot = (over = {}) => ({ part: "RD-1 / Housing", part_id: id(1), part_revision: 1, quantity: "2", unit: "pcs", loss_rate: null, critical: false, notes: null, reference_designators: ["R1"], ...over });

test("rule items read as places in the BOM or the original", () => {
  const duplicate = { code: "duplicate_designator", title: "重复位号", status: "fail", count: 1, items: [], explanation: "" };
  assert.equal(review.ruleItemText(duplicate, { designator: "C1", lines: [{ key: "a" }, { key: "b", row: 7 }], level: "fail" }), "C1：行 a、原件第 7 行");
  const quantity = { ...duplicate, code: "quantity" };
  assert.equal(review.ruleItemText(quantity, { key: "x", problem: "non_positive", value: "-1", level: "fail" }), "行 x：数量 -1 不是正数");
  assert.equal(review.ruleItemText(quantity, { key: "x", problem: "unknown", level: "warn" }), "行 x：用量未知");
  assert.equal(review.ruleItemText({ ...duplicate, code: "missing_unit" }, { key: "y", level: "warn" }), "行 y：用量与单位都未知");
  const alternate = { ...duplicate, code: "unqualified_alternate" };
  assert.equal(review.ruleItemText(alternate, { key: "a", alternate: "RD-9 / Cap", approval: "not_connected", level: "warn" }), "行 a：替代料 RD-9 / Cap（批准记录未接入）");
  assert.equal(review.ruleItemText(alternate, { key: "a", alternate: "RD-9", approval: "missing", level: "warn" }), "行 a：替代料 RD-9未经具名批准，齐套不计入");
  assert.equal(review.ruleStatusTitles.unknown, "暂不能判断");
  assert.equal(review.ruleItemText({ ...duplicate, code: "designator_quantity_mismatch" }, { key: "z", quantity: "3", designators: 2, level: "warn" }), "行 z：用量 3，位号 2 个");
});

test("values show unknowns and lists in words", () => {
  assert.equal(review.valueText("reference_designators", snapshot({ reference_designators: ["R1", "R2"] })), "R1、R2");
  assert.equal(review.valueText("reference_designators", snapshot({ reference_designators: [] })), "未填");
  assert.equal(review.valueText("alternates", snapshot({ alternates: [] })), "无");
  assert.equal(review.valueText("alternates", snapshot({ alternates: ["RD-9 / Cap"] })), "RD-9 / Cap");
  assert.equal(review.valueText("quantity", snapshot({ quantity: null })), "未知");
  assert.equal(review.valueText("part_revision", snapshot({ part_revision: null })), "新物料");
  assert.equal(review.valueText("critical", snapshot({ critical: true })), "是");
  assert.equal(review.quantityText(snapshot({ quantity: null })), "用量未知");
  assert.equal(review.valueText("quantity", null), "—");
});

test("review shape is checked before display", () => {
  const diff = { summary: { added: 1, removed: 0, changed: 0, unchanged: 0 }, lines: [{ key: "a", change: "added", fields: [], before: null, after: snapshot() }] };
  const rules = { ruleset: "bom-rules.v1", status: "pass", lines: 1, rules: [{ code: "quantity", title: "数量", status: "pass", count: 0, items: [], explanation: "" }], basis: "" };
  assert.equal(review.isReview({ bom: { name: "B", revision: 1 }, previous: null, diff, rules, import_basis: null }), true);
  assert.equal(review.isReview({ bom: { name: "B", revision: 1 }, previous: null, diff: { ...diff, summary: {} }, rules }), false);
  assert.equal(review.isRuleCard({ ...rules, rules: [{ ...rules.rules[0], status: "maybe" }] }), false);
});

test("import request and command carry the server conversion unchanged", () => {
  const body = review.importRequest({ artifactId: id(9), revision: 2, sheet: "BOM", headerRow: 2, columns: [{ field: "name", column: 1 }], dispositions: [{ row: 5, action: "skip", reason: "  ", drop_unresolved_alternates: true }, { row: 6, action: "reuse", part_id: id(3), expected_part_revision: 1 }, { row: 7, action: "accept", drop_unresolved_alternates: true }], previous: null, visibility: "private" });
  assert.deepEqual(JSON.parse(JSON.stringify(body.dispositions)), [
    { row: 5, action: "skip", part_id: null, expected_part_revision: null, reason: null, drop_unresolved_alternates: false },
    { row: 6, action: "reuse", part_id: id(3), expected_part_revision: 1, reason: null, drop_unresolved_alternates: false },
    { row: 7, action: "accept", part_id: null, expected_part_revision: null, reason: null, drop_unresolved_alternates: true },
  ]);
  const lines = [{ key: "RD-1", part_id: null }];
  const result = { complete: true, payload: { lines, import_basis: { format: "xlsx" }, sources: [{ artifact_id: id(9), expected_revision: 2, line: 2, quote: "料号" }], required_source_read_set: [{ artifact_id: id(9), expected_revision: 2 }] } };
  const command = review.importCommand({ productId: id(1), productRevision: 3, name: " BOM v2 ", reason: "按回传更新", visibility: "private", previous: { id: id(4), revision: 1, required_source_read_set: [{ artifact_id: id(8), expected_revision: 1 }] }, result });
  assert.equal(command.operation, "engineering.bom.revise");
  assert.equal(command.payload.lines, lines);
  assert.equal(command.payload.name, "BOM v2");
  assert.deepEqual(JSON.parse(JSON.stringify(command.source_read_set)).map(r => r.artifact_id), [id(8), id(9)]);
  assert.throws(() => review.importCommand({ productId: id(1), productRevision: 3, name: "BOM", reason: "ok!", visibility: "private", previous: null, result: { ...result, complete: false } }), /未处置/);
  assert.throws(() => review.mergeReads([{ artifact_id: id(9), expected_revision: 1 }], [{ artifact_id: id(9), expected_revision: 2 }]), /不同版本/);
  assert.equal(review.pendingRows({ rows: [{ row: 3, status: "ready" }, { row: 4, status: "needs_disposition" }] }).length, 1);
});

test("manual designators split and expand like the import", () => {
  assert.deepEqual(JSON.parse(JSON.stringify(preparation.parseDesignators("R1-R3, C5；U1A"))), ["R1", "R2", "R3", "C5", "U1A"]);
  assert.deepEqual(JSON.parse(JSON.stringify(preparation.parseDesignators(""))), []);
  assert.throws(() => preparation.parseDesignators("R5-R1", "电阻"), /电阻位号范围 R5-R1/);
  assert.throws(() => preparation.parseDesignators("中文"), /无法识别/);
  const line = { ...preparation.blankBomLine(1), name: "Resistor", designators: "R1,R2" };
  assert.deepEqual(JSON.parse(JSON.stringify(preparation.bomLinesPayload([line], [])[0].reference_designators)), ["R1", "R2"]);
  const withAlternate = { ...line, alternates: [{ partId: id(5), partRevision: 1, label: "RD-9" }] };
  assert.deepEqual(JSON.parse(JSON.stringify(preparation.bomLinesPayload([withAlternate], [])[0].alternates)), [{ part_id: id(5), expected_part_revision: 1 }]);
  // Drafts saved before these fields existed still produce a valid payload.
  const old = { ...preparation.blankBomLine(2), name: "Old draft" }; delete old.designators; delete old.alternates;
  assert.deepEqual(JSON.parse(JSON.stringify(preparation.bomLinesPayload([old], [])[0].reference_designators)), []);
});
