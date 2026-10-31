import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
function load(relative, require = dependency) {
  const filename = path.join(web, "src", relative), loaded = new Module(filename); loaded.require = require;
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX } }).outputText, filename);
  return loaded.exports;
}
const values = load("lib/work-products.ts");
const { WorkProductActions } = load("components/pai/work-product-actions.tsx", name => name === "@/lib/work-products" ? values : name === "@/components/ui/button" ? { Button: "button" } : name === "@phosphor-icons/react" ? { FileText: "svg", Table: "svg" } : dependency(name));
const run = { run_id: "run", status: "completed", result: { summary: "已整理以下结果，仍有条件待核对。" } };
const task = { version: 1, format: "cases", title: "案例表", columns: [{ key: "measures", label: "措施" }], rows: [{ cells: { measures: { status: "recorded", text: "更换密封圈" } } }], verified: true, unknown_count: 0 };
const comparison = { version: 1, format: "comparison", rows: [], complete: true, stats: { changes: 0 }, unmatched: [] };
const structured = assistant => ({ ...run, result: { ...run.result, result: { assistant } } });
const render = props => renderToStaticMarkup(React.createElement(WorkProductActions, { run, items: [], busy: false, onOpen() {}, ...props }));
const children = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(children) : [tree, ...children(tree.props?.children)];
const text = tree => typeof tree === "string" ? tree : Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(tree.props?.children) : "";

for (const [name, assistant] of [["task_result", { task_result: task }], ["comparison", { comparison }]]) {
  test(`${name} without summary Markdown exposes a table save and the actual table callback`, () => {
    const current = structured(assistant), opened = [];
    assert.ok(!current.result.summary.includes("|"));
    const html = render({ run: current }); assert.match(html, /保存为文档/); assert.match(html, /保存为表格/);
    const tree = WorkProductActions({ run: current, items: [], busy: false, onOpen: kind => opened.push(kind) });
    assert.deepEqual(opened, [], "rendering does not save anything");
    const table = children(tree).find(node => node.type === "button" && text(node) === "保存为表格");
    assert.ok(table); table.props.onClick(); assert.deepEqual(opened, ["table"]);
  });
  test(`${name} with an existing private table exposes open, and busy state disables it`, () => {
    const saved = { id: "table-1", root_id: "table-1", run_id: "run", kind: "table", revision: 1 };
    const html = render({ run: structured(assistant), items: [saved], busy: true });
    assert.match(html, /打开表格/); assert.doesNotMatch(html, /保存为表格/);
    const tree = WorkProductActions({ run: structured(assistant), items: [saved], busy: true, onOpen() {} });
    assert.equal(children(tree).find(node => node.type === "button" && text(node) === "打开表格").props.disabled, true);
  });
}

test("structured tables preserve completed, reverted and nonempty summary boundaries", () => {
  const current = structured({ task_result: task, comparison });
  for (const change of [{ status: "partial" }, { status: "failed" }, { status: "running" }, { reverted: true }, { result: { ...current.result, summary: "  " } }, { result: { result: current.result.result } }]) {
    assert.equal(render({ run: { ...current, ...change } }), "");
  }
});

test("ordinary Markdown tables remain available and unrecognized result objects do not imply tables", () => {
  assert.match(render({ run: { ...run, result: { summary: "| 案例 | 措施 |\n| --- | --- |\n| A | 复核 |" } } }), /保存为表格/);
  for (const assistant of [{ task_result: {} }, { task_result: { ...task, version: 2 } }, { task_result: { ...task, format: "unregistered" } }, { task_result: { ...task, rows: [] } }, { comparison: {} }, { comparison: { ...comparison, rows: "model prose" } }, { arbitrary_table: task }]) {
    const html = render({ run: structured(assistant) }); assert.match(html, /保存为文档/); assert.doesNotMatch(html, /保存为表格/);
  }
  assert.doesNotMatch(render({ run: structured({ task_result: task }), items: [{ run_id: "another", kind: "table", revision: 1 }] }), /打开表格/);
});

test("server tables with explicit unknown or incomplete coverage remain saveable", () => {
  assert.match(render({ run: structured({ task_result: { ...task, verified: false, unknown_count: 1 } }) }), /保存为表格/);
  assert.match(render({ run: structured({ comparison: { ...comparison, complete: false, unmatched: [{ reason: "incomplete_parse" }] } }) }), /保存为表格/);
});
