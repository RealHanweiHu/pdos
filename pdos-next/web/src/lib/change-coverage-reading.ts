/** Read-only shape reading. Counts never supply capabilities or authorize an action. */
export const changeCoverageFacets = [
  { key: "engineering", label: "工程配置及定义" },
  { key: "manufacturing", label: "制造工序与工装" },
  { key: "evidence_applicability", label: "证据适用性" },
  { key: "in_process_builds", label: "在制轮次" },
  { key: "customer_samples", label: "客户样件" },
  { key: "supply_inventory_wip", label: "供应、库存和在制品" },
  { key: "production_switch", label: "制造切换" },
  { key: "training", label: "人员培训" },
] as const;
export type ChangeCoverageFacet = typeof changeCoverageFacets[number]["key"];
type JsonRow = Record<string, unknown>;
type FixedRef = { id: string; revision: number; kind: string; key: string | null };
export type CoverageReadingInput = {
  capture: unknown; expectedScope: unknown; expectedProductId: string;
  expectedChangeId: string; expectedAudience: unknown; assessments: unknown;
};
export type CoverageFacetReading = {
  facet: ChangeCoverageFacet; label: string; listed: number | null;
  unknown: number | null; needsReview: number | null; impactUnknown: number | null;
  notApplicable: number | null;
};
export type ChangeCoverageReadingView = {
  needsReview: boolean; issues: string[]; nodeCount: number | null; edgeCount: number | null;
  snapshot: { id: string | null; revision: number | null; capturedAt: string | null;
    expiresAt: string | null; hash: string | null; synthetic: boolean; current: boolean; expired: boolean };
  facets: CoverageFacetReading[];
  applicability: { objectLabel: string; targets: string[]; status: string; reason: string; source: string }[];
  impact: { status: "not_assessed" | "readable" | "needs_review";
    unknowns: { facet: ChangeCoverageFacet; label: string; objectLabel: string | null; reason: string }[] };
};
const kinds = new Set(["spec", "part", "bom", "interface", "engineering_configuration", "build", "sample", "test_run", "operation", "tooling", "fixture", "sop", "work_instruction", "control_plan", "manufacturing_baseline", "pilot_run", "manufacturing_release", "customer_sample", "supply_commitment", "inventory", "wip", "training", "evidence", "issue", "capa", "manufacturing_configuration", "graph_snapshot"]);
const facetKeys = new Set<string>(changeCoverageFacets.map(row => row.key));
const row = (value: unknown): value is JsonRow => !!value && typeof value === "object" && !Array.isArray(value);
const uuid = (value: unknown): value is string => typeof value === "string" && /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const revision = (value: unknown): value is number => Number.isSafeInteger(value) && Number(value) > 0;
const text = (value: unknown, max = 2000): value is string => typeof value === "string" && value.length > 0 && value.trim() === value && value.length <= max;
const fields = (value: JsonRow, allowed: readonly string[]) => Object.keys(value).every(key => allowed.includes(key));
const fixedRef = (value: unknown): value is FixedRef => row(value) && fields(value, ["id", "revision", "kind", "key"]) && uuid(value.id) && revision(value.revision) && typeof value.kind === "string" && kinds.has(value.kind) && (value.key === null || text(value.key, 120));
const refKey = (ref: FixedRef) => JSON.stringify([ref.kind, ref.id.toLowerCase(), ref.revision, ref.key]);
const scope = (value: unknown): value is JsonRow => row(value) && fields(value, ["tenant_id", "product_id", "project_id"]) && ["tenant_id", "product_id", "project_id"].every(key => uuid(value[key]));
const sameScope = (a: JsonRow, b: JsonRow) => ["tenant_id", "product_id", "project_id"].every(key => a[key] === b[key]);
const audience = (value: unknown): value is string[] => Array.isArray(value) && value.length > 0 && value.every(value => text(value, 120)) && new Set(value).size === value.length;
const sameAudience = (a: string[], b: string[]) => a.length === b.length && a.every(value => b.includes(value));
function time(value: unknown): value is string {
  if (typeof value !== "string") return false;
  const match = /^(\d{4})-(\d\d)-(\d\d)T(\d\d):(\d\d):(\d\d)(?:\.(\d+))?(Z|([+-])(\d\d):(\d\d))$/.exec(value);
  if (!match) return false;
  const [, year, month, day, hour, minute, second, , zone, , offsetHour, offsetMinute] = match;
  const date = new Date(Date.UTC(Number(year), Number(month) - 1, Number(day)));
  return Number(year) >= 100 && date.getUTCFullYear() === Number(year) && date.getUTCMonth() === Number(month) - 1 && date.getUTCDate() === Number(day)
    && Number(hour) < 24 && Number(minute) < 60 && Number(second) < 60 && (zone === "Z" || Number(offsetHour) < 24 && Number(offsetMinute) < 60) && Number.isFinite(Date.parse(value));
}
// Keep all supplied fractional precision when matching the two saved deadlines.
function instantKey(value: string): string {
  const fraction = /\.(\d+)(?=Z|[+-]\d\d:\d\d$)/.exec(value);
  const seconds = fraction ? value.slice(0, fraction.index) + value.slice(fraction.index + fraction[0].length) : value;
  return `${Date.parse(seconds)}:${(fraction?.[1] ?? "").replace(/0+$/, "")}`;
}
const artifactPosition = (value: unknown): value is string => typeof value === "string" && /^line:[1-9]\d*;quote_sha256:[0-9a-f]{64}$/.test(value) && Number.isSafeInteger(Number(value.split(";")[0].slice(5)));
const source = (value: unknown): value is JsonRow => row(value) && fields(value, ["id", "revision", "kind", "position"]) && uuid(value.id) && revision(value.revision) && ["artifact", "domain", "command"].includes(String(value.kind)) && text(value.position) && (value.kind !== "artifact" || artifactPosition(value.position));
function stable(value: unknown): unknown {
  return Array.isArray(value) ? value.map(stable) : row(value) ? Object.fromEntries(Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, value]) => [key, stable(value)])) : value;
}
function sameGraph(a: unknown, b: unknown): boolean {
  try { return JSON.stringify(stable(a)) === JSON.stringify(stable(b)); } catch { return false; }
}

