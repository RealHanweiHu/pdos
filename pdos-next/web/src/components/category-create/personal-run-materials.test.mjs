import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const dependency = createRequire(path.join(directory, "../../../package.json"));
const ts = dependency("typescript"), React = dependency("react");
let hooks = null;
const same = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
const shim = { ...React,
  useState(initial) { const state = hooks, index = state.index++; if (!(index in state.values)) state.values[index] = typeof initial === "function" ? initial() : initial; return [state.values[index], value => { state.values[index] = typeof value === "function" ? value(state.values[index]) : value; }]; },
  useEffect(effect, dependencies) { const state = hooks, index = state.index++, prior = state.values[index]; if (!prior || !same(prior.dependencies, dependencies)) { state.values[index] = { dependencies, cleanup: prior?.cleanup }; state.effects.push(() => { state.values[index].cleanup?.(); state.values[index].cleanup = effect(); }); } },
};
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = specifier => specifier === "react" ? shim
    : specifier === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") })
    : specifier.endsWith(".module.css") ? { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) }
    : specifier.startsWith("@/") ? load(path.join(directory, "../../..", "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { PersonalRunMaterials } = load(path.join(directory, "personal-run-materials.tsx"));
const runId = "11111111-1111-4111-8111-111111111111", categoryId = "22222222-2222-4222-8222-222222222222";
const candidate = digest => ({ type: "category_candidate", cancel_epoch: 0, candidate_digest: digest,
  input: { key: `pump-${digest[0]}`, name: digest[0] === "a" ? "原候选名称" : "待确认品类", purpose: "合成用途", groups: { knowledge: [], parameters: [], snapshot_refs: [] } },
  source: { model_call_id: "model", skill: { key: "category-create", digest: "source" } }, snapshots: [] });
const adopted = { type: "category_adopted", proof_version: 1, run_id: runId, category_id: categoryId,
  receipt_id: "33333333-3333-4333-8333-333333333333", candidate_event_id: "44444444-4444-4444-8444-444444444444",
  input_ref: "55555555-5555-4555-8555-555555555555", candidate_digest: "a".repeat(64), cancel_epoch: 0 };
const tick = () => new Promise(resolve => setImmediate(resolve));
function nodes(tree, predicate) { if (!tree || typeof tree !== "object") return []; if (Array.isArray(tree)) return tree.flatMap(item => nodes(item, predicate)); return [...(predicate(tree) ? [tree] : []), ...nodes(tree.props?.children, predicate)]; }
function session(api) {
  const state = { values: [], index: 0, effects: [] }, openedCandidates = [], openedCategories = [];
  let unavailable = 0, tree;
  const props = { api, runId, onOpenCandidate: (...value) => openedCandidates.push(value), onOpenCategory: (...value) => openedCategories.push(value), onUnavailable: () => unavailable++ };
  function render() { state.index = 0; state.effects = []; hooks = state; try { tree = PersonalRunMaterials(props); } finally { hooks = null; } return tree; }
  return { render, openedCandidates, openedCategories, unavailable: () => unavailable, cards: () => nodes(render(), node => node.type?.name === "PaiDocumentCard"),
    async settle() { for (let index = 0; index < 6; index++) { await tick(); render(); const effects = state.effects; state.effects = []; effects.forEach(effect => effect()); } return tree; },
    unmount() { state.values.forEach(value => value?.cleanup?.()); } };
}

test("history restores actual saved category and pending candidate cards with direct open callbacks", async () => {
  const c = session(async path => path === "v1/categories" ? [{ id: categoryId, name: "人工修订后的品类", purpose: "当前用途" }]
    : { items: [{ sequence: 1, event: candidate("a".repeat(64)) }, { sequence: 2, event: adopted }, { sequence: 3, event: candidate("b".repeat(64)) }], next_cursor: 0 });
  try {
    await c.settle(); const cards = c.cards(); assert.equal(cards.length, 2);
    const saved = cards.find(card => card.props.title === "人工修订后的品类"); assert.ok(saved); assert.equal(saved.props.action, "返回编辑");
    saved.props.onOpen(); assert.equal(c.openedCategories[0][0], runId); assert.equal(c.openedCategories[0][1].receipt_id, adopted.receipt_id); assert.equal(c.openedCategories[0][2].name, "人工修订后的品类");
    const pending = cards.find(card => card.props.title === "待确认品类"); assert.ok(pending); pending.props.onOpen(); assert.equal(c.openedCandidates[0][0], runId); assert.equal(c.openedCandidates[0][1].candidate_digest, "b".repeat(64));
  } finally { c.unmount(); }
});

test("permission failure hides historical materials and invokes the shared cleanup", async () => {
  const c = session(async () => { throw Object.assign(Error("denied"), { status: 403 }); });
  try { await c.settle(); assert.equal(c.unavailable(), 1); assert.equal(c.cards().length, 0); } finally { c.unmount(); }
});
