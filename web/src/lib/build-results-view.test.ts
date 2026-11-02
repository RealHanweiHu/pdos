import test from "node:test";
import assert from "node:assert/strict";
import { blankLocalResults, blankResultsEvent, blankResultsWork, captureResultsInput, checkPreparedResults, computeResultsPayload, emptyResults, importResultsPayload, makeResultsCommand, normalizeResults, professionalResultsPayload, readResultsBuild, readResultsContext, restoreResults, resultsAuthority, resultsCapability, resultsError, resultsEvent, resultsRaw, resultsReads, resultsReference, resultsSame, resultsTier, resultsVerdict, validResultsInputs, validResultsPreview, validResultsReceipt, type ResultsApi, type ResultsReport, type ResultsRequest, type ResultsRun } from "./build-results-view";
import { createWorkspaceApi, type WorkspaceTransport } from "./workspace-api";
import type { DefinitionSource } from "./product-view";

const now = Date.parse("2026-10-04T00:00:00Z");
const source = { artifact_id: "report", expected_revision: 1, line: 2, quote: "原报告实测事件" };
const event = { occurred_at: "2026-10-03T17:00:00.123456Z", original_timezone: "America/Los_Angeles", source: { id: "report", revision: 1, kind: "artifact", position: `line:2;quote_sha256:${"a".repeat(64)}` }, effective_at: null };
function original(operation: "test.results.import" | "test.run.review" = "test.results.import") { return makeResultsCommand({ id: "product", revision: 4 }, operation, { request_id: "request", expected_request_revision: 7, run_id: "run", expected_run_revision: 2, at: event, reason: "按原报告核对", ...(operation === "test.run.review" ? { projection_id: "projection", expected_projection_revision: 1, expected_basis_sha256: "a".repeat(64), text: "独立专业结论" } : { final: false }) }, [{ artifact_id: "report", expected_revision: 1 }], "command", "key"); }
function preview(operation: "test.results.import" | "test.run.review" = "test.results.import") { const command = original(operation), tier = resultsTier(operation), token = tier === "T2" ? "approval_token" : "confirmation_token", fixed = { request: { request_id: "request", revision: 7 }, run: { run_id: "run", revision: 2 }, projection: { id: "projection", revision: 1, basis_sha256: "a".repeat(64) } }; return { command: { ...command, payload: { ...command.payload, [token]: "t".repeat(32) } }, expires_at: "2026-10-05T00:00:00Z", write_tier: tier, ...(tier === "T2" ? { approval_token: "t".repeat(32) } : {}), review: { before: fixed, after: { ...fixed, run: { run_id: "run", revision: 3, status: tier === "T2" ? "reviewed" : "running" }, observations: [], measurement_effect: tier === "T2" ? "none" : "append_verified_original_values", occupancy_effect: "none_retain_original_start_and_consumption", received_at: null, time_policy: "server_on_save" }, effect: "按完整固定原值保存，不重新占用" } }; }

