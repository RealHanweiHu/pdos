import assert from "node:assert/strict";
import test from "node:test";
import { blankRiskLocal, canRecordRisk, newRiskCommand, parseProjectRiskView, parseRiskPayload, restoreRiskLocal, riskDraft, riskDraftCurrent, riskFollowupOperation, riskPrepared, riskSemantic, riskStorageKey, runRiskRequest, validRiskCommand, type ProjectRisk, type ProjectRiskView, type RiskCommand, type RiskPending } from "./project-risks";
import type { ProjectWorkApi, WorkScope } from "./project-work";

// Synthetic transport and source metadata exercise client recovery, not server
// authorization, database atomicity or the existence of the claimed original.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope: WorkScope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) }, at = "2030-10-17T12:00:00Z";
const source = { kind: "artifact" as const, id: id(5), revision: 1, position: "line:1;quote_sha256:" + "a".repeat(64) };
function row(): ProjectRisk { return { id: id(6), decision_id: id(7), title: "G0 原风险", note: "原具名跟进事项", responsible_id: scope.principalId, due_date: "2030-10-17", source: { kind: "question", id: id(8) }, state: "open", current: null, summary: null, can_record: true, blocked: null, history: [], task: { id: id(9), revision: 6, state: "completed" } }; }
function view(): ProjectRiskView { return { project: { id: scope.projectId, revision: 1, name: "合成项目", owner_id: id(10), visibility: "category" }, product_revision: 3, members: [{ id: scope.principalId, name: "本人", can_write: true }], risks: [row()], as_of: at }; }
function command(value = row()) { return newRiskCommand(scope, 3, { ...riskDraft(value, scope), summary: "已核对原件，内部无需继续跟进", reason: "原具名跟进人登记", sources: JSON.stringify([source]) }, value); }
const inputs = (c: RiskCommand) => ({ payload: riskSemantic(c.payload), required_source_read_set: c.source_read_set, review: { before: null, after: { risk_id: c.payload.risk.id, decision_id: c.payload.risk.decision_id, revision: 1, state: c.payload.action === "close" ? "closed" : "open", summary: c.payload.summary } } });
const preview = (c: RiskCommand) => ({ command: { ...structuredClone(c), payload: { ...structuredClone(c.payload), confirmation_token: "explicit-common-confirmation-substitute" } }, confirmation_token: "explicit-common-confirmation-substitute", expires_at: "2099-01-01T00:00:00Z", review: inputs(c).review });
const receipt = (c: RiskCommand) => ({ id: id(20), operation: riskFollowupOperation, subject_type: "risk_followup", subject_id: id(21), subject_revision: 1, result: { id: id(21), revision: 1, status: c.payload.action === "close" ? "closed" : "open", risk_id: c.payload.risk.id, project_id: c.payload.project_id } });

