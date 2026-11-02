import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import {
  appendChangeHistory, blankQualityLocal, blankQualityWork, changeCreatePayload, changeRefKey, createFailurePayload, emptyChanges, emptyQuality, graphCaptureRequest, impactPayload, issuePayload, issueReferenceOptions, mapChangeReading, mapIssueReading, qualityCapability, qualityCommand, qualityEvent, qualityIndexScope, qualityPayloadReads, qualityReads, qualitySame, qualitySource, readQualityContext, restoreQualityLocal, selectQualityIndexed, selectQualityScope, validGraphCapture, validQualityInputs, validQualityPreview, validQualityReceipt,
  type ChangeRow, type GraphCapture, type QualityApi, type QualityContext, type QualityFailure, type QualityIndexedSelection, type QualityIssue, type QualitySource, type QualityPreview,
} from "./build-quality-loop-view";
import { emptyResults } from "./build-results-view";
import type { DefinitionSource } from "./product-view";

const hash = "a".repeat(64), source: QualitySource = { id: "source", revision: 1, kind: "artifact", position: `line:1;quote_sha256:${hash}` }, reads = [{ artifact_id: "source", expected_revision: 1 }];
const failure = (): QualityFailure => ({ failure: { identity: "fixed-failure", run: { id: "run-logical", revision: 3 }, measurement_id: "measurement", coverage: { sample_id: "sample", item_id: "pressure" }, sample: { id: "sample", revision: 1, actual_configuration: { id: "actual", revision: 1 } }, build: { id: "build", revision: 1, engineering_configuration: { id: "engineering", revision: 1 }, manufacturing_configuration: { id: "manufacturing", revision: 1 } }, source, method: source, criterion: source, nature: "synthetic" }, available: true, run_status: "results_pending", measurement: { raw_value: "152", unit: "PSI" }, event_ids: ["exact-event"], required_source_read_set: reads, capabilities: { "quality.issue.create": true } });
const issue = (): QualityIssue => ({ id: "issue-version", issue_id: "issue-logical", revision: 2, is_current: true, source_status: "current", issue: { title: "固定压力失败", status: "triaged", failures: [{ identity: "fail-a" }, { identity: "fail-b" }], risk: null, containment: [], aliases: [], history: [] }, failures: [], capabilities: { "quality.issue.triage": true, "quality.issue.merge": true, "quality.issue.containment.record": true, "quality.capa.draft": true }, authority: {}, required_source_read_set: reads, followup_needs: [] });
const change = (): ChangeRow => ({ id: "change-version", change_id: "change-logical", revision: 1, current: true, source_status: "current", request: { title: "结构与工序提案", reason: "固定压力失败", status: "draft", roots: [{ id: "issue-logical", revision: 2, kind: "issue", key: null }], references: [], sources: [source], audience: ["owner"] }, capabilities: { impact_compute: true }, authority: {}, required_source_read_set: reads });
const capture = (): GraphCapture => ({ id: "capture", revision: 1, change_id: "change-logical", change_revision: 1, graph: {}, current: true, expires_at: "2026-10-02T18:10:00Z", required_source_read_set: reads, impact_payload: { change_id: "change-logical", expected_change_revision: 1, snapshot: { id: "capture", revision: 1, kind: "graph_snapshot", key: null }, hypotheses: [] } });
const command = () => qualityCommand({ id: "product", revision: 3 }, "quality.issue.triage", { issue_id: "issue-logical", expected_issue_revision: 2, reason: "按当前政策分诊" }, reads, "command", "same-key");
const preview = (): QualityPreview => { const original = command(); return { command: { ...original, payload: { ...original.payload, confirmation_token: "token".repeat(8) } }, expires_at: "2026-10-02T18:10:00Z", review: { before: { issue: { id: "issue-logical", revision: 2, title: "固定压力失败" } }, after: { issue: { id: "issue-logical", revision: 3 } }, effect: "只具名分诊，不改原测量" } }; };
const now = Date.parse("2026-10-02T18:00:00Z");

