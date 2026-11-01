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
const { request, context, source, impact } = load(path.join(directory, "__tests__/fixtures.ts"));
const { ChangeControlReading, ChangeImpactReading } = load(path.join(directory, "reading.tsx"));
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
const complete = { ...request, order: { ...request.order, effectiveScopeIds: ["A", "B"], awaitingScopeIds: [] } };

test("explicit engineering and manufacturing edges, missing coverage and AI guesses stay distinct", () => {
  const html = render(ChangeControlReading, { request });
  for (const text of ["规格约束", "装配工序", "synthetic-spec", "synthetic-operation", "合成工序到治具缺边", "AI 合成治具兼容性猜测", "无引用", "合成报告第 4 行", "UNKNOWN"]) assert.ok(html.includes(text), text);
});
test("missing manufacturing edge does not claim no impact", () => {
  const html = render(ChangeImpactReading, { impact: { ...impact, paths: impact.paths.filter(value => value.line === "engineering") } });
  assert.ok(html.includes("不能认定无影响"));
});
test("approval, implementation failure, partial effectivity and independent review remain separate", () => {
  const html = render(ChangeControlReading, { request });
  for (const text of ["仅批准工程范围", "尚无此专业具名批准", "合成实施故障保留", "仅合成 A 范围已生效", "等待实际回执范围：B", "尚无具名独立复核决定", "尚未具名关闭", "不表示已建新配置", "日期到期不会自动批准或生效"]) assert.ok(html.includes(text), text);
});
test("history remains visible when a later decision becomes effective", () => {
  const decision = { actorId: context.actor.id, actorLabel: context.actor.label, at: "2026-10-02T17:00:00Z", text: "合成新有效性结论", sources: [source], result: "effective", independent: true, coverageScopeIds: ["A", "B"], runs: context.verificationCandidates[0].refs };
  const html = render(ChangeControlReading, { request: { ...complete, order: { ...complete.order, verification: [{ ...decision, result: "ineffective", text: "合成旧无效结论保留" }, decision] } } });
  assert.ok(html.includes("合成旧无效结论保留"));
  assert.ok(html.includes("合成新有效性结论"));
  assert.ok(html.includes("尚未具名关闭"));
});
test("transport sent or accepted stage never displays established effectivity", () => {
  for (const stage of ["sent", "accepted"]) {
    const html = render(ChangeControlReading, { request: { ...request, order: { ...request.order, effectivity: [{ ...request.order.effectivity[0], stage, outcome: "effective" }] } } });
    assert.ok(html.includes("未证实际生效"));
    assert.equal(html.includes("已明确生效 ·"), false);
  }
});
