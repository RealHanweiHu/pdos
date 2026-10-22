import assert from "node:assert/strict";
import { existsSync, readFileSync, writeFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as icons from "@phosphor-icons/react";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(extension => filename + extension).find(existsSync);
  if (!filename) throw new Error("Test module not found");
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename);
  modules.set(filename, loaded);
  const localRequire = createRequire(filename);
  loaded.require = specifier => specifier === "@phosphor-icons/react" ? icons : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2))) : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : localRequire(specifier);
  const compiled = ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } });
  loaded._compile(compiled.outputText, filename);
  return loaded.exports;
}
const { context, source, ref, scope, counts, result, toolTrial, pilot, canonicalIntents, newIds } = load(path.join(directory, "__tests__/fixtures.ts"));
const { toDomainPayload, domainCounts } = load(path.join(directory, "domain-payload.ts"));
const { resultProblems, fixedContextKey, baseProblems, staleProblems } = load(path.join(directory, "contracts.ts"));
const { ToolTrialWorkbench, PilotRunWorkbench } = load(path.join(directory, "preparation.tsx"));
const { PilotResultsWorkbench, YieldReading, displayRate } = load(path.join(directory, "results.tsx"));
const action = { busy: false, unresolved: false };
const callbacks = { onPreview: async () => { throw new Error("Rendering must never preview or write"); } };
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
const check = (options = {}) => resultProblems(options.scope ?? scope, "counts" in options ? options.counts : counts, options.units ?? [], options.occurredAt ?? result.occurredAt, options.timezone ?? result.originalTimezone, "source" in options ? options.source : source, options.previous ?? null, options.reason ?? "", options.missing ?? "");

