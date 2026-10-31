import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Installed compiler only; no Next build, service, shared cache or external data.
const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(root, "package.json"));
const ts = dependency("typescript");
const React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const cache = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (!filename) throw new Error("Owned test module not found");
  if (cache.has(filename)) return cache.get(filename).exports;
  const mod = new Module(filename);
  cache.set(filename, mod);
  const requireLocal = createRequire(filename);
  mod.require = specifier => specifier.startsWith("@/") ? load(path.join(root, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : requireLocal(specifier);
  mod._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return mod.exports;
}
const { ModelConfigurationSettings } = load(path.join(directory, "settings.tsx"));
const { ConnectionEditor } = load(path.join(directory, "connection-editor.tsx"));
const { readinessText, validateRequest } = load(path.join(directory, "contracts.ts"));
const metadata = { protocol: "openai-compatible", base_url: "https://synthetic.invalid/v1", model: "synthetic-model", model_version: "v1", max_output_tokens: 2048, openai_output_parameter: "max_completion_tokens", timeout_seconds: 30, response_bytes: 1048576 };
const reading = { revision: 2, version_id: "synthetic-version", provider_version: "synthetic-binding", metadata, enabled: true, credential_status: "bound", credential_display: "已绑定 ••••", created_at: "2026-10-02T00:00:00Z", requires_requalification: true };
function render(props) { return renderToStaticMarkup(React.createElement(ModelConfigurationSettings, props)); }

test("missing command port disables settings and does not fabricate saved configuration", () => {
  const html = render({ reading: null, canEdit: true, readiness: null });
  assert.ok(html.includes("尚未保存模型配置"));
  assert.ok(html.includes("办理接口待接入"));
  assert.match(html, /<button[^>]*disabled=""/);
  assert.ok(html.includes("当前调用检查接口待接入"));
  assert.equal(html.includes("保存成功"), false);
});

test("non administrators cannot edit even when callbacks are supplied", () => {
  let invoked = false;
  const html = render({ reading, canEdit: false, readiness: null, onPreview: async () => { invoked = true; } });
  assert.match(html, /<fieldset disabled=""/);
  assert.match(html, /<button[^>]*disabled=""/);
  assert.ok(html.includes("仅当前授权管理员"));
  assert.equal(invoked, false);
});

test("masked configured state and authorizer readiness do not claim active model calls", () => {
  const html = render({ reading, canEdit: true, readiness: { state: "authorizer_check", code: "MODEL_AUTHORIZER_CHECK_REQUIRED" }, onPreview: async () => { throw new Error("Render must not invoke"); } });
  assert.ok(html.includes("已绑定 ••••"));
  assert.ok(html.includes("仍须取得本次材料和调用授权"));
  assert.ok(html.includes("核对并预览"));
  assert.equal(html.includes('type="password"'), false);
  assert.equal(html.includes("synthetic-binding"), false);
  assert.equal(html.includes("确认保存"), false);
  assert.equal(html.includes("secret_reference"), false);
});

test("pending parent command locks edits and keeps only one preview entry", () => {
  const html = render({ reading, canEdit: true, readiness: null, pending: true, onPreview: async () => {} });
  assert.match(html, /<fieldset disabled=""/);
  assert.match(html, /<button[^>]*disabled=""/);
  assert.equal((html.match(/<button/g) ?? []).length, 1);
});

test("unknown or mismatched readiness stays unavailable and cannot echo secret errors", () => {
  assert.equal(readinessText({ state: "unavailable", code: "MODEL_AUTHORIZER_CHECK_REQUIRED" }), "当前调用条件或接口尚不齐全");
  assert.equal(readinessText({ state: "unavailable", code: "private-secret-error" }), "当前调用条件或接口尚不齐全");
  for (const [code, text] of [["MODEL_QUALIFICATION_REQUIRED", "真实资格"], ["MODEL_EGRESS_REQUIRED", "出站授权"], ["MODEL_BUDGET_REQUIRED", "预算"], ["MODEL_CANCELLED", "已取消"], ["MODEL_SECRET_CHANGED", "重新绑定"]]) assert.ok(readinessText({ state: "unavailable", code }).includes(text));
});

test("invalid numeric input is rejected before requesting a preview", () => {
  const request = { expected_revision: 2, metadata, enabled: false };
  assert.equal(validateRequest(request), null);
  for (const [field, value] of [["max_output_tokens", 0], ["max_output_tokens", 1.5], ["timeout_seconds", NaN], ["response_bytes", 10], ["model_version", ""]]) assert.ok(validateRequest({ ...request, metadata: { ...metadata, [field]: value } }));
  assert.ok(validateRequest({ ...request, expected_revision: -1 }));
});

test("input labels have unique accessible ids with both explicit protocol choices", () => {
  const html = render({ reading, canEdit: true, readiness: null, onPreview: async () => {} });
  const ids = [...html.matchAll(/id="([^"]+)"/g)].map(match => match[1]);
  assert.equal(ids.length, 12);
  assert.equal(new Set(ids).size, ids.length);
  for (const id of ids) assert.ok(html.includes(`for="${id}"`));
  assert.ok(html.includes("OpenAI 兼容")); assert.ok(html.includes("Anthropic 原生"));
  assert.ok(html.includes("Chat Completions API"));
  assert.ok(html.includes('value="tools"')); assert.ok(html.includes('value="text"'));
  assert.ok(html.includes("接口支持流式响应"));
});

test("provider creation exposes direct password entry with no stored key echo", () => {
  const html = renderToStaticMarkup(React.createElement(ConnectionEditor, {
    api: async () => { throw new Error("Render cannot save"); }, onSaved() {}, onCancel() {},
  }));
  for (const label of ["Base URL", "API Key", "模型名称", "保存服务商"]) assert.ok(html.includes(label));
  assert.match(html, /type="password"[^>]*autoComplete="new-password"/);
  assert.ok(html.includes("保存到服务器安全存储"));
  assert.equal(html.includes("synthetic-fixture-only"), false);
});


test("optional context window renders and validates configured and empty values", () => {
  const props = { reading, canEdit: true, readiness: null, onPreview: async () => {} };
  assert.ok(render(props).includes("未填写（按 32,000 估算）"));
  assert.ok(render(props).includes("上下文窗口（tokens）"));
  const configured = { ...reading, metadata: { ...metadata, context_window_tokens: 200000 } };
  assert.match(render({ ...props, reading: configured }), /上下文窗口：200000/);
  for (const value of [512, 10000001, 1024.5, NaN]) assert.ok(validateRequest({ expected_revision: 0, metadata: { ...metadata, context_window_tokens: value }, enabled: false }));
  for (const value of [null, undefined, 200000]) assert.equal(validateRequest({ expected_revision: 0, metadata: { ...metadata, context_window_tokens: value }, enabled: false }), null);
  const editor = renderToStaticMarkup(React.createElement(ConnectionEditor, { api: async () => {}, onSaved() {}, onCancel() {} }));
  assert.ok(editor.includes("上下文窗口（tokens）"));
});
