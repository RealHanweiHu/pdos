import assert from "node:assert/strict";
import test from "node:test";
import { blankCandidateDraft, blankKnowledgeLocal, candidateOperation, knowledgeBindingCurrent, knowledgeDraftCurrent, knowledgePrepared, knowledgePreviewCurrent, knowledgeSemantic, knowledgeStorageKey, newKnowledgeCommand, parseKnowledgePayload, parseKnowledgeView, publishRuleDraft, restoreKnowledgeLocal, reviseCandidateDraft, reviseRuleDraft, ruleOperation, runKnowledgeRequest, validKnowledgeCommand, type CandidateDraft, type CandidatePayload, type KnowledgeCandidate, type KnowledgeCommand, type KnowledgePending, type KnowledgeRule, type KnowledgeScope, type KnowledgeView, type RuleDraft, type RulePayload } from "./knowledge-experience";
import type { ProjectWorkApi } from "./project-work";

// The transport and source metadata below are explicit substitutes. These checks
// establish client boundaries and recovery, not actual qualification or receipts.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope: KnowledgeScope = { categoryId: id(1), productId: id(2), projectId: "", principalId: id(4) }, at = "2030-10-17T12:00:00.123456Z";
const source = { kind: "artifact" as const, id: id(5), revision: 1, position: "line:1;quote_sha256:" + "a".repeat(64) }, configuration = { kind: "engineering_configuration" as const, id: id(8), revision: 2, name: "实际工程配置" };
function candidate(): KnowledgeCandidate { return { id: id(6), version_id: id(16), revision: 2, project_id: id(3), owner_id: id(9), visibility: "category", title: "合成材料经验", lesson: "材料切换前核对原件", evidence_summary: "原结果的实际资料摘要", applicability_hypothesis: "仅为候选假设，待实际配置评估", sources: [source], result_receipts: [{ receipt_id: id(10) }], author_id: id(11), origin: "ai", created_at: at, can_revise: true, history: [{ id: id(16), revision: 2, actor_id: id(11), created_at: at, receipt_id: id(12) }] }; }
function rule(): KnowledgeRule { return { id: id(20), version_id: id(21), revision: 1, project_id: id(3), owner_id: id(9), visibility: "category", title: "固定配置经验规则", rule_text: "本配置在指定用途下按实际原件核对", nature: "synthetic", candidate: { id: id(6), revision: 2 }, candidate_version_id: id(16), applicability: { target: { kind: configuration.kind, id: configuration.id, revision: 2 }, purpose: "指定试制批次的内部核对", differences: ["固定材料牌号的差异"], adopted_rule: "采用核对后配置规则", conditions: ["仅对本轮试制适用"], decision: "applicable", rationale: "本人核对固定候选与目标配置", valid_from: at, valid_until: null, candidate_version: { id: id(16), revision: 2 }, assessor_id: scope.principalId, withdrawal_reason: null }, usability: { state: "needs_recheck", reason_codes: ["source_changed"] }, sources: [source], author_id: scope.principalId, created_at: at, can_revise: true, history: [{ id: id(21), revision: 1, actor_id: scope.principalId, created_at: at, receipt_id: id(22) }] }; }
function view(): KnowledgeView { return { product_revision: 3, projects: [{ id: id(3), revision: 1, name: "实际合成项目", owner_id: id(9), visibility: "category" }], configurations: [{ ...configuration }], candidates: [candidate()], rules: [rule()], as_of: at }; }
function candidateDraft(): CandidateDraft { return { ...blankCandidateDraft(scope), title: "待评估经验", lesson: "固定原件经验", evidence_summary: "实际证据摘要", applicability_hypothesis: "适用范围仍待核对", sources: JSON.stringify([source]), reason: "登记候选" }; }
function ruleDraft(): RuleDraft { return { ...publishRuleDraft(candidate(), scope), rule_text: "适用于本配置的具体规则", target: { kind: configuration.kind, id: configuration.id, revision: 2 }, purpose: "本轮固定配置的指定用途", differences: "材料来源有所差异\n批次已固定", adopted_rule: "采用实际固定规则", conditions: "本轮合成验证", decision: "applicable", rationale: "本人核对实际原件及配置差异", valid_from: at, valid_until: "2031-01-01T00:00:00Z", reason: "具名正式发布" }; }
const command = (isRule = false) => newKnowledgeCommand(scope, view(), isRule ? ruleDraft() : candidateDraft());
const inputs = (c: KnowledgeCommand) => ({ payload: knowledgeSemantic(c.operation, c.payload), required_source_read_set: c.source_read_set, review: { before: null, after: c.payload } });
const preview = (c: KnowledgeCommand) => ({ command: { ...structuredClone(c), payload: { ...structuredClone(c.payload), approval_token: "actual-common-approval-substitute" } }, approval_token: "actual-common-approval-substitute", expires_at: null, write_tier: "T2", named_decision: true, review: inputs(c).review });
function receipt(c: KnowledgeCommand) { const p = c.payload as RulePayload & CandidatePayload, previous = c.operation === candidateOperation ? p.candidate : p.rule, actual = id(30); return { id: id(31), operation: c.operation, subject_type: c.operation === candidateOperation ? "knowledge_candidate" : "design_rule", subject_id: actual, subject_revision: (previous?.revision ?? 0) + 1, result: { id: actual, revision: (previous?.revision ?? 0) + 1, status: c.operation === candidateOperation ? "draft" : "published", project_id: p.project_id ?? null, ...(c.operation === candidateOperation ? { candidate_id: previous?.id ?? actual } : { rule_id: previous?.id ?? actual, assessment_id: id(32) }) } }; }

