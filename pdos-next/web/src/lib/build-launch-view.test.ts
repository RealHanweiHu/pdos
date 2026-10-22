import test from "node:test";
import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import { blankLaunchEvent, blankLaunchWork, blankLaunchRunWork, launchRunDraftKey, launchFactCoverage, blankLocalLaunch, emptyLaunch, launchAuthority, launchCapability, launchSyntheticAuthority, launchError, launchEvent, launchExactCoverage, launchFactMatches, launchFactPlan, launchPlanPayload, launchReads, launchRunPayload, makeLaunchCommand, normalizeLaunch, readLaunchBuild, restoreLaunch, validLaunchInputs, validLaunchPreview, validLaunchReceipt, type LaunchApi, type LaunchPreview, type LaunchRequest, type LaunchResourceFact, type LaunchRun } from "./build-launch-view";
import type { DefinitionReference } from "./product-view";

const ref: DefinitionReference = { artifact_id: "artifact", expected_revision: 2, line: 3, quote: "实际开测原文记录" };
const window = { start: "2026-10-03T17:00:00Z", finish: "2026-10-03T18:00:00Z", original_timezone: "America/Los_Angeles" };
const pairs = [{ sample_id: "sample-b", item_id: "pressure" }, { sample_id: "sample-a", item_id: "noise" }];
const request = { id: "formal-v2", request_id: "request", revision: 2, title: "已接收压力验证", purpose: "内部测试", build: { id: "build", revision: 1 }, accepted_coverage: pairs, items: [], documents: [], request_snapshot: { status: "accepted" }, status: "accepted", is_current: true, source_status: "current", required_source_read_set: [], capabilities: { run_plan: true } } as LaunchRequest;
const fact = { id: "resource-fact", revision: 3, current: true, state: "active", source_status: "current", nature: "synthetic", required_source_read_set: [], binding: { run_id: "run", request_id: request.request_id, accepted_request_id: request.id, accepted_request_revision: 2, build_id: "build", window, executor_id: "executor", equipment: ref, calibration: ref, environment: "20°C", conditions: "按固定规程", pairs: pairs.map(pair => ({ sample: { id: pair.sample_id }, item_id: pair.item_id })) } } as LaunchResourceFact;
const plan = launchFactPlan(fact);
const run = { id: "run-v1", run_id: "run", revision: 1, request_id: "request", build: { id: "build", revision: 1 }, status: "planned", execution_plan: plan, plan_sha256: "a".repeat(64), run_snapshot: { actual_start: null, coverage: [pairs[1], pairs[0]] }, promise: null, required_source_read_set: [], is_current: true, source_status: "current", capabilities: {} } as LaunchRun;
const at = { occurred_at: "2026-10-03T17:00:00Z", original_timezone: "America/Los_Angeles", effective_at: null, source: { id: ref.artifact_id, revision: 2, kind: "artifact" as const, position: `line:3;quote_sha256:${createHash("sha256").update(ref.quote).digest("hex")}` } };
const now = Date.parse("2026-10-04T00:00:00Z");
function command() { return makeLaunchCommand({ id: "product", revision: 4 }, "test.run.plan", launchPlanPayload(request, fact, "固定真实全部已接收范围", [ref]), [{ artifact_id: ref.artifact_id, expected_revision: 2 }], "same-command", "same-key"); }
function preview(): LaunchPreview { const original = command(); return { command: { ...original, payload: { ...original.payload, confirmation_token: "t".repeat(32) } }, expires_at: "2026-10-05T00:00:00Z", review: { before: { request, run: null }, after: { request, run: { ...run, id: null }, occupancy_effect: "none" }, effect: "固定完整计划，不产生实际占用" } }; }

