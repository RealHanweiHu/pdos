import assert from "node:assert/strict";
import test from "node:test";
import { awareTimestamp, canonicalLifecycleTime, lifecycleCommand, lifecycleFailure, lifecycleScope, normalizeInventory, sameLifecycleValue, validLifecycleCandidate, validLifecyclePreview, validLifecycleReceipt, type LifecycleCommand } from "./original-lifecycle";

const raw = { id: "object-a", title: "未完成上传的合成原件", filename: "source.txt", revision: 3, registered: false, upload_state: "failed", parse_state: "not_requested", retention_until: "2026-10-01T10:00:00Z", manual_hold: false, disposition: "active", pending_intent_id: null, reference_count: 0, formal_history: false, coverage_complete: true, registration_state: "unregistered", byte_status: "present", reasons: [], can_quarantine: true, can_restore: false, can_record_protection: true, can_abandon_upload: true, upload_attempt_id: "attempt-a", upload_attempt_revision: 2, policy_version: "policy-a", intents: [{ id: "intent-a", revision: 1, action: "quarantine", state: "pending", created_at: "2026-10-02T10:00:00Z", updated_at: "2026-10-02T10:00:00Z", recovery_required: false, reason: "合成观察", can_cancel: true, can_reconcile: false }] };
const inventory = normalizeInventory({ items: [raw], policy: { version: "policy-a", profile: "local-synthetic", failed_upload_grace_seconds: 60, quarantine_grace_seconds: 120 }, coverage_complete: true });
const item = inventory.items[0], now = Date.parse("2026-10-02T10:01:00Z");
const candidate = { candidate_id: "candidate-a", action: "quarantine", object_id: item.id, digest: "a".repeat(64), eligible: true, reasons: [], captured_at: "2026-10-02T10:05:00Z", not_before: null, lifecycle_revision: item.revision };
const command = lifecycleCommand("product-a", 7, item, "evidence.lifecycle.quarantine", { candidate_id: candidate.candidate_id, digest: candidate.digest }, "具名核对合成隔离意图", "command-a", "key-a");
function prepared(original: LifecycleCommand = command) { return { command: { ...original, payload: { ...original.payload, confirmation_token: "server-confirmation-token" } }, expires_at: "2026-10-02T10:05:00Z", review: { before: { ...candidate }, after: { action: "quarantine", status: "pending", reason: original.payload.reason, physical_effect_applied: false }, effect: "只记录意图，不删除字节，不授予安全资格。" } }; }

