import test from "node:test";
import assert from "node:assert/strict";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";
import { changeCoverageFacets, readChangeCoverage } from "./change-coverage-reading";
import { ChangeCoverageReading } from "../components/builds/change-coverage-reading";

type Row = Record<string, unknown>;
const id = (n: number) => `00000000-0000-0000-0000-${String(n).padStart(12, "0")}`;
const at = "2026-10-05T12:00:00.000000+00:00", until = "2026-10-05T13:00:00.123456+00:00", now = Date.parse("2026-10-05T12:30:00Z");
function fixture(count = 2) {
  const scope = { tenant_id: id(1), product_id: id(2), project_id: id(3) }, audience = [`product:${id(2)}`];
  const source = { id: id(6), revision: 2, kind: "artifact", position: `line:4;quote_sha256:${"a".repeat(64)}` };
  const nodes = Array.from({ length: count }, (_, index) => ({ ref: { id: id(1000 + index), revision: 3, kind: "part", key: null }, scope: { ...scope }, audience: [...audience], source: { id: id(1000 + index), revision: 3, kind: "domain", position: "change-owner:part:" }, label: `固定零件 ${index + 1}` }));
  const graph = { id: id(5), revision: 1, scope, audience, roots: [{ ...nodes[0].ref }], nodes,
    edges: [] as Row[], coverage: nodes.flatMap(node => changeCoverageFacets.map(facet => ({ node: { ...node.ref }, facet: facet.key, status: "complete", source: { ...source }, reason: null } as Row))),
    sources: [{ ...source }], captured_at: at, expires_at: until, nature: "synthetic" };
  return { expectedScope: { ...scope }, expectedProductId: scope.product_id, expectedChangeId: id(4), expectedAudience: [...audience], assessments: [] as Row[],
    capture: { id: graph.id, revision: 1, change_id: id(4), change_revision: 2, current: true, source_status: "current", graph, expires_at: until, required_source_read_set: [{ artifact_id: source.id, expected_revision: 2 }] } };
}
function addAssessment(input: ReturnType<typeof fixture>, unknowns: Row[] = []) {
  const assessment: Row = { id: id(7), request_revision: 3, graph: structuredClone(input.capture.graph), input_digest: "b".repeat(64), known: [], unknown: unknowns, hypotheses: [], computed_at: "2026-10-05T12:10:00Z" };
  input.assessments.push(assessment); return assessment;
}
const record = (value: unknown) => value as Row;

test("source-backed non-applicability retains its reason separately from listed coverage", () => {
  const input = fixture(), entry = input.capture.graph.coverage[0];
  entry.status = "not_applicable"; entry.reason = "本次不涉及该固定对象的工程改版，详见原文";
  const view = readChangeCoverage(input, now);
  assert.equal(view.needsReview, false); assert.equal(view.facets[0].notApplicable, 1);
  assert.equal(view.facets[0].listed, 1); assert.equal(view.applicability[0].reason, entry.reason);
  entry.source = null;
  assert.equal(readChangeCoverage(input, now).facets[0].needsReview, 1);
});

test("exact path applicability is readable only with its node, reason and fixed original", () => {
  const input = fixture(), graph = record(input.capture.graph);
  graph.path_applicability = [{ node: { ...input.capture.graph.nodes[0].ref }, targets: ["pilot_run"], status: "not_applicable", reason: "仅内部改版复验，无试产切换", source: { ...input.capture.graph.sources[0] } }];
  const view = readChangeCoverage(input, now);
  assert.equal(view.needsReview, false); assert.deepEqual(view.applicability[0].targets, ["pilot_run"]);
  const path = (graph.path_applicability as Row[])[0]; path.reason = "";
  assert.equal(readChangeCoverage(input, now).needsReview, true);
  path.reason = "仅内部改版复验，无试产切换"; path.source = null;
  assert.equal(readChangeCoverage(input, now).needsReview, true);
});

