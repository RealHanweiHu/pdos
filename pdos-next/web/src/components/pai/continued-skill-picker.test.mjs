import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Render the actual stateless control and invoke its buttons. React, the
// version-preserving helper and callbacks are real; no browser/network is used.
const directory = path.dirname(fileURLToPath(import.meta.url));
const web = path.resolve(directory, "../../.."), dependency = createRequire(path.join(web, "package.json"));
const ts = dependency("typescript"), modules = new Map();
const SkillPicker = () => null;
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename);
  modules.set(filename, loaded);
  loaded.require = name => name === "./skill-picker" ? { SkillPicker }
    : name === "@/components/ui/button" ? { Button: "button" }
    : name === "@phosphor-icons/react" ? { X: "svg", ArrowCounterClockwise: "svg" }
    : name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX,
    esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}
const { ContinuedSkillPicker } = load(path.join(directory, "continued-skill-picker.tsx"));
const nodes = (tree, predicate) => !tree || typeof tree !== "object" ? [] : Array.isArray(tree)
  ? tree.flatMap(node => nodes(node, predicate))
  : [...(predicate(tree) ? [tree] : []), ...nodes(tree.props?.children, predicate)];
const selected = [{ key: "gap_check", version: "original-version", digest: "1".repeat(64) },
  { key: "public_research", version: "other-original-version", digest: "2".repeat(64) }];

test("input control removes and restores each original inherited skill without refetching or upgrading", () => {
  let excluded = [], requests = 0;
  const props = { api: async () => { requests++; throw Error("must not fetch on removal"); },
    continued: selected, excluded, onExcludedChange: value => { excluded = value; },
    requested: [], onRequestedChange() {}, disabled: false };
  let tree = ContinuedSkillPicker(props);
  let buttons = nodes(tree, node => node.type === "button");
  assert.equal(buttons.length, 2);
  assert.equal(buttons[0].props["aria-label"], "移除沿用技能 资料查漏");
  assert.equal(buttons[0].props["aria-pressed"], true);
  buttons[0].props.onClick();
  assert.deepEqual(excluded, ["gap_check"]);
  tree = ContinuedSkillPicker({ ...props, excluded });
  buttons = nodes(tree, node => node.type === "button");
  assert.equal(buttons[0].props["aria-label"], "恢复沿用技能 资料查漏");
  assert.equal(buttons[0].props["aria-pressed"], false);
  buttons[0].props.onClick();
  assert.deepEqual(excluded, []);
  assert.equal(selected[0].version, "original-version");
  assert.equal(requests, 0);
});

test("personal catalog, explicit selection and the pending guard reach the existing picker", () => {
  const onRequestedChange = () => {}, api = async () => ({});
  const tree = ContinuedSkillPicker({ api, resource: "v1/personal/agent-skills", continued: selected,
    excluded: [], onExcludedChange() {}, requested: [selected[1]], onRequestedChange, disabled: true });
  assert.ok(nodes(tree, node => node.type === "button").every(node => node.props.disabled));
  const picker = nodes(tree, node => node.type === SkillPicker)[0];
  assert.equal(picker.props.api, api);
  assert.equal(picker.props.resource, "v1/personal/agent-skills");
  assert.deepEqual(picker.props.value, [selected[1]]);
  assert.equal(picker.props.onChange, onRequestedChange);
  assert.equal(picker.props.disabled, true);
  const inherited = nodes(tree, node => node.type === "button");
  assert.equal(inherited.length, 1);
  assert.equal(inherited[0].props["aria-label"], "移除沿用技能 资料查漏");
});
