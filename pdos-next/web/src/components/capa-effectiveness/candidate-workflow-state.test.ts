import assert from "node:assert/strict";
import test from "node:test";
import { candidatePayload, candidateLinkKey, candidateMappingKey, candidateSourceKey,
  type CandidateFormPayload, type CandidateMaterials, type CandidateFormScope } from "./candidate-form-contract";
import {
  blankCandidateLocal, candidateBasisChanged, candidateCanPrepare, candidateErrorStatus, candidateFailureOutcome,
  candidateHostBasis, candidateIdentity, candidateInputsCommand, candidatePrepared, candidateReceipt, candidateSaved,
  exactCandidatePayload, newCandidateCommand, restoreCandidateLocal,
  type CandidateCommand, type CandidateHost, type CandidateLocal, type CandidateReceipt,
} from "./candidate-workflow-state";

// Shape-only host choices. No test fixture attests actual professional/bytes/UOW facts.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const clock = "2026-10-03T06:25:03.160086-07:00";
const ref = { artifact_id: id(10), expected_revision: 1, line: 2, quote: `原值与时钟保持 ${clock}` };
const scope: CandidateFormScope = { tenant_id: id(1), product_id: id(2), project_id: id(3), principal_id: id(4),
  issue_id: id(5), current_issue: { id: id(6), revision: 9 }, capa_id: id(7), failure_ids: ["fixed-failure"],
  visibility: "private", issue_label: "固定失败问题", capa_label: "固定整改", origin_issue: { id: id(8), revision: 6 } };
const materials: CandidateMaterials = { links: [{ ref: { id: id(9), revision: 1 }, label: "实际回链", detail: "保留草稿历史", visibility: "private" }],
  mappings: [{ mapping: { failure_id: "fixed-failure", run: { id: id(11), revision: 2, kind: "verification_run", key: null },
    sample_id: id(12), sample_revision: 1, actual_configuration_id: id(13), actual_configuration_revision: 1,
    item_id: "pressure", measurement_id: null, projection_id: null, applicability_sources: [ref] },
    label: "原失败与新复验逐项对应", original_value: "150.00000000", conditions: "20°C", occurred_at: clock,
    original_timezone: "America/Los_Angeles", detail: "未补造观测", visibility: "private" }],
  sources: [{ reference: ref, title: "实际原文", visibility: "private" }] };
function host(): CandidateHost { return { scope, materials, product_revision: 12,
  required_source_read_set: [{ artifact_id: ref.artifact_id, expected_revision: 1 }], allowed: true,
  current_evaluation: "evaluated_current", source_status: "current", authority: { authorized: true, qualified: true, synthetic: true },
  missing: [], allowProductVisibility: false, accessEpoch: "actual-host-read-1" }; }
function payload(): CandidateFormPayload { return candidatePayload(scope, materials, {
  links: materials.links.map(row => candidateLinkKey(row.ref)), mappings: materials.mappings.map(row => candidateMappingKey(row.mapping)),
  sources: materials.sources.map(row => candidateSourceKey(row.reference)), reason: "固定原失败与新复验依据", visibility: "private",
})!; }
function command(): CandidateCommand { return newCandidateCommand(host(), payload(), id(20), id(21)); }
function preview(original = command()): Record<string, unknown> {
  const binding = { basis: { issue_id: scope.issue_id, capa_id: scope.capa_id, issue_revision: 6 },
    remediation_link_refs: original.payload.remediation_link_refs, mappings: original.payload.mappings };
  return { command: { ...original, payload: { ...original.payload, confirmation_token: "opaque-server-confirmation-token" } },
    expires_at: "2099-10-03T14:00:00Z", review: { operation: original.operation, payload_semantic: original.payload,
      stable_anchor: { origin: { ref: scope.origin_issue } }, binding, inspection: { binding, applicable: null,
        independently_verified: null, observation_complete: null, result: "indeterminate" },
      raw_source_basis: [], required_source_read_set: original.source_read_set, sources: [], authority_snapshot: {},
      policy_snapshot: {}, owner_id: scope.principal_id, visibility: "private", current_issue_revision: 9 } };
}
function unknownLocal(): CandidateLocal {
  const identity = candidateIdentity(host())!, original = command(), prepared = candidatePrepared(preview(original), original)!;
  return { ...blankCandidateLocal(identity), draft: payload(), pending: { stage: "execute", command: prepared.command }, outcome: "unknown" };
}
const receipt: CandidateReceipt = { id: id(30), operation: "quality.capa.verification.candidate.record", subject_id: id(31),
  subject_revision: 1, subject_type: "capa_verification_candidate" };

