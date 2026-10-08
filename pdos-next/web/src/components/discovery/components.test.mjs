import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as icons from "@phosphor-icons/react";

// Installed TS compiler only; emits in memory, never writes .next or a build cache.
const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript");
const React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
let hookSession = null;
/* eslint-disable react-hooks/rules-of-hooks -- Test-only hook dispatcher switches real SSR and explicit in-memory event sessions. */
const reactShim = { ...React, useId: () => hookSession ? "test-id" : React.useId(),
  useState: initial => {
    if (!hookSession) return React.useState(initial);
    const session = hookSession;
    const index = session.index++;
    if (!(index in session.states)) session.states[index] = typeof initial === "function" ? initial() : initial;
    return [session.states[index], value => { session.states[index] = typeof value === "function" ? value(session.states[index]) : value; }];
  },
};
/* eslint-enable react-hooks/rules-of-hooks */
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(extension => filename + extension).find(existsSync);
  if (!filename) throw new Error("Module not found");
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename);
  modules.set(filename, loaded);
  const localRequire = createRequire(filename);
  loaded.require = specifier => specifier === "react" ? reactShim : specifier === "@phosphor-icons/react" ? icons
    : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : localRequire(specifier);
  const compiled = ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } });
  loaded._compile(compiled.outputText, filename);
  return loaded.exports;
}
const { ResearchStart, SourceImport, SourcePackage, DefinitionSelection, CandidateReading } = load(path.join(directory, "index.ts"));
const { grouped, selectionRequest } = load(path.join(directory, "contracts.ts"));
const citation = { artifact_id: "synthetic-artifact", expected_revision: 3, content_hash: "a".repeat(64), derived_line: 4,
  quote: "合成原文：转速001.2300，单位待核对", location: { kind: "cell", sheet: "规格", cell: "B4" },
  original_id: "synthetic-original", original_version: "v3", original_hash: "b".repeat(64) };
const value = { parameter: "转速", value_type: "number", value: "001.2300", lower: null, upper: null, text: null,
  unit: null, tolerance: null, test_conditions: [], method: null, applicability: null, acceptance_criterion: null };
const observation = { id: "synthetic-observation", key: "speed", kind: "spec", origin: "ai_extraction",
  raw_text: citation.quote, statement: "转速候选", spec: value, sources: [citation] };
const stored = { observation, verification: { status: "pending", reason: "字段尚未核对", accepted_requirement: false } };
const research = { id: "synthetic-research", tenant_id: "synthetic-tenant", owner_id: "synthetic-human", scope_id: "synthetic-scope",
  audience: "private", revision: 4, title: "合成客户输入", mode: "oem", questions: ["完整吗"], use_cases: ["客户设备"],
  items: [{ category: "specification", source: citation }], observations: [stored] };
const context = { scopeLabel: "合成研究范围", productLabel: "合成真实产品", purpose: "客户设备用途", actorLabel: "合成具名人员",
  requiredCategories: ["drawing", "specification"], readiness: { start: true, import: true, preview: true } };
const source = { id: "source-option", label: "合成授权原件", category: "specification", citation };
const noWrites = { onStart: async () => { throw new Error("Rendering must not write"); },
  onImport: async () => { throw new Error("Rendering must not write"); }, onPreview: async () => { throw new Error("Rendering must not write"); } };
function html(Component, props) { return renderToStaticMarkup(React.createElement(Component, props)); }
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
function session(Component, props) {
  const hooks = { states: [], index: 0 };
  return { render() { hookSession = hooks; hooks.index = 0;
    try { return Component(props); } finally { hookSession = null; } }, hooks };
}
async function submit(tree, values) {
  const original = globalThis.FormData;
  globalThis.FormData = class { constructor(form) { this.values = form.values; } get(key) { return this.values[key] ?? null; } };
  try { await elements(tree, e => e.type === "form")[0].props.onSubmit({ preventDefault() {}, currentTarget: { values } }); }
  finally { globalThis.FormData = original; }
}

