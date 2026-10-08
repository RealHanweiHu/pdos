import assert from "node:assert/strict";
import { readFileSync, existsSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as icons from "@phosphor-icons/react";

// In-memory isolated TSX loader; no Next build, dependency installation or disk cache.
const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript");
const React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server");
const modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".tsx", ".ts"].map(extension => filename + extension).find(existsSync);
  if (!filename) throw new Error("Test module could not be found");
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename);
  modules.set(filename, loaded);
  const localRequire = createRequire(filename);
  loaded.require = specifier => specifier === "@phosphor-icons/react" ? icons : specifier.startsWith("@/") ? load(path.join(webRoot, "src", specifier.slice(2))) : specifier.startsWith(".") ? load(path.resolve(path.dirname(filename), specifier)) : localRequire(specifier);
  const compiled = ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2017, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } });
  loaded._compile(compiled.outputText, filename);
  return loaded.exports;
}
const { request, context, source, action, impact } = load(path.join(directory, "__tests__/fixtures.ts"));
const { emptyDraft, unresolved } = load(path.join(directory, "contracts.ts"));
const { editorIntent } = load(path.join(directory, "editor.ts"));
const { ChangeControlReading, ChangeImpactReading } = load(path.join(directory, "reading.tsx"));
const { ChangeControlWorkbench } = load(path.join(directory, "workbench.tsx"));
const render = (Component, props) => renderToStaticMarkup(React.createElement(Component, props));
const writeForbidden = () => { throw new Error("Synthetic render must not write"); };
const draft = (operation, overrides = {}) => ({ ...emptyDraft(operation), text: "合成本次决定", approvalExpiresAt: "2026-10-09T17:00:00Z", ...overrides });
const complete = { ...request, order: { ...request.order, effectiveScopeIds: ["A", "B"], awaitingScopeIds: [] } };
const decide = draft("change.verification.record", { verificationKey: "verification" });

