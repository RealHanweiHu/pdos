import assert from "node:assert/strict";
import test from "node:test";
import {
  blankNativeLocal, importNativeResult, importNativeStatistics, nativeCountFields, nativeInputs, nativeItem, nativeOriginalResult, nativeOriginalStatistics, nativePrepared,
  nativeSemantic, newNativeCommand, requireNativeOriginal, restoreNativeLocal, runNativeRequest,
  type NativeCommand, type NativeCreatePayload, type NativePilotItem, type NativeRecord, type NativeScope,
} from "./native-pilots";
import type { DefinitionSource } from "./product-view";

// Actual contracts and transport orchestration; API responses are explicit IO substitutes.
const id = (n: number) => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
const scope: NativeScope = { categoryId: id(1), productId: id(2), projectId: id(3), principalId: id(4) };
const purpose = "本项目固定用途", source = { kind: "artifact" as const, id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` };
const named = (kind: string, n: number) => ({ kind, id: id(n), revision: 1 });
function create(): NativeCreatePayload { return { project_id: scope.projectId, visibility: "private", statistics: null, details: { pilot_id: id(10), basis: { build: named("build", 11), lot: named("build_lot", 12), actual_configuration: named("actual_configuration", 13), engineering_configuration: named("engineering_configuration", 14), process_revision: named("process_revision", 15), unit: "ea" }, purpose, source } }; }
function record(): NativeRecord { return { observation_id: id(20), expected_pilot_revision: 1, previous_observation_id: null, correction_reason: null, scope: { basis: create().details.basis, manufacturing_baseline: null, line: null, cohort_key: "本批", window_start: "2026-10-17T09:00:00Z", window_end: "2026-10-17T10:00:00Z", criterion: named("criterion", 21), nature: "synthetic", minimum_sample: 2 }, counts: Object.fromEntries(nativeCountFields.map(key => [key, key === "input_count" || key === "output_count" || key === "final_good" || key === "first_pass" ? 10 : 0])), units: [], exceptions: [], observed: { occurred_at: "2026-10-17T10:00:00.123456Z", original_timezone: "Asia/Shanghai", effective_at: null, source }, source }; }
function pilot(): NativePilotItem { return { schema_version: "pdos-native-pilot-v1", project_id: scope.projectId, pilot: { id: id(10), revision: 1, details: create().details, statistics_basis: null, material: {}, gaps: [], receipt_id: id(22), source_status: "current" }, current: { revision: 1, epoch: 1, latest_observation_id: null }, observations: [], qualification: "unknown", start_authorized: false, manufacturing_release: null }; }
function command(result = false): NativeCommand { return newNativeCommand(scope, 4, result ? "npi.pilot.result.record" : "npi.pilot.create", result ? { pilot_id: id(10), expected_pilot_revision: 1, record: record() } : create()); }
function review(c: NativeCommand) {
  const semantic = nativeSemantic(c.payload);
  return { operation: c.operation, before: null, after: { qualification: "unknown", start_authorized: false, manufacturing_release: null, external_delivery: false, material: {}, gaps: [{ code: "RESOURCE_UNKNOWN", detail: "资源准备度未知" }], ...("details" in c.payload ? { details: semantic.details, statistics_basis: semantic.statistics } : { record: semantic.record, pilot_id: c.payload.pilot_id, pilot_revision_before: c.payload.expected_pilot_revision, fixed_scope: null, projection: null }) }, authority: { subject_id: scope.principalId, operation: c.operation, purpose, authorized: true, qualified: true, roles: ["manufacturing"], scope: { tenant_id: id(30), product_id: scope.productId, project_id: scope.projectId } }, effect: "保存原始材料，未授予启动和放行", required_source_read_set: c.source_read_set };
}
function prepared(c: NativeCommand) { const token = "explicit-common-confirmation-substitute"; return { command: { ...structuredClone(c), payload: { ...structuredClone(c.payload), confirmation_token: token } }, confirmation_token: token, expires_at: "2099-10-17T10:00:00Z", review: review(c) }; }
function document(value: unknown): DefinitionSource { return { id: id(5), revision: 1, title: "实际登记合成字节", content: JSON.stringify(value), status: "active", visibility: "private" } as DefinitionSource; }

for (const result of [false, true]) test(`${result ? "result" : "create"} actual canonical inputs and T1 preview stop before execute and keep original request`, async () => {
  const original = command(result), before = structuredClone(original), calls: string[] = [], stages: string[] = [];
  const response = await runNativeRequest(async <T>(path: string) => { calls.push(path); return (path.endsWith("/inputs") ? { command: original, review: review(original) } : prepared(original)) as T; }, { stage: "inputs", command: original }, scope, purpose, next => stages.push(next.stage), () => true);
  assert.equal(response?.stage, "preview");
  assert.deepEqual(calls, [`v1/products/${scope.productId}/pilots/inputs`, "v1/commands/preview"]);
  assert.deepEqual(stages, ["preview"]); assert.deepEqual(original, before);
});

test("typed omitted defaults and equivalent timestamp representation compare without dropping actual source values", () => {
  const c = command(), server = structuredClone(c);
  Object.assign(server.payload, nativeSemantic(server.payload));
  assert.equal(nativeInputs({ command: server, review: review(server) }, c, scope, purpose), server);
  const result = command(true), p = prepared(result);
  if (!("record" in result.payload)) assert.fail();
  result.payload.record.observed.occurred_at = "2026-10-17T18:00:00.123456+08:00";
  assert.equal(nativePrepared(p, result, scope, purpose), p);
  const after = p.review.after as Record<string, unknown>;
  after.record = { ...after.record as object, source: { ...source, position: `line:2;quote_sha256:${"b".repeat(64)}` } };
  assert.equal(nativePrepared(p, result, scope, purpose), null);
});

for (const fault of ["actor", "project", "qualification", "record", "readset", "expired", "tier"]) test(`preview rejects actual ${fault} difference`, () => {
  const original = command(true), p = prepared(original);
  if (fault === "actor") p.review.authority.subject_id = id(40);
  if (fault === "project") p.review.authority.scope.project_id = id(41);
  if (fault === "qualification") p.review.authority.qualified = false;
  if (fault === "record") ((p.review.after as Record<string, unknown>).record as NativeRecord).counts!.input_count = 11;
  if (fault === "readset") p.review.required_source_read_set = [{ artifact_id: id(42), expected_revision: 2 }];
  if (fault === "expired") p.expires_at = "2000-01-01T00:00:00Z";
  if (fault === "tier") Object.assign(p, { write_tier: "T2", named_decision: true });
  assert.equal(nativePrepared(p, original, scope, purpose), null);
});

test("UNKNOWN replays the identical original confirmed command/key/token only on explicit recovery", async () => {
  const c = prepared(command()).command, sent: unknown[] = []; let attempt = 0;
  const api = async <T>(path: string, body?: unknown) => { assert.equal(path, "v1/commands"); sent.push(body); if (attempt++ === 0) throw new Error("response lost"); return { id: id(50), subject_id: id(10), subject_revision: 1, subject_type: "pilot_run", operation: c.operation } as T; };
  const waiting = { stage: "execute" as const, command: c };
  await assert.rejects(runNativeRequest(api, waiting, scope, purpose, () => assert.fail(), () => true), /response lost/);
  assert.equal(sent.length, 1);
  assert.equal((await runNativeRequest(api, waiting, scope, purpose, () => assert.fail(), () => true))?.stage, "saved");
  assert.equal(sent[0], c); assert.equal(sent[1], c);
});

test("scope disposal after inputs blocks all later preview and writes", async () => {
  const c = command(); let active = true, count = 0;
  const answer = await runNativeRequest(async <T>() => { count++; active = false; return { command: c, review: review(c) } as T; }, { stage: "inputs", command: c }, scope, purpose, () => assert.fail(), () => active);
  assert.equal(answer, null); assert.equal(count, 1);
});

test("local drafts and UNKNOWN restore only the exact principal/product/project and fixed command material", () => {
  const local = blankNativeLocal(scope), c = prepared(command()).command;
  local.create = { ...local.create, pilotId: id(10), lotId: id(12), source, visibility: "private" };
  local.pending = { stage: "execute", command: c };
  assert.deepEqual(restoreNativeLocal(local, scope), local);
  for (const changed of [{ ...scope, principalId: id(51) }, { ...scope, projectId: id(52) }, { ...scope, productId: id(53) }]) assert.equal(restoreNativeLocal(local, changed), null);
  const other = structuredClone(local); other.create.source = { ...source, revision: 2 };
  assert.equal(restoreNativeLocal(other, scope), null);
});

test("supported original statistics JSON binds only its actual complete line and retains criterion whitespace", async () => {
  const statistics = { site: "合成线", original_timezone: "Asia/Shanghai", window_start: "2026-10-17T09:00:00Z", window_end: "2026-10-17T10:00:00Z", cohort_mode: "entire_lot", samples: [], statistics_basis_key: "原始固定口径", criterion_id: id(60), criterion_revision: 1, criterion_text: "  保留判据空格  ", minimum_sample: 2, operation_key: "assemble", operational_scope: null, source };
  const bytes = document(nativeOriginalStatistics(id(10), statistics));
  const imported = await importNativeStatistics(bytes, 1, id(10));
  assert.equal(imported.criterion_text, statistics.criterion_text); assert.match(imported.source.position, /^line:1;quote_sha256:[a-f0-9]{64}$/);
  assert.notEqual(imported.source.position, source.position);
  await assert.rejects(importNativeStatistics(bytes, 1, id(61)), /Pilot/);
});

test("real original result import records exact values; changed UI counts require a different matching original", async () => {
  const item = pilot(), raw = record(), bytes = document(nativeOriginalResult(item.pilot.id, raw));
  const value = await importNativeResult(bytes, 1, item);
  await requireNativeOriginal(value, item.pilot.id, [bytes]);
  assert.equal(value.observed.source, value.source);
  value.counts!.final_good = 9;
  await assert.rejects(requireNativeOriginal(value, item.pilot.id, [bytes]), /原文不一致/);
  const newer = structuredClone(item); newer.current = { revision: 2, epoch: 2, latest_observation_id: id(70) };
  await assert.rejects(importNativeResult(bytes, 1, newer), /当前Pilot版本/);
});

test("operational original uses actual typed decimal and UTC defaults without rewriting the selected source", async () => {
  const statistics = { site: "合成线", original_timezone: "Asia/Shanghai", window_start: "2026-10-17T09:00:00Z", window_end: "2026-10-17T10:00:00Z", cohort_mode: "entire_lot", samples: [], statistics_basis_key: "原始固定口径", criterion_id: id(60), criterion_revision: 1, criterion_text: "固定判据", minimum_sample: 2, operation_key: "assemble", operational_scope: { purpose, quantity: "2.00", unit: "ea", site: "合成线", window: { start: "2026-10-17T17:00:00+08:00", finish: "2026-10-17T18:00:00+08:00", original_timezone: "Asia/Shanghai" } }, source };
  const original = nativeOriginalStatistics(id(10), statistics), bytes = document(original);
  const adopted = await importNativeStatistics(bytes, 1, id(10));
  assert.equal((adopted.operational_scope as Record<string, unknown>).quantity, "2");
  assert.equal(statistics.operational_scope.quantity, "2.00");
  const altered = structuredClone(original) as { statistics: { operational_scope: { quantity: string } } };
  altered.statistics.operational_scope.quantity = "2.00";
  await assert.rejects(importNativeStatistics(document(altered), 1, id(10)), /typed默认字段/);
});

test("exception original must retain typed issue:null even though recursive source/disposition are omitted", async () => {
  const item = pilot(), raw = record(); raw.exceptions = [{ key: "unlinked", description: "实际异常，关联问题未知", source }];
  const original = nativeOriginalResult(item.pilot.id, raw) as { record: { exceptions: Record<string, unknown>[] } };
  assert.equal(original.record.exceptions[0].issue, null);
  assert.equal("source" in original.record.exceptions[0], false); assert.equal("disposition" in original.record.exceptions[0], false);
  assert.equal((await importNativeResult(document(original), 1, item)).exceptions[0].issue, null);
  delete original.record.exceptions[0].issue;
  await assert.rejects(importNativeResult(document(original), 1, item), /完整原文值/);
});

test("native read preserves immutable root and full ordered corrections without claiming qualification", () => {
  const item = pilot(); assert.equal(nativeItem(item, scope.projectId), true);
  assert.equal(nativeItem({ ...item, start_authorized: true }, scope.projectId), false);
  assert.equal(nativeItem(item, id(71)), false);
  item.current.revision = 2; item.current.epoch = 2; item.current.latest_observation_id = id(20);
  assert.equal(nativeItem(item, scope.projectId), false); // Head without actual immutable observation.
});
