import assert from "node:assert/strict";
import test from "node:test";
import { blankHandoffLocal, handoffDetail, handoffDraftKey, handoffHistoryPage, handoffInputs, handoffOperations, handoffPrepared, handoffReady, handoffSemantic, newHandoffCommand, parseHandoffPayload, restoreHandoffLocal, runHandoffRequest, type HandoffCommand, type HandoffDetail, type HandoffInputs, type HandoffPending, type HandoffScope } from "./external-handoffs";

// Explicit transport substitutes exercise client state, never actual issuer,
// qualification, source registration, PostgreSQL or external delivery evidence.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const ref = (n: number) => ({ id: id(n), revision: 1 });
const scope: HandoffScope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) };
const source = { kind: "artifact", id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const range = { quantity: "10", unit: "ea", site: "合成场地", lots: null, lines: null, regions: null };
const configuration = { definition: ref(6), engineering_configuration: ref(7), manufacturing_configuration: ref(8) };
function payload(receipt = false) { return receipt ? { handoff: ref(20), intent: ref(21), source, reason: "核对同一原回执" } : { project_id: scope.projectId, package: ref(10), engineering_decision: ref(11), manufacturing_decision: ref(12), subject_config: configuration, release_scope: range, purpose: "固定移交用途", destination: { system: "实际系统", recipient_id: "实际收件方" }, external_id: "external-1", mappings: [], manifest: [], sources: [source], reason: "本人核对明确范围" }; }
function command(receipt = false) { return newHandoffCommand(scope, 3, handoffOperations[receipt ? 1 : 0], payload(receipt)); }
function inputs(c: HandoffCommand, ready = true): HandoffInputs {
  const auth = c.operation === handoffOperations[0];
  const original = { schema_version: "pdos-external-receipt-v1", handoff: ref(20), intent: ref(21), destination: { system: "实际系统", recipient_id: "实际收件方" }, external_id: "external-1", manifest_sha256: "b".repeat(64), release_scope: range, stage: "sent", outcome: "unknown", external_receipt_id: "remote-1", occurred_at: "2026-10-17T12:00:00Z", reconciles: null };
  return { operation: c.operation, payload: handoffSemantic(c.operation, c.payload) as typeof c.payload, required_source_read_set: c.source_read_set, authority: auth ? { subject_id: scope.principalId, operation: c.operation, purpose: c.payload.purpose, authorized: true, qualified: true, roles: ["engineering"], scope: { product_id: scope.productId, project_id: scope.projectId } } : {}, diagnostics: [], candidate: { structural_only: true, status: "unexecuted_candidate", operation: c.operation, scope: { tenant_id: id(30), product_id: scope.productId, project_id: scope.projectId }, category_id: scope.categoryId, state: ready ? "READY" : "UNKNOWN", unknown: ready ? [] : [auth ? "HANDOFF_CONTRACT_NOT_READ" : "ACTUAL_RECEIPT_ISSUER_MISSING"], sources: [source], required_source_read_set: c.source_read_set, network_send: false, ...(auth ? { declaration: handoffSemantic(c.operation, c.payload), package_sha256: "a".repeat(64), manifest_sha256: "b".repeat(64), mappings_sha256: "c".repeat(64), content_sha256: "d".repeat(64), limits: [], signers: [scope.principalId], blocked: [], prepared_at: "2026-10-17T12:00:00Z", external_received: false, external_effective: false } : { original, source, issuer: ready ? { key: "host-substitute", version: "v1", epoch: 1, system: "实际系统", subject_id: "actual-recipient", proof_sha256: "e".repeat(64) } : null, mismatches: [], received_at: "2026-10-17T12:00:01Z" }) } };
}
function waiting(c = command()): HandoffPending { return { stage: "preview", command: c, inputs: inputs(c) }; }
function prepared(p = waiting()) { return { command: { ...structuredClone(p.command), payload: { ...structuredClone(p.command.payload), approval_token: "actual-common-token-substitute" } }, approval_token: "actual-common-token-substitute", write_tier: "T2", named_decision: true, expires_at: null, review: { operation: p.command.operation, after: { ...structuredClone(p.inputs!.candidate), prepared_at: null }, authority: p.inputs!.authority, required_source_read_set: p.command.source_read_set } }; }

test("authorization reads actual inputs and one common preview without execute", async () => {
  const c = command(), calls: string[] = [], stages: HandoffPending[] = [];
  const answer = await runHandoffRequest(async <T>(path: string) => { calls.push(path); return (path.endsWith("/inputs") ? inputs(c) : prepared(waiting(c))) as T; }, { stage: "inputs", command: c }, scope, p => stages.push(p), () => true);
  assert.equal(answer?.stage, "preview"); assert.deepEqual(calls, [`v1/products/${scope.productId}/external-handoff/inputs`, "v1/commands/preview"]); assert.equal(stages[0].stage, "preview");
});
test("unknown authorization remains review and never creates an external action", async () => {
  const c = command(), calls: string[] = [];
  const result = await runHandoffRequest(async <T>(path: string) => { calls.push(path); return inputs(c, false) as T; }, { stage: "inputs", command: c }, scope, () => {}, () => true);
  assert.equal(result?.stage, "review"); assert.equal(calls.length, 1);
});
test("missing named authority cannot reach common authorization preview", async () => {
  const c = command(), value = inputs(c), calls: string[] = []; value.authority.qualified = false;
  assert.equal((await runHandoffRequest(async <T>(path: string) => { calls.push(path); return value as T; }, { stage: "inputs", command: c }, scope, () => {}, () => true))?.stage, "review"); assert.equal(calls.length, 1);
});
test("a verified unknown-outcome receipt stops for explicit registration without T1 or T2 preview", async () => {
  const c = command(true), value = inputs(c), calls: string[] = [];
  assert.ok(handoffReady(value));
  const result = await runHandoffRequest(async <T>(path: string) => { calls.push(path); return value as T; }, { stage: "inputs", command: c }, scope, () => {}, () => true);
  assert.equal(result?.stage, "review"); assert.equal(calls.length, 1); assert.equal(value.candidate.network_send, false);
});
test("missing trusted issuer stays unknown and no payload can self-register an issuer", () => {
  const c = command(true), value = inputs(c, false); assert.ok(handoffInputs(value, c, scope)); assert.equal(handoffReady(value), false);
  assert.throws(() => parseHandoffPayload({ ...payload(true), issuer: { key: "self-claimed" } }, handoffOperations[1], scope), /发行者/);
});
test("T2 preview permits null expiry and rejects a changed fixed manifest digest", () => {
  const p = waiting(), value = prepared(p); assert.ok(handoffPrepared(value, p, scope)); (value.review.after as Record<string, unknown>).manifest_sha256 = "f".repeat(64); assert.equal(handoffPrepared(value, p, scope), null);
});
test("T2 preview rejects another signer and expired original proof", () => {
  const p = waiting(), value = prepared(p); value.review.authority = { ...value.review.authority, subject_id: id(90) }; assert.equal(handoffPrepared(value, p, scope), null);
  const expired: Record<string, unknown> = prepared(p); expired.expires_at = "2000-01-01T00:00:00Z"; assert.equal(handoffPrepared(expired, p, scope), null);
});
test("explicit UNKNOWN replay retains identical command, key, payload and approval token", async () => {
  const c = prepared().command, original = structuredClone(c), sent: unknown[] = []; let attempts = 0;
  const api = async <T>(path: string, body?: unknown) => { assert.equal(path, "v1/commands"); sent.push(body); if (!attempts++) throw new Error("response lost"); return { id: id(40), operation: c.operation, subject_type: "external_handoff", subject_id: id(20), subject_revision: 1 } as T; };
  const pending = { stage: "execute" as const, command: c }; await assert.rejects(runHandoffRequest(api, pending, scope, () => assert.fail(), () => true), /response lost/); assert.equal((await runHandoffRequest(api, pending, scope, () => assert.fail(), () => true))?.stage, "saved"); assert.equal(sent[0], c); assert.equal(sent[1], c); assert.deepEqual(c, original);
});
test("recording sends only the same source selection after explicit caller action", async () => {
  const c = command(true), copy = structuredClone(c); let count = 0;
  const answer = await runHandoffRequest(async <T>(path: string, body?: unknown) => { count++; assert.equal(path, "v1/commands"); assert.equal(body, c); return { id: id(41), operation: c.operation, subject_type: "external_receipt", subject_id: id(42), subject_revision: 1 } as T; }, { stage: "execute", command: c }, scope, () => assert.fail(), () => true);
  assert.equal(answer?.stage, "saved"); assert.equal(count, 1); assert.deepEqual(c, copy); assert.equal(c.payload.approval_token, undefined); assert.equal(c.payload.issuer, undefined);
});
test("restored pending submission stays scoped to its original package and both decisions", () => {
  const local = blankHandoffLocal(scope), c = prepared().command; Object.assign(local, { package: ref(10), engineering: ref(11), manufacturing: ref(12), pending: { stage: "execute", command: c } }); local.drafts[handoffDraftKey(local.operation, local)] = JSON.stringify(payload());
  assert.deepEqual(restoreHandoffLocal(local, scope), local); assert.equal(restoreHandoffLocal(local, { ...scope, principalId: id(50) }), null); assert.equal(restoreHandoffLocal(local, { ...scope, projectId: id(51) }), null);
  const changed = structuredClone(local); changed.manufacturing = ref(99); assert.equal(restoreHandoffLocal(changed, scope), null);
});
test("scope disposal after inputs cannot open preview or dispatch", async () => {
  const c = command(); let active = true, count = 0;
  assert.equal(await runHandoffRequest(async <T>() => { count++; active = false; return inputs(c) as T; }, { stage: "inputs", command: c }, scope, () => assert.fail(), () => active), null); assert.equal(count, 1);
});
test("actual detail and receipt page must share the selected handoff, intent and read watermark", () => {
  const stages = Object.fromEntries(["sent", "accepted", "effective"].map(stage => [stage, { stage, state: "not_recorded", active: [], covered_scopes: [], mismatches: [] }]));
  const value = { id: id(20), revision: 1, project_id: scope.projectId, purpose: "固定移交用途", package: ref(10), receipt_id: id(30), as_of: { id: id(31), handoff: ref(20), intent: ref(21), receipt_count: 1, latest_receipt: ref(42), epoch: 2, projection_sha256: "a".repeat(64) }, reading: { status: "authorized", ...stages, delivery_unknown: true, rejected: false, failed: false, conflict: false, network_send: false }, network_send: false, authorization: inputs(command()).candidate, authority: {}, intent: { ...ref(21), packet: { handoff: ref(20), manifest: [], mappings: [], network_send: false } }, applicability: "current" };
  assert.ok(handoffDetail(value, scope)); assert.equal(handoffDetail(value, { ...scope, projectId: id(90) }), false);
  const receipt = inputs(command(true)).candidate, page = { as_of: value.as_of, items: [{ ...ref(42), sequence: 1, original: receipt.original, source, issuer: receipt.issuer, mismatches: [], receipt_id: id(43), received_at: "2026-10-17T12:00:01Z" }], before_sequence: null };
  assert.ok(handoffHistoryPage(page, value as HandoffDetail)); assert.equal(handoffHistoryPage({ ...page, as_of: { ...value.as_of, epoch: 3 } }, value as HandoffDetail), false);
});
