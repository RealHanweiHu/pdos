import assert from "node:assert/strict";
import test from "node:test";
import { newPublicationCommand, publicationInputs, publicationPrepared, runPublicationRequest, type PublicationCommand, type PublicationPending } from "./publication-contract";

// Explicit transport substitutes; these checks never attest professional authority.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const actor = id(7);
function command(): PublicationCommand {
  const source = { artifact_id: id(8), expected_revision: 1, line: 1, quote: "固定原文  精确空格" };
  return { category_id: id(1), product_id: id(2), command_id: id(3), idempotency_key: id(4), operation: "npi.manufacturing_baseline.publish", expected_revision: 5, source_read_set: [{ artifact_id: id(8), expected_revision: 1 }], payload: { project_id: id(5), baseline: { kind: "manufacturing_baseline", id: id(6), revision: 2 }, purpose: "精确固定用途", applicability: { site: null, sources: [source] }, requirements: [], risk: null, packaging: null, reaction_plan: null, previous_id: null, expected_previous_revision: null, visibility: "category", reason: "固定本轮工艺和资料", sources: [source] } };
}
function review(c: PublicationCommand) {
  const declaration = structuredClone(c.payload); delete declaration.approval_token;
  Object.assign(declaration.applicability, { lines: null, conditions: null, valid_from: null, valid_until: null }, c.payload.applicability);
  return { operation: c.operation, before: null, after: { id: null, revision: (c.payload.expected_previous_revision ?? 0) + 1, status: "published", created_at: null, time_policy: "server_on_save", body: { declaration, qualification: "unknown", manufacturing_release: null } }, authority: { subject_id: actor, operation: c.operation, purpose: c.payload.purpose, authorized: true, qualified: true, roles: ["manufacturing"], scope: { product_id: c.product_id, project_id: c.payload.project_id } }, effect: "固定资料，资格与制造放行分别核对。", reason: c.payload.reason, gaps: [{ code: "resource_requirements_unknown", detail: "资源要求尚未声明" }], required_source_read_set: c.source_read_set };
}
function prepared(c: PublicationCommand) { return { command: { ...structuredClone(c), payload: { ...structuredClone(c.payload), approval_token: "explicit-server-token-substitute" } }, expires_at: null, write_tier: "T2", named_decision: true, review: review(c) }; }
function receipt(c: PublicationCommand) { return { id: id(10), subject_id: id(11), subject_revision: 1, subject_type: "manufacturing_publication", operation: c.operation }; }

test("factory fixes the explicitly selected current publication independently of a new baseline", () => {
  const original = command(), previous = { id: id(21), revision: 3, project_id: original.payload.project_id, is_current: true };
  const process = { id: id(23), revision: 2 };
  const input = { project_id: original.payload.project_id, process, title: "另一固定基线", previous_id: null, expected_previous_revision: null, visibility: original.payload.visibility, reason: "固定新资料", sources: original.payload.sources, operations: [{ operation_key: "assemble", work_instruction: null, control_plan: null }], risk_notes: null, packaging_label_basis: null };
  const baseline: Parameters<typeof newPublicationCommand>[3] = {
    schema_version: "pdos-manufacturing-preparation-v1", kind: "manufacturing_baseline", id: id(22), revision: 5, series_id: id(24), project_id: input.project_id, owner_id: actor, title: input.title, purpose: original.payload.purpose, visibility: input.visibility, sources: input.sources, required_source_read_set: original.source_read_set, process, operation_key: null, previous_id: null, previous_revision: null, created_at: "2026-10-17T10:00:00Z", status: "draft", is_current: true, source_status: "current", receipt_id: id(25), qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false,
    body: { schema_version: "pdos-manufacturing-preparation-v1", kind: "manufacturing_baseline", status: "draft", input, scope: { project_id: input.project_id, purpose: original.payload.purpose }, process_snapshot: { ...process, name: "固定工艺", site: "固定现场", operations: [{ key: "assemble", name: "装配" }] }, document_bindings: [], gaps: [], qualification: "unknown", manufacturing_release: null, negative_enumeration_complete: false },
  };
  const before = structuredClone({ baseline, previous });
  const result = newPublicationCommand(original.category_id, original.product_id, original.expected_revision, baseline, original.payload.reason, previous);
  assert.equal(result.payload.previous_id, previous.id); assert.equal(result.payload.expected_previous_revision, 3);
  assert.deepEqual(result.payload.baseline, { kind: "manufacturing_baseline", id: id(22), revision: 5 });
  assert.equal(publicationInputs({ command: result, review: review(result) }, result, actor), result);
  assert.equal(publicationPrepared(prepared(result), result, actor)?.review.after.revision, 4);
  assert.deepEqual({ baseline, previous }, before);
  for (const changed of [{ ...previous, is_current: false }, { ...previous, project_id: id(30) }, { ...previous, revision: 0 }]) assert.throws(() => newPublicationCommand(original.category_id, original.product_id, original.expected_revision, baseline, original.payload.reason, changed), /当前发布版/);
  const initial = newPublicationCommand(original.category_id, original.product_id, original.expected_revision, baseline, original.payload.reason);
  assert.equal(initial.payload.previous_id, null); assert.equal(initial.payload.expected_previous_revision, null);
});

