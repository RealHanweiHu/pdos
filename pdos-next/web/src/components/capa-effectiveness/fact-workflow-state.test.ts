import assert from "node:assert/strict";
import test from "node:test";
import { factCandidateSelectionMatches, factPendingCandidate, factCanPrepare, factIdentity, factInstant, factSourceKey, factRecordTiming, validFactHost, factWorkflowSchema, observationOperation, reviewOperation,
  readFactBusinessReview, sameFactInstant, validFactPayload, type FactHost, type ObservationPayload, type NamedReviewPayload,
  type FactCommand, type FactReceipt } from "./fact-workflow-contract";
import { blankFactLocal, factBasisChanged, factBegin, factFailure, factInputsCommand, factPrepared, factSaved,
  newFactCommand, restoreFactLocal, selectFactSources } from "./fact-workflow-state";

// Contract/state fixtures only. These are not professional, bytes or transaction attestations.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const source = { id: id(10), revision: 1, kind: "artifact" as const, position: `line:2;quote_sha256:${"a".repeat(64)}` };
const rule = { id: id(20), revision: 2, sha256: "b".repeat(64) }, candidate = { id: id(21), revision: 1, sha256: "c".repeat(64) };
const observed = { id: id(22), revision: 1, sha256: "d".repeat(64) };
const instant = "2026-10-03T06:25:03.160086+00:00";
function host(): FactHost {
  const capability = { allowed: true, authority: { authorized: true, qualified: true, synthetic: true }, independence: "verified" as const,
    current_evaluation: "evaluated_current" as const, source_status: "current" as const, missing: [], required_source_read_set: [{ artifact_id: source.id, expected_revision: 1 }] };
  return { schema_version: factWorkflowSchema, binding: { scope: { tenant_id: id(1), product_id: id(2), project_id: id(3) }, caller_id: id(4),
    issue_id: id(5), current_issue: { id: id(6), revision: 8 }, capa_id: id(7), purpose: "固定用途", owner_id: id(4), visibility: "private" },
    product_revision: 11, access_epoch: "actual-read-epoch", rules: [{ ref: rule, label: "固定发布规则", target_keys: ["sample-one"], previous: null }],
    candidate, observations: [observed], sources: [{ source, title: "原始观察资料", line: 2, quote: "记录原值与实际微秒时间", visibility: "private" }],
    records: [{ key: "original-record", label: "实际样件记录", detail: "原值、工况及事件均来自固定原文", visibility: "private",
      record: { target_key: "sample-one", occurred_at: instant, original_timezone: "UTC", sources: [source], raw_material: { raw_value: "11.0000", unit: "V", conditions: "23C" } } }],
    pairs: [{ key: "fixed-pair", label: "原失败与实际复验", detail: "只核对固定配对", visibility: "private", method: source, criterion: source,
      mapping: { failure_id: "original-failure", run: { id: id(31), revision: 3, kind: "verification_run", key: null }, sample_id: id(32), sample_revision: 1,
        actual_configuration_id: id(33), actual_configuration_revision: 1, item_id: "voltage", measurement_id: id(34), projection_id: id(35), applicability_sources: [] } }],
    actions: [{ action_id: id(40), label: "实际整改措施", detail: "保留实际完成历史", visibility: "private" }], history: [{ ref: rule, kind: "rule", label: "真实固定规则",
      fact: { sampling: { minimum_records: 1, observation_from: "2026-10-03T00:00:00Z", observation_until: "2026-10-04T00:00:00Z", require_named_review: true, require_run_review: true, require_disposition: true } },
      current_evaluation: "evaluated_current", source_status: "current", missing: [] }],
    operations: { [observationOperation]: structuredClone(capability), [reviewOperation]: structuredClone(capability) }, missing: [], effectiveness_enabled: false, close_enabled: false };
}
function observation(): ObservationPayload { const h = host(); return { issue_id: h.binding.issue_id, expected_issue_revision: 8, capa_id: h.binding.capa_id,
  rule, previous: null, target_keys: ["sample-one"], observed_from: "2026-10-03T06:25:03.160085+00:00", observed_until: instant,
  at: { occurred_at: instant, original_timezone: "UTC", source, effective_at: null }, records: [h.records[0].record], coverage_sources: [source], sources: [source], reason: "记录实际原文观察", visibility: "private" }; }
