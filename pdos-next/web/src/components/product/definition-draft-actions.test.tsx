// eslint-disable-next-line @typescript-eslint/ban-ts-comment -- The test-only dynamic loader and hook dispatcher exercise runtime behavior; production files remain strictly checked.
// @ts-nocheck -- Test-only dispatcher drives real component handlers and effects without a DOM dependency.
import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";

const directory = __dirname;
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
// Explicit test-only override; production never reads this environment variable.
const source = path.join(directory, "definition-draft-actions.tsx");
let hooks = null;
const equalDependencies = (a, b) => !!a && !!b && a.length === b.length && a.every((value, index) => Object.is(value, b[index]));
/* eslint-disable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps -- Test-only hook dispatcher executes actual component effects and handlers. */
const react = { ...React,
  useState(initial) {
    if (!hooks) return React.useState(initial);
    const own = hooks, index = own.index++;
    if (!(index in own.slots)) own.slots[index] = typeof initial === "function" ? initial() : initial;
    return [own.slots[index], value => { if (!own.disposed) { own.slots[index] = typeof value === "function" ? value(own.slots[index]) : value; own.dirty = true; } }];
  },
  useRef(initial) {
    if (!hooks) return React.useRef(initial);
    const index = hooks.index++;
    return hooks.slots[index] ??= { current: initial };
  },
  useCallback(callback, dependencies) {
    if (!hooks) return React.useCallback(callback, dependencies);
    const index = hooks.index++;
    if (!equalDependencies(hooks.slots[index]?.dependencies, dependencies)) hooks.slots[index] = { callback, dependencies };
    return hooks.slots[index].callback;
  },
  useEffect(effect, dependencies) {
    if (!hooks) return React.useEffect(effect, dependencies);
    const own = hooks, index = own.index++;
    if (!equalDependencies(own.slots[index]?.dependencies, dependencies)) {
      const previous = own.slots[index];
      const entry = { dependencies, cleanup: previous?.cleanup };
      own.slots[index] = entry;
      own.effects.push(() => { entry.cleanup?.(); entry.cleanup = effect(); });
    }
  },
};
/* eslint-enable react-hooks/rules-of-hooks, react-hooks/exhaustive-deps */
const modules = new Map();
const container = props => React.createElement("div", null, props.children);
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "react" ? react
    : name === "next/link" ? props => React.createElement("a", { href: props.href }, props.children)
    : name === "@phosphor-icons/react" ? Object.fromEntries(["ShareNetwork", "LockKey", "CheckCircle", "WarningCircle"].map(key => [key, () => React.createElement("svg")]))
    : name === "radix-ui" ? { Dialog: Object.fromEntries(["Root", "Portal", "Overlay", "Content", "Title", "Description"].map(key => [key, container])) }
    : name.startsWith("@/") ? load(path.join(webRoot, "src", name.slice(2)))
    : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}
