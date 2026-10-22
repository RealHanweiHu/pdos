import test from "node:test";
import assert from "node:assert/strict";
import {
  approvalInputs, approvalOrders, blankApprovalDraft, blankApprovalLocal, makeApprovalCommand, readApprovalScope,
  restoreApprovals, validApprovalPreview, validApprovalReceipt,
  type ApprovalCommand, type ApprovalDecision, type ApprovalDiscipline, type ApprovalDraft, type ApprovalOrder, type ApprovalPreview, type ApprovalScope,
} from "./build-change-approvals-view";
import type { OrderApi, OrderContext, OrderReadSource } from "./build-change-orders-view";
import type { DefinitionSource } from "./product-view";

const id = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const product = { id: id(1), revision: 7 }, principal = id(2), project = id(3), changeId = id(4), orderId = id(5);
const source = { id: id(6), revision: 2, kind: "artifact" as const, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const policySource = { id: id(7), revision: 3, kind: "artifact" as const, position: `line:2;quote_sha256:${"b".repeat(64)}` };
const object = { id: id(8), revision: 1, kind: "engineering_configuration", key: null };
const now = Date.parse("2026-10-17T10:00:00Z"), expiresAt = "2026-10-17T10:10:00Z";
const reads = [{ artifact_id: source.id, expected_revision: source.revision }];
type Snapshot = Record<string, unknown> & { id: string; revision: number; status: string; title: string; scope: { product_id: string; project_id: string }; sources: OrderReadSource[]; orders: ApprovalOrder[]; history: unknown[] };
type PreviewFixture = ApprovalPreview & { review: ApprovalPreview["review"] & { before: Snapshot; after: Snapshot } };

function savedDecision(discipline: ApprovalDiscipline): ApprovalDecision {
  return { actor_id: id(discipline === "engineering" ? 20 : 21), at: "2026-10-16T11:00:00Z", text: `${discipline} 已具名核对`, sources: [source, policySource], discipline, decision_id: id(22), content_digest: "fixed-order-content", expires_at: null };
}
function order(approvals: ApprovalDecision[] = []): ApprovalOrder {
  return {
    id: orderId, assessment_id: id(9), assessment_digest: "fixed-assessment", content_digest: "fixed-order-content",
    plan: {
      id: id(10), expires_at: "2026-11-01T00:00:00Z",
      items: [{ id: id(11), discipline: "engineering", selection: { objects: [object], units: [`object:${object.id}`], conditions: ["仅固定项目"], sources: [source] }, intent: { id: id(12), kind: "new_engineering_configuration", basis: [object], description: "创建下一版固定工程配置" }, verification_requirement: "核对新配置与独立验证" }],
      dispositions: [{ object, handling: "covered_by_plan", item_ids: [id(11)], rationale: "由明确计划项覆盖", sources: [source] }],
    },
    policy: policySource, required_disciplines: ["engineering", "manufacturing"], approvals,
    implementations: [], effectivity: [], verifications: [], closure: null,
  };
}
function definition(ref = source): DefinitionSource { return { id: ref.id, revision: ref.revision, title: "当前可读原文", content: "完整第一行\n完整第二行", visibility: "private", status: "active" }; }
function scope(approvals: ApprovalDecision[] = []): ApprovalScope {
  const orders = [order(approvals)];
  const request: Snapshot = { id: changeId, revision: 4, status: "review", title: "固定项目的结构整改", scope: { product_id: product.id, project_id: project }, audience: [principal], sources: [source], roots: [object], references: [], assessments: [{ id: id(9) }], orders, history: [] };
  const context: OrderContext = { change: { id: id(13), change_id: changeId, revision: 4, project_id: project, visibility: "private", status: "review", request }, policy: { current: true, required_disciplines: ["engineering", "manufacturing"], valid_from: "2026-10-01T00:00:00Z", valid_until: "2026-12-01T00:00:00Z", nature: "synthetic", source: policySource }, actions: [], selections: [], object_options: [], missing: [] };
  return { context, orders, sources: [definition()] };
}
function draft(discipline: ApprovalDiscipline = "engineering"): ApprovalDraft { return { discipline, text: "  已核对本专业固定内容与精确依据  ", expiresAt: "", sources: [{ ...source }] }; }
function command(value = scope(), discipline: ApprovalDiscipline = "engineering"): ApprovalCommand { return makeApprovalCommand(product, value, orderId, draft(discipline), id(14), id(15), now); }
function preview(value = scope(), discipline: ApprovalDiscipline = "engineering"): PreviewFixture {
  const original = command(value, discipline), before = structuredClone(value.context.change.request) as Snapshot, after = structuredClone(before), currentOrder = after.orders.at(-1)!;
  const decision = { actor_id: principal, at: "server_on_save", text: original.payload.text, sources: [...before.sources, currentOrder.policy], discipline, decision_id: "actual_consumed_named_proof_on_save", content_digest: currentOrder.content_digest, expires_at: original.payload.expires_at };
  currentOrder.approvals.push(decision);
  after.revision += 1;
  after.status = currentOrder.required_disciplines.every(name => currentOrder.approvals.some(row => row.discipline === name)) ? "approved" : "review";
  return { command: { ...original, payload: { ...original.payload, approval_token: "original-named-proof-token-1234567890" } }, expires_at: expiresAt, write_tier: "T2", named_decision: true, review: { operation: original.operation, before, after, effect: "保存本专业具名决定，其他专业独立办理" } };
}
function validates(value: unknown, original = command(), currentScope = scope()): boolean { return validApprovalPreview(value, original, currentScope, orderId, principal, now); }
function saved(value = scope(), discipline: ApprovalDiscipline = "engineering") {
  return { schema_version: 1, product_id: product.id, principal_id: principal, project_id: project, change_id: changeId, selectedOrderId: orderId, drafts: { [orderId]: draft(discipline) }, pending: { stage: "execute", orderId, command: preview(value, discipline).command } };
}
function apiFor(context: OrderContext, calls: string[], indexed: unknown[] = [{ ...context.change, current: true, capabilities: { order_approve: false } }]): OrderApi {
  return async <T>(path: string): Promise<T> => { calls.push(path); return (path.includes("order-context?") ? context : path.includes("change-execution") ? { changes: indexed } : { sources: [definition()] }) as T; };
}

test("approval reads bind the actual Current index to one explicit Change without inventing capability permission", async () => {
  const value = scope(), calls: string[] = [], result = await readApprovalScope(apiFor(value.context, calls), product.id, changeId, project, () => true);
  assert.deepEqual(result?.orders, value.orders);
  assert.deepEqual(calls, [`v1/products/${product.id}/change-execution?project_id=${project}`, `v1/products/${product.id}/workspace`, `v1/products/${product.id}/change-execution/order-context?change_id=${changeId}`]);
  assert.equal(result?.context.change.current, undefined); // The actual detail DTO has no Current/capability claim.
  const original = command(result!);
  assert.equal(approvalInputs({ allowed: false, command: original }, original), null);
  assert.equal(validates(preview(result!), original, result!), true);
});

test("excluded or cross-project Changes never trigger a formal-history deep read and obsolete reads are discarded", async () => {
  const value = scope(), calls: string[] = [];
  await assert.rejects(readApprovalScope(apiFor(value.context, calls, [{ ...value.context.change, current: false }]), product.id, changeId, project, () => true));
  assert.equal(calls.length, 2);
  calls.length = 0;
  await assert.rejects(readApprovalScope(apiFor(value.context, calls), product.id, id(99), project, () => true));
  assert.equal(calls.length, 2);
  calls.length = 0;
  await assert.rejects(readApprovalScope(apiFor(value.context, calls), product.id, changeId, id(99), () => true));
  assert.equal(calls.length, 2);
  calls.length = 0;
  assert.equal(await readApprovalScope(apiFor(value.context, calls), product.id, changeId, project, () => false), null);
  assert.equal(calls.length, 2);
  calls.length = 0;
  await assert.rejects(readApprovalScope(apiFor(value.context, calls), product.id, "", project, () => true));
  assert.deepEqual(calls, []);
});

test("the detail must match the indexed version and its own immutable Change product, project and status", async () => {
  const original = scope().context;
  const changes: ((value: OrderContext) => void)[] = [
    value => { value.change.id = id(99); }, value => { value.change.revision += 1; }, value => { value.change.project_id = id(99); },
    value => { value.change.current = false; }, value => { value.change.source_status = "needs_recheck"; },
    value => { value.change.request.id = id(99); }, value => { value.change.request.revision = 3; }, value => { value.change.request.status = "approved"; },
    value => { value.change.request.scope = { product_id: id(99), project_id: project }; },
    value => { value.change.request.scope = { product_id: product.id, project_id: id(99) }; },
  ];
  for (const mutate of changes) {
    const changed = structuredClone(original); mutate(changed);
    await assert.rejects(readApprovalScope(apiFor(changed, [], [{ ...original.change, current: true }]), product.id, changeId, project, () => true));
  }
});

test("saved orders require real professional decisions and reject duplicates or preview placeholders", () => {
  assert.equal(approvalOrders(scope([savedDecision("engineering")]).context)[0].approvals[0].discipline, "engineering");
  for (const mutate of [
    (value: ApprovalScope) => { value.orders.push(structuredClone(value.orders[0])); },
    (value: ApprovalScope) => { value.orders[0].approvals = [savedDecision("engineering"), savedDecision("engineering")]; },
    (value: ApprovalScope) => { value.orders[0].approvals = [{ ...savedDecision("engineering"), content_digest: "other-content" }]; },
    (value: ApprovalScope) => { value.orders[0].approvals = [{ ...savedDecision("engineering"), at: "server_on_save" }]; },
    (value: ApprovalScope) => { value.orders[0].approvals = [{ ...savedDecision("engineering"), decision_id: "actual_consumed_named_proof_on_save" }]; },
  ]) { const value = scope(); mutate(value); assert.throws(() => approvalOrders(value.context)); }
});

test("only the latest review Order and an outstanding required professional decision can form a command", () => {
  const value = scope(), original = command(value);
  assert.equal(original.payload.expected_change_revision, 4); assert.equal(original.expected_revision, product.revision);
  assert.equal(original.payload.text, draft().text.trim()); assert.deepEqual(original.source_read_set, reads);
  const historical = { ...structuredClone(value.orders[0]), id: id(40) }; value.orders.unshift(historical);
  assert.throws(() => makeApprovalCommand(product, value, historical.id, draft(), id(14), id(15), now));
  assert.throws(() => command(scope([savedDecision("engineering")])));
  assert.throws(() => command(scope(), "customer"));
  for (const status of ["analysis", "approved", "implementing", "closed"]) { const changed = scope(); changed.context.change.status = status; assert.throws(() => command(changed)); }
  assert.equal(original.payload.approval_token, undefined);
});

test("either profession may approve first but the Change stays in review until all required disciplines are complete", () => {
  for (const first of ["engineering", "manufacturing"] as const) {
    const initial = scope(), firstPreview = preview(initial, first);
    assert.equal(validates(firstPreview, command(initial, first), initial), true); assert.equal(firstPreview.review.after.status, "review");
    const wrongFirst = structuredClone(firstPreview); wrongFirst.review.after.status = "approved";
    assert.equal(validates(wrongFirst, command(initial, first), initial), false);
    const second = first === "engineering" ? "manufacturing" : "engineering", next = scope([savedDecision(first)]), secondPreview = preview(next, second);
    assert.equal(validates(secondPreview, command(next, second), next), true); assert.equal(secondPreview.review.after.status, "approved");
    const wrongSecond = structuredClone(secondPreview); wrongSecond.review.after.status = "review";
    assert.equal(validates(wrongSecond, command(next, second), next), false);
  }
  const additional = scope([savedDecision("engineering")]); additional.orders[0].required_disciplines.push("customer");
  const candidate = preview(additional, "manufacturing"); assert.equal(candidate.review.after.status, "review"); assert.equal(validates(candidate, command(additional, "manufacturing"), additional), true);
});

test("approval previews require named T2 proof and a current proof clock without assuming a T2 time limit", () => {
  const value = preview(); assert.equal(validates(value), true); assert.equal(validates({ ...value, expires_at: null }), true);
  for (const delta of [{ write_tier: "T1" }, { named_decision: false }, { expires_at: "2026-10-17T09:59:59Z" }, { expires_at: "2026-10-17T10:10:00" }]) assert.equal(validates({ ...value, ...delta }), false);
  assert.equal(validates({ ...value, command: { ...value.command, payload: { ...value.command.payload, approval_token: "short" } } }), false);
  assert.equal(validApprovalPreview(value, command(), scope(), orderId, principal, now + 11 * 60_000), false);
});

test("the new decision remains a server-on-save proposal and binds its actual person, discipline and fixed content", () => {
  const original = preview();
  for (const delta of [{ actor_id: id(99) }, { discipline: "manufacturing" }, { text: "替换批准说明" }, { content_digest: "other-order" }, { at: "2026-10-17T10:00:00Z" }, { decision_id: id(99) }, { expires_at: "2026-10-18T00:00:00Z" }]) {
    const value = structuredClone(original), decision = value.review.after.orders.at(-1)!.approvals.at(-1)!;
    Object.assign(decision, delta); assert.equal(validates(value), false);
  }
  assert.equal(validApprovalPreview(original, command(), scope(), orderId, id(99), now), false);
});

test("preview source provenance is the real request plus fixed policy, with exact versions and positions", () => {
  const original = preview(); assert.deepEqual(original.review.after.orders[0].approvals[0].sources, [source, policySource]);
  for (const sources of [[source], [policySource, source], [source, { ...policySource, revision: 4 }], [source, { ...policySource, position: "other-fixed-line" }]]) {
    const value = structuredClone(original); value.review.after.orders[0].approvals[0].sources = sources; assert.equal(validates(value), false);
  }
  const repeated = scope(); (repeated.context.change.request.sources as OrderReadSource[]).push(policySource);
  const value = preview(repeated); value.review.after.orders[0].approvals[0].sources = [source, policySource];
  assert.equal(validates(value, command(repeated), repeated), true);
});

test("a preview cannot replace the original command, read-set, current Order, plan or Change scope", () => {
  const original = preview();
  const changes: ((value: PreviewFixture) => void)[] = [
    value => { value.command.command_id = id(99); }, value => { value.command.idempotency_key = id(99); }, value => { value.command.product_id = id(99); },
    value => { value.command.expected_revision += 1; }, value => { value.command.payload.expected_change_revision += 1; }, value => { value.command.source_read_set = []; },
    value => { value.command.payload.sources = [{ ...source, revision: 3 }]; }, value => { value.review.before.revision = 3; },
    value => { value.review.after.orders[0].id = id(99); }, value => { value.review.after.orders[0].plan = { ...value.review.after.orders[0].plan, id: id(99) }; },
    value => { value.review.after.scope.project_id = id(99); }, value => { value.review.after.title = "替换固定变更内容"; }, value => { value.review.after.roots = []; },
  ];
  for (const mutate of changes) { const value = structuredClone(original); mutate(value); assert.equal(validates(value), false); }
  assert.equal(validApprovalPreview(original, command(), scope(), id(99), principal, now), false);
  const value = scope(), previous = { ...structuredClone(value.orders[0]), id: id(40) }; value.orders.unshift(previous);
  const changed = preview(value); changed.review.after.orders[0].content_digest = "changed-history";
  assert.equal(validates(changed, command(value), value), false);
});

test("inputs may add server read dependencies while preserving the same request and every explicitly chosen source", () => {
  const original = { ...command(), category_id: id(41) }, returned = { ...structuredClone(original), source_read_set: [...reads, { artifact_id: policySource.id, expected_revision: policySource.revision }] };
  assert.deepEqual(approvalInputs({ allowed: true, command: returned }, original), returned); assert.equal(approvalInputs({ allowed: false, command: returned }, original), null);
  for (const delta of [{ command_id: id(99) }, { idempotency_key: id(99) }, { category_id: id(99) }, { expected_revision: 8 }, { source_read_set: [] }, { source_read_set: [{ artifact_id: source.id, expected_revision: 3 }] }]) assert.throws(() => approvalInputs({ allowed: true, command: { ...returned, ...delta } }, original));
  assert.throws(() => approvalInputs({ allowed: true, command: { ...returned, payload: { ...returned.payload, discipline: "manufacturing" } } }, original));
  assert.throws(() => approvalInputs({ allowed: true, command: { ...returned, payload: { ...returned.payload, sources: [{ ...source, position: `line:2;quote_sha256:${"c".repeat(64)}` }] } } }, original));
});

test("approval evidence uses current active exact artifact versions, retaining distinct lines without duplicate reads", () => {
  const value = scope();
  for (const sources of [[], [source, source], [{ ...source, revision: 1 }], [{ ...source, id: id(99) }], [{ ...source, position: "line:1" }]]) assert.throws(() => makeApprovalCommand(product, value, orderId, { ...draft(), sources }, id(14), id(15), now));
  value.sources[0].status = "withdrawn"; assert.throws(() => command(value));
  const work = draft(); work.sources.push({ ...source, position: `line:2;quote_sha256:${"c".repeat(64)}` });
  const original = makeApprovalCommand(product, scope(), orderId, work, id(14), id(15), now);
  assert.equal(original.payload.sources.length, 2); assert.deepEqual(original.source_read_set, reads);
  original.payload.sources[0].position = "mutated"; assert.equal(work.sources[0].position, source.position);
});

test("an explicitly supplied approval deadline must be current, zoned and within the fixed plan", () => {
  for (const expiresAt of ["2026-10-17T09:00:00Z", "2026-10-17T10:00:00Z", "2026-10-18T10:00:00", "2026-11-02T00:00:00Z"]) assert.throws(() => makeApprovalCommand(product, scope(), orderId, { ...draft(), expiresAt }, id(14), id(15), now));
  assert.equal(command().payload.expires_at, null);
  assert.equal(makeApprovalCommand(product, scope(), orderId, { ...draft(), expiresAt: "2026-10-18T10:00:00+08:00" }, id(14), id(15), now).payload.expires_at, "2026-10-18T10:00:00+08:00");
});

test("unknown execute restoration preserves the complete original command and token after its deadline passes", () => {
  const value = saved(), encoded = JSON.parse(JSON.stringify(value)), result = restoreApprovals(encoded, product.id, principal, project, changeId);
  assert.deepEqual(result?.pending, value.pending); assert.deepEqual(result?.drafts[orderId], value.drafts[orderId]);
  assert.equal(result?.pending?.command.command_id, id(14)); assert.equal(result?.pending?.command.idempotency_key, id(15));
  assert.equal(result?.pending?.command.payload.approval_token, value.pending.command.payload.approval_token);
  assert.deepEqual(result?.pending?.command.source_read_set, reads);
  assert.equal(validApprovalPreview(preview(), result!.pending!.command, scope(), orderId, principal, now + 11 * 60_000), false);
  assert.deepEqual(restoreApprovals(encoded, product.id, principal, project, changeId)?.pending, value.pending);
});

test("restoration isolates principal, product, project and Change and refuses a different pending Order", () => {
  const value = saved();
  for (const args of [[id(99), principal, project, changeId], [product.id, id(99), project, changeId], [product.id, principal, id(99), changeId], [product.id, principal, project, id(99)]]) assert.equal(restoreApprovals(value, args[0], args[1], args[2], args[3]), null);
  assert.equal(restoreApprovals({ ...value, project_id: undefined }, product.id, principal, project, changeId), null);
  assert.equal(restoreApprovals({ ...value, selectedOrderId: id(99) }, product.id, principal, project, changeId), null);
  assert.equal(restoreApprovals({ ...value, pending: { ...value.pending, orderId: id(99) } }, product.id, principal, project, changeId), null);
  assert.equal(restoreApprovals({ ...value, pending: { ...value.pending, command: { ...value.pending.command, payload: { ...value.pending.command.payload, change_id: id(99) } } } }, product.id, principal, project, changeId), null);
  assert.equal(restoreApprovals({ ...value, pending: { ...value.pending, command: command() } }, product.id, principal, project, changeId), null);
});

test("drafts stay separate per fixed Order and incomplete input or preview requests retain their own stage", () => {
  const value = saved(); value.drafts[id(40)] = { ...blankApprovalDraft(), discipline: "manufacturing", text: "另一个固定变更令的本专业草稿" };
  for (const stage of ["inputs", "preview"]) {
    const pending = { stage, orderId, command: command() }, result = restoreApprovals({ ...value, pending }, product.id, principal, project, changeId);
    assert.deepEqual(result?.pending, pending); assert.equal(result?.drafts[id(40)].discipline, "manufacturing"); assert.equal(result?.drafts[orderId].discipline, "engineering");
  }
  const malformed = { ...value, drafts: { [orderId]: { ...draft(), sources: [{ ...source, revision: 0 }] } } };
  assert.equal(restoreApprovals(malformed, product.id, principal, project, changeId), null);
});

test("a saved receipt binds the exact operation, product, resulting revision and human writer", () => {
  const original = command(), receipt = { id: id(50), subject_id: id(51), operation: original.operation, product_id: product.id, subject_type: "change_request", subject_revision: original.payload.expected_change_revision + 1, writer_id: principal, requester_id: principal, agent_run_id: null };
  assert.equal(validApprovalReceipt(receipt, original, principal), true);
  for (const delta of [{ operation: "change.order.prepare" }, { product_id: id(99) }, { subject_type: "change_order" }, { subject_revision: 4 }, { writer_id: id(99) }, { requester_id: id(99) }, { agent_run_id: id(99) }, { id: "proposal" }]) assert.equal(validApprovalReceipt({ ...receipt, ...delta }, original, principal), false);
});

test("fresh approval local state does not share mutable drafts or evidence", () => {
  const first = blankApprovalLocal(), second = blankApprovalLocal(); first.drafts[orderId] = draft();
  assert.deepEqual(second, { selectedOrderId: "", drafts: {}, pending: null });
  const a = blankApprovalDraft(), b = blankApprovalDraft(); a.sources.push(source); assert.deepEqual(b.sources, []);
});
