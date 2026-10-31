import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const cache = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (!filename) throw new Error("Test module not found");
  if (cache.has(filename)) return cache.get(filename).exports;
  const loaded = new Module(filename); cache.set(filename, loaded);
  const local = createRequire(filename);
  loaded.require = name => name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : local(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { VerificationPreparationCard } = load(path.join(directory, "verification-preparation-card.tsx"));
const target = {
  id: "c2428acc-cb4c-4beb-a4ec-65f411a2e0b1", name: "密封复验 D16-03", revision: 2,
  engineering_configuration: { id: "e13e02a7-567d-4396-bfec-f67aef4d46d7", name: "密封组件工程配置", revision: 4 },
  manufacturing_configuration: { id: "7c00d716-f21e-4d76-87be-2a53c20b2d3b", name: "装配工艺配置", revision: 3 },
};
const item = { id: "pressure", feature: "气密性", sample_count: 6, method: { quote: "保压十分钟" }, criterion_text: "无泄漏", criterion_source: { quote: "十分钟内无泄漏" } };
const saved = { receipt_id: "actual-preparation-receipt", preparation_id: "ee91aa7f-8f81-42ab-ad2c-8fab595ceef1", expected_preparation_revision: 7, preparation_sha256: "a".repeat(64) };
const pending = { title: "新密封圈复验", purpose: "核对更换措施后的气密性", target, items: [item], basisCount: 3, state: "pending", onPreview() {} };
const adopted = { ...pending, state: "adopted", preparation: saved, onCreateRequest() {} };
const render = props => renderToStaticMarkup(React.createElement(VerificationPreparationCard, props));
const nodes = tree => !tree || typeof tree !== "object" ? [] : Array.isArray(tree) ? tree.flatMap(nodes) : [tree, ...nodes(tree.props?.children)];
const text = tree => typeof tree === "string" ? tree : typeof tree === "number" ? String(tree) : Array.isArray(tree) ? tree.map(text).join("") : tree && typeof tree === "object" ? text(tree.props?.children) : "";
const action = tree => nodes(tree).find(node => typeof node.props?.onClick === "function");

test("pending card shows actual named versions, preparation details and one preview action", () => {
  const html = render(pending);
  for (const value of ["新密封圈复验", "核对更换措施后的气密性", "密封复验 D16-03 · v2", "密封组件工程配置 · v4", "装配工艺配置 · v3", "气密性", "<dd>6</dd>", "保压十分钟", "无泄漏", "3 条依据", "核对并预览"]) assert.ok(html.includes(value), value);
  assert.equal((html.match(/<button\b/g) ?? []).length, 1);
  assert.doesNotMatch(html, /创建复验请求|已保存|自动|按服务器权限|不可作为授权|已经适用/);
  for (const value of [target.id, target.engineering_configuration.id, target.manufacturing_configuration.id]) assert.ok(!html.includes(value));
});

test("missing or invalid sample counts remain unknown and never become a default one", () => {
  for (const sample_count of [undefined, null, 0, -1, 1.5, NaN]) {
    const html = render({ ...pending, items: [{ id: "unknown", feature: "密封性", sample_count }] });
    assert.match(html, /样本数<\/dt><dd>待确认<\/dd>/);
    assert.doesNotMatch(html, /<dd>1<\/dd>/);
    assert.equal((html.match(/待确认<\/dd>/g) ?? []).length, 3, "sample count, method and criterion are explicit");
  }
});

test("numeric criteria retain zero and units; unsupported free text stays to confirm", () => {
  const html = render({ ...pending, items: [{ ...item, unit: "kPa", criterion: { lower: "0", upper: "5", source: { quote: "压力在0到5kPa之间" } } }], basisCount: 0 });
  assert.match(html, /≥ 0，≤ 5 kPa/); assert.match(html, /0 条依据/);
  const unconfirmed = render({ ...pending, items: [{ ...item, criterion_source: null }] });
  assert.match(unconfirmed, /判据<\/dt><dd[^>]*>待确认<\/dd>/);
  assert.doesNotMatch(unconfirmed, />无泄漏</);
});

test("preview is a single explicit parent callback, preserving the actual focus trigger", () => {
  const called = [], trigger = { kind: "actual-button" };
  const tree = VerificationPreparationCard({ ...pending, onPreview: button => called.push(button) });
  assert.deepEqual(called, []);
  const button = action(tree); assert.equal(text(button), "核对并预览");
  button.props.onClick({ currentTarget: trigger });
  assert.deepEqual(called, [trigger]);
});

test("adopted card displays the real saved revision and returns the exact preparation to its human next step", () => {
  const called = [], trigger = { kind: "create-request-button" };
  const props = { ...adopted, onCreateRequest: (...args) => called.push(args), onPreview() { throw new Error("Adopted card must not preview preparation again"); } };
  const html = render(props);
  assert.match(html, /已保存 v7/); assert.match(html, /创建复验请求/);
  assert.doesNotMatch(html, /核对并预览/);
  assert.equal((html.match(/<button\b/g) ?? []).length, 1);
  for (const value of [saved.receipt_id, saved.preparation_id, saved.preparation_sha256]) assert.ok(!html.includes(value));
  assert.deepEqual(called, [], "rendering or opening saved preparation performs no write or model call");
  const button = action(VerificationPreparationCard(props)); button.props.onClick({ currentTarget: trigger });
  assert.equal(called.length, 1); assert.equal(called[0][0], saved); assert.equal(called[0][1], trigger);
});

test("busy and parent-disabled actions use native disabled buttons and cannot fire callbacks", () => {
  for (const base of [pending, adopted]) for (const flag of ["busy", "disabled"]) {
    const calls = [], props = { ...base, [flag]: true, onPreview: () => calls.push("preview"), onCreateRequest: () => calls.push("create") };
    assert.match(render(props), /<button[^>]*disabled=""/);
    const button = action(VerificationPreparationCard(props)); assert.equal(button.props.disabled, true);
    button.props.onClick({ currentTarget: {} }); assert.deepEqual(calls, []);
    if (flag === "busy") assert.match(render(props), /aria-busy="true"/);
  }
});

test("all business text is safely escaped, with wrapping and existing theme tokens", () => {
  const attack = '<script>alert("x")</script><img src=x onerror=alert(1)>';
  const html = render({ ...pending, title: attack, purpose: attack, target: { ...target, name: attack }, items: [{ ...item, feature: attack, method: { quote: attack }, criterion_text: attack }] });
  assert.match(html, /&lt;script&gt;/); assert.match(html, /&lt;img/); assert.doesNotMatch(html, /<script|<img/);
  for (const value of ["min-w-0", "overflow-wrap:anywhere", "flex-wrap", "bg-card", "text-card-foreground", "border-border", "text-muted-foreground"]) assert.ok(html.includes(value), value);
});

test("empty preparation fields show explicit unknowns without generating content", () => {
  const html = render({ ...pending, title: "", purpose: " ", items: [], basisCount: null });
  for (const value of ["复验准备", "复验目的待确认", "测试项待确认", "依据待确认"]) assert.ok(html.includes(value), value);
  assert.doesNotMatch(html, /<dd>1<\/dd>|已适用|已批准/);
});