test("completed associated task does not close a risk; only the G0 named follower may draft", () => {
  const actual = row(), draft = riskDraft(actual, scope); assert.equal(actual.task?.state, "completed"); assert.equal(actual.state, "open"); assert.equal(draft.action, "close"); assert.equal(draft.current, null); assert.equal("promised_at" in draft, false);
  for (const changed of [{ ...actual, responsible_id: id(99) }, { ...actual, can_record: false }, { ...actual, state: "unknown" as const }, { ...actual, blocked: { code: "source_missing", message: "资料缺失" } }]) { assert.equal(canRecordRisk(changed, scope), false); assert.throws(() => riskDraft(changed, scope)); }
});
test("reopen uses the same fixed G0 and exact prior followup without changing the original date", () => {
  const original = row(), actual: ProjectRisk = { ...original, state: "closed", current: { id: id(21), revision: 1 }, summary: "原关闭结果" }, draft = riskDraft(actual, scope);
  assert.equal(draft.action, "reopen"); assert.deepEqual(draft.risk, { id: original.id, decision_id: original.decision_id }); assert.deepEqual(draft.current, actual.current); assert.equal(original.due_date, "2030-10-17");
  for (const changed of [{ ...actual, current: { id: id(99), revision: 2 } }, { ...actual, decision_id: id(99) }, { ...actual, state: "open" as const }]) assert.equal(riskDraftCurrent(draft, changed, scope), false);
});
test("read errors, unknown states and blocked records are retained without an empty or open substitution", () => {
  const value = view(); value.risks.push({ ...row(), id: id(40), state: "unknown", can_record: false, blocked: { code: "followup_unavailable", message: "原记录不可读" } }); const parsed = parseProjectRiskView(value, scope); assert.equal(parsed.risks[1].state, "unknown"); assert.equal(parsed.risks[1].current, null);
  for (const bad of [{ ...view(), risks: undefined }, { ...view(), risks: [row(), row()] }, { ...view(), project: { ...view().project, id: id(99) } }, { ...view(), risks: [{ ...row(), due_date: "2030-02-30" }] }, { ...view(), risks: [{ ...row(), state: "closed" }] }]) assert.throws(() => parseProjectRiskView(bad, scope));
  assert.equal(parseProjectRiskView({ ...view(), risks: [] }, scope).risks.length, 0);
});
test("result and reason need original artifact sources and cannot carry approval or actor fields", () => {
  const p = command().payload;
  for (const bad of [{ ...p, sources: [] }, { ...p, sources: [{ ...source, kind: "question" }] }, { ...p, risk: { ...p.risk, owner_id: scope.principalId } }, { ...p, current: { id: id(21), revision: 1, state: "open" } }, { ...p, project_id: id(99) }, { ...p, summary: " " }, { ...p, reason: " " }, { ...p, authorized: true }, { ...p, actor_id: scope.principalId }, { ...p, action: "accept" }]) assert.throws(() => parseRiskPayload(bad, scope));
  const value = row(); assert.throws(() => newRiskCommand(scope, 3, { ...riskDraft(value, scope), summary: "结果", reason: "依据", sources: JSON.stringify([source, { ...source, revision: 2 }]) }, value), /两个版本/);
});
test("inputs and preview stop before a business save and persist the enriched source read set", async () => {
  const c = command(), calls: string[] = [], stages: RiskPending[] = [];
  const result = await runRiskRequest(async <T>(route: string) => { calls.push(route); return (route.endsWith("/inputs") ? inputs(c) : preview(c)) as T; }, { stage: "inputs", command: c }, scope, value => stages.push(value), () => true);
  assert.equal(result?.stage, "preview"); assert.deepEqual(calls, [`v1/categories/${scope.categoryId}/products/${scope.productId}/project-work/risks/inputs`, `v1/categories/${scope.categoryId}/commands/preview`]); assert.equal(stages[0].stage, "preview"); assert.equal(calls.some(path => path.endsWith("/commands")), false);
});
test("inputs cannot silently replace the G0 risk, current version, content, action or source", async () => {
  const c = command();
  for (const changed of [{ ...c.payload, risk: { ...c.payload.risk, id: id(99) } }, { ...c.payload, risk: { ...c.payload.risk, decision_id: id(99) } }, { ...c.payload, current: { id: id(21), revision: 1 } }, { ...c.payload, action: "reopen" }, { ...c.payload, summary: "不同结果" }, { ...c.payload, sources: [{ ...source, revision: 2 }] }]) {
    let calls = 0; await assert.rejects(runRiskRequest(async <T>() => { calls++; return { ...inputs(c), payload: changed } as T; }, { stage: "inputs", command: c }, scope, () => assert.fail(), () => true)); assert.equal(calls, 1);
  }
});
test("common preview checks the original envelope, token and server expiry without adding a client TTL", () => {
  const c = command(); assert.ok(riskPrepared(preview(c), c, scope));
  for (const key of ["command_id", "idempotency_key", "category_id", "product_id", "expected_revision", "source_read_set"] as const) { const changed = preview(c); Object.assign(changed.command, { [key]: key === "source_read_set" ? [] : key === "expected_revision" ? 4 : id(99) }); assert.equal(riskPrepared(changed, c, scope), null); }
  for (const changed of [{ ...preview(c), expires_at: null }, { ...preview(c), expires_at: "2000-01-01T00:00:00Z" }, { ...preview(c), confirmation_token: "different-confirmation-token" }]) assert.equal(riskPrepared(changed, c, scope), null);
});
test("unknown execution restores purely and an explicit replay sends the exact original command and key", async () => {
  const c = preview(command()).command, original = structuredClone(c), pending: RiskPending = { stage: "execute", command: c }, calls: unknown[] = []; let lost = true;
  const api: ProjectWorkApi = async <T>(_route: string, body?: unknown) => { calls.push(body); if (lost) { lost = false; throw new Error("synthetic response lost"); } return receipt(c) as T; };
  await assert.rejects(runRiskRequest(api, pending, scope, () => assert.fail(), () => true)); const local = restoreRiskLocal({ ...blankRiskLocal(scope), pending }, scope); assert.ok(local?.pending); assert.equal(calls.length, 1);
  assert.equal((await runRiskRequest(api, local.pending, scope, () => assert.fail(), () => true))?.stage, "saved"); assert.deepEqual(calls, [original, original]);
});
test("a receipt for another risk, revision, state or project cannot establish success", async () => {
  const c = preview(command()).command;
  for (const bad of [{ ...receipt(c), subject_type: "task" }, { ...receipt(c), operation: "work.task.create" }, { ...receipt(c), result: { ...receipt(c).result, risk_id: id(99) } }, { ...receipt(c), result: { ...receipt(c).result, project_id: id(99) } }, { ...receipt(c), result: { ...receipt(c).result, status: "open" } }, { ...receipt(c), result: { ...receipt(c).result, revision: 2 } }]) await assert.rejects(runRiskRequest(async <T>() => bad as T, { stage: "execute", command: c }, scope, () => assert.fail(), () => true), /回执尚未核实/);
});
test("scope isolation and persisted stage validation reject cross-person and fake confirmation recovery", () => {
  const c = command(), local = { ...blankRiskLocal(scope), pending: { stage: "preview", command: c } }; assert.ok(restoreRiskLocal(local, scope));
  for (const key of ["principalId", "categoryId", "productId", "projectId"] as const) { const other = { ...scope, [key]: id(99) }; assert.equal(restoreRiskLocal(local, other), null); assert.notEqual(riskStorageKey(scope), riskStorageKey(other)); }
  assert.equal(restoreRiskLocal({ ...local, pending: { stage: "execute", command: c } }, scope), null);
  assert.equal(restoreRiskLocal({ ...local, pending: { stage: "preview", command: preview(c).command } }, scope), null);
  assert.equal(validRiskCommand({ ...c, source_read_set: [] }, scope), false);
});
test("DTO strip and UUID normalization do not permit semantic edits or mutate an exact execute body", async () => {
  const c = command(), raw = { ...c.payload, summary: ` ${c.payload.summary} `, reason: ` ${c.payload.reason} `, risk: { id: c.payload.risk.id.toUpperCase(), decision_id: c.payload.risk.decision_id.toUpperCase() }, sources: c.payload.sources.map(value => ({ ...value, position: ` ${value.position} ` })) };
  assert.deepEqual(riskSemantic(parseRiskPayload(raw, scope)), riskSemantic(c.payload));
  const alpha = "abcdefab-1234-4000-8000-abcdefabcdef", normalized = parseRiskPayload({ ...c.payload, risk: { id: ` ${alpha.toUpperCase()} `, decision_id: alpha.toUpperCase() }, current: { id: alpha.toUpperCase(), revision: 2 }, sources: [{ ...source, id: alpha.toUpperCase() }] }, scope); assert.deepEqual(normalized.risk, { id: alpha, decision_id: alpha }); assert.equal(normalized.current?.id, alpha); assert.equal(normalized.sources[0].id, alpha);
  const exact = preview(c).command, before = structuredClone(exact); await runRiskRequest(async <T>(_route: string, body?: unknown) => { assert.deepEqual(body, before); return receipt(c) as T; }, { stage: "execute", command: exact }, scope, () => assert.fail(), () => true); assert.deepEqual(exact, before);
});
test("storage transition failure or disposal after input prevents the next POST", async () => {
  const c = command(); let calls = 0; await assert.rejects(runRiskRequest(async <T>() => { calls++; return inputs(c) as T; }, { stage: "inputs", command: c }, scope, () => { throw new Error("storage unavailable"); }, () => true), /storage unavailable/); assert.equal(calls, 1);
  let active = true; calls = 0; const result = await runRiskRequest(async <T>() => { calls++; active = false; return inputs(c) as T; }, { stage: "inputs", command: c }, scope, () => assert.fail(), () => active); assert.equal(result, null); assert.equal(calls, 1);
});