test("missing capability and unknown availability cannot become a failure-create permission", () => { const row = failure(); row.capabilities = {}; assert.equal(qualityCapability(row.capabilities, "quality.issue.create"), false); assert.throws(() => createFailurePayload(row, "exact-event", "压力失败", "private")); row.capabilities = { "quality.issue.create": true }; row.available = false; assert.throws(() => createFailurePayload(row, "exact-event", "压力失败", "private")); });
test("fixed failure creation uses semantic Run ID and exact delivery event, no client risk or result", () => { assert.deepEqual(createFailurePayload(failure(), "exact-event", "压力失败", "private"), { run_id: "run-logical", measurement_id: "measurement", event_id: "exact-event", title: "压力失败", visibility: "private" }); assert.throws(() => createFailurePayload(failure(), "invented-event", "压力失败", "private")); });
test("precise source hashes the complete original UTF-8 line including spaces", async () => { const quote = "  压力 152 PSI  ", doc = { id: "doc", revision: 4, title: "原件", content: `${quote}\n第二行`, status: "active", visibility: "private" } as DefinitionSource; const ref = await qualitySource(doc, 1); assert.equal(ref.position, `line:1;quote_sha256:${createHash("sha256").update(quote).digest("hex")}`); assert.equal(ref.revision, 4); await assert.rejects(qualitySource({ ...doc, status: "withdrawn" }, 1)); });
test("source read-set never silently truncates or combines revisions", () => { assert.equal(qualityReads(Array.from({ length: 25 }, (_, i) => ({ artifact_id: `doc-${i}`, expected_revision: 1 }))).length, 25); assert.throws(() => qualityReads(reads, [{ artifact_id: "source", expected_revision: 2 }]), /两个版本/); assert.deepEqual(qualityReads(reads, reads), reads); });
test("payload read-set includes nested actual evidence and hypotheses, not unrelated selected rows", () => { assert.deepEqual(qualityPayloadReads({ action: { evidence: [source], at: { source } }, hypotheses: [{ text: "候选", sources: [source] }], unrelated_id: "other" }), reads); assert.throws(() => qualityPayloadReads({ sources: [{ ...source, position: "line:1" }] })); });
test("actual containment clock preserves the original ISO offset and cannot be defaulted or future", () => { const event = qualityEvent({ occurredAt: "2026-10-02T10:00:00-07:00", timezone: "America/Los_Angeles", source }, now); assert.equal(event.occurred_at, "2026-10-02T10:00:00-07:00"); assert.equal(event.effective_at, null); assert.throws(() => qualityEvent({ occurredAt: "", timezone: "UTC", source }, now)); assert.throws(() => qualityEvent({ occurredAt: "2026-10-02T20:00:00Z", timezone: "UTC", source }, now)); assert.throws(() => qualityEvent({ occurredAt: "2026-10-02T10:00:00", timezone: "UTC", source }, now)); assert.throws(() => qualityEvent({ occurredAt: "not-a-timeZ", timezone: "UTC", source }, now)); });
test("actual containment retains reported microseconds and original UTC or regional offsets without rewriting", () => {
  const utc = "2026-10-03T06:25:03.160086+00:00", regional = "2026-10-02T23:25:03.160086-07:00", later = Date.parse("2026-10-03T06:25:04Z");
  for (const [occurredAt, timezone] of [[utc, "UTC"], [regional, "America/Los_Angeles"]]) {
    const event = qualityEvent({ occurredAt, timezone, source }, later);
    assert.equal(event.occurred_at, occurredAt); assert.equal(event.original_timezone, timezone); assert.deepEqual(event.source, source);
    const historical = occurredAt.replace(/^2026/, "2020"), work = { ...blankQualityWork(), containmentId: "completed-action", containmentText: "本人实际隔离待核件", sources: [source], contained: { occurredAt: historical, timezone, source } };
    const payload = issuePayload("quality.issue.containment.record", issue(), work, "owner", [], []);
    assert.equal(((payload.action as Record<string, unknown>).at as Record<string, unknown>).occurred_at, historical);
  }
});
test("T1 prepared command binds original IDs, payload, read-set and issue revision", () => { const value = preview(); assert.equal(validQualityPreview(value, command(), now), true); assert.equal(validQualityPreview({ ...value, command: { ...value.command, idempotency_key: "new-key" } }, command(), now), false); assert.equal(validQualityPreview({ ...value, command: { ...value.command, source_read_set: [] } }, command(), now), false); assert.equal(validQualityPreview({ ...value, review: { ...value.review, before: { id: "other-issue", revision: 2 } } }, command(), now), false); });
test("T1 rejects changed content and expired confirmation", () => { const value = preview(); assert.equal(validQualityPreview({ ...value, command: { ...value.command, payload: { ...value.command.payload, reason: "换一个原因" } } }, command(), now), false); assert.equal(validQualityPreview(value, command(), now + 11 * 60 * 1000), false); });
test("T1 offset-to-UTC normalization accepts an identical event but not a new instant", () => { const original = { ...command(), operation: "quality.issue.containment.record" as const, payload: { issue_id: "issue-logical", expected_issue_revision: 2, action: { at: { occurred_at: "2026-10-02T10:00:00-07:00", effective_at: null } } } }; const value = preview(); value.command = { ...original, payload: { ...original.payload, action: { at: { occurred_at: "2026-10-02T17:00:00Z", effective_at: null } }, confirmation_token: "t".repeat(40) } }; assert.equal(validQualityPreview(value, original, now), true); value.command.payload.action = { at: { occurred_at: "2026-10-02T17:01:00Z", effective_at: null } }; assert.equal(validQualityPreview(value, original, now), false); });
test("T1 preserves microsecond identity across offsets and rejects a same-millisecond altered event", () => {
  const occurred_at = "2026-10-02T10:00:00.160086-07:00", original = { ...command(), operation: "quality.issue.containment.record" as const, payload: { issue_id: "issue-logical", expected_issue_revision: 2, action: { at: { occurred_at, effective_at: null } } } }, value = preview();
  value.command = { ...original, payload: { ...original.payload, confirmation_token: "t".repeat(40) } };
  for (const same of ["2026-10-02T17:00:00.160086Z", "2026-10-02T17:00:00.160086+00:00", "2026-10-02T17:00:00.1600860Z"]) {
    value.command.payload.action = { at: { occurred_at: same, effective_at: null } };
    assert.equal(validQualityPreview(value, original, now), true);
  }
  for (const changed of ["2026-10-02T17:00:00.160000Z", "2026-10-02T17:00:00.160087Z"]) {
    value.command.payload.action = { at: { occurred_at: changed, effective_at: null } };
    assert.equal(validQualityPreview(value, original, now), false);
  }
  assert.equal(original.payload.action.at.occurred_at, occurred_at);
});
test("inputs must return the same operation and an explicit allowed boolean", () => { assert.equal(validQualityInputs({ operation: command().operation, allowed: true, required_source_read_set: reads }, command()), true); assert.equal(validQualityInputs({ operation: command().operation, required_source_read_set: reads }, command()), false); assert.equal(validQualityInputs({ operation: "change.request.create", allowed: true, required_source_read_set: reads }, command()), false); });
test("common receipts use operation and immutable version family, including semantic replay of the old receipt", () => { const receipt = { id: "original-receipt", operation: "quality.issue.triage", subject_id: "new-version", subject_type: "quality_issue" }; assert.equal(validQualityReceipt(receipt, command()), true); assert.equal(validQualityReceipt({ ...receipt, subject_type: "change_request" }, command()), false); assert.equal(validQualityReceipt({ ...receipt, operation: "quality.capa.draft" }, command()), false); assert.equal(validQualityReceipt({ ...receipt, id: "" }, command()), false); });
test("named triage does not expose a client risk or independence bypass", () => { const work = blankQualityWork(); work.reason = "具名核对当前政策"; assert.deepEqual(issuePayload("quality.issue.triage", issue(), work, "owner", [], []), { issue_id: "issue-logical", expected_issue_revision: 2, reason: work.reason }); });
test("actual containment requires its event to be part of evidence and binds the current named executor", () => { const work = blankQualityWork(); work.containmentId = "action"; work.containmentText = "实际隔离本批待核件"; work.contained = { occurredAt: "2020-01-01T10:00:00Z", timezone: "UTC", source }; work.sources = [source]; const payload = issuePayload("quality.issue.containment.record", issue(), work, "current-person", [], []); const action = payload.action as Record<string, unknown>; assert.equal(action.executor_id, "current-person"); assert.equal("reason" in payload, false); work.sources = [{ ...source, id: "other" }]; assert.throws(() => issuePayload("quality.issue.containment.record", issue(), work, "owner", [], [])); });
test("CAPA draft covers all failures, keeps completion null and validates selected responsible people", () => { const work = blankQualityWork(); work.capaId = "capa"; work.hypotheses = [{ text: "有来源的根因候选", sources: [source] }]; work.actions = [{ id: "action", kind: "corrective", text: "准备新工艺验证", executorId: "named-person" }]; work.method = "以独立下一轮验证"; work.acceptance = "覆盖全部原失败"; work.observationUntil = "2026-11-01T17:00:00-07:00"; const payload = issuePayload("quality.capa.draft", issue(), work, "owner", [], [{ id: "named-person" }]); assert.deepEqual((payload.requirement as Record<string, unknown>).required_failure_ids, ["fail-a", "fail-b"]); assert.equal((payload.actions as Record<string, unknown>[])[0].completion, null); assert.throws(() => issuePayload("quality.capa.draft", issue(), work, "owner", [], [])); });
test("CAPA cannot overwrite old drafts or build from an untriaged/historical Issue", () => { const row = issue(), work = blankQualityWork(); row.issue.capa = { id: "old" }; assert.throws(() => issuePayload("quality.capa.draft", row, work, "owner", [], [])); row.issue.capa = null; row.is_current = false; assert.throws(() => issuePayload("quality.issue.triage", row, { ...work, reason: "核对" }, "owner", [], [])); });
test("merge keeps source logical identities and revisions and rejects CAPA-bearing origins", () => { const target = issue(), original = { ...issue(), id: "source-version", issue_id: "source-logical", revision: 4, issue: { ...issue().issue, title: "另一独立失败" } }, work = { ...blankQualityWork(), mergeIds: ["source-logical"], reason: "同范围保留两失败归并" }; assert.deepEqual(issuePayload("quality.issue.merge", target, work, "owner", [original], []).sources, [{ id: "source-logical", revision: 4 }]); (original.issue as Record<string, unknown>).capa = { id: "old-capa" }; assert.throws(() => issuePayload("quality.issue.merge", target, work, "owner", [original], [])); });
test("Issue/CAPA change references use the exact Issue aggregate and CAPA key", () => { const row = issue(); row.issue.capa = { id: "embedded-capa" }; const options = issueReferenceOptions(row); assert.deepEqual(options[1].ref, { id: "issue-logical", revision: 2, kind: "capa", key: "embedded-capa" }); });
test("change creation only picks returned real references, never client change ID or graph completeness", () => { const options = issueReferenceOptions(issue()), work = { ...blankQualityWork(), changeTitle: "工程与制造双线提案", changeReason: "依据固定失败核对", rootKeys: [changeRefKey(options[0].ref)], sources: [source] }; const payload = changeCreatePayload(work, options); assert.equal("change_id" in payload, false); assert.equal("graph" in payload, false); assert.equal("coverage_complete" in payload, false); assert.throws(() => changeCreatePayload({ ...work, rootKeys: ["invented-ref"] }, options)); });
test("graph capture is fixed to the current eligible change and keeps caller capture key", () => { assert.deepEqual(graphCaptureRequest(change(), "核对真实影响范围", "same-capture-key"), { capture_key: "same-capture-key", change_id: "change-logical", expected_change_revision: 1, reason: "核对真实影响范围" }); assert.throws(() => graphCaptureRequest({ ...change(), current: false }, "历史", "same-capture-key")); });
test("impact cannot refresh an expired graph or silently use another change version", () => { assert.deepEqual(impactPayload(change(), capture(), [], now).snapshot, capture().impact_payload.snapshot); assert.throws(() => impactPayload(change(), capture(), [], now + 11 * 60 * 1000)); assert.throws(() => impactPayload({ ...change(), revision: 2 }, capture(), [], now)); });
test("legacy readonly CAPA refuses unknown risk/independence instead of coercing false", () => { const row = issue(); row.failures = [failure()]; row.issue.failures = [row.failures[0].failure]; row.issue.capa = { id: "capa", hypotheses: [], actions: [], requirement: { method: "后续独立验证", acceptance: "覆盖固定失败", observation_until: "2026-11-01T00:00:00Z", required_failure_ids: ["fixed-failure"] } }; assert.equal(mapIssueReading(row, null, new Map()), null); assert.equal(mapIssueReading(row, { id: "policy", revision: 1, independent_verification: false }, new Map()), null); });
test("change readonly mapping keeps unknown facets and never creates an approved Order", () => { const row = change(); row.request.assessments = [{ id: "assessment", graph: { nodes: [], edges: [], expires_at: "2099-01-01T00:00:00Z" }, known: [], unknown: [{ node: null, facet: "production_switch", reason: "制造切换节点未接入" }], hypotheses: [] }]; const mapped = mapChangeReading(row, new Map()); assert.equal(mapped?.order, null); assert.equal(mapped?.impact?.unknowns[0].reason, "制造切换节点未接入"); assert.deepEqual(mapped?.impact?.unknowns[0].missing, ["制造切换"]); });
test("local recovery is bound to exact actor/product and retains the complete prepared command", () => { const local = blankQualityLocal(), prepared = preview().command; local.pending = { stage: "execute", command: prepared }; const saved = { schema_version: 1, product_id: "product", principal_id: "owner", ...local }; assert.deepEqual(restoreQualityLocal(saved, "product", "owner")?.pending, local.pending); assert.equal(restoreQualityLocal(saved, "other-product", "owner"), null); assert.equal(restoreQualityLocal(saved, "product", "other-owner"), null); });
test("switching selected scope isolates CAPA IDs and preserves prior local drafts", () => { const a = { ...blankQualityLocal(), selectedBuildId: "build", selectedRunId: "run", selectedIssueId: "issue-a", work: { ...blankQualityWork(), capaId: "a-capa", changeTitle: "未丢草稿" } }, b = selectQualityScope(a, { selectedIssueId: "issue-b" }); assert.equal(b.work.capaId, ""); const back = selectQualityScope(b, { selectedIssueId: "issue-a" }); assert.equal(back.work.capaId, "a-capa"); assert.equal(back.work.changeTitle, "未丢草稿"); });
test("object key order is immaterial while array order and content remain semantic", () => { assert.equal(qualitySame({ text: "原值", source: { id: "one", revision: 1 } }, { source: { revision: 1, id: "one" }, text: "原值" }), true); assert.equal(qualitySame(["a", "b"], ["b", "a"]), false); });
test("empty selection only loads readable Builds and workspace, not global history", async () => { const calls: string[] = [], api: QualityApi = async <T>(path: string): Promise<T> => { calls.push(path); return (path.endsWith("/builds") ? { items: [] } : { sources: [] }) as T; }; const result = await readQualityContext(api, "product", blankQualityLocal(), () => true); assert.deepEqual(result?.quality, emptyQuality); assert.deepEqual(result?.changes, emptyChanges); assert.equal(calls.length, 2); });
test("read superseded cancellation is quiet, a simultaneous genuine failure remains visible", async () => { const cancelled = { code: "READ_SUPERSEDED" }, api: QualityApi = async <T>(): Promise<T> => { throw cancelled; }; assert.equal(await readQualityContext(api, "product", blankQualityLocal(), () => true), null); const mixed: QualityApi = async <T>(path: string): Promise<T> => { throw path.endsWith("/builds") ? { status: 503 } : cancelled; }; await assert.rejects(readQualityContext(mixed, "product", blankQualityLocal(), () => true), error => (error as { status: number }).status === 503); });
test("scope generation discards a late old read and private authorization failure is retained", async () => { const api: QualityApi = async <T>(path: string): Promise<T> => (path.endsWith("/builds") ? { items: [] } : { sources: [] }) as T; assert.equal(await readQualityContext(api, "product", blankQualityLocal(), () => false), null); const denied: QualityApi = async <T>(): Promise<T> => { throw { status: 403 }; }; await assert.rejects(readQualityContext(denied, "product", blankQualityLocal(), () => true), error => (error as { status: number }).status === 403); });
test("actual quality T1 before/after maps bind the target and preserve all merge origins", () => { const original = command(), value = preview(); value.review.before = { "issue-logical": { id: "issue-logical", revision: 2 }, "source-logical": { id: "source-logical", revision: 4 } }; value.review.after = { "issue-logical": { id: "issue-logical", revision: 3 }, "source-logical": { id: "source-logical", revision: 5, merged_into: "issue-logical" } }; assert.equal(validQualityPreview(value, original, now), true); (value.review.after as Record<string, unknown>)["issue-logical"] = { id: "issue-logical", revision: 2 }; assert.equal(validQualityPreview(value, original, now), false); });
test("human impact hypotheses cannot be rendered as the legacy AI hypothesis category", () => { const row = change(); row.request.assessments = [{ graph: { edges: [] }, known: [], unknown: [], hypotheses: [{ text: "人工候选", sources: [source] }] }]; assert.equal(mapChangeReading(row, new Map()), null); });
test("malformed local nested drafts cannot be restored as trusted form state", () => { const local = blankQualityLocal(), saved = { schema_version: 1, product_id: "product", principal_id: "owner", ...local, drafts: { other: { contained: null } } }; assert.equal(restoreQualityLocal(saved, "product", "owner"), null); });
test("known server policy is shown as its exact risk and independence, without defaulting unknown", () => { const row = issue(); row.failures = [failure()]; row.issue.failures = [row.failures[0].failure]; row.issue.risk = "high"; row.issue.capa = { id: "capa", hypotheses: [], actions: [], requirement: { method: "独立后续验证", acceptance: "覆盖固定失败", observation_until: "2026-11-01T00:00:00Z", required_failure_ids: ["fixed-failure"] } }; const mapped = mapIssueReading(row, { id: "policy", revision: 2, independent_verification: true }, new Map()); assert.equal(mapped?.capa?.verificationRequirement.highRisk, true); assert.equal(mapped?.capa?.verificationRequirement.independentRequired, true); });
test("deep reads stay scoped to the explicit Build, logical Run and Issue, without global scans", async () => {
  const calls: string[] = [], local = { ...blankQualityLocal(), selectedBuildId: "build", selectedRunId: "run-logical", selectedIssueId: "issue-logical" };
  const results = { ...emptyResults, runs: [{ id: "run-version", run_id: "run-logical", request_id: "request", revision: 3, build: { id: "build", revision: 1 }, run_snapshot: {}, basis_sha256: hash, required_source_read_set: [] }] };
  const api: QualityApi = async <T>(path: string): Promise<T> => { calls.push(path); return (path.endsWith("/builds") ? { items: [{ id: "build" }] } : path.endsWith("/workspace") ? { sources: [] } : path.includes("verification-results?") ? results : path.includes("quality-execution?") ? { ...emptyQuality, issues: [issue()], failures: [failure()] } : emptyChanges) as T; };
  await readQualityContext(api, "product", local, () => true);
  assert.equal(calls[2], "v1/products/product/verification-results?build_id=build"); assert.equal(calls[3], "v1/products/product/quality-execution?build_id=build&run_id=run-logical"); assert.equal(calls[4], "v1/products/product/change-execution?issue_id=issue-logical"); assert.equal(calls.length, 5);
});
test("a Build switch during the late scoped result read prevents any old quality or change request", async () => {
  let current = true; const calls: string[] = [], local = { ...blankQualityLocal(), selectedBuildId: "build", selectedRunId: "run-logical" };
  const api: QualityApi = async <T>(path: string): Promise<T> => { calls.push(path); if (path.includes("verification-results?")) { current = false; return emptyResults as T; } return (path.endsWith("/builds") ? { items: [{ id: "build" }] } : { sources: [] }) as T; };
  assert.equal(await readQualityContext(api, "product", local, () => current), null); assert.equal(calls.some(path => path.includes("quality-execution")), false);
});
test("capture response binds the exact change version and saved graph seed, never another candidate", () => { const row = capture(), request = graphCaptureRequest(change(), "核对真实图", "same-capture"), response = { capture: row, impact_payload: row.impact_payload, required_source_read_set: reads }; assert.equal(validGraphCapture(response, request), true); assert.equal(validGraphCapture({ ...response, impact_payload: { ...row.impact_payload, snapshot: { id: "other", revision: 1, kind: "graph_snapshot", key: null } } }, request), false); assert.equal(validGraphCapture({ ...response, capture: { ...row, change_revision: 2 } }, request), false); });

