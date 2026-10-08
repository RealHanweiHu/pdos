import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";
import * as icons from "@phosphor-icons/react";

// Synthetic-only isolated compiler and real React SSR; no page wiring or service.
const directory = path.dirname(fileURLToPath(import.meta.url));
const webRoot = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(webRoot, "package.json"));
const ts = dependency("typescript");
const React = dependency("react");
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
const { ResourceReadiness } = load(path.join(directory, "readiness.tsx"));
const { candidateProblem, validityCoverage } = load(path.join(directory, "contracts.ts"));
const window = { start: "2026-10-02T17:00:00Z", finish: "2026-10-02T18:00:00Z", originalTimezone: "America/Los_Angeles" };
const ref = { id: "synthetic-fixture", revision: 2, kind: "fixture" };
const source = { originalId: "synthetic-original", revision: 3, locator: "第2页", status: "current" };
const context = { key: "synthetic-scope-v1", portReady: true, current: true, unavailableReason: null, actor: { label: "合成具名人", kind: "human" } };
const action = { busy: false, reviewPending: false, outcomeUnknown: false, error: null };
const candidate = { id: "synthetic-candidate", digest: "synthetic-digest", contextKey: context.key, title: "合成联合预约", summary: "固定治具与执行范围", resources: [ref], window, available: true, unavailableReason: null, kind: "verification_reservation", policy: { registered: true, hostOperation: "synthetic.host.reservation", tier: "T1" } };
const resource = { ref, label: "合成治具", purpose: "内部验证", units: 1, status: "BLOCKED", checks: [{ code: "fixture.accepted", kind: "acceptance", status: "blocked", detail: "未取得具名验收", source: null, purpose: "内部验证", validity: null }, { code: "equipment.calibration", kind: "calibration", status: "satisfied", detail: "合成校准事实", source, purpose: "内部验证", validity: { validFrom: window.start, validUntil: "2026-10-02T17:30:00Z" } }], conditions: [], calendar: { id: "synthetic-calendar", revision: 7, status: "current" }, capacity: { status: "checked", detail: "按当前日历核对容量", conflicts: [] } };
const view = { id: "synthetic-view", title: "合成资源准备度", asOf: "2026-10-02T16:50:00Z", status: "BLOCKED", window, resources: [resource], reservations: [], physicalReceived: null, actualStarted: null };
const onPrepare = async () => { throw new Error("SSR must never call a port"); };
function render(overrides = {}) { return renderToStaticMarkup(React.createElement(ResourceReadiness, { view, context, candidates: [candidate], action, onPrepare, ...overrides })); }