function named(): NamedReviewPayload { const h = host(); return { issue_id: h.binding.issue_id, expected_issue_revision: 8, capa_id: h.binding.capa_id,
  candidate, rule, observations: [observed], at: observation().at, pair_applicability: [{ mapping: h.pairs[0].mapping, method: source, criterion: source, conclusion: "unknown", reason: "实际复验仍有缺项", sources: [source] }],
  action_fulfillment: [{ action_id: h.actions[0].action_id, conclusion: "unknown", reason: "不从存在回链推定完成", sources: [source] }], conclusion: "unknown", reason: "独立专业复核仍待核对", sources: [source], visibility: "private" }; }
function command(op = observationOperation as FactCommand["operation"]): FactCommand { return newFactCommand(host(), op, op === observationOperation ? observation() : named(), id(50), id(51)); }
function preview(c = command()) {
  const review = { operation: c.operation, payload_semantic: c.payload, stable_anchor: { origin: { ref: { id: id(80), revision: 6 }, issue: { root_cause: { text: "固定具名根因" },
    capa: { actions: [{ text: "实际整改", completion: { text: "完成事实", at: observation().at } }] } } }, failures: [{ failure: { measurement_id: id(81) }, result: { verified: { run: {
      measurements: [{ id: id(81), raw_value: "11.0000", unit: "V", conditions: "23C", equipment_label: "固定原设备", observed_at: instant, observed_timezone: "UTC" }],
    } } } }] }, binding: { kind: c.operation === observationOperation ? "observation" : "review", current_issue_version_id: id(6), series: null,
    body_material: { ...c.payload, kind: c.operation === observationOperation ? "observation" : "review", scope: host().binding.scope, purpose: "固定用途", owner_id: id(4), nature: "synthetic" } },
    inspection: { applicable: null, observation_complete: null, missing: [] }, raw_source_basis: [], required_source_read_set: c.source_read_set,
    sources: [source], authority_snapshot: {}, policy_snapshot: {}, owner_id: id(4), visibility: "private", current_issue_revision: 8 };
  const token = c.operation === observationOperation ? "confirmation_token" : "approval_token";
  return { command: { ...c, payload: { ...c.payload, [token]: "actual-opaque-server-token" } }, expires_at: "2099-01-01T00:00:00Z", review,
    ...(c.operation === reviewOperation ? { write_tier: "T2", named_decision: true } : {}) };
}
function unknown() { const identity = factIdentity(host())!, p = factPrepared(preview(), command())!;
  return factBegin(blankFactLocal(identity), { stage: "execute", command: p.command }); }
const receipt: FactReceipt = { id: id(60), operation: observationOperation, subject_id: id(61), subject_revision: 1, subject_type: "capa_observation" };

