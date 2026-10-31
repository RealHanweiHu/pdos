import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const ts = createRequire(import.meta.url)("typescript");
const loaded = { exports: {} };
const preferences = { exports: {} };
const verification = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./verification-action.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: verification, exports: verification.exports });
runInNewContext(ts.transpileModule(readFileSync(new URL("./search-preferences.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: preferences, exports: preferences.exports });
runInNewContext(ts.transpileModule(readFileSync(new URL("./run-start-intent.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: loaded, exports: loaded.exports, require: name => { if (name === "./verification-action") return verification.exports; assert.equal(name, "./search-preferences"); return preferences.exports; } });
const { restoreRunStart } = loaded.exports;
const proposal = "11111111-1111-4111-8111-111111111111";
const original = { path: "v1/agent-runs", body: { goal: "核对提案未知项", idempotency_key: "original-intent-key", product_id: null, proposal_id: proposal, sources: [] } };

test("verification continuation recovery retains only the exact project selection and original read versions", () => {
  const project = "22222222-2222-4222-8222-222222222222", build = "33333333-3333-4333-8333-333333333333";
  const request = { path: "v1/agent-runs", body: { goal: "准备复验请求", idempotency_key: "original-verification-key", continue_from_run_id: build, sources: [], verification_action: { selection: { id: build, revision: 1, product_id: proposal, project_id: project, engineering_configuration: { id: proposal, revision: 2 }, manufacturing_configuration: { id: build, revision: 3 } }, citation_ids: [proposal] } } };
  assert.equal(restoreRunStart(request, undefined, project), request);
  assert.equal(restoreRunStart(request, undefined, build), null);
  assert.equal(restoreRunStart(request), null);
  for (const patch of [{ product_id: proposal }, { project_id: project }, { session_id: build }, { source_run_id: build }, { requested_skills: [] }, { continue_from_run_id: "unfixed" }]) assert.equal(restoreRunStart({ ...request, body: { ...request.body, ...patch } }, undefined, project), null);
});
test("recovery retains the original human lookup choice and rejects untyped authority fields", () => {
  const value = { ...original, body: { ...original.body, search_preferences: { scope: "current", include_customer_private: false } } };
  assert.equal(restoreRunStart(value, proposal), value);
  for (const search_preferences of [{ scope: "all_tenants", include_customer_private: true }, { scope: "same_category", include_customer_private: "true" }, { scope: "current", include_customer_private: false, approved: true }]) {
    assert.equal(restoreRunStart({ ...value, body: { ...value.body, search_preferences } }, proposal), null);
  }
});
test("short greetings can recover while blank goals stay invalid", () => {
  for (const goal of ["你好", "好", "  你好\n"]) {
    const request = { ...original, body: { ...original.body, goal } };
    assert.equal(restoreRunStart(request, proposal), request);
  }
  for (const goal of ["", " \n\t"]) {
    assert.equal(restoreRunStart({ ...original, body: { ...original.body, goal } }, proposal), null);
  }
});
test("restoring a start preserves the exact goal, intent and proposal without executing", () => {
  assert.equal(restoreRunStart(original, proposal), original);
  assert.equal(restoreRunStart(original), null);
  const category = structuredClone(original); delete category.body.proposal_id;
  assert.equal(restoreRunStart(category), category);
});
test("local recovery cannot substitute another operation, proposal or policy context", () => {
  for (const value of [
    { ...original, path: "v1/commands" },
    { ...original, body: { ...original.body, proposal_id: "other" } },
    { ...original, body: { ...original.body, private_context: false } },
    { ...original, body: { ...original.body, idempotency_key: "" } },
    { ...original, body: { ...original.body, product_id: proposal } },
    { ...original, body: { ...original.body, sources: [{ artifact_id: proposal, expected_revision: 0 }] } },
  ]) assert.equal(restoreRunStart(value, proposal), null);
});

test("project start recovery retains its original project and product and rejects another page", () => {
  const project = "22222222-2222-4222-8222-222222222222";
  const request = { path: "v1/agent-runs", body: { goal: "核对项目当前资料", idempotency_key: "original-project-key", product_id: proposal, project_id: project, sources: [] } };
  assert.equal(restoreRunStart(request, undefined, project), request);
  assert.equal(restoreRunStart(request), null);
  assert.equal(restoreRunStart(request, undefined, proposal), null);
  assert.equal(restoreRunStart({ ...request, body: { ...request.body, product_id: null } }, undefined, project), null);
});

test("unknown skill selection restores its exact version without accepting extra authority", () => {
  const request = structuredClone(original);
  request.body.requested_skills = [{ key: "gap_check", version: "0.1.0", digest: "a".repeat(64) }];
  assert.equal(restoreRunStart(request, proposal), request);
  for (const change of [
    items => { items[0].qualified = true; }, items => { items[0].digest = "bad"; },
    items => { items.push({ ...items[0] }); }, items => { items[0].key = ""; },
  ]) {
    const bad = structuredClone(request); change(bad.body.requested_skills);
    assert.equal(restoreRunStart(bad, proposal), null);
  }
});
