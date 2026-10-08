import assert from "node:assert/strict";
import test from "node:test";
import {
  uiSchema, operations, tiers, parseModel, same, eventTime, eventTimezone, validReads,
  type Model, type Context, type Binding, type Operation, type HostCommand,
  type Inputs, type Prepared, type Receipt, type Capability, type ExpiredUnsaved, type ExpiryTransport,
} from "./ui-contract";
import {
  initialState, selectIssue, setDraft, startRead, acceptRead, readFailure, canPrepare, begin,
  acceptInputs, acceptPreview, confirm, requestFailure, resumeOriginal, acceptExpiredUnsaved,
  requestRepreview, cancelPreparation, acceptReceipt, outcomeLabel, type UiState,
} from "./ui-state";

// These are pure host DTO projections, not real professional/transaction/bytes attestations.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const NOW = Date.parse("2026-10-03T12:00:00Z");
const candidateOp = operations[0], observationOp = operations[1], reviewOp = operations[2];
const effectOp = operations[3], closeOp = operations[4];
const copy = <T>(x: T): T => structuredClone(x);
// Only tests inject this synthetic decoder; no real Wave17 transport is currently registered.
const testExpiryTransport: ExpiryTransport = { inspect: (_command, value) => value as ExpiredUnsaved };
const context: Context = { scope: { tenant_id: id(1), product_id: id(2), project_id: id(3) }, caller_id: id(4), product_revision: 10 };
function model(revision = 6): Model {
  const issueRef = { id: id(20 + revision), revision }, anchorRef = { id: id(50), revision: 1, sha256: "a".repeat(64) };
  const binding: Binding = { scope: context.scope, caller_id: context.caller_id, issue_id: id(6), issue_ref: issueRef,
    capa_id: id(7), purpose: "固定独立复验用途", anchor: anchorRef };
  const cap = (operation: Operation): Capability => ({ operation, binding, allowed: true,
    authority: { authorized: true, qualified: true, synthetic: true }, independence: "verified",
    current_evaluation: "evaluated_current", missing: [],
    required_source_read_set: [{ artifact_id: id(9), expected_revision: 1 }, { artifact_id: id(8), expected_revision: 2 }],
    receipt_subject_type: operation === effectOp || operation === closeOp ? "quality_issue" : "host_fixed_companion",
  });
  const caps: Model["operations"] = { [candidateOp]: cap(candidateOp), [observationOp]: cap(observationOp),
    [reviewOp]: cap(reviewOp), [effectOp]: cap(effectOp), [closeOp]: cap(closeOp) };
  return { schema_version: uiSchema, context: copy(context), issue: { issue_id: id(6), ref: issueRef,
    owner_id: id(5), visibility: "product", purpose: binding.purpose, status: "awaiting_verification",
    current_evaluation: "evaluated_current", source_status: "current" }, current_issue: issueRef,
    anchor: { ref: anchorRef, origin_issue: { id: id(26), revision: 6 }, issue_id: id(6), capa_id: id(7),
      scope: context.scope, owner_id: id(5), visibility: "product", purpose: binding.purpose, nature: "synthetic", source_status: "current" },
    late_links: [{ ref: { id: id(60), revision: 1, sha256: "b".repeat(64) }, issue_id: id(6), meaning: "planned",
      formal: { id: id(61), revision: 1 }, run: null, current_evaluation: "not_evaluated_historical", source_status: "current", missing: [] }],
    candidates: [{ ref: { id: id(62), revision: 1, sha256: "c".repeat(64) }, anchor: anchorRef,
      late_link: { id: id(60), revision: 1, sha256: "b".repeat(64) }, applicable: null,
      independently_verified: null, observation_complete: null, result: "indeterminate",
      current_evaluation: "evaluated_current", source_status: "current", missing: [{ code: "OBSERVATION_MISSING", detail: "实际观察尚缺" }] }],
    rule_publications: [{ ref: { id: id(63), revision: 1, sha256: "d".repeat(64) }, publication: "host_only",
      issuer_key: "local-owner", issuer_version: "1", issuer_epoch: 1, nature: "synthetic", source_status: "current",
      current_evaluation: "evaluated_current", valid_from: "2026-10-03T00:00:00Z", valid_until: "2026-10-04T00:00:00Z", missing: [] }],
    observations: [], reviews: [], effectiveness: null, operations: caps, missing: [] };
}
function loaded(m = model()): UiState {
  const state = startRead(initialState(m.context, m.issue.ref));
  return acceptRead(state, state.read_epoch, m);
}
function host(state: UiState, operation: Operation = candidateOp, n = 100): HostCommand {
  const cap = state.model!.operations[operation];
  return { schema_version: uiSchema, context: state.context!, binding: cap.binding,
    command: { command_id: id(n), idempotency_key: id(n + 100), product_id: id(2), expected_revision: state.context!.product_revision,
      operation, source_read_set: copy(cap.required_source_read_set),
      payload: { fixed_ref: { id: id(26), revision: 6 }, reason: "保留精确原材料",
        event: { occurred_at: "2026-10-03T06:25:03.160086+00:00", original_timezone: "America/Los_Angeles" },
        quantity: "22.00000000" } } };
}
const inputs = (h: HostCommand): Inputs => ({ schema_version: uiSchema, command: h.command, binding: h.binding,
  allowed: true, required_source_read_set: h.command.source_read_set, missing: [] });
