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
const { ResearchResult } = load(path.join(directory, "research-result.tsx"));
const source = { id: "source", title: "Actual specs", final_url: "https://maker.example/specs", retrieved_at: "2026-10-16T00:00:00Z", status: "ok" };
const row = { row_id: "row", snapshot_id: "source", quote: "Pressure: 20 psi", locator: "chars:0:32", status: "partial", model: "P1", value: "20", unit: "psi" };
const job = { status: "partial", snapshots: [source], ledger: [row], coverage: [{ task_key: "maker", searches: [{}], reads: [{}], unread_urls: ["https://other.example/"], unread_locations: [{}], accepted_rows: 1, rejected_rows: 0 }], failures: [{ reason: "read_timeout", message: "Second source timed out" }] };
const value = { version: 1, jobs: [job], source_count: 1, row_count: 1 };
const render = value => renderToStaticMarkup(React.createElement(ResearchResult, { value }));
test("actual partial evidence shows source, exact quote, uncovered work and original failure", () => {
 const html = render(value);
 for (const text of ["Actual specs", "Pressure: 20 psi", "chars:0:32", "1 份实际来源", "尚未读取 1 个网址、1 段原文", "Second source timed out"]) assert.ok(html.includes(text), text);
 assert.ok(html.includes('href="https://maker.example/specs"'));
});
test("missing evidence is absent; inconsistent counts and malformed records are visible failures", () => {
 assert.equal(render(undefined), "");
 assert.match(render({ ...value, source_count: 999 }), /数量尚未核对/);
 assert.match(render({ ...value, jobs: [{ ...job, snapshots: [null] }] }), /格式暂不可核对/);
});
test("unavailable work remains visible without fabricated sources", () => {
 const html = render({ version: 1, source_count: 0, row_count: 0, jobs: [{ status: "unavailable", snapshots: [], ledger: [], coverage: [], failures: [{ reason: "SOURCE_UNAVAILABLE", message: "Search unavailable" }] }] });
 assert.match(html, /尚未读到可引用来源/); assert.match(html, /Search unavailable/);
});
test("source URL cannot become an executable link and quotes stay escaped", () => {
 const html = render({ ...value, jobs: [{ ...job, snapshots: [{ ...source, final_url: "javascript:alert(1)" }], ledger: [{ ...row, quote: "<script>untrusted</script>" }] }] });
 assert.ok(!html.includes('href="javascript:')); assert.ok(!html.includes("<script>")); assert.match(html, /&lt;script&gt;/);
});
