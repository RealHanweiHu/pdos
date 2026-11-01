import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";
const require = createRequire(import.meta.url), ts = require("typescript");
const compiled = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./object-search.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { module: compiled, exports: compiled.exports, URLSearchParams });
const { searchHref } = compiled.exports;
const category = "11111111-1111-4111-8111-111111111111", id = "22222222-2222-4222-8222-222222222222";
test("actual result scopes map to the existing object pages", () => {
  const base = { id, category_id: category, product_id: id };
  assert.equal(searchHref({ ...base, kind: "proposal" }), `/categories/${category}/proposals/${id}`);
  assert.equal(new URLSearchParams(searchHref({ ...base, kind: "project" })).get("project"), id);
  const product = new URLSearchParams(searchHref({ ...base, kind: "product" }));
  assert.equal(product.get("category"), category); assert.equal(product.get("product"), id);
  assert.equal(product.get("bench"), "products"); assert.equal(product.get("view"), "overview");
  assert.equal(new URLSearchParams(searchHref({ ...base, kind: "category", id: category })).get("category"), category);
});
test("unknown or inconsistent result identities never become executable links", () => {
  const base = { kind: "product", id, category_id: category, product_id: id };
  for (const patch of [{ id: "javascript:bad" }, { category_id: "../other" }, { product_id: category }, { kind: "claim" }, { kind: "category" }]) assert.equal(searchHref({ ...base, ...patch }), null);
});
