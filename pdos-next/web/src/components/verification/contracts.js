"use strict";
Object.defineProperty(exports, "__esModule", { value: true });
exports.missingFieldNames = exports.timeKindNames = exports.resultStatusNames = exports.runStatusNames = exports.requestStatusNames = void 0;
exports.sourceText = sourceText;
exports.fixedContextKey = fixedContextKey;
exports.sameIntent = sameIntent;
exports.previewProblem = previewProblem;
exports.handoffProblems = handoffProblems;
exports.measurementProblems = measurementProblems;
exports.incompleteResultItems = incompleteResultItems;
exports.pairKey = pairKey;
exports.mergeCoverage = mergeCoverage;
exports.startProblems = startProblems;
exports.eventTimeProblems = eventTimeProblems;
exports.coverageGaps = coverageGaps;
exports.requestStatusNames = { draft: "准备中", offered: "已提出交接", accepted: "已接收明确范围", scheduled: "已承诺时段", executing: "验证执行中", reported: "结果已返回", disposed: "已处置" };
exports.runStatusNames = { planned: "待开测", running: "测试执行中", results_pending: "等待结果核对", reviewed: "结果已审阅", disposed: "已处置" };
exports.resultStatusNames = { pending: "尚无结论", pass: "通过", fail: "不通过", indeterminate: "不确定", invalid: "无效" };
exports.timeKindNames = { request_created: "请求建立", sample_ready: "实物就绪", documents_complete: "资料齐套", offered: "提出交接", accepted: "正式接收", promised_start: "承诺开测", actual_start: "实际开测", preliminary_result: "部分结果返回", final_result: "最终结果返回", disposed: "处置" };
exports.missingFieldNames = { rawValue: "原始读数", unit: "单位", conditions: "工况", equipment: "设备", environment: "环境", method: "方法版本", sourcePosition: "来源位置", observedAt: "真实观测时间", originalTimezone: "观测原始时区" };
function sourceText(source) {
    return source ? `${source.kind} ${source.originalId} · v${source.revision} · ${source.locator}` : "来源尚未记录";
}
function fixedContextKey(context, request, samples, runs = []) {
    // Full snapshot also protects against a caller forgetting to advance its watermark.
    return JSON.stringify({ context, request, samples, runs });
}
function sameIntent(left, right) {
    return canonical(left) === canonical(right);
}
function canonical(value) {
    var _a;
    if (Array.isArray(value))
        return `[${value.map(canonical).join(",")}]`;
    if (value && typeof value === "object")
        return `{${Object.entries(value).sort(([left], [right]) => left.localeCompare(right)).map(([key, field]) => `${JSON.stringify(key)}:${canonical(field)}`).join(",")}}`;
    return (_a = JSON.stringify(value)) !== null && _a !== void 0 ? _a : "null";
}
function previewProblem(preview, intent, contextKey, now) {
    if (!preview.token || !preview.digest || !preview.summary.trim())
        return "服务器核对结果不完整。";
    if (preview.contextKey !== contextKey || !sameIntent(preview.intent, intent))
        return "输入或当前资料已变化，请重新核对。";
    if (!Number.isFinite(Date.parse(preview.expiresAt)) || Date.parse(preview.expiresAt) <= now)
        return "本次预览已过期，请重新核对。";
    if (!preview.allowed || preview.missing.some(item => item.blocking))
        return "本次范围尚不可办理，请处理阻塞缺项。";
    if (preview.scope.request.id !== intent.request.id || preview.scope.request.revision !== intent.request.revision)
        return "服务器核对的请求范围不一致。";
    if ("build" in intent && (preview.scope.productId !== intent.build.productId || preview.scope.projectId !== intent.build.projectId))
        return "服务器核对的产品或项目范围不一致。";
    const expectedSamples = intent.samples;
    if (expectedSamples.some(sample => !preview.scope.samples.some(value => canonical(value) === canonical(sample))) || preview.scope.samples.some(sample => !expectedSamples.some(value => canonical(value) === canonical(sample))))
        return "服务器核对未固定实际样件及配置版本。";
    if (canonical(preview.scope.coverage) !== canonical(intent.coverage))
        return "服务器核对未覆盖所选样件与测试项的精确对应范围。";
    return null;
}
function handoffProblems(request, samples, coverage, returnedItems, action, partialReason = "", nextOwnerId = "") {
    var _a, _b, _c, _d, _e, _f;
    const problems = [];
    if (new Set(coverage.sampleIds).size !== coverage.sampleIds.length || new Set(coverage.testItemIds).size !== coverage.testItemIds.length)
        problems.push("样件或测试项重复。");
    if (action === "handoff.return") {
        if (!coverage.pairs.length || coverage.pairs.some(pair => { var _a, _b; return !((_a = request.offeredCoverage) === null || _a === void 0 ? void 0 : _a.pairs.some(value => pairKey(value) === pairKey(pair))) || ((_b = request.acceptedCoverage) === null || _b === void 0 ? void 0 : _b.pairs.some(value => pairKey(value) === pairKey(pair))); }))
            problems.push("退回须固定本次实际提出且尚未接收的对应范围。");
        if (!returnedItems.length || returnedItems.some(item => !item.reason.trim() || !item.nextOwnerId.trim()))
            problems.push("每项退缺项都须填写原因与下一责任人。");
        return problems;
    }
    if (!coverage.sampleIds.length || !coverage.testItemIds.length)
        problems.push("请明确实际样件与测试项覆盖。");
    const selectedSamples = samples.filter(sample => coverage.sampleIds.includes(sample.id));
    if (selectedSamples.length !== coverage.sampleIds.length || selectedSamples.some(sample => sample.buildId !== request.build.id || !sample.actualConfiguration.id || sample.actualConfiguration.revision < 1 || sample.availability !== "available" || !sample.source))
        problems.push("所选样件缺少当前可用性、真实配置或来源，需要服务器重核。");
    if (action === "handoff.accept" && coverage.sampleIds.some(id => { var _a; return !((_a = request.offeredCoverage) === null || _a === void 0 ? void 0 : _a.sampleIds.includes(id)); }))
        problems.push("只能接收本次实际提出交接的样件。");
    if (coverage.pairs.some(pair => !coverage.sampleIds.includes(pair.sampleId) || !coverage.testItemIds.includes(pair.testItemId)) || coverage.sampleIds.some(id => !coverage.pairs.some(pair => pair.sampleId === id)) || coverage.testItemIds.some(id => !coverage.pairs.some(pair => pair.testItemId === id)))
        problems.push("请明确每件样件与测试项的对应覆盖。");
    if (new Set(coverage.pairs.map(pairKey)).size !== coverage.pairs.length)
        problems.push("样件与测试项对应覆盖重复。");
    if (action === "handoff.accept" && coverage.pairs.some(pair => { var _a; return !((_a = request.offeredCoverage) === null || _a === void 0 ? void 0 : _a.pairs.some(value => pairKey(value) === pairKey(pair))); }))
        problems.push("只能接收实际提出交接的对应覆盖。");
    if (action === "handoff.accept" && coverage.pairs.some(pair => { var _a; return (_a = request.acceptedCoverage) === null || _a === void 0 ? void 0 : _a.pairs.some(value => pairKey(value) === pairKey(pair)); }))
        problems.push("已接收对应范围不可重复接收或退回。");
    const selectedItems = request.testItems.filter(item => coverage.testItemIds.includes(item.id));
    if (selectedItems.length !== coverage.testItemIds.length)
        problems.push("所选测试项不属于此请求。");
    for (const item of action === "handoff.accept" ? selectedItems : []) {
        if (!item.method.source || !item.method.criterion.trim() || !item.method.unit.trim() || !item.method.conditions.trim())
            problems.push(`${item.title} 的方法、判据、单位或工况不完整。`);
        if (item.documentIds.some(id => !request.documents.some(doc => doc.id === id && doc.status === "current" && !!doc.source)))
            problems.push(`${item.title} 的适用资料尚未齐套。`);
    }
    if (returnedItems.some(item => !item.reason.trim() || !item.nextOwnerId.trim()))
        problems.push("每项退缺项都须填写原因与下一责任人。");
    if (action === "handoff.accept") {
        const cumulative = mergeCoverage(request.acceptedCoverage, coverage);
        const omitted = (_b = (_a = request.offeredCoverage) === null || _a === void 0 ? void 0 : _a.pairs.filter(pair => !cumulative.pairs.some(value => pairKey(value) === pairKey(pair)))) !== null && _b !== void 0 ? _b : [];
        if (omitted.some(pair => !returnedItems.some(item => item.kind === "coverage" && item.id === pairKey(pair))))
            problems.push("部分接收须为未接收样件与测试项逐项记录原因和下一责任人。");
        if (coverageGaps(request, samples, cumulative).length > 0 && (!((_d = (partialReason || ((_c = returnedItems[0]) === null || _c === void 0 ? void 0 : _c.reason))) === null || _d === void 0 ? void 0 : _d.trim()) || !((_f = (nextOwnerId || ((_e = returnedItems[0]) === null || _e === void 0 ? void 0 : _e.nextOwnerId))) === null || _f === void 0 ? void 0 : _f.trim())))
            problems.push("原请求数量或模穴仍有差距，须明确部分接收原因与下一责任人。");
    }
    return Array.from(new Set(problems));
}
function measurementProblems(measurement, run, request) {
    const problems = [];
    const sample = run.samples.find(item => item.id === measurement.sample.id);
    const item = request.testItems.find(item => item.id === measurement.testItemId);
    if (!sample || canonical(sample) !== canonical(measurement.sample))
        problems.push("测量样件或实际配置与 Run 固定版本不一致。");
    if (!item || !run.coverage.pairs.some(pair => pair.sampleId === measurement.sample.id && pair.testItemId === measurement.testItemId))
        problems.push("测量样件与测试项不在 Run 精确覆盖范围内。");
    if (measurement.method && item && canonical(measurement.method) !== canonical({ id: item.method.id, revision: item.method.revision }))
        problems.push("测量方法版本与固定测试项不一致。");
    const fields = ["rawValue", "unit", "conditions", "equipment", "environment", "method", "sourcePosition", "observedAt", "originalTimezone"];
    for (const field of fields) {
        const value = measurement[field];
        const empty = value === null || (typeof value === "string" && !value.trim());
        if (empty !== measurement.missing.includes(field))
            problems.push(`${exports.missingFieldNames[field]}须填写原值或明确声明缺项。`);
    }
    if (measurement.sourcePosition && (!measurement.sourcePosition.originalId.trim() || !measurement.sourcePosition.kind.trim() || !measurement.sourcePosition.locator.trim() || !Number.isInteger(measurement.sourcePosition.revision) || measurement.sourcePosition.revision < 1))
        problems.push("来源位置须含原件、有效版本和精确位置。");
    if (measurement.observedAt && (!Number.isFinite(Date.parse(measurement.observedAt)) || !/(Z|[+-]\d{2}:\d{2})$/i.test(measurement.observedAt)))
        problems.push("真实观测时间须含明确时区偏移。");
    if (measurement.originalTimezone) {
        try {
            new Intl.DateTimeFormat("zh-CN", { timeZone: measurement.originalTimezone });
        }
        catch (_a) {
            problems.push("观测原始时区须为有效 IANA 时区。");
        }
    }
    return problems;
}
function incompleteResultItems(run, measurements) {
    return run.coverage.testItemIds.filter(id => run.coverage.pairs.some(pair => pair.testItemId === id && !measurements.some(value => value.testItemId === id && value.sample.id === pair.sampleId)));
}
function pairKey(pair) { return `${pair.sampleId}:${pair.testItemId}`; }
function mergeCoverage(previous, current) {
    var _a;
    const pairs = [...((_a = previous === null || previous === void 0 ? void 0 : previous.pairs) !== null && _a !== void 0 ? _a : []), ...current.pairs].filter((pair, index, values) => values.findIndex(value => pairKey(value) === pairKey(pair)) === index);
    return { sampleIds: Array.from(new Set(pairs.map(pair => pair.sampleId))), testItemIds: Array.from(new Set(pairs.map(pair => pair.testItemId))), pairs };
}
function startProblems(data, context) {
    const problems = [];
    if (!context.executor || data.execution.executorId !== context.executor.id)
        problems.push("开测执行人须为服务器绑定的当前具名身份。");
    problems.push(...eventTimeProblems(data.time, "真实开始"));
    if (!context.startResources.equipment.some(value => canonical(value) === canonical(data.execution.equipment)) || !context.startResources.calibration.some(value => canonical(value) === canonical(data.execution.calibration)))
        problems.push("设备与校准须选择服务器当前可见的固定来源版本。");
    if (!data.execution.environment.trim() || !data.execution.conditions.trim())
        problems.push("真实环境与工况须明确记录。");
    return problems;
}
function eventTimeProblems(value, label) {
    const problems = [];
    if (!Number.isFinite(Date.parse(value.occurredAt)) || !/(Z|[+-]\d{2}:\d{2})$/i.test(value.occurredAt))
        problems.push(`${label}时间须含明确 UTC 或时区偏移。`);
    try {
        if (!value.originalTimezone.trim())
            throw new Error();
        new Intl.DateTimeFormat("zh-CN", { timeZone: value.originalTimezone });
    }
    catch (_a) {
        problems.push(`${label}须填写有效的原始 IANA 时区。`);
    }
    const source = value.source;
    if (!source.originalId.trim() || !source.kind.trim() || !source.locator.trim() || !Number.isInteger(source.revision) || source.revision < 1)
        problems.push(`${label}须固定有效来源及精确位置。`);
    return problems;
}
function coverageGaps(request, samples, coverage) {
    return request.testItems.flatMap(item => {
        const covered = samples.filter(sample => coverage.pairs.some(pair => pair.sampleId === sample.id && pair.testItemId === item.id));
        const cavities = item.method.cavities.filter(cavity => !covered.some(sample => sample.cavity === cavity));
        return covered.length < item.method.sampleQuantity || cavities.length ? [`${item.title}：本范围 ${covered.length}/${item.method.sampleQuantity} 件；未覆盖模穴 ${cavities.join("、") || "无"}。`] : [];
    });
}