test("能力仅接受服务器逐操作true，未知资格和产品写权不能变成开测能力", () => { assert.equal(launchCapability({ can_write: true, run_start: "true" }, "run_start"), false); assert.equal(launchCapability({ run_start: true }, "run_start"), true); assert.equal(launchCapability(undefined, "run_start"), false); });
test("空选或不可读Build不深读所有Run，也不默认选择首条轮次", async () => { const paths: string[] = [], api: LaunchApi = async path => { paths.push(path); throw new Error("不应请求"); }; assert.deepEqual(await readLaunchBuild(api, "product", "", [{ id: "R3" }], () => true), emptyLaunch); assert.deepEqual(await readLaunchBuild(api, "product", "unreadable", [{ id: "R3" }], () => true), emptyLaunch); assert.deepEqual(paths, []); });
test("已选轮次GET有准确过滤，范围切换后的迟到结果不写入", async () => { let current = true, resolve!: (value: unknown) => void; const paths: string[] = [], api: LaunchApi = <T>(path: string) => { paths.push(path); return new Promise<T>(done => { resolve = value => done(value as T); }); }; const result = readLaunchBuild(api, "product", "build", [{ id: "build" }], () => current); assert.deepEqual(paths, ["v1/products/product/verification-launch?build_id=build"]); current = false; resolve(emptyLaunch); assert.equal(await result, null); });
test("跨轮次请求或资源事实不成为本轮能力，缺关键运行版本也拒绝", () => { const dto = { ...emptyLaunch, requests: [request], runs: [run], resource_facts: [fact], runs_by_request: { request: ["run"] } }; assert.equal(normalizeLaunch(dto, "build").requests[0].id, request.id); assert.throws(() => normalizeLaunch(dto, "other")); assert.throws(() => normalizeLaunch({ ...dto, runs: [{ ...run, plan_sha256: null }] }, "build")); });
test("逐Run明确覆盖排序固定，空范围和重复范围拒绝", () => { assert.deepEqual(launchExactCoverage(pairs), [pairs[1], pairs[0]]); assert.throws(() => launchExactCoverage([])); assert.throws(() => launchExactCoverage([pairs[0], pairs[0]])); assert.throws(() => launchExactCoverage([{ sample_id: "sample", item_id: "" }])); });
test("可信Fact可固定同accepted请求版的非空子范围，不得引入未接收项或扩大范围", () => {
  const subset = { ...fact, binding: { ...fact.binding, pairs: [(fact.binding.pairs as unknown[])[0]] } };
  assert.equal(launchFactMatches(request, fact), true);
  assert.equal(launchFactMatches(request, subset), true);
  assert.deepEqual(launchFactCoverage(subset), [pairs[0]]);
  assert.deepEqual(launchPlanPayload(request, subset, "固定此运行范围", [ref]).coverage, [pairs[0]]);
  assert.equal(launchFactMatches(request, { ...fact, binding: { ...fact.binding, pairs: [] } }), false);
  assert.equal(launchFactMatches(request, { ...fact, binding: { ...fact.binding, pairs: [{ sample: { id: "not-accepted" }, item_id: pairs[0].item_id }] } }), false);
  assert.equal(launchFactMatches(request, { ...fact, binding: { ...fact.binding, accepted_request_revision: 1 } }), false);
  assert.equal(launchFactMatches(request, { ...fact, current: false }), false);
  assert.equal(launchFactMatches(request, { ...fact, source_status: "needs_recheck" }), false);
});
test("计划从同资源Fact固定runid和条件，不输入资源用量或资格以授予权限", () => { const value = launchPlanPayload(request, fact, "完整计划", [ref]); assert.equal(value.run_id, fact.binding.run_id); assert.deepEqual(value.coverage, [pairs[1], pairs[0]]); assert.deepEqual(value.execution_plan, plan); assert.equal(Object.hasOwn(value, "qualification"), false); assert.equal(Object.hasOwn(value, "uses"), false); const copied = launchFactPlan(fact); copied.window.start = "changed"; assert.equal((fact.binding.window as { start: string }).start, window.start); });
test("缺设备校准或来源当前未知不补默认计划", () => { assert.throws(() => launchFactPlan({ ...fact, binding: { ...fact.binding, calibration: null } })); assert.throws(() => launchPlanPayload(request, { ...fact, state: "withdrawn" }, "不能采用撤回事实", [ref])); assert.throws(() => launchPlanPayload({ ...request, is_current: false }, fact, "历史不可写", [ref])); });
test("承诺和Start只引用固定运行hash与版本，不携带可更改execution的字段", () => { const value = launchRunPayload(request, run, at, "实际开测核对", [ref]); assert.equal(value.expected_run_revision, 1); assert.equal(value.expected_plan_sha256, run.plan_sha256); assert.equal(Object.hasOwn(value, "execution"), false); assert.equal(Object.hasOwn(value, "execution_plan"), false); assert.equal((value.at as typeof at).occurred_at, at.occurred_at); assert.throws(() => launchRunPayload(request, { ...run, is_current: false }, at, "历史不可写", [])); });
test("事件无默认now且实际Start不得future，承诺时间独立可future", async () => { assert.deepEqual(blankLaunchEvent(), { occurredAt: "", timezone: "", reference: null }); await assert.rejects(() => launchEvent(blankLaunchEvent(), false, now)); await assert.rejects(() => launchEvent({ occurredAt: "2026-10-05T10:00:00-07:00", timezone: "America/Los_Angeles", reference: ref }, false, now)); const future = await launchEvent({ occurredAt: "2026-10-05T10:00:00-07:00", timezone: "America/Los_Angeles", reference: ref }, true, now); assert.equal(future.occurred_at, "2026-10-05T17:00:00Z"); assert.equal(future.effective_at, null); assert.equal(Object.hasOwn(future, "received_at"), false); });
test("事件定位采用原文UTF8摘要，时间offset归一后保存原IANA", async () => { const value = await launchEvent({ occurredAt: "2026-10-03T10:00:00.123456-07:00", timezone: "America/Los_Angeles", reference: ref }, false, now); assert.equal(value.occurred_at, "2026-10-03T17:00:00.123456Z"); assert.equal(value.original_timezone, "America/Los_Angeles"); assert.equal(value.source.position, at.source.position); });
test("T1必须原command/key/readset与实质完整计划，错Run和子集不能确认", () => { const original = command(), value = preview(); assert.equal(validLaunchPreview(value, original, now), true); assert.equal(validLaunchPreview({ ...value, command: { ...value.command, idempotency_key: "new" } }, original, now), false); assert.equal(validLaunchPreview({ ...value, command: { ...value.command, source_read_set: [] } }, original, now), false); assert.equal(validLaunchPreview({ ...value, review: { ...value.review, after: { ...value.review.after, run: { ...run, run_id: "other" } } } }, original, now), false); assert.equal(validLaunchPreview({ ...value, command: { ...value.command, payload: { ...value.command.payload, coverage: [pairs[0]] } } }, original, now), false); });
test("时间offset同一语义仍可确认，实质条件与时点改变会拒绝", () => { const original = command(), value = preview(), changedPlan = { ...plan, window: { ...plan.window, start: "2026-10-03T10:00:00-07:00" } }; assert.equal(validLaunchPreview({ ...value, command: { ...value.command, payload: { ...value.command.payload, execution_plan: changedPlan } } }, original, now), true); assert.equal(validLaunchPreview({ ...value, command: { ...value.command, payload: { ...value.command.payload, execution_plan: { ...plan, conditions: "另一个条件" } } } }, original, now), false); });
test("承诺preview仅推进请求且零占用，Start必须同时推进请求Run和占用影响", () => { const payload = launchRunPayload(request, run, at, "具名核对", [ref]), promise = makeLaunchCommand({ id: "product", revision: 4 }, "verification.schedule.promise", payload, [], "c", "k"); const value = { command: { ...promise, payload: { ...payload, confirmation_token: "t".repeat(32) } }, expires_at: "2026-10-05T00:00:00Z", review: { before: { request, run }, after: { request: { ...request, revision: 3, status: "scheduled" }, run, proposed_promise: { run_id: run.run_id, at, reason: payload.reason }, occupancy_effect: "none" }, effect: "承诺不占用" } }; assert.equal(validLaunchPreview(value, promise, now), true); const start = { ...promise, operation: "test.run.start" as const }; const startView = { ...value, command: { ...value.command, operation: start.operation }, review: { ...value.review, after: { request: { ...request, revision: 3, status: "executing" }, run: { ...run, revision: 2, status: "running" }, occupancy_effect: "stage_formal_and_sample_use_in_caller_uow" } } }; assert.equal(validLaunchPreview(startView, start, now), true); assert.equal(validLaunchPreview({ ...startView, review: { ...startView.review, after: { ...startView.review.after, occupancy_effect: "none" } } }, start, now), false); });
test("完整读集去重及版本冲突分别处理，只读inputs不能扩大原目标", () => { assert.deepEqual(launchReads([{ artifact_id: "a", expected_revision: 1 }], [{ artifact_id: "a", expected_revision: 1 }]), [{ artifact_id: "a", expected_revision: 1 }]); assert.throws(() => launchReads([{ artifact_id: "a", expected_revision: 1 }, { artifact_id: "a", expected_revision: 2 }])); const original = command(), inputs = { operation: original.operation, request_id: request.request_id, run_id: "run", allowed: false, required_source_read_set: [] }; assert.equal(validLaunchInputs(inputs, original), true); assert.equal(validLaunchInputs({ ...inputs, run_id: "other" }, original), false); assert.equal(validLaunchInputs({ ...inputs, allowed: "true" }, original), false); });
test("本机未知提交仅同人同product恢复，严格保留returnedcommand和token", () => { const local = { schema_version: 1, product_id: "product", principal_id: "person", ...blankLocalLaunch(), selectedBuildId: "build", selectedRequestId: "request", drafts: { request: blankLaunchWork() }, pending: { stage: "execute", command: preview().command } }; const restored = restoreLaunch(local, "product", "person"); assert.equal(restored?.pending?.command.command_id, "same-command"); assert.equal(restored?.pending?.command.idempotency_key, "same-key"); assert.equal(restoreLaunch(local, "other", "person"), null); assert.equal(restoreLaunch(local, "product", "other"), null); assert.equal(restoreLaunch({ ...local, pending: { stage: "execute", command: command() } }, "product", "person"), null); });
test("回执subject族精确匹配，计划不能被正式请求回执冒充", () => { const original = command(), receipt = { id: "receipt", subject_id: "run-v1", subject_type: "test_run", operation: original.operation }; assert.equal(validLaunchReceipt(receipt, original), true); assert.equal(validLaunchReceipt({ ...receipt, subject_type: "verification_request" }, original), false); assert.equal(validLaunchReceipt({ ...receipt, operation: "test.run.start" }, original), false); });
test("只读失败与提交未知不同文案，不将未发起操作说成待回执", () => { assert.match(launchError(new Error("read failed"), true).message, /读取失败/); assert.match(launchError(new Error("read failed"), true).message, /尚未发起新的提交/); assert.match(launchError(new Error("post unknown")).message, /原命令/); });

