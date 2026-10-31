import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.join(directory, "../../../package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const filename = path.join(directory, "answer-task-result.tsx"), component = new Module(filename);
component.require = dependency;
component._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
  module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
} }).outputText, filename);
const { AnswerTaskResult } = component.exports;
const cid = "7e957c7f-3f19-4ce4-a330-388783851579";
const source = { citation_id: cid, source_revision: 3 };
const registry = {
  blockers: ["阻塞清单", [["conclusion", "当前结论"], ["blocker", "阻塞事项"], ["owner", "责任人"], ["next_step", "下一步"], ["decision", "待决定事项"]]],
  cases: ["案例表", [["case", "相似案例"], ["root_cause", "根因"], ["measures", "措施"], ["verification", "验证结果"], ["conditions_and_differences", "适用条件与差异"]]],
  review: ["评审清单", [["key_changes", "关键变化"], ["unresolved_issues", "未解决问题"], ["decisions", "需决定事项"]]],
  commitments: ["承诺表", [["current_commitment", "当前承诺"], ["deviation", "偏差"], ["related_objects", "相关对象"], ["follow_up", "需跟进事项"]]],
};
const recorded = { status: "recorded", text: "更换密封圈", content_kind: "recorded", basis_text: "更换密封圈", citation_id: cid, source_revision: 3, locator: { line_start: 2 } };
function fixture(format = "cases", cell = recorded) {
  const [title, fields] = registry[format];
  return { version: 1, format, title, columns: fields.map(([key, label]) => ({ key, label })),
    rows: [{ cells: Object.fromEntries(fields.map(([key], index) => [key, index === 0 ? { ...cell } : key === "owner" ? { status: "unspecified", text: "未指定" } : { status: "to_confirm", text: "待确认" }])) }],
    verified: true, unknown_count: fields.length - 1 };
}
const render = (value, sources = [source]) => renderToStaticMarkup(React.createElement(AnswerTaskResult, { value, sources }));

for (const format of Object.keys(registry)) test(`${format} renders its columns, checked citation and honest unknowns`, () => {
  const html = render(fixture(format));
  for (const [, label] of registry[format][1]) assert.ok(html.includes(label), label);
  assert.match(html, /更换密封圈/); assert.match(html, /待确认/);
  assert.ok(html.includes(`href="#assistant-source-${cid}-0"`));
  assert.match(html, /v3 · 第 2 行/); assert.match(html, /可横向滚动/);
  if (format === "blockers") assert.match(html, /未指定/);
});

test("analysis and literal basis stay visibly separate and escape untrusted text", () => {
  const html = render(fixture("cases", { ...recorded, content_kind: "analysis", text: "可供参考，当前工况仍待核对。", basis_text: "<script>更换密封圈</script>" }));
  assert.match(html, />分析</); assert.match(html, /可供参考/); assert.match(html, /原文依据：/);
  assert.match(html, /&lt;script&gt;/); assert.ok(!html.includes("<script>"));
});

test("missing table stays absent and malformed or unbacked records stay visible failures", () => {
  assert.equal(render(undefined), "");
  const bad = [
    { ...fixture(), format: "unregistered" }, { ...fixture(), unknown_count: 0 },
    { ...fixture(), rows: [] },
    fixture("cases", { ...recorded, citation_id: "forged" }),
    fixture("cases", { ...recorded, source_revision: 999 }),
    fixture("cases", { ...recorded, text: "MODEL_OVERRIDE" }),
  ];
  for (const value of bad) {
    const html = render(value);
    assert.match(html, /任务结果暂不可核对/); assert.ok(!html.includes("MODEL_OVERRIDE"));
  }
  assert.match(render(fixture(), []), /任务结果暂不可核对/);
});

test("owner cannot be presented as analysis and unknown cells cannot hide invented text", () => {
  const owner = fixture("blockers");
  owner.rows[0].cells.owner = { ...recorded, content_kind: "analysis" }; owner.unknown_count--;
  assert.match(render(owner), /任务结果暂不可核对/);
  const unknown = fixture(); unknown.rows[0].cells.root_cause.text = "SILENT_INVENTION";
  assert.ok(!render(unknown).includes("SILENT_INVENTION"));
});

test("source updates and applicability gaps are visible beside retained historical cells", () => {
  const html = render(fixture(), [{ ...source, currentness: "updated", read_basis_status: "needs_recheck" }]);
  assert.match(html, /资料已更新，当前事实请重新查询/); assert.match(html, /当前适用性待重核/);
  assert.match(html, /更换密封圈/);
  assert.match(render({ ...fixture(), verified: false }), /部分单元格未通过引用核对/);
});