const { DefinitionDraftActions } = load(path.resolve(source));
const editorTools = load(path.join(webRoot, "src/lib/definition-item-editor.ts"));
function elements(tree, predicate) {
  if (!tree || typeof tree !== "object") return [];
  if (Array.isArray(tree)) return tree.flatMap(item => elements(item, predicate));
  return [...(predicate(tree) ? [tree] : []), ...elements(tree.props?.children, predicate)];
}
const tick = () => new Promise(resolve => setImmediate(resolve));
function component(props) {
  let instance, key, inner, tree;
  function unmount() {
    if (!instance) return;
    instance.slots.forEach(slot => slot?.cleanup?.()); instance.disposed = true;
  }
  function render() {
    const wrapper = DefinitionDraftActions(props);
    if (!instance || key !== wrapper.key) {
      unmount(); key = wrapper.key; inner = wrapper;
      instance = { slots: [], index: 0, effects: [], disposed: false, dirty: true };
    }
    inner = wrapper;
    instance.index = 0; instance.effects = []; instance.dirty = false;
    hooks = instance;
    try { tree = inner.type(inner.props); } finally { hooks = null; }
    instance.effects.forEach(effect => effect());
  }
  render();
  return {
    async flush() { for (let i = 0; i < 8; i++) { await tick(); if (instance.dirty) render(); } return tree; },
    tree: () => tree,
    html: () => renderToStaticMarkup(tree),
    setProps(next) { props = next; render(); },
    unmount,
  };
}
const id = n => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const human = id(1), category = id(2), product = id(3), definitionId = id(4);
function definition(changes = {}) {
  return { id: definitionId, category_id: category, product_id: product, variant_id: null,
    revision: 3, status: "draft", sealed: false, visibility: "private", title: "合成固定定义", purpose: "合成测试用途",
    owner_id: human, use_cases: [], requirements: [], constraints: [], unknowns: [], exclusions: [], sources: [],
    source_status: "current", differences: [], parent_definition_id: id(40), change_reason: "固定父版",
    specs: [{ key: "pressure", parameter: "压力", value_type: "number", value: "0", lower: null, upper: null,
      text: null, unit: "PSI", tolerance: "0", availability: "known", item_status: "confirmed",
      test_conditions: ["固定台架"], condition_note: "标准工况", method: "读取真实原文", acceptance_criterion: "精确零目标",
      parameter_id: id(10), parameter_version: 2, modality: "must", exceptions: [{ text: "室内", numeric: 0 }],
      applicable_variants: [{ key: "base", enabled: false }], owner_id: id(11), reason: "原始依据", nature: "decided",
      origin: "ai_draft", writer_id: id(12), run_id: id(13), confirmed_by: human, receipt_id: id(14), prepared_candidate_id: id(15),
      source_refs: [{ type: "human", id: human, version: 1, statement: "私有具名原文" }], sources: [] }],
    item_versions: [{ item_id: id(5), item_version: 7, row_id: id(6), key: "pressure" }], ...changes };
}
function environment(t, changes = {}) {
  const previous = globalThis.window, storage = new Map(), calls = [];
  const sessionStorage = { getItem: key => storage.get(key) ?? null, setItem: (key, value) => storage.set(key, value), removeItem: key => storage.delete(key) };
  globalThis.window = { sessionStorage };
  let saved = 0, denied = 0;
  const props = { definition: definition(), product: { id: product, revision: 9 }, principalId: human, sources: [], isLatest: true,
    api: (path, body) => new Promise((resolve, reject) => {
      if (path === "v1/commands") assert.ok([...storage.values()].some(value => JSON.parse(value).command.idempotency_key === body.idempotency_key), "Write-ahead journal must precede request");
      calls.push({ path, body, resolve, reject });
    }), onSaved: () => { saved++; }, onAccessDenied: () => { denied++; }, ...changes };
  let mounted = component(props);
  t.after(() => { mounted.unmount(); globalThis.window = previous; });
  return { props, storage, calls, sessionStorage, saved: () => saved, denied: () => denied,
    tree: () => mounted.tree(), html: () => mounted.html(), flush: () => mounted.flush(),
    remount(next = props) { mounted.unmount(); mounted = component(next); },
    setProps: next => mounted.setProps(next), unmount: () => mounted.unmount() };
}
function content(value) {
  if (Array.isArray(value)) return value.map(content).join("");
  if (value && typeof value === "object") return content(value.props?.children);
  return value == null ? "" : String(value);
}
function button(env, label) { return elements(env.tree(), element => typeof element.props?.onClick === "function" && content(element.props.children) === label)[0]; }
async function click(env, label) {
  const element = button(env, label); assert.ok(element, `Missing button: ${label}`); assert.ok(!element.props.disabled, `${label} disabled`);
  element.props.onClick(); await env.flush();
}
async function input(env, label, value) {
  const element = elements(env.tree(), item => item.props?.["aria-label"] === label && item.props.onChange)[0];
  assert.ok(element, `Missing field: ${label}`); element.props.onChange({ target: { value } }); await env.flush();
}
async function submitForm(env) { elements(env.tree(), node => node.type === "form")[0].props.onSubmit({ preventDefault() {} }); await env.flush(); }
function receipt(call, changes = {}) {
  const request = call.body, inherit = request.operation === "product.definition.draft";
  return { id: id(100), category_id: request.category_id, product_id: request.product_id, operation: request.operation,
    subject_type: "definition_revision", subject_id: inherit ? id(101) : request.payload.definition_id,
    subject_revision: inherit ? request.payload.expected_parent_revision + 1 : 3,
    writer_id: human, requester_id: human, agent_run_id: null,
    result: inherit ? { inherited_from: request.payload.parent_definition_id } : { definition_id: request.payload.definition_id,
      changes: request.payload.ops.map(op => ({ item_id: op.item_id ?? id(102), item_version: (op.base_version ?? 0) + 1, key: op.content?.key ?? "pressure", removed: op.op === "remove" })) }, ...changes };
}
async function edited(env) { await env.flush(); await click(env, "修订压力"); await input(env, "依据或未知说明", "人工修订依据"); await submitForm(env); return env.calls.at(-1); }
const failure = (status, code, reason) => Object.assign(new Error(`合成错误 ${code}`), { status, code, detail: { reason } });