test("原值逐字保留，未知不转为零，数值不在客户端重解释", () => { assert.equal(resultsRaw(" 001.2300 "), " 001.2300 "); assert.equal(resultsRaw("0"), "0"); assert.equal(resultsRaw(null), "原报告未提供"); assert.equal(resultsRaw(12), "原值类型待核对"); });
test("数值判定、未知和专业无效分别展示，未知值不默认通过", () => { assert.match(resultsVerdict("pass"), /数值判定通过/); assert.match(resultsVerdict("indeterminate"), /不能确定/); assert.match(resultsVerdict("invalid"), /明确记录为无效/); assert.match(resultsVerdict(null), /待核对/); });
test("权限只接受服务器逐操作布尔true，产品写权限不能成为专业能力", () => { assert.equal(resultsCapability({ can_write: true, run_review: "true" }, "run_review"), false); assert.equal(resultsCapability({ run_review: true }, "run_review"), true); assert.equal(resultsCapability(undefined, "run_review"), false); });
test("导入一次确认、计算无额外确认、复核与处置分别具名T2", () => { assert.equal(resultsTier("test.results.import"), "T1"); assert.equal(resultsTier("test.result.compute"), "T0"); assert.equal(resultsTier("test.run.review"), "T2"); assert.equal(resultsTier("test.disposition.decide"), "T2"); });
test("精确读集去重与版本冲突守卫不丢固定范围", () => { assert.deepEqual(resultsReads([{ artifact_id: "a", expected_revision: 1 }], [{ artifact_id: "a", expected_revision: 1 }]), [{ artifact_id: "a", expected_revision: 1 }]); assert.throws(() => resultsReads([{ artifact_id: "a", expected_revision: 1 }, { artifact_id: "a", expected_revision: 2 }])); });
test("事件默认空，不能由当前时钟或计划窗口补造发生", async () => { assert.deepEqual(blankResultsEvent(), { occurredAt: "", timezone: "", reference: null }); await assert.rejects(resultsEvent(blankResultsEvent(), now)); await assert.rejects(resultsEvent({ occurredAt: "2026-10-05T00:00:00Z", timezone: "UTC", reference: source }, now)); });
test("精确事件位置以原文摘要生成，offset同瞬间保存UTC与原IANA", async () => { const value = await resultsEvent({ occurredAt: "2026-10-03T10:00:00.123456-07:00", timezone: "America/Los_Angeles", reference: source }, now); assert.equal(value.occurred_at, "2026-10-03T17:00:00.123456Z"); assert.equal(value.original_timezone, "America/Los_Angeles"); assert.match(value.source.position, /^line:2;quote_sha256:[0-9a-f]{64}$/); assert.equal(value.effective_at, null); assert.equal(Object.hasOwn(value, "received_at"), false); });
test("对象键序不造假差异，数组顺序与原值语义仍保留", () => { assert.equal(resultsSame({ raw_value: " 1 ", coverage: { sample_id: "s", item_id: "i" } }, { coverage: { item_id: "i", sample_id: "s" }, raw_value: " 1 " }), true); assert.equal(resultsSame([1, 2], [2, 1]), false); assert.equal(resultsSame({ raw_value: " 1 " }, { raw_value: "1" }), false); });
test("预览必须严格原命令标识、完整读集和实质载荷，不把新请求当重试", () => { const command = original(), value = preview(); assert.equal(validResultsPreview(value, command, now), true); assert.equal(validResultsPreview({ ...value, command: { ...value.command, idempotency_key: "new" } }, command, now), false); assert.equal(validResultsPreview({ ...value, command: { ...value.command, source_read_set: [] } }, command, now), false); assert.equal(validResultsPreview({ ...value, command: { ...value.command, payload: { ...value.command.payload, final: true } } }, command, now), false); assert.equal(validResultsPreview({ ...value, review: { ...value.review, after: { ...value.review.after, occupancy_effect: "new_reservation" } } }, command, now), false); assert.equal(validResultsPreview({ ...value, review: { ...value.review, after: { ...value.review.after, run: { ...value.review.after.run, run_id: "other" } } } }, command, now), false); });
test("offset语义归一仍匹配，独立事件实际改变则拒绝", () => { const command = original(), value = preview(); const changed = { ...value, command: { ...value.command, payload: { ...value.command.payload, at: { ...event, occurred_at: "2026-10-03T10:00:00.123456-07:00" } } } }; assert.equal(validResultsPreview(changed, command, now), true); assert.equal(validResultsPreview({ ...changed, command: { ...changed.command, payload: { ...changed.command.payload, at: { ...event, occurred_at: "2026-10-03T17:00:01Z" } } } }, command, now), false); });
test("T2只能持对应approval token，T1 token和普通一次确认不能冒充批准", () => { const command = original("test.run.review"), value = preview("test.run.review"); assert.equal(validResultsPreview(value, command, now), true); assert.equal(validResultsPreview({ ...value, write_tier: "T1" }, command, now), false); assert.equal(validResultsPreview({ ...value, approval_token: "other" }, command, now), false); assert.equal(validResultsPreview({ ...value, command: { ...value.command, payload: { ...command.payload, confirmation_token: "t".repeat(32) } } }, command, now), false); });
test("inputs是当前同请求同Run操作的服务器核对，unknown allowed不能变成允许", () => { const command = original(), value = { operation: command.operation, request_id: "request", run_id: "run", allowed: false, required_source_read_set: [] }; assert.equal(validResultsInputs(value, command), true); assert.equal(validResultsInputs({ ...value, request_id: "other" }, command), false); assert.equal(validResultsInputs({ ...value, run_id: "other" }, command), false); assert.equal(validResultsInputs({ ...value, allowed: "true" }, command), false); assert.equal(validResultsInputs({ ...value, required_source_read_set: [{ artifact_id: "r", expected_revision: 0 }] }, command), false); });
test("读取失败与提交回执未知分别说明，读取不触发业务恢复提示", () => { assert.match(resultsError(null, true).message, /没有发起提交/); assert.match(resultsError(null).message, /原请求/); assert.match(resultsError({ status: 403 }).message, /具名职责/); });