test("source reading separates raw values, origin, correspondence and maturity", () => {
  const output = html(SourcePackage, { research, context });
  for (const label of ["AI 抽取", "待原值核对", "001.2300", "规格 · B4", "仍缺 drawing", "候选，尚未成为正式规格", citation.quote]) assert.ok(output.includes(label), label);
  assert.equal(output.includes("客户已批准"), false);
});
test("permission-drift reading takes redacted input and reveals no raw text", () => {
  const output = html(SourcePackage, { research: null, context, unavailableReason: "来源权限已变化" });
  assert.ok(output.includes("来源权限已变化")); assert.equal(output.includes(citation.quote), false);
});
test("missing completeness policy cannot imply complete OEM inputs", () => {
  assert.ok(html(SourcePackage, { research, context: { ...context, requiredCategories: [] } }).includes("规则尚未绑定"));
});
test("missing ports or binding visibly disable each action", () => {
  for (const [Component, props, label] of [
    [ResearchStart, {}, "保存研究范围"], [SourceImport, { research, sources: [source] }, "保存为待核对观察"],
    [DefinitionSelection, { research }, "核对定义候选"],
  ]) {
    const output = html(Component, { ...props, context: { ...context, scopeLabel: null, productLabel: null,
      readiness: { start: false, import: false, preview: false } }, callbacks: noWrites });
    assert.match(output, new RegExp(`<button[^>]*disabled=""[^>]*>${label}</button>`));
    assert.equal(output.includes("回执："), false);
  }
});
test("empty authorized source list is explicit and cannot save", () => {
  const output = html(SourceImport, { research, sources: [], context, callbacks: noWrites });
  assert.ok(output.includes("暂无可消费的授权来源")); assert.match(output, /<button[^>]*disabled=""/);
});
test("start callback sends no tenant/product/project authority", async () => {
  const calls = [];
  const component = session(ResearchStart, { context, callbacks: { onStart: async payload => calls.push(payload) } });
  await submit(component.render(), { title: "OEM 客户资料", mode: "oem", questions: "完整性\n冲突", use_cases: "客户设备" });
  assert.deepEqual(calls, [{ title: "OEM 客户资料", mode: "oem", questions: ["完整性", "冲突"], use_cases: ["客户设备"] }]);
});
test("import callback preserves decimal text and exact pinned citation", async () => {
  const calls = [];
  const component = session(SourceImport, { research, sources: [source], context,
    callbacks: { onImport: async (...args) => calls.push(args) } });
  const checkbox = elements(component.render(), e => e.type === "input" && e.props.type === "checkbox")[0];
  checkbox.props.onChange({ target: { checked: true } });
  await submit(component.render(), { key: "speed", statement: "转速人工观察", parameter: "转速", value: "001.2300", conditions: "25°C\n湿度未知" });
  const [researchId, revision, payload] = calls[0];
  assert.equal(researchId, research.id); assert.equal(revision, 4);
  assert.equal(payload.observations[0].spec.value, "001.2300");
  assert.equal(payload.observations[0].spec.unit, null); assert.equal(payload.observations[0].spec.tolerance, null);
  assert.deepEqual(payload.observations[0].sources, [citation]);
  assert.equal(payload.observations[0].raw_text, citation.quote);
});
test("selection sends one group to the existing preview callback and no confirmation", async () => {
  const calls = [];
  const second = { ...stored, observation: { ...observation, id: "second", key: "power" } };
  const component = session(DefinitionSelection, { research: { ...research, observations: [stored, second] }, context,
    parent: { id: "fixed-parent", revision: 2 }, callbacks: { onPreview: async (...args) => calls.push(args) } });
  const initial = component.render();
  // Groups are alphabetical: only select speed, leaving power omitted.
  const checkboxes = elements(initial, e => e.type === "input" && e.props.type === "checkbox");
  checkboxes[1].props.onChange({ target: { checked: true } });
  const radios = elements(component.render(), e => e.type === "input" && e.props.type === "radio");
  radios[3].props.onChange();
  const reasons = elements(component.render(), e => e.type === "textarea" && typeof e.props.onChange === "function");
  reasons[1].props.onChange({ target: { value: "选择转速，保留人工候选" } });
  await submit(component.render(), { title: "内部候选", reason: "本次输入导入", partial: "只导入转速，功率待补" });
  assert.equal(calls.length, 1);
  assert.deepEqual(calls[0][2].selections, [{ key: "speed", observation_id: observation.id, reason: "选择转速，保留人工候选" }]);
  assert.equal(calls[0][2].parent_definition_id, "fixed-parent");
});
test("failed callbacks retain input and render an actionable error", async () => {
  const component = session(ResearchStart, { context, callbacks: { onStart: async () => { throw new Error("当前范围已变化"); } } });
  await submit(component.render(), { title: "研究输入", mode: "research", questions: "问题", use_cases: "场景" });
  assert.ok(elements(component.render(), e => e.props?.role === "alert").some(e => e.props.children === "当前范围已变化"));
  assert.equal(component.hooks.states[0], false);
});
test("selection validation and reserved keys cannot add accidental groups", () => {
  assert.throws(() => selectionRequest("标题", "变更原因", "", {}));
  assert.throws(() => selectionRequest("标题", "变更原因", "", { speed: { included: true, observationId: null, reason: "" } }));
  const special = { ...stored, observation: { ...observation, key: "__proto__" } };
  assert.equal(grouped({ ...research, observations: [special] })[0][0], "__proto__");
});
test("candidate reading shows unresolved values, provenance and no fake completion", () => {
  const candidate = { research_id: research.id, research_revision: 4, product_id: "real-product", expected_product_revision: 2,
    payload: { title: "内部候选", purpose: context.purpose, visibility: "private", use_cases: [], requirements: [], constraints: [],
      unknowns: ["单位待核对"], exclusions: [], sources: [], specs: [{ ...value, key: "speed", availability: "conflicted", nature: "extracted",
        state: "needs_confirmation", owner_id: "synthetic-human", reason: "保留两种口径", sources: [] }] },
    provenance: [{ key: "speed", observations: [stored], selected_id: null, actor_id: "synthetic-human", reason: "保留冲突", maturity: "candidate" }],
    conflicts: [{ key: "speed", observation_ids: ["a", "b"], reasons: ["unit"] }], missing_categories: [], omitted_keys: [], digest: "fixed-hash",
    effect: "仅形成内部定义草稿；不发布规格、不创建项目、不表示客户批准" };
  const output = html(CandidateReading, { candidate });
  for (const label of ["冲突，目标值未裁决", "单位待核对", "并列冲突仍保留", "合成原文", "fixed-hash"]) assert.ok(output.includes(label));
  assert.equal(output.includes("已提交成功"), false);
});
