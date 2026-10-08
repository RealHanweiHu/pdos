import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as icons from "@phosphor-icons/react";

// In-memory isolated TSX loader; no Next build, dependency installation or disk cache.
const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript");
const React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(extension => filename + extension).find(existsSync);
  if (!filename) throw new Error("Test module could not be found");
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename);
  modules.set(filename, loaded);
  const localRequire = createRequire(filename);
  loaded.require = specifier => specifier === "@phosphor-icons/react" ? icons : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2))) : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : localRequire(specifier);
  const compiled = ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } });
  loaded._compile(compiled.outputText, filename);
  return loaded.exports;
}
const { issue, failure, context, preview, mergeIntent, action } = load(path.join(directory, "__tests__/fixtures.ts"));
load(path.join(directory, "contracts.test.ts"));
const { QualityIssueReading } = load(path.join(directory, "reading.tsx"));
const { QualityIssueWorkbench } = load(path.join(directory, "workbench.tsx"));
const { QualityActionReview } = load(path.join(directory, "review.tsx"));
const callbacks = { onPrepare: () => { throw new Error("Rendering must not write"); }, onConfirm: () => { throw new Error("Rendering must not write"); }, onResolve: () => { throw new Error("Rendering must not write"); } };
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));

test("Issue reading retains raw values, exact references, synthetic nature and original independent failures", () => {
  const html = render(QualityIssueReading, { issue });
  for (const text of ["001.2300", "synthetic-measurement", "synthetic-sample", "synthetic-method", "synthetic-criterion", "synthetic-actual", "synthetic-engineering", "synthetic-manufacturing", "明确合成输入", "合成报告第 3 行", "synthetic-other-failure", "合成历史测量保留"]) assert.ok(html.includes(text), text);
});
test("completed measures remain distinct from root cause, independent effectiveness and closure", () => {
  const html = render(QualityIssueReading, { issue });
  for (const text of ["等待独立有效性复核", "措施已完成", "AI 假设", "尚无具名根因结论", "尚无具名有效性决定", "措施完成不等于有效或关闭", "高风险", "须独立验证", "待对应模块办理"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes("已具名关闭"), false);
});
test("source withdrawal retains failure references and prevents old raw value leakage", () => {
  const html = render(QualityIssueReading, { issue: { ...issue, requiresRecheck: true, recheckReasons: ["合成来源撤回"], failures: [{ ...failure, source: { ...failure.source, status: "withdrawn" } }] } });
  for (const text of ["当前判断待重核", "合成来源撤回", "未读取（原值待核验）", "原始测量保留", "synthetic-measurement"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes("001.2300"), false);
  assert.equal(html.includes("已具名关闭"), false);
});
test("missing ports disable workbench and show no invented successful receipt", () => {
  const html = render(QualityIssueWorkbench, { issue: null, failures: [], mergeCandidates: [], context: { ...context, portReady: false, unavailableReason: "合成 RunPort 未接入" }, action, callbacks });
  assert.ok(html.includes("待接入"));
  assert.ok(html.includes("合成 RunPort 未接入"));
  assert.match(html, /<button[^>]*disabled=""[^>]*>核对本次实质范围<\/button>/);
  assert.equal(html.includes("回执："), false);
});
test("AI T2 view refuses named submission despite supplied allowed capability", () => {
  const html = render(QualityIssueWorkbench, { issue, failures: [], mergeCandidates: [], context: { ...context, actor: { ...context.actor, kind: "ai" } }, action, callbacks, initialOperation: "quality.capa.effectiveness.decide" });
  assert.ok(html.includes("AI 只能准备候选"));
  assert.match(html, /<button[^>]*disabled=""[^>]*>核对本次实质范围<\/button>/);
});
test("controlled merge preview renders exact preserved failures and substantive differences", () => {
  const html = render(QualityActionReview, { action: { ...action, preview }, context, intent: mergeIntent, callbacks });
  assert.ok(html.includes("合成归并新增失败范围，不覆盖原读数"));
  assert.ok(html.includes("synthetic-other-failure"));
  assert.match(html, /<button(?![^>]*disabled="")[^>]*>一次确认此范围<\/button>/);
});
test("edited intent or configuration drift visibly disables old preview confirmation", () => {
  for (const props of [{ intent: { ...mergeIntent, reason: "已改说明" }, context }, { intent: mergeIntent, context: { ...context, key: "new-config" } }]) {
    const html = render(QualityActionReview, { action: { ...action, preview }, callbacks, ...props });
    assert.match(html, /<button[^>]*disabled=""[^>]*>一次确认此范围<\/button>/);
    assert.ok(html.includes("须重新"));
  }
});
test("unknown receipt locks confirmation and exposes only original action resolution", () => {
  const html = render(QualityActionReview, { action: { ...action, preview, unknown: true, receipt: { outcome: "unknown", receiptId: null, message: "合成结果未知" } }, context, intent: mergeIntent, callbacks });
  assert.ok(html.includes("原动作结果未知"));
  assert.ok(html.includes("回执尚未确认"));
  assert.match(html, /<button[^>]*disabled=""[^>]*>一次确认此范围<\/button>/);
  assert.ok(html.includes("核对原动作回执"));
  assert.equal(html.includes("回执："), false);
});
test("unknown action without restored preview refuses new prepare", () => {
  const html = render(QualityIssueWorkbench, { issue, failures: [], mergeCandidates: [], context, action: { ...action, unknown: true }, callbacks });
  assert.ok(html.includes("恢复原预览与回执查询入口"));
  assert.match(html, /<button[^>]*disabled=""[^>]*>核对本次实质范围<\/button>/);
});
test("previous ineffective named decisions remain visible when a later decision is effective", () => {
  const oldDecision = { text: "合成旧复验无效原因保留", result: "ineffective", actorId: "synthetic-old-reviewer", actorLabel: "合成旧具名复核人", decidedAt: "2026-10-01T17:00:00Z", sources: [failure.source], independent: true, verificationRuns: context.independentVerificationRuns };
  const latest = { ...oldDecision, text: "合成新的具名有效结论", result: "effective", decidedAt: "2026-10-02T17:00:00Z" };
  const html = render(QualityIssueReading, { issue: { ...issue, capa: { ...issue.capa, effectiveness: latest, effectivenessHistory: [oldDecision, latest] } } });
  for (const text of ["合成旧复验无效原因保留", "合成新的具名有效结论", "合成旧具名复核人", "历史有效性决定"]) assert.ok(html.includes(text), text);
});
test("null authority measurement never becomes an empty fabricated value", () => {
  const html = render(QualityIssueReading, { issue: { ...issue, failures: [{ ...failure, rawValue: null, unit: null, conditions: null }] } });
  assert.ok(html.includes("未读取（原值待核验）"));
  assert.equal(html.includes("001.2300"), false);
  assert.equal(html.includes("空原值"), false);
});
