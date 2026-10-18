import assert from "node:assert/strict";
import test from "node:test";
import { availableExternalWaitActions, blankExternalWaitLocal, externalWaitOperation, externalWaitSemantic, externalWaitStorageKey, newExternalWaitCommand, parseExternalWaitPayload, parseExternalWaitView, restoreExternalWaitLocal, runExternalWaitRequest, validExternalWaitCommand, type ExternalWaitAction, type ExternalWaitCommand, type ExternalWaitPayload, type ExternalWaitPending, type ExternalWaitRecord } from "./external-waits";
import type { ProjectWorkApi, WorkScope } from "./project-work";

// Synthetic transport and source metadata establish no database fact or receipt.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope: WorkScope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) }, at = "2030-10-17T12:00:00.123456Z";
const source = { id: id(5), revision: 1, kind: "artifact" as const, position: "line:1;quote_sha256:" + "a".repeat(64) };
const calendar = { kind: "project_plan" as const, id: id(10), revision: 2, calendar_key: "engineering", calendar_version: "v2" };
const records: Record<ExternalWaitAction, ExternalWaitRecord> = {
  create: { action: "create", title: "等待外部原件", target: "真实供应商联系人", request_content: "请提供原始检验资料", closure_condition: "原件经实际核对", blocking: true, next_check_at: null, original_timezone: "Asia/Shanghai" },
  details: { action: "details", title: "维护原等待", closure_condition: "核对原件", blocking: false, next_check_at: null, calendar, original_timezone: "Asia/Shanghai" },
  initiate: { action: "initiate", at: null, text: "登记已发起材料", original_timezone: "Asia/Shanghai" },
  delivery: { action: "delivery", status: "effective", at, text: "本人核对原件中的真实送达", original_timezone: "Asia/Shanghai" },
  commitment: { action: "commitment", promised_at: null, text: "对方声称会补齐，时间未知", original_timezone: "Asia/Shanghai" },
  reply: { action: "reply", status: "partial", at: null, text: "收到部分回复声明", original_timezone: "Asia/Shanghai" },
  close: { action: "close", result: "本条内部等待已无需继续跟进" }, reopen: { action: "reopen" },
  transfer_request: { action: "transfer_request", to_id: id(7) }, transfer_accept: { action: "transfer_accept", request_id: id(8) }, transfer_cancel: { action: "transfer_cancel", request_id: id(8) },
};
function payload(action: ExternalWaitAction = "create"): ExternalWaitPayload { return { project_id: scope.projectId, wait: action === "create" ? null : { id: id(6), revision: 2 }, sources: [structuredClone(source)], reason: "本人核对本次实际原件", record: structuredClone(records[action]) }; }
const command = (action: ExternalWaitAction = "create") => newExternalWaitCommand(scope, 3, payload(action));
const inputs = (c: ExternalWaitCommand) => ({ payload: externalWaitSemantic(c.payload), required_source_read_set: c.source_read_set, review: { action: c.payload.record.action } });
const receipt = (c: ExternalWaitCommand) => ({ id: id(20), operation: externalWaitOperation, subject_id: id(21), subject_revision: c.payload.wait ? c.payload.wait.revision + 1 : 1, subject_type: "external_wait", result: { wait_id: c.payload.wait?.id ?? id(21) } });
function view() { return { project: { id: scope.projectId, revision: 1, name: "实际合成项目", owner_id: scope.principalId, visibility: "category" }, product_revision: 3, members: [{ id: scope.principalId, name: "当前本人", can_write: true }], as_of: at, available_calendars: [{ ref: calendar, label: "实际项目采用的工作日历", calendar: { calendar_id: "engineering", version: "v2", timezone: "Asia/Shanghai", weekly: {}, exceptions: {} } }], waits: [{ id: id(6), wait_id: id(6), version_id: id(16), revision: 2, state: "open", responsible_id: scope.principalId, title: "等待原件", target: "原供应商", request_content: "原请求", closure_condition: "实际核对原件", blocking: true, milestone: null, build: null, replaces: null, created_at: at, next_check_at: null, original_timezone: "Asia/Shanghai", calendar: null, initiation: null, delivery: null, counterparty_commitment: null, reply: null, last_closure: null, transfer: null, history: [{ id: id(16), revision: 2, action: "details", state: "open", actor_id: scope.principalId, created_at: at, receipt_id: id(17) }], clock: { status: "delivery_unknown", response_started_at: null, working_minutes: null, calendar_label: null, check_due: null, claimed_commitment_due: null, escalation: "unknown", reasons: ["effective_delivery_missing"] } }] }; }

