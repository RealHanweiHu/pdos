import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), dependency = createRequire(path.join(directory, "../../package.json"));
const ts = dependency("typescript"), React = dependency("react");
let hooks;
const same = (a, b) => a && b && a.length === b.length && a.every((v, i) => Object.is(v, b[i]));
const shim = { ...React,
  useState(initial) { const h = hooks, i = h.index++; if (!(i in h.values)) h.values[i] = typeof initial === "function" ? initial() : initial; return [h.values[i], value => { h.values[i] = typeof value === "function" ? value(h.values[i]) : value; }]; },
  useEffect(effect, deps) { const h = hooks, i = h.index++, old = h.values[i]; if (!old || !same(old.deps, deps)) { h.values[i] = { deps }; h.effects.push(() => { old?.cleanup?.(); h.values[i].cleanup = effect(); }); } },
};
function compile(relative, require) {
  const filename = path.join(directory, relative), loaded = new Module(filename);
  loaded.require = require;
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const data = compile("../lib/personal-preferences.ts", dependency);
const require = name => name === "react" ? shim : name.endsWith(".css") ? {} : name === "./ui/button" ? { Button: "button" } : name === "@/lib/browser-api" ? { browserApi: async () => { throw Error("provide explicit test API"); } } : name === "@/lib/personal-preferences" ? data : name === "./pai-conversation" ? { PaiWelcome: "default-welcome" } : name === "@phosphor-icons/react" ? { ArrowUpRight: "i", Sparkle: "i" } : dependency(name);
const { PersonalPreferences } = compile("personal-preferences.tsx", require);
const { PersonalPreferenceWelcome } = compile("personal-preference-welcome.tsx", require);
const text = tree => typeof tree === "string" || typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(tree.props?.children) : "";
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const tick = () => new Promise(resolve => setImmediate(resolve));
function runner(component, props) {
  const h = { values: [], index: 0, effects: [] };
  return { props, render() { h.index = 0; h.effects = []; hooks = h; const tree = component(props); hooks = null; h.effects.forEach(effect => effect()); return tree; }, async settle() { for (let i = 0; i < 4; i++) { this.render(); await tick(); } return this.render(); }, async click(label) { const button = nodes(this.render()).find(node => node.type === "button" && text(node) === label); assert.ok(button, label); assert.ok(!button.props.disabled, label); button.props.onClick(); await this.settle(); }, async change(label, value) { const parent = nodes(this.render()).find(node => node.type === "label" && text(node).startsWith(label)); const input = nodes(parent).find(node => ["input", "select"].includes(node.type)); assert.ok(input, label); input.props.onChange({ target: { value } }); await this.settle(); }, async submit() { nodes(this.render()).find(node => node.type === "form").props.onSubmit({ preventDefault() {} }); await this.settle(); } };
}
const initial = () => ({ revision: 0, preferences: data.newPersonalPreferences(), navigation_candidates: [], role_defaults: { welcome_examples: [], summary_sections: [] }, updated_at: null });

test("opening settings only reads; explicit save persists all fields and clear sends defaults", async () => {
  const writes = []; let state = initial();
  const r = runner(PersonalPreferences, { api: async (_path, body) => { if (!body) return state; writes.push(structuredClone(body)); state = { ...state, revision: state.revision + 1, preferences: body.preferences }; return state; } });
  await r.settle(); assert.equal(writes.length, 0);
  await r.change("回答语言", "en"); await r.change("回答详略", "detailed"); await r.change("岗位", "quality"); await r.change("部门", "质量部");
  assert.equal(writes.length, 0);
  await r.submit(); assert.equal(writes.length, 1); assert.equal(writes[0].preferences.role, "quality"); assert.equal(writes[0].preferences.department, "质量部"); assert.equal(writes[0].preferences.answer_language, "en"); assert.equal(writes[0].preferences.response_detail, "detailed"); assert.equal(writes[0].expected_revision, 0);
  await r.click("清空偏好"); assert.deepEqual(writes[1].preferences, data.newPersonalPreferences()); assert.equal(writes[1].expected_revision, 1);
});

test("lost response keeps edits for identical retry; conflict refresh keeps explicit draft", async () => {
  const writes = []; let state = initial(), lose = true, conflict = false;
  const r = runner(PersonalPreferences, { api: async (_path, body) => {
    if (!body) return state;
    writes.push(structuredClone(body));
    if (conflict) { conflict = false; state = { ...state, revision: 5 }; throw Object.assign(Error("changed elsewhere"), { code: "VERSION_CONFLICT" }); }
    state = { ...state, revision: body.expected_revision + 1, preferences: body.preferences };
    if (lose) { lose = false; throw Error("response lost"); }
    return state;
  } });
  await r.settle(); await r.change("部门", "研发部"); await r.submit(); assert.match(text(r.render()), /response lost/);
  await r.submit(); assert.deepEqual(writes[0], writes[1]);
  conflict = true; await r.change("回答详略", "brief"); await r.submit();
  assert.match(text(r.render()), /changed elsewhere/);
  await r.click("读取最新设置并保留填写"); await r.submit();
  assert.equal(writes.at(-1).expected_revision, 5); assert.equal(writes.at(-1).preferences.response_detail, "brief"); assert.equal(writes.at(-1).preferences.department, "研发部");
});

test("favorite selection is explicit and bounded while saved navigation uses server candidates", async () => {
  const state = { ...initial(), navigation_candidates: [{ id: "cat", kind: "category", label: "本人可读", href: "?area=projects&category=cat" }] };
  const r = runner(PersonalPreferences, { api: async () => state }); await r.settle();
  const favorite = nodes(r.render()).find(node => node.type?.name === "FavoriteOptions" && node.props.kind === "category");
  favorite.props.onChange(["cat"]); await r.settle();
  assert.equal(nodes(r.render()).find(node => node.type === "a").props.href, state.navigation_candidates[0].href);
  const writes = []; r.props.api = async (_path, body) => { if (body) writes.push(body); return state; }; await r.settle();
  const chooser = nodes(r.render()).find(node => node.type?.name === "FavoriteOptions" && node.props.kind === "category"); chooser.props.onChange(["cat"]); await r.settle(); await r.submit();
  assert.deepEqual(writes[0].preferences.favorite_category_ids, ["cat"]);
});

test("favorite picker reads authorized pages and search, then only edits the unsaved selection", async () => {
  const calls = [], changed = [];
  const api = async (path, body) => {
    calls.push({ path, body });
    if (path === "v1/personal/preferences") return initial();
    const query = new URL(`https://synthetic.invalid/${path}`).searchParams;
    const id = query.get("cursor") ? "next" : query.get("query") ? "found" : "first";
    return { items: [{ id, kind: "category", label: id }], next_cursor: id === "first" ? "cursor" : null };
  };
  const parent = runner(PersonalPreferences, { api }); await parent.settle();
  const element = nodes(parent.render()).find(node => node.type?.name === "FavoriteOptions" && node.props.kind === "category");
  const props = { ...element.props, onChange: ids => { changed.push(ids); props.selected = ids; } };
  const picker = runner(element.type, props); await picker.settle();
  assert.match(text(picker.render()), /first/);
  await picker.click("读取更多品类"); assert.match(text(picker.render()), /next/);
  await picker.change("查找常用品类", "当前搜索"); await picker.click("查找"); assert.match(text(picker.render()), /found/);
  const checkbox = nodes(picker.render()).find(node => node.type === "input" && node.props.type === "checkbox");
  checkbox.props.onChange({ target: { checked: true } }); await picker.settle();
  assert.deepEqual(changed, [["found"]]); assert.ok(calls.every(call => call.body === undefined));
  props.selected = Array.from({ length: 10 }, (_, index) => `saved-${index}`); await picker.settle();
  assert.equal(nodes(picker.render()).find(node => node.type === "input" && node.props.type === "checkbox").props.disabled, true);
});

test("welcome defaults on failure; saved role examples only fill text and focus rechecks candidates", async () => {
  const originalWindow = globalThis.window, events = new Map();
  globalThis.window = { addEventListener: (name, fn) => events.set(name, fn), removeEventListener: name => events.delete(name) };
  try {
    const fallback = runner(PersonalPreferenceWelcome, { api: async () => { throw Error("optional failure"); }, onSuggest() {} });
    await fallback.settle(); assert.equal(fallback.render().type, "default-welcome");
    let state = { ...initial(), role_defaults: { welcome_examples: ["查找类似质量问题"], summary_sections: [] }, navigation_candidates: [{ id: "allowed", kind: "project", label: "可读项目", href: "?area=cockpit&project=allowed" }] };
    const filled = [], calls = [];
    const r = runner(PersonalPreferenceWelcome, { api: async (path, body) => { calls.push({ path, body }); return state; }, onSuggest: value => filled.push(value) });
    await r.settle(); await r.click("查找类似质量问题"); assert.deepEqual(filled, ["查找类似质量问题"]); assert.ok(calls.every(call => call.body === undefined));
    assert.match(text(r.render()), /可读项目/);
    state = { ...initial(), role_defaults: state.role_defaults, navigation_candidates: [] }; events.get("focus")(); await r.settle();
    assert.doesNotMatch(text(r.render()), /可读项目/);
  } finally { globalThis.window = originalWindow; }
});
