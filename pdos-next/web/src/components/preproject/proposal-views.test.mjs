import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(process.env.PDOS_WEB_DEPENDENCIES ?? webRoot, "package.json"));
const ts = dependency("typescript");
const React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const modules = new Map();
function load(filename) {
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_, key) => String(key) }) };
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(ext => filename + ext).find(existsSync);
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = specifier => specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2)))
    : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : dependency(specifier);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: {
    module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true,
  } }).outputText, filename);
  return loaded.exports;
}
const { ProposalSourceInspector } = load(path.join(directory, "proposal-source-inspector.tsx"));
const { ProposalViews } = load(path.join(directory, "proposal-views.tsx"));
const { isProposalViewResponse, matchesProposalDocument } = load(path.join(directory, "proposal-view-contracts.ts"));
const render = (component, props) => renderToStaticMarkup(React.createElement(component, props));
const document = { proposal_id: "proposal-one", revision: 4, document_digest: "fixed-document-digest", submission_id: "submission-one", document_mode: "submission" };
const metadata = { ...document, context_changes: [], engine_version: "server-v1", input_digest: "fixed-input-digest" };
const subjects = [{ type: "target", id: "target-one", label: "我方目标" }, { type: "competitor", id: "competitor-one", label: "竞品一" }];
const sources = [{ type: "snapshot", id: "real-source-id", version: 2, locator: { line: 8 }, quote: "原始证据" }];
const observation = { subject: subjects[0], observation_id: "observation-one", kind: "spec", value_type: "number", value: "123.456789012345", availability: "known", nature: "observed", evidence_kind: "measured", source_refs: sources, comparable: false, reasons: ["服务器判定：测试工况不同"] };
const group = { parameter_id: "parameter-one", parameter_version: 2, parameter: { key: "pressure", name: "压力", value_type: "number" }, unit: "kPa", condition_note: "25°C", test_conditions: { temperature: "25°C" }, observations: [observation], sample_count: 1, comparable_count: 0, unknown_count: 7, separation_reasons: ["参数版本不同，独立分组"] };
const comparison = { ...metadata, view: "spec-benchmark", data: { engine_version: "server-v1", input_digest: "fixed-input-digest", subjects, groups: [group], unmapped: [], unavailable: [], unknown_count: 7 } };
const positioning = { ...metadata, view: "positioning", data: { groups: [{ key: "price-facet", parameter_id: "parameter-one", parameter_version: 2, unit: "kPa", condition_note: "25°C", price_context: { currency: "CNY", basis: "retail", as_of: "2026-10-11", includes_tax: null, includes_shipping: false, channel: "retail", region: "CN" }, sample_count: 3,
  points: ["measured", "claimed", "inferred", "unknown"].map((evidence_kind, index) => ({ subject: subjects[index % 2], label: `观察${index}`, x: String(100 + index), y: String(10 + index), evidence_kind, source_refs: sources })) }], unknowns: [{ subject: subjects[1], reasons: ["价格日期未提供"] }], unmapped: [], unknown_count: 1 } };
const view = (result, overrides = {}) => render(ProposalViews, { view: result.view, result, document, ...overrides });

