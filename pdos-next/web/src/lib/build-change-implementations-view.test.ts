import test from "node:test";
import assert from "node:assert/strict";
import {
  blankImplementationDraft, blankImplementationLocal, implementationInputs, implementationItem, implementationKey, implementationPlanReady,
  makeImplementationCapture, makeImplementationCommand, nativeImplementationSources, normalizeImplementationCapture, readImplementationScope,
  restoreImplementations, supportedImplementationItem, validImplementationFact, validImplementationPreview, validImplementationReceipt,
  blankFieldOccurrenceDraft, fieldImplementationSelection, fieldOccurrenceRequest, readFieldImplementationOutputs,
  type ImplementationCapture, type ImplementationCommand, type ImplementationDraft, type ImplementationFact, type ImplementationPreview, type ImplementationScope,
} from "./build-change-implementations-view";
import type { ApprovalDecision, ApprovalOrder } from "./build-change-approvals-view";
import type { OrderApi, OrderItem, OrderReadSource } from "./build-change-orders-view";
import type { DefinitionSource } from "./product-view";

const id = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const product = { id: id(1), revision: 7 }, principal = id(2), project = id(3), changeId = id(4), orderId = id(5), itemId = id(6), intentId = id(7);
const source = { id: id(8), revision: 2, kind: "artifact" as const, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const evidence = { id: id(9), revision: 1, kind: "artifact" as const, position: `line:2;quote_sha256:${"b".repeat(64)}` };
const previous = { id: id(10), revision: 3, kind: "engineering_configuration", key: null }, output = { id: id(11), revision: 1, kind: "engineering_configuration", key: null };
const now = Date.parse("2026-10-17T10:00:00Z"), createdAt = "2026-10-17T09:30:00Z", expiresAt = "2026-11-01T00:00:00Z";
const reads = [{ artifact_id: source.id, expected_revision: source.revision }, { artifact_id: evidence.id, expected_revision: evidence.revision }];
type Snapshot = Record<string, unknown> & { id: string; revision: number; status: string; title: string; scope: { product_id: string; project_id: string }; sources: OrderReadSource[]; orders: ApprovalOrder[]; assessments: { id: string; graph: { nature: string; roots: unknown[] } }[] };
type PreviewFixture = ImplementationPreview & { review: ImplementationPreview["review"] & { before: Snapshot; after: Snapshot } };
type NativeSource = DefinitionSource & { original_id: string | null };

function definition(): NativeSource { return { id: source.id, revision: source.revision, title: "系统内登记的结构化实施原文", content: "原文整行由原件所有者解析", visibility: "private", status: "active", original_id: null }; }
function item(): OrderItem { return { id: itemId, discipline: "engineering", selection: { objects: [previous], units: [`object:${previous.id}`], conditions: ["仅固定项目"], sources: [evidence] }, intent: { id: intentId, kind: "new_engineering_configuration", basis: [previous], description: "建立已批准的新配置" }, verification_requirement: "核对实际新配置并另行独立验证" }; }
function approvals(): ApprovalDecision[] { return (["engineering", "manufacturing"] as const).map((discipline, index) => ({ actor_id: id(20 + index), at: "2026-10-16T10:00:00Z", text: "本专业已具名核对", sources: [evidence], discipline, decision_id: id(22 + index), content_digest: "fixed-approved-order", expires_at: null })); }
function scope(): ImplementationScope {
  const order: ApprovalOrder = { id: orderId, assessment_id: id(24), assessment_digest: "fixed-assessment", content_digest: "fixed-approved-order", plan: { id: id(25), expires_at: expiresAt, items: [item()], dispositions: [{ object: previous, handling: "covered_by_plan", item_ids: [itemId], rationale: "明确由已批准计划项覆盖", sources: [evidence] }] }, policy: evidence, required_disciplines: ["engineering", "manufacturing"], approvals: approvals(), implementations: [], effectivity: [], verifications: [], closure: null };
  const orders = [order], request: Snapshot = { id: changeId, revision: 6, status: "approved", title: "本项目固定配置变更", scope: { product_id: product.id, project_id: project }, audience: [principal], roots: [previous], references: [], sources: [evidence], assessments: [{ id: id(24), graph: { nature: "synthetic", roots: [previous] } }], orders };
  return { context: { change: { id: id(26), change_id: changeId, revision: 6, project_id: project, visibility: "private", status: "approved", request }, policy: null, actions: [], selections: [], object_options: [], missing: [] }, orders, sources: [definition()] };
}
function request(value = scope()) { return makeImplementationCapture(value, orderId, itemId, source, id(27), now); }
function fact(): ImplementationFact { return { id: id(28), reconciles_id: null, item_id: itemId, intent_id: intentId, executor_id: principal, outcome: "succeeded", occurred_at: "2026-10-17T09:00:00Z", received_at: createdAt, sources: [evidence], outputs: [output], note: "实际新配置已由本人建立并登记原文", nature: "synthetic" }; }
function capture(): ImplementationCapture { return { id: id(29), revision: 1, change_id: changeId, change_revision: 6, order_id: orderId, item_id: itemId, fact_id: id(28), fact: fact(), required_source_read_set: structuredClone(reads), created_at: createdAt, expires_at: expiresAt }; }
function draft(value = scope()): ImplementationDraft { return { ...blankImplementationDraft(orderId, itemId), source: { ...source }, request: request(value), capture: capture() }; }
function command(value = scope(), work = draft(value)): ImplementationCommand { return makeImplementationCommand(product, value, work, principal, id(30), id(31), now); }
function preview(value = scope(), work = draft(value)): PreviewFixture {
  const original = command(value, work), before = structuredClone(value.context.change.request) as Snapshot, after = structuredClone(before);
  after.revision += 1; after.status = "implementing"; after.orders.at(-1)!.implementations.push(structuredClone(work.capture!.fact));
  return { command: { ...original, payload: { ...original.payload, confirmation_token: "original-implementation-confirmation-token-123456" } }, expires_at: "2026-10-17T10:10:00Z", review: { operation: original.operation, proof_tier: "T1", before, after, effect: "将原件捕获的实际事实保存到固定计划项；生效与独立验证另行办理" } };
}
function validates(value: unknown, current = scope(), work = draft(current), original = command(current, work)): boolean { return validImplementationPreview(value, original, current, work, now); }
function saved(stage: "capture" | "inputs" | "preview" | "execute" = "execute") {
  const work = draft(), pending = stage === "capture" ? { stage, request: work.request! } : { stage, orderId, itemId, command: stage === "execute" ? preview().command : command() };
  return { schema_version: 1, product_id: product.id, principal_id: principal, project_id: project, change_id: changeId, selectedOrderId: orderId, selectedItemId: itemId, drafts: { [implementationKey(orderId, itemId)]: work }, pending };
}

test("implementation scope reuses the actual Current Change read and never deep-reads another project", async () => {
  const current = scope(), calls: string[] = [], api: OrderApi = async <T>(path: string): Promise<T> => { calls.push(path); return (path.includes("order-context?") ? current.context : path.includes("change-execution") ? { changes: [{ ...current.context.change, current: true, capabilities: { implementation_record: false } }] } : { sources: current.sources }) as T; };
  const value = await readImplementationScope(api, product.id, changeId, project, () => true);
  assert.equal(value?.context.change.current, undefined); assert.equal(implementationPlanReady(value!, orderId, now), true);
  assert.equal(calls[2], `v1/products/${product.id}/change-execution/order-context?change_id=${changeId}`);
  calls.length = 0; await assert.rejects(readImplementationScope(api, product.id, changeId, id(99), () => true)); assert.equal(calls.length, 2);
});

test("capture requires the current latest Order, both professional approvals and their fixed unexpired content", () => {
  assert.equal(implementationPlanReady(scope(), orderId, now), true);
  const current = scope(); current.context.change.status = "implementing"; assert.equal(implementationPlanReady(current, orderId, now), true);
  const cases: ((value: ImplementationScope) => void)[] = [
    value => { value.context.change.status = "review"; }, value => { value.orders[0].approvals.pop(); },
    value => { value.orders[0].required_disciplines = ["engineering"]; }, value => { value.orders[0].required_disciplines.push("customer"); },
    value => { value.orders[0].approvals[1].content_digest = "other-content"; },
    value => { value.orders[0].approvals[1].expires_at = "2026-10-17T09:59:59Z"; },
    value => { value.orders[0].plan = { ...value.orders[0].plan, expires_at: "2026-10-17T10:00:00Z" }; },
  ];
  for (const mutate of cases) { const value = scope(); mutate(value); assert.equal(implementationPlanReady(value, orderId, now), false); assert.throws(() => request(value)); }
  const historical = scope(); historical.orders.unshift({ ...structuredClone(historical.orders[0]), id: id(40) });
  assert.equal(implementationPlanReady(historical, id(40), now), false);
  assert.throws(() => makeImplementationCapture(historical, id(40), itemId, source, id(27), now));
});

test("only an actual supported item of that Order can be captured and no planned Build or Run is an output owner", () => {
  const value = scope(); assert.equal(implementationItem(value, orderId, itemId)?.intent.id, intentId); assert.equal(implementationItem(value, orderId, id(99)), null);
  assert.equal(supportedImplementationItem(item()), true); assert.throws(() => makeImplementationCapture(value, orderId, id(99), source, id(27), now));
  for (const kind of ["new_build", "new_test_run", "erp_mes_effectivity"] as const) {
    const changed = scope(), original = changed.orders[0].plan.items[0]; changed.orders[0].plan = { ...changed.orders[0].plan, items: [{ ...original, intent: { ...original.intent, kind } }] };
    assert.equal(supportedImplementationItem(changed.orders[0].plan.items[0]), false); assert.throws(() => request(changed));
  }
});

test("native selection requires explicit original_id null and the active exact Artifact revision and complete line", () => {
  const native = definition(), uploaded = { ...native, id: id(41), original_id: id(42) }, absent: DefinitionSource = { id: id(43), revision: 1, title: "缺原件元数据", content: "内容", visibility: "private", status: "active" };
  assert.deepEqual(nativeImplementationSources([native, uploaded, absent]), [native]);
  for (const sources of [[uploaded], [absent], [{ ...native, original_id: undefined }], [{ ...native, status: "withdrawn" }], [{ ...native, revision: 3 }]]) {
    const value = scope(); value.sources = sources; assert.throws(() => request(value));
  }
  assert.throws(() => makeImplementationCapture(scope(), orderId, itemId, { ...source, position: "line:1" }, id(27), now));
  assert.throws(() => makeImplementationCapture(scope(), orderId, itemId, null, id(27), now));
});

test("capture requests preserve one original key and exact source without asserting a formal implementation", () => {
  const value = scope(), original = request(value), repeated = makeImplementationCapture(value, orderId, itemId, source, original.capture_key, now);
  assert.deepEqual(repeated, original); assert.equal(original.expected_change_revision, 6); assert.equal(original.item_id, itemId);
  original.source.position = "changed"; assert.equal(source.position.startsWith("line:1;"), true);
  const received = normalizeImplementationCapture(capture(), request(value), value, principal);
  assert.equal(received.fact_id, received.fact.id); assert.deepEqual(value.orders[0].implementations, []); assert.equal(value.context.change.status, "approved");
  assert.equal("command_id" in received, false); assert.equal("capture_key" in received, false); // capture_view returns the real fact, not a fabricated request echo.
});

test("capture responses bind the actual fact, item, intent, executor, nature and original fixed read-set", () => {
  assert.deepEqual(normalizeImplementationCapture(capture(), request(), scope(), principal), capture());
  const cases: ((value: ImplementationCapture) => void)[] = [
    value => { value.change_id = id(99); }, value => { value.change_revision = 5; }, value => { value.order_id = id(99); }, value => { value.item_id = id(99); },
    value => { value.fact_id = id(99); }, value => { value.fact.item_id = id(99); }, value => { value.fact.intent_id = id(99); }, value => { value.fact.executor_id = id(99); },
    value => { value.fact.nature = "real"; }, value => { value.required_source_read_set = [{ artifact_id: source.id, expected_revision: 1 }]; },
    value => { value.required_source_read_set = [{ artifact_id: evidence.id, expected_revision: evidence.revision }]; },
    value => { value.required_source_read_set.push({ artifact_id: source.id, expected_revision: 3 }); },
    value => { value.created_at = "2026-10-17T09:31:00Z"; }, value => { value.fact.occurred_at = "2026-10-17T09:31:00Z"; },
  ];
  for (const mutate of cases) { const value = capture(); mutate(value); assert.throws(() => normalizeImplementationCapture(value, request(), scope(), principal)); }
});

test("successful captures need an actual new output of the approved configuration family and cannot reuse old identities", () => {
  for (const outputs of [[], [previous], [{ ...previous, revision: 4 }], [{ ...output, kind: "manufacturing_configuration" }], [{ ...output, key: "operation-A" }], [output, output]]) {
    const value = capture(); value.fact.outputs = outputs; assert.throws(() => normalizeImplementationCapture(value, request(), scope(), principal));
  }
  const manufacturing = scope(), original = manufacturing.orders[0].plan.items[0];
  manufacturing.orders[0].plan = { ...manufacturing.orders[0].plan, items: [{ ...original, intent: { ...original.intent, kind: "new_manufacturing_configuration", basis: [{ ...previous, kind: "manufacturing_configuration" }] } }] };
  const actual = capture(); actual.fact.outputs = [{ ...output, kind: "manufacturing_configuration" }];
  assert.deepEqual(normalizeImplementationCapture(actual, request(manufacturing), manufacturing, principal).fact.outputs, actual.fact.outputs);
});

test("failed or unknown occurrence facts remain their actual outcome without inventing successful outputs", () => {
  for (const outcome of ["failed", "unknown"] as const) {
    const value = capture(); value.fact.outcome = outcome; value.fact.outputs = [];
    assert.equal(validImplementationFact(value.fact), true); assert.equal(normalizeImplementationCapture(value, request(), scope(), principal).fact.outcome, outcome);
  }
  assert.equal(validImplementationFact({ ...fact(), occurred_at: "2026-10-17T10:00:00" }), false);
  assert.equal(validImplementationFact({ ...fact(), sources: [] }), false);
});

test("a formal command references only the actual captured fact and the original exact source read-set", () => {
  const current = scope(), work = draft(current), original = command(current, work);
  assert.deepEqual(original.payload, { change_id: changeId, expected_change_revision: 6, visibility: "private", item_id: itemId, fact_id: id(28) });
  assert.deepEqual(original.source_read_set, reads); assert.equal(original.operation, "change.implementation.record");
  original.source_read_set[0].expected_revision = 9; assert.equal(work.capture!.required_source_read_set[0].expected_revision, source.revision);
  const wrongProduct = { ...product, id: id(99) }; assert.throws(() => makeImplementationCommand(wrongProduct, current, work, principal, id(30), id(31), now));
  const changed = draft(); changed.request!.expected_change_revision = 5; assert.throws(() => command(scope(), changed));
  const missing = draft(); missing.capture = null; assert.throws(() => command(scope(), missing));
});

test("a captured fact cannot form a new formal command after its source is withdrawn, superseded or loses its native owner", () => {
  for (const delta of [{ status: "withdrawn" }, { revision: 3 }, { original_id: id(99) }]) {
    const current = scope(), work = draft(current); current.sources[0] = { ...definition(), ...delta };
    assert.throws(() => command(current, work));
  }
  const current = scope(), work = draft(current); current.sources = []; assert.throws(() => command(current, work));
});

test("expired captures and facts already recorded in the current Order cannot become another submission", () => {
  const work = draft(); work.capture!.expires_at = "2026-10-17T10:00:00Z"; assert.throws(() => command(scope(), work));
  const current = scope(); current.orders[0].implementations.push(fact()); assert.throws(() => command(current));
});

test("T1 preview appends exactly the captured fact while preserving approvals, the fixed graph and Change scope", () => {
  const current = scope(), work = draft(current), proposed = preview(current, work);
  assert.equal(validates(proposed, current, work), true); assert.equal(proposed.review.after.status, "implementing");
  assert.deepEqual(proposed.review.after.orders[0].implementations, [work.capture!.fact]); assert.deepEqual(current.orders[0].implementations, []);
  const cases: ((value: PreviewFixture) => void)[] = [
    value => { value.command.command_id = id(99); }, value => { value.command.idempotency_key = id(99); }, value => { value.command.payload.fact_id = id(99); },
    value => { value.command.payload.item_id = id(99); }, value => { value.command.source_read_set = []; }, value => { value.command.payload.confirmation_token = "short"; },
    value => { value.review.after.status = "approved"; }, value => { value.review.after.scope.project_id = id(99); }, value => { value.review.after.title = "替换变更内容"; },
    value => { value.review.after.assessments[0].graph.roots = []; }, value => { value.review.after.orders[0].approvals.pop(); },
    value => { value.review.after.orders[0].plan = { ...value.review.after.orders[0].plan, id: id(99) }; },
    value => { value.review.after.orders[0].implementations = [{ ...fact(), outputs: [previous] }]; },
  ];
  for (const mutate of cases) { const changed = structuredClone(proposed); mutate(changed); assert.equal(validates(changed, current, work), false); }
  assert.equal(validImplementationPreview(proposed, command(), current, work, now + 11 * 60_000), false);
});

test("existing Order history and prior implementation facts remain intact when one new fact is proposed", () => {
  const current = scope(), prior = { ...fact(), id: id(44), item_id: id(45), intent_id: id(46), outcome: "failed" as const, outputs: [] };
  current.orders[0].implementations.push(prior); current.orders.unshift({ ...structuredClone(current.orders[0]), id: id(47) });
  const work = draft(current), candidate = preview(current, work); assert.equal(validates(candidate, current, work), true);
  const historyChanged = structuredClone(candidate); historyChanged.review.after.orders[0].content_digest = "changed-history"; assert.equal(validates(historyChanged, current, work), false);
  const priorChanged = structuredClone(candidate); priorChanged.review.after.orders.at(-1)!.implementations[0] = { ...prior, note: "替换旧事实" }; assert.equal(validates(priorChanged, current, work), false);
});

test("inputs add real server dependencies without changing the original command, fact or selected source versions", () => {
  const original = { ...command(), category_id: id(48) }, returned = { ...structuredClone(original), source_read_set: [...reads, { artifact_id: id(49), expected_revision: 1 }] };
  assert.deepEqual(implementationInputs({ allowed: true, command: returned }, original), returned); assert.equal(implementationInputs({ allowed: false, command: returned }, original), null);
  for (const delta of [{ command_id: id(99) }, { idempotency_key: id(99) }, { category_id: id(99) }, { source_read_set: [reads[1]] }, { source_read_set: [{ ...reads[0], expected_revision: 3 }, reads[1]] }]) assert.throws(() => implementationInputs({ allowed: true, command: { ...returned, ...delta } }, original));
  assert.throws(() => implementationInputs({ allowed: true, command: { ...returned, payload: { ...returned.payload, fact_id: id(99) } } }, original));
});

test("unknown capture recovery retains the complete same request and capture key across local restoration", () => {
  const value = saved("capture"), key = implementationKey(orderId, itemId); value.drafts[key].capture = null;
  const original = JSON.parse(JSON.stringify(value)), restored = restoreImplementations(original, product.id, principal, project, changeId);
  assert.deepEqual(restored?.pending, value.pending); assert.equal(restored?.pending?.stage, "capture");
  if (restored?.pending?.stage === "capture") assert.equal(restored.pending.request.capture_key, id(27));
  assert.deepEqual(restored?.drafts[key].request, value.drafts[key].request); assert.equal(restored?.drafts[key].capture, null);
  assert.equal(restoreImplementations({ ...value, pending: { stage: "capture", request: { ...request(), item_id: id(99) } } }, product.id, principal, project, changeId), null);
});

test("unknown execute restoration preserves the exact original command, key, token and fact even after expiry", () => {
  const value = saved(), key = implementationKey(orderId, itemId); value.drafts[key].capture!.expires_at = "2026-10-17T09:00:00Z";
  const result = restoreImplementations(JSON.parse(JSON.stringify(value)), product.id, principal, project, changeId);
  assert.deepEqual(result?.pending, value.pending); assert.deepEqual(result?.drafts[key].capture, value.drafts[key].capture);
  if (result?.pending?.stage === "execute") { assert.equal(result.pending.command.command_id, id(30)); assert.equal(result.pending.command.idempotency_key, id(31)); assert.equal(result.pending.command.payload.confirmation_token, preview().command.payload.confirmation_token); assert.deepEqual(result.pending.command.source_read_set, reads); }
  assert.equal(validImplementationPreview(preview(), command(), scope(), draft(), now + 11 * 60_000), false);
  assert.deepEqual(restoreImplementations(value, product.id, principal, project, changeId)?.pending, value.pending);
});

test("recovery isolates principal, product, project, Change and selected Order/item without mixing drafts", () => {
  const value = saved();
  for (const args of [[id(99), principal, project, changeId], [product.id, id(99), project, changeId], [product.id, principal, id(99), changeId], [product.id, principal, project, id(99)]]) assert.equal(restoreImplementations(value, args[0], args[1], args[2], args[3]), null);
  assert.equal(restoreImplementations({ ...value, selectedItemId: id(99) }, product.id, principal, project, changeId), null);
  assert.equal(restoreImplementations({ ...value, selectedOrderId: id(99) }, product.id, principal, project, changeId), null);
  assert.equal(restoreImplementations({ ...value, pending: { stage: "execute", orderId, itemId, command: command() } }, product.id, principal, project, changeId), null);
  const other = blankImplementationDraft(id(50), id(51)); value.drafts[implementationKey(other.orderId, other.itemId)] = other;
  const restored = restoreImplementations(value, product.id, principal, project, changeId); assert.deepEqual(restored?.drafts[implementationKey(other.orderId, other.itemId)], other);
  assert.equal(restoreImplementations({ ...value, drafts: { [implementationKey(orderId, id(99))]: draft() } }, product.id, principal, project, changeId), null);
});

test("implementation receipts bind the resulting Change version and the exact human writer", () => {
  const original = command(), receipt = { id: id(52), subject_id: id(53), operation: original.operation, product_id: product.id, subject_type: "change_request", subject_revision: 7, writer_id: principal, requester_id: principal, agent_run_id: null };
  assert.equal(validImplementationReceipt(receipt, original, principal), true);
  for (const delta of [{ operation: "change.order.approve" }, { product_id: id(99) }, { subject_type: "implementation_capture" }, { subject_revision: 6 }, { writer_id: id(99) }, { requester_id: id(99) }, { agent_run_id: id(99) }]) assert.equal(validImplementationReceipt({ ...receipt, ...delta }, original, principal), false);
});

test("new local state and item drafts do not share mutable request or capture state", () => {
  const first = blankImplementationLocal(), second = blankImplementationLocal(); first.drafts[implementationKey(orderId, itemId)] = draft();
  assert.deepEqual(second, { selectedOrderId: "", selectedItemId: "", drafts: {}, pending: null });
  assert.deepEqual(blankImplementationDraft(orderId, itemId), { orderId, itemId, source: null, request: null, capture: null });
});

function fieldScope(): ImplementationScope { const value = scope(); value.context.change.purpose = "本轮现场配置调查"; value.context.change.request.scope = { tenant_id: id(40), product_id: product.id, project_id: project }; value.context.selections = [{ id: id(41), revision: 2, item: item(), status: "applicable", valid_until: null, source, receipt_id: id(42), current: true, source_status: "current", missing: [], basis_kind: "field_intent", material_sha256: "a".repeat(64), feedback: { id: id(43), revision: 2 }, feedback_version_id: id(44), feedback_sha256: "b".repeat(64), intent_id: intentId, executor_id: principal }]; return value; }
const fieldOutput = () => ({ ref: output, name: "本人实际新工程配置", previous_id: previous.id, expected_previous_revision: previous.revision, owner_id: principal, visibility: "private", created_at: "2026-10-17T09:00:00Z", required_source_read_set: reads });
test("Field occurrence fixes actual Selection metadata while future plan and performed outcome remain distinct", () => { const actual = fieldScope(), draft = { ...blankFieldOccurrenceDraft(id(45)), outcome: "unknown" as const, occurredAt: createdAt, timezone: "UTC", source, note: "已经执行，但实际结果仍待核对" }, request = fieldOccurrenceRequest(actual, orderId, itemId, principal, draft, [], now); assert.equal(request.path, null); assert.equal(request.body.selection_id, id(41)); assert.equal(request.body.selection_revision, 2); assert.equal(request.body.selection_sha256, "a".repeat(64)); assert.equal(request.body.feedback_sha256, "b".repeat(64)); assert.equal(request.body.outcome, "unknown"); assert.deepEqual(request.body.outputs, []); assert.equal("issue_id" in request.body, false); assert.equal("capa_id" in request.body, false); assert.equal(actual.orders[0].implementations.length, 0); });
test("Field occurrence refuses another executor, stale Selection, planned outputs or future event times", () => { const actual = fieldScope(), draft = { ...blankFieldOccurrenceDraft(id(45)), outcome: "succeeded" as const, occurredAt: createdAt, timezone: "UTC", source, note: "本人已建立真实新配置", outputKeys: [JSON.stringify([output.kind, output.id, output.revision, null])] }; assert.equal(fieldOccurrenceRequest(actual, orderId, itemId, principal, draft, [fieldOutput()], now).body.outcome, "succeeded"); for (const change of [(s: ImplementationScope) => { s.context.selections[0].current = false; }, (s: ImplementationScope) => { s.context.selections[0].executor_id = id(99); }, (s: ImplementationScope) => { s.context.selections[0].material_sha256 = ""; }]) { const value = fieldScope(); change(value); assert.throws(() => fieldOccurrenceRequest(value, orderId, itemId, principal, draft, [fieldOutput()], now)); } assert.throws(() => fieldOccurrenceRequest(actual, orderId, itemId, principal, { ...draft, outputKeys: [] }, [], now)); assert.throws(() => fieldOccurrenceRequest(actual, orderId, itemId, principal, { ...draft, occurredAt: "2030-10-18T12:00:00Z" }, [fieldOutput()], now)); assert.throws(() => fieldOccurrenceRequest(actual, orderId, itemId, principal, { ...draft, outputKeys: ["new-plan-output"] }, [], now)); });
test("new configuration choices come from saved same-family successor rows created by the actual executor after approvals", async () => { const row = { id: output.id, revision: 1, name: "实际新配置", owner_id: principal, visibility: "private", source_status: "current", previous_id: previous.id, expected_previous_revision: previous.revision, created_at: "2026-10-17T09:00:00Z", required_source_read_set: reads }, extra = [{ ...row, id: id(46), owner_id: id(99) }, { ...row, id: id(47), previous_id: id(99) }, { ...row, id: id(48), created_at: "2026-10-01T09:00:00Z" }, { ...row, id: id(49), source_status: "needs_recheck" }], calls: string[] = []; const values = await readFieldImplementationOutputs(async <T>(path: string) => { calls.push(path); return { engineering: [row, ...extra], processes: [] } as T; }, product.id, fieldScope(), orderId, itemId, principal); assert.deepEqual(calls, [`v1/products/${product.id}/configurations`]); assert.equal(values.length, 1); assert.equal(values[0].ref.id, output.id); await assert.rejects(readFieldImplementationOutputs(async <T>() => ({ engineering: [] }) as T, product.id, fieldScope(), orderId, itemId, principal)); });
test("an actual failed occurrence never adopts a stale or cross-item Selection as its basis", () => { const actual = fieldScope(), draft = { ...blankFieldOccurrenceDraft(id(45)), outcome: "failed" as const, occurredAt: createdAt, timezone: "UTC", source, note: "实际尝试失败，没有新配置产物" }; assert.ok(fieldImplementationSelection(actual, itemId)); assert.equal(fieldImplementationSelection(actual, id(99)), null); actual.context.selections[0].item = { ...item(), id: id(99) }; assert.throws(() => fieldOccurrenceRequest(actual, orderId, itemId, principal, draft, [], now)); });
test("category Change rejects private occurrence evidence or output before any material registration", () => { const actual = fieldScope(), draft = { ...blankFieldOccurrenceDraft(id(45)), outcome: "succeeded" as const, occurredAt: createdAt, timezone: "UTC", source, note: "本人已建立真实新配置", outputKeys: [JSON.stringify([output.kind, output.id, output.revision, null])] }; actual.context.change.visibility = "category"; assert.throws(() => fieldOccurrenceRequest(actual, orderId, itemId, principal, draft, [fieldOutput()], now), /当前变更受众不可采用该私有原文\/输出/); actual.sources[0].visibility = "category"; assert.throws(() => fieldOccurrenceRequest(actual, orderId, itemId, principal, draft, [fieldOutput()], now), /当前变更受众不可采用该私有原文\/输出/); assert.equal(fieldOccurrenceRequest(actual, orderId, itemId, principal, draft, [{ ...fieldOutput(), visibility: "category" }], now).artifact_payload.visibility, "category"); actual.context.change.visibility = "private"; actual.sources[0].visibility = "private"; assert.equal(fieldOccurrenceRequest(actual, orderId, itemId, principal, draft, [fieldOutput()], now).artifact_payload.visibility, "private"); });