test("continuation review and preview cannot substitute the selected predecessor", () => {
  const original = command(); original.payload.previous_id = id(21); original.payload.expected_previous_revision = 3;
  for (const changed of [{ previous_id: id(22) }, { expected_previous_revision: 4 }]) {
    const response = structuredClone(original); Object.assign(response.payload, changed);
    assert.equal(publicationInputs({ command: response, review: review(response) }, original, actor), null);
    assert.equal(publicationPrepared(prepared(response), original, actor), null);
  }
});

test("inputs may extend the server read set and keep original command, key, scope and content", () => {
  const original = command(), expanded = structuredClone(original);
  expanded.source_read_set.push({ artifact_id: id(12), expected_revision: 3 });
  assert.equal(publicationInputs({ command: expanded, review: review(expanded) }, original, actor), expanded);
  const changed = structuredClone(expanded); changed.idempotency_key = id(13);
  assert.equal(publicationInputs({ command: changed, review: review(changed) }, original, actor), null);
  expanded.source_read_set.shift();
  assert.equal(publicationInputs({ command: expanded, review: review(expanded) }, original, actor), null);
});

test("named T2 preview permits no deadline and preserves gaps without claiming release", () => {
  const c = command(), p = prepared(c);
  assert.equal(publicationPrepared(p, c, actor), p);
  p.review.after.body.qualification = "ready";
  assert.equal(publicationPrepared(p, c, actor), null);
});

for (const fault of ["actor", "purpose", "role", "type", "expired", "source"])
  test(`preview rejects mismatched ${fault} material`, () => {
    const c = command(), p = prepared(c);
    if (fault === "actor") p.review.authority.subject_id = id(14);
    if (fault === "purpose") p.review.authority.purpose = "other purpose";
    if (fault === "role") p.review.authority.roles = ["engineering"];
    if (fault === "type") p.write_tier = "T1";
    if (fault === "expired") Object.assign(p, { expires_at: "2000-01-01T00:00:00Z" });
    if (fault === "source") p.command.payload.sources[0].quote = "rewritten source";
    assert.equal(publicationPrepared(p, c, actor), null);
  });

test("initial request obtains inputs and preview without submitting a decision", async () => {
  const c = command(), calls: { path: string; body: unknown }[] = [], stages: PublicationPending[] = [];
  const result = await runPublicationRequest(async <T>(path: string, body?: unknown) => {
    calls.push({ path, body });
    return (path.endsWith("/inputs") ? { command: c, review: review(c) } : prepared(c)) as T;
  }, { stage: "inputs", command: c }, actor, next => stages.push(next), () => true);
  assert.equal(result?.stage, "preview"); assert.equal(stages.length, 1);
  assert.deepEqual(calls.map(v => v.path), [`v1/products/${c.product_id}/manufacturing-publications/inputs`, "v1/commands/preview"]);
  assert.ok(calls.every(v => (v.body as PublicationCommand).idempotency_key === c.idempotency_key));
});

test("server canonical applicability defaults permit inputs and preview without changing the original request or executing", async () => {
  for (const canonicalCommand of [false, true]) {
    const original = command(), before = structuredClone(original), returned = structuredClone(original);
    if (canonicalCommand) Object.assign(returned.payload.applicability, { lines: null, conditions: null, valid_from: null, valid_until: null });
    const calls: { path: string; body: unknown }[] = [], stages: PublicationPending[] = [];
    const result = await runPublicationRequest(async <T>(path: string, body?: unknown) => {
      calls.push({ path, body });
      return (path.endsWith("/inputs") ? { command: returned, review: review(returned) } : prepared(returned)) as T;
    }, { stage: "inputs", command: original }, actor, next => stages.push(next), () => true);
    assert.equal(result?.stage, "preview");
    assert.deepEqual(calls.map(v => v.path), [`v1/products/${original.product_id}/manufacturing-publications/inputs`, "v1/commands/preview"]);
    assert.equal(stages.length, 1);
    assert.ok(calls.every(v => (v.body as PublicationCommand).command_id === original.command_id && (v.body as PublicationCommand).idempotency_key === original.idempotency_key));
    assert.deepEqual(original, before);
    assert.deepEqual(Object.keys(original.payload.applicability).sort(), ["site", "sources"]);
    assert.equal(original.payload.approval_token, undefined);
  }
});