test("sealed typed-only G0/published continuation sends only fixed-parent fields", async t => {
  for (const status of ["draft", "published"]) await t.test(status, async t => {
    const env = environment(t, { definition: definition({ sealed: true, status }) }); await env.flush();
    assert.equal(button(env, "修订压力"), undefined);
    await input(env, "续版原因", "  保留全部内容继续工作  "); await click(env, "保留完整内容，创建新草稿");
    const call = env.calls[0];
    assert.deepEqual(call.body.payload, { mode: "inherit_parent", parent_definition_id: definitionId, expected_parent_revision: 3, change_reason: "保留全部内容继续工作" });
    assert.deepEqual(call.body.source_read_set, []); assert.equal(call.body.category_id, category); assert.equal(call.body.expected_revision, 9);
    call.resolve(receipt(call)); await env.flush(); assert.equal(env.saved(), 1); assert.match(env.html(), /已取得保存回执/);
  });
});
test("actual full item edit retains zero and M3 fields, strips every provenance field", async t => {
  const env = environment(t), call = await edited(env), op = call.body.payload.ops[0];
  assert.equal(call.body.operation, "product.definition.item.patch"); assert.equal(op.item_id, id(5)); assert.equal(op.base_version, 7);
  assert.equal(op.content.value, "0"); assert.equal(op.content.tolerance, "0"); assert.equal(op.content.text_value, null);
  assert.equal(op.content.parameter_id, id(10)); assert.equal(op.content.parameter_version, 2); assert.equal(op.content.verification_method, "读取真实原文");
  assert.equal(op.content.condition_note, "标准工况"); assert.equal(op.content.modality, "must"); assert.equal(op.content.owner_id, id(11));
  assert.deepEqual(op.content.exceptions, [{ text: "室内", numeric: 0 }]); assert.deepEqual(op.content.applicable_variants, [{ key: "base", enabled: false }]);
  assert.equal(op.source_refs[0].statement, "私有具名原文");
  for (const key of ["origin", "writer_id", "run_id", "confirmed_by", "receipt_id", "prepared_candidate_id", "sources", "text", "method", "item_id"]) assert.equal(Object.hasOwn(op.content, key), false, key);
  call.resolve(receipt(call)); await env.flush(); assert.equal(env.saved(), 1);
});
test("boolean false and enum text survive actual editing without numeric conversion", async t => {
  for (const [kind, value] of [["boolean", "false"], ["enum", "matte"]]) await t.test(kind, async t => {
    const parent = definition(); parent.specs[0] = { ...parent.specs[0], value_type: kind, value: null, tolerance: null, text: value, unit: null };
    const env = environment(t, { definition: parent }), call = await edited(env);
    assert.equal(call.body.payload.ops[0].content.text_value, value); assert.equal(call.body.payload.ops[0].content.value, null);
    call.resolve(receipt(call)); await env.flush();
  });
});
test("new confirmed item requires user's explicit statement; no source is invented", async t => {
  const env = environment(t); await env.flush(); await click(env, "新增规格条目");
  await input(env, "条目标识", "flag"); await input(env, "参数名称", "显示开关");
  await input(env, "值类型", "boolean"); await input(env, "信息状态", "known"); await input(env, "实际值", "false"); await input(env, "确认状态", "confirmed");
  await submitForm(env); assert.equal(env.calls.length, 0); assert.match(env.html(), /明确选择来源/);
  await input(env, "本人具名陈述", "  我选择不配显示功能  "); await click(env, "加入本人陈述"); await submitForm(env);
  const op = env.calls[0].body.payload.ops[0]; assert.equal(op.item_id, undefined); assert.equal(op.base_version, undefined);
  assert.equal(op.source_refs[0].id, human); assert.equal(op.source_refs[0].statement, "我选择不配显示功能"); assert.equal(op.content.text_value, "false");
});
test("remove uses actual preview then the sealed request, never sends content or source fields", async t => {
  const env = environment(t); await env.flush(); await click(env, "移除压力");
  assert.equal(env.calls[0].path, "v1/commands/preview"); const initial = env.calls[0].body;
  assert.deepEqual(initial.payload.ops, [{ op: "remove", item_id: id(5), base_version: 7 }]);
  const prepared = { ...initial, payload: { ...initial.payload, confirmation_token: "actual-preview-token" } };
  env.calls[0].resolve({ command: prepared, review: { definition_id: definitionId, effect: "追加移除版本；保留原记录。" } }); await env.flush();
  assert.equal(env.calls.length, 1); assert.match(env.html(), /条目 v7/); await click(env, "确认移除此条");
  assert.deepEqual(env.calls[1].body, prepared); env.calls[1].resolve(receipt(env.calls[1])); await env.flush(); assert.equal(env.saved(), 1);
});
test("unmount and refresh recover unknown exact command without automatic submission", async t => {
  const env = environment(t), call = await edited(env), original = structuredClone(call.body);
  call.reject(new Error("transport unknown")); await env.flush(); env.remount(); await env.flush();
  assert.equal(env.calls.length, 1); assert.match(env.html(), /原操作结果仍待核对/);
  await click(env, "按原请求核对结果"); assert.deepEqual(env.calls[1].body, original);
  env.calls[1].resolve(receipt(env.calls[1])); await env.flush(); env.remount(); await env.flush();
  assert.equal(env.calls.length, 2); assert.match(env.html(), /已取得保存回执/); assert.equal(button(env, "按原请求核对结果"), undefined);
});
test("precise version refusal survives remount and requires explicit reread before a new request", async t => {
  const env = environment(t), call = await edited(env);
  call.reject(failure(409, "VERSION_CONFLICT", "definition_item_moved")); await env.flush(); env.remount(); await env.flush();
  assert.equal(env.calls.length, 1); await click(env, "重新读取后准备新操作"); assert.equal(env.calls[1].body, undefined);
  const current = definition(); current.item_versions[0].item_version = 8; current.item_versions[0].row_id = id(30);
  env.calls[1].resolve({ items: [current] }); env.calls[2].resolve({ product: { id: product, category_id: category, revision: 12 } }); await env.flush(); assert.equal(env.calls.length, 3);
  await click(env, "修订压力"); await submitForm(env); const next = env.calls[3].body;
  assert.equal(next.expected_revision, 12);
  assert.equal(next.payload.ops[0].base_version, 8); assert.notEqual(next.idempotency_key, call.body.idempotency_key);
});
test("fixed-consumption refusal keeps parent and guides an explicit continuation", async t => {
  const env = environment(t), call = await edited(env);
  call.reject(failure(409, "VERSION_CONFLICT", "definition_consumed")); await env.flush(); assert.match(env.html(), /已被固定引用/);
  await click(env, "重新读取后准备新操作"); env.calls[1].resolve({ items: [definition()] }); env.calls[2].resolve({ product: { id: product, category_id: category, revision: 9 } }); await env.flush();
  await input(env, "续版原因", "保留被引用原版继续"); await click(env, "保留完整内容，创建新草稿");
  assert.equal(env.calls[3].body.operation, "product.definition.draft");
});
test("401/403 clear private presentation and retain the exact request across refresh", async t => {
  for (const status of [401, 403]) await t.test(String(status), async t => {
    const env = environment(t), call = await edited(env); call.reject(failure(status, "FORBIDDEN_SCOPE", "revoked")); await env.flush();
    assert.equal(env.denied(), 1); assert.doesNotMatch(env.html(), /私有具名原文|压力|标准工况/); env.remount(); await env.flush();
    assert.doesNotMatch(env.html(), /私有具名原文|压力|标准工况/); await click(env, "按原请求核对结果"); assert.deepEqual(env.calls[1].body, call.body);
  });
});
test("unknown 409 and 5xx never release the original request", async t => {
  for (const status of [409, 503]) await t.test(String(status), async t => {
    const env = environment(t), call = await edited(env); call.reject(failure(status, "VERSION_CONFLICT", "unrecognized")); await env.flush();
    assert.equal(button(env, "重新读取后准备新操作"), undefined); assert.ok(button(env, "按原请求核对结果"));
  });
});
test("receipt success notifies owner immediately and survives failed refresh", async t => {
  let notify = 0, rejectRefresh;
  const env = environment(t, { onSaved: () => { notify++; return new Promise((_, reject) => { rejectRefresh = reject; }); } });
  const call = await edited(env); call.resolve(receipt(call)); await env.flush();
  assert.equal(notify, 1); assert.match(env.html(), /已取得保存回执/); assert.equal(env.calls.length, 1);
  rejectRefresh(new Error("synthetic refresh failure")); await env.flush(); assert.match(env.html(), /保存已成功；最新内容读取失败/);
  env.remount(); await env.flush(); assert.equal(env.calls.length, 1); assert.match(env.html(), /已取得保存回执/);
});
test("a new unknown request clears the previous success and preserves exact manual recovery", async t => {
  const env = environment(t), first = await edited(env);
  first.resolve(receipt(first)); await env.flush();
  assert.equal(env.saved(), 1); assert.match(env.html(), /保存已成功，原版本与来源保留/);
  const current = definition(); current.item_versions[0].item_version = 8; current.item_versions[0].row_id = id(30);
  current.specs[0].reason = "人工修订依据";
  const refreshed = { ...env.props, definition: current, product: { id: product, revision: 10 } };
  env.setProps(refreshed); await env.flush(); await click(env, "修订压力");
  await input(env, "依据或未知说明", "第二次人工修订依据"); await submitForm(env);
  const second = env.calls[1], original = structuredClone(second.body);
  assert.notEqual(original.idempotency_key, first.body.idempotency_key);
  assert.equal(original.payload.ops[0].base_version, 8); assert.equal(original.expected_revision, 10);
  assert.doesNotMatch(env.html(), /保存已成功|已取得保存回执/);
  second.reject(new Error("transport unknown")); await env.flush();
  assert.match(env.html(), /原操作结果仍待核对/); assert.doesNotMatch(env.html(), /保存已成功|已取得保存回执/);
  const journal = JSON.parse([...env.storage.values()][0]);
  assert.equal(journal.state, "unknown"); assert.deepEqual(journal.command, original);
  env.remount(refreshed); await env.flush(); assert.equal(env.calls.length, 2);
  await click(env, "按原请求核对结果"); assert.deepEqual(env.calls[2].body, original);
  env.calls[2].resolve(receipt(env.calls[2], { id: id(103) })); await env.flush();
  assert.equal(env.saved(), 2); assert.match(env.html(), /保存已成功，原版本与来源保留/);
  assert.doesNotMatch(env.html(), /原操作结果仍待核对/);
});
test("scope switch ignores old UI response but stores the original scope's receipt", async t => {
  const env = environment(t), call = await edited(env);
  const next = { ...env.props, definition: definition({ id: id(70), title: "第二固定定义" }) };
  env.setProps(next); await env.flush(); call.resolve(receipt(call)); await env.flush();
  assert.doesNotMatch(env.html(), /已取得保存回执/); assert.equal(env.saved(), 0);
  env.remount(); await env.flush(); assert.match(env.html(), /已取得保存回执/);
});
test("storage failure prevents a new write and mismatched receipts preserve recovery", async t => {
  const env = environment(t); await env.flush(); env.sessionStorage.setItem = () => { throw new Error("storage denied"); };
  await click(env, "修订压力"); await submitForm(env); assert.equal(env.calls.length, 0);
  env.sessionStorage.setItem = (key, value) => env.storage.set(key, value);
  await submitForm(env); env.calls[0].resolve(receipt(env.calls[0], { product_id: id(999) })); await env.flush();
  assert.equal(env.saved(), 0); assert.ok(button(env, "按原请求核对结果"));
});
test("projection never fills unknown with zero and reference extras never become policy", () => {
  const value = editorTools.projectItem({ key: "x", parameter: "合成", availability: "unknown", origin: "ai_draft", tenant_id: id(99) });
  assert.equal(value.value, null); assert.equal(value.text_value, null); assert.equal(Object.hasOwn(value, "tenant_id"), false);
  assert.equal(editorTools.itemSummary(value), "未知");
  const reference = editorTools.projectReference({ type: "human", id: human, version: 1, statement: "本人原话", policy: "allow" });
  assert.equal(Object.hasOwn(reference, "policy"), false);
});