test("explicit engineering and manufacturing edges, missing coverage and AI guesses stay distinct", () => {
  const html = render(ChangeControlReading, { request });
  for (const text of ["规格约束", "装配工序", "synthetic-spec", "synthetic-operation", "合成工序到治具缺边", "AI 合成治具兼容性猜测", "无引用", "合成报告第 4 行", "UNKNOWN"]) assert.ok(html.includes(text), text);
});
test("missing manufacturing edge does not claim no impact", () => {
  const html = render(ChangeImpactReading, { impact: { ...impact, paths: impact.paths.filter(value => value.line === "engineering") } });
  assert.ok(html.includes("不能认定无影响"));
});
test("approval, implementation failure, partial effectivity and independent review remain separate", () => {
  const html = render(ChangeControlReading, { request });
  for (const text of ["仅批准工程范围", "尚无此专业具名批准", "合成实施故障保留", "仅合成 A 范围已生效", "等待实际回执范围：B", "尚无具名独立复核决定", "尚未具名关闭", "不表示已建新配置", "日期到期不会自动批准或生效"]) assert.ok(html.includes(text), text);
});
test("unknown ports and unregistered actions disable preparation without invented receipts", () => {
  for (const changed of [{ ...context, portReady: false }, { ...context, capabilities: {} }]) {
    const html = render(ChangeControlWorkbench, { request, context: changed, draft: draft("change.order.approve", { discipline: "manufacturing" }), action, onDraftChange: writeForbidden, onPrepare: writeForbidden, sharedReview: null });
    assert.match(html, /<button[^>]*disabled=""[^>]*>核对本次实质范围<\/button>/);
    assert.equal(html.includes("回执："), false);
  }
});
test("AI can prepare only named T2 candidate; component never owns confirmation", () => {
  const html = render(ChangeControlWorkbench, { request, context: { ...context, actor: { id: "synthetic-agent", label: "合成 AI", kind: "ai" } }, draft: draft("change.order.approve", { discipline: "manufacturing" }), action, onDraftChange: writeForbidden, onPrepare: writeForbidden, sharedReview: null });
  assert.ok(html.includes("准备具名决定候选"));
  assert.ok(html.includes("本组件不执行确认"));
  assert.equal(html.includes("具名提交此决定"), false);
});
test("unknown original action blocks every new prepare until shared receipt recovery", () => {
  for (const changed of [{ ...action, unknown: true }, { ...action, receipt: { outcome: "unknown", id: null } }, { ...action, receipt: { outcome: "committed", id: null } }]) {
    assert.equal(unresolved(changed), true);
    const html = render(ChangeControlWorkbench, { request, context, draft: draft("change.order.approve", { discipline: "manufacturing" }), action: changed, onDraftChange: writeForbidden, onPrepare: writeForbidden, sharedReview: React.createElement("div", null, "合成共同回执区") });
    assert.ok(html.includes("当前禁止重提新动作"));
    assert.match(html, /<button[^>]*disabled=""[^>]*>核对本次实质范围<\/button>/);
  }
});
test("source/configuration drift invalidates old effectivity plan and decisions", () => {
  assert.equal(editorIntent(draft("change.order.approve", { discipline: "manufacturing" }), { ...request, requiresRecheck: true }, context).intent, null);
  assert.equal(editorIntent(draft("change.order.prepare", { planKey: "plan" }), { ...request, impact: { ...impact, revision: 2 } }, context).intent, null);
  assert.equal(editorIntent(draft("change.order.approve", { discipline: "manufacturing" }), { ...request, impact: { ...impact, revision: 2 } }, context).intent, null);
});
test("cross-scope references and withdrawn sources cannot produce new requests", () => {
  const create = draft("change.request.create", { title: "合成新请求", rootKeys: ["part"], referenceKeys: ["not-authorized"] });
  assert.equal(editorIntent(create, null, context).intent, null);
  assert.equal(editorIntent({ ...create, referenceKeys: ["issue"] }, null, { ...context, referenceOptions: [{ ...context.referenceOptions[0], source: { ...source, status: "withdrawn" } }] }).intent, null);
});
test("fixed input source and audience omissions retain unknown rather than computing complete impact", () => {
  for (const change of [{ audience: [] }, { sourceScope: "" }, { current: false }, { refs: [] }]) {
    assert.equal(editorIntent(draft("change.impact.compute", { inputBundleKey: "bundle" }), request, { ...context, inputBundles: [{ ...context.inputBundles[0], ...change }] }).intent, null);
  }
});
test("proposer self approval and lowered named-decision tier are refused", () => {
  const approve = draft("change.order.approve", { discipline: "manufacturing" });
  assert.equal(editorIntent(approve, { ...request, impact: { ...impact, unknowns: [] } }, { ...context, actor: { ...context.actor, id: request.requestedBy } }).intent, null);
  assert.equal(editorIntent(approve, request, { ...context, capabilities: { ...context.capabilities, "change.order.approve": { ...context.capabilities["change.order.approve"], tier: "T1" } } }).intent, null);
});
test("implementation references exact owner fact and preserves failed/unknown outcomes", () => {
  const implementation = draft("change.implementation.record", { implementationKey: "implementation" });
  const executorContext = { ...context, actor: { ...context.actor, id: "synthetic-operator" } };
  for (const outcome of ["failed", "unknown"]) {
    const changed = { ...executorContext, implementationCandidates: [{ ...context.implementationCandidates[0], fact: { ...context.implementationCandidates[0].fact, outcome } }] };
    const result = editorIntent(implementation, request, changed);
    assert.equal(result.intent.factId, "synthetic-implementation-fact");
    assert.equal(result.intent.itemId, "A");
    assert.equal("outcome" in result.intent, false, "client must not claim owner facts");
  }
  assert.equal(editorIntent(implementation, request, context).intent, null, "another actor cannot record implementation");
  assert.equal(editorIntent(implementation, request, { ...executorContext, implementationCandidates: [{ ...context.implementationCandidates[0], serverVerified: false }] }).intent, null);
});
test("unverified or outside-range receipt cannot assert actual effectivity", () => {
  const effectivity = draft("change.effectivity.record", { receiptKey: "receipt" });
  assert.equal(editorIntent(effectivity, request, { ...context, receiptCandidates: [{ ...context.receiptCandidates[0], serverVerified: false }] }).intent, null);
  assert.equal(editorIntent(effectivity, request, { ...context, receiptCandidates: [{ ...context.receiptCandidates[0], receipt: { ...context.receiptCandidates[0].receipt, scopeIds: ["outside"] } }] }).intent, null);
});
test("partial effectivity and insufficient independent coverage block verification", () => {
  assert.equal(editorIntent(decide, request, context).intent, null);
  assert.equal(editorIntent(decide, complete, { ...context, verificationCandidates: [{ ...context.verificationCandidates[0], scopeIds: ["A"] }] }).intent, null);
  assert.equal(editorIntent(decide, complete, { ...context, verificationCandidates: [{ ...context.verificationCandidates[0], independent: false }] }).intent, null);
  assert.ok(editorIntent(decide, complete, context).intent);
});
test("all professional executors are excluded from independent self review", () => {
  for (const actorId of [...request.order.excludedReviewerIds, "synthetic-measurer"]) {
    assert.equal(editorIntent(decide, complete, { ...context, actor: { ...context.actor, id: actorId } }).intent, null);
  }
});
test("approval and implementation alone never close an order", () => {
  assert.equal(editorIntent(draft("change.close"), complete, context).intent, null);
});
test("current independent effective decision enables separate named closure, stale decision does not", () => {
  const decision = { actorId: context.actor.id, actorLabel: context.actor.label, at: "2026-10-02T17:00:00Z", text: "合成独立有效", sources: [source], result: "effective", independent: true, coverageScopeIds: ["A", "B"], runs: [context.verificationCandidates[0].refs[0]] };
  const verified = { ...complete, order: { ...complete.order, verification: [decision] } };
  assert.ok(editorIntent(draft("change.close"), verified, context).intent);
  assert.equal(editorIntent(draft("change.close"), { ...verified, order: { ...verified.order, verification: [{ ...decision, sources: [{ ...source, status: "stale" }] }] } }, context).intent, null);
});
test("history remains visible when a later decision becomes effective", () => {
  const decision = { actorId: context.actor.id, actorLabel: context.actor.label, at: "2026-10-02T17:00:00Z", text: "合成新有效性结论", sources: [source], result: "effective", independent: true, coverageScopeIds: ["A", "B"], runs: context.verificationCandidates[0].refs };
  const html = render(ChangeControlReading, { request: { ...complete, order: { ...complete.order, verification: [{ ...decision, result: "ineffective", text: "合成旧无效结论保留" }, decision] } } });
  assert.ok(html.includes("合成旧无效结论保留"));
  assert.ok(html.includes("合成新有效性结论"));
  assert.ok(html.includes("尚未具名关闭"));
});
test("unknown known-object disposition blocks approval and stays visible", () => {
  const changed = { ...request, impact: { ...impact, unknowns: [] }, order: { ...request.order, plan: { ...request.order.plan, dispositions: [{ ...request.order.plan.dispositions[0], handling: "unknown" }] } } };
  assert.equal(editorIntent(draft("change.order.approve", { discipline: "manufacturing" }), changed, context).intent, null);
  assert.ok(render(ChangeControlReading, { request: changed }).includes("UNKNOWN · 不得批准"));
});
test("new source/root revision prepares independently and preserves old request projection", () => {
  const stale = { ...request, requiresRecheck: true, recheckReasons: ["合成规格换版"] };
  const intent = editorIntent(draft("change.request.revise", { title: "合成修订", rootKeys: ["part"], referenceKeys: ["issue"] }), stale, context).intent;
  assert.equal(intent.operation, "change.request.revise");
  assert.equal(intent.request.revision, request.revision);
  assert.equal(stale.order.implementations[0].outcome, "failed");
});
test("order preparation retains exact server unit tokens and every disposition", () => {
  const intent = editorIntent(draft("change.order.prepare", { planKey: "plan" }), request, context).intent;
  assert.strictEqual(intent.plan, context.planCandidates[0].commandPlan);
  assert.deepEqual(intent.plan.items[0].selection.units, ["batch:synthetic-lot-A"]);
  assert.deepEqual(intent.plan.dispositions, request.order.plan.dispositions);
});
test("transport sent or accepted stage never displays established effectivity", () => {
  for (const stage of ["sent", "accepted"]) {
    const html = render(ChangeControlReading, { request: { ...request, order: { ...request.order, effectivity: [{ ...request.order.effectivity[0], stage, outcome: "effective" }] } } });
    assert.ok(html.includes("未证实际生效"));
    assert.equal(html.includes("已明确生效 ·"), false);
  }
});
test("impact unknown blocks named approval preparation even when every disposition is covered", () => {
  const approve = draft("change.order.approve", { discipline: "manufacturing" });
  assert.ok(request.order.plan.dispositions.every(value => value.handling !== "unknown"));
  const result = editorIntent(approve, request, context);
  assert.equal(result.intent, null);
  assert.ok(result.problem.includes("影响评估仍有缺边"));
  const html = render(ChangeControlWorkbench, { request, context, draft: approve, action, onDraftChange: writeForbidden, onPrepare: writeForbidden, sharedReview: null });
  assert.match(html, /<button[^>]*disabled=""[^>]*>核对本次实质范围<\/button>/);
  assert.ok(editorIntent(approve, { ...request, impact: { ...impact, unknowns: [] } }, context).intent, "complete fixed impact remains eligible for advisory prepare");
});