for (const action of Object.keys(records) as ExternalWaitAction[]) test(`${action} uses exact sources and inputs then one T0 save, without a preview or confirmation`, async () => {
  const c = command(action), calls: { path: string; body: unknown }[] = [], stages: ExternalWaitPending[] = [];
  const result = await runExternalWaitRequest(async <T>(path: string, body?: unknown) => { calls.push({ path, body }); return (path.endsWith("/inputs") ? inputs(c) : receipt(c)) as T; }, { stage: "inputs", command: c }, scope, stage => stages.push(stage), () => true);
  assert.equal(result?.stage, "saved"); assert.equal(calls.length, 2); assert.equal(stages[0].stage, "execute"); assert.equal(calls.some(call => call.path.endsWith("/preview")), false); assert.equal("confirmation_token" in c.payload, false); assert.deepEqual(c.source_read_set, [{ artifact_id: source.id, expected_revision: 1 }]);
});
test("effective delivery requires an actual aware time; null claims and checks stay unknown", () => {
  const delivery = payload("delivery"); assert.throws(() => parseExternalWaitPayload({ ...delivery, record: { ...delivery.record, at: null } }, scope)); assert.throws(() => parseExternalWaitPayload({ ...delivery, record: { ...delivery.record, at: "2030-10-17T12:00" } }, scope));
  const claim = parseExternalWaitPayload(payload("commitment"), scope); assert.equal(claim.record.action === "commitment" && claim.record.promised_at, null);
  const create = externalWaitSemantic(payload()); assert.equal(create.record.action === "create" && create.record.next_check_at, null); assert.equal(create.record.action === "create" && create.record.calendar, null);
  assert.deepEqual(externalWaitSemantic(delivery), externalWaitSemantic({ ...delivery, record: { ...delivery.record, at: "2030-10-17T20:00:00.123456+08:00" } as ExternalWaitRecord }));
});
test("scope spoofing, inline calendars, mutable anchors and missing original sources are rejected", () => {
  const original = payload();
  for (const bad of [{ ...original, project_id: id(99) }, { ...original, sources: [] }, { ...original, actor_id: scope.principalId }, { ...original, confirmation_token: "made-up-token" }, { ...original, record: { ...original.record, calendar: { ...calendar, weekly: {} } } }, { ...payload("details"), record: { ...records.details, request_content: "silently replaced" } }, { ...payload("reply"), wait: null }, { ...original, wait: { id: id(6), revision: 2 } }]) assert.throws(() => parseExternalWaitPayload(bad, scope));
  assert.throws(() => newExternalWaitCommand(scope, 3, { ...original, sources: [source, { ...source, revision: 2 }] }), /两个版本/);
  const c = command(); c.source_read_set = []; assert.equal(validExternalWaitCommand(c, scope), false);
});
test("inputs may not rewrite the fixed request, wait revision or actual material", async () => {
  const c = command("delivery"); for (const wrong of [{ ...inputs(c), payload: { ...c.payload, wait: { id: id(6), revision: 3 } } }, { ...inputs(c), required_source_read_set: [] }, { ...inputs(c), payload: { ...c.payload, record: { ...c.payload.record, at: "2030-10-18T12:00:00Z" } } }]) {
    let calls = 0; await assert.rejects(runExternalWaitRequest(async <T>() => { calls++; return wrong as T; }, { stage: "inputs", command: c }, scope, () => assert.fail(), () => true)); assert.equal(calls, 1);
  }
});
test("unknown-save restoration is pure and explicit replay preserves original version and request key", async () => {
  const c = command("reply"), original = structuredClone(c), local = blankExternalWaitLocal(scope); local.pending = { stage: "execute", command: c }; local.action = "reply"; local.selectedId = id(6);
  assert.deepEqual(restoreExternalWaitLocal(local, scope), local);
  for (const key of ["principalId", "categoryId", "productId", "projectId"] as const) { const other = { ...scope, [key]: id(99) }; assert.equal(restoreExternalWaitLocal(local, other), null); assert.notEqual(externalWaitStorageKey(scope), externalWaitStorageKey(other)); }
  let first = true; const calls: unknown[] = [], api: ProjectWorkApi = async <T>(_path: string, body?: unknown) => { calls.push(body); if (first) { first = false; throw new Error("response lost"); } return receipt(c) as T; };
  await assert.rejects(runExternalWaitRequest(api, local.pending, scope, () => assert.fail(), () => true)); assert.equal(calls.length, 1); await runExternalWaitRequest(api, local.pending, scope, () => assert.fail(), () => true); assert.deepEqual(calls, [original, original]);
});
test("storage failure or disposal after inputs prevents an unrecoverable T0 write", async () => {
  const c = command(); let calls = 0; await assert.rejects(runExternalWaitRequest(async <T>() => { calls++; return inputs(c) as T; }, { stage: "inputs", command: c }, scope, () => { throw new Error("storage unavailable"); }, () => true)); assert.equal(calls, 1);
  let active = true; calls = 0; assert.equal(await runExternalWaitRequest(async <T>() => { calls++; active = false; return inputs(c) as T; }, { stage: "inputs", command: c }, scope, () => assert.fail(), () => active), null); assert.equal(calls, 1);
});
test("actual read parsing retains null clock values and rejects a partial or foreign success", () => {
  const actual = parseExternalWaitView(view(), scope); assert.equal(actual.waits[0].clock.working_minutes, null); assert.equal(actual.waits[0].clock.claimed_commitment_due, null);
  for (const bad of [{ ...view(), project: { ...view().project, id: id(99) } }, { ...view(), waits: undefined }, { ...view(), waits: [{ ...view().waits[0], id: id(99) }] }, { ...view(), waits: [{ ...view().waits[0], clock: { ...view().waits[0].clock, check_due: undefined } }] }]) assert.throws(() => parseExternalWaitView(bad, scope));
});
test("transfer requests preserve old responsibility and only the named target can accept; closed only reopens", () => {
  const wait = parseExternalWaitView(view(), scope).waits[0]; wait.transfer = { request_id: id(8), from_id: scope.principalId, to_id: id(7), actor_id: scope.principalId, requested_at: at, sources: [source] };
  assert.equal(wait.responsible_id, scope.principalId); assert.deepEqual(availableExternalWaitActions(wait, id(7), id(90)), ["transfer_accept"]); assert.deepEqual(availableExternalWaitActions(wait, id(9), id(90)), []); assert.ok(availableExternalWaitActions(wait, scope.principalId, id(90)).includes("transfer_cancel")); assert.equal(availableExternalWaitActions(wait, scope.principalId, id(90)).includes("transfer_accept"), false);
  wait.state = "closed"; assert.deepEqual(availableExternalWaitActions(wait, id(7), id(90)), []); assert.deepEqual(availableExternalWaitActions(wait, scope.principalId, id(90)), ["reopen"]);
  const wrong = { ...view(), waits: [{ ...view().waits[0], transfer: { ...wait.transfer, from_id: id(99) } }] }; assert.throws(() => parseExternalWaitView(wrong, scope));
});
test("a receipt for a different wait or operation cannot establish saved success", async () => {
  const c = command("close"); for (const result of [{ ...receipt(c), result: { wait_id: id(99) } }, { ...receipt(c), operation: "work.task.create" }, { ...receipt(c), subject_type: "task" }]) await assert.rejects(runExternalWaitRequest(async <T>() => result as T, { stage: "execute", command: c }, scope, () => assert.fail(), () => true), /回执尚未核实/);
});

test("DTO whitespace and UUID spelling canonicalize before input comparison while exact execution replay stays unchanged", async () => {
  const original = payload(); if (original.record.action !== "create") assert.fail();
  original.reason = "  本人核对理由  "; original.record.title = "  合法标题  "; original.record.target = "  实际联系人  "; original.sources[0].position = `  ${source.position}  `; original.sources[0].id = "ABCDEFAB-0000-4000-8000-000000000005";
  const c = newExternalWaitCommand(scope, 3, original); assert.equal(c.payload.reason, "本人核对理由"); assert.equal(c.payload.record.action === "create" && c.payload.record.title, "合法标题"); assert.equal(c.payload.sources[0].id, original.sources[0].id.toLowerCase()); assert.equal(c.payload.sources[0].position, source.position);
  const retained = structuredClone(c); retained.payload.reason = "  本人核对理由  "; const calls: unknown[] = [];
  const result = await runExternalWaitRequest(async <T>(_path: string, body?: unknown) => { calls.push(body); return receipt(retained) as T; }, { stage: "execute", command: retained }, scope, () => assert.fail(), () => true);
  assert.equal(result?.stage, "saved"); assert.deepEqual(calls, [retained]); assert.equal(retained.payload.reason, "  本人核对理由  ");
});
