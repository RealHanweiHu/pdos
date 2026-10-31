import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Installed compiler and local fixtures only; no service, KMS, DB or external dependency.
const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react"), { renderToStaticMarkup } = dependency("react-dom/server");
const cache = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (!filename) throw new Error("Owned module not found");
  if (cache.has(filename)) return cache.get(filename).exports;
  const mod = new Module(filename), local = createRequire(filename); cache.set(filename, mod);
  mod.require = name => name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : local(name);
  mod._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return mod.exports;
}
const { embeddingConnectionFrom, embeddingConnectionMetadata, newEmbeddingConnectionRequest } = load(path.join(web, "src/lib/embedding-connections.ts"));
const { EmbeddingConnectionEditor, EmbeddingConnectionPicker } = load(path.join(directory, "embedding-connection-picker.tsx"));
const { EmbeddingProfileEditor } = load(path.join(directory, "embedding-settings.tsx"));
const id = n => `00000000-0000-0000-0000-${n.toString(16).padStart(12, "0")}`;
const connection = { id: id(1), name: "Embedding only", metadata: { protocol: "openai-compatible", base_url: "https://embedding.invalid/v1", model: "embed-model", model_version: "embed@1", connection_id: id(1) }, provider: "embedding.invalid", credential_display: "已保存 ••••", pricing_configured: true };
const form = { name: "Independent embedding", base: "https://embedding.invalid/v1/", model: "embed-model", version: "embed@1", key: "synthetic-only-key-private", priced: false, source: "", inputRate: "", requestFee: "0", byteBound: "", framing: "", verified: false };
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));

test("selector accepts exact explicit managed OpenAI connections and excludes unselectable host defaults", () => {
  const selected = embeddingConnectionFrom(connection); assert.equal(selected.id, connection.id); assert.equal(selected.model, "embed-model");
  for (const value of [{ ...connection, id: null }, { ...connection, id: "bad" }, { ...connection, metadata: { ...connection.metadata, protocol: "anthropic-native" } }, { ...connection, metadata: { ...connection.metadata, connection_id: id(2) } }, { ...connection, metadata: { ...connection.metadata, model: "bad model" } }, { ...connection, metadata: { ...connection.metadata, base_url: "http://remote.invalid/v1" } }]) assert.equal(embeddingConnectionFrom(value), null);
});
test("selection copies only public route fields into profile, leaving credentials and chat settings out", () => {
  const selected = embeddingConnectionFrom({ ...connection, secret_reference: "private-marker", api_key: form.key });
  const metadata = embeddingConnectionMetadata(selected);
  assert.deepEqual(metadata, { connection_id: connection.id, base_url: connection.metadata.base_url, model: "embed-model", model_version: "embed@1" });
  assert.equal(JSON.stringify(metadata).includes(form.key), false); assert.equal(JSON.stringify(metadata).includes("private-marker"), false);
  assert.equal("enabled" in metadata, false); assert.equal("dimensions" in metadata, false); assert.equal("api_key" in metadata, false);
});
test("secure registration is a separate request and never implicitly creates or enables a profile/chat command", () => {
  const request = newEmbeddingConnectionRequest(form);
  assert.equal(request.api_key, form.key); assert.equal(request.metadata.base_url, "https://embedding.invalid/v1"); assert.equal(request.metadata.protocol, "openai-compatible"); assert.equal(request.pricing, null);
  for (const field of ["operation", "enabled", "connection_id", "confirmation_token", "category_id", "tenant_id"]) assert.equal(field in request, false);
  assert.equal(request.metadata.connection_id, undefined); assert.match(request.request_id, /^[a-f0-9-]{36}$/);
});
test("embedding pricing requires explicit source/rates/billing confirmation and carries only input/request prices", () => {
  const checked = new Date("2026-10-29T00:00:00Z"), priced = { ...form, priced: true, source: "synthetic pricing", inputRate: "0.25", requestFee: "0.0001", byteBound: "1", framing: "100", verified: true };
  const request = newEmbeddingConnectionRequest(priced, checked);
  assert.equal(request.pricing.input_per_million, "0.25"); assert.equal(request.pricing.request_fee, "0.0001"); assert.equal(request.pricing.output_per_million, "0"); assert.equal(request.pricing.verified_at, checked.toISOString()); assert.equal(request.pricing.valid_until, "2026-11-28T00:00:00.000Z");
  for (const patch of [{ verified: false }, { source: "" }, { inputRate: "-1" }, { inputRate: "Infinity" }, { inputRate: "1e2" }, { byteBound: "0" }, { framing: "1.1" }, { framing: "2147483648" }]) assert.throws(() => newEmbeddingConnectionRequest({ ...priced, ...patch }, checked));
  assert.throws(() => newEmbeddingConnectionRequest(priced, new Date("invalid")));
});
test("invalid key and route errors never echo entered credential material", () => {
  for (const patch of [{ key: "" }, { key: "private\ninvalid" }, { key: "private\u0000invalid" }, { key: "x".repeat(8193) }, { base: "https://key@embedding.invalid" }, { version: "" }]) {
    assert.throws(() => newEmbeddingConnectionRequest({ ...form, ...patch }), failure => { assert.equal(failure.message.includes(form.key), false); if (patch.key) assert.equal(failure.message.includes(patch.key), false); return true; });
  }
});
test("native registration form explains no chat switch and keeps key solely in password input", () => {
  let saves = 0; const html = render(EmbeddingConnectionEditor, { onSave: async () => { saves++; }, onCancel() {} });
  for (const text of ["独立 API Key", "保存连接不会切换当前聊天模型", "换 Key 时新增一份连接", "不进入配置预览、历史、回执或本地恢复记录", "Embedding 价格与计量"]) assert.ok(html.includes(text));
  assert.match(html, /type="password"[^>]*autoComplete="new-password"/); assert.equal(html.includes(form.key), false); assert.equal(html.includes("最大输出 tokens"), false); assert.equal(html.includes("Chat Completions"), false); assert.equal(saves, 0);
  const ids = [...html.matchAll(/id="([^"]+)"/g)].map(match => match[1]); assert.equal(new Set(ids).size, ids.length); for (const id of ids) assert.ok(html.includes(`for="${id}"`));
  assert.equal((html.match(/<form/g) ?? []).length, 1);
});
test("page render does not choose chat credentials or submit registration/profile commands", () => {
  const reads = [], selected = [];
  const props = { api: async (...args) => { reads.push(args); return { connections: [connection] }; }, disabled: false, onChoose: value => selected.push(value), onEditingChange() {} };
  const html = render(EmbeddingConnectionPicker, props);
  assert.ok(html.includes("明确选择一份连接")); assert.ok(html.includes("新增独立连接 / 换 Key")); assert.ok(html.includes("不会自动沿用当前聊天模型的 Key")); assert.equal(selected.length, 0); assert.equal(reads.length, 0);
  assert.match(html, /<button[^>]*disabled=""[^>]*>带入配置表单/);
});
test("profile keeps registration beside its form and original preview boundary", () => {
  const html = render(EmbeddingProfileEditor, { profile: null, budget: null, api: async () => { throw Error("Render must not read"); }, onPreview: async () => { throw Error("Render must not preview"); } });
  assert.ok(html.includes("选择或新增独立 Embedding 连接")); assert.ok(html.includes("核对配置并预览")); assert.equal((html.match(/<form/g) ?? []).length, 1); assert.equal(html.includes('type="password"'), false);
});
