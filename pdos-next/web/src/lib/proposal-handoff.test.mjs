import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";
const ts = createRequire(import.meta.url)("typescript"), loaded = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./proposal-handoff.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: loaded, exports: loaded.exports, URLSearchParams });
const { isG0Handoff, g0ProjectHref } = loaded.exports;
const expected = { id: "decision", outcome: "approved", rationale: "named decision", receipt_id: "receipt", decided_by: "reviewer", decided_at: "2026-10-16T10:00:00Z", product_id: "product", variant_id: null, definition_id: "definition", project_id: "project" };
const person = { id: "owner", name: "Synthetic owner" };
function packet() { return {
  category_id: "category", proposal_id: "proposal",
  decision: { id: "decision", outcome: "approved", receipt_id: "receipt", signer: { id: "reviewer", name: "Synthetic reviewer" }, decided_at: expected.decided_at, rationale: "named decision" },
  identity: { kind: "new_product", product: { id: "product", name: "Synthetic product" }, variant: null },
  definition: { id: "definition", product_id: "product", variant_id: null, title: "Fixed G0 definition", revision: 1, sealed: true, status: "draft" },
  project: { id: "project", name: "Synthetic project", product_id: "product", owner: person, definition_id: "definition", definition_revision: 1 },
  open_items: [{ id: "task", project_id: "project", g0_decision_id: "decision", kind: "task", title: "Resolve unknown", owner: person, due_date: "2026-10-25", status: "open" }],
}; }
test("handoff binds actual named decision, project, fixed v1 and carried tasks", () => {
  assert.equal(isG0Handoff(packet(), "category", "proposal", expected), true);
  assert.equal(g0ProjectHref("category", "project"), "/?area=cockpit&category=category&project=project");
});
test("variant result cannot masquerade as a new product or another variant", () => {
  const value = packet(), variant = { ...expected, variant_id: "variant" };
  value.identity = { ...value.identity, kind: "new_variant", variant: { id: "variant", name: "Customer variant", kind: "customer" } };
  value.definition.variant_id = "variant";
  assert.equal(isG0Handoff(value, "category", "proposal", variant), true);
  assert.equal(isG0Handoff(value, "category", "proposal", expected), false);
  value.identity.variant.id = "other";
  assert.equal(isG0Handoff(value, "category", "proposal", variant), false);
});
test("mismatched scope, receipt, definition or carried item is unavailable", () => {
  for (const alter of [v => v.category_id = "other", v => v.proposal_id = "other", v => v.decision.receipt_id = "other", v => v.decision.signer.id = "other", v => v.definition.revision = 2, v => v.definition.sealed = false, v => v.project.definition_id = "other", v => v.open_items[0].g0_decision_id = "other"]) {
    const value = packet(); alter(value);
    assert.equal(isG0Handoff(value, "category", "proposal", expected), false);
  }
  assert.equal(isG0Handoff(packet(), "category", "proposal", { ...expected, outcome: "returned" }), false);
});