test("Current CAS differs from original rule and is bound to this issue", () => {
  assert.equal(command().payload.expected_issue_revision, 8); assert.equal(command().payload.rule.revision, 2);
  assert.throws(() => newFactCommand(host(), observationOperation, { ...observation(), expected_issue_revision: 2 }, id(50), id(51)));
});
test("actual candidate choices require explicit selection and exact scoped material", () => {
  const h = host(); h.candidate_options = [{ ref: candidate, label: "固定候选材料", mapping_count: 0, visibility: "private" }];
  const scope = [h.binding.scope.product_id, h.binding.caller_id, h.binding.issue_id] as const;
  assert.equal(factCandidateSelectionMatches(h, ...scope, null), false);
  assert.equal(factCandidateSelectionMatches(h, ...scope, candidate), true);
  h.candidate = null; assert.equal(factCandidateSelectionMatches(h, ...scope, null), true);
  assert.equal(factCandidateSelectionMatches(h, ...scope, candidate), false);
  h.candidate = candidate;
  for (const changed of [{ ...candidate, id: id(90) }, { ...candidate, revision: 2 }, { ...candidate, sha256: "e".repeat(64) }])
    assert.equal(factCandidateSelectionMatches(h, ...scope, changed), false);
  assert.equal(factCandidateSelectionMatches(h, id(99), scope[1], scope[2], candidate), false);
  assert.equal(factCandidateSelectionMatches(h, scope[0], id(99), scope[2], candidate), false);
  assert.equal(factCandidateSelectionMatches(h, scope[0], scope[1], id(99), candidate), false);
  h.candidate_options = []; assert.equal(factCandidateSelectionMatches(h, ...scope, candidate), false);
});
test("candidate index rejects malformed counts, duplicate fixed refs and wrong audience without granting capability", () => {
  const h = host(); assert.equal(validFactHost(h), true);
  assert.equal(factCandidateSelectionMatches(h, h.binding.scope.product_id, h.binding.caller_id, h.binding.issue_id, candidate), false);
  const choice = { ref: candidate, label: "当前可读固定候选", mapping_count: 1, visibility: "private" as const };
  for (const invalid of [null, {}, [choice, choice], [{ ...choice, mapping_count: -1 }], [{ ...choice, mapping_count: 0.5 }],
    [{ ...choice, mapping_count: true }], [{ ...choice, visibility: "public" }], [{ ...choice, ref: { ...candidate, sha256: "wrong" } }]])
    assert.equal(validFactHost({ ...h, candidate_options: invalid } as unknown as FactHost), false);
  h.candidate_options = [choice]; h.operations[reviewOperation].allowed = false;
  assert.equal(validFactHost(h), true); assert.equal(factCanPrepare(h, reviewOperation), false);
});
test("candidate host change cannot migrate an unknown request or its original confirmation", () => {
  const original = unknown(), h = host();
  h.candidate_options = [{ ref: { ...candidate, id: id(91) }, label: "另一固定候选", mapping_count: 1, visibility: "private" }];
  h.candidate = h.candidate_options[0].ref;
  assert.deepEqual(factBasisChanged(original), original);
  assert.deepEqual(restoreFactLocal(JSON.parse(JSON.stringify(original)), factIdentity(h)!)?.pending?.command, original.pending?.command);
  assert.throws(() => factBegin(original, { stage: "inputs", command: command(reviewOperation) }));
});
test("reload restores only the validated original review candidate, not a default or ordinary draft", () => {
  const h = host(), c = command(reviewOperation); h.candidate = null; h.candidate_options = [];
  const identity = factIdentity(h)!;
  for (const stage of ["inputs", "preview", "execute"] as const) {
    const original = stage === "execute" ? factPrepared(preview(c), c)!.command : c;
    const local = factBegin(blankFactLocal(identity), { stage, command: original });
    const restored = restoreFactLocal(JSON.parse(JSON.stringify(local)), identity)!;
    assert.deepEqual(factPendingCandidate(h, restored.pending!.command), candidate);
    assert.deepEqual(restored.pending!.command, original);
    assert.equal(restored.pending!.command.idempotency_key, c.idempotency_key);
  }
  assert.equal(factPendingCandidate(h, command()), null);
  assert.equal(factPendingCandidate(h, { candidate }), null);
  for (const changed of [{ ...c, product_id: id(95) }, { ...c, payload: { ...c.payload, issue_id: id(96) } },
    { ...c, payload: { ...c.payload, capa_id: id(97) } }]) assert.equal(factPendingCandidate(h, changed), null);
  assert.equal(restoreFactLocal(JSON.parse(JSON.stringify(unknown())), JSON.stringify([id(1), id(2), id(3), id(99), id(5), id(7)])), null);
});
test("missing or changed restored candidate cannot clear an unknown command or saved receipt", () => {
  const h = host(), c = command(reviewOperation), prepared = factPrepared(preview(c), c)!;
  const local = factBegin(blankFactLocal(factIdentity(h)!), { stage: "execute", command: prepared.command });
  const originalRef = factPendingCandidate(h, local.pending!.command)!;
  h.candidate = null; h.candidate_options = [];
  assert.equal(factCandidateSelectionMatches(h, h.binding.scope.product_id, h.binding.caller_id, h.binding.issue_id, originalRef), false);
  const failed = factFailure(local, { status: 409, code: "READ_CANDIDATE_MISMATCH" });
  assert.equal(failed.clearPrivate, false); assert.deepEqual(failed.local.pending, local.pending);
  const saved = factSaved(local, { ...receipt, operation: reviewOperation, subject_type: "capa_named_verification_review" });
  assert.equal(factFailure(saved, { status: 503 }).local.savedReceipt?.id, receipt.id);
  assert.equal(factFailure(local, { status: 403 }).clearPrivate, true);
});
test("missing, false and historical qualification never become permission", () => {
  for (const change of [{ allowed: false }, { authority: { authorized: false, qualified: true, synthetic: true } },
    { authority: { authorized: true, qualified: null, synthetic: true } }, { current_evaluation: "not_evaluated_historical" }, { source_status: "needs_recheck" }]) {
    const h = host(); Object.assign(h.operations[observationOperation], change); assert.equal(factCanPrepare(h, observationOperation), false);
  }
  const h = host(); h.operations[reviewOperation].independence = "not_verified"; assert.equal(factCanPrepare(h, reviewOperation), false);
  assert.equal(factCanPrepare({ ...host(), close_enabled: true } as unknown as FactHost, observationOperation), false);
});
test("microsecond interval and offset semantics preserve original event strings", () => {
  assert.equal(validFactPayload(observationOperation, observation()), true);
  assert.equal(sameFactInstant(instant, "2026-10-02T23:25:03.160086-07:00"), true);
  assert.equal(sameFactInstant(instant, "2026-10-03T06:25:03.160000Z"), false);
  assert.equal(command().payload.at.occurred_at, instant); assert.equal(factInstant("2026-10-03T06:25:03.1600867Z"), null);
});
test("whole original record, exact source and private audience cannot be rewritten", () => {
  const p = observation(); p.records[0].raw_material.raw_value = "12.0000"; assert.throws(() => newFactCommand(host(), observationOperation, p, id(50), id(51)));
  const q = observation(); q.at.source = { ...source, position: `line:3;quote_sha256:${"a".repeat(64)}` }; assert.throws(() => newFactCommand(host(), observationOperation, q, id(50), id(51)));
  const h = host(); h.binding.visibility = "category"; assert.throws(() => newFactCommand(h, observationOperation, { ...observation(), visibility: "category" }, id(50), id(51)));
});
test("strict payload refuses issuer/participants/independence/effective clocks", () => {
  for (const extra of [{ issuer: "self" }, { independently_verified: true }, { participants: [id(4)] }, { observation_complete: true }])
    assert.equal(validFactPayload(observationOperation, { ...observation(), ...extra }), false);
  assert.equal(validFactPayload(reviewOperation, { ...named(), at: { ...named().at, effective_at: instant } }), false);
});
test("same record, target, action and observation identities cannot count twice", () => {
  assert.equal(validFactPayload(observationOperation, { ...observation(), records: [observation().records[0], observation().records[0]] }), false);
  assert.equal(validFactPayload(observationOperation, { ...observation(), target_keys: ["sample-one", "sample-one"] }), false);
  assert.equal(validFactPayload(reviewOperation, { ...named(), observations: [observed, observed] }), false);
  assert.equal(validFactPayload(reviewOperation, { ...named(), action_fulfillment: [named().action_fulfillment[0], named().action_fulfillment[0]] }), false);
});
test("source choices are copied whole with no recomputed locator", () => {
  const sources = selectFactSources(host(), [factSourceKey(source)]); assert.deepEqual(sources, [source]);
  assert.throws(() => selectFactSources(host(), [factSourceKey(source), factSourceKey(source)])); assert.throws(() => selectFactSources(host(), ["arbitrary-source"]));
});
test("input read union keeps key and semantics and cannot omit a selected source", () => {
  const c = command(), r = { artifact_id: id(70), expected_revision: 2 };
  const next = factInputsCommand({ operation: c.operation, allowed: true, required_source_read_set: [...c.source_read_set, r] }, c)!;
  assert.deepEqual(next.payload, c.payload); assert.equal(next.idempotency_key, c.idempotency_key);
  assert.throws(() => factInputsCommand({ operation: c.operation, allowed: true, required_source_read_set: [r] }, c));
  assert.equal(factInputsCommand({ operation: c.operation, allowed: false, required_source_read_set: [] }, c), null);
});
test("actual inputs command/review is accepted only with exact original material and full read union", () => {
  const c = command(), extra = { artifact_id: id(74), expected_revision: 2 }, withReads = { ...c, source_read_set: [...c.source_read_set, extra] };
  const v = preview(withReads), actual = { command: withReads, review: v.review };
  assert.deepEqual(factInputsCommand(actual, c), withReads);
  const changed = structuredClone(actual); changed.command.payload.reason = "替换原原因";
  assert.throws(() => factInputsCommand(changed, c));
  assert.throws(() => factInputsCommand({ command: v.command, review: v.review }, c));
  assert.throws(() => factInputsCommand({ command: withReads, review: { ...v.review, current_issue_revision: 7 } }, c));
});
test("actual T1 preview allows omitted display tier; T2 must be named", () => {
  const p = factPrepared(preview(), command())!; assert.equal(p.write_tier, "T1"); assert.equal(p.named_decision, false);
  const c = command(reviewOperation), v = preview(c); assert.equal(factPrepared(v, c)?.write_tier, "T2");
  assert.equal(factPrepared({ ...v, named_decision: false }, c), null); assert.equal(factPrepared({ ...v, write_tier: "T1" }, c), null);
});
test("named T2 review accepts no deadline while T1 confirmation requires one", () => {
  const c = command(reviewOperation), v = preview(c);
  assert.equal(factPrepared({ ...v, expires_at: null }, c)?.write_tier, "T2");
  assert.equal(factPrepared({ ...v, expires_at: null, named_decision: false }, c), null);
  assert.equal(factPrepared({ ...v, expires_at: undefined }, c), null);
  assert.equal(factPrepared({ ...preview(), expires_at: null }, command()), null);
});
test("preview keeps exact command while parsed semantic clocks may use equivalent UTC", () => {
  const c = command(), v = preview(c); const semantic = structuredClone(c.payload) as ObservationPayload;
  semantic.at.occurred_at = "2026-10-03T06:25:03.160086Z"; v.review.payload_semantic = semantic;
  assert.ok(factPrepared(v, c)); semantic.at.occurred_at = "2026-10-03T06:25:03.160000Z"; assert.equal(factPrepared(v, c), null);
  const changed = preview(); changed.command.idempotency_key = id(71); assert.equal(factPrepared(changed, c), null);
});
test("preview rejects replaced full reads, Current version and family material", () => {
  const c = command(); for (const mutate of [
    (v: ReturnType<typeof preview>) => { v.review.current_issue_revision = 7; },
    (v: ReturnType<typeof preview>) => { v.review.required_source_read_set = []; },
    (v: ReturnType<typeof preview>) => { v.review.binding.kind = "rule"; },
  ]) { const v = preview(); mutate(v); assert.equal(factPrepared(v, c), null); }
  assert.equal(factPrepared({ ...preview(), expires_at: "2020-01-01T00:00:00Z" }, c), null);
});
test("UNKNOWN survives basis changes and cannot downgrade to fresh preview", () => {
  const local = unknown(); assert.equal(local.outcome, "unknown"); assert.deepEqual(factBasisChanged(local), local);
  assert.throws(() => factBegin(local, { ...local.pending!, stage: "preview" }));
  assert.deepEqual(restoreFactLocal(JSON.parse(JSON.stringify(local)), local.identity), local);
});
test("restore rejects different actor scope and malformed execute proof", () => {
  const local = unknown(); assert.equal(restoreFactLocal(local, factIdentity({ ...host(), binding: { ...host().binding, caller_id: id(72) } })!), null);
  const x = structuredClone(local); delete (x.pending!.command.payload as ObservationPayload).confirmation_token;
  assert.equal(restoreFactLocal(x, x.identity), null);
});
test("saved receipt wins before parent read failure and removes original write", () => {
  const local = factSaved(unknown(), receipt); assert.equal(local.pending, null); assert.equal(local.outcome, "saved");
  const outcome = factFailure(local, Object.assign(new Error(), { status: 500 })); assert.equal(outcome.saved, true); assert.equal(outcome.local.pending, null);
  assert.deepEqual(restoreFactLocal({ ...local, pending: unknown().pending }, local.identity)?.savedReceipt, receipt);
});
test("401/403 clears private receipt and command while retaining only saved fact", () => {
  for (const status of [401, 403]) { const x = factFailure(factSaved(unknown(), receipt), Object.assign(new Error(), { status }));
    assert.equal(x.clearPrivate, true); assert.equal(x.saved, true); assert.equal(x.local.savedReceipt, null); assert.equal(x.local.pending, null); assert.equal(x.local.outcome, "saved"); }
});
test("ordinary conflict, confirmation expiry and timeout do not unlock UNKNOWN", () => {
  const local = unknown(); for (const error of [Object.assign(new Error(), { status: 409, code: "CONFIRMATION_REQUIRED" }),
    Object.assign(new Error(), { status: 409, code: "FOLLOWUP_CONFIRMATION_EXPIRED" }), new Error("timeout")]) {
    const failure = factFailure(local, error); assert.equal(failure.clearPrivate, false); assert.deepEqual(failure.local.pending, local.pending);
  }
});
test("cross-family receipt never turns an unresolved write into saved", () => {
  assert.throws(() => factSaved(unknown(), { ...receipt, subject_type: "quality_issue" } as unknown as FactReceipt));
  assert.throws(() => factSaved(unknown(), { ...receipt, operation: reviewOperation, subject_type: "capa_named_verification_review" }));
});
test("business review preserves原值 and microseconds and never infers effectiveness", () => {
  const c = command(), value = readFactBusinessReview(host(), preview().review, c)!; assert.ok(value?.complete);
  const rows = value.sections.flatMap(s => s.rows); assert.ok(rows.some(r => r.value === "11.0000")); assert.ok(rows.some(r => r.value === instant));
  assert.ok(rows.some(r => r.label === "有效性与关闭" && r.value?.includes("均未办理")));
  const bad = preview(); (bad.review.binding.body_material as unknown as Record<string, unknown>).records = [{ ...observation().records[0], raw_material: { raw_value: "12.0000" } }];
  assert.equal(readFactBusinessReview(host(), bad.review, c), null);
});
test("inspection gaps and three unknowns stay visible and absent material cannot unlock confirmation", () => {
  const v = preview(), inspection = v.review.inspection as Record<string, unknown>;
  inspection.independently_verified = null; inspection.missing = ["OBSERVATION_INTERVAL_INCOMPLETE"];
  const r = readFactBusinessReview(host(), v.review, command())!; assert.ok(r.complete);
  assert.equal(r.sections.flatMap(s => s.rows).filter(r => r.value === "尚不能确定，保持未知").length, 3);
  assert.ok(r.sections.flatMap(s => s.rows).some(r => r.value?.includes("完整观察期")));
  assert.equal(readFactBusinessReview({ ...host(), history: [] }, v.review, command()), null);
});