/** Reads the complete supplied graph; never clips nodes, coverage, sources or unknowns. */
export function readChangeCoverage(input: CoverageReadingInput, now = Date.now()): ChangeCoverageReadingView {
  const issues = new Set<string>(), capture = row(input.capture) ? input.capture : {}, graph = row(capture.graph) ? capture.graph : {};
  const result: ChangeCoverageReadingView = {
    needsReview: false, issues: [], nodeCount: null, edgeCount: null,
    snapshot: { id: uuid(graph.id) ? graph.id : null, revision: revision(graph.revision) ? graph.revision : null,
      capturedAt: time(graph.captured_at) ? graph.captured_at : null, expiresAt: time(graph.expires_at) ? graph.expires_at : null,
      hash: typeof capture.graph_sha256 === "string" && /^[0-9a-f]{64}$/.test(capture.graph_sha256) ? capture.graph_sha256 : null,
      synthetic: graph.nature === "synthetic", current: capture.current === true && capture.source_status === "current",
      expired: !Number.isFinite(now) || !(graph.expires_at === null || time(graph.expires_at) && Date.parse(graph.expires_at) > now) },
    facets: changeCoverageFacets.map(({ key, label }) => ({ facet: key, label, listed: null, unknown: null, needsReview: null, impactUnknown: null, notApplicable: null })),
    applicability: [],
    impact: { status: "not_assessed", unknowns: [] },
  };
  const finish = () => { result.issues = [...issues]; result.needsReview = issues.size > 0; return result; };
  const headerValid = fields(graph, ["id", "revision", "scope", "audience", "roots", "nodes", "edges", "coverage", "sources", "captured_at", "expires_at", "nature", "path_applicability"]) && uuid(graph.id) && revision(graph.revision)
    && capture.id === graph.id && capture.revision === graph.revision && capture.change_id === input.expectedChangeId && uuid(input.expectedChangeId) && revision(capture.change_revision)
    && scope(input.expectedScope) && scope(graph.scope) && sameScope(graph.scope, input.expectedScope) && input.expectedScope.product_id === input.expectedProductId
    && audience(graph.audience) && audience(input.expectedAudience) && sameAudience(graph.audience, input.expectedAudience)
    && time(graph.captured_at) && (graph.expires_at === null && capture.expires_at === null || time(graph.expires_at) && time(capture.expires_at) && instantKey(graph.expires_at) === instantKey(capture.expires_at) && Date.parse(graph.expires_at) > Date.parse(graph.captured_at))
    && ["real", "synthetic"].includes(String(graph.nature)) && typeof capture.current === "boolean" && capture.source_status === (capture.current ? "current" : "needs_recheck")
    && Array.isArray(graph.nodes) && graph.nodes.length > 0 && Array.isArray(graph.edges)
    && Array.isArray(graph.coverage) && Array.isArray(graph.roots) && graph.roots.length > 0 && Array.isArray(graph.sources) && graph.sources.length > 0;
  if (!headerValid) { issues.add("固定图身份、范围、受众、期限或完整结构待核对。"); result.impact.status = "needs_review"; return finish(); }
  if (capture.graph_sha256 !== undefined && !result.snapshot.hash) issues.add("服务器提供的固定图摘要格式待核对。");
  const nodes = graph.nodes as unknown[], edges = graph.edges as unknown[], coverage = graph.coverage as unknown[], roots = graph.roots as unknown[], sources = graph.sources as unknown[];
  const nodeLabels = new Map<string, string>(), nodeRecords = new Map<string, JsonRow>();
  for (const node of nodes) {
    if (!row(node) || !fields(node, ["ref", "scope", "audience", "source", "label"]) || !fixedRef(node.ref) || !scope(node.scope) || !sameScope(node.scope, graph.scope as JsonRow) || !audience(node.audience) || !sameAudience(node.audience, graph.audience as string[]) || !source(node.source) || !text(node.label) || nodeLabels.has(refKey(node.ref))) {
      issues.add("固定节点缺项、重复或范围不合，数量待核对。"); result.impact.status = "needs_review"; return finish();
    }
    nodeLabels.set(refKey(node.ref), node.label);
    nodeRecords.set(refKey(node.ref), node);
  }
  result.nodeCount = nodes.length; result.edgeCount = edges.length;
  const rootKeys = new Set<string>();
  for (const root of roots) {
    if (!fixedRef(root) || !nodeLabels.has(refKey(root)) || rootKeys.has(refKey(root))) { issues.add("固定根对象缺项或重复。"); break; }
    rootKeys.add(refKey(root));
  }
  const edgeIds = new Set<string>();
  for (const edge of edges) {
    if (!row(edge) || !fields(edge, ["id", "origin", "target", "source", "relation"]) || !text(edge.id, 120) || edgeIds.has(edge.id) || !fixedRef(edge.origin) || !fixedRef(edge.target) || !nodeLabels.has(refKey(edge.origin)) || !nodeLabels.has(refKey(edge.target)) || !source(edge.source) || !text(edge.relation)) { issues.add("固定依赖边缺项、重复或引用不合。"); continue; }
    edgeIds.add(edge.id);
  }
  const reads = new Map<string, number>();
  if (!Array.isArray(capture.required_source_read_set)) issues.add("完整来源读集缺失。");
  else for (const read of capture.required_source_read_set) {
    if (!row(read) || !fields(read, ["artifact_id", "expected_revision"]) || !uuid(read.artifact_id) || !revision(read.expected_revision) || reads.has(read.artifact_id)) { issues.add("完整来源读集身份、版本或唯一性待核对。"); continue; }
    reads.set(read.artifact_id, read.expected_revision);
  }
  const supportedSource = (value: unknown) => source(value) && (value.kind !== "artifact" || reads.get(String(value.id)) === value.revision);
  if (!sources.every(supportedSource)) issues.add("图的固定来源或精确版本待核对。");
  if (nodes.some(node => row(node) && !supportedSource(node.source)) || edges.some(edge => row(edge) && !supportedSource(edge.source))) issues.add("固定节点或依赖边的来源版本待核对。");
  // Complete coverage sources are supplied by the owner and may be outside graph.sources.
  const pairs = new Map<string, unknown[]>();
  for (const entry of coverage) {
    if (!row(entry) || !fixedRef(entry.node) || !nodeLabels.has(refKey(entry.node)) || typeof entry.facet !== "string" || !facetKeys.has(entry.facet)) { issues.add("覆盖引用或影响范围待核对。"); continue; }
    const key = JSON.stringify([refKey(entry.node), entry.facet]);
    const entries = pairs.get(key) ?? [];
    entries.push(entry); pairs.set(key, entries);
  }
  for (const facet of result.facets) {
    facet.listed = 0; facet.unknown = 0; facet.needsReview = 0; facet.notApplicable = 0;
    for (const node of nodeLabels.keys()) {
      const entries = pairs.get(JSON.stringify([node, facet.facet])) ?? [], entry = entries[0];
      if (entries.length !== 1 || !row(entry) || !fields(entry, ["node", "facet", "status", "source", "reason"])) { facet.needsReview++; continue; }
      if (entry.status === "complete" && supportedSource(entry.source) && (entry.source as JsonRow).kind === "artifact" && (entry.reason === null || entry.reason === undefined || text(entry.reason))) facet.listed++;
      else if (entry.status === "not_applicable" && supportedSource(entry.source) && (entry.source as JsonRow).kind === "artifact" && text(entry.reason)) {
        facet.notApplicable++;
        const original = entry.source as JsonRow;
        result.applicability.push({ objectLabel: nodeLabels.get(node)!, targets: [facet.label], status: "not_applicable", reason: entry.reason, source: `${original.id} · v${original.revision} · ${original.position}` });
      }
      else if (entry.status === "unknown" && text(entry.reason) && (entry.source === null || entry.source === undefined || supportedSource(entry.source))) facet.unknown++;
      else facet.needsReview++;
    }
    if (facet.needsReview > 0) issues.add("存在缺失、重复或来源不完整的节点范围，须逐项核对。");
  }
  const paths = graph.path_applicability ?? [], pathKeys = new Set<string>();
  if (!Array.isArray(paths)) issues.add("后续路径适用性结构待核对。");
  else for (const path of paths) {
    if (!row(path) || !fields(path, ["node", "targets", "status", "reason", "source"]) || !fixedRef(path.node) || !nodeLabels.has(refKey(path.node))
      || !Array.isArray(path.targets) || !path.targets.length || path.targets.some(kind => typeof kind !== "string" || !kinds.has(kind)) || new Set(path.targets).size !== path.targets.length
      || !["applicable", "not_applicable", "unknown"].includes(String(path.status)) || !text(path.reason)
      || (path.status === "unknown" ? path.source !== null && path.source !== undefined && !supportedSource(path.source) : !supportedSource(path.source) || (path.source as JsonRow).kind !== "artifact")) {
      issues.add("后续路径适用性的对象、理由或原文来源待核对。"); continue;
    }
    const key = JSON.stringify([refKey(path.node), [...path.targets].sort()]);
    if (pathKeys.has(key)) { issues.add("后续路径适用性声明重复，须核对原文。"); continue; }
    pathKeys.add(key);
    result.applicability.push({ objectLabel: nodeLabels.get(refKey(path.node))!, targets: path.targets as string[], status: String(path.status), reason: path.reason,
      source: row(path.source) ? `${path.source.id} · v${path.source.revision} · ${path.source.position}` : "尚无固定原文" });
  }
  if (!Array.isArray(input.assessments)) { issues.add("固定影响核对记录结构待核对。"); result.impact.status = "needs_review"; return finish(); }
  if (input.assessments.some(value => !row(value) || !row(value.graph) || !uuid(value.graph.id) || !revision(value.graph.revision))) { issues.add("固定影响核对记录缺少图身份，须核对原记录。"); result.impact.status = "needs_review"; return finish(); }
  const matching = input.assessments.filter(value => row(value) && row(value.graph) && value.graph.id === graph.id && value.graph.revision === graph.revision);
  const assessment = matching.at(-1);
  if (!assessment) return finish();
  if (!row(assessment) || !fields(assessment, ["id", "request_revision", "graph", "input_digest", "known", "unknown", "hypotheses", "computed_at"]) || !uuid(assessment.id) || !revision(assessment.request_revision) || !text(assessment.input_digest, 120) || !time(assessment.computed_at)
    || !sameGraph(assessment.graph, graph) || !Array.isArray(assessment.unknown) || !Array.isArray(assessment.known) || !Array.isArray(assessment.hypotheses)
    || assessment.known.some(known => !row(known) || !fields(known, ["node", "path", "lanes"]) || !row(known.node) || !fixedRef(known.node.ref) || !sameGraph(nodeRecords.get(refKey(known.node.ref)), known.node) || !Array.isArray(known.path) || !known.path.every(edge => text(edge, 120) && edgeIds.has(edge)) || !Array.isArray(known.lanes) || !known.lanes.every(lane => ["engineering", "manufacturing", "operational"].includes(String(lane))))
    || assessment.hypotheses.some(hypothesis => !row(hypothesis) || !fields(hypothesis, ["text", "sources"]) || !text(hypothesis.text) || !Array.isArray(hypothesis.sources) || !hypothesis.sources.length || !hypothesis.sources.every(source))) { issues.add("对应影响核对的固定图或 UNKNOWN 记录待核对。"); result.impact.status = "needs_review"; return finish(); }
  const unknowns: ChangeCoverageReadingView["impact"]["unknowns"] = [];
  for (const unknown of assessment.unknown) {
    if (!row(unknown) || !fields(unknown, ["node", "facet", "reason"]) || typeof unknown.facet !== "string" || !facetKeys.has(unknown.facet) || !text(unknown.reason) || (unknown.node !== null && (!fixedRef(unknown.node) || !nodeLabels.has(refKey(unknown.node))))) {
      issues.add("对应影响核对的 UNKNOWN 引用、范围或原因待核对。"); result.impact.status = "needs_review"; return finish();
    }
    const facet = changeCoverageFacets.find(facet => facet.key === unknown.facet)!;
    unknowns.push({ facet: facet.key, label: facet.label, reason: unknown.reason, objectLabel: unknown.node === null ? null : nodeLabels.get(refKey(unknown.node as FixedRef))! });
  }
  result.impact = { status: "readable", unknowns };
  for (const facet of result.facets) facet.impactUnknown = unknowns.filter(unknown => unknown.facet === facet.facet).length;
  return finish();
}
