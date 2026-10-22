import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const ts = createRequire(import.meta.url)("typescript");
const loaded = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./run-start-intent.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: loaded, exports: loaded.exports });
const { restoreRunStart } = loaded.exports;
const proposal = "11111111-1111-4111-8111-111111111111";
const original = { path: "v1/agent-runs", body: { goal: "核对提案未知项", idempotency_key: "original-intent-key", product_id: null, proposal_id: proposal, sources: [] } };
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
