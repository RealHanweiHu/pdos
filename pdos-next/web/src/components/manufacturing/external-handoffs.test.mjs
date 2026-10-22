import assert from "node:assert/strict";
import { existsSync, readFileSync } from "node:fs";
import Module, { createRequire } from "node:module";
import path from "node:path";
import test from "node:test";
import { fileURLToPath } from "node:url";

// Real React reading component with explicit data fixtures. These checks do not
// attest issuer, backend ownership, PostgreSQL or an actual external delivery.
const directory = path.dirname(fileURLToPath(import.meta.url)), web = path.resolve(directory, "../../..");
const dependency = createRequire(path.join(web, "package.json")), ts = dependency("typescript"), React = dependency("react");
const { renderToStaticMarkup } = dependency("react-dom/server"), modules = new Map();
function load(filename) {
  if (!path.extname(filename)) filename = [".ts", ".tsx"].map(ext => filename + ext).find(existsSync);
  if (filename.endsWith(".css")) return { __esModule: true, default: new Proxy({}, { get: (_object, key) => String(key) }) };
  if (modules.has(filename)) return modules.get(filename).exports;
  const loaded = new Module(filename); modules.set(filename, loaded);
  loaded.require = name => name === "@phosphor-icons/react" ? new Proxy({}, { get: () => () => React.createElement("svg") }) : name.startsWith("@/") ? load(path.join(web, "src", name.slice(2))) : name.startsWith(".") ? load(path.resolve(path.dirname(filename), name)) : dependency(name);
  loaded._compile(ts.transpileModule(readFileSync(filename, "utf8"), { compilerOptions: { target: ts.ScriptTarget.ES2022, module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true } }).outputText, filename);
  return loaded.exports;
}
const { ExternalHandoffReading } = load(path.join(directory, "external-handoffs.tsx"));
const id = n => `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`, ref = n => ({ id: id(n), revision: 1 });
const range = { quantity: "10", unit: "ea", site: "固定场地", lots: null, lines: [], regions: null };
const source = { kind: "artifact", id: id(5), revision: 1, position: `line:1;quote_sha256:${"a".repeat(64)}` };
function detail() {
  const declaration = { project_id: id(3), package: ref(10), engineering_decision: ref(11), manufacturing_decision: ref(12), subject_config: { definition: ref(6), engineering_configuration: ref(7), manufacturing_configuration: ref(8) }, release_scope: range, purpose: "已固定的移交用途", destination: { system: "ERP登记", recipient_id: "实际收件方" }, external_id: "external-1", manifest: [{ artifact: ref(9), logical_name: "装配图原件", content_sha256: "b".repeat(64), external_number: "DWG-01", external_version: "A", sources: [source] }], mappings: [{ ref: { kind: "engineering_configuration", ...ref(7) }, external_number: "CFG-01", external_version: "A", sources: [source] }] };
  return { id: id(20), revision: 1, project_id: id(3), purpose: declaration.purpose, package: ref(10), receipt_id: id(30), as_of: { id: id(31), handoff: ref(20), intent: ref(21), receipt_count: 0, latest_receipt: null, epoch: 1, projection_sha256: "c".repeat(64) }, reading: { status: "authorized", ...Object.fromEntries(["sent", "accepted", "effective"].map(stage => [stage, { stage, state: "not_recorded", active: [], covered_scopes: [], mismatches: [] }])), delivery_unknown: false, rejected: false, failed: false, conflict: false, network_send: false }, network_send: false, authorization: { declaration, limits: [] }, authority: {}, intent: { ...ref(21), packet: { handoff: ref(20), ...declaration, network_send: false } }, applicability: "current" };
}
function history(sequence, stage = "sent", outcome = "unknown", reconciles = null) { return { ...ref(40 + sequence), sequence, original: { handoff: ref(20), intent: ref(21), destination: { system: "ERP登记", recipient_id: "实际收件方" }, external_id: "external-1", manifest_sha256: "b".repeat(64), release_scope: range, stage, outcome, external_receipt_id: `remote-${sequence}`, occurred_at: "2026-10-17T12:00:00Z", reconciles }, source, issuer: { key: "actual-host-issuer" }, mismatches: [], receipt_id: id(50 + sequence), received_at: "2026-10-17T12:00:01Z" }; }
function render(value, records = []) { return renderToStaticMarkup(React.createElement(ExternalHandoffReading, { detail: value, history: records })); }

test("an authorized intent shows all three external stages unrecorded", () => {
  const html = render(detail()); assert.match(html, /发送：尚无记录/); assert.match(html, /接收：尚无记录/); assert.match(html, /实际生效：尚无记录/); assert.match(html, /授权和意图不会自动表示已发送/); assert.match(html, /装配图原件/); assert.match(html, /DWG-01／A/); assert.match(html, /CFG-01／A/); assert.match(html, /实际收件方/); assert.match(html, /明确为空，不代表全部/); assert.doesNotMatch(html, /<h3>已记录发送成功/);
});
test("unknown send, partial acceptance, and failed effectiveness remain separate", () => {
  const value = detail(); value.as_of.receipt_count = 3; value.as_of.epoch = 4; value.reading.sent.state = "unknown"; value.reading.accepted.state = "partial"; value.reading.accepted.covered_scopes = [{ ...range, quantity: "5" }]; value.reading.effective.state = "failed"; value.reading.delivery_unknown = true; value.reading.failed = true;
  const html = render(value, [history(3, "effective", "failed"), history(2, "accepted", "succeeded"), history(1)]); assert.match(html, /发送：结果未知/); assert.match(html, /接收：部分范围/); assert.match(html, /实际生效：已失败/); assert.match(html, /须对账同一原意图，不新增盲目重发/); assert.match(html, /序号 1 · 发送 · 结果未知/); assert.ok(html.indexOf("序号 3") < html.indexOf("序号 2"));
});
test("explicit reconciliation keeps the original unknown fact and mismatched responses", () => {
  const value = detail(); value.applicability = "needs_recheck"; value.as_of.receipt_count = 3; value.as_of.epoch = 4; value.reading.sent.state = "succeeded"; value.reading.accepted.state = "conflict"; value.reading.accepted.mismatches = ["MANIFEST_MISMATCH"]; value.reading.conflict = true;
  const rows = [history(3, "accepted", "succeeded"), history(2, "sent", "succeeded", ref(41)), history(1)]; rows[0].mismatches = ["MANIFEST_MISMATCH"];
  const html = render(value, rows); assert.match(html, /接收：事实冲突/); assert.match(html, /回执文件摘要与授权不一致/); assert.match(html, /显式对账原事实/); assert.match(html, /序号 1 · 发送 · 结果未知/); assert.match(html, /历史授权和回执保留/); assert.match(html, /页面保存成功不会替代这三项事实/);
});
