import assert from "node:assert/strict";
import test from "node:test";
import { approvalDraft, blankReleaseLocal, newReleaseCommand, parseReleasePayload, releaseDetail, releaseDraftKey, releaseHeader, releaseInputs, releaseOperations, releasePrepared, releaseSemantic, restoreReleaseLocal, runReleaseRequest, type ReleaseAssessment, type ReleaseCommand, type ReleaseDetail, type ReleaseInputs, type ReleasePayload, type ReleasePending, type ReleaseScope } from "./releases";

// Transport responses are explicit IO substitutes, not professional or policy evidence.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope: ReleaseScope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) };
const source = { kind: "artifact", id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const ref = (n: number) => ({ id: id(n), revision: 1 });
const configuration = { definition: ref(6), engineering_configuration: ref(7), manufacturing_configuration: ref(8) };
const range = { quantity: "10", unit: "ea", site: "合成场地", lots: null, lines: null, regions: null };
function payload(approve = false) { return { ...(approve ? { package: ref(10), expiry: null } : { project_id: scope.projectId, subject_config: configuration }), release_scope: range, purpose: "本轮明确用途", reason: "本人核对实际材料", sources: [source], limits: [] }; }
function command(approve = false): ReleaseCommand { return newReleaseCommand(scope, 3, releaseOperations[approve ? 1 : 0], payload(approve)); }
function assessment(discipline: "engineering" | "manufacturing" = "engineering", ready = false): ReleaseAssessment { return { discipline, state: ready ? "READY" : "UNKNOWN", checks: [], blocked: [], unknown: ready ? [] : ["RELEASE_POLICY_MISSING"], conditions: [] }; }
function inputs(c: ReleaseCommand, ready = false): ReleaseInputs {
  const assemble = c.operation === releaseOperations[0], discipline = c.operation === releaseOperations[1] ? "engineering" : "manufacturing";
  return { operation: c.operation, payload: releaseSemantic(c.operation, c.payload) as ReleasePayload, required_source_read_set: c.source_read_set, assessments: [assessment("engineering", ready), assessment("manufacturing", ready)], authority: assemble ? {} : { subject_id: scope.principalId, operation: c.operation, purpose: c.payload.purpose, authorized: true, qualified: true, roles: [discipline], scope: { product_id: scope.productId, project_id: scope.projectId } }, diagnostics: ready ? [] : [{ code: "RELEASE_POLICY_MISSING", detail: "尚无真实适用政策" }], candidate: { structural_only: true, status: "unexecuted_candidate", scope: { tenant_id: id(30), product_id: scope.productId, project_id: scope.projectId }, category_id: scope.categoryId, evidence_digest: "a".repeat(64), ...(assemble ? { declaration: releaseSemantic(c.operation, c.payload), owner_id: scope.principalId, product_revision: 3, policy: ready ? { version: "policy-v1", sources: [source] } : null, objects: [{ ref: { kind: "definition", ...ref(6) }, sha256: "b".repeat(64), product_id: scope.productId }], body_sha256: "c".repeat(64), sources: [source], checks: [], exceptions: [], required_source_read_set: c.source_read_set } : { operation: c.operation, discipline, package: c.payload.package, package_sha256: "d".repeat(64), subject_config: configuration, release_scope: range, purpose: c.payload.purpose, limits: [], policy_version: ready ? "policy-v1" : null, signers: [scope.principalId], expiry: null, assessment: assessment(discipline, ready), input_snapshot: releaseSemantic(c.operation, c.payload), prepared_at: "2026-10-17T12:00:00Z", customer_acceptance: null, external_received: false, external_effective: false }) } };
}
function waiting(c = command(true)): ReleasePending { return { stage: "preview", command: c, inputs: inputs(c, true) as ReleaseInputs }; }
function prepared(p = waiting()) { return { command: { ...structuredClone(p.command), payload: { ...structuredClone(p.command.payload), approval_token: "actual-common-token-substitute" } }, approval_token: "actual-common-token-substitute", write_tier: "T2", named_decision: true, expires_at: null, review: { operation: p.command.operation, after: structuredClone(p.inputs!.candidate), assessments: structuredClone(p.inputs!.assessments), required_source_read_set: structuredClone(p.command.source_read_set), authority: { subject_id: scope.principalId, operation: p.command.operation, purpose: p.command.payload.purpose, roles: ["engineering"], authorized: true, qualified: true, scope: { product_id: scope.productId, project_id: scope.projectId } } } }; }
function detail(): ReleaseDetail { const c = command(), i = inputs(c); return { id: id(10), revision: 1, project_id: scope.projectId, purpose: c.payload.purpose, current: { id: id(10), version: ref(10), epoch: 1 }, applicability: "current", receipt_id: id(11), package: i.candidate, assessments: i.assessments as ReleaseDetail["assessments"], decisions: [] }; }

test("manual assembly reads actual UNKNOWN candidate then stops before any save", async () => {
  const c = command(), before = structuredClone(c), calls: string[] = [], stages: ReleasePending[] = [];
  const answer = await runReleaseRequest(async <T>(path: string) => { calls.push(path); return inputs(c) as T; }, { stage: "inputs", command: c }, scope, p => stages.push(p), () => true);
  assert.equal(answer?.stage, "review"); assert.deepEqual(calls, [`v1/products/${scope.productId}/release/inputs`]); assert.equal(stages[0].stage, "review"); assert.deepEqual(c, before);
});

test("assembly sends the same T0 command only after the caller's explicit save", async () => {
  const c = command(), calls: unknown[] = [];
  const answer = await runReleaseRequest(async <T>(path: string, body?: unknown) => { assert.equal(path, "v1/commands"); calls.push(body); return { id: id(20), operation: c.operation, subject_type: "release_package", subject_id: id(10), subject_revision: 1 } as T; }, { stage: "execute", command: c }, scope, () => assert.fail(), () => true);
  assert.equal(answer?.stage, "saved"); assert.equal(calls[0], c); assert.equal(c.payload.approval_token, undefined);
});

test("ready discipline goes through actual common preview without execute", async () => {
  const c = command(true), calls: string[] = [], stages: ReleasePending[] = [];
  const answer = await runReleaseRequest(async <T>(path: string) => { calls.push(path); return (path.endsWith("/inputs") ? inputs(c, true) : prepared(waiting(c))) as T; }, { stage: "inputs", command: c }, scope, p => stages.push(p), () => true);
  assert.equal(answer?.stage, "preview"); assert.deepEqual(calls, [`v1/products/${scope.productId}/release/inputs`, "v1/commands/preview"]); assert.equal(stages[0].stage, "preview");
});

test("unknown policy cannot advance an approval to common preview or execute", async () => {
  const c = command(true), calls: string[] = [];
  const answer = await runReleaseRequest(async <T>(path: string) => { calls.push(path); return inputs(c) as T; }, { stage: "inputs", command: c }, scope, () => {}, () => true);
  assert.equal(answer?.stage, "review"); assert.equal(calls.length, 1);
});

test("an unqualified named actor keeps actual diagnostics and never advances to preview", async () => {
  const c = command(true), raw = inputs(c, true), calls: string[] = []; raw.authority.qualified = false; raw.authority.reason_codes = ["PROFESSIONAL_QUALIFICATION_REQUIRED"];
  const answer = await runReleaseRequest(async <T>(path: string) => { calls.push(path); return raw as T; }, { stage: "inputs", command: c }, scope, () => {}, () => true);
  assert.equal(answer?.stage, "review"); assert.equal(calls.length, 1); if (answer?.stage === "review") assert.deepEqual(answer.inputs.authority.reason_codes, raw.authority.reason_codes);
});

test("typed defaults compare canonically but actual source and scope changes remain different", () => {
  const c = command(), value = inputs(c); assert.ok(releaseInputs(value, c, scope));
  value.payload.release_scope = { ...value.payload.release_scope, lines: [ref(40)] }; assert.equal(releaseInputs(value, c, scope), null);
  const changed = inputs(c); (changed.payload.sources as typeof source[])[0] = { ...source, position: `line:2;quote_sha256:${"b".repeat(64)}` }; assert.equal(releaseInputs(changed, c, scope), null);
});

for (const fault of ["signer", "project", "source", "policy", "unknown", "scope", "token", "expired"]) test(`T2 preview rejects actual ${fault} mismatch`, () => {
  const p = waiting(), response = prepared(p);
  if (fault === "signer") response.review.authority.subject_id = id(50);
  if (fault === "project") response.review.authority.scope.project_id = id(50);
  if (fault === "source") response.review.after.evidence_digest = "f".repeat(64);
  if (fault === "policy") response.review.after.policy_version = "changed";
  if (fault === "unknown") (response.review.after.assessment as ReleaseAssessment).state = "UNKNOWN";
  if (fault === "scope") response.command.payload.release_scope = { ...range, quantity: "20" };
  if (fault === "token") response.approval_token = "another-common-token-substitute";
  if (fault === "expired") (response as Record<string, unknown>).expires_at = "2000-01-01T00:00:00Z";
  assert.equal(releasePrepared(response, p, scope), null);
});

test("UNKNOWN keeps the exact original command, key and token across explicit replay", async () => {
  const c = prepared().command, original = structuredClone(c), sent: unknown[] = []; let attempts = 0;
  const api = async <T>(path: string, body?: unknown) => { assert.equal(path, "v1/commands"); sent.push(body); if (!attempts++) throw new Error("response lost"); return { id: id(60), operation: c.operation, subject_type: "release_decision", subject_id: id(61), subject_revision: 1 } as T; };
  const pending = { stage: "execute" as const, command: c };
  await assert.rejects(runReleaseRequest(api, pending, scope, () => assert.fail(), () => true), /response lost/);
  assert.equal((await runReleaseRequest(api, pending, scope, () => assert.fail(), () => true))?.stage, "saved"); assert.equal(sent[0], c); assert.equal(sent[1], c); assert.deepEqual(c, original);
});

test("local recovery requires exact principal/project/package and matching draft", () => {
  const local = blankReleaseLocal(scope), c = prepared().command; local.operation = c.operation; local.selected = ref(10); local.pending = { stage: "execute", command: c }; local.drafts[releaseDraftKey(local.operation, local.selected)] = JSON.stringify(payload(true));
  assert.deepEqual(restoreReleaseLocal(local, scope), local);
  for (const changed of [{ ...scope, principalId: id(70) }, { ...scope, projectId: id(71) }, { ...scope, productId: id(72) }]) assert.equal(restoreReleaseLocal(local, changed), null);
  const wrong = structuredClone(local); wrong.selected = ref(71); assert.equal(restoreReleaseLocal(wrong, scope), null);
  const edited = structuredClone(local); edited.drafts[releaseDraftKey(local.operation, local.selected)] = JSON.stringify({ ...payload(true), reason: "另一决定" }); assert.equal(restoreReleaseLocal(edited, scope), null);
});

test("scope disposal after inputs never opens a preview or dispatches a write", async () => {
  const c = command(true); let active = true, count = 0;
  const answer = await runReleaseRequest(async <T>() => { count++; active = false; return inputs(c, true) as T; }, { stage: "inputs", command: c }, scope, () => assert.fail(), () => active);
  assert.equal(answer, null); assert.equal(count, 1);
});

test("list accepts a header and detail requires the actual fixed scope", () => {
  const fixed = detail(), header: Record<string, unknown> = { ...fixed }; delete header.package; delete header.decisions; delete header.assessments;
  assert.ok(releaseHeader(header, scope.projectId)); assert.ok(releaseDetail(fixed, scope)); assert.equal(releaseDetail(header, scope), false);
  assert.equal(releaseDetail({ ...fixed, project_id: id(80) }, scope), false);
  const p = JSON.parse(approvalDraft(fixed)); assert.deepEqual(p.package, ref(10)); assert.equal(p.reason, "");
  assert.throws(() => parseReleasePayload(p, releaseOperations[1], scope, ref(10)), /精确用途/);
});

test("actual mapped assessments and an unchecked header retain unknown without a full read", () => {
  const c = command(), raw = inputs(c), mapped = { ...raw, assessments: { engineering: raw.assessments[0], manufacturing: raw.assessments[1] } };
  assert.equal(releaseInputs(mapped, c, scope)?.assessments[0].state, "UNKNOWN");
  assert.ok(releaseHeader({ ...detail(), applicability: "not_checked" }, scope.projectId));
  assert.equal(releaseDetail({ ...detail(), applicability: "not_checked" }, scope), false);
});

test("selected scope can be ready while the whole package remains unknown", async () => {
  const c = command(true), raw = inputs(c, true); raw.assessments = [assessment("engineering"), assessment("manufacturing")]; const p = { stage: "preview" as const, command: c, inputs: raw }, response = prepared(p);
  assert.ok(releasePrepared(response, p, scope));
  const answer = await runReleaseRequest(async <T>(path: string) => (path.endsWith("/inputs") ? raw : response) as T, { stage: "inputs", command: c }, scope, () => {}, () => true);
  assert.equal(answer?.stage, "preview");
});

test("server retains actual package and exception limits in addition to this declaration", () => {
  const c = command(true), raw = inputs(c, true), added = { text: "真实独立例外限制", sources: [source] }; raw.candidate.limits = [added];
  assert.ok(releaseInputs(raw, c, scope)); const p = { stage: "preview" as const, command: c, inputs: raw }, response = prepared(p); assert.ok(releasePrepared(response, p, scope));
  (response.review.after.limits as unknown[]).push({ text: "未经本次材料核对的新限制", sources: [source] }); assert.equal(releasePrepared(response, p, scope), null);
});

test("explicit expiry preserves sub-millisecond precision and exact original declaration", () => {
  const c = command(true); c.payload.expiry = "2099-01-01T00:00:00.123456Z";
  const raw = inputs(c, true); raw.candidate.expiry = c.payload.expiry;
  const p = { stage: "preview" as const, command: c, inputs: raw }, response = prepared(p);
  response.review.after.expiry = "2099-01-01T08:00:00.123456+08:00";
  assert.ok(releasePrepared(response, p, scope));
  response.review.after.expiry = "2099-01-01T08:00:00.123499+08:00";
  assert.equal(releasePrepared(response, p, scope), null);
});