const indexIdentity = { productId: "product", principalId: "owner", productRevision: 3 };
function indexedWork() {
  const local = { ...blankQualityLocal(), selectedBuildId: "build", selectedRunId: "run-logical", selectedIssueId: "issue-logical" };
  const historicalIssue = { ...issue(), id: "issue-old-version", revision: 1, is_current: false, capabilities: {} };
  const historicalChange = { ...change(), id: "change-old-version", revision: 1, current: false, capabilities: {} };
  const context: QualityContext = {
    builds: [{ id: "build" }] as QualityContext["builds"], sources: [],
    results: { ...emptyResults, runs: [{ id: "run-version", run_id: "run-logical", request_id: "request", revision: 3, build: { id: "build", revision: 1 }, run_snapshot: {}, basis_sha256: hash, required_source_read_set: [] }] as unknown as QualityContext["results"]["runs"] },
    quality: { ...emptyQuality, issues: [issue(), historicalIssue], failures: [failure()], current_by_issue: { "issue-logical": { issue_version_id: "issue-version", revision: 2 } } },
    changes: { ...emptyChanges, changes: [{ ...change(), revision: 2 }, historicalChange], current_by_change: { "change-logical": { version_id: "change-version", revision: 2 } } },
  };
  return { local, context, checked: qualityIndexScope(indexIdentity, local) };
}
test("four indexed selection kinds use the returned scope without repeating its five reads", async () => {
  const setup = indexedWork(), calls: string[] = [];
  const api: QualityApi = async <T>(path: string): Promise<T> => {
    calls.push(path);
    return (path.endsWith("/builds") ? { items: setup.context.builds } : path.endsWith("/workspace") ? { sources: setup.context.sources } : path.includes("verification-results?") ? setup.context.results : path.includes("quality-execution?") ? setup.context.quality : setup.context.changes) as T;
  };
  const context = await readQualityContext(api, "product", setup.local, () => true); assert.ok(context);
  let local = setup.local;
  for (const patch of [{ selectedFailureId: "fixed-failure" }, { selectedIssueVersionId: "issue-old-version" }, { selectedChangeId: "change-logical", selectedChangeVersionId: "" }, { selectedChangeVersionId: "change-old-version" }]) {
    const next = selectQualityIndexed(local, patch, context, setup.checked, qualityIndexScope(indexIdentity, local)); assert.ok(next); local = next;
  }
  assert.equal(calls.length, 5); assert.equal(local.selectedFailureId, "fixed-failure"); assert.equal(local.selectedIssueVersionId, "issue-old-version"); assert.equal(local.selectedChangeVersionId, "change-old-version");
});
test("scope, actor, product revision, and a missing checked index all require a fresh read", () => {
  const { local, context, checked } = indexedWork(), patch = { selectedFailureId: "fixed-failure" };
  for (const identity of [{ ...indexIdentity, productId: "other-product" }, { ...indexIdentity, principalId: "other-person" }, { ...indexIdentity, productRevision: 4 }]) assert.equal(selectQualityIndexed(local, patch, context, checked, qualityIndexScope(identity, local)), null);
  for (const field of ["selectedBuildId", "selectedRunId", "selectedIssueId"] as const) {
    const other = { ...local, [field]: "another-scope" };
    assert.equal(selectQualityIndexed(other, patch, context, checked, qualityIndexScope(indexIdentity, other)), null);
  }
  assert.equal(selectQualityIndexed(local, patch, context, null, checked), null);
  assert.equal(selectQualityIndexed(local, patch, { ...context, builds: [] }, checked, checked), null);
  assert.equal(selectQualityIndexed(local, patch, { ...context, results: emptyResults }, checked, checked), null);
});
test("indexed selection rejects invented or cross-logical failure and history identities", () => {
  const { local, context, checked } = indexedWork();
  for (const patch of [{ selectedFailureId: "not-returned" }, { selectedIssueVersionId: "not-returned" }, { selectedChangeId: "not-returned" }, { selectedChangeId: "change-logical", selectedChangeVersionId: "not-returned" }]) assert.throws(() => selectQualityIndexed(local, patch, context, checked, checked));
  const cross = { ...context, quality: { ...context.quality, failures: [{ ...failure(), failure: { ...failure().failure, run: { id: "other-run", revision: 3 } } }], issues: [...context.quality.issues, { ...issue(), id: "foreign-issue-version", issue_id: "foreign-issue" }] }, changes: { ...context.changes, changes: [...context.changes.changes, { ...change(), id: "foreign-change-version", change_id: "foreign-change" }] } };
  assert.throws(() => selectQualityIndexed(local, { selectedFailureId: "fixed-failure" }, cross, checked, checked));
  assert.throws(() => selectQualityIndexed(local, { selectedIssueVersionId: "foreign-issue-version" }, cross, checked, checked));
  assert.throws(() => selectQualityIndexed(local, { selectedChangeId: "change-logical", selectedChangeVersionId: "foreign-change-version" }, cross, checked, checked));
});
test("all pending modes keep their exact original request locked against indexed selection", () => {
  const { local, context, checked } = indexedWork();
  for (const pending of [{ stage: "inputs" as const, command: command() }, { stage: "preview" as const, command: command() }, { stage: "execute" as const, command: preview().command }, { stage: "capture" as const, request: graphCaptureRequest(change(), "固定图原请求", "same-capture") }]) {
    const locked = { ...local, pending }, before = structuredClone(locked);
    assert.throws(() => selectQualityIndexed(locked, { selectedFailureId: "fixed-failure" }, context, checked, checked), /原请求/);
    assert.deepEqual(locked, before); assert.equal(locked.pending, pending);
  }
});
test("selection discards unsent old-target material without changing server facts or other scope drafts", () => {
  const { local, context, checked } = indexedWork(), material = { ...blankQualityWork(), eventId: "exact-event", capaId: "old-draft", sources: [source], contained: { occurredAt: "2026-10-03T06:25:03.160086+00:00", timezone: "UTC", source } }, other = { ...blankQualityWork(), changeTitle: "另一个问题仍保留" };
  const draft = { ...local, work: material, drafts: { [checked.selectionKey]: material, "other-scope": other } }, before = structuredClone(context);
  const next = selectQualityIndexed(draft, { selectedFailureId: "fixed-failure" }, context, checked, checked); assert.ok(next);
  assert.deepEqual(next.work, blankQualityWork()); assert.equal(checked.selectionKey in next.drafts, false); assert.equal(next.drafts["other-scope"], other); assert.equal(draft.work, material); assert.deepEqual(context, before);
  const unchanged = selectQualityIndexed(next, { selectedFailureId: "fixed-failure" }, context, checked, checked); assert.equal(unchanged, next);
});
test("local history display preserves false current capabilities and cannot promote an old version", () => {
  const { local, context, checked } = indexedWork();
  const selected = selectQualityIndexed(local, { selectedIssueVersionId: "issue-old-version", selectedChangeId: "change-logical", selectedChangeVersionId: "change-old-version" }, context, checked, checked); assert.ok(selected);
  const historicalIssue = context.quality.issues.find(row => row.id === selected.selectedIssueVersionId)!, historicalChange = context.changes.changes.find(row => row.id === selected.selectedChangeVersionId)!;
  assert.equal(historicalIssue.is_current, false); assert.deepEqual(historicalIssue.capabilities, {}); assert.equal(historicalChange.current, false); assert.deepEqual(historicalChange.capabilities, {});
  assert.throws(() => issuePayload("quality.issue.triage", historicalIssue, { ...blankQualityWork(), reason: "不可把历史变当前" }, "owner", [], []));
  assert.throws(() => graphCaptureRequest(historicalChange, "不可沿用旧版", "original-key"));
});
test("remote scope or arbitrary form edits cannot enter the local indexed-only path", () => {
  const { local, context, checked } = indexedWork();
  for (const patch of [{ selectedBuildId: "other-build" }, { selectedRunId: "other-run" }, { selectedIssueId: "other-issue" }, { work: blankQualityWork() }, { selectedFailureId: 0 }]) assert.throws(() => selectQualityIndexed(local, patch as unknown as QualityIndexedSelection, context, checked, checked));
});