test("verified original record clocks copy whole microseconds and reject partial or unrelated evidence", () => {
  const h = host(), p = observation(), choice = { ...h.records[0], observed_from: p.observed_from, observed_until: p.observed_until, at: p.at };
  assert.deepEqual(factRecordTiming(choice), { observed_from: p.observed_from, observed_until: p.observed_until, at: p.at });
  const offset = { ...choice, at: { ...p.at, occurred_at: "2026-10-02T23:25:03.160086-07:00", original_timezone: "America/Los_Angeles" } };
  assert.equal(factRecordTiming(offset)?.at.occurred_at, offset.at.occurred_at);
  assert.equal(factRecordTiming({ ...choice, at: { ...p.at, source: { ...source, id: id(99) } } }), null);
  assert.equal(factRecordTiming({ ...choice, observed_until: undefined }), null);
  assert.equal(validFactHost({ ...h, records: [{ ...h.records[0], observed_from: p.observed_from }] }), false);
  assert.equal(validFactHost({ ...h, records: [offset] }), true);
});
test("long verified publication quote is bounded and retained without truncation", () => {
  const h = host(); h.sources[0].quote = "原".repeat(12000);
  assert.equal(validFactHost(h), true); assert.equal(selectFactSources(h, [factSourceKey(source)])[0].position, source.position);
  assert.equal(h.sources[0].quote.length, 12000);
  h.sources[0].quote = "原".repeat(20001); assert.equal(validFactHost(h), false);
});

