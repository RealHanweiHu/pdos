import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.resolve(directory, "../../../package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const filename = path.join(directory, "project-status-summary.tsx"), loadedModule = new Module(filename);
loadedModule.require = name => name.endsWith(".css") ? { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) } : dependency(name);
loadedModule._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
const { ProjectStatusSummary } = loadedModule.exports;
const render = update => renderToStaticMarkup(React.createElement(ProjectStatusSummary, { update }));
const update = { id: "named-update", revision: 1, actor: { id: "actual-author", name: "本人原署名" }, fact_summary: "本期实际验收结果", next_steps: "下一步核对剩余项", task_refs: [{ id: "fixed-task", revision: 8 }], created_at: "2026-10-18T01:00:00Z", receipt_id: "actual-receipt" };

test("unread and no signed update are distinct states", () => {
  assert.match(render(undefined), /尚未读取/); assert.match(render(null), /尚无具名状态更新/);
});
test("named summary keeps actual author, receipt and fixed task version", () => {
  const html = render(update);
  for (const text of ["本人原署名", "本期实际验收结果", "下一步核对剩余项", "fixed-task", "固定 v8", "actual-receipt"]) assert.ok(html.includes(text), text);
  assert.match(html, /datetime="2026-10-18T01:00:00Z"/i);
  assert.doesNotMatch(html, /已自动更新任务|预测已改|AI已批准/);
});
test("unread author is never replaced with the viewing user and statement remains text", () => {
  const html = render({ ...update, actor: { id: "actual-author", name: null }, fact_summary: "<script>alert('source')</script>", task_refs: [] });
  assert.match(html, /姓名暂不可读/); assert.match(html, /未引用任务版本/); assert.doesNotMatch(html, /<script>/); assert.match(html, /&lt;script&gt;/);
});