test("candidate is a T0 draft and records no fabricated qualification, author, origin or standard", () => {
  const c = command(); assert.equal(c.operation, candidateOperation); assert.equal(c.payload.project_id, null); assert.equal("approval_token" in c.payload, false); assert.equal("origin" in c.payload, false); assert.equal("author_id" in c.payload, false); assert.deepEqual((c.payload as CandidatePayload).result_receipts, []);
  for (const key of ["approved", "origin", "author_id", "standard", "approval_token", "confirmation_token"]) assert.throws(() => parseKnowledgePayload({ ...c.payload, [key]: true }, candidateOperation, scope));
});
test("actual candidate and rule history, fixed candidate version, authorship and usability survive reads", () => {
  const actual = parseKnowledgeView(view(), scope); assert.equal(actual.candidates[0].origin, "ai"); assert.equal(actual.candidates[0].author_id, id(11)); assert.equal(actual.rules[0].applicability.assessor_id, scope.principalId); assert.equal(actual.rules[0].usability.state, "needs_recheck"); assert.equal(actual.rules[0].applicability.valid_until, null);
  for (const key of ["projects", "configurations", "candidates", "rules"]) assert.throws(() => parseKnowledgeView({ ...view(), [key]: undefined }, scope));
  assert.throws(() => parseKnowledgeView({ ...view(), candidates: [{ ...candidate(), history: [] }] }, scope)); assert.throws(() => parseKnowledgeView({ ...view(), rules: [{ ...rule(), applicability: { ...rule().applicability, candidate_version: { id: id(99), revision: 2 } } }] }, scope));
  assert.equal(parseKnowledgeView({ ...view(), candidates: [], rules: [] }, scope).rules.length, 0);
});
test("candidate revision preserves scope and exact current version; an arbitrary project cannot be invented", () => {
  const row = candidate(), draft = reviseCandidateDraft(row, scope); assert.deepEqual(draft.candidate, { id: row.id, revision: 2 }); assert.equal(draft.visibility, row.visibility); assert.equal(draft.project_id, row.project_id); assert.throws(() => reviseCandidateDraft({ ...row, can_revise: false }, scope));
  const v = view(); v.candidates[0].revision++; assert.equal(knowledgeDraftCurrent(draft, v, scope), false);
  assert.throws(() => newKnowledgeCommand(scope, view(), { ...candidateDraft(), project_id: id(99) }), /已变化/);
});
test("rule drafting uses actual readable materials without inferring publication qualification from the project owner", () => {
  const draft = publishRuleDraft(candidate(), scope); assert.equal(draft.decision, "unknown"); assert.equal(draft.target, null); assert.deepEqual(draft.candidate, { id: id(6), revision: 2 }); assert.notEqual(view().projects[0].owner_id, scope.principalId);
  assert.equal(command(true).operation, ruleOperation); const revised = reviseRuleDraft(rule(), candidate(), scope); assert.deepEqual(revised.rule, { id: id(20), revision: 1 }); assert.throws(() => reviseRuleDraft({ ...rule(), can_revise: false }, candidate(), scope));
});
test("unknown, conflicting and inapplicable assessments cannot become formal rules", () => {
  const p = command(true).payload as RulePayload;
  for (const decision of ["unknown", "conflicted", "not_applicable"] as const) assert.throws(() => parseKnowledgePayload({ ...p, applicability: { ...p.applicability, decision } }, ruleOperation, scope), /不能正式发布/);
  for (const applicability of [{ ...p.applicability, valid_from: "2030-10-17T12:00" }, { ...p.applicability, valid_until: p.applicability.valid_from }, { ...p.applicability, target: { ...p.applicability.target, qualified: true } }, { ...p.applicability, assessor_id: scope.principalId }, { ...p.applicability, purpose: " " }]) assert.throws(() => parseKnowledgePayload({ ...p, applicability }, ruleOperation, scope));
});
test("actual artifact and unique result receipt references are mandatory where declared", () => {
  const p = command().payload as CandidatePayload;
  for (const bad of [{ ...p, sources: [] }, { ...p, sources: [{ ...source, kind: "spec" }] }, { ...p, result_receipts: [{ receipt_id: id(10) }, { receipt_id: id(10) }] }, { ...p, result_receipts: [{ receipt_id: "unknown" }] }]) assert.throws(() => parseKnowledgePayload(bad, candidateOperation, scope));
  assert.throws(() => newKnowledgeCommand(scope, view(), { ...candidateDraft(), sources: JSON.stringify([source, { ...source, revision: 2 }]) }), /两个版本/);
});
test("fixed project context cannot silently switch to another project or an unscoped candidate", () => {
  const fixed = { ...scope, projectId: id(3) }; assert.equal(blankCandidateDraft(fixed).project_id, id(3)); assert.throws(() => parseKnowledgePayload(command().payload, candidateOperation, fixed)); assert.throws(() => parseKnowledgeView({ ...view(), rules: [{ ...rule(), project_id: id(99) }] }, fixed)); assert.notEqual(knowledgeStorageKey(fixed), knowledgeStorageKey(scope));
});
test("candidate inputs are persisted before one T0 save with no preview or confirmation", async () => {
  const c = command(), calls: string[] = [], stages: KnowledgePending[] = []; const result = await runKnowledgeRequest(async <T>(route: string) => { calls.push(route); return (route.endsWith("/inputs") ? inputs(c) : receipt(c)) as T; }, { stage: "inputs", command: c }, scope, value => stages.push(value), () => true);
  assert.equal(result?.stage, "saved"); assert.deepEqual(calls, [`v1/categories/${scope.categoryId}/products/${scope.productId}/experience/inputs`, `v1/categories/${scope.categoryId}/commands`]); assert.equal(stages[0].stage, "execute"); assert.equal("approval_token" in stages[0].command.payload, false);
});
test("rule inputs and actual common T2 preview stop before an explicit human confirmation", async () => {
  const c = command(true), calls: string[] = [], stages: KnowledgePending[] = []; const result = await runKnowledgeRequest(async <T>(route: string) => { calls.push(route); return (route.endsWith("/inputs") ? inputs(c) : preview(c)) as T; }, { stage: "inputs", command: c }, scope, value => stages.push(value), () => true);
  assert.equal(result?.stage, "preview"); assert.equal(stages[0].stage, "preview"); assert.equal(calls.length, 2); assert.ok(calls[1].endsWith("/commands/preview")); assert.equal(calls.some(value => value.endsWith("/commands")), false); assert.equal((result?.stage === "preview" ? result.prepared.command.payload as RulePayload : null)?.approval_token, "actual-common-approval-substitute");
});
test("server material inputs may normalize DTOs but cannot replace candidate, rule, target, purpose or source", async () => {
  const c = command(true), p = c.payload as RulePayload;
  for (const changed of [{ ...p, candidate: { ...p.candidate, revision: 3 } }, { ...p, rule: { id: id(20), revision: 1 } }, { ...p, project_id: id(99) }, { ...p, applicability: { ...p.applicability, target: { ...p.applicability.target, revision: 3 } } }, { ...p, applicability: { ...p.applicability, purpose: "另一用途" } }, { ...p, sources: [{ ...source, revision: 2 }] }]) { let count = 0; await assert.rejects(runKnowledgeRequest(async <T>() => { count++; return { ...inputs(c), payload: changed } as T; }, { stage: "inputs", command: c }, scope, () => assert.fail(), () => true)); assert.equal(count, 1); }
});
test("actual T2 preview checks the original command, real approval token and server expiry", () => {
  const c = command(true); assert.ok(knowledgePrepared(preview(c), c, scope));
  for (const key of ["command_id", "idempotency_key", "expected_revision", "source_read_set"] as const) { const value = preview(c); Object.assign(value.command, { [key]: key === "expected_revision" ? 4 : key === "source_read_set" ? [] : id(99) }); assert.equal(knowledgePrepared(value, c, scope), null); }
  const wrongToken = preview(c); delete (wrongToken.command.payload as RulePayload).approval_token; Object.assign(wrongToken.command.payload, { confirmation_token: "wrong-T1-token-substitute" }); assert.equal(knowledgePrepared(wrongToken, c, scope), null);
  assert.equal(knowledgePrepared({ ...preview(c), expires_at: "2000-01-01T00:00:00Z" }, c, scope), null); assert.equal(knowledgePrepared(preview(command()), command(), scope), null);
});
test("T2 null expiry means no server deadline while missing, malformed and expired finite deadlines fail", () => {
  const c = command(true), raw = preview(c), parsed = knowledgePrepared(raw, c, scope); assert.ok(parsed); assert.equal(parsed.expires_at, null); assert.equal(parsed.write_tier, "T2"); assert.equal(parsed.named_decision, true); assert.equal(knowledgePreviewCurrent(parsed, Date.parse("2100-01-01T00:00:00Z")), true); assert.deepEqual(parsed.command, raw.command);
  const finite = knowledgePrepared({ ...raw, expires_at: "2099-01-01T00:00:00Z" }, c, scope, Date.parse("2098-01-01T00:00:00Z")); assert.ok(finite); assert.equal(knowledgePreviewCurrent(finite, Date.parse("2098-01-01T00:00:00Z")), true); assert.equal(knowledgePreviewCurrent(finite, Date.parse("2099-01-01T00:00:00Z")), false); assert.equal(knowledgePreviewCurrent(finite, Date.parse("2100-01-01T00:00:00Z")), false);
  const missing: Record<string, unknown> = { ...raw }; delete missing.expires_at; assert.equal(knowledgePrepared(missing, c, scope), null);
  for (const expires_at of [undefined, "", "wrong", 0, false, "2099-01-01T00:00"]) assert.equal(knowledgePrepared({ ...raw, expires_at }, c, scope), null);
  assert.equal(knowledgePrepared({ ...raw, expires_at: "2099-01-01T00:00:00Z" }, c, scope, Date.parse("2099-01-01T00:00:00Z")), null);
});
test("formal preview must explicitly identify the actual T2 named-decision boundary", () => {
  const c = command(true), raw = preview(c);
  for (const changed of [{ ...raw, write_tier: undefined }, { ...raw, write_tier: "T1" }, { ...raw, named_decision: undefined }, { ...raw, named_decision: false }, { ...raw, named_decision: "true" }]) assert.equal(knowledgePrepared(changed, c, scope), null);
});
test("candidate, rule and actual target configuration drift invalidate the old publication without retargeting", () => {
  const c = command(true), p = c.payload;
  for (const mutate of [(v: KnowledgeView) => { v.candidates[0].revision++; }, (v: KnowledgeView) => { v.configurations[0].revision++; }, (v: KnowledgeView) => { v.projects = []; }]) { const v = view(); mutate(v); assert.equal(knowledgeBindingCurrent(p, ruleOperation, v, scope), false); }
  const revised = reviseRuleDraft(rule(), candidate(), scope), v = view(); v.rules[0].revision++; assert.equal(knowledgeDraftCurrent(revised, v, scope), false);
});
for (const isRule of [false, true]) test(`${isRule ? "rule" : "candidate"} unknown save restores purely and explicitly replays exact original command and key`, async () => {
  const c = isRule ? preview(command(true)).command : command(), original = structuredClone(c), calls: unknown[] = []; let lost = true; const pending: KnowledgePending = { stage: "execute", command: c };
  const api: ProjectWorkApi = async <T>(_route: string, body?: unknown) => { calls.push(body); if (lost) { lost = false; throw new Error("synthetic response lost"); } return receipt(c) as T; };
  await assert.rejects(runKnowledgeRequest(api, pending, scope, () => assert.fail(), () => true)); const saved = restoreKnowledgeLocal({ ...blankKnowledgeLocal(scope), pending }, scope); assert.ok(saved?.pending); assert.equal(calls.length, 1); assert.equal((await runKnowledgeRequest(api, saved.pending, scope, () => assert.fail(), () => true))?.stage, "saved"); assert.deepEqual(calls, [original, original]);
});
test("formal receipt needs the actual matching rule version, scope and applicability assessment UUID", async () => {
  const c = preview(command(true)).command;
  for (const bad of [{ ...receipt(c), subject_type: "knowledge_candidate" }, { ...receipt(c), result: { ...receipt(c).result, rule_id: id(99) } }, { ...receipt(c), result: { ...receipt(c).result, project_id: id(99) } }, { ...receipt(c), result: { ...receipt(c).result, assessment_id: null } }, { ...receipt(c), result: { ...receipt(c).result, revision: 2 } }]) await assert.rejects(runKnowledgeRequest(async <T>() => bad as T, { stage: "execute", command: c }, scope, () => assert.fail(), () => true), /回执尚未核实/);
});
test("DTO strip, UUID spelling, nullable defaults and equivalent timezones normalize only semantic comparison", () => {
  const c = command(true), p = c.payload as RulePayload, alpha = "abcdefab-1234-4000-8000-abcdefabcdef", raw = { ...p, title: ` ${p.title} `, rule: null, applicability: { ...p.applicability, valid_from: "2030-10-17T20:00:00.123456+08:00" } }; assert.deepEqual(knowledgeSemantic(ruleOperation, parseKnowledgePayload(raw, ruleOperation, scope)), knowledgeSemantic(ruleOperation, p));
  const normalized = parseKnowledgePayload({ ...command().payload, candidate: { id: alpha.toUpperCase(), revision: 2 }, result_receipts: [{ receipt_id: ` ${alpha.toUpperCase()} ` }] }, candidateOperation, scope) as CandidatePayload; assert.equal(normalized.candidate?.id, alpha); assert.equal(normalized.result_receipts[0].receipt_id, alpha);
});
test("scope/stage recovery, persistence failure and stale callbacks cannot cross into a later write", async () => {
  const c = command(true), local = { ...blankKnowledgeLocal(scope), pending: { stage: "preview", command: c } }; assert.ok(restoreKnowledgeLocal(local, scope));
  for (const key of ["principalId", "categoryId", "productId", "projectId"] as const) { const other = { ...scope, [key]: id(99) }; assert.equal(restoreKnowledgeLocal(local, other), null); assert.notEqual(knowledgeStorageKey(scope), knowledgeStorageKey(other)); }
  assert.equal(restoreKnowledgeLocal({ ...local, pending: { stage: "execute", command: c } }, scope), null); assert.equal(validKnowledgeCommand({ ...c, source_read_set: [] }, scope), false);
  let count = 0; await assert.rejects(runKnowledgeRequest(async <T>() => { count++; return inputs(c) as T; }, { stage: "inputs", command: c }, scope, () => { throw new Error("storage unavailable"); }, () => true), /storage unavailable/); assert.equal(count, 1);
  let active = true; assert.equal(await runKnowledgeRequest(async <T>() => { active = false; return inputs(c) as T; }, { stage: "inputs", command: c }, scope, () => assert.fail(), () => active), null);
});