test("half-open validity covers the full window including exact matching finish", () => {
  assert.equal(validityCoverage({ validFrom: window.start, validUntil: window.finish }, window), "covered");
  assert.equal(validityCoverage({ validFrom: window.start, validUntil: "2026-10-02T17:59:59Z" }, window), "not_covered");
  assert.equal(validityCoverage({ validFrom: "2026-10-02T17:00:01Z", validUntil: window.finish }, window), "not_covered");
});
test("unknown validity and offset-free timestamps cannot become coverage", () => {
  assert.equal(validityCoverage({ validFrom: window.start, validUntil: null }, window), "unknown");
  assert.equal(validityCoverage({ validFrom: "2026-10-02T17:00:00", validUntil: window.finish }, window), "unknown");
  assert.equal(validityCoverage({ validFrom: window.start, validUntil: window.finish }, { ...window, finish: window.start }), "unknown");
});
test("same instants across offsets preserve coverage and IANA timezone remains required", () => {
  assert.equal(validityCoverage({ validFrom: "2026-10-02T10:00:00-07:00", validUntil: "2026-10-02T11:00:00-07:00" }, window), "covered");
  assert.match(candidateProblem({ ...candidate, window: { ...window, originalTimezone: "Invalid/Timezone" } }, context, action, true), /IANA/);
});
test("missing host port, registration and fixed candidate fields disable preparation", () => {
  assert.match(candidateProblem(candidate, { ...context, portReady: false }, action, true), /待主线接入/);
  assert.match(candidateProblem(candidate, context, action, false), /共同办理入口/);
  assert.match(candidateProblem({ ...candidate, policy: { ...candidate.policy, registered: false } }, context, action, true), /政策注册/);
  assert.match(candidateProblem({ ...candidate, digest: "" }, context, action, true), /固定候选不完整/);
  assert.match(candidateProblem({ ...candidate, resources: [{ ...ref, revision: 0 }] }, context, action, true), /固定候选不完整/);
});
test("drift, existing review and unknown results prohibit a new candidate", () => {
  assert.match(candidateProblem(candidate, { ...context, key: "synthetic-v2" }, action, true), /已变化/);
  assert.match(candidateProblem(candidate, { ...context, current: false }, action, true), /已变化/);
  assert.match(candidateProblem(candidate, context, { ...action, reviewPending: true }, true), /已有办理核对/);
  assert.match(candidateProblem(candidate, context, { ...action, outcomeUnknown: true }, true), /原回执/);
});
test("fixture T2 retains canonical action and named human actor; no tier downgrade", () => {
  const fixture = { ...candidate, kind: "fixture_acceptance", policy: { registered: true, hostOperation: "npi.fixture.accept", tier: "T2" } };
  assert.equal(candidateProblem(fixture, context, action, true), null);
  assert.match(candidateProblem(fixture, { ...context, actor: { label: "合成AI", kind: "ai" } }, action, true), /具名人员/);
  assert.match(candidateProblem(fixture, { ...context, actor: null }, action, true), /具名人员/);
  assert.match(candidateProblem({ ...fixture, policy: { ...fixture.policy, tier: "T0" } }, context, action, true), /具名人员/);
  assert.match(candidateProblem({ ...fixture, policy: { ...fixture.policy, hostOperation: "synthetic.other" } }, context, action, true), /npi.fixture.accept/);
});
test("SSR distinguishes qualified readiness, checked capacity and missing actual events", () => {
  const html = render();
  for (const text of ["资源准备度：阻塞", "缺少证据 · UNKNOWN", "有效期未覆盖完整执行区间", "已核对（尚未占用）", "实物正式接收", "Actual 实际开测", "尚无预约记录", "尚未发生或缺少真实事件证据"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes("一次确认此范围"), false);
});
test("SSR keeps tentative, formal, cancellation history and actual source times separate", () => {
  const reservations = [{ id: "synthetic-reservation", revision: 4, status: "cancelled", resources: [{ ref, units: 1 }], purpose: "内部验证", window, events: [{ kind: "tentative", at: "2026-10-02T12:00:00Z", reason: "合成暂定", actorLabel: "合成协调人", source }, { kind: "formal", at: "2026-10-02T13:00:00Z", reason: "合成正式确认", actorLabel: "合成协调人", source }, { kind: "released", at: "2026-10-02T14:00:00Z", reason: "合成释放", actorLabel: "合成协调人", source }, { kind: "cancelled", at: "2026-10-02T15:00:00Z", reason: "合成取消原因", actorLabel: "合成协调人", source }] }];
  const html = render({ view: { ...view, reservations, actualStarted: { occurredAt: "2026-10-02T18:30:00Z", originalTimezone: window.originalTimezone, source } } });
  for (const text of ["暂定时段", "正式预约", "已释放", "已取消", "合成取消原因", "2026-10-02T18:30:00Z", "第2页"]) assert.ok(html.includes(text), text);
});
test("SSR preserves conditions, expiry and conflicts without a numeric readiness score", () => {
  const conditioned = { ...resource, status: "READY_WITH_CONDITIONS", conditions: [{ id: "synthetic-limit", description: "只允许低压工况", allowedPurpose: "内部探索", expiresAt: window.finish, source }], capacity: { status: "conflicted", detail: "合成并发超额", conflicts: [{ reservationId: "synthetic-other-reservation", units: 1, window, detail: "合成冲突时段" }] } };
  const html = render({ view: { ...view, status: "READY_WITH_CONDITIONS", resources: [conditioned] } });
  for (const text of ["在限定条件下就绪", "只允许低压工况", "内部探索", "到期", "合成冲突时段"]) assert.ok(html.includes(text), text);
  assert.equal(html.includes("准备度评分"), false);
});
test("SSR missing ports and unknown receipt keep candidate disabled while host review slot renders", () => {
  const html = render({ context: { ...context, portReady: false }, actionReview: React.createElement("div", { "data-host-review": true }, "合成共同确认槽") });
  assert.match(html, /<button[^>]*disabled=""[^>]*>交主线核对候选<\/button>/);
  assert.ok(html.includes("合成共同确认槽"));
  const unknown = render({ action: { ...action, outcomeUnknown: true } });
  assert.match(unknown, /<button[^>]*disabled=""[^>]*>交主线核对候选<\/button>/);
  assert.ok(unknown.includes("先由主线核对原回执"));
});
