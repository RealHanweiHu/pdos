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
const { issue, failure, context } = load(path.join(directory, "__tests__/fixtures.ts"));
load(path.join(directory, "contracts.test.ts"));
const { QualityIssueReading } = load(path.join(directory, "reading.tsx"));
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