test("Current CAS stays 9 while the fixed origin remains 6", () => {
  const c = command(); assert.equal(c.payload.expected_issue_revision, 9); assert.equal(scope.origin_issue!.revision, 6);
  assert.throws(() => newCandidateCommand(host(), { ...payload(), expected_issue_revision: 6 }, id(20), id(21)));
});
test("all absent or negative actual capability/qualification branches stay disabled", () => {
  for (const h of [{ ...host(), allowed: false }, { ...host(), current_evaluation: "not_evaluated_historical" as const },
    { ...host(), source_status: "needs_recheck" as const }, { ...host(), authority: { ...host().authority, qualified: null } },
    { ...host(), authority: { ...host().authority, authorized: false } }]) assert.equal(candidateCanPrepare(h), false);
  assert.equal(candidateCanPrepare({ ...host(), allowed: undefined } as unknown as CandidateHost), false);
});
test("host material or access epoch changes produce a different exact basis", () => {
  assert.notEqual(candidateHostBasis(host()), candidateHostBasis({ ...host(), accessEpoch: "actual-host-read-2" }));
  assert.notEqual(candidateHostBasis(host()), candidateHostBasis({ ...host(), materials: { ...materials,
    sources: [{ ...materials.sources[0], reference: { ...ref, quote: "另一精确原文" } }] } }));
});
test("unavailable/duplicate choices cannot produce an old or arbitrary pair", () => {
  assert.throws(() => newCandidateCommand({ ...host(), materials: { ...materials, mappings: [] } }, payload(), id(20), id(21)));
  assert.equal(exactCandidatePayload({ ...payload(), sources: [ref, ref] }), false);
  assert.equal(exactCandidatePayload({ ...payload(), sources: [{ ...ref, line: true }] }), false);
  assert.equal(exactCandidatePayload({ ...payload(), trusted_qualification: true }), false);
});
test("partial material with no mappings remains a tokenless indeterminate selection", () => {
  const p = { ...payload(), remediation_link_refs: [], mappings: [] };
  assert.equal(exactCandidatePayload(p), true); assert.equal(newCandidateCommand(host(), p, id(20), id(21)).payload.mappings.length, 0);
});
test("a shared origin requires explicit same audience and no private material", () => {
  const h = { ...host(), scope: { ...scope, visibility: "category" as const }, allowProductVisibility: true };
  assert.throws(() => newCandidateCommand(h, payload(), id(20), id(21)));
  assert.throws(() => newCandidateCommand(h, { ...payload(), visibility: "category" }, id(20), id(21)));
});
test("server inputs may add real reads but cannot omit or replace original sources", () => {
  const original = command(), extra = { artifact_id: id(32), expected_revision: 3 };
  const c = candidateInputsCommand({ operation: original.operation, allowed: true,
    required_source_read_set: [...original.source_read_set, extra] }, original)!;
  assert.deepEqual(c.payload, original.payload); assert.equal(c.command_id, original.command_id); assert.equal(c.idempotency_key, original.idempotency_key);
  assert.throws(() => candidateInputsCommand({ operation: original.operation, allowed: true, required_source_read_set: [extra] }, original));
  assert.equal(candidateInputsCommand({ operation: original.operation, allowed: false, required_source_read_set: [] }, original), null);
});
test("actual 13-key preview preserves whole request and three unknown facts", () => {
  const original = command(), p = candidatePrepared(preview(original), original)!;
  assert.ok(p); assert.equal(p.command.payload.sources[0].quote, ref.quote);
  assert.equal(p.review.inspection.result, "indeterminate"); assert.equal(p.review.current_issue_revision, 9);
  assert.equal(p.command.command_id, original.command_id); assert.equal(p.command.idempotency_key, original.idempotency_key);
  assert.equal(materials.mappings[0].occurred_at, clock);
});
test("old before/after shape and altered semantic/key/readset cannot masquerade as this preview", () => {
  const original = command(), p = preview(original);
  assert.equal(candidatePrepared({ ...p, review: { before: {}, after: {}, effect: "旧预览" } }, original), null);
  for (const mutate of [
    (x: Record<string, unknown>) => { (x.command as CandidateCommand).idempotency_key = id(40); },
    (x: Record<string, unknown>) => { (x.command as CandidateCommand).payload = { ...payload(), reason: "改变原因", confirmation_token: "opaque-server-confirmation-token" }; },
    (x: Record<string, unknown>) => { (x.command as CandidateCommand).source_read_set = []; },
    (x: Record<string, unknown>) => { ((x.review as Record<string, unknown>).inspection as Record<string, unknown>).applicable = true; },
    (x: Record<string, unknown>) => { (x.review as Record<string, unknown>).current_issue_revision = 6; },
  ]) { const changed = structuredClone(p); mutate(changed); assert.equal(candidatePrepared(changed, original), null); }
});
test("expired unsubmitted preview needs explicit preview and does not create a new key", () => {
  const original = command(), p = preview(original); p.expires_at = "2020-01-01T00:00:00Z";
  assert.equal(candidatePrepared(p, original), null); assert.equal(original.idempotency_key, id(21));
});
test("unknown restore carries exact original token/payload/key even after read basis changes", () => {
  const local = unknownLocal(), changed = candidateBasisChanged(local);
  assert.equal(changed.draft, null); assert.deepEqual(changed.pending, local.pending);
  assert.deepEqual(restoreCandidateLocal(JSON.parse(JSON.stringify(changed)), changed.identity)!.pending, local.pending);
});
test("an unsubmitted input/preview is invalidated on new actual materials", () => {
  for (const stage of ["inputs", "preview"] as const) {
    const local = { ...blankCandidateLocal(candidateIdentity(host())!), draft: payload(), pending: { stage, command: command() } };
    assert.equal(candidateBasisChanged(local).pending, null); assert.equal(candidateBasisChanged(local).draft, null);
  }
});
test("different private scope and malformed execute token cannot restore an old request", () => {
  const local = unknownLocal(); assert.equal(restoreCandidateLocal(local, candidateIdentity({ ...host(), scope: { ...scope, principal_id: id(50) } })!), null);
  const malformed = structuredClone(local); delete malformed.pending!.command.payload.confirmation_token;
  assert.equal(restoreCandidateLocal(malformed, local.identity), null);
  assert.equal(restoreCandidateLocal({ ...local, current_qualification: true }, local.identity), null);
});
test("common candidate Receipt remains saved ahead of read failure and stale pending", () => {
  const local = candidateSaved(unknownLocal(), receipt);
  assert.equal(local.pending, null); assert.equal(local.draft, null);
  assert.deepEqual(candidateFailureOutcome(local, 500), { clearPrivate: false, saved: true, pending: null });
  const restored = restoreCandidateLocal({ ...local, pending: unknownLocal().pending }, local.identity)!;
  assert.equal(restored.outcome, "saved"); assert.equal(restored.pending, null); assert.deepEqual(restored.savedReceipt, receipt);
});
test("actual Error status 401/403 clears private data without turning saved into unknown", () => {
  const e = Object.assign(new Error("transport"), { status: 403, code: "FORBIDDEN_SCOPE" });
  assert.equal(candidateErrorStatus(e), 403);
  assert.deepEqual(candidateFailureOutcome(candidateSaved(unknownLocal(), receipt), candidateErrorStatus(e)),
    { clearPrivate: true, saved: true, pending: null });
  assert.equal(candidateErrorStatus(Object.assign(new Error(), { status: "403" })), undefined);
});
test("ordinary 409/500/timeout cannot unlock unknown or discard the original key", () => {
  const local = unknownLocal(); for (const status of [409, 500, undefined]) {
    const recovery = candidateFailureOutcome(local, status); assert.equal(recovery.clearPrivate, false); assert.equal(recovery.saved, false);
    assert.deepEqual(recovery.pending!.command, local.pending!.command);
  }
});
test("a Receipt from another family or coercive revision is not a success", () => {
  assert.equal(candidateReceipt(receipt), true); assert.equal(candidateReceipt({ ...receipt, subject_type: "quality_issue" }), false);
  assert.equal(candidateReceipt({ ...receipt, subject_revision: true }), false);
  assert.equal(candidateReceipt({ ...receipt, subject_revision: 2 }), false);
});
