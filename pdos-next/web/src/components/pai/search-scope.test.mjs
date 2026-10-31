import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import test from "node:test";
import { fileURLToPath } from "node:url";

const dependency = createRequire(import.meta.url), ts = dependency("typescript"), React = dependency("react");
const filename = fileURLToPath(new URL("./search-scope.tsx", import.meta.url)), loaded = new Module(filename);
loaded.require = name => name.endsWith(".css") ? {} : dependency(name);
loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
const { SearchScope } = loaded.exports;
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
test("showing context never edits it; both controls preserve the complete explicit choice", () => {
  const changes = [], value = { scope: "same_category", include_customer_private: false };
  let tree = SearchScope({ label: "已核对的气密项目", value, onChange: next => changes.push(next) });
  assert.equal(changes.length, 0);
  const html = dependency("react-dom/server").renderToStaticMarkup(tree);
  assert.match(html, /当前对象：/); assert.match(html, /当前项目＋同品类补查/);
  nodes(tree).find(node => node.type === "input").props.onChange({ target: { checked: true } });
  assert.deepEqual(changes, [{ scope: "same_category", include_customer_private: true }]);
  tree = SearchScope({ label: "提案", kind: "proposal", value: changes[0], onChange: next => changes.push(next) });
  nodes(tree).find(node => node.type === "select").props.onChange({ target: { value: "current" } });
  assert.deepEqual(changes[1], { scope: "current", include_customer_private: true });
  const disabled = SearchScope({ label: "提案", value: changes[1], onChange() {}, disabled: true });
  assert.ok(nodes(disabled).filter(node => ["select", "input"].includes(node.type)).every(node => node.props.disabled));
  assert.ok(React.isValidElement(tree));
});