test("unknown protection facts are preserved and absent capabilities never become permission", () => {
  const unknown = normalizeInventory({ items: [{ id: item.id, title: item.title, revision: 1 }], coverage_complete: false }).items[0];
  assert.equal(unknown.registered, null); assert.equal(unknown.manual_hold, null); assert.equal(unknown.reference_count, null); assert.equal(unknown.formal_history, null);
  assert.equal(unknown.can_quarantine, false); assert.equal(unknown.can_restore, false); assert.equal(unknown.can_record_protection, false); assert.equal(unknown.can_abandon_upload, false);
  assert.equal(normalizeInventory({ items: [{ ...raw, can_quarantine: "true", reference_count: "0", manual_hold: 0 }] }).items[0].can_quarantine, false);
  assert.equal(normalizeInventory({ items: [{ ...raw, reference_count: "0" }] }).items[0].reference_count, null);
});
test("a factual zero and known false remain distinct from unknown", () => { assert.equal(item.reference_count, 0); assert.equal(item.manual_hold, false); assert.equal(item.registered, false); assert.equal(inventory.policy?.profile, "local-synthetic"); });
test("intent actions require explicit capabilities rather than a guessed state", () => {
  const row = normalizeInventory({ items: [{ ...raw, intents: [{ id: "intent-a", revision: 1, state: "pending" }] }] }).items[0];
  assert.equal(row.intents[0].can_cancel, false); assert.equal(row.intents[0].can_reconcile, false);
  assert.throws(() => lifecycleCommand("product-a", 7, row, "evidence.lifecycle.cancel", { intent_id: "intent-a", expected_revision: 1 }, "取消理由", "c", "k"));
});
test("candidate identity, action, digest, version and aware time are exact", () => {
  assert.equal(validLifecycleCandidate(candidate, item, "quarantine"), true);
  for (const changes of [{ object_id: "object-b" }, { action: "restore" }, { digest: "broken" }, { lifecycle_revision: 2 }, { captured_at: "2026-10-02T10:05:00" }]) assert.equal(validLifecycleCandidate({ ...candidate, ...changes }, item, "quarantine"), false);
  assert.equal(validLifecycleCandidate({ ...candidate, eligible: false, reasons: ["registered_original"] }, item, "quarantine"), true);
});
test("confirmed command preserves identifiers, semantic payload and empty source read-set", () => {
  assert.equal(validLifecyclePreview(prepared(), command, item, now), true);
  for (const key of ["command_id", "idempotency_key", "product_id", "operation", "expected_revision"] as const) { const value = prepared(); Object.assign(value.command, { [key]: "changed" }); assert.equal(validLifecyclePreview(value, command, item, now), false); }
  const altered = prepared(); altered.command.source_read_set = [{ id: "arbitrary" }] as unknown as []; assert.equal(validLifecyclePreview(altered, command, item, now), false);
});
test("substantive confirmation cannot replace the object, reason or physical outcome", () => {
  for (const changes of [{ object_id: "other" }, { digest: "b".repeat(64) }, { eligible: false }]) { const value = prepared(); Object.assign(value.review.before, changes); assert.equal(validLifecyclePreview(value, command, item, now), false); }
  for (const changes of [{ physical_effect_applied: true }, { action: "restore" }, { status: "applied" }, { reason: "另一个理由" }]) { const value = prepared(); Object.assign(value.review.after, changes); assert.equal(validLifecyclePreview(value, command, item, now), false); }
});
test("expired previews, missing tokens and extra payload facts are not accepted", () => {
  assert.equal(validLifecyclePreview(prepared(), command, item, Date.parse("2026-10-02T10:06:00Z")), false);
  const missing = prepared(); missing.command.payload.confirmation_token = ""; assert.equal(validLifecyclePreview(missing, command, item, now), false);
  const extra = prepared(); Object.assign(extra.command.payload, { manual_hold: false }); assert.equal(validLifecyclePreview(extra, command, item, now), false);
});
test("human protection requires an explicit boolean, current version and aware retention", () => {
  assert.equal(awareTimestamp("2026-10-10T17:00:00-07:00"), true); assert.equal(awareTimestamp("2026-10-10T17:00:00"), false);
  assert.throws(() => lifecycleCommand("product-a", 7, item, "evidence.lifecycle.protection.record", { object_id: item.id, expected_revision: item.revision, manual_hold: null, retention_until: "2026-10-10T17:00:00-07:00" } as never, "核对期限", "c", "k"));
  assert.throws(() => lifecycleCommand("product-a", 7, item, "evidence.lifecycle.protection.record", { object_id: item.id, expected_revision: 2, manual_hold: false, retention_until: "2026-10-10T17:00:00-07:00" }, "核对期限", "c", "k"));
  const protection = lifecycleCommand("product-a", 7, item, "evidence.lifecycle.protection.record", { object_id: item.id, expected_revision: item.revision, manual_hold: true, retention_until: "2026-10-10T17:00:00-07:00" }, "核对期限", "c", "k");
  const result = { command: { ...protection, payload: { ...protection.payload, confirmation_token: "server-token" } }, expires_at: "2026-10-02T10:05:00Z", review: { before: { object_id: item.id, revision: item.revision, manual_hold: false, retention_until: raw.retention_until }, after: { object_id: item.id, revision: 4, manual_hold: true, retention_until: "2026-10-11T00:00:00+00:00", reason: protection.payload.reason }, effect: "记录保留事实，不执行物理动作。" } };
  assert.equal(validLifecyclePreview(result, protection, item, now), true);
});
test("an upload termination binds the exact upload reservation revision and real server review", () => {
  assert.throws(() => lifecycleCommand("product-a", 7, item, "evidence.lifecycle.upload.abandon", { object_id: item.id, expected_revision: 2 }, "终止吧", "c", "k"), /4–2000/);
  assert.throws(() => lifecycleCommand("product-a", 7, item, "evidence.lifecycle.upload.abandon", { object_id: item.id, expected_revision: 3 }, "终止未完成上传", "c", "k"));
  const abandon = lifecycleCommand("product-a", 7, item, "evidence.lifecycle.upload.abandon", { object_id: item.id, expected_revision: 2 }, "终止未完成上传", "c", "k");
  const result = { command: { ...abandon, payload: { ...abandon.payload, confirmation_token: "server-token" } }, expires_at: "2026-10-02T10:05:00Z", review: { before: { id: item.id, title: item.title, status: "reserved", revision: 2 }, after: { status: "abandoned", reason: abandon.payload.reason }, effect: "关闭未完成上传，字节仍保留。" } };
  assert.equal(validLifecyclePreview(result, abandon, item, now), true); result.review.after.status = "committed"; assert.equal(validLifecyclePreview(result, abandon, item, now), false);
});
test("protection preview accepts server UTC normalization but rejects a changed time or other semantics", () => {
  const protection = lifecycleCommand("product-a", 7, item, "evidence.lifecycle.protection.record", { object_id: item.id, expected_revision: item.revision, manual_hold: false, retention_until: "2026-10-10T17:00:00.123456-07:00" }, "核对真实保留期限", "c", "k");
  const result = { command: { ...protection, payload: { ...protection.payload, retention_until: "2026-10-11T00:00:00.123456Z", confirmation_token: "server-token" } }, expires_at: "2026-10-02T10:05:00Z", review: { before: { object_id: item.id, revision: item.revision, manual_hold: false, retention_until: raw.retention_until }, after: { object_id: item.id, revision: 4, manual_hold: false, retention_until: "2026-10-11T00:00:00.123456+00:00", reason: protection.payload.reason }, effect: "记录保留事实，不执行物理动作。" } };
  assert.equal(validLifecyclePreview(result, protection, item, now), true);
  assert.equal(canonicalLifecycleTime("2026-10-11T00:00:00.000000+00:00"), "2026-10-11T00:00:00Z");
  assert.equal(canonicalLifecycleTime("2026-10-11T00:00:00.1234567Z"), null);
  result.command.payload.retention_until = "2026-10-11T00:00:00.123457Z"; assert.equal(validLifecyclePreview(result, protection, item, now), false);
  result.command.payload.retention_until = "2026-10-11T00:00:00.123456Z"; result.review.after.retention_until = "2026-10-11T00:00:00.123457+00:00"; assert.equal(validLifecyclePreview(result, protection, item, now), false);
  result.review.after.retention_until = "2026-10-11T00:00:00.123456+00:00"; result.command.payload.reason = "不同的决定理由"; assert.equal(validLifecyclePreview(result, protection, item, now), false);
  assert.equal((protection.payload as { retention_until: string }).retention_until, "2026-10-10T17:00:00.123456-07:00");
});
test("object key order does not create scope changes; protection and authority changes do", () => {
  assert.equal(sameLifecycleValue({ a: 1, nested: { x: false, y: null } }, { nested: { y: null, x: false }, a: 1 }), true);
  assert.equal(sameLifecycleValue([1, 2], [2, 1]), false);
  const scope = lifecycleScope("product-a", 7, item); for (const changes of [{ revision: 4 }, { manual_hold: true }, { reference_count: null }, { coverage_complete: false }, { can_quarantine: false }]) assert.notEqual(lifecycleScope("product-a", 7, { ...item, ...changes }), scope);
  assert.notEqual(lifecycleScope("product-a", 8, item), scope);
});
test("receipts are checked against the actual operation and correct subject family", () => {
  const receipt = { id: "receipt-a", operation: command.operation, subject_id: "intent-b", subject_type: "original_lifecycle_intent" };
  assert.equal(validLifecycleReceipt(receipt, command, item), true); assert.equal(validLifecycleReceipt({ ...receipt, operation: "evidence.lifecycle.restore" }, command, item), false); assert.equal(validLifecycleReceipt({ ...receipt, subject_type: "uploaded_original" }, command, item), false);
  const abandon = lifecycleCommand("product-a", 7, item, "evidence.lifecycle.upload.abandon", { object_id: item.id, expected_revision: 2 }, "终止未完成上传", "c", "k");
  assert.equal(validLifecycleReceipt({ ...receipt, operation: abandon.operation, subject_type: "upload_attempt", subject_id: "attempt-a" }, abandon, item), true); assert.equal(validLifecycleReceipt({ ...receipt, operation: abandon.operation, subject_type: "upload_attempt", subject_id: "attempt-b" }, abandon, item), false);
});
test("storage paths, raw stack traces and untrusted server details never enter the error surface", () => { const error = lifecycleFailure({ status: 500, message: "Traceback storage_key secret/private", code: "UNKNOWN_SECRET" }); assert.doesNotMatch(error.message, /Traceback|storage_key|secret/); assert.match(error.message, /保留原请求/); assert.match(lifecycleFailure({ status: 403 }).message, /授权/); });
