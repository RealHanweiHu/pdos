import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const here = path.dirname(fileURLToPath(import.meta.url));
const web = path.resolve(here, "../../../..");
const require = createRequire(path.join(web, "package.json"));
const ts = require("typescript");
const source = readFileSync(path.join(here, "memory-review.ts"), "utf8");
const output = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText;
const loaded = { exports: {} };
new Function("module", "exports", "require", output)(loaded, loaded.exports, name => {
  if (name === "react") return { useCallback: f => f, useEffect: () => {}, useState: v => [v, () => {}] };
  throw new Error(`unexpected module ${name}`);
});
const { parseReviewPage, routeChoices } = loaded.exports;

const item = (overrides = {}) => ({
  item_id: "11111111-2222-4333-8444-555555555555", source: "correction", kind: "fact", label: "事实错误",
  status: "open", choices: ["resolved", "dismissed"], text: null, proposed_kind: null,
  recorded_at: "2026-11-15T00:00:00+00:00", parent_id: null, run_id: null, reasons: ["wrong_value"],
  scope: { kind: "category", id: "c", category_id: "c" },
  object: { kind: "category", id: "c", title: "汽车充气泵", recorded_version: 1, current_version: 1 },
  ...overrides,
});

test("review page parses only the fixed shape", () => {
  assert.equal(parseReviewPage({ version: "memory-review-items/v1", items: [item()], raised: [], note: "n" }).count, 1);
  assert.equal(parseReviewPage({ version: "other", items: [], raised: [] }), null);
  assert.equal(parseReviewPage({ version: "memory-review-items/v1", items: [{ ...item(), kind: "rewrite" }], raised: [] }), null);
});

test("further routes are offered only on my own first-level corrections", () => {
  assert.deepEqual(routeChoices(item()), ["personal", "team", "forward"]);
  assert.deepEqual(routeChoices(item({ kind: "skill", object: undefined })), ["personal", "team"]);
  assert.deepEqual(routeChoices(item({ scope: { kind: "global", id: null, category_id: null }, object: undefined })), ["personal"]);
  assert.deepEqual(routeChoices(item({ status: "forwarded" })), ["personal", "team"]);
  assert.deepEqual(routeChoices(item({ parent_id: "x" })), []);
  assert.deepEqual(routeChoices(item({ source: "staleness", kind: "object_updated" })), []);
});