test("history pagination preserves records and uses only the fresh server Current for actions", () => {
  const old = change(), oldCapture = { ...capture(), expires_at: null }, latest = { ...old, id: "new-version", revision: 2 };
  const previous = { ...emptyChanges, changes: [old], captures: [oldCapture], current_by_change: { "change-logical": { version_id: old.id, revision: 1 } } };
  const page = { ...emptyChanges, changes: [latest, { ...old, current: false, capabilities: { impact_compute: false } }], captures: [], current_by_change: { "change-logical": { version_id: latest.id, revision: 2 } }, history_page: { next_cursor: "next-history-page" } };
  const merged = appendChangeHistory(previous, page);
  assert.equal(merged.changes.length, 2);
  assert.equal(merged.changes.find(row => row.id === old.id)?.capabilities.impact_compute, false);
  assert.equal(merged.changes.find(row => row.id === latest.id)?.current, true);
  assert.equal(merged.captures[0].current, false);
  assert.equal(merged.captures[0].expires_at, null);
  assert.equal(previous.captures[0].current, true);
  assert.deepEqual(merged.current_by_change, page.current_by_change);
});

test("project recovery requires the exact saved project and preserves the original unknown command", () => {
  const pending = { stage: "execute", command: preview().command }, saved = { schema_version: 1, product_id: "product", principal_id: "owner", project_id: "project-a", ...blankQualityLocal(), selectedBuildId: "build", selectedRunId: "run-logical", selectedIssueId: "issue-logical", work: { ...blankQualityWork(), reason: "A项目原草稿" }, pending };
  const restored = restoreQualityLocal(saved, "product", "owner", "project-a");
  assert.equal(restored?.work.reason, "A项目原草稿"); assert.deepEqual(restored?.pending, pending);
  assert.equal(restoreQualityLocal(saved, "product", "owner", "project-b"), null);
  assert.equal(restoreQualityLocal(saved, "product", "owner"), null);
  const generic = { ...saved } as Record<string, unknown>; delete generic.project_id;
  assert.equal(restoreQualityLocal(generic, "product", "owner", "project-a"), null);
  assert.deepEqual(restoreQualityLocal(generic, "product", "owner")?.pending, pending);
});
test("project quality reads first narrow Builds and cannot deep-read an excluded saved Build", async () => {
  const calls: string[] = [], { local, context } = indexedWork();
  const api: QualityApi = async <T>(path: string): Promise<T> => { calls.push(path); return (path.includes("/builds?") ? { items: [{ id: "project-a-build" }] } : { sources: [] }) as T; };
  const result = await readQualityContext(api, "product", local, () => true, "project-a");
  assert.deepEqual(result?.builds.map(row => row.id), ["project-a-build"]); assert.deepEqual(result?.quality, emptyQuality);
  assert.deepEqual(calls, ["v1/products/product/builds?project_id=project-a", "v1/products/product/workspace"]);
  calls.length = 0;
  const selected: QualityApi = async <T>(path: string): Promise<T> => { calls.push(path); return (path.includes("/builds?") ? { items: context.builds } : path.endsWith("/workspace") ? { sources: [] } : path.includes("verification-results?") ? context.results : path.includes("quality-execution?") ? context.quality : context.changes) as T; };
  await readQualityContext(selected, "product", local, () => true, "project-a");
  assert.deepEqual(calls.slice(2), ["v1/products/product/verification-results?build_id=build", "v1/products/product/quality-execution?build_id=build&run_id=run-logical", "v1/products/product/change-execution?issue_id=issue-logical"]);
});
test("project changes invalidate a checked display index even for the same product and local selection", () => {
  const { local, context } = indexedWork(), checked = qualityIndexScope({ ...indexIdentity, projectId: "project-a" }, local);
  assert.equal(selectQualityIndexed(local, { selectedFailureId: "fixed-failure" }, context, checked, qualityIndexScope({ ...indexIdentity, projectId: "project-b" }, local)), null);
  assert.equal(selectQualityIndexed(local, { selectedFailureId: "fixed-failure" }, context, checked, qualityIndexScope(indexIdentity, local)), null);
});
