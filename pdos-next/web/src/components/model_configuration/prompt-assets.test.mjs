import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const root = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(root, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
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
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022,
    jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return mod.exports;
}
const { PromptAssetView } = load(path.join(directory, "agent-skills.tsx"));

test("prompt code, provenance and editing boundary are visible without an online overwrite", () => {
  const prompt = {
    key: "xiaopai.main", version: "1.0.0",
    content_digest: "a".repeat(64), system_digest: "b".repeat(64),
    content: "Synthetic prompt <unsafe> & visible",
    source: "pdos-next/server/pdos_next/prompt_packages/versions/1.0.0.md",
  };
  const html = renderToStaticMarkup(React.createElement(PromptAssetView, { prompt }));
  assert.ok(html.includes("当前主提示词"));
  assert.ok(html.includes("代码版本 1.0.0"));
  assert.ok(html.includes("aaaaaaaaaaaa"));
  assert.ok(html.includes("bbbbbbbbbbbb"));
  assert.ok(html.includes(prompt.source));
  assert.ok(html.includes("Synthetic prompt &lt;unsafe&gt; &amp; visible"));
  assert.ok(html.includes("新建草稿、查看差异并完成同题评估"));
  assert.ok(html.includes('tabindex="0"'));
  assert.ok(html.includes('aria-label="主提示词正文，可滚动"'));
  assert.equal(html.includes("<unsafe>"), false);
  assert.equal(html.includes("保存提示词"), false);
  assert.equal(html.includes("<textarea"), false);
});
