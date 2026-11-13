import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Installed compiler only; no Next build, service, shared cache or external data.
const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, "../../../..");
const dependency = createRequire(path.join(root, "package.json"));
const ts = dependency("typescript");
const React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const cache = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (!filename) throw new Error("Owned test module not found");
  if (cache.has(filename)) return cache.get(filename).exports;
  const mod = new Module(filename);
  cache.set(filename, mod);
  const requireLocal = createRequire(filename);
  mod.require = specifier => specifier.startsWith("@/") ? load(path.join(root, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : requireLocal(specifier);
  mod._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return mod.exports;
}

const { SkillQualityBody, SkillQualityHoldsBanner } = load(path.join(root, "src/features/settings/model-configuration/skill-quality.tsx"));
const metrics = { runs_window: 20, runs_withdrawn: 2, writes_window: 20, writes_changed: 3, writes_withdrawn: 2, withdrawal_rate: 0.1, modification_rate: 0.15, retention_rate: 0.9, untouched_rate: 0.75 };
const rule = (key, label, state, gating, extra = {}) => ({ key, label, window: 20, limit: 0.05, definition: "", gating, state, sample: 20, count: 2, rate: 0.1, reason: null, ...extra });
const view = {
  skill_key: "public_research",
  definitions: { withdrawal_rate: "撤回口径", modification_rate: "修改口径", retention_rate: "保留口径", untouched_rate: "原样口径", granularity: "对象级" },
  groups: [{ skill_version: "1.0.0", model_version: "synthetic-model", runs_total: 20, writes_total: 20, first_at: null, last_at: null, metrics }],
  current: {
    skill_version: "1.0.0", model_version: "synthetic-model", since: "2026-11-09T00:00:00Z", metrics, breach: "withdrawal",
    rules: [rule("withdrawal", "撤回率", "breached", true), rule("framework_check", "框架检查失败率", "unavailable", false, { sample: 0, count: 0, rate: null, reason: "框架检查器尚未接入" })],
    basis: { withdrawal: ["run-a", "run-b"], modification: [] },
    spot_check: { rule: "20% 抽样", weeks: [{ week_start: "2026-11-09", runs: 20, sampled: 1, required: 2 }], runs: [{ run_id: "run-a", first_at: "2026-11-09T01:00:00Z", week_start: "2026-11-09", reason: "weekly_minimum" }] },
  },
  model_judgement: false,
};

test("a crossed threshold is shown as a step back to one confirmation with its basis runs", () => {
  const html = renderToStaticMarkup(React.createElement(SkillQualityBody, { view }));
  assert.match(html, /撤回率超过阈值，自动写入已降回一次确认，待重新审阅/);
  assert.match(html, /撤回率：2\/20（10\.0%） · 阈值 &gt;5\.0% · 最近 20 次 · 超过阈值 · 触发降回一次确认/);
  assert.match(html, /框架检查器尚未接入/);
  assert.match(html, /被撤回：run-a、run-b/);
  assert.match(html, /以下周抽样不足：2026-11-09/);
  assert.match(html, /每周至少 2 次补足/);
  assert.match(html, /90\.0%/);
});

test("without a current qualification only historical value metrics are listed", () => {
  const html = renderToStaticMarkup(React.createElement(SkillQualityBody, { view: { ...view, current: null, groups: [] } }));
  assert.match(html, /当前没有有效资格/);
  assert.match(html, /尚无自动写入记录/);
  assert.doesNotMatch(html, /降回一次确认，待重新审阅/);
});

test("open holds are pinned with their owner and basis runs, and hidden when none", () => {
  const hold = { id: "h", skill_key: "public_research", skill_version: "1.0.0", model_version: "m", reason: "critical_spot_check", threshold: {}, metrics: { sample: 1, count: 1 }, basis_run_ids: ["run-x"], spot_check_id: "s", owner_name: "Synthetic owner", created_at: "2026-11-09T00:00:00Z" };
  const html = renderToStaticMarkup(React.createElement(SkillQualityHoldsBanner, { holds: [hold] }));
  assert.match(html, /待复审 · 1 项自动执行资格已降回一次确认/);
  assert.match(html, /抽检发现关键错误 · 抽检标注为关键错误 · 资格负责人：Synthetic owner/);
  assert.match(html, /依据运行：run-x/);
  assert.equal(renderToStaticMarkup(React.createElement(SkillQualityHoldsBanner, { holds: [] })), "");
  assert.equal(renderToStaticMarkup(React.createElement(SkillQualityHoldsBanner, { holds: null })), "");
});
