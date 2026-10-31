import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.join(directory, "../../package.json"));
const ts = dependency("typescript");
const { renderToStaticMarkup } = dependency("react-dom/server");
function load(name, extra = {}) {
  const filename = path.join(directory, name);
  const loaded = new Module(filename);
  loaded.require = key => Object.hasOwn(extra, key) ? extra[key] : dependency(key);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const component = load("project-current-basis.tsx");
const { ProjectCurrentBasis, projectBasisHref } = component;
const text = tree => typeof tree === "string" || typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(tree.props?.children) : "";
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const id = n => "00000000-0000-4000-8000-" + String(n).padStart(12, "0");
const url = "/?area=cockpit&category=" + id(1) + "&product=" + id(2) + "&project=" + id(3) + "&projectView=gates";
const initial = { version: "project-current-facts/v1", as_of: "2026-10-29T12:34:56+00:00", currentness: "current", complete: true, missing: [], references: [{ kind: "project_governance", id: id(4), revision: 2, receipt_id: id(5), url }] };

test("native current basis shows actual timestamp versions receipts and a project deep link", () => {
  const tree = ProjectCurrentBasis({ value: initial });
  assert.match(text(tree), /已读项目当前记录/);
  assert.match(text(tree), /2026-10-29T12:34:56\+00:00/);
  assert.match(text(tree), /阶段与门禁/); assert.match(text(tree), /v2/);
  assert.match(text(tree), new RegExp(id(5)));
  assert.equal(nodes(tree).find(node => node.type === "a").props.href, url);
  assert.doesNotMatch(text(tree), /未查公司资料|引用|检索命中/);
});

test("P32 updated basis preserves its original timestamp and states current re-read", () => {
  for (const version of ["project-current-facts/v1", "project-current-facts/v2"]) {
    const tree = ProjectCurrentBasis({ value: { ...initial, version, currentness: "updated" } });
    assert.match(text(tree), /保留本回答原版本，当前事实请重新读取/);
    assert.equal(nodes(tree).find(node => node.type === "time").props.dateTime, initial.as_of);
    assert.match(text(ProjectCurrentBasis({ value: { ...initial, version, complete: false } })), /未知项保留/);
  }
});

test("v2 native task plan and commitment references render using the backend project tasks URL", () => {
  // project_current_context._link(tab='work') resolves to the existing project
  // cockpit tasks view; native version IDs are proof metadata, not new routes.
  const tasksUrl = url.replace("projectView=gates", "projectView=tasks");
  const references = [
    { kind: "work_task", id: id(6), revision: 2, receipt_id: id(7), url: tasksUrl },
    { kind: "plan_task", id: id(8), revision: 1, receipt_id: null, url: tasksUrl },
    { kind: "work_commitment", id: id(9), revision: 1, receipt_id: id(10), url: tasksUrl },
  ];
  const tree = ProjectCurrentBasis({ value: { ...initial, version: "project-current-facts/v2", references } });
  const html = renderToStaticMarkup(tree);
  assert.match(html, /已读项目当前记录/);
  assert.match(html, /任务 · /); assert.match(html, /计划任务 · /); assert.match(html, /承诺 · /);
  assert.match(html, new RegExp(`回执 ${id(7)}`));
  assert.match(html, new RegExp(`回执 ${id(10)}`));
  assert.equal(nodes(tree).filter(node => node.type === "a").length, 3);
  assert.ok(nodes(tree).filter(node => node.type === "a").every(node => node.props.href === tasksUrl));
  assert.equal(projectBasisHref(tasksUrl), tasksUrl);
  assert.doesNotMatch(html, /未查公司资料|检索命中/);
});

test("v2 deduplicates identical native references while preserving different fixed versions", () => {
  const ref = { kind: "work_task", id: id(6), revision: 2, receipt_id: id(7), url };
  const tree = ProjectCurrentBasis({ value: { ...initial, version: "project-current-facts/v2",
    references: [ref, { ...ref }, { ...ref, revision: 1, receipt_id: id(8) }] } });
  const links = nodes(tree).filter(node => node.type === "a");
  assert.equal(links.length, 2);
  assert.match(text(links[0]), /v2/); assert.match(text(links[1]), /v1/);
});

test("malformed external duplicate or unknown links never become active authority links", () => {
  for (const target of ["https://example.test/", url + "&project=" + id(9), url.replace("gates", "admin"), url + "&token=private", "/?area=cockpit&project=" + id(3)]) assert.equal(projectBasisHref(target), null);
  for (const version of ["forged", "project-current-facts/v3", null, 2, ["project-current-facts/v2"]]) assert.equal(ProjectCurrentBasis({ value: { ...initial, version } }), null);
  for (const version of ["project-current-facts/v1", "project-current-facts/v2"]) {
    for (const patch of [{ as_of: "not-a-time" }, { references: [{ ...initial.references[0], url: "javascript:alert(1)" }] }, { references: [{ ...initial.references[0], kind: "arbitrary" }] }]) assert.equal(ProjectCurrentBasis({ value: { ...initial, version, ...patch } }), null);
    for (const patch of [{ id: "not-a-uuid" }, { revision: "2" }, { revision: 0 }, { receipt_id: [] }, { url: url + "&token=private" }, { kind: "__proto__" }]) {
      const tree = ProjectCurrentBasis({ value: { ...initial, version, references: [{ ...initial.references[0], kind: "work_task", ...patch }] } });
      assert.equal(tree, null);
      assert.equal(renderToStaticMarkup(tree), "");
    }
  }
  assert.equal(ProjectCurrentBasis({ value: undefined }), null);
});

test("AnswerSources mounts native basis independently of RAG sources and no lookup marker", () => {
  const { AnswerSources } = load("answer-sources.tsx", {
    react: { useRef: () => ({ current: null }) },
    "@/components/ui/button": { Button: "button" }, "../pai-conversation.module.css": {},
    "./answer-comparison": { AnswerComparison: "comparison" },
    "./answer-task-result": { AnswerTaskResult: "task-result" },
    "./project-current-basis": component,
  });
  for (const version of ["project-current-facts/v1", "project-current-facts/v2"]) {
    const actual = { ...initial, version };
    const tree = AnswerSources({ answer: { project_basis: actual } });
    const basis = nodes(tree).find(node => node.type === ProjectCurrentBasis);
    assert.ok(basis); assert.deepEqual(basis.props.value, actual);
    assert.match(text(ProjectCurrentBasis(basis.props)), /已读项目当前记录/);
  }
  assert.equal(AnswerSources({ answer: { lookup: "not_run" } }), null);
});
