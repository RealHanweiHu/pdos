import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- In-memory event dispatcher; SSR forwards hooks unchanged. */

const directory = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.join(directory, "../../package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const shim = { ...React,
  useState(initial) { if (!hooks) return React.useState(initial); const state = hooks, index = state.index++; if (!(index in state.values)) state.values[index] = typeof initial === "function" ? initial() : initial; return [state.values[index], value => { state.values[index] = typeof value === "function" ? value(state.values[index]) : value; }]; },
  useRef(initial) { if (!hooks) return React.useRef(initial); const state = hooks, index = state.index++; if (!(index in state.values)) state.values[index] = { current: initial }; return state.values[index]; },
  useCallback(callback, dependencies) { if (!hooks) return React.useCallback(callback, dependencies); const state = hooks, index = state.index++, prior = state.values[index]; if (!prior || !same(prior.dependencies, dependencies)) state.values[index] = { callback, dependencies }; return state.values[index].callback; },
  useEffect(effect, dependencies) { if (!hooks) return React.useEffect(effect, dependencies); const state = hooks, index = state.index++, prior = state.values[index]; if (!prior || !same(prior.dependencies, dependencies)) { state.values[index] = { dependencies, cleanup: prior?.cleanup }; state.effects.push(() => { state.values[index].cleanup?.(); state.values[index].cleanup = effect(); }); } },
};
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? shim
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier === "@/components/ui/button" ? { Button: props => React.createElement("button", props) }
    : specifier.startsWith("@/") ? load(path.join(directory, "../../..", "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { WorkProductEditor } = load(path.join(directory, "work-product-editor.tsx"));
const product = { id: "p1", root_id: "p1", session_id: "s1", run_id: "r1", category_id: null, kind: "document", title: "真实方案", body: "## 方案 A\n\n真实回复正文", revision: 1, origin: "ai_draft", supersedes_id: null, created_at: "2026-10-27T00:00:00Z" };
const revised = { ...product, id: "p2", revision: 2, origin: "human", supersedes_id: "p1", title: "人工标题", body: "人工正文" };

test("updated sources label the saved record while retaining its human text", () => {
  const html = renderToStaticMarkup(React.createElement(WorkProductEditor, {
    product: { ...revised, source_currentness: "updated" }, original: product, open: true,
    api: async () => { throw Error("Rendering cannot fetch"); }, onClose() {}, onSaved() {},
    onReload: async () => null, onUnavailable() {},
  }));
  assert.match(html, /来源资料已更新/); assert.match(html, /人工正文/);
  assert.match(html, /v2/);
});
const tick = () => new Promise(resolve => setImmediate(resolve));
function nodes(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(item => nodes(item, predicate)); if (["PaiMobileWorkspaceSwitch", "Button"].includes(tree.type?.name)) return nodes(tree.type(tree.props), predicate); return [...(predicate(tree) ? [tree] : []), ...nodes(tree.props?.children, predicate)]; }
function text(tree) { return typeof tree === "string" ? tree : Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(tree.props?.children) : ""; }
function session(productValue = product, api, reload = async () => null) {
  const state = { values: [], index: 0, effects: [] }, saved = [], unavailable = [];
  let tree, current = productValue;
  const props = { product: current, original: product, open: true, api, onClose() {}, onSaved: value => saved.push(value), onReload: reload, onUnavailable: () => unavailable.push(true), onMobileChat() {} };
  function render() { state.index = 0; state.effects = []; hooks = state; try { tree = WorkProductEditor(props); } finally { hooks = null; } return tree; }
  return { render, saved, unavailable, async settle() { for (let index = 0; index < 6; index++) { await tick(); render(); const effects = state.effects; state.effects = []; effects.forEach(effect => effect()); } return tree; }, async click(label) { render(); const button = nodes(tree, node => node.type === "button" && text(node.props.children) === label)[0]; assert.ok(button, label); button.props.onClick(); await this.settle(); }, update(next) { current = next; props.product = current; props.original = product; return render(); } };
}

test("human edit uses exact current revision and returns to the saved reading state", async () => {
  const c = session(product, async (path, body) => { assert.equal(path, "v1/personal/work-products/p1/revisions"); assert.equal(body.expected_revision, 1); return revised; });
  await c.settle(); await c.click("继续编辑");
  const inputs = nodes(c.render(), node => node.type === "input"); inputs[0].props.onChange({ target: { value: "人工标题" } });
  const area = nodes(c.render(), node => node.type === "textarea")[0]; area.props.onChange({ target: { value: "人工正文" } });
  await c.click("保存修改"); assert.equal(c.saved.length, 1); assert.equal(c.saved[0].id, "p2");
  c.update(revised); assert.match(renderToStaticMarkup(c.render()), /人工正文/); assert.match(renderToStaticMarkup(c.render()), /v2/); assert.match(renderToStaticMarkup(c.render()), /查看原 AI 内容/);
});

test("unknown save keeps the exact request and replays it without a duplicate", async () => {
  const requests = [];
  const c = session(product, async (path, body) => { requests.push(structuredClone(body)); if (requests.length === 1) throw Error("network lost"); return revised; });
  await c.settle(); await c.click("继续编辑"); await c.click("保存修改"); assert.match(renderToStaticMarkup(c.render()), /原请求已保留/);
  await c.click("核对原保存请求"); assert.equal(requests.length, 2); assert.deepEqual(requests[0], requests[1]);
});

test("a version conflict reloads the latest product and preserves the human draft", async () => {
  const requests = [], latest = { ...revised, title: "另一窗口标题", body: "另一窗口正文" };
  const c = session(product, async (path, body) => {
    requests.push(structuredClone(body));
    if (requests.length === 1) throw Object.assign(Error("成果已有新版本"), { status: 409, code: "VERSION_CONFLICT" });
    return { ...latest, id: "p3", revision: 3, title: body.title, body: body.body };
  }, async current => current.id === product.id ? latest : null);
  await c.settle(); await c.click("继续编辑");
  const inputs = nodes(c.render(), node => node.type === "input"); inputs[0].props.onChange({ target: { value: "保留的人工标题" } });
  const area = nodes(c.render(), node => node.type === "textarea")[0]; area.props.onChange({ target: { value: "保留的人工正文" } });
  await c.click("保存修改"); assert.equal(c.saved[0].id, "p2");
  assert.match(renderToStaticMarkup(c.render()), /已更新到 v2/);
  c.update(latest); const html = renderToStaticMarkup(c.render());
  assert.match(html, /保留的人工标题/); assert.match(html, /保留的人工正文/);
  await c.click("保存修改"); assert.equal(requests[1].expected_revision, 2); assert.equal(c.saved[1].revision, 3);
});

test("permission loss clears the editor and calls the shared cleanup", async () => {
  const c = session(product, async () => { throw Object.assign(Error("denied"), { status: 403 }); });
  await c.settle(); await c.click("继续编辑"); await c.click("保存修改"); assert.equal(c.unavailable.length, 1);
});

test("table reading uses the actual markdown cells", () => {
  const table = { ...product, kind: "table", body: "| 方案 | 日期 |\n| --- | --- |\n| A | 11-01 |" };
  const html = renderToStaticMarkup(React.createElement(WorkProductEditor, { product: table, open: true, onClose() {}, onSaved() {}, onUnavailable() {} }));
  assert.match(html, /方案/); assert.match(html, /日期/); assert.match(html, /11-01/);
  assert.equal((html.match(/<th>/g) || []).length, 2); assert.equal((html.match(/<td>/g) || []).length, 2);
  assert.doesNotMatch(html, /<td>---<\/td>/);
});

test("saved v1 table cells render exact br markers as text newlines for analysis and basis", () => {
  const table = { ...product, kind: "table", revision: 1, body: "| 措施 |\n| --- |\n| 分析：可参考历史措施<br>依据：更换密封圈<br/>当前条件待确认 |" };
  const html = renderToStaticMarkup(React.createElement(WorkProductEditor, { product: table, open: true, onClose() {}, onSaved() {}, onUnavailable() {} }));
  assert.match(html, /<td>分析：可参考历史措施\n依据：更换密封圈\n当前条件待确认<\/td>/);
  assert.doesNotMatch(html, /&lt;br|<br/);
  assert.equal(table.body.includes("<br>"), true, "display does not rewrite the saved v1 body");
});

test("cell breaks never interpret scripts, images, attributes or other HTML as markup", () => {
  const table = { ...product, kind: "table", body: '| 措施 |\n| --- |\n| <script>alert("x")</script><br/><img src=x onerror=alert(1)><br onclick=alert(2)><br /><BR> |' };
  const html = renderToStaticMarkup(React.createElement(WorkProductEditor, { product: table, open: true, onClose() {}, onSaved() {}, onUnavailable() {} }));
  assert.match(html, /&lt;script&gt;alert\(&quot;x&quot;\)&lt;\/script&gt;\n&lt;img/);
  assert.match(html, /&lt;br onclick=alert\(2\)&gt;/); assert.match(html, /&lt;br \/&gt;/); assert.match(html, /&lt;BR&gt;/);
  assert.doesNotMatch(html, /<script|<img|<br|<BR/);
});

test("document text keeps its literal br characters", () => {
  const document = { ...product, body: "分析：文本<br>依据：仍是文档文本" };
  const html = renderToStaticMarkup(React.createElement(WorkProductEditor, { product: document, open: true, onClose() {}, onSaved() {}, onUnavailable() {} }));
  assert.match(html, /分析：文本&lt;br&gt;依据：仍是文档文本/);
});