function prepared(h: HostCommand, expires = "2026-10-03T12:10:00Z"): Prepared {
  const tier = tiers[h.command.operation];
  return { schema_version: uiSchema, command: { ...h.command, payload: { ...h.command.payload,
    [tier === "T2" ? "approval_token" : "confirmation_token"]: "opaque-server-token-not-a-UI-proof" } },
    binding: h.binding, expires_at: expires, write_tier: tier, named_decision: tier === "T2",
    review: { before: { revision: 6 }, after: { received_at: null, clock_basis: "server_on_save" }, effect: "本次保存固定事实，不自动决定有效性" } };
}
function executing(state = loaded(), operation: Operation = candidateOp, n = 100): UiState {
  const h = host(state, operation, n);
  return confirm(acceptPreview(acceptInputs(begin(state, h), inputs(h)), prepared(h), NOW), NOW);
}
function receipt(state: UiState): Receipt {
  return { id: id(400), operation: state.pending!.command.operation, subject_id: id(401),
    subject_revision: 7, subject_type: state.pending!.receipt_subject_type };
}

test("strict version/capability/null contract never fills absent facts", () => {
  assert.ok(parseModel(model()));
  for (const change of [
    (m: Model) => { (m as unknown as Record<string, unknown>).schema_version = "future"; },
    (m: Model) => { delete (m.operations as unknown as Record<string, unknown>)[effectOp]; },
    (m: Model) => { (m.operations[reviewOp].authority as unknown as Record<string, unknown>).qualified = "true"; },
    (m: Model) => { delete (m.candidates[0] as unknown as Record<string, unknown>).applicable; },
  ]) { const m = model(); change(m); assert.equal(parseModel(m), null); }
});
test("candidate three NULLs and indeterminate cannot become professional success", () => {
  for (const key of ["applicable", "independently_verified", "observation_complete"]) {
    for (const value of [true, false]) { const m = model(); (m.candidates[0] as unknown as Record<string, unknown>)[key] = value; assert.equal(parseModel(m), null); }
  }
  const m = model(); (m.candidates[0] as unknown as Record<string, unknown>).result = "pass";
  assert.equal(parseModel(m), null);
  assert.notEqual(outcomeLabel("unknown"), outcomeLabel("ineffective"));
  assert.notEqual(outcomeLabel("indeterminate"), outcomeLabel("ineffective"));
});
test("a peer product grant and even positive projected capability cannot independently act on old private Issue", () => {
  const m = model(); m.issue.visibility = "private"; m.anchor!.visibility = "private";
  let state = loaded(m);
  assert.equal(canPrepare(state, candidateOp), false);
  assert.equal(canPrepare(state, reviewOp), false);
  m.context.caller_id = id(5);
  for (const cap of Object.values(m.operations)) cap.binding.caller_id = id(5);
  state = loaded(m);
  assert.equal(canPrepare(state, candidateOp), true);
  for (const op of [reviewOp, effectOp, closeOp]) assert.equal(canPrepare(state, op), false);
});
test("unknown/false qualification, scope mismatch and absent anchor cannot grant a button", () => {
  for (const qualified of [null, false]) { const m = model(); m.operations[observationOp].authority.qualified = qualified; assert.equal(canPrepare(loaded(m), observationOp), false); }
  const m = model(); m.operations[reviewOp].binding = { ...m.operations[reviewOp].binding, purpose: "另一用途" };
  assert.equal(parseModel(m), null);
  const missing = model(); missing.anchor = null; assert.equal(canPrepare(loaded(missing), candidateOp), false);
});
test("history stays exact and readonly when a newer Current appears", () => {
  const m = model(); m.current_issue = { id: id(27), revision: 7 }; m.issue.current_evaluation = "not_evaluated_historical";
  for (const cap of Object.values(m.operations)) { cap.allowed = false; cap.current_evaluation = "not_evaluated_historical"; }
  const state = loaded(m);
  assert.deepEqual(state.selection, m.issue.ref);
  for (const op of operations) assert.equal(canPrepare(state, op), false);
  let read = startRead(state); read = acceptRead(read, read.read_epoch, model(7));
  assert.equal(read.notice, "selection_requires_explicit_choice");
  assert.deepEqual(read.selection, m.issue.ref);
});
test("old Draft link remains planned, and host-only Rule cannot be an artificial UI operation", () => {
  const state = loaded(); assert.equal(state.model!.late_links[0].meaning, "planned");
  assert.equal(state.model!.late_links[0].run, null);
  assert.equal(state.model!.rule_publications[0].publication, "host_only");
  assert.equal(operations.some(op => String(op).includes("rule")), false);
  const m = model(); (m.rule_publications[0] as unknown as Record<string, unknown>).publication = "manual_ui";
  assert.equal(parseModel(m), null);
});
test("original microseconds, offset and original IANA timezone survive command/preview/execute unchanged", () => {
  const iso = "2026-10-02T23:25:03.160086-07:00", zone = "America/Los_Angeles";
  assert.equal(eventTime(iso), iso); assert.equal(eventTimezone(zone), zone);
  assert.equal(eventTime("2026-10-03T06:25:03.160086"), null); assert.equal(eventTimezone("-07:00"), null);
  const state = loaded(), h = host(state); (h.command.payload.event as Record<string, string>).occurred_at = iso;
  const saved = confirm(acceptPreview(acceptInputs(begin(state, h), inputs(h)), prepared(h), NOW), NOW);
  assert.equal((saved.pending!.command.payload.event as Record<string, string>).occurred_at, iso);
  assert.equal((saved.pending!.command.payload.event as Record<string, string>).original_timezone, zone);
});
test("cloned immutable command preserves read order and values despite external mutation", () => {
  const state = loaded(), h = host(state), pending = begin(state, h);
  h.command.source_read_set.reverse(); h.command.payload.quantity = "0";
  (h.command.payload.event as Record<string, string>).occurred_at = "replaced";
  assert.equal(pending.pending!.command.source_read_set[0].artifact_id, id(9));
  assert.equal(pending.pending!.command.payload.quantity, "22.00000000");
  assert.equal((pending.pending!.command.payload.event as Record<string, string>).occurred_at, "2026-10-03T06:25:03.160086+00:00");
  assert.throws(() => { pending.pending!.command.payload.quantity = "changed"; }, TypeError);
});
test("complete reads reject truncation, duplicate identities and changed order", () => {
  assert.equal(validReads(Array.from({ length: 21 }, (_, i) => ({ artifact_id: id(500 + i), expected_revision: 1 }))), false);
  assert.equal(validReads([{ artifact_id: id(8), expected_revision: 1 }, { artifact_id: id(8), expected_revision: 2 }]), false);
  const state = loaded(), h = host(state); h.command.source_read_set.reverse();
  assert.equal(begin(state, h).pending, null);
});
test("inputs cannot change payload, target, complete reads or manufacture allowed", () => {
  const state = loaded(), h = host(state), waiting = begin(state, h);
  const changed = copy(inputs(h)); changed.command.payload.reason = "changed";
  assert.equal(acceptInputs(waiting, changed).pending!.mode, "inputs");
  const blocked = inputs(h); blocked.allowed = false;
  assert.equal(acceptInputs(waiting, blocked).pending, null);
  const missing = inputs(h); missing.required_source_read_set = [];
  assert.equal(acceptInputs(waiting, missing).notice, "invalid_host_material");
});
test("preview binds identity/key/payload/readset and exact tier, without generating professional conclusions", () => {
  const state = loaded(), h = host(state, reviewOp), waiting = acceptInputs(begin(state, h), inputs(h));
  for (const change of [
    (p: Prepared) => { p.command.idempotency_key = id(777); },
    (p: Prepared) => { p.command.source_read_set.reverse(); },
    (p: Prepared) => { p.command.payload.reason = "changed"; },
    (p: Prepared) => { p.write_tier = "T1"; },
    (p: Prepared) => { p.named_decision = false; },
  ]) { const p = copy(prepared(h)); change(p); assert.equal(acceptPreview(waiting, p, NOW).preview, null); }
  const ok = acceptPreview(waiting, prepared(h), NOW); assert.equal(ok.pending!.mode, "preview");
  assert.equal(ok.pending!.command.payload.approval_token, undefined);
});
test("an expired preview before any execute requires manual same-command repreview", () => {
  const state = loaded(), h = host(state), waiting = acceptPreview(acceptInputs(begin(state, h), inputs(h)), prepared(h), NOW);
  const expired = confirm(waiting, NOW + 11 * 60 * 1000);
  assert.equal(expired.pending!.mode, "expired_preview"); assert.equal(expired.last_outcome, "not_saved");
  assert.equal(resumeOriginal(expired), expired);
  const manual = requestRepreview(expired); assert.equal(manual.pending!.mode, "preview");
  assert.deepEqual(manual.pending!.command, h.command);
});
test("timeout, ordinary409 and old followup expiry code all keep UNKNOWN exact execute locked", () => {
  const executingState = executing();
  for (const error of [{ status: 500 }, { status: 409 }, { code: "FOLLOWUP_CONFIRMATION_EXPIRED", status: 409 }, {}]) {
    const failed = requestFailure(executingState, error);
    assert.equal(failed.pending!.mode, "execute"); assert.equal(failed.last_outcome, "unknown");
    assert.deepEqual(failed.pending!.command, executingState.pending!.command);
    assert.equal(selectIssue(failed, { id: id(27), revision: 7 }).selection!.id, id(26));
    assert.equal(cancelPreparation(failed).pending!.mode, "execute");
    assert.deepEqual(begin(failed, host(loaded(), observationOp, 300)).pending!.command, failed.pending!.command);
  }
});
test("recovery repeats only the original mode and does not add another ID/key/time", () => {
  const failed = requestFailure(executing(), {}), recovering = resumeOriginal(failed);
  assert.equal(recovering.pending!.recovery_attempt, true);
  assert.deepEqual(recovering.pending!.command, failed.pending!.command);
  assert.equal(recovering.preview, null);
});
test("only a bound host absence outcome on original execute recovery may unlock manual repreview", () => {
  const state = loaded(), h = host(state), unknown = requestFailure(executing(state), {});
  const notice = { schema_version: uiSchema, state: "not_saved_expired_proof" as const, command: h.command };
  assert.equal(acceptExpiredUnsaved(unknown, notice), unknown);
  assert.equal(acceptExpiredUnsaved(unknown, notice, testExpiryTransport), unknown);
  const recovering = resumeOriginal(unknown), changed = copy(notice); changed.command.source_read_set.reverse();
  assert.equal(acceptExpiredUnsaved(recovering, changed, testExpiryTransport), recovering);
  changed.command = copy(h.command); changed.command.payload.quantity = "23";
  assert.equal(acceptExpiredUnsaved(recovering, changed, testExpiryTransport), recovering);
  const unlocked = acceptExpiredUnsaved(recovering, notice, testExpiryTransport);
  assert.equal(unlocked.pending!.mode, "expired_preview"); assert.equal(unlocked.preview, null);
  assert.equal(unlocked.last_outcome, "not_saved");
  assert.deepEqual(requestRepreview(unlocked).pending!.command, h.command);
});
test("JSONB object-key order may differ, but recovery never normalizes event values or arrays", () => {
  assert.equal(same({ a: 1, b: 2 }, { b: 2, a: 1 }), true);
  const h = host(loaded()), recovering = resumeOriginal(requestFailure(executing(), {}));
  const changed = copy(h.command); (changed.payload.event as Record<string, string>).occurred_at = "2026-10-03T06:25:03.160000Z";
  assert.equal(acceptExpiredUnsaved(recovering, { schema_version: uiSchema, state: "not_saved_expired_proof", command: changed }, testExpiryTransport), recovering);
});
test("saved receipt dominates subsequent read/network failures and prevents re-execute", () => {
  const run = executing(), saved = acceptReceipt(run, receipt(run));
  assert.equal(saved.last_outcome, "saved"); assert.equal(saved.pending, null);
  const read = startRead(saved), failed = readFailure(read, read.read_epoch, {});
  assert.equal(failed.notice, "saved_read_failed"); assert.deepEqual(failed.savedReceipt, saved.savedReceipt);
  assert.equal(requestFailure(saved, { status: 500 }).notice, "saved_read_failed");
  assert.equal(resumeOriginal(saved), saved);
});
test("late original-key success after timeout wins over both refresh failure and any expiry notice", () => {
  const run = executing(), waiting = resumeOriginal(requestFailure(run, { status: 504 }));
  const saved = acceptReceipt(waiting, receipt(run));
  let inspected = false;
  const unchanged = acceptExpiredUnsaved(saved, {}, { inspect: () => { inspected = true; return null; } });
  assert.equal(unchanged, saved); assert.equal(inspected, false);
  const read = startRead(saved), failed = readFailure(read, read.read_epoch, { status: 500 });
  assert.equal(failed.last_outcome, "saved"); assert.equal(failed.pending, null);
  assert.equal(failed.notice, "saved_read_failed");
});
test("401/403 clears all sensitive state immediately, preserving only a saved/non-sensitive outcome", () => {
  for (const status of [401, 403]) {
    const run = executing(setDraft(loaded(), { private_quote: "private local draft" }));
    const saved = acceptReceipt(run, receipt(run)), denied = requestFailure(saved, { status });
    assert.equal(denied.context, null); assert.equal(denied.model, null); assert.equal(denied.selection, null);
    assert.equal(denied.draft, null); assert.equal(denied.preview, null); assert.equal(denied.pending, null);
    assert.equal(denied.savedReceipt, null); assert.deepEqual(denied.completed, []);
    assert.equal(denied.last_outcome, "saved"); assert.equal(denied.notice, "saved_scope_rejected");
    const unknown = requestFailure(run, { status }); assert.equal(unknown.pending, null); assert.equal(unknown.last_outcome, "unknown");
  }
});
test("unconfigured or failed expiry transport cannot unlock new operations UNKNOWN", () => {
  const recovering = resumeOriginal(requestFailure(executing(), {}));
  const notice = { schema_version: uiSchema, state: "not_saved_expired_proof" as const, command: host(loaded()).command };
  assert.equal(acceptExpiredUnsaved(recovering, notice), recovering);
  assert.equal(acceptExpiredUnsaved(recovering, notice, { inspect: () => null }), recovering);
  assert.equal(acceptExpiredUnsaved(recovering, notice, { inspect: () => { throw new Error("Not configured"); } }), recovering);
});
test("same-lifetime denied read clears private state even if a newer read epoch began", () => {
  const first = startRead(setDraft(loaded(), { private_quote: "must clear" })), second = startRead(first);
  const denied = readFailure(second, first.read_epoch, { status: 403 });
  assert.equal(denied.context, null); assert.equal(denied.draft, null); assert.equal(denied.model, null);
  assert.equal(denied.loading, false);
});
test("stale reads cannot clear a newer loading epoch; current cancellation ends loading and disables writes", () => {
  const first = startRead(loaded()), second = startRead(first);
  assert.equal(readFailure(second, first.read_epoch, { code: "READ_SUPERSEDED" }), second);
  assert.equal(acceptRead(second, first.read_epoch, model()), second);
  const canceled = readFailure(second, second.read_epoch, { code: "READ_SUPERSEDED" });
  assert.equal(canceled.loading, false); assert.equal(canceled.read_failed, true); assert.equal(canPrepare(canceled, candidateOp), false);
});
test("performing takes the read epoch and ends old loading without changing original recovery material", () => {
  const state = loaded(), h = host(state), start = begin(state, h), reading = startRead(start);
  const ready = acceptInputs(reading, inputs(h)), reviewed = acceptPreview(ready, prepared(h), NOW);
  // Reads must finish before confirmation. Once clear, execute invalidates prior read epoch.
  const clear = readFailure(reviewed, reviewed.read_epoch, {}); assert.equal(confirm(clear, NOW).pending!.mode, "preview");
  const normal = executing(state); assert.equal(normal.loading, false);
  assert.equal(acceptRead(normal, state.read_epoch, model()), normal);
});
test("changed Product watermark invalidates prepared approval and never rewrites original command", () => {
  const state = loaded(), h = host(state, reviewOp), waiting = acceptPreview(acceptInputs(begin(state, h), inputs(h)), prepared(h), NOW);
  const m = model(); m.context.product_revision = 11;
  const reading = startRead(waiting), refreshed = acceptRead(reading, reading.read_epoch, m);
  assert.equal(refreshed.context!.product_revision, 11); assert.equal(refreshed.preview, null);
  assert.equal(refreshed.pending!.command.expected_revision, 10);
});
test("receipt family or revision mismatch leaves exact request UNKNOWN", () => {
  const run = executing(), wrong = receipt(run); wrong.subject_type = "quality_issue";
  const state = acceptReceipt(run, wrong); assert.equal(state.last_outcome, "unknown"); assert.equal(state.pending!.mode, "execute");
  wrong.subject_type = run.pending!.receipt_subject_type; wrong.subject_revision = 0;
  assert.equal(acceptReceipt(run, wrong).savedReceipt, null);
});
test("effectiveness and close require separate explicit commands; ineffective cannot become close", () => {
  const state = loaded(); assert.equal(canPrepare(state, effectOp), true); assert.equal(canPrepare(state, closeOp), false);
  const effectRun = executing(state, effectOp), saved = acceptReceipt(effectRun, receipt(effectRun));
  assert.equal(saved.pending, null); assert.equal(saved.preview, null);
  const next = model(7); next.context.product_revision = 11;
  next.effectiveness = { issue_ref: next.issue.ref, actor_id: context.caller_id, outcome: "effective" };
  let selected = selectIssue(saved, next.issue.ref); selected = startRead(selected); selected = acceptRead(selected, selected.read_epoch, next);
  assert.equal(canPrepare(selected, closeOp), true); assert.equal(canPrepare(selected, effectOp), false);
  assert.equal(begin(selected, host(selected, closeOp, 100)).pending, null); // Reused original command/key.
  const close = begin(selected, host(selected, closeOp, 301)); assert.equal(close.pending!.mode, "inputs");
  assert.notEqual(close.pending!.command.command_id, effectRun.pending!.command.command_id);
  next.effectiveness.outcome = "ineffective"; assert.equal(canPrepare(loaded(next), closeOp), false);
  next.effectiveness.outcome = "effective"; next.effectiveness.actor_id = id(99);
  assert.equal(canPrepare(loaded(next), closeOp), false);
});
