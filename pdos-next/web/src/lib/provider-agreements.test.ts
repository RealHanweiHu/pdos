import test from "node:test";
import assert from "node:assert/strict";
import { agreementPendingKey, matchAgreementReceipt, parseAgreementPending, validateAgreement, type AgreementRequest, type AgreementReceipt } from "./provider-agreements";

const original: AgreementRequest = { provider: "synthetic-provider", expected_revision: 2,
  signed_on: "2026-10-01T00:00:00.000Z", expires_at: "2026-11-01T00:00:00.000Z",
  data_categories: ["customer_original"], retention_terms: "合成协议：保留三十天", training_terms: "合成协议：不用于训练",
  active: true, decision: "批准", idempotency_key: "original-approved-key" };
const receipt: AgreementReceipt = { id: "receipt", category_id: "category", operation: "provider.agreement.register",
  subject_type: "provider_agreement", subject_id: "agreement", subject_revision: 3, writer_id: "human",
  requester_id: "human", agent_run_id: null, result: { provider: original.provider, revision: 3, tier: "T2", decided_by: "human", decision: "批准" } };

test("expired approved originals remain exact recovery inputs, with scope-owned storage", () => {
  assert.deepEqual(parseAgreementPending(JSON.stringify(original)), original);
  assert.ok(validateAgreement(original, Date.parse("2026-12-01T00:00:00Z")));
  assert.notEqual(agreementPendingKey("human", "a"), agreementPendingKey("human", "b"));
  assert.notEqual(agreementPendingKey("human", "a"), agreementPendingKey("peer", "a"));
  for (const value of [null, {}, { ...original, decision: "AI批准" }, { ...original, tenant_id: "forged" }, { ...original, data_categories: ["__proto__"] }, { ...original, expected_revision: "2" }]) assert.throws(() => parseAgreementPending(JSON.stringify(value)));
});

test("only a same-person same-category provider revision receipt clears an unknown request", () => {
  assert.ok(matchAgreementReceipt(receipt, original, "human", "category"));
  for (const changed of [{ category_id: "other" }, { writer_id: "ai" }, { requester_id: "peer" }, { agent_run_id: "run" }, { subject_revision: 4 }, { operation: "other" }, { result: { ...receipt.result, provider: "different" } }, { result: { ...receipt.result, tier: "T1" } }]) assert.equal(matchAgreementReceipt({ ...receipt, ...changed }, original, "human", "category"), false);
});

test("registration dates, explicit data categories and provider metadata must be reviewable", () => {
  const instant = Date.parse("2026-10-16T00:00:00Z");
  assert.equal(validateAgreement(original, instant), null);
  for (const changed of [{ provider: " " }, { data_categories: [] }, { retention_terms: " " }, { training_terms: " " }, { signed_on: "invalid" }, { signed_on: "2026-12-01T00:00:00Z" }, { expires_at: original.signed_on }, { expected_revision: 0.5 }]) assert.ok(validateAgreement({ ...original, ...changed }, instant));
});

test("cache choices survive recovery exactly and must match the named receipt", () => {
  for (const choice of [true, false, null]) {
    const request = { ...original, prompt_cache_allowed: choice };
    assert.deepEqual(parseAgreementPending(JSON.stringify(request)), request);
    const same = { ...receipt, result: { ...receipt.result, prompt_cache_allowed: choice } };
    assert.equal(matchAgreementReceipt(same, request, "human", "category"), true);
    assert.equal(matchAgreementReceipt({ ...same, result: { ...same.result, prompt_cache_allowed: choice === true ? false : true } }, request, "human", "category"), false);
  }
  assert.equal(matchAgreementReceipt(receipt, { ...original, prompt_cache_allowed: null }, "human", "category"), true);
  assert.equal(matchAgreementReceipt(receipt, { ...original, prompt_cache_allowed: true }, "human", "category"), false);
  assert.equal(matchAgreementReceipt(receipt, { ...original, prompt_cache_allowed: false }, "human", "category"), false);
});

test("cache permission uses a strict choice rather than coercing retention text", () => {
  const instant = Date.parse("2026-10-16T00:00:00Z");
  for (const choice of [0, 1, "true", "false", "禁止缓存", {}, []]) {
    const invalid = { ...original, prompt_cache_allowed: choice } as AgreementRequest;
    assert.ok(validateAgreement(invalid, instant));
    assert.throws(() => parseAgreementPending(JSON.stringify(invalid)));
  }
  assert.equal(validateAgreement({ ...original, prompt_cache_allowed: true, retention_terms: "禁止缓存的原始条款，管理员另行核对" }, instant), null);
});