test("reads all eight canonical facets and never returns capabilities or changes supplied material", () => {
  const input = fixture(), before = structuredClone(input), view = readChangeCoverage(input, now);
  assert.deepEqual(view.facets.map(row => row.facet), changeCoverageFacets.map(row => row.key));
  assert.equal(view.needsReview, false); assert.equal(view.nodeCount, 2);
  for (const facet of view.facets) assert.deepEqual([facet.listed, facet.unknown, facet.needsReview, facet.impactUnknown], [2, 0, 0, null]);
  assert.equal("capabilities" in view, false); assert.equal(view.impact.status, "not_assessed"); assert.deepEqual(input, before);
});
test("coverage owner source may be absent from graph.sources but must belong to complete capture read set", () => {
  const input = fixture(); input.capture.graph.sources = [];
  const domain = input.capture.graph.nodes[0].source;
  input.capture.graph.sources.push({ ...domain } as unknown as typeof input.capture.graph.sources[number]);
  assert.equal(readChangeCoverage(input, now).needsReview, false);
});
test("250 nodes and 2000 node/facet declarations are counted without clipping", () => {
  const input = fixture(250), view = readChangeCoverage(input, now);
  assert.equal(input.capture.graph.coverage.length, 2000); assert.equal(view.nodeCount, 250);
  assert.ok(view.facets.every(row => row.listed === 250)); assert.equal(view.needsReview, false);
});
test("all explicit unknown declarations remain unknown and do not become missing rows", () => {
  const input = fixture(); for (const entry of input.capture.graph.coverage) { entry.status = "unknown"; entry.source = null; entry.reason = "等待专业所有者核对"; }
  assert.ok(readChangeCoverage(input, now).facets.every(row => row.listed === 0 && row.unknown === 2 && row.needsReview === 0));
});
test("missing node/facet is pending, not unknown or complete", () => {
  const input = fixture(); input.capture.graph.coverage.shift(); const view = readChangeCoverage(input, now);
  assert.equal(view.needsReview, true); assert.deepEqual([view.facets[0].listed, view.facets[0].unknown, view.facets[0].needsReview], [1, 0, 1]);
});
test("duplicate complete declaration is pending and is not counted twice", () => {
  const input = fixture(); input.capture.graph.coverage.push(structuredClone(input.capture.graph.coverage[0])); const view = readChangeCoverage(input, now);
  assert.deepEqual([view.facets[0].listed, view.facets[0].needsReview], [1, 1]); assert.equal(view.needsReview, true);
});
test("complete and unknown duplicates do not select a preferred declaration", () => {
  const input = fixture(); input.capture.graph.coverage.push({ ...structuredClone(input.capture.graph.coverage[0]), status: "unknown", source: null, reason: "未知" }); const view = readChangeCoverage(input, now);
  assert.deepEqual([view.facets[0].listed, view.facets[0].unknown, view.facets[0].needsReview], [1, 0, 1]);
});
for (const [name, value] of [["missing", undefined], ["domain", { id: id(6), revision: 2, kind: "domain", position: "owner" }], ["partial quote", { id: id(6), revision: 2, kind: "artifact", position: "line:4" }], ["wrong version", { id: id(6), revision: 3, kind: "artifact", position: `line:4;quote_sha256:${"a".repeat(64)}` }], ["wrong id", { id: id(8), revision: 2, kind: "artifact", position: `line:4;quote_sha256:${"a".repeat(64)}` }], ["unsafe line", { id: id(6), revision: 2, kind: "artifact", position: `line:9007199254740992;quote_sha256:${"a".repeat(64)}` }]] as const) {
  test(`complete coverage ${name} artifact Source stays pending`, () => {
    const input = fixture(); input.capture.graph.coverage[0].source = value; const view = readChangeCoverage(input, now);
    assert.equal(view.needsReview, true); assert.equal(view.facets[0].listed, 1); assert.equal(view.facets[0].needsReview, 1);
  });
}
for (const [name, change] of [
  ["unknown reason missing", (entry: Row) => { entry.status = "unknown"; entry.source = null; entry.reason = null; }],
  ["unknown reason empty", (entry: Row) => { entry.status = "unknown"; entry.source = null; entry.reason = " "; }],
  ["unexpected coverage field", (entry: Row) => { entry.authorized = true; }],
  ["unrecognized status", (entry: Row) => { entry.status = "qualified"; }],
] as const) test(name, () => { const input = fixture(); change(input.capture.graph.coverage[0]); const view = readChangeCoverage(input, now); assert.equal(view.needsReview, true); assert.equal(view.facets[0].needsReview, 1); });