test("source details retain exact identity, version, locator and unavailable status", () => {
  const html = render(ProposalSourceInspector, { sources: [{
    type: "snapshot", id: "immutable-snapshot", version: 3,
    locator: { page: 2, start: 10, end: 25 }, availability: "unknown", status: "withdrawn",
  }] });
  for (const text of ["immutable-snapshot", "引用版本", "3", "page", "25", "unknown", "withdrawn", "<details", "<summary"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes("href="), false);
});

test("source addresses and markup remain inert text and missing content is not invented", () => {
  const html = render(ProposalSourceInspector, { sources: [{ type: "claim", id: "redacted", version: 1, status: "unavailable", url: "javascript:alert(1)", title: "<img src=x onerror=alert(1)>" }] });
  assert.ok(html.includes("javascript:alert(1)"));
  assert.ok(html.includes("&lt;img"));
  assert.equal(html.includes("href="), false);
  assert.equal(html.includes("<img"), false);
  assert.equal(html.includes("引用片段"), false);
});

test("empty references remain explicitly unavailable", () => {
  assert.ok(render(ProposalSourceInspector, { sources: [] }).includes("服务器未提供可读来源"));
});

test("comparison preserves server groups, precision, reasons and sample counts", () => {
  const html = view(comparison);
  for (const expected of [observation.value, "样本 1", "可比 0", "未知 7", "不可比", "服务器判定：测试工况不同", "参数版本不同，独立分组", "未知 · 未提供观察记录", "原始证据"]) assert.ok(html.includes(expected), expected);
  assert.ok(isProposalViewResponse(comparison));
});

test("feature booleans retain false and enum text; unmapped names are kept separate", () => {
  const feature = { ...comparison, view: "feature-config", data: { subjects, groups: [{ ...group, observations: [{ ...observation, value_type: "boolean", value: false }, { ...observation, observation_id: "enum-one", value_type: "enum", value: "server-enum-value" }] }], unmapped: [{ ...observation, key: "unmapped-free-key", parameter: "原始功能名" }] } };
  const html = view(feature);
  for (const expected of [">无<", "server-enum-value", "未映射条目", "原始功能名"]) assert.ok(html.includes(expected), expected);
  assert.ok(isProposalViewResponse(feature));
});

test("positioning plots known coordinates only and distinguishes evidence styles", () => {
  const html = view(positioning);
  assert.equal((html.match(/<circle /g) ?? []).length, 3);
  assert.ok(html.includes('fill="currentColor"'));
  assert.ok(html.includes('fill="var(--background)"'));
  assert.ok(html.includes('stroke-dasharray="3 2"'));
  assert.ok(html.includes('class="text-primary"'));
  assert.ok(html.includes('class="text-muted-foreground"'));
  for (const expected of ["价格日期未提供", "含税：未知", "含运费：否", "样本 3", "未知 1", "原始证据"]) assert.ok(html.includes(expected), expected);
  assert.equal(html.includes("NaN"), false);
  assert.equal(html.includes("Infinity"), false);
});

test("separate server price facets remain separate even with identical parameter ids", () => {
  const result = structuredClone(positioning);
  result.data.groups.push({ ...result.data.groups[0], key: "usd-price", price_context: { ...result.data.groups[0].price_context, currency: "USD", as_of: "2025-01-01" } });
  const html = view(result);
  assert.equal((html.match(/<svg /g) ?? []).length, 2);
  assert.ok(html.includes("CNY")); assert.ok(html.includes("USD")); assert.ok(html.includes("2025-01-01"));
});

test("nonfinite numeric coordinates never generate invalid SVG or invented values", () => {
  const result = structuredClone(positioning);
  result.data.groups[0].points = [{ ...result.data.groups[0].points[0], x: "not-a-number" }];
  const html = view(result);
  assert.equal(html.includes("<circle"), false);
  assert.equal(html.includes("<svg"), false);
  assert.ok(html.includes("没有可绘制的已知坐标"));
  assert.ok(html.includes("not-a-number"));
});

test("every document identity dimension rejects an old result", () => {
  for (const [key, value] of Object.entries({ proposal_id: "other", revision: 5, document_digest: "other", submission_id: null, document_mode: "current" })) {
    assert.equal(matchesProposalDocument(comparison, { ...document, [key]: value }), false, key);
    const html = view(comparison, { document: { ...document, [key]: value } });
    assert.ok(html.includes("当前提案版本的视图尚不可用"), key);
    assert.equal(html.includes(observation.value), false, key);
  }
});

test("loading, failed reads, wrong view and incomplete payload hide old successful content", () => {
  for (const extra of [{ loading: true }, { error: "FORBIDDEN_SCOPE" }, { view: "feature-config" }, { result: { ...comparison, data: {} } }, { result: null }]) {
    const html = view(comparison, extra);
    assert.equal(html.includes(observation.value), false);
    assert.equal(html.includes("<table"), false);
  }
  assert.equal(isProposalViewResponse({ ...comparison, data: {} }), false);
});

test("maturity renders only server counts, question assignments and exact blocker reasons", () => {
  const result = { ...metadata, view: "definition-maturity", data: { spec_count: 9, option_count: 1, item_status_counts: { ai_draft: 8, expert_pending: 1 }, availability_counts: { known: 8, conflicted: 1 }, submission_checks: { worth_it_present: false, alternative_or_reason_required: true }, freeze_blockers: [{ item_id: "spec-one", version: 3, content: { parameter: "压力" }, source_refs: sources, blocker_reasons: ["原文存在冲突", "缺少测试工况"] }], questions: [{ item_id: "question-one", version: 1, content: { question: "采用哪个测试工况？", owner_id: "human-owner", due_date: "2026-11-01", status: "open" } }], guidance: "服务器提醒：10–20 条仅作提示" } };
  const html = view(result);
  for (const expected of ["9 条关键规格", "原文存在冲突", "缺少测试工况", "human-owner", "2026-11-01", "待填写", "需填写没有替代方案的理由", result.data.guidance]) assert.ok(html.includes(expected), expected);
  assert.equal(html.includes("成熟度评分"), false);
  assert.ok(isProposalViewResponse(result));
});

test("rendering never issues requests or starts an agent", () => {
  let calls = 0;
  const original = globalThis.fetch;
  globalThis.fetch = () => { calls++; throw Error("unexpected request"); };
  try {
    const html = view(comparison, { onViewChange() {}, onRetry() {} });
    assert.ok(html.includes("切换提案视图"));
    assert.equal(calls, 0);
  } finally { globalThis.fetch = original; }
});

test("nonmeasurement evidence uses a separate marker and retains the original nature", () => {
  const result = structuredClone(positioning);
  result.data.groups[0].points = ["target", "decided", "computed", "custom-nature"].map(kind => ({ ...result.data.groups[0].points[0], evidence_kind: kind }));
  const html = view(result);
  assert.equal((html.match(/<rect /g) ?? []).length, 4);
  assert.equal(html.includes("<circle"), false);
  assert.ok(html.includes("custom-nature"));
});

test("free-text feature sections remain separate and never become mapped feature values", () => {
  const result = { ...comparison, view: "feature-config", data: { subjects: [{ ...subjects[0], unmapped_features: [{ item_id: "feature-section", text: "明确不做：自动调压", source_refs: sources, reasons: ["unmapped_feature_text"] }] }], groups: [], unmapped: [], unavailable: [{ subject: subjects[0], reasons: ["source_unavailable"] }] } };
  const html = view(result);
  assert.ok(html.includes("明确不做：自动调压"));
  assert.ok(html.includes("功能叙述尚未映射到字典参数"));
  assert.ok(html.includes("来源不可用"));
  assert.equal(html.includes("<td"), false);
});


test("nullable unavailable feature text retains its source identity without displaying hidden content", () => {
  const feature = { item_id: "redacted-feature", text: null, availability: "unknown", source_refs: [{ type: "artifact", id: "restricted-source", version: 3, status: "unavailable" }], reasons: ["feature_source_unavailable"] };
  const result = { ...comparison, view: "feature-config", data: { subjects: [{ ...subjects[0], unmapped_features: [feature] }], groups: [], unmapped: [] } };
  assert.ok(isProposalViewResponse(result));
  const html = view(result);
  assert.ok(html.includes("来源不可用，暂不展示功能叙述。"));
  assert.ok(html.includes("restricted-source"));
  assert.equal(html.includes("功能叙述尚未映射到字典参数"), false);
  // A contradictory server value must not expose text marked unavailable either.
  const inconsistent = structuredClone(result);
  inconsistent.data.subjects[0].unmapped_features[0].text = "HIDDEN ORIGINAL FEATURE";
  assert.equal(view(inconsistent).includes("HIDDEN ORIGINAL FEATURE"), false);
});

test("unknown positioning records drill into the returned redacted references", () => {
  const result = structuredClone(positioning);
  result.data.groups = [];
  result.data.unknowns = [{ subject: subjects[1], label: "服务器竞品名称", observation_id: "actual-observation-id", price_index: 0, reasons: ["source_unavailable"], source_refs: [{ type: "artifact", id: "unavailable-source-id", version: 7, status: "unavailable" }] }];
  assert.ok(isProposalViewResponse(result));
  const html = view(result);
  for (const value of ["服务器竞品名称", "actual-observation-id", "价格记录索引：0", "unavailable-source-id", "引用版本", "来源状态", "查看来源"]) assert.ok(html.includes(value), value);
  assert.equal(html.includes("原始证据"), false);
  assert.equal(html.includes("<svg"), false);
  result.data.unknowns[0].source_refs = "invalid";
  assert.equal(isProposalViewResponse(result), false);
});

test("unrepresentable decimal coordinates retain exact text and explain why they are not plotted", () => {
  for (const value of ["1E-400", "1E+400", "9007199254740993", "0.10000000000000001"]) {
    const result = structuredClone(positioning);
    result.data.groups[0].points = [{ ...result.data.groups[0].points[0], y: value }];
    const html = view(result);
    assert.ok(html.includes(`参数 ${value}`), value);
    assert.ok(html.includes("原值超出绘图精度或范围，仅保留原始文本。"), value);
    assert.ok(html.includes("real-source-id"), value);
    assert.equal(html.includes("<svg"), false, value);
    assert.equal(html.includes("参数 0 ·"), false, value);
  }
});

test("finite extreme endpoints do not overflow the SVG scale", () => {
  const result = structuredClone(positioning);
  const point = result.data.groups[0].points[0];
  result.data.groups[0].points = [{ ...point, y: "-1E+308" }, { ...point, y: "1E+308" }];
  const html = view(result);
  assert.ok(html.includes("参数 -1E+308"));
  assert.ok(html.includes("参数 1E+308"));
  assert.ok(html.includes("数值跨度超出绘图范围，仅保留原始文本。"));
  assert.equal(html.includes("<svg"), false);
  assert.equal(html.includes("NaN"), false);
  assert.equal(html.includes("Infinity"), false);
});

test("true zero and equivalent decimal spellings remain plotable", () => {
  for (const value of ["0", "-0.000", "0E-400", "1.2500", "1.25E+2"]) {
    const result = structuredClone(positioning);
    result.data.groups[0].points = [{ ...result.data.groups[0].points[0], x: "0", y: value }];
    const html = view(result);
    assert.ok(html.includes("<circle"), value);
    assert.ok(html.includes(`参数 ${value}`), value);
    assert.equal(html.includes("原值超出绘图精度"), false, value);
    assert.equal(html.includes("NaN"), false, value);
  }
});

test("single numeric source bounds remain explicit constraints in the actual comparison view", () => {
  const upper = structuredClone(comparison);
  upper.data.groups[0].observations[0] = { ...observation, value: null, lower: null, upper: "75", nature: "extracted", evidence_kind: "target" };
  const html = view(upper);
  assert.ok(html.includes("≤75")); assert.ok(html.includes("原始证据"));
  assert.equal(html.includes("未知 ～ 75"), false);
  const lower = structuredClone(upper);
  lower.data.groups[0].observations[0].lower = "0"; lower.data.groups[0].observations[0].upper = null;
  assert.ok(view(lower).includes("≥0"));
});