test("actual canonical preview accepts only declared clock normalization and keeps returned command for recovery", () => {
  const c = command(), v = structuredClone(preview(c)), p = v.command.payload as ObservationPayload;
  p.observed_from = p.observed_from.replace("+00:00", "Z");
  p.observed_until = p.observed_until.replace("+00:00", "Z");
  p.at.occurred_at = p.at.occurred_at.replace("+00:00", "Z");
  p.records = structuredClone(p.records); p.records[0].occurred_at = p.records[0].occurred_at.replace("+00:00", "Z");
  v.review.payload_semantic = { ...p }; delete (v.review.payload_semantic as ObservationPayload).confirmation_token;
  const prepared = factPrepared(v, c); assert.ok(prepared);
  assert.deepEqual(prepared.command, v.command);
  const pending = factBegin(blankFactLocal(factIdentity(host())!), { stage: "execute", command: prepared.command });
  assert.deepEqual(restoreFactLocal(JSON.parse(JSON.stringify(pending)), pending.identity)?.pending?.command, v.command);
  assert.equal((prepared.command.payload as ObservationPayload).records[0].occurred_at, "2026-10-03T06:25:03.160086Z");
  assert.equal(c.payload.at.occurred_at, instant);
});
test("canonical preview still rejects a microsecond, source/quote hash, raw number or envelope drift", () => {
  const c = command();
  const mutations: ((v: ReturnType<typeof preview>) => void)[] = [
    v => { v.command.payload.at.occurred_at = "2026-10-03T06:25:03.160087Z"; },
    v => { v.command.payload.sources[0] = { ...source, id: id(99) }; },
    v => { v.command.payload.at.source = { ...source, position: `line:2;quote_sha256:${"f".repeat(64)}` }; },
    v => { (v.command.payload as ObservationPayload).records[0].raw_material = { ...observation().records[0].raw_material, raw_value: 11 }; },
    v => { (v.command.payload as ObservationPayload).records[0].raw_material = { ...observation().records[0].raw_material, raw_value: "11.0" }; },
    v => { v.command.source_read_set = [{ artifact_id: source.id, expected_revision: 2 }]; },
  ];
  for (const mutate of mutations) { const v = preview(); v.command.payload = structuredClone(v.command.payload); mutate(v);
    assert.equal(factPrepared(v, c), null); }
});
