import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(extension => filename + extension).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const runtime = new Module(filename); modules.set(filename, runtime);
  runtime.require = name => name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  runtime._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS } }).outputText, filename);
  return runtime.exports;
}
const { readProjectExternalHandoffs, readProjectExternalHandoff, readProjectExternalHandoffReceipts } = load(path.join(directory, "project-external-handoffs.ts"));
const id = n => `00000000-0000-4000-8000-${n.toString(16).padStart(12, "0")}`, ref = n => ({ id: id(n), revision: 1 });
const clone = value => structuredClone(value);
const scope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) };
const root = `v1/categories/${scope.categoryId}/products/${scope.productId}/external-handoffs`;
const at = "2026-10-18T12:34:56.123456+08:00", received = "2026-10-18T12:34:57.654321+08:00";
const source = { kind: "artifact", id: id(5), revision: 2, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const range = { quantity: "1.234567890123456789E+3", unit: "ea", site: "保存时场地", lots: null, lines: [], regions: null };
function detail(count = 0, n = 100) {
  const declaration = { project_id: scope.projectId, package: ref(10), engineering_decision: ref(11), manufacturing_decision: ref(12),
    subject_config: { definition: ref(6), engineering_configuration: ref(7), manufacturing_configuration: ref(8) },
    release_scope: clone(range), purpose: "固定合成移交用途", visibility: "category", destination: { system: "Synthetic ERP", recipient_id: "registered-recipient" }, external_id: "fixed-external-id",
    mappings: [{ ref: { kind: "engineering_configuration", ...ref(7) }, external_number: "EC-01", external_version: "A", sources: [clone(source)] }],
    manifest: [{ artifact: ref(9), logical_name: "fixed-original.txt", content_sha256: "b".repeat(64), external_number: "DOC-01", external_version: "A", sources: [clone(source)] }],
    sources: [clone(source)], reason: "保存时本人核对", approval_token: null };
  const authorization = { structural_only: true, status: "unexecuted_candidate", operation: "integration.handoff.authorize",
    scope: { tenant_id: id(15), product_id: scope.productId, project_id: scope.projectId }, category_id: scope.categoryId, declaration,
    package_sha256: "c".repeat(64), manifest_sha256: "d".repeat(64), mappings_sha256: "e".repeat(64), content_sha256: "f".repeat(64),
    limits: [{ text: "保存时明确限制", sources: [clone(source)] }], signers: [id(25)], state: "READY", unknown: [], blocked: [], sources: [clone(source)],
    required_source_read_set: [{ artifact_id: source.id, expected_revision: source.revision }], prepared_at: at, network_send: false, external_received: false, external_effective: false };
  const packet = { handoff: ref(n), ...Object.fromEntries(["package", "engineering_decision", "manufacturing_decision", "subject_config", "release_scope", "purpose", "destination", "external_id", "manifest", "mappings"].map(key => [key, clone(declaration[key])])),
    manifest_sha256: authorization.manifest_sha256, mappings_sha256: authorization.mappings_sha256, content_sha256: authorization.content_sha256, network_send: false };
  return { ...ref(n), project_id: scope.projectId, purpose: declaration.purpose, package: ref(10), visibility: "category", created_at: at, receipt_id: id(500 + n),
    as_of: { id: id(1000 + n), handoff: ref(n), intent: ref(2000 + n), receipt_count: count, latest_receipt: count ? ref(3000 + count) : null, epoch: count + 1, projection_sha256: "a".repeat(64) },
    reading: { status: "authorized", ...Object.fromEntries(["sent", "accepted", "effective"].map(stage => [stage, { stage, state: "not_recorded", active: [], covered_scopes: [], mismatches: [] }])),
      delivery_unknown: false, rejected: false, failed: false, conflict: false, network_send: false }, network_send: false,
    authorization, authority: { subject_id: id(25), valid_until: null, saved_role: "engineering", synthetic: true }, intent: { ...ref(2000 + n), packet }, applicability: "needs_recheck" };
}
function header(value) { const { authorization, authority, intent, applicability, ...head } = value; void authorization; void authority; void intent; void applicability; return head; }
function receipt(value, sequence) {
  return { ...ref(3000 + sequence), sequence,
    original: { schema_version: "pdos-external-receipt-v1", handoff: { id: value.id, revision: value.revision }, intent: { id: value.intent.id, revision: value.intent.revision },
      destination: clone(value.intent.packet.destination), external_id: value.intent.packet.external_id, manifest_sha256: value.intent.packet.manifest_sha256,
      release_scope: clone(range), stage: "sent", outcome: "unknown", external_receipt_id: `original-${sequence}`, occurred_at: at, reconciles: null },
    source: clone(source), issuer: { key: "actual-host-substitute", version: "v1", epoch: 1, system: "Synthetic ERP", subject_id: "registered-recipient", proof_sha256: "b".repeat(64) },
    mismatches: [], receipt_id: id(4000 + sequence), received_at: received };
}
function world(count = 0) {
  const fixed = detail(count), state = { calls: [], fixed, list: { items: [header(fixed)], next_cursor: null },
    receipts: { as_of: clone(fixed.as_of), items: Array.from({ length: Math.min(count, 20) }, (_, i) => receipt(fixed, count - i)), before_sequence: count > 20 ? count - 19 : null }, error: null };
  state.api = async (request, ...body) => {
    assert.equal(body.length, 0, "GET only"); state.calls.push(request);
    if (state.error) throw state.error;
    return clone(request.includes("/receipts") ? state.receipts : request.includes("?project_id=") ? state.list : state.fixed);
  };
  return state;
}
const readList = state => readProjectExternalHandoffs(state.api, scope);
const readDetail = state => readProjectExternalHandoff(state.api, scope, { id: state.fixed.id, revision: state.fixed.revision });
const readReceipts = (state, before) => readProjectExternalHandoffReceipts(state.api, scope, state.fixed, before);

test("project list is one exact GET and preserves server states and raw header values", async () => {
  const state = world(), raw = clone(state.list), value = await readList(state);
  assert.deepEqual(state.calls, [`${root}?project_id=${scope.projectId}`]); assert.deepEqual(value, { items: raw.items, nextCursor: null }); assert.deepEqual(state.list, raw);
  assert.equal(value.items[0].reading.status, "authorized"); assert.equal(value.items[0].network_send, false);
});
test("explicit detail GET preserves immutable authorization, saved signer, authority, intent, mappings, nulls and decimal precision", async () => {
  const state = world(), raw = clone(state.fixed), value = await readDetail(state);
  assert.deepEqual(state.calls, [`${root}/${raw.id}`]); assert.deepEqual(value, raw);
  assert.notEqual(value.authorization.signers[0], scope.principalId); assert.equal(value.applicability, "needs_recheck");
  assert.equal(value.authorization.declaration.release_scope.quantity, range.quantity); assert.equal(value.authority.valid_until, null);
});
test("separate raw receipt GET preserves unknown, failed, rejected, mismatch and reconciliation without recomputing reading", async () => {
  const state = world(4), raw = clone(state.fixed.reading);
  state.receipts.items[0].original.outcome = "failed"; state.receipts.items[1].original.outcome = "rejected";
  state.receipts.items[2].original = { ...state.receipts.items[2].original, outcome: "succeeded", external_id: "external-disagreement", reconciles: ref(3001) };
  state.receipts.items[2].mismatches = ["EXTERNAL_ID_MISMATCH"];
  const value = await readReceipts(state);
  assert.deepEqual(state.calls, [`${root}/${state.fixed.id}/receipts`]); assert.deepEqual(value.items, state.receipts.items); assert.deepEqual(state.fixed.reading, raw);
  assert.equal(value.items[0].original.occurred_at, at); assert.equal(value.items[0].received_at, received);
});
test("original UUID history cursor is encoded and descending returned rows remain a page rather than a total", async () => {
  const state = world(); state.list.items = Array.from({ length: 20 }, (_, i) => header(detail(0, 100 - i))); state.list.next_cursor = id(81);
  const page = await readProjectExternalHandoffs(state.api, scope, id(101));
  assert.equal(state.calls[0], `${root}?project_id=${scope.projectId}&history_cursor=${id(101)}`); assert.equal(page.nextCursor, id(81)); assert.equal(page.items.length, 20);
});
test("receipt sequence pagination uses the original before_sequence and fixed watermark", async () => {
  const state = world(25), first = await readReceipts(state);
  assert.equal(first.beforeSequence, 6); state.receipts.items = Array.from({ length: 5 }, (_, i) => receipt(state.fixed, 5 - i)); state.receipts.before_sequence = null;
  const next = await readReceipts(state, first.beforeSequence);
  assert.equal(state.calls[1], `${root}/${state.fixed.id}/receipts?before_sequence=6`); assert.equal(next.items.length, 5); assert.equal(next.beforeSequence, null); assert.deepEqual(next.asOf, first.asOf);
});
test("server-accepted positive before_sequence can exceed count and need not be a receipt in the page", async () => {
  const state = world(1); assert.equal((await readReceipts(state, 100)).items[0].sequence, 1);
});
test("empty original lists and zero-receipt pages are valid explicit reads", async () => {
  const state = world(); state.list.items = [];
  assert.deepEqual(await readList(state), { items: [], nextCursor: null }); assert.deepEqual((await readReceipts(state)).items, []);
});
for (const key of ["categoryId", "productId", "projectId", "principalId"]) test(`invalid ${key} is rejected before any request`, async () => {
  const state = world(); await assert.rejects(readProjectExternalHandoffs(state.api, { ...scope, [key]: "invalid" })); assert.equal(state.calls.length, 0);
});
test("invalid history cursor, selected identity/revision or receipt sequence never makes a request", async () => {
  const state = world();
  await assert.rejects(readProjectExternalHandoffs(state.api, scope, "bad"));
  await assert.rejects(readProjectExternalHandoff(state.api, scope, { id: "bad", revision: 1 }));
  await assert.rejects(readProjectExternalHandoff(state.api, scope, { id: state.fixed.id, revision: 0 }));
  for (const before of [0, -1, 1.5, NaN, "2"]) await assert.rejects(readReceipts(state, before));
  assert.equal(state.calls.length, 0);
});
for (const [name, mutate] of [
  ["missing list body", s => { s.list = {}; }],
  ["wrong project", s => { s.list.items[0].project_id = id(90); }],
  ["duplicate row", s => { s.list.items.push(clone(s.list.items[0])); }],
  ["unordered rows", s => { s.list.items.push(header(detail(0, 101))); }],
  ["bad cursor", s => { s.list.next_cursor = "bad"; }],
  ["unbacked next cursor", s => { s.list.next_cursor = s.fixed.id; }],
  ["bad epoch", s => { s.list.items[0].as_of.epoch = 99; }],
  ["missing current pointer", s => { s.list.items[0].as_of = null; }],
  ["unknown state", s => { s.list.items[0].reading.accepted.state = "done"; }],
  ["missing aware creation clock", s => { s.list.items[0].created_at = "2026-10-18"; }],
]) test(`list rejects ${name} without empty fallback`, async () => { const state = world(); mutate(state); await assert.rejects(readList(state)); });
test("cursor pages reject rows outside the original UUID boundary", async () => {
  const state = world(); await assert.rejects(readProjectExternalHandoffs(state.api, scope, state.fixed.id));
});
for (const [name, mutate] of [
  ["different selected identity", s => { s.fixed.id = id(99); }],
  ["different selected version", s => { s.fixed.revision = 2; }],
  ["wrong category", s => { s.fixed.authorization.category_id = id(99); }],
  ["wrong product", s => { s.fixed.authorization.scope.product_id = id(99); }],
  ["wrong project", s => { s.fixed.authorization.scope.project_id = id(99); }],
  ["missing tenant", s => { delete s.fixed.authorization.scope.tenant_id; }],
  ["wrong authorization purpose", s => { s.fixed.authorization.declaration.purpose = "other-purpose"; }],
  ["wrong packet configuration", s => { s.fixed.intent.packet.subject_config.definition = ref(99); }],
  ["wrong packet manifest", s => { s.fixed.intent.packet.manifest = []; }],
  ["wrong packet digest", s => { s.fixed.intent.packet.content_sha256 = "9".repeat(64); }],
  ["malformed fixed source", s => { s.fixed.authorization.declaration.sources[0].position = "missing"; }],
  ["bad saved prepared clock", s => { s.fixed.authorization.prepared_at = "not-a-clock"; }],
  ["network send true", s => { s.fixed.intent.packet.network_send = true; }],
]) test(`detail rejects ${name}`, async () => {
  const state = world(), selected = { id: state.fixed.id, revision: 1 }; mutate(state); await assert.rejects(readProjectExternalHandoff(state.api, scope, selected));
});
for (const [name, mutate] of [
  ["advanced watermark", s => { s.receipts.as_of.receipt_count++; s.receipts.as_of.epoch++; }],
  ["changed projection hash", s => { s.receipts.as_of.projection_sha256 = "9".repeat(64); }],
  ["different intent", s => { s.receipts.items[0].original.intent = ref(99); }],
  ["different handoff", s => { s.receipts.items[0].original.handoff = ref(99); }],
  ["latest receipt identity mismatch", s => { s.receipts.items[0].id = id(99); }],
  ["duplicate sequence", s => { s.receipts.items[1].sequence = 2; }],
  ["bad issuer", s => { s.receipts.items[0].issuer = null; }],
  ["bad source", s => { s.receipts.items[0].source.revision = 0; }],
  ["unbacked page token", s => { s.receipts.before_sequence = 1; }],
  ["missing original clock timezone", s => { s.receipts.items[0].original.occurred_at = "2026-10-18T12:00:00"; }],
]) test(`receipt read rejects ${name}`, async () => { const state = world(2); mutate(state); await assert.rejects(readReceipts(state)); });
test("receipt page cannot repeat or cross the requested sequence boundary", async () => { const state = world(2); await assert.rejects(readReceipts(state, 2)); });
test("wrong-scope prior detail is rejected before requesting receipt history", async () => { const state = world(); state.fixed.project_id = id(90); await assert.rejects(readReceipts(state)); assert.equal(state.calls.length, 0); });
for (const status of [401, 403, 409, 503]) test(`original ${status} failure propagates exactly and never becomes an empty list`, async () => {
  const state = world(); state.error = Object.assign(new Error("original server failure"), { status, code: "SOURCE_UNAVAILABLE" });
  await assert.rejects(readList(state), error => error === state.error); await assert.rejects(readDetail(state), error => error === state.error); await assert.rejects(readReceipts(state), error => error === state.error);
});
