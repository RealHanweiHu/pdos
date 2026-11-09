import test from "node:test";
import assert from "node:assert/strict";
import { breachLabels, percent, ruleSummary, sampleShortfall, type QualityRule } from "./skill-quality";

const rule: QualityRule = { key: "withdrawal", label: "撤回率", window: 20, limit: 0.05, definition: "", gating: true, state: "breached", sample: 20, count: 2, rate: 0.1, reason: null };

test("rates format without inventing a value when the window is empty", () => {
  assert.equal(percent(0.1), "10.0%");
  assert.equal(percent(1 / 3), "33.3%");
  assert.equal(percent(null), "—");
  assert.equal(percent(Number.NaN), "—");
});

test("rule summaries say whether a threshold steps T0 back or is a value metric only", () => {
  assert.equal(ruleSummary(rule), "撤回率：2/20（10.0%） · 阈值 >5.0% · 最近 20 次 · 超过阈值 · 触发降回一次确认");
  assert.match(ruleSummary({ ...rule, gating: false, state: "insufficient", sample: 7, count: 1, rate: 1 / 7 }), /样本不足（N\/A） · 只作价值指标/);
  assert.match(ruleSummary({ ...rule, key: "framework_check", state: "unavailable", sample: 0, count: 0, rate: null }), /：— · /);
  assert.equal(breachLabels.unavailable, "指标读取失败，按未通过处理");
});

test("weekly spot-check shortfall is computed from the server's own counts", () => {
  const weeks = [{ week_start: "2026-11-02", runs: 1, sampled: 1, required: 1 }, { week_start: "2026-11-09", runs: 9, sampled: 1, required: 2 }];
  assert.deepEqual(sampleShortfall({ rule: "", weeks, runs: [] }), ["2026-11-09"]);
});