const request = { id: "request-v7", request_id: "request", revision: 7, title: "压力验证", purpose: "内部压力测试", build: { id: "build", revision: 1 }, items: [], is_current: true, source_status: "current", required_source_read_set: [] } as ResultsRequest;
const run = { id: "run-v2", run_id: "run", request_id: "request", revision: 2, status: "running", build: request.build, run_snapshot: { coverage: [{ sample_id: "sample-a", item_id: "pressure" }] }, basis_sha256: "a".repeat(64), current_projection: null, capabilities: {}, authority: {}, is_current: true, source_status: "current", required_source_read_set: [] } as ResultsRun;
const report = { artifact_id: "report", artifact_revision: 1, title: "固定原报告", source_status: "current", original_id: "original", original_revision: 1, security_epoch: 2, lines: [{ original_line: 2, fragment: '{"raw_value":" 001.2300 "}' }], verification: "original_bytes_integrity_checked_format_not_verified", derived_line_not_assumed: true, has_more: false } as ResultsReport;
const selection = { line: 2, sample_id: "sample-a", item_id: "pressure" };
test("空轮次或不可读轮次不深读全产品，明确选择才请求scoped结果", async () => { const paths: string[] = [], api: ResultsApi = async path => { paths.push(path); return emptyResults as never; }; assert.equal(await readResultsBuild(api, "product", "", [{ id: "build" }], () => true), emptyResults); assert.equal(await readResultsBuild(api, "product", "unreadable", [{ id: "build" }], () => true), emptyResults); assert.equal(paths.length, 0); await readResultsBuild(api, "product", "build", [{ id: "build" }], () => true); assert.deepEqual(paths, ["v1/products/product/verification-results?build_id=build"]); });
test("切换轮次后迟到结果不复用，跨Build或缺固定basis的运行拒绝", async () => { let current = true, done!: (value: unknown) => void; const api: ResultsApi = <T>() => new Promise<T>(resolve => { done = value => resolve(value as T); }); const pending = readResultsBuild(api, "product", "build", [{ id: "build" }], () => current); current = false; done(emptyResults); assert.equal(await pending, null); assert.throws(() => normalizeResults({ ...emptyResults, requests: [request], runs: [{ ...run, build: { id: "other", revision: 1 } }] }, "build")); assert.throws(() => normalizeResults({ ...emptyResults, requests: [request], runs: [{ ...run, basis_sha256: null }] }, "build")); });
test("捕获只带原件位置与固定pair，不输入原值、权威或伪造原件摘要", () => { const value = captureResultsInput(4, request, run, report, [selection], "核对原件实测位置", "capture-key"); assert.deepEqual(value.selections, [selection]); assert.equal(value.report_artifact_id, report.artifact_id); for (const field of ["raw_value", "measurement", "authority", "sha256", "security_epoch"]) assert.equal(Object.hasOwn(value, field), false); assert.throws(() => captureResultsInput(4, request, run, report, [selection, selection], "重复不能通过", "capture-key")); assert.throws(() => captureResultsInput(4, request, run, report, [{ ...selection, sample_id: "not-fixed" }], "不超范围", "capture-key")); assert.throws(() => captureResultsInput(4, request, { ...run, status: "planned" }, report, [selection], "尚未开测", "capture-key")); assert.throws(() => captureResultsInput(4, request, run, report, [{ ...selection, line: 1 }], "不能采用派生文本行号", "capture-key")); assert.throws(() => captureResultsInput(4, request, run, { ...report, derived_line_not_assumed: false } as unknown as ResultsReport, [selection], "须核对原件", "capture-key")); });
test("捕获响应固定原Run/请求版与候选ID，不接受别Run或不完整读集", () => { const input = captureResultsInput(4, request, run, report, [selection], "核对原件", "capture-key"), capture = { id: "capture", revision: 1, run_id: "run", observations: [], results_import_payload: {} }, seed = { request_id: "request", expected_request_revision: 7, run_id: "run", expected_run_revision: 2, capture_id: "capture", expected_capture_revision: 1 }; assert.equal(checkPreparedResults({ capture, results_import_payload: seed, required_source_read_set: [] }, input), true); assert.equal(checkPreparedResults({ capture, results_import_payload: { ...seed, run_id: "other" }, required_source_read_set: [] }, input), false); assert.equal(checkPreparedResults({ capture, results_import_payload: seed, required_source_read_set: [{ artifact_id: "r", expected_revision: 0 }] }, input), false); });
test("固定数值计算无时间或token，无资格自授且历史不可提交", () => { const value = computeResultsPayload(request, run, "读取同一固定判定"); assert.equal(value.expected_basis_sha256, run.basis_sha256); for (const field of ["at", "approval_token", "confirmation_token", "result", "authority"]) assert.equal(Object.hasOwn(value, field), false); assert.throws(() => computeResultsPayload(request, { ...run, is_current: false }, "历史不能写")); });
test("partial必须有真实capture及当前下一责任人，final不能缺实际结束", async () => { const work = blankResultsWork(); work.returned = { occurredAt: "2020-01-01T00:00:00Z", timezone: "UTC", reference: source }; work.importReason = "原值返回"; await assert.rejects(importResultsPayload(request, run, undefined, work, []), /部分返回/); work.final = true; await assert.rejects(importResultsPayload(request, run, undefined, work, []), /独立时间/); });
test("具名专业批准绑定完整投影basis，旧basis不能继续批准", async () => { const work = blankResultsWork(); work.reviewed = { occurredAt: "2020-01-01T00:00:00Z", timezone: "UTC", reference: source }; work.reviewText = "独立专业意见"; work.reviewReason = "核对固定结果"; const current = { ...run, current_projection: { id: "projection", revision: 1, basis_sha256: run.basis_sha256, result: "indeterminate" } }; const value = await professionalResultsPayload(request, current, "test.run.review", work); assert.equal(value.projection_id, "projection"); assert.equal(value.expected_basis_sha256, run.basis_sha256); assert.equal(Object.hasOwn(value, "computed_result"), false); await assert.rejects(professionalResultsPayload(request, { ...current, current_projection: { ...current.current_projection, basis_sha256: "b".repeat(64) } }, "test.run.review", work), /旧批准/); });
test("未知原请求只在同具名人同产品恢复，原key/token不更换", () => { const local = { schema_version: 1, product_id: "product", principal_id: "person", ...blankLocalResults(), selectedBuildId: "build", selectedRunId: "run", drafts: { run: blankResultsWork() }, pending: { stage: "execute", command: preview().command } }; assert.equal(restoreResults(local, "product", "person")?.pending?.stage, "execute"); assert.equal(restoreResults(local, "product", "other"), null); assert.equal(restoreResults(local, "other", "person"), null); assert.equal(restoreResults({ ...local, pending: { stage: "execute", command: original() } }, "product", "person"), null); });
test("各回执精确属于该操作，projection不能冒充Run新版本", () => { const command = original(), receipt = { id: "receipt", subject_id: "run-v3", subject_type: "test_run", operation: command.operation }; assert.equal(validResultsReceipt(receipt, command), true); assert.equal(validResultsReceipt({ ...receipt, subject_type: "test_result_projection" }, command), false); assert.equal(validResultsReceipt({ ...receipt, operation: "test.run.review" }, command), false); });
test("专业事实必须绑定本操作，只有Grant或别操作角色不开放T2", () => { const authority = { operation: "test.run.review", authorized: true, qualified: true }; assert.equal(resultsAuthority({ run_review: authority }, "test.run.review"), authority); assert.equal(resultsAuthority({ run_review: { ...authority, operation: "test.run.start" } }, "test.run.review"), undefined); assert.equal(resultsAuthority({ can_write: true }, "test.run.review"), undefined); });
test("整行事件摘录保留首尾空白与原字面值，不裁剪成另一个hash出处", () => { const line = '  {"occurred_at":"2026-10-03T17:00:00Z"}  ', artifact = { id: "event", title: "事件原文", revision: 1, status: "active", visibility: "category", content: `标题\r\n${line}` } as DefinitionSource; const ref = resultsReference(artifact, 2, line); assert.equal(ref.quote, line); assert.throws(() => resultsReference(artifact, 1, line)); });
test("mounted旧读由原请求POST取代不报网络失败，提交后的同轮上下文回读v3", async () => {
  const calls: { path: string; body: unknown; resolve: (value: unknown) => void }[] = [];
  const transport: WorkspaceTransport = <T>(path: string, body?: unknown) => new Promise<T>(resolve => calls.push({ path, body, resolve: value => resolve(value as T) }));
  const client = createWorkspaceApi(transport, "person:product"), turn = () => new Promise<void>(resolve => setImmediate(resolve));
  const old = readResultsContext(client.api, "product", "build", () => true); await turn();
  const original = { command_id: "original-command", idempotency_key: "original-key" }, post = client.api("v1/commands", original); await turn();
  assert.equal(await old, null); assert.equal(calls.length, 3); assert.equal(calls[2].body, original);
  calls[0].resolve({ items: [{ id: "obsolete-build" }] }); calls[1].resolve({ sources: [{ id: "obsolete-source" }] }); calls[2].resolve({ subject_id: "run-v3" }); await post;
  const current = readResultsContext(client.api, "product", "build", () => true); await turn();
  calls[3].resolve({ items: [{ id: "build" }] }); calls[4].resolve({ sources: [] }); await turn();
  assert.equal(calls[5].path, "v1/products/product/verification-results?build_id=build");
  calls[5].resolve({ ...emptyResults, requests: [{ ...request, revision: 8 }], runs: [{ ...run, id: "run-v3", revision: 3 }] });
  const value = await current; assert.equal(value?.data.runs[0].revision, 3); assert.equal(value?.builds[0].id, "build"); assert.deepEqual(value?.sources, []);
});
test("精确READ_SUPERSEDED可忽略，真实错误和其他取消不得吞掉", async () => {
  const api: ResultsApi = async path => { throw path.endsWith("/builds") ? { code: "READ_SUPERSEDED" } : { status: 503, code: "READ_UNAVAILABLE" }; };
  await assert.rejects(readResultsContext(api, "product", "build", () => true), /读取失败/);
  for (const code of ["READ_CANCELLED", "READ_SCOPE_DISPOSED", undefined]) {
    const other: ResultsApi = async () => { throw { code }; };
    await assert.rejects(readResultsContext(other, "product", "build", () => true), /读取失败/);
  }
});
test("scoped Run旧读取消不清空成功事实，当前真实网络或格式失败仍显式报错", async () => {
  for (const fault of [{ code: "READ_SUPERSEDED" }, { status: 503, code: "READ_UNAVAILABLE" }]) {
    const api: ResultsApi = async path => { if (path.endsWith("/builds")) return { items: [{ id: "build" }] } as never; if (path.endsWith("/workspace")) return { sources: [] } as never; throw fault; };
    if (fault.code === "READ_SUPERSEDED") assert.equal(await readResultsContext(api, "product", "build", () => true), null);
    else await assert.rejects(readResultsContext(api, "product", "build", () => true), /读取失败/);
  }
  const malformed: ResultsApi = async () => null as never;
  await assert.rejects(readResultsContext(malformed, "product", "build", () => true), /读取失败/);
});