test("specific format and item validation refusals allow explicit reread, while preserving the original until then", async t => {
  for (const [status, code, reason] of [[422, "VALIDATION_FAILED", "INVALID_PAYLOAD"], [409, "VALIDATION_FAILED", "parameter_unit_mismatch"], [409, "VERSION_CONFLICT", "definition_item_removed"]]) await t.test(reason, async t => {
    const env = environment(t), call = await edited(env); call.reject(failure(status, code, reason)); await env.flush();
    env.remount(); await env.flush(); assert.ok(button(env, "重新读取后准备新操作"));
    assert.equal(env.calls.length, 1); assert.deepEqual(JSON.parse([...env.storage.values()][0]).command, call.body);
    await click(env, "重新读取后准备新操作"); env.calls[1].resolve({ items: [definition()] });
    env.calls[2].reject(new Error("reread failed")); await env.flush();
    assert.ok(button(env, "重新读取后准备新操作")); assert.equal(JSON.parse([...env.storage.values()][0]).state, "rejected");
  });
});
test("late removal preview never enters another fixed definition scope", async t => {
  const env = environment(t); await env.flush(); await click(env, "移除压力"); const old = env.calls[0];
  env.setProps({ ...env.props, definition: definition({ id: id(71) }) }); await env.flush();
  old.resolve({ command: { ...old.body, payload: { ...old.body.payload, confirmation_token: "old-token" } }, review: { definition_id: definitionId, effect: "移除旧条目" } });
  await env.flush(); assert.equal(button(env, "确认移除此条"), undefined); assert.equal(env.calls.length, 1);
});

test("actual numeric editor saves a single bound without changing dictionary identity or copied conditions", async t => {
  const env = environment(t); await env.flush(); await click(env, "修订压力");
  await input(env, "value", ""); await input(env, "upper", "75");
  await submitForm(env); assert.equal(env.calls.length, 1);
  const actual = env.calls[0].body.payload.ops[0].content;
  assert.equal(actual.value_type, "number"); assert.equal(actual.parameter_id, id(10));
  assert.equal(actual.parameter_version, 2); assert.equal(actual.value, null);
  assert.equal(actual.lower, null); assert.equal(actual.upper, "75");
  assert.deepEqual(actual.exceptions, [{ text: "室内", numeric: 0 }]);
  assert.deepEqual(actual.test_conditions, ["固定台架"]);
  assert.equal(actual.acceptance_criterion, "精确零目标");
  assert.equal(env.calls[0].body.payload.ops[0].base_version, 7);
});