test("当前专业事实必须绑定本操作，旧交接资格和Grant不代替测试资格", () => { const start = { operation: "test.run.start", authorized: true, qualified: true, synthetic: true }; assert.equal(launchAuthority(start, "test.run.start"), start); assert.equal(launchAuthority({ run_start: start }, "test.run.start"), start); assert.equal(launchAuthority({ run_start: { ...start, operation: "verification.handoff.accept" } }, "test.run.start"), undefined); assert.equal(launchAuthority({ can_write: true }, "test.run.start"), undefined); assert.equal(launchAuthority(start, "verification.schedule.promise"), undefined); assert.equal(launchSyntheticAuthority(start), true); assert.equal(launchSyntheticAuthority({ run_start: start }), true); assert.equal(launchSyntheticAuthority(null), false); });
test("同逻辑请求也拒绝跨Build运行投影和载荷，不将迟到别轮结果复用", () => { const other = { ...run, build: { id: "other-build", revision: 1 } }; assert.throws(() => normalizeLaunch({ ...emptyLaunch, requests: [request], runs: [other], resource_facts: [fact] }, "build")); assert.throws(() => launchRunPayload(request, other, at, "不能跨轮次开测", [ref])); });
test("预览核对时间可为null并保留完整输入摘要，原签名命令仍可确认且不补造当前钟", () => { const original = command(), value = preview(), report = { status: "READY", checked_at: null, checked_at_basis: "server_revalidates_on_execute", input_digest: "b".repeat(64) }; value.review.resource_report = report; value.review.after.resource_report = report; assert.equal(validLaunchPreview(value, original, now), true); assert.equal(report.checked_at, null); assert.equal(report.input_digest, "b".repeat(64)); assert.equal(value.command.command_id, original.command_id); assert.equal(value.command.idempotency_key, original.idempotency_key); assert.equal(validLaunchPreview({ ...value, command: { ...value.command, payload: { ...value.command.payload, reason: "另一个实质原因" } } }, original, now), false); });


