import assert from "node:assert/strict";
import test from "node:test";
import {
  blankExceptionLocal, exceptionDetail, exceptionDraftKey, exceptionInputs, exceptionOperations, exceptionPrepared, exceptionReady, exceptionSemantic, newExceptionCommand, parseExceptionPayload, restoreExceptionLocal, runExceptionRequest,
  type ExceptionCommand, type ExceptionInputs, type ExceptionPayload, type ExceptionPending, type ExceptionScope,
} from "./release-exceptions";

// Transport substitutes test client invariants, never actual qualifications,
// controlled source registration, professional signing or PostgreSQL evidence.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, ref = (n: number) => ({ id: id(n), revision: 1 });
const scope: ExceptionScope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) };
const source = { kind: "artifact", id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const range = { quantity: "10", unit: "ea", site: "固定场地", lots: null, lines: [], regions: ["CN"] };
const configuration = { definition: ref(6), engineering_configuration: ref(7), manufacturing_configuration: ref(8) };
function payload(withdraw = false): ExceptionPayload { return withdraw ? { exception: ref(20), sources: [source], reason: "本人明确撤回原例外" } : { basis_package: ref(10), discipline: "engineering", release_scope: range, purpose: "固定发布用途", check_keys: ["check-1"], limits: [{ text: "限定本批次", sources: [source] }], risk_controls: [{ text: "逐件人工核对", sources: [source] }], expiry: null, sources: [source], reason: "本人核对限定范围" }; }
function command(withdraw = false) { return newExceptionCommand(scope, 3, exceptionOperations[withdraw ? 1 : 0], payload(withdraw)); }
function inputs(c: ExceptionCommand, state: "READY" | "UNKNOWN" | "BLOCKED" = "READY"): ExceptionInputs {
  const approved = c.operation === exceptionOperations[0], original = payload() as ExceptionPayload & { purpose: string };
  return { operation: c.operation, payload: exceptionSemantic(c.operation, c.payload) as ExceptionPayload, required_source_read_set: c.source_read_set, authority: { subject_id: scope.principalId, operation: c.operation, purpose: original.purpose, authorized: true, qualified: true, roles: ["engineering"], scope: { product_id: scope.productId, project_id: scope.projectId } }, diagnostics: [], candidate: { structural_only: true, status: "unexecuted_candidate", operation: c.operation, action: approved ? "approved" : "withdrawn", declaration: exceptionSemantic(c.operation, c.payload), scope: { tenant_id: id(30), product_id: scope.productId, project_id: scope.projectId }, category_id: scope.categoryId, owner_id: scope.principalId, visibility: "private", discipline: "engineering", basis_package: ref(10), policy_fact: ref(11), policy_version: "actual-policy-v1", subject_config: configuration, release_scope: range, purpose: original.purpose, check_keys: original.check_keys, selected_checks: [{ key: "check-1", discipline: "engineering", applicable: true, required: true, state: "blocked", non_waivable: state === "BLOCKED", detail: "原检查阻塞，例外不改变此事实", sources: [source], release_scope: range, exception: null }], limits: original.limits, risk_controls: original.risk_controls, expiry: null, sources: [source], required_source_read_set: c.source_read_set, signers: [scope.principalId], prepared_at: "2026-10-17T12:00:00Z", previous: approved ? null : ref(20), reason: c.payload.reason, state, unknown: state === "UNKNOWN" ? ["RELEASE_POLICY_NOT_CURRENT"] : [], blocked: state === "BLOCKED" ? ["check-1:NON_WAIVABLE"] : [] } };
}
function waiting(c = command()): ExceptionPending { return { stage: "preview", command: c, inputs: inputs(c) }; }
function preview(p = waiting()) { return { command: { ...structuredClone(p.command), payload: { ...structuredClone(p.command.payload), approval_token: "actual-common-token-substitute" } }, approval_token: "actual-common-token-substitute", write_tier: "T2", named_decision: true, expires_at: null, review: { operation: p.command.operation, after: { ...structuredClone(p.inputs!.candidate), prepared_at: "2026-10-17T12:00:01Z" }, authority: p.inputs!.authority, required_source_read_set: p.command.source_read_set } }; }

for (const withdraw of [false, true]) test(`${withdraw ? "withdrawal" : "exception decision"} requires one common named preview and stops before execution`, async () => {
  const c = command(withdraw), calls: string[] = [], stages: ExceptionPending[] = [];
  const result = await runExceptionRequest(async <T>(route: string) => { calls.push(route); return (route.endsWith("/inputs") ? inputs(c) : preview(waiting(c))) as T; }, { stage: "inputs", command: c }, scope, p => stages.push(p), () => true);
  assert.equal(result?.stage, "preview"); assert.deepEqual(calls, [`v1/products/${scope.productId}/release-exception/inputs`, "v1/commands/preview"]); assert.equal(stages[0].stage, "preview");
});
test("a ready exception retains the selected original blocked check", () => { const c = command(), value = inputs(c); assert.ok(exceptionInputs(value, c, scope)); assert.ok(exceptionReady(value)); assert.equal(value.candidate.selected_checks[0].state, "blocked"); });
for (const state of ["UNKNOWN", "BLOCKED"] as const) test(`${state} actual policy or non-waivable evidence cannot reach preview`, async () => {
  const c = command(), calls: string[] = []; const result = await runExceptionRequest(async <T>(route: string) => { calls.push(route); return inputs(c, state) as T; }, { stage: "inputs", command: c }, scope, () => {}, () => true);
  assert.equal(result?.stage, "review"); assert.equal(calls.length, 1);
});
test("missing current personal qualification never reaches the shared preview", async () => { const c = command(true), value = inputs(c); value.authority.subject_id = id(90); let count = 0; assert.equal((await runExceptionRequest(async <T>() => { count++; return value as T; }, { stage: "inputs", command: c }, scope, () => {}, () => true))?.stage, "review"); assert.equal(count, 1); });
test("client declarations reject extra authority facts, repeated checks, and conflicting source versions", () => {
  for (const extra of ["project_id", "visibility", "issuer", "qualified"]) assert.throws(() => parseExceptionPayload({ ...payload(), [extra]: "client-assertion" }, exceptionOperations[0]));
  assert.throws(() => parseExceptionPayload({ ...payload(), check_keys: ["check-1", "check-1"] }, exceptionOperations[0]));
  assert.throws(() => newExceptionCommand(scope, 3, exceptionOperations[0], { ...payload(), sources: [source, { ...source, revision: 2 }] }), /两个版本/);
  assert.throws(() => newExceptionCommand(scope, 3, exceptionOperations[0], { ...payload(), approval_token: "self-selected-approval-token" }), /共同预览/);
});
test("preview permits no deadline and rejects any changed fixed policy, controls, signer or command", () => {
  const p = waiting(); assert.ok(exceptionPrepared(preview(p), p, scope));
  for (const key of ["policy_fact", "subject_config", "selected_checks", "risk_controls", "limits", "signers"]) { const value = preview(p); (value.review.after as Record<string, unknown>)[key] = key === "policy_fact" ? ref(99) : []; assert.equal(exceptionPrepared(value, p, scope), null, key); }
  const changed = preview(p); changed.command.idempotency_key = id(99); assert.equal(exceptionPrepared(changed, p, scope), null);
  const expired: Record<string, unknown> = preview(p); expired.expires_at = "2000-01-01T00:00:00Z"; assert.equal(exceptionPrepared(expired, p, scope), null);
});
test("input scope and direct source-read substitution cannot enter a candidate", () => {
  const c = command(), foreign = inputs(c); foreign.candidate.scope = { product_id: scope.productId, project_id: id(90) }; assert.equal(exceptionInputs(foreign, c, scope), null);
  const changed = inputs(c); changed.required_source_read_set = [{ artifact_id: id(91), expected_revision: 1 }]; assert.equal(exceptionInputs(changed, c, scope), null);
});
test("the actual common review permits its normalized null prepared_at only at preview", () => {
  const p = waiting(), value = preview(p); (value.review.after as Record<string, unknown>).prepared_at = null;
  assert.ok(exceptionPrepared(value, p, scope));
  const raw = inputs(p.command); raw.candidate.prepared_at = null; assert.equal(exceptionInputs(raw, p.command, scope), null);
  for (const invalid of [undefined, "", "not-an-instant"]) { (value.review.after as Record<string, unknown>).prepared_at = invalid; assert.equal(exceptionPrepared(value, p, scope), null); }
});
test("expiry semantic comparison preserves microseconds without adding a default TTL", () => {
  const operation = exceptionOperations[0], left = { ...payload(), expiry: "2030-01-01T08:00:00.123456+08:00" }, right = { ...payload(), expiry: "2030-01-01T00:00:00.123456Z" };
  assert.deepEqual(exceptionSemantic(operation, left), exceptionSemantic(operation, right)); assert.notDeepEqual(exceptionSemantic(operation, left), exceptionSemantic(operation, { ...right, expiry: "2030-01-01T00:00:00.123457Z" })); assert.equal(exceptionSemantic(operation, payload()).expiry, null);
});
test("response loss has no automatic retry; explicit replay retains the exact original approved request", async () => {
  const c = preview(waiting(command(true))).command, saved = structuredClone(c), sent: unknown[] = []; let attempt = 0;
  const api = async <T>(route: string, body?: unknown) => { assert.equal(route, "v1/commands"); sent.push(body); if (!attempt++) throw new Error("response lost"); return { id: id(40), operation: c.operation, subject_type: "release_exception", subject_id: id(21), subject_revision: 1 } as T; };
  const p: ExceptionPending = { stage: "execute", command: c }; await assert.rejects(runExceptionRequest(api, p, scope, () => assert.fail(), () => true), /response lost/); assert.equal(sent.length, 1); assert.equal((await runExceptionRequest(api, p, scope, () => assert.fail(), () => true))?.stage, "saved"); assert.equal(sent[0], c); assert.equal(sent[1], c); assert.deepEqual(c, saved);
});
test("restoring the original request binds actor, project, explicit package and withdrawal selection", () => {
  for (const withdraw of [false, true]) { const local = blankExceptionLocal(scope), c = preview(waiting(command(withdraw))).command; Object.assign(local, { operation: c.operation, package: ref(10), selected: ref(20), pending: { stage: "execute", command: c } }); local.drafts[exceptionDraftKey(local.operation, local)] = JSON.stringify(payload(withdraw));
    assert.deepEqual(restoreExceptionLocal(local, scope), local); assert.equal(restoreExceptionLocal(local, { ...scope, principalId: id(90) }), null); assert.equal(restoreExceptionLocal(local, { ...scope, projectId: id(91) }), null);
    const changed = structuredClone(local); if (withdraw) changed.selected = ref(92); else changed.package = ref(92); assert.equal(restoreExceptionLocal(changed, scope), null);
  }
});
test("disposing a scope after actual inputs prevents the later preview", async () => { const c = command(); let active = true, calls = 0; assert.equal(await runExceptionRequest(async <T>() => { calls++; active = false; return inputs(c) as T; }, { stage: "inputs", command: c }, scope, () => assert.fail(), () => active), null); assert.equal(calls, 1); });
test("saved history keeps immutable independent row IDs and exact shared current watermark", () => {
  const c = command(), candidate = inputs(c).candidate, current = { decision: ref(21), epoch: 2, action: "withdrawn" };
  const value = { id: id(20), revision: 1, project_id: scope.projectId, purpose: candidate.purpose, discipline: "engineering", action: "approved", basis_package: ref(10), series_id: id(20), visibility: "private", expiry: null, created_at: "2026-10-17T12:00:00Z", receipt_id: id(40), as_of: current, decision: candidate, authority: {}, applicability: "needs_recheck", current };
  assert.ok(exceptionDetail(value, scope)); assert.equal(exceptionDetail({ ...value, revision: 2 }, scope), false); assert.equal(exceptionDetail({ ...value, current: { ...current, epoch: 3 } }, scope), false); assert.equal(exceptionDetail(value, { ...scope, projectId: id(90) }), false);
});