for (const field of ["tenant_id", "product_id", "project_id"] as const) test(`different expected ${field} makes the whole graph pending`, () => {
  const input = fixture(); input.expectedScope[field] = id(90); const view = readChangeCoverage(input, now);
  assert.equal(view.needsReview, true); assert.ok(view.facets.every(row => row.listed === null));
});
test("expected product cannot disagree with fixed scope", () => { const input = fixture(); input.expectedProductId = id(90); assert.equal(readChangeCoverage(input, now).needsReview, true); });
test("wrong change owner and graph identity never supply trusted counts", () => {
  for (const mutate of [(input: ReturnType<typeof fixture>) => { input.capture.change_id = id(90); }, (input: ReturnType<typeof fixture>) => { input.capture.id = id(90); }]) { const input = fixture(); mutate(input); assert.equal(readChangeCoverage(input, now).nodeCount, null); }
});
test("scope of a fixed node cannot widen the saved graph scope", () => { const input = fixture(); input.capture.graph.nodes[0].scope.project_id = id(90); const view = readChangeCoverage(input, now); assert.equal(view.needsReview, true); assert.equal(view.nodeCount, null); });
test("graph and node audiences must match exact expected audience", () => {
  const input = fixture(); input.expectedAudience = ["private:another"]; assert.equal(readChangeCoverage(input, now).nodeCount, null);
  const other = fixture(); other.capture.graph.nodes[0].audience = ["private:another"]; assert.equal(readChangeCoverage(other, now).nodeCount, null);
});
test("duplicate nodes and unsupported ref kinds make counts pending", () => {
  const input = fixture(); input.capture.graph.nodes.push(structuredClone(input.capture.graph.nodes[0])); assert.equal(readChangeCoverage(input, now).nodeCount, null);
  const other = fixture(); other.capture.graph.nodes[0].ref.kind = "model-invented"; assert.equal(readChangeCoverage(other, now).nodeCount, null);
});
test("unknown facet or node reference is never silently accepted", () => {
  const input = fixture(); input.capture.graph.coverage[0].facet = "approved"; assert.equal(readChangeCoverage(input, now).needsReview, true);
  const other = fixture(); record(other.capture.graph.coverage[0].node).id = id(90); assert.equal(readChangeCoverage(other, now).needsReview, true);
});
test("legacy graph without complete coverage array stays pending", () => { const input = fixture(); delete record(input.capture.graph).coverage; assert.equal(readChangeCoverage(input, now).nodeCount, null); });
test("graphs over the previous node bound retain every node and facet", () => {
  const input = fixture(5001), size = input.capture.graph.nodes.length, view = readChangeCoverage(input, now);
  assert.equal(view.nodeCount, size); assert.equal(view.needsReview, false); assert.equal(input.capture.graph.nodes.length, size); assert.equal(input.capture.graph.coverage.length, 40008);
});
test("invalid graph source and unavailable exact source read set stay pending", () => {
  const input = fixture(); input.capture.graph.sources[0].position = "model quote"; assert.equal(readChangeCoverage(input, now).needsReview, true);
  const other = fixture(); delete record(other.capture).required_source_read_set; const view = readChangeCoverage(other, now); assert.equal(view.needsReview, true); assert.equal(view.facets[0].listed, 0);
});
test("conflicting or duplicate Source read versions cannot be summarized as complete", () => {
  const input = fixture(); input.capture.required_source_read_set.push({ ...input.capture.required_source_read_set[0], expected_revision: 3 }); assert.equal(readChangeCoverage(input, now).needsReview, true);
});
test("more than 20 sources retains the complete read set", () => {
  const input = fixture(); for (let i = 0; i < 20; i++) input.capture.required_source_read_set.push({ artifact_id: id(100 + i), expected_revision: 1 });
  const before = structuredClone(input), view = readChangeCoverage(input, now); assert.equal(view.needsReview, false); assert.equal(view.facets[0].listed, 2); assert.deepEqual(input, before);
});
test("ordinary captures rely on Current without a manufactured deadline", () => {
  const input = fixture(); record(input.capture).expires_at = null; record(input.capture.graph).expires_at = null;
  const view = readChangeCoverage(input, now);
  assert.equal(view.needsReview, false); assert.equal(view.snapshot.expired, false); assert.equal(view.snapshot.current, true);
  input.capture.current = false; input.capture.source_status = "needs_recheck";
  assert.equal(readChangeCoverage(input, now).snapshot.current, false);
  record(input.capture).expires_at = until;
  assert.equal(readChangeCoverage(input, now).nodeCount, null);
});
test("malformed and duplicate edges stay pending", () => {
  const input = fixture(), edge = { id: "edge-1", origin: input.capture.graph.nodes[0].ref, target: input.capture.graph.nodes[1].ref, source: input.capture.graph.nodes[0].source, relation: "关联" };
  input.capture.graph.edges.push(edge); assert.equal(readChangeCoverage(input, now).needsReview, false);
  input.capture.graph.edges.push(structuredClone(edge)); assert.equal(readChangeCoverage(input, now).needsReview, true);
  const other = fixture(); other.capture.graph.edges.push({ ...edge, target: { ...edge.target, id: id(90) } }); assert.equal(readChangeCoverage(other, now).needsReview, true);
});
test("roots missing from node set or repeated stay pending", () => {
  const input = fixture(); input.capture.graph.roots[0].id = id(90); assert.equal(readChangeCoverage(input, now).needsReview, true);
  const other = fixture(); other.capture.graph.roots.push({ ...other.capture.graph.roots[0] }); assert.equal(readChangeCoverage(other, now).needsReview, true);
});
test("deadlines retain original text and submillisecond differences are not discarded", () => {
  const input = fixture(); assert.equal(readChangeCoverage(input, now).snapshot.expiresAt, until);
  input.capture.expires_at = until.replace("123456", "123999"); assert.equal(readChangeCoverage(input, now).nodeCount, null);
});
test("offset spelling can identify the same exact deadline", () => { const input = fixture(); input.capture.expires_at = "2026-10-05T06:00:00.123456-07:00"; assert.equal(readChangeCoverage(input, now).needsReview, false); });
test("invalid calendar dates, missing zone and inverted expiry are pending", () => {
  for (const value of ["2026-02-30T13:00:00Z", "2026-10-05T13:00:00", "2026-10-05T11:59:00Z"]) { const input = fixture(); input.capture.graph.expires_at = value; input.capture.expires_at = value; assert.equal(readChangeCoverage(input, now).nodeCount, null); }
});
test("expiry and historical capture preserve saved counts without making it current", () => {
  const input = fixture(), view = readChangeCoverage(input, Date.parse(until) + 1); assert.equal(view.snapshot.expired, true); assert.equal(view.facets[0].listed, 2);
  input.capture.current = false; input.capture.source_status = "needs_recheck"; const history = readChangeCoverage(input, now); assert.equal(history.snapshot.current, false); assert.equal(history.facets[0].listed, 2);
});
test("server hash is preserved exactly or explicitly unavailable, never manufactured", () => {
  const input = fixture(); assert.equal(readChangeCoverage(input, now).snapshot.hash, null);
  record(input.capture).graph_sha256 = "c".repeat(64); assert.equal(readChangeCoverage(input, now).snapshot.hash, "c".repeat(64));
  record(input.capture).graph_sha256 = "not-a-hash"; assert.equal(readChangeCoverage(input, now).needsReview, true);
});
test("full listed coverage retains corresponding server missing-edge UNKNOWN separately", () => {
  const input = fixture(); addAssessment(input, [{ node: { ...input.capture.graph.nodes[0].ref }, facet: "engineering", reason: "固定规格缺少通往配置的显式依赖边" }, { node: null, facet: "training", reason: "培训边待核对" }]);
  const view = readChangeCoverage(input, now); assert.equal(view.needsReview, false); assert.equal(view.facets[0].listed, 2); assert.equal(view.facets[0].impactUnknown, 1); assert.equal(view.impact.unknowns.length, 2); assert.match(view.impact.unknowns[0].reason, /缺少/);
});
test("valid known nodes and actual edge paths preserve separate impact UNKNOWN counts", () => {
  const input = fixture(), graph = input.capture.graph;
  graph.edges.push({ id: "edge-1", origin: graph.nodes[0].ref, target: graph.nodes[1].ref, source: graph.nodes[0].source, relation: "明确依赖" });
  const assessment = addAssessment(input); assessment.known = [{ node: structuredClone(graph.nodes[0]), path: [], lanes: ["engineering"] }, { node: structuredClone(graph.nodes[1]), path: ["edge-1"], lanes: ["manufacturing"] }];
  assert.equal(readChangeCoverage(input, now).impact.status, "readable");
  record((assessment.known as Row[])[1]).path = ["edge-does-not-exist"]; assert.equal(readChangeCoverage(input, now).impact.status, "needs_review");
});
test("malformed legacy assessment cannot be treated as no assessment or zero UNKNOWN", () => {
  const input = fixture(); input.assessments.push({ unknown: [] }); const view = readChangeCoverage(input, now);
  assert.equal(view.needsReview, true); assert.equal(view.impact.status, "needs_review"); assert.equal(view.facets[0].impactUnknown, null);
});
test("an assessment for another saved graph cannot clear selected graph UNKNOWN", () => {
  const input = fixture(), assessment = addAssessment(input); record(assessment.graph).id = id(90); const view = readChangeCoverage(input, now); assert.equal(view.impact.status, "not_assessed"); assert.equal(view.facets[0].impactUnknown, null);
});
test("same graph identity with substituted full material is pending", () => {
  const input = fixture(), assessment = addAssessment(input); record(record(assessment.graph).scope).project_id = id(90); const view = readChangeCoverage(input, now); assert.equal(view.impact.status, "needs_review"); assert.equal(view.facets[0].impactUnknown, null);
});
test("the latest matching saved assessment supplies UNKNOWN without mixing other graphs", () => {
  const input = fixture(); addAssessment(input, [{ node: null, facet: "training", reason: "旧核对仍保留" }]); addAssessment(input, [{ node: null, facet: "manufacturing", reason: "当前对应核对缺边" }]); const other = addAssessment(input); record(other.graph).id = id(90);
  const view = readChangeCoverage(input, now); assert.equal(view.impact.unknowns.length, 1); assert.equal(view.facets[1].impactUnknown, 1); assert.equal(view.facets[7].impactUnknown, 0);
});
for (const [name, change] of [
  ["unknown missing", (assessment: Row) => { delete assessment.unknown; }],
  ["wrong unknown node", (assessment: Row) => { assessment.unknown = [{ node: { id: id(90), revision: 1, kind: "part", key: null }, facet: "engineering", reason: "待核对" }]; }],
  ["unknown facet", (assessment: Row) => { assessment.unknown = [{ node: null, facet: "invented", reason: "待核对" }]; }],
  ["unknown missing reason", (assessment: Row) => { assessment.unknown = [{ node: null, facet: "engineering", reason: "" }]; }],
  ["legacy assessment header missing", (assessment: Row) => { delete assessment.computed_at; }],
  ["known fabricated node", (assessment: Row) => { assessment.known = [{ node: { ref: { id: id(90), revision: 1, kind: "part", key: null } }, path: [], lanes: [] }]; }],
] as const) test(`matching assessment ${name} is not a zero-unknown result`, () => { const input = fixture(); change(addAssessment(input)); const view = readChangeCoverage(input, now); assert.equal(view.impact.status, "needs_review"); assert.equal(view.facets[0].impactUnknown, null); });