test("同请求的两个Run保留精确对应与各自承诺，旧单Run合同拒绝", () => {
  const promised = { id: "fact-promise-a", at, recorded_at: "2026-10-03T16:30:00Z", sources: [ref], reason: "只承诺Run A" };
  const first = { ...run, promise: promised }, second = { ...run, id: "run-b-v1", run_id: "run-b", promise: null };
  const dto = { ...emptyLaunch, requests: [request], runs: [first, second], runs_by_request: { request: ["run", "run-b"] } };
  const normalized = normalizeLaunch(dto, "build");
  assert.deepEqual(normalized.runs_by_request.request, ["run", "run-b"]);
  assert.equal(normalized.runs[0].promise?.id, promised.id);
  assert.equal(normalized.runs[1].promise, null);
  assert.throws(() => normalizeLaunch({ ...dto, runs_by_request: { request: ["run"] } }, "build"));
  assert.throws(() => normalizeLaunch({ ...dto, runs_by_request: { other: ["run", "run-b"] } }, "build"));
  assert.throws(() => normalizeLaunch({ ...dto, runs_by_request: { request: ["run", "run"] } }, "build"));
  assert.throws(() => normalizeLaunch({ ...dto, runs_by_request: undefined, run_by_request: { request: "run" } }, "build"));
  assert.throws(() => normalizeLaunch({ ...dto, runs: [{ ...first, promise: { ...promised, at: null } }, second] }, "build"));
});
test("新计划preview不能扩大固定Fact子范围，after实际覆盖也必须匹配", () => {
  const subset = { ...fact, binding: { ...fact.binding, pairs: [(fact.binding.pairs as unknown[])[0]] } };
  const original = makeLaunchCommand({ id: "product", revision: 4 }, "test.run.plan", launchPlanPayload(request, subset, "仅本Run", [ref]), [], "subset", "subset-key");
  const value = { ...preview(), command: { ...original, payload: { ...original.payload, confirmation_token: "t".repeat(32) } }, review: { ...preview().review, after: { ...preview().review.after, run: { ...run, run_snapshot: { ...run.run_snapshot, coverage: [pairs[0]] } } } } };
  assert.equal(validLaunchPreview(value, original, now), true);
  assert.equal(validLaunchPreview({ ...value, review: { ...value.review, after: { ...value.review.after, run } } }, original, now), false);
});
test("另一Run已经执行时，本Run承诺preview保留executing且不改变Run版本", () => {
  const executing = { ...request, status: "executing", request_snapshot: { status: "executing" } };
  const payload = launchRunPayload(executing, run, at, "承诺另一独立Run", [ref]);
  const original = makeLaunchCommand({ id: "product", revision: 4 }, "verification.schedule.promise", payload, [], "promise-b", "promise-b-key");
  const value = { command: { ...original, payload: { ...payload, confirmation_token: "t".repeat(32) } }, expires_at: "2026-10-05T00:00:00Z", review: { before: { request: executing, run }, after: { request: { ...executing, revision: 3 }, run, proposed_promise: { run_id: run.run_id, at, reason: payload.reason }, occupancy_effect: "none" }, effect: "只承诺本Run" } };
  assert.equal(validLaunchPreview(value, original, now), true);
  assert.equal(validLaunchPreview({ ...value, review: { ...value.review, after: { ...value.review.after, proposed_promise: { run_id: "other-run", at, reason: payload.reason } } } }, original, now), false);
  assert.equal(validLaunchPreview({ ...value, review: { ...value.review, after: { ...value.review.after, request: { ...executing, revision: 3, status: "scheduled" } } } }, original, now), false);
  assert.equal(validLaunchPreview({ ...value, review: { ...value.review, after: { ...value.review.after, run: { ...run, revision: 2 } } } }, original, now), false);
});
test("刷新恢复时计划按Request、承诺Start按准确Build Request Run分别保留", () => {
  const keyA = launchRunDraftKey("build", "request", "run-a"), keyB = launchRunDraftKey("build", "request", "run-b");
  const local = { schema_version: 2, product_id: "product", principal_id: "person", ...blankLocalLaunch(), selectedBuildId: "build", selectedRequestId: "request", selectedRunId: "run-b", drafts: { request: { ...blankLaunchWork(), resourceFactId: "new-run-fact", planReason: "再建Run C", references: [ref] } }, runDrafts: { [keyA]: { ...blankLaunchRunWork(), promiseReason: "承诺A", promiseEvent: { occurredAt: at.occurred_at, timezone: at.original_timezone, reference: ref }, references: [ref] }, [keyB]: { ...blankLaunchRunWork(), startReason: "开测B" } }, pending: { stage: "execute", command: preview().command } };
  const restored = restoreLaunch(JSON.parse(JSON.stringify(local)), "product", "person");
  assert.equal(restored?.selectedRunId, "run-b");
  assert.equal(restored?.drafts.request.planReason, "再建Run C");
  assert.equal(restored?.runDrafts[keyA].promiseReason, "承诺A");
  assert.equal(restored?.runDrafts[keyB].promiseReason, "");
  assert.equal(restored?.runDrafts[keyB].startReason, "开测B");
  assert.equal(restored?.runDrafts[launchRunDraftKey("other-build", "request", "run-a")], undefined);
  assert.deepEqual(restored?.pending, local.pending);
  assert.equal(restoreLaunch({ ...local, runDrafts: { request: blankLaunchRunWork() } }, "product", "person"), null);
});
test("旧草稿有精确选中Run身份才迁移，推断首Run或未知提交都不串用草稿", () => {
  const oldWork = { ...blankLaunchWork(), ...blankLaunchRunWork(), resourceFactId: "fact", planReason: "计划", promiseReason: "旧承诺", startReason: "旧开测", references: [ref] };
  const old = { schema_version: 1, product_id: "product", principal_id: "person", ...blankLocalLaunch(), selectedBuildId: "build", selectedRequestId: "request", selectedRunId: "", drafts: { request: oldWork }, pending: { stage: "execute", command: preview().command } };
  const unbound = restoreLaunch(old, "product", "person");
  assert.deepEqual(unbound?.runDrafts, {});
  assert.equal(unbound?.drafts.request.planReason, "计划");
  assert.deepEqual(unbound?.pending, old.pending);
  const exact = restoreLaunch({ ...old, selectedRunId: "run" }, "product", "person");
  assert.equal(exact?.runDrafts[launchRunDraftKey("build", "request", "run")].promiseReason, "旧承诺");
  assert.equal(exact?.runDrafts[launchRunDraftKey("build", "request", "other")], undefined);
});
