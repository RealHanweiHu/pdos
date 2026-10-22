import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Actual component/helper with offline hooks. No API, authorization or browser proof.
const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(root, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hooks;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const react = {
  ...React,
  useState(initial) {
    const own = hooks, index = own.index++;
    if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial;
    return [own.slots[index], value => {
      if (own.disposed) return;
      own.slots[index] = typeof value === "function" ? value(own.slots[index]) : value;
      own.dirty = true;
    }];
  },
  useRef(initial) {
    const index = hooks.index++;
    if (!(index in hooks.slots)) hooks.slots[index] = { current: initial };
    return hooks.slots[index];
  },
  useEffect(effect, deps) {
    const own = hooks, index = own.index++, previous = own.slots[index];
    if (!same(previous?.deps, deps)) {
      own.slots[index] = { deps, cleanup: previous?.cleanup };
      own.effects.push(() => { own.slots[index].cleanup?.(); own.slots[index].cleanup = effect(); });
    }
  },
};
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename);
  modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react
    : name === "@/components/ui/button" ? { Button: props => React.createElement("button", props) }
      : name.startsWith("@/") ? load(path.join(root, "src", name.slice(2)))
        : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
  }).outputText, filename);
  return loaded.exports;
}
const { KnowledgeNativeResultPicker: Picker } = load(path.join(directory, "knowledge-native-result-picker.tsx"));
const { knowledgeNativeDraftPatch } = load(path.join(root, "src/lib/knowledge-experience-native.ts"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope = { categoryId: id(1), productId: id(2), projectId: "", principalId: id(3) };
function context() {
  return {
    scope: { category_id: id(1), product_id: id(2), project_id: null, principal_id: id(3) },
    as_of: "2026-10-19T12:30:00Z",
    result_options: [{ receipt_id: id(4), family: "change", title: "实际实施结果", operation: "change.implementation.record", subject: { kind: "change_request", id: id(5), revision: 8 }, recorded_at: "2026-10-19T11:30:00Z", visibility: "audience", selectable: true, reason: null }],
    source_options: [{ ref: { kind: "artifact", id: id(6), revision: 2, position: "line:3;quote_sha256:" + "a".repeat(64) }, title: "客户现场原件", excerpt: "保留实际原文与未知条件。", visibility: "private", selectable: true, reason: null }],
    configuration_options: [{ ref: { kind: "engineering_configuration", id: id(7), revision: 3 }, name: "实际工程配置", selectable: true, reason: null }],
    next_cursor: null,
  };
}
function nodes(value, predicate) {
  if (Array.isArray(value)) return value.flatMap(child => nodes(child, predicate));
  if (!React.isValidElement(value)) return [];
  return [...(predicate(value) ? [value] : []), ...nodes(value.props.children, predicate)];
}
function environment(overrides = {}) {
  const own = { slots: [], index: 0, effects: [], dirty: false, disposed: false };
  const selections = [];
  let props = { context: context(), scope, editable: true, onSelect: value => selections.push(value), ...overrides }, tree;
  function render() {
    do {
      own.dirty = false; own.index = 0; hooks = own; tree = Picker(props);
      for (const effect of own.effects.splice(0)) effect();
    } while (own.dirty);
    return tree;
  }
  render();
  return {
    selections, tree: () => tree, html: () => renderToStaticMarkup(tree),
    setProps(next) { props = { ...props, ...next }; render(); },
    checkbox(label) { const found = nodes(tree, node => node.type === "input" && node.props["aria-label"] === label)[0]; assert.ok(found, label); return found; },
    apply() { const found = nodes(tree, node => node.props.type === "button" && typeof node.props.onClick === "function")[0]; assert.ok(found); return found; },
    select(label, checked = true) { const target = this.checkbox(label); assert.equal(target.props.disabled, false); target.props.onChange({ target: { checked } }); render(); },
    choose() { const button = this.apply(); assert.equal(button.props.disabled, false); button.props.onClick(); render(); },
    dispose() { own.disposed = true; for (const slot of own.slots) slot?.cleanup?.(); },
  };
}

test("natural selectors start empty and emit exact references only after explicit selection", () => {
  const env = environment();
  assert.equal(nodes(env.tree(), node => node.type === "input" && node.props.checked).length, 0);
  assert.equal(nodes(env.tree(), node => node.type === "textarea").length, 0);
  assert.equal(env.apply().props.disabled, true);
  env.select("结果：实际实施结果"); env.select("原件：客户现场原件"); env.select("配置：实际工程配置");
  assert.equal(env.selections.length, 0);
  env.choose();
  assert.equal(env.selections.length, 1);
  assert.deepEqual(env.selections[0].result_receipts, [{ receipt_id: id(4) }]);
  assert.deepEqual(env.selections[0].configurations, context().configuration_options.map(row => row.ref));
  const patch = knowledgeNativeDraftPatch(env.selections[0], context(), scope);
  assert.deepEqual(JSON.parse(patch.sources), context().source_options.map(row => row.ref));
  assert.deepEqual(Object.keys(patch).sort(), ["result_receipts", "sources"]);
  assert.match(env.html(), /指定受众/);
});

test("ordinary candidate can select only a real original without project, closed Change or configuration", () => {
  const value = context(); value.result_options = []; value.configuration_options = [];
  const env = environment({ context: value });
  env.select("原件：客户现场原件"); env.choose();
  assert.deepEqual(env.selections[0].result_receipts, []);
  assert.deepEqual(env.selections[0].configurations, []);
  assert.equal("project_id" in env.selections[0], false);
});

test("unavailable reasons are literal text and never selectable even with a contradictory available flag", () => {
  const value = context(); value.source_options[0].reason = "来源已撤回 <script>not executable</script>";
  const env = environment({ context: value });
  assert.equal(env.checkbox("原件：客户现场原件").props.disabled, true);
  assert.match(env.html(), /来源已撤回 &lt;script&gt;not executable&lt;\/script&gt;/);
  assert.doesNotMatch(env.html(), /<script>/);
  assert.equal(env.apply().props.disabled, true);
});

test("readonly and unresolved permissions disable callbacks including an old explicit apply handler", () => {
  const env = environment(); env.select("原件：客户现场原件");
  const oldApply = env.apply().props.onClick;
  env.setProps({ editable: false });
  assert.equal(env.checkbox("原件：客户现场原件").props.disabled, true);
  assert.equal(env.apply().props.disabled, true);
  oldApply();
  assert.equal(env.selections.length, 0);
  const unresolved = environment({ editable: undefined });
  const checkbox = unresolved.checkbox("原件：客户现场原件");
  checkbox.props.onChange({ target: { checked: true } });
  assert.equal(unresolved.selections.length, 0);
});

test("scope change hides old private material and disposes old checkbox/apply callbacks", () => {
  const env = environment(); env.select("原件：客户现场原件");
  const oldApply = env.apply().props.onClick, oldSource = env.checkbox("原件：客户现场原件").props.onChange;
  env.setProps({ scope: { ...scope, principalId: id(99) } });
  assert.doesNotMatch(env.html(), /客户现场原件|保留实际原文|实际实施结果/);
  assert.match(env.html(), /旧材料已隐藏/);
  oldSource({ target: { checked: true } }); oldApply();
  assert.equal(env.selections.length, 0);
});

test("refresh, next page and corrected fixed references clear prior choices instead of retargeting", () => {
  for (const update of [
    value => { value.as_of = "2026-10-19T12:31:00Z"; },
    value => { value.next_cursor = "next-page"; },
    value => { value.source_options[0].ref.revision++; },
  ]) {
    const env = environment(); env.select("原件：客户现场原件");
    const oldApply = env.apply().props.onClick, next = context(); update(next);
    env.setProps({ context: next });
    assert.equal(env.checkbox("原件：客户现场原件").props.checked, false);
    assert.equal(env.apply().props.disabled, true);
    oldApply(); assert.equal(env.selections.length, 0);
  }
});

test("failed or malformed directory is unknown and never reuses an old private selection", () => {
  for (const value of [null, { ...context(), source_options: undefined }]) {
    const env = environment(); env.select("原件：客户现场原件");
    const oldApply = env.apply().props.onClick;
    env.setProps({ context: value }); oldApply();
    assert.doesNotMatch(env.html(), /客户现场原件|实际实施结果/);
    assert.equal(env.selections.length, 0);
  }
});

test("disposing the picker prevents a saved event callback from filling another candidate", () => {
  const env = environment(); env.select("原件：客户现场原件");
  const oldApply = env.apply().props.onClick;
  env.dispose(); oldApply();
  assert.equal(env.selections.length, 0);
});
