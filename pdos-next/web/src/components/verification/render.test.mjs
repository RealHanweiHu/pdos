import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as icons from "@phosphor-icons/react";

// Isolated TSX loader using the installed compiler; no build cache or service.
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
const { request, context, sampleA, sampleB, run, measurement, coverageA } = load(path.join(directory, "__tests__/fixtures.ts"));
load(path.join(directory, "contracts.test.ts"));
const { VerificationRequestReading } = load(path.join(directory, "request-reading.tsx"));
const { VerificationHandoff } = load(path.join(directory, "handoff.tsx"));
const { VerificationTestRuns } = load(path.join(directory, "test-runs.tsx"));
const callbacks = { onPreview: async () => { throw new Error("Rendering must not write"); }, onConfirm: async () => { throw new Error("Rendering must not write"); } };
const owners = [{ id: "next-person", label: "合成下一责任人" }];

test("request reading keeps samples, documents, tentative scheduling and sourced times separate", () => {
  const html = renderToStaticMarkup(React.createElement(VerificationRequestReading, { request, samples: [] }));
  for (const content of ["资料齐套", "实际样件", "暂定时段与正式接收", "计划 Build 不能替代样件", "实物就绪", "资料齐套", "部分结果返回", "尚未记录"]) assert.ok(html.includes(content), content);
  assert.equal(html.includes("测试通过"), false);
});

test("missing ports visibly disable actual reception without a synthetic successful state", () => {
  const html = renderToStaticMarkup(React.createElement(VerificationHandoff, { request, samples: [], context: { ...context, portReady: false }, callbacks, nextOwners: owners }));
  assert.ok(html.includes("待主线接入"));
  assert.match(html, /<button[^>]*disabled=""[^>]*>核对接收范围<\/button>/);
  assert.ok(html.includes("尚无实际 SampleUnit"));
  assert.equal(html.includes("回执："), false);
});

test("a failed run retains execution status independently and limits result interpretation to its scope", () => {
  const reportedRun = { ...run, status: "results_pending", result: "fail", measurements: [{ ...measurement, id: "measurement-a", computedResult: "indeterminate", professionalConclusion: null }] };
  const html = renderToStaticMarkup(React.createElement(VerificationTestRuns, { request: { ...request, status: "executing" }, samples: [sampleA, sampleB], runs: [reportedRun], context, callbacks, nextOwners: owners }));
  for (const content of ["执行：等待结果核对", "本 Run 范围判定：不通过", "001.2300", "确定性判定：不确定", "专业结论：尚未记录", "原请求覆盖差距", "最终结果（仍可为不确定或无效）"]) assert.ok(html.includes(content), content);
  assert.equal(html.includes("请求通过"), false);
});

test("named start asks for real event evidence and displays the server executor read-only", () => {
  const html = renderToStaticMarkup(React.createElement(VerificationTestRuns, { request: { ...request, status: "accepted", acceptedCoverage: coverageA }, samples: [sampleA], runs: [run], context, callbacks, nextOwners: owners }));
  for (const content of ["真实开始时间", "原始 IANA 时区", "当前校准固定来源", "合成具名人员", "开始记录精确位置"]) assert.ok(html.includes(content), content);
  assert.equal(html.includes('name="executorId"'), false);
});
