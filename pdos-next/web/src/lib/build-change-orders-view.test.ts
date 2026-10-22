import test from "node:test";
import assert from "node:assert/strict";
import {
  blankOrderDisposition, blankOrderDraft, blankOrderLocal, makeOrderPrepare, normalizeOrderCandidate, normalizeOrderChanges, normalizeOrderContext,
  orderInputs, orderPlanReading, orderPreparePayload, orderRefKey, orderSelectionUsable, readOrderScope, restoreOrders, validOrderPreview, validOrderReceipt,
  blankFieldPlanDraft, fieldBasisKey, fieldPlanRequest,
  type OrderApi, type OrderCandidate, type OrderCommand, type OrderContext, type OrderDraft, type OrderItem, type OrderPreview,
} from "./build-change-orders-view";

const id = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const product = { id: id(1), revision: 3 }, principal = id(2), project = id(3), changeId = id(4), source = { id: id(5), revision: 1, kind: "artifact" as const, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const object = { id: id(6), revision: 1, kind: "engineering_configuration", key: null }, now = Date.parse("2026-10-17T10:00:00Z"), reads = [{ artifact_id: source.id, expected_revision: source.revision }];
const item: OrderItem = { id: id(7), discipline: "engineering", selection: { objects: [object], units: [`object:${object.id}`], conditions: ["仅本次固定用途"], sources: [source] }, intent: { id: id(8), kind: "new_engineering_configuration", basis: [object], description: "由工程负责人建立下一固定工程配置" }, verification_requirement: "新配置、新请求、新Run分别核对" };
function context(): OrderContext { return { change: { id: id(9), change_id: changeId, revision: 2, project_id: project, visibility: "private", status: "analysis", current: true, source_status: "current", purpose: "整改固定压力失败", request: { id: changeId, revision: 2, title: "压力结构变更", scope: { product_id: product.id, project_id: project }, assessments: [{ id: id(10) }], audience: [principal], orders: [] } }, policy: { current: true, required_disciplines: ["engineering", "manufacturing"], valid_from: "2026-10-01T00:00:00Z", valid_until: "2026-12-01T00:00:00Z", nature: "synthetic", source }, actions: [{ issue_id: id(11), issue_revision: 4, capa_id: id(12), action_id: id(13), executor_id: principal, text: "建立新配置并重新验证", kind: "corrective", completion: null }], selections: [{ id: id(14), revision: 1, item, status: "applicable", valid_until: "2026-12-01T00:00:00Z", source, receipt_id: id(15), current: true, source_status: "current", missing: [] }], object_options: [{ ref: object, label: "固定工程配置A", source }], missing: [] }; }
function selectionCandidate(): OrderCandidate {
  const action = { issue_id: id(11), expected_issue_revision: 4, capa_id: id(12), action_id: id(13) }, payload = { change_id: changeId, expected_change_revision: 2, visibility: "private", item, action, status: "applicable", source, valid_until: "2026-12-01T00:00:00Z", reason: "核对实际措施与精确范围", expected_previous_id: null, expected_previous_revision: null };
  return { command: { command_id: id(16), idempotency_key: id(17), product_id: product.id, expected_revision: 3, operation: "change.selection.decide", payload, source_read_set: reads }, material: { schema_version: "pdos-controlled-change-selection-v1", scope: { product_id: product.id, project_id: project }, change_id: changeId, item, issue_id: action.issue_id, capa_id: action.capa_id, action_id: action.action_id, executor_id: principal, decider_id: principal, status: payload.status, valid_until: payload.valid_until, reason: payload.reason }, required_source_read_set: reads };
}
function draft(): OrderDraft { return { ...blankOrderDraft(id(18)), selectedSelectionIds: [id(14)], reason: "准备本次明确范围，保留未知", dispositions: { [orderRefKey(object)]: { ...blankOrderDisposition(), handling: "covered_by_plan", itemIds: [item.id], rationale: "由本次真实计划项覆盖固定对象", source } } }; }
function prepareCommand(): OrderCommand { return makeOrderPrepare(product, orderPreparePayload(context(), draft(), now), id(19), id(20)); }
function selectionPreview(): OrderPreview { const candidate = selectionCandidate(); return { command: { ...structuredClone(candidate.command), payload: { ...structuredClone(candidate.command.payload), approval_token: "t".repeat(32) } }, expires_at: "2026-10-17T10:10:00Z", write_tier: "T2", named_decision: true, review: { operation: "change.selection.decide", before: { change_id: changeId, change_revision: 2, selection: null, revision: 0 }, after: { selection_revision: 1, material: structuredClone(candidate.material), issue_version_id: id(30) }, effect: "仅保存本项具名适用性，不批准变更令" } }; }
function preparePreview(): OrderPreview { const command = prepareCommand(); return { command: { ...command, payload: { ...command.payload, confirmation_token: "t".repeat(32) } }, expires_at: "2026-10-17T10:10:00Z", review: { operation: "change.order.prepare", before: { id: changeId, revision: 2 }, after: { id: changeId, revision: 3, status: "review", orders: [{ assessment_id: id(10), plan: command.payload.plan, approvals: [] }] }, effect: "准备正式变更令，保留未知" } }; }

test("project Change index and context reject another project and malformed provenance", () => {
  const ctx = context(); assert.equal(normalizeOrderChanges({ changes: [ctx.change] }, project)[0].change_id, changeId); assert.deepEqual(normalizeOrderChanges({ changes: [{ ...ctx.change, current: false }] }, project), []);
  assert.throws(() => normalizeOrderChanges({ changes: [ctx.change] }, id(99)));
  assert.equal(normalizeOrderContext(ctx, changeId, project).policy?.current, true); assert.throws(() => normalizeOrderContext(ctx, id(99), project)); assert.throws(() => normalizeOrderContext(ctx, changeId, id(99)));
  assert.throws(() => normalizeOrderContext({ ...ctx, selections: [{ ...ctx.selections[0], receipt_id: null }] }, changeId, project));
});
test("empty or excluded Change does not deep-read all formal history and late project reads are discarded", async () => {
  const calls: string[] = [], api: OrderApi = async <T>(path: string): Promise<T> => { calls.push(path); return (path.includes("change-execution") ? { changes: [context().change] } : { sources: [] }) as T; };
  const result = await readOrderScope(api, product.id, "", project, () => true); assert.equal(result?.context, null);
  assert.deepEqual(calls, [`v1/products/${product.id}/change-execution?project_id=${project}`, `v1/products/${product.id}/workspace`]);
  calls.length = 0; assert.equal((await readOrderScope(api, product.id, id(99), project, () => true))?.context, null); assert.equal(calls.length, 2);
  calls.length = 0; assert.equal(await readOrderScope(api, product.id, changeId, project, () => false), null); assert.equal(calls.length, 2);
});
test("one explicitly returned Change alone permits its scoped formal context read", async () => {
  const calls: string[] = [], api: OrderApi = async <T>(path: string): Promise<T> => { calls.push(path); return (path.includes("order-context?") ? context() : path.includes("change-execution") ? { changes: [context().change] } : { sources: [] }) as T; };
  assert.equal((await readOrderScope(api, product.id, changeId, project, () => true))?.context?.change.change_id, changeId);
  assert.equal(calls[2], `v1/products/${product.id}/change-execution/order-context?change_id=${changeId}`);
});
test("registered selection material must bind the exact source, real action and named decider", () => {
  const candidate = selectionCandidate(); assert.equal(normalizeOrderCandidate(candidate, product.id, context(), source, principal).command.command_id, id(16));
  assert.throws(() => normalizeOrderCandidate(candidate, product.id, context(), { ...source, revision: 2 }, principal));
  assert.throws(() => normalizeOrderCandidate({ ...candidate, material: { ...candidate.material, action_id: id(99) } }, product.id, context(), source, principal));
  assert.throws(() => normalizeOrderCandidate(candidate, product.id, context(), source, id(99)));
  assert.throws(() => normalizeOrderCandidate(candidate, product.id, { ...context(), actions: [] }, source, principal));
});
test("unknown, not applicable, stale, expired or incomplete Selection cannot become a plan item", () => {
  const row = context().selections[0]; assert.equal(orderSelectionUsable(row, now), true);
  for (const delta of [{ status: "unknown" as const }, { status: "not_applicable" as const }, { source_status: "needs_recheck" }, { current: false }, { missing: [{ code: "SOURCE_STALE", detail: "需核对" }] }, { valid_until: "2026-10-17T09:00:00Z" }]) { const changed = { ...context(), selections: [{ ...row, ...delta }] }; assert.equal(orderSelectionUsable(changed.selections[0], now), false); assert.throws(() => orderPreparePayload(changed, draft(), now)); }
});
test("prepare uses the selected immutable item and stable draft plan identity without changing owner material", () => {
  const ctx = context(), work = draft(), payload = orderPreparePayload(ctx, work, now), second = orderPreparePayload(ctx, work, now), plan = payload.plan as { id: string; items: OrderItem[]; dispositions: unknown[]; expires_at: null };
  assert.deepEqual(payload, second); assert.equal(plan.id, work.planId); assert.deepEqual(plan.items, [item]); assert.equal(plan.expires_at, null); assert.equal(payload.assessment_id, id(10));
  plan.items[0].selection.units = ["object:changed"]; assert.deepEqual(ctx.selections[0].item.selection.units, item.selection.units);
  assert.throws(() => orderPreparePayload(ctx, { ...work, selectedSelectionIds: [id(99)] }, now));
  assert.throws(() => orderPreparePayload(ctx, { ...work, selectedSelectionIds: [id(14), id(14)] }, now));
});
test("every actual known object needs explicit rationale and exact evidence; default unknown is retained honestly", () => {
  const ctx = context(), work = draft(), key = orderRefKey(object);
  assert.throws(() => orderPreparePayload(ctx, { ...work, dispositions: {} }, now));
  assert.throws(() => orderPreparePayload(ctx, { ...work, dispositions: { [key]: { ...blankOrderDisposition(), rationale: "保持未知" } } }, now));
  const unknown = orderPreparePayload(ctx, { ...work, dispositions: { [key]: { ...blankOrderDisposition(), rationale: "现有材料不足，仍待明确", source } } }, now);
  assert.equal(((unknown.plan as { dispositions: { handling: string }[] }).dispositions[0]).handling, "unknown");
  assert.throws(() => orderPreparePayload(ctx, { ...work, dispositions: { [key]: { ...work.dispositions[key], itemIds: [id(99)] } } }, now));
  assert.throws(() => orderPreparePayload(ctx, { ...work, dispositions: { [key]: { ...work.dispositions[key], handling: "reviewed_no_change" } } }, now));
});
test("T2 selection preview must be named and preserve exact command, action and decision material", () => {
  const original = selectionCandidate().command, value = selectionPreview(); assert.equal(validOrderPreview(value, original, now), true);
  assert.equal(validOrderPreview({ ...value, named_decision: false }, original, now), false);
  assert.equal(validOrderPreview({ ...value, command: { ...value.command, idempotency_key: id(99) } }, original, now), false);
  assert.equal(validOrderPreview({ ...value, command: { ...value.command, source_read_set: [] } }, original, now), false);
  assert.equal(validOrderPreview({ ...value, review: { ...value.review, after: { ...value.review.after, material: { ...selectionCandidate().material, item: { ...item, id: id(99) } } } } }, original, now), false);
  assert.equal(validOrderPreview(value, original, now + 11 * 60_000), false);
});
test("T1 preparation preview binds the whole plan, current assessment and a new unapproved Order", () => {
  const original = prepareCommand(), value = preparePreview(); assert.equal(validOrderPreview(value, original, now), true);
  assert.equal(validOrderPreview({ ...value, review: { ...value.review, after: { ...value.review.after, status: "approved" } } }, original, now), false);
  assert.equal(validOrderPreview({ ...value, review: { ...value.review, after: { ...value.review.after, orders: [{ assessment_id: id(99), plan: original.payload.plan, approvals: [] }] } } }, original, now), false);
  assert.equal(validOrderPreview({ ...value, review: { ...value.review, after: { ...value.review.after, orders: [{ assessment_id: id(10), plan: original.payload.plan, approvals: [{ discipline: "engineering" }] }] } } }, original, now), false);
});
test("inputs only fills the server read-set while original identifiers and semantic scope stay fixed", () => {
  const original = prepareCommand(), returned = { ...original, source_read_set: reads }; assert.deepEqual(orderInputs({ allowed: true, command: returned }, original), returned);
  assert.equal(orderInputs({ allowed: false, command: returned }, original), null);
  assert.throws(() => orderInputs({ allowed: true, command: { ...returned, command_id: id(99) } }, original));
  assert.throws(() => orderInputs({ allowed: true, command: { ...returned, payload: { ...returned.payload, assessment_id: id(99) } } }, original));
});
test("unknown execute recovery preserves exact command key token and project while other projects cannot restore it", () => {
  const pending = { stage: "execute", command: selectionPreview().command }, saved = { schema_version: 1, product_id: product.id, principal_id: principal, project_id: project, ...blankOrderLocal(), selectedChangeId: changeId, drafts: { [changeId]: draft() }, pending };
  assert.deepEqual(restoreOrders(JSON.parse(JSON.stringify(saved)), product.id, principal, project)?.pending, pending);
  assert.equal(restoreOrders(saved, product.id, principal, id(99)), null); assert.equal(restoreOrders(saved, product.id, id(99), project), null); assert.equal(restoreOrders(saved, id(99), principal, project), null);
  assert.equal(restoreOrders({ ...saved, project_id: undefined }, product.id, principal, project), null);
  assert.equal(restoreOrders({ ...saved, selectedChangeId: id(99) }, product.id, principal, project), null);
  assert.equal(restoreOrders({ ...saved, pending: { stage: "execute", command: selectionCandidate().command } }, product.id, principal, project), null);
});
test("different Change drafts retain stable plan identities and exact material candidates separately", () => {
  const a = { ...draft(), candidate: selectionCandidate(), selectionSource: source }, b = { ...blankOrderDraft(id(50)), reason: "另一个变更的草稿" }, saved = { schema_version: 1, product_id: product.id, principal_id: principal, project_id: project, ...blankOrderLocal(), selectedChangeId: changeId, drafts: { [changeId]: a, [id(51)]: b } };
  const restored = restoreOrders(saved, product.id, principal, project); assert.equal(restored?.drafts[changeId].planId, id(18)); assert.equal(restored?.drafts[id(51)].planId, id(50)); assert.deepEqual(restored?.drafts[changeId].candidate, selectionCandidate());
  assert.equal(restoreOrders({ ...saved, drafts: { [id(51)]: a } }, product.id, principal, project), null);
});
test("receipts bind their actual operation and subject family without inventing formal approval", () => {
  const selection = selectionCandidate().command, prepare = prepareCommand(); assert.equal(validOrderReceipt({ id: id(40), subject_id: id(41), operation: selection.operation, subject_type: "change_selection_fact" }, selection), true);
  assert.equal(validOrderReceipt({ id: id(40), subject_id: id(41), operation: prepare.operation, subject_type: "change_request" }, prepare), true);
  assert.equal(validOrderReceipt({ id: id(40), subject_id: id(41), operation: selection.operation, subject_type: "change_request" }, selection), false);
});
test("plan reading preserves exact unit tokens and unknown dispositions without implying actual new objects", () => {
  const plan = orderPreparePayload(context(), draft(), now).plan, reading = orderPlanReading(plan as Parameters<typeof orderPlanReading>[0], [principal]); assert.deepEqual(reading.scopes[0].units, item.selection.units); assert.equal(reading.intents[0].actualRef, null); assert.equal(reading.intents[0].fixedRefs[0].id, object.id);
});

test("domain or command graph provenance keeps every real object and never becomes default disposition evidence", () => {
  for (const kind of ["domain", "command"]) {
    const ctx = context(), other = { id: id(60), revision: 2, kind: "manufacturing_configuration", key: null };
    ctx.object_options.push({ ref: other, label: "实际制造配置", source: { id: id(61), revision: 1, kind, position: "fixed-owner-receipt" } });
    const normalized = normalizeOrderContext(ctx, changeId, project); assert.equal(normalized.object_options.length, 2); assert.equal(normalized.object_options[1].source.kind, kind);
    assert.throws(() => orderPreparePayload(normalized, draft(), now));
    const work = draft(); work.dispositions[orderRefKey(other)] = { ...blankOrderDisposition(), rationale: "仍需原文核对，不补为无需更改", source };
    assert.equal((orderPreparePayload(normalized, work, now).plan as { dispositions: unknown[] }).dispositions.length, 2);
  }
});

test("a stale Selection with an unavailable receipt remains readable with explicit gaps and grants no plan eligibility", () => {
  const ctx = context(), stale = { ...ctx.selections[0], receipt_id: null, source_status: "needs_recheck", missing: [{ code: "SOURCE_STALE", detail: "原回执与来源尚不能完整核对" }] };
  const normalized = normalizeOrderContext({ ...ctx, selections: [stale] }, changeId, project); assert.equal(normalized.selections[0].receipt_id, null); assert.equal(orderSelectionUsable(normalized.selections[0], now), false); assert.throws(() => orderPreparePayload(normalized, draft(), now));
});

test("a real PlanItem keeps its owner-verified domain sources while the original Selection and disposition still need exact artifacts", () => {
  const ctx = context(), domain = { id: id(70), revision: 1, kind: "domain", position: "fixed-current-configuration" };
  ctx.selections[0] = { ...ctx.selections[0], item: { ...item, selection: { ...item.selection, sources: [domain] } } };
  const normalized = normalizeOrderContext(ctx, changeId, project); assert.equal(normalized.selections[0].item.selection.sources[0].kind, "domain");
  const payload = orderPreparePayload(normalized, draft(), now); assert.equal((payload.plan as { items: OrderItem[] }).items[0].selection.sources[0].kind, "domain");
  assert.throws(() => normalizeOrderContext({ ...ctx, selections: [{ ...ctx.selections[0], source: domain }] }, changeId, project));
  const work = draft(); work.dispositions[orderRefKey(object)].source = domain as never; assert.throws(() => orderPreparePayload(normalized, work, now));
  assert.equal(orderPlanReading(payload.plan as Parameters<typeof orderPlanReading>[0], [principal]).scopes[0].sources[0].status, "unknown");
});

function fieldContext(): OrderContext { return { ...context(), actions: [], field_basis_options: [{ feedback: { id: id(40), revision: 2 }, version_id: id(41), sha256: "a".repeat(64), title: "已定位的实际现场反馈" }], executor_options: [{ id: principal, name: "实际执行人" }] }; }
function fieldCandidate(): OrderCandidate { const old = selectionCandidate(), ctx = fieldContext(), feedback = ctx.field_basis_options![0], action = { kind: "field_intent", feedback: feedback.feedback, executor_id: principal }, material: Record<string, unknown> = { ...old.material, schema_version: "pdos-field-change-selection-v1", feedback: feedback.feedback, feedback_version_id: feedback.version_id, feedback_sha256: feedback.sha256 }; for (const field of ["issue_id", "capa_id", "action_id"]) delete material[field]; return { ...old, command: { ...old.command, payload: { ...old.command.payload, action } }, material }; }
test("native Field selection binds its own feedback version and future executor without Issue/CAPA aliases", () => { const candidate = fieldCandidate(); assert.equal(normalizeOrderCandidate(candidate, product.id, fieldContext(), source, principal).material.feedback_version_id, id(41)); for (const delta of [{ feedback_version_id: id(99) }, { feedback_sha256: "b".repeat(64) }, { executor_id: id(99) }]) assert.throws(() => normalizeOrderCandidate({ ...candidate, material: { ...candidate.material, ...delta } }, product.id, fieldContext(), source, principal)); assert.throws(() => normalizeOrderCandidate(candidate, product.id, { ...fieldContext(), field_basis_options: [] }, source, principal)); assert.throws(() => normalizeOrderCandidate(candidate, product.id, { ...fieldContext(), executor_options: [] }, source, principal)); });
test("a Field T2 selection accepts the actual null proof clock and retains named decision requirements", () => { const candidate = fieldCandidate(), value: OrderPreview = { ...selectionPreview(), command: { ...candidate.command, payload: { ...candidate.command.payload, approval_token: "actual-T2-substitute-token" } }, expires_at: null, review: { ...selectionPreview().review, after: { selection_revision: 1, material: candidate.material } } }; assert.equal(validOrderPreview(value, candidate.command, now), true); assert.equal(validOrderPreview({ ...value, named_decision: false }, candidate.command, now), false); for (const expires_at of [undefined, "wrong", "2026-10-17T09:00:00Z"]) assert.equal(validOrderPreview({ ...value, expires_at } as unknown as OrderPreview, candidate.command, now), false); assert.equal(validOrderPreview({ ...preparePreview(), expires_at: null }, prepareCommand(), now), false); });
test("future Field plan input uses actual people/configuration options and exact object identity units", () => { const ctx = fieldContext(), base = blankFieldPlanDraft(id(42), id(43)), work = { ...base, feedbackKey: fieldBasisKey(ctx.field_basis_options![0]), executorId: principal, objectKey: orderRefKey(object), conditions: "仅本固定批次", description: "未来建立明确的新工程配置", verification: "新配置另作实测复验", status: "applicable" as const, reason: "本人据实际反馈明确未来计划" }, request = fieldPlanRequest(ctx, work, product.id, now), plan = request.body.item as OrderItem; assert.deepEqual(plan.selection.units, [`object:engineering_configuration:${object.id}:1:`]); assert.equal(plan.intent.id, id(43)); assert.equal(plan.id, id(42)); assert.deepEqual(plan.intent.basis, [object]); assert.equal("source" in request.body, false); assert.equal("issue_id" in (request.body.field_intent as object), false); for (const delta of [{ executorId: id(99) }, { objectKey: "unknown" }, { feedbackKey: "unknown" }, { description: " " }, { verification: "" }, { conditions: "" }]) assert.throws(() => fieldPlanRequest(ctx, { ...work, ...delta }, product.id, now)); });
test("development adoption is explicit and fixes the actual old Build and the server condition without rewriting ordinary plans", () => {
  const oldBuild = { id: id(80), revision: 3, kind: "build", key: null }, ctx: OrderContext = { ...fieldContext(), adoption_condition: "仅明确前轮的继任开发 Build；其他范围另行办理。", old_builds: [{ ref: oldBuild, label: "实际前轮" }] }, work = { ...blankFieldPlanDraft(id(42), id(43)), feedbackKey: fieldBasisKey(ctx.field_basis_options![0]), executorId: principal, objectKey: orderRefKey(object), conditions: "原有自由条件\n继续保留", description: "未来建立明确的新工程配置", verification: "新配置另作实测复验", status: "applicable" as const, reason: "本人明确采用范围" };
  const generic = fieldPlanRequest(ctx, work, product.id, now).body.item as OrderItem;
  assert.deepEqual(generic.intent.basis, [object]); assert.deepEqual(generic.selection.conditions, ["原有自由条件", "继续保留"]);
  assert.throws(() => fieldPlanRequest(ctx, { ...work, adoptionMode: true }, product.id, now), /真实前轮/);
  const opted = fieldPlanRequest(ctx, { ...work, adoptionMode: true, oldBuildKey: orderRefKey(oldBuild) }, product.id, now).body.item as OrderItem;
  assert.deepEqual(opted.intent.basis, [object, oldBuild]); assert.deepEqual(opted.selection.conditions, [ctx.adoption_condition]); assert.deepEqual(opted.selection.objects, [object]); assert.deepEqual(opted.selection.units, generic.selection.units);
  assert.throws(() => fieldPlanRequest({ ...ctx, old_builds: [] }, { ...work, adoptionMode: true, oldBuildKey: orderRefKey(oldBuild) }, product.id, now));
  assert.throws(() => fieldPlanRequest({ ...ctx, adoption_condition: undefined }, { ...work, adoptionMode: true, oldBuildKey: orderRefKey(oldBuild) }, product.id, now));
});
test("old Build adoption options remain exact current server refs and never accept planned identities or repeated versions", () => {
  const row = { ref: { id: id(80), revision: 3, kind: "build", key: null }, label: "实际前轮" }, ctx = { ...fieldContext(), adoption_condition: "固定开发范围", old_builds: [row] };
  assert.equal(normalizeOrderContext(ctx, changeId, project).old_builds?.[0].ref.revision, 3);
  for (const old_builds of [[{ ...row, ref: { ...row.ref, kind: "planned_build" } }], [row, row], [{ ...row, ref: { ...row.ref, revision: "3" } }]]) assert.throws(() => normalizeOrderContext({ ...ctx, old_builds }, changeId, project));
});
test("fixed Change mode reads only that actual index and cannot restore another Change's pending request", async () => { const calls: string[] = [], api: OrderApi = async <T>(path: string) => { calls.push(path); return (path.includes("order-context?") ? fieldContext() : path.includes("change-execution") ? { changes: [fieldContext().change] } : { sources: [] }) as T; }; assert.ok(await readOrderScope(api, product.id, changeId, project, () => true, changeId)); assert.equal(calls[0], `v1/products/${product.id}/change-execution?project_id=${project}&change_id=${changeId}`); await assert.rejects(readOrderScope(api, product.id, id(99), project, () => true, changeId)); const saved = { ...blankOrderLocal(), selectedChangeId: changeId, schema_version: 1, product_id: product.id, principal_id: principal, project_id: project }; assert.ok(restoreOrders(saved, product.id, principal, project, changeId)); assert.equal(restoreOrders(saved, product.id, principal, project, id(99)), null); });