test("项目结果页先核对本项目轮次，其他项目的旧选择不会读取详情", async () => {
  const calls: string[] = [];
  const api: ResultsApi = async path => {
    calls.push(path);
    if (path.includes("/builds?")) return { items: [{ id: "current-build" }] } as never;
    if (path.endsWith("/workspace")) return { sources: [] } as never;
    assert.fail(`不应读取其他项目的详情：${path}`);
  };
  const value = await readResultsContext(api, "product", "other-build", () => true, "project-a");
  assert.deepEqual(calls, ["v1/products/product/builds?project_id=project-a", "v1/products/product/workspace"]);
  assert.deepEqual(value?.data, emptyResults);
  assert.deepEqual(value?.builds, [{ id: "current-build" }]);
});

test("本项目结果读取保留范围，筛选读取失败不退回全部轮次", async () => {
  const calls: string[] = [];
  const api: ResultsApi = async path => {
    calls.push(path);
    if (path.includes("/builds?")) return { items: [{ id: "build" }] } as never;
    if (path.endsWith("/workspace")) return { sources: [] } as never;
    assert.equal(path, "v1/products/product/verification-results?build_id=build");
    return emptyResults as never;
  };
  assert.deepEqual((await readResultsContext(api, "product", "build", () => true, "project-a"))?.data, emptyResults);
  assert.equal(calls.length, 3);
  calls.length = 0;
  const failed: ResultsApi = async path => { calls.push(path); throw { status: 503 }; };
  await assert.rejects(readResultsContext(failed, "product", "build", () => true, "project-a"), /读取失败/);
  assert.equal(calls.length, 2);
  assert.equal(calls.some(path => path.endsWith("/builds")), false);
});