for (const [field, changed] of Object.entries({
  lines: [{ kind: "line", id: id(20), revision: 1 }],
  conditions: { text: "另一适用条件", sources: command().payload.sources },
  valid_from: "2026-10-17T10:00:00Z",
  valid_until: "2026-10-18T10:00:00Z",
}))
  test(`omitted applicability ${field} never accepts a non-null server change`, () => {
    const original = command(), response = prepared(original);
    Object.assign(response.review.after.body.declaration.applicability, { [field]: changed });
    assert.equal(publicationInputs({ command: original, review: response.review }, original, actor), null);
    assert.equal(publicationPrepared(response, original, actor), null);
    Object.assign(response.command.payload.applicability, { [field]: changed });
    const inputCommand: PublicationCommand = structuredClone(response.command); delete inputCommand.payload.approval_token;
    assert.equal(publicationInputs({ command: inputCommand, review: response.review }, original, actor), null);
    assert.equal(publicationPrepared(response, original, actor), null);
  });

test("canonical comparison preserves actual applicability sources, fixed line and baseline references", () => {
  const original = command();
  Object.assign(original.payload.applicability, {
    lines: [{ kind: "line", id: id(20), revision: 2 }],
    conditions: { text: "固定适用条件", sources: structuredClone(original.payload.sources) },
  });
  const valid = prepared(original);
  assert.equal(publicationPrepared(valid, original, actor), valid);
  const declarations = [
    { ...valid.review.after.body.declaration, baseline: { ...original.payload.baseline, revision: 3 } },
    { ...valid.review.after.body.declaration, sources: [{ ...original.payload.sources[0], quote: "改写正文" }] },
    ...[
      { lines: [] },
      { sources: [{ ...original.payload.sources[0], expected_revision: 2 }] },
      { sources: [{ ...original.payload.sources[0], line: 2 }] },
      { sources: [{ ...original.payload.sources[0], quote: "改写适用范围原文" }] },
      { lines: [{ kind: "line" as const, id: id(21), revision: 2 }] },
      { lines: [{ kind: "line" as const, id: id(20), revision: 3 }] },
      { conditions: { text: "固定适用条件", sources: [{ ...original.payload.sources[0], artifact_id: id(22) }] } },
      { extra_scope: "undeclared" },
    ].map(change => ({ ...valid.review.after.body.declaration, applicability: { ...valid.review.after.body.declaration.applicability, ...change } })),
  ];
  for (const declaration of declarations) {
    const response = prepared(original);
    response.review.after.body.declaration = declaration;
    assert.equal(publicationInputs({ command: original, review: response.review }, original, actor), null);
    assert.equal(publicationPrepared(response, original, actor), null);
  }
});

test("scope disposal after inputs prevents any further preview or write", async () => {
  const c = command(); let active = true, calls = 0;
  const result = await runPublicationRequest(async <T>() => { calls += 1; active = false; return { command: c, review: review(c) } as T; }, { stage: "inputs", command: c }, actor, () => assert.fail("disposed scope cannot persist a new phase"), () => active);
  assert.equal(result, null); assert.equal(calls, 1);
});

test("unknown save recovery resends only the original explicitly approved request", async () => {
  const c = prepared(command()).command, waiting = { stage: "execute" as const, command: c };
  const sent: PublicationCommand[] = []; let attempts = 0;
  const api = async <T>(path: string, body?: unknown) => {
    assert.equal(path, "v1/commands"); sent.push(body as PublicationCommand); attempts += 1;
    if (attempts === 1) throw new Error("synthetic response lost after save");
    return receipt(c) as T;
  };
  await assert.rejects(runPublicationRequest(api, waiting, actor, () => assert.fail("no new phase"), () => true), /response lost/);
  const result = await runPublicationRequest(api, waiting, actor, () => assert.fail("no new phase"), () => true);
  assert.equal(result?.stage, "saved"); assert.equal(sent.length, 2);
  assert.equal(sent[0], c); assert.equal(sent[1], c);
});

test("saved response of the wrong operation is uncertain and cannot become success", async () => {
  const c = prepared(command()).command;
  await assert.rejects(runPublicationRequest(async <T>() => ({ ...receipt(c), operation: "build.start" }) as T, { stage: "execute", command: c }, actor, () => {}, () => true), /尚未核实/);
});
