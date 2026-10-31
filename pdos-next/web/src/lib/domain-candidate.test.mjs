import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import test from "node:test";
import { runInNewContext } from "node:vm";

const require = createRequire(import.meta.url), ts = require("typescript");
const compiledModule = { exports: {} };
const verification = { exports: {} };
runInNewContext(ts.transpileModule(readFileSync(new URL("./verification-action.ts", import.meta.url), "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 } }).outputText, { module: verification, exports: verification.exports });
runInNewContext(ts.transpileModule(readFileSync(new URL("./domain-candidate.ts", import.meta.url), "utf8"), {
  compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022 },
}).outputText, { module: compiledModule, exports: compiledModule.exports, require: name => { assert.equal(name, "./verification-action"); return verification.exports; } });
const { boundCandidateCommand, sameCandidateCommand, matchesPendingCandidate } = compiledModule.exports;
const category = "11111111-1111-4111-8111-111111111111";
const run = "22222222-2222-4222-8222-222222222222";
const command = () => ({
  operation: "platform.link.create", category_id: category, product_id: category,
  command_id: run, idempotency_key: "actual-server-model-intent", expected_revision: 1,
  source_read_set: [], payload: { prepared_by_run_id: run, candidate_digest: "a".repeat(64),
    compatibility: null, platform_version: null, confirmation_token: null },
});

test("native preparation kind binds the ordinary command without pretending to be a CONTENT candidate", () => {
  const event = "33333333-3333-4333-8333-333333333333";
  const value = { ...command(), operation: "verification.preparation.record", payload: { request_id: run, build_id: category, expected_build_revision: 1, expected_request_revision: 0, title: "复验准备", purpose: "改善复验", items: [{ sample_count: 6 }], sources: [] } };
  assert.equal(boundCandidateCommand(value, category, run, event), false);
  assert.equal(boundCandidateCommand(value, category, run, event, "verification_preparation"), true);
  for (const patch of [{ prepared_by_run_id: run }, { candidate_digest: "a".repeat(64) }, { prepared_event_id: event }]) assert.equal(boundCandidateCommand({ ...value, payload: { ...value.payload, ...patch } }, category, run, event, "verification_preparation"), false);
  assert.equal(sameCandidateCommand(value, { ...value, payload: { ...value.payload, confirmation_token: "native-preview-token" } }), true);
});

test("only an actual scoped domain candidate can be restored for confirmation", () => {
  assert.equal(boundCandidateCommand(command(), category, run), true);
  for (const changes of [
    { category_id: run }, { operation: "proposal.g0.decide" }, { operation: "project.create" },
    { operation: "unknown" }, { command_id: "not-uuid" }, { expected_revision: 0 },
    { expected_revision: true }, { source_read_set: null }, { payload: { prepared_by_run_id: category, candidate_digest: "a".repeat(64) } },
    { payload: { prepared_by_run_id: run, candidate_digest: "forged" } },
  ]) assert.equal(boundCandidateCommand({ ...command(), ...changes }, category, run), false);
});

test("preview comparison tolerates JSON key order and the one server confirmation token", () => {
  const original = command(), preview = structuredClone(original);
  preview.payload = Object.fromEntries(Object.entries(preview.payload).reverse());
  preview.payload.confirmation_token = "actual-named-preview-token";
  assert.equal(sameCandidateCommand(original, preview), true);
  assert.equal(original.payload.confirmation_token, null);
});

test("changed scope, material, version or original request is not the same preview", () => {
  for (const changes of [
    { command_id: category }, { idempotency_key: "different-intent" }, { product_id: run },
    { expected_revision: 2 }, { payload: { ...command().payload, compatibility: "changed" } },
    { payload: { ...command().payload, candidate_digest: "b".repeat(64) } },
  ]) assert.equal(sameCandidateCommand(command(), { ...command(), ...changes }), false);
});

test("nested business fields called confirmation_token are still compared", () => {
  const original = command(), preview = structuredClone(original);
  original.payload.content = { confirmation_token: "business-source-text" };
  preview.payload.content = { confirmation_token: "changed-source-text" };
  assert.equal(sameCandidateCommand(original, preview), false);
});

test("snapshot confirmation needs the server event and exact currently listed command", () => {
  const event = "33333333-3333-4333-8333-333333333333";
  const original = { ...command(), operation: "research.snapshot.register", product_id: null,
    payload: { prepared_event_id: event, snapshot_id: category } };
  assert.equal(boundCandidateCommand(original, category, run), false);
  assert.equal(boundCandidateCommand(original, category, run, event), true);
  assert.equal(boundCandidateCommand(original, category, run, category), false);
  const current = { event_id: event, state: "pending", command: original,
    command_id: original.command_id, idempotency_key: original.idempotency_key };
  const confirmed = structuredClone(original); confirmed.payload.confirmation_token = "actual-preview";
  assert.equal(matchesPendingCandidate(current, confirmed, event, category, run), true);
  assert.equal(matchesPendingCandidate(undefined, confirmed, event, category, run), false);
  assert.equal(matchesPendingCandidate({ ...current, state: "unavailable" }, confirmed, event, category, run), false);
  assert.equal(matchesPendingCandidate({ ...current, command: { ...original, payload: { ...original.payload, snapshot_id: run } } }, confirmed, event, category, run), false);
});
