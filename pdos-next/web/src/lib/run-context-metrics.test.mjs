import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
const directory = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.join(directory, "../../package.json")), ts = dependency("typescript");
const filename = path.join(directory, "run-context-metrics.ts"), loaded = new Module(filename);
loaded.require = dependency;
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, filename);
const data = loaded.exports;

test("unknown tokens, cache defaults and nonfinite values never become measured zero or charged totals", () => {
  for (const value of [null, undefined, NaN, Infinity, -1]) assert.equal(data.metricNumber(value), "未知");
  assert.equal(data.metricNumber(0), "0");
  assert.equal(data.metricNumber(26000), "26,000");
  for (const value of [0, null, undefined, NaN]) assert.equal(data.metricCacheTokens(value), "未知");
  assert.equal(data.metricCacheTokens(5000), "5,000");
  assert.equal(data.metricPercent(.25), "25%");
  assert.equal(data.metricPercent(null), "未知");
});
test("carry summary reports the actual loaded snapshot and new omissions without claiming old omissions disappeared", () => {
  assert.equal(data.contextCarrySummary({ history: { carried: 3 }, work_state: { revision: 7 }, reductions_count: 2 }), "携带历史 3 轮 · 工作状态第 7 版 · 本次新增省略 2 项");
  assert.match(data.contextCarrySummary({ history: null, work_state: null, reductions_count: null }), /历史 未知 轮/);
});
test("metric selection keeps legacy process silent and never treats provider text as a metric", () => {
  const real = { kind: "context_observed", context_metrics: { version: 1 } };
  assert.deepEqual(data.contextMetricSteps([real, { kind: "text_delta", context_metrics: { version: 1, text: "PRIVATE" } }, { kind: "context_observed" }, { kind: "context_observed", context_metrics: { version: 2 } }]), [real]);
  assert.deepEqual(data.contextMetricSteps([]), []);
});
test("only four server warnings and controlled reasons are named, unknown text is not a new warning or label", () => {
  assert.equal(Object.keys(data.warningLabels).length, 4);
  assert.match(data.cleanupReason("insufficient_eligible_tokens"), /不足 20%F.*保留/);
  assert.equal(data.cleanupReason("PRIVATE body"), "原因未记录");
  assert.equal(data.reductionLabel("PRIVATE body"), "已记录的省略动作");
  assert.equal(data.metricField("PRIVATE body"), "字段未知");
  assert.equal(data.metricField("PRIVATE"), "字段未知");
  assert.equal(data.metricField("work_state.constraints"), "约束");
});