test("tool trial preserves round, write tier, cavity/parameter sources and quality gaps", () => {
  const html = render(ToolTrialWorkbench, { context, fixed: toolTrial, action, callbacks, initialPurpose: "合成探索试模", initialRound: 2 });
  for (const text of ["trial_round", "写入方式：一次确认", "A1、A2", "12", "MPa", "原始问题引用", "整改来源", "具名验收来源", "实际样件待产出", "方法需专业核对", "资格已撤回", "品质请求由验证模块在共同事务中建立或关联"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes("确认并执行"), false);
});
test("port unavailable disables trial entry and never fabricates a receipt", () => {
  const html = render(ToolTrialWorkbench, { context: { ...context, portReady: false }, fixed: toolTrial, action, callbacks, initialPurpose: "探索" });
  assert.match(html, /<button[^>]*disabled=""[^>]*>预览试模候选<\/button>/);
  assert.ok(html.includes("待接入"));
  assert.equal(html.includes("已成功创建"), false);
});
test("missing baseline and draft process remain explicit while a candidate is allowed", () => {
  const html = render(PilotRunWorkbench, { context, fixed: pilot, action, callbacks, initialPurpose: "合成准备" });
  for (const text of ["实际 BuildLot", "实际型号配置", "正式制造基线未齐", "仅为草稿", "尚不可宣称正式可开工", "不新增库存", "正式制造基线缺失"]) assert.ok(html.includes(text), text);
  assert.match(html, /<button(?![^>]*disabled="")[^>]*>预览试产候选<\/button>/);
});
test("stale actual configuration disables pilot preparation", () => {
  const html = render(PilotRunWorkbench, { context, fixed: { ...pilot, actualConfiguration: { ...pilot.actualConfiguration, current: false } }, action, callbacks, initialPurpose: "准备" });
  assert.match(html, /<button[^>]*disabled=""[^>]*>预览试产候选<\/button>/);
  assert.ok(html.includes("固定版本或来源需重核"));
});
test("common preview and receipt slots render and unresolved state blocks duplicate attempts", () => {
  const html = render(PilotRunWorkbench, { context, fixed: pilot, callbacks, initialPurpose: "准备", action: { ...action, unresolved: true, previewSlot: React.createElement("p", null, "共同预览插槽"), receiptSlot: React.createElement("p", null, "共同回执插槽") } });
  for (const text of ["共同预览插槽", "共同回执插槽", "不重复提交"]) assert.ok(html.includes(text));
  assert.match(html, /<button[^>]*disabled=""[^>]*>预览试产候选<\/button>/);
});
test("reading separates first pass/final yield, real/received time and sample limits", () => {
  const html = render(YieldReading, { result });
  for (const text of ["首次通过率", "最终合格率", "60%", "80%", "累计返工次数", "样本不足", "不声明长期过程能力或工厂资格", "系统接收", "真实发生", "合成", "不平均百分比"]) assert.ok(html.includes(text), text);
});
test("zero and unknown denominators cannot render successful supplied percentages", () => {
  for (const [denominator, message] of [[0, "零分母 / 不可计算"], [null, "未知分母"]]) {
    const html = render(YieldReading, { result: { ...result, scope: { ...scope, denominator }, firstPassRate: "1", finalGoodRate: "1" } });
    assert.ok(html.includes(message)); assert.equal(html.includes("100%"), false);
  }
});
test("quantity conflict or missing results hides supplied rates", () => {
  for (const status of ["conflicted", "no_results"]) assert.equal(render(YieldReading, { result: { ...result, status } }).includes("80%"), false);
  for (const rate of ["NaN", "2", "-0.1", "", "0.3 text"]) assert.equal(displayRate(rate, 10, "complete"), "口径需重核");
});
test("results expose fixed denominator and source selection without editable authority fields", () => {
  const html = render(PilotResultsWorkbench, { context, scope, previous: null, sources: [source], action, callbacks });
  for (const text of ["留空表示未知", "返工次数不增加投入", "固定观察来源及精确位置", "原始 IANA 时区", "由服务器绑定接收时间"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes('name="tenantId"'), false);
  assert.equal(html.includes('name="denominator"'), false);
  assert.match(html, /<button[^>]*disabled=""[^>]*>预览观察与统计口径<\/button>/);
});
test("immutable correction retains original reference and requires reason", () => {
  const previous = ref("observation");
  const html = render(PilotResultsWorkbench, { context, scope, previous, sources: [source], action, callbacks });
  assert.ok(html.includes("修正试产观察（续版）")); assert.ok(html.includes("原观察不覆盖"));
  assert.ok(check({ previous }).some(problem => problem.includes("修正原因")));
  assert.deepEqual(check({ previous, reason: "原报告计数修正" }), []);
});
test("multiple rework cycles never increase fixed denominator", () => {
  assert.deepEqual(check({ counts: { ...counts, reworkAttempts: 35 } }), []);
  assert.ok(check({ counts: { ...counts, input: 45, reworkAttempts: 35 } }).some(problem => problem.includes("固定分母")));
});
test("exclusive terminal quantities and first-pass result detect contradictions", () => {
  assert.ok(check({ counts: { ...counts, finalGood: 9 } }).some(problem => problem.includes("互斥")));
  assert.ok(check({ counts: { ...counts, finalGood: 5, undetermined: 3 } }).some(problem => problem.includes("首次通过")));
  assert.ok(check({ counts: { ...counts, scrap: -1 } }).some(problem => problem.includes("非负安全整数")));
  assert.ok(check({ counts: { ...counts, reworkAttempts: 1.5 } }).some(problem => problem.includes("非负安全整数")));
});
test("partial unknown count remains recordable only with explicit missing scope", () => {
  assert.ok(check({ counts: { ...counts, firstPassGood: null } }).some(problem => problem.includes("局部未知")));
  assert.deepEqual(check({ counts: { ...counts, firstPassGood: null }, missing: "首次结果报告待接收" }), []);
  assert.ok(check({ counts: { ...counts, finalGood: 10, scrap: 1, reworkPending: null }, missing: "待核对" }).some(problem => problem.includes("超过固定投入")));
});
test("unknown denominator is kept unknown and cannot silently become zero", () => {
  assert.deepEqual(check({ scope: { ...scope, denominator: null }, counts: Object.fromEntries(Object.keys(counts).map(key => [key, null])), missing: "投入与结果均待原值核对" }), []);
  assert.ok(check({ scope: { ...scope, denominator: null } }).some(problem => problem.includes("固定分母")));
});
test("scope must preserve unit, criterion, window and current facts", () => {
  assert.ok(check({ scope: { ...scope, unit: "" } }).some(problem => problem.includes("单位")));
  assert.ok(check({ scope: { ...scope, criterion: { ...scope.criterion, source: { ...source, status: "withdrawn" } } } }).some(problem => problem.includes("判据")));
  assert.ok(check({ occurredAt: "2026-10-01T09:00:00-07:00" }).some(problem => problem.includes("窗口")));
  assert.ok(check({ scope: { ...scope, lot: { ...scope.lot, current: false } } }).some(problem => problem.includes("需重核")));
});
test("source cannot mix synthetic/real or withdrawn facts and event time needs a valid timezone", () => {
  assert.ok(check({ source: { ...source, synthetic: false } }).some(problem => problem.includes("合成与现实")));
  assert.ok(check({ source: { ...source, status: "withdrawn" } }).some(problem => problem.includes("当前来源")));
  assert.ok(check({ occurredAt: "2026-10-02T09:00:00" }).some(problem => problem.includes("发生时间")));
  assert.ok(check({ timezone: "not-a-zone" }).some(problem => problem.includes("IANA")));
});
test("unit mode cannot mix batch counts, duplicate samples or conflicting first passes", () => {
  const sample = ref("sample");
  const unitScope = { ...scope, denominator: 1, allocation: { mode: "unit", samples: [sample] } };
  const units = [{ sample, firstPass: "fail", outcome: "good", reworkAttempts: 3, source }];
  assert.deepEqual(check({ scope: unitScope, counts: null, units }), []);
  assert.ok(check({ scope: unitScope, units }).some(problem => problem.includes("逐件观察")));
  assert.ok(check({ scope: unitScope, counts: null, units: [...units, ...units] }).some(problem => problem.includes("逐件观察")));
  assert.ok(check({ scope: unitScope, counts: null, units: [{ ...units[0], firstPass: "pass" }] }).some(problem => problem.includes("矛盾")));
});
test("unit UI pins each real sample and cannot create a sample ledger", () => {
  const unitScope = { ...scope, denominator: 1, allocation: { mode: "unit", samples: [ref("sample")] } };
  const html = render(PilotResultsWorkbench, { context, scope: unitScope, previous: null, sources: [source], action, callbacks });
  for (const text of ["固定实际样件", "每件唯一终态", "首次结果", "唯一终态", "累计返工次数"]) assert.ok(html.includes(text));
  assert.equal(html.includes("新增样件"), false);
});
test("server context/version drift and fixed batch/config changes alter the preview binding", () => {
  const key = fixedContextKey(context, scope);
  assert.notEqual(key, fixedContextKey({ ...context, version: "v2" }, scope));
  assert.notEqual(key, fixedContextKey(context, { ...scope, lot: { ...scope.lot, revision: 2 } }));
  assert.notEqual(key, fixedContextKey(context, { ...scope, actualConfiguration: { ...scope.actualConfiguration, revision: 2 } }));
  assert.ok(baseProblems({ ...context, capabilities: { ...context.capabilities, resultRecord: false } }, "npi.pilot.result.record").length);
  assert.ok(staleProblems([{ ...ref("fixture"), revision: 0 }]).length);
});

test("adapter emits exact closed top-level DTO shapes for all three canonical operations", () => {
  const expected = [
    ["trial_id", "build", "tooling", "trial_round", "purpose", "cavities", "material_lots", "parameters", "issues", "corrective_actions", "named_acceptances", "verification", "source"],
    ["pilot_id", "basis", "purpose", "manufacturing_baseline", "line", "people", "material_lots", "fixtures", "equipment", "instructions", "control_plan", "risk", "reservation", "first_article", "parameters", "source"],
    ["observation_id", "expected_pilot_revision", "previous_observation_id", "correction_reason", "scope", "counts", "units", "exceptions", "observed", "source"],
  ];
  for (const [index, intent] of canonicalIntents.entries()) {
    const payload = toDomainPayload(intent, newIds[index]);
    assert.deepEqual(Object.keys(payload).sort(), expected[index].sort());
    const serialized = JSON.stringify(payload);
    for (const forbidden of ['"operation":', '"label":', '"current":', '"synthetic":', '"status":', '"capabilities":']) assert.equal(serialized.includes(forbidden), false, forbidden);
    assert.deepEqual(Object.keys(payload.source).sort(), ["id", "revision", "kind", "position"].sort());
  }
});
test("all 12 counts map one-to-one and unknowns remain JSON null", () => {
  assert.deepEqual(domainCounts(counts), { input_count: 10, output_count: 10, first_pass: 6, first_failed: 4, first_unknown: 0, final_good: 8, reworked_good: 2, scrap: 1, rework_pending: 1, undecided: 0, unprocessed: 0, rework_cycles: 5 });
  const unknown = Object.fromEntries(Object.keys(counts).map(key => [key, null]));
  assert.equal(Object.keys(domainCounts(unknown)).length, 12);
  assert.ok(Object.values(JSON.parse(JSON.stringify(domainCounts(unknown)))).every(value => value === null));
});
test("verification DTO preserves complete method/criterion/document scope without invented refs", () => {
  const payload = toDomainPayload(canonicalIntents[0], newIds[0]);
  assert.deepEqual(payload.verification, toolTrial.quality.requestCreate);
  assert.deepEqual(Object.keys(payload.verification.items[0]).sort(), ["id", "feature", "drawing", "method", "criterion", "criterion_text", "criterion_source", "unit", "conditions", "material", "sample_count", "cavities", "destructive"].sort());
  assert.deepEqual(payload.corrective_actions[0], { kind: "corrective_action", id: toolTrial.corrections[0].id, revision: 1 });
  assert.throws(() => toDomainPayload({ ...canonicalIntents[0], fixed: { ...toolTrial, quality: { ...toolTrial.quality, requestCreate: null } } }, newIds[0]), /RequestCreate/);
  assert.throws(() => toDomainPayload({ ...canonicalIntents[0], fixed: { ...toolTrial, quality: { ...toolTrial.quality, requestCreate: { ...toolTrial.quality.requestCreate, build_id: newIds[0] } } } }, newIds[0]), /Build/);
  assert.throws(() => toDomainPayload(canonicalIntents[1], "generated-later"), /UUID/);
});
test("result scope, event and exceptions have exact fixed reference/source shape", () => {
  const payload = toDomainPayload(canonicalIntents[2], newIds[2]);
  assert.deepEqual(Object.keys(payload.scope).sort(), ["basis", "manufacturing_baseline", "line", "cohort_key", "window_start", "window_end", "criterion", "nature", "minimum_sample"].sort());
  assert.deepEqual(Object.keys(payload.scope.basis).sort(), ["build", "lot", "actual_configuration", "engineering_configuration", "process_revision", "unit"].sort());
  assert.equal(payload.scope.criterion.kind, "criterion"); assert.equal(payload.scope.minimum_sample, 30);
  assert.deepEqual(payload.observed, { occurred_at: result.occurredAt, original_timezone: result.originalTimezone, source: payload.source, effective_at: null });
  assert.deepEqual(payload.exceptions[0], { key: "dimension_deviation", description: "一次加工尺寸偏差", source: payload.source, issue: { kind: "issue", id: ref("issue").id, revision: 1 }, disposition: payload.source });
  assert.throws(() => toDomainPayload({ ...canonicalIntents[2], scope: { ...scope, minimumSample: 0 } }, newIds[2]), /minimum_sample/);
});
test("unprocessed unit DTO is sourced and cannot carry rework or processed first result", () => {
  const sample = ref("sample");
  const unitScope = { ...scope, denominator: 1, allocation: { mode: "unit", samples: [sample] } };
  const unit = { sample, firstPass: "unprocessed", outcome: "unprocessed", reworkAttempts: 0, source };
  assert.deepEqual(check({ scope: unitScope, counts: null, units: [unit] }), []);
  assert.ok(check({ scope: unitScope, counts: null, units: [{ ...unit, reworkAttempts: 1 }] }).some(problem => problem.includes("矛盾")));
  assert.ok(check({ scope: unitScope, counts: null, units: [{ ...unit, firstPass: "unknown" }], missing: "未知" }).some(problem => problem.includes("矛盾")));
  const payload = toDomainPayload({ ...canonicalIntents[2], scope: unitScope, counts: null, units: [unit] }, newIds[2]);
  assert.deepEqual(payload.units[0], { sample: { kind: "sample", id: sample.id, revision: 1 }, first_result: "unprocessed", final_state: "unprocessed", rework_cycles: 0, source: payload.source });
  assert.throws(() => toDomainPayload({ ...canonicalIntents[2], scope: unitScope, counts: null, units: [{ ...unit, source: null }] }, newIds[2]), /逐件观察/);
});
test("unknown first outcomes suppress a supplied reliable first-pass percentage", () => {
  for (const firstUnknown of [null, 1]) {
    const html = render(YieldReading, { result: { ...result, counts: { ...counts, firstUnknown } } });
    assert.ok(html.includes("首次结果有未知 / 不可可靠计算"));
    assert.equal(html.includes("60%"), false);
  }
});
test("UI exposes new closed count fields and fixed manufacturing references", () => {
  const html = render(PilotResultsWorkbench, { context, scope, previous: null, sources: [source], action, callbacks });
  for (const text of ["实际产出", "首次失败", "首次结果未知", "返工后合格", "未加工", "已有具名处置来源", "此处只引用，不作决定", "工程配置", "固定判据版本"]) assert.ok(html.includes(text), text);
  const pilotHtml = render(PilotRunWorkbench, { context, fixed: pilot, action, callbacks, initialPurpose: "准备" });
  for (const text of ["作业指引固定版本", "控制计划", "过程风险", "资源预约固定引用", "创建来源", "固定单位"]) assert.ok(pilotHtml.includes(text), text);
});
test("single instant observations and unknown parameter fields match backend semantics", () => {
  const instant = { ...scope, window: { start: result.occurredAt, end: result.occurredAt } };
  assert.deepEqual(check({ scope: instant }), []);
  const { ParameterReading } = load(path.join(directory, "display.tsx"));
  const html = render(ParameterReading, { parameters: [{ key: "压力", value: null, unit: null, source: null }] });
  for (const text of ["未知", "单位未知", "来源未知"]) assert.ok(html.includes(text), text);
});

if (process.env.PDOS_MANUFACTURING_PAYLOAD_FIXTURES) {
  const payloads = Object.fromEntries(canonicalIntents.map((intent, index) => [intent.operation, toDomainPayload(intent, newIds[index])]));
  writeFileSync(process.env.PDOS_MANUFACTURING_PAYLOAD_FIXTURES, JSON.stringify(payloads, null, 2) + "\n");
}