test("no capabilities or claimed authorization changes the read-only summary", () => {
  const input = fixture(), original = readChangeCoverage(input, now); record(input.capture).capabilities = { "change.impact.compute": true }; record(input.capture).authority = { qualified: true, authorized: true }; assert.deepEqual(readChangeCoverage(input, now), original);
});
test("malformed capture values always render pending without a crash", () => {
  for (const capture of [null, [], "legacy", {}, { graph: null }]) { const input = { ...fixture(), capture }; const view = readChangeCoverage(input, now); assert.equal(view.needsReview, true); assert.ok(view.facets.every(row => row.listed === null)); }
});
test("component exposes eight readable facets and complete unknowns without write controls", () => {
  const input = fixture(250); addAssessment(input, [{ node: null, facet: "engineering", reason: "缺边仍按影响 UNKNOWN 保留" }]);
  const html = renderToStaticMarkup(createElement(ChangeCoverageReading, input));
  assert.equal((html.match(/scope="row"/g) ?? []).length, 8); assert.ok(html.includes("250 个固定对象")); assert.ok(html.includes("缺边仍按影响 UNKNOWN 保留")); assert.ok(html.includes("服务器摘要未在读取中提供")); assert.ok(html.includes("固定图身份与期限"));
  assert.doesNotMatch(html, /<(?:button|input|select|form)\b/); assert.doesNotMatch(html, /已批准|已放行|资格已核对/);
});
test("component shows malformed and legacy material as pending, not zero coverage", () => {
  const input = fixture(); delete record(input.capture.graph).coverage; const html = renderToStaticMarkup(createElement(ChangeCoverageReading, input)); assert.ok(html.includes("待核对")); assert.ok(html.includes("UNKNOWN")); assert.doesNotMatch(html, /0 个固定对象/);
});
test("component preserves the actual fixed hash and escaped unknown text", () => {
  const input = fixture(); record(input.capture).graph_sha256 = "d".repeat(64); addAssessment(input, [{ node: null, facet: "training", reason: "<script>not executable</script>" }]); const html = renderToStaticMarkup(createElement(ChangeCoverageReading, input)); assert.ok(html.includes("d".repeat(64))); assert.ok(html.includes("&lt;script&gt;")); assert.doesNotMatch(html, /<script>/);
});
