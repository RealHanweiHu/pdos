/** Host-to-view adapter contract. No HTTP route or client-issued qualification. */
import { eventTime, eventTimezone, json, positive, record, same, validMaterial, validMissing,
  validReads, validScope, uuid, type JsonObject, type MaterialRef, type Missing, type Read,
  type Scope, type Authority, type Evaluation, type SourceState } from "./ui-contract";
import type { CandidateFailurePairMapping } from "./candidate-form-contract";

export const factWorkflowSchema = "pdos-capa-fact-workflow-v1" as const;
export const observationOperation = "quality.capa.observation.record" as const;
export const reviewOperation = "quality.capa.verification.review" as const;
export type FactOperation = typeof observationOperation | typeof reviewOperation;
export type FactSource = { id: string; revision: number; kind: "artifact"; position: string };
export type FactEvent = { occurred_at: string; original_timezone: string; source: FactSource; effective_at: null };
export type FactVisibility = "private" | "category" | "audience";
export type FactSourceChoice = { source: FactSource; title: string; line: number; quote: string; visibility: FactVisibility };
export type FactRecord = { target_key: string; occurred_at: string; original_timezone: string;
  sources: FactSource[]; raw_material: JsonObject };
export type FactRecordChoice = { key: string; label: string; detail: string; record: FactRecord; visibility: FactVisibility;
  /** Optional, whole server-verified event selection. Never derived from display text. */
  observed_from?: string; observed_until?: string; at?: FactEvent };
export type FactPairChoice = { key: string; label: string; detail: string; mapping: CandidateFailurePairMapping;
  method: FactSource | null; criterion: FactSource | null; visibility: FactVisibility };
export type FactActionChoice = { action_id: string; label: string; detail: string; visibility: FactVisibility };
export type FactRuleChoice = { ref: MaterialRef; label: string; target_keys: string[]; previous: MaterialRef | null };
export type FactHistory = { ref: MaterialRef; kind: "rule" | "observation" | "review"; label: string;
  fact: JsonObject; current_evaluation: Evaluation; source_status: SourceState; missing: Missing[] };
export type FactBinding = { scope: Scope; caller_id: string; issue_id: string; current_issue: { id: string; revision: number };
  capa_id: string; purpose: string; owner_id: string; visibility: FactVisibility };
export type FactCapability = { allowed: boolean; authority: Authority; independence: "verified" | "not_verified" | "not_required";
  current_evaluation: Evaluation; source_status: SourceState; missing: Missing[]; required_source_read_set: Read[] };
export type FactCandidateChoice = { ref: MaterialRef; label: string; mapping_count: number; visibility: FactVisibility };
export type FactHost = { schema_version: typeof factWorkflowSchema; binding: FactBinding; product_revision: number;
  access_epoch: string; rules: FactRuleChoice[]; candidate: MaterialRef | null; observations: MaterialRef[];
  /** Older offline host fixtures may omit this. The actual panel requires server choices. */
  candidate_options?: FactCandidateChoice[];
  sources: FactSourceChoice[]; records: FactRecordChoice[]; pairs: FactPairChoice[]; actions: FactActionChoice[];
  history: FactHistory[]; history_page?: { next_cursor: string | null }; operations: Record<FactOperation, FactCapability>; missing: Missing[];
  effectiveness_enabled: false; close_enabled: false };
export type ObservationPayload = { issue_id: string; expected_issue_revision: number; capa_id: string;
  rule: MaterialRef; previous: MaterialRef | null; target_keys: string[]; observed_from: string; observed_until: string;
  at: FactEvent; records: FactRecord[]; coverage_sources: FactSource[]; sources: FactSource[]; reason: string;
  visibility: FactVisibility; confirmation_token?: string };
export type PairAssessment = { mapping: CandidateFailurePairMapping; method: FactSource | null; criterion: FactSource | null;
  conclusion: "applicable" | "not_applicable" | "unknown"; reason: string; sources: FactSource[] };
export type ActionAssessment = { action_id: string; conclusion: PairAssessment["conclusion"]; reason: string; sources: FactSource[] };
export type NamedReviewPayload = { issue_id: string; expected_issue_revision: number; capa_id: string;
  candidate: MaterialRef; rule: MaterialRef; observations: MaterialRef[]; at: FactEvent;
  pair_applicability: PairAssessment[]; action_fulfillment: ActionAssessment[];
  conclusion: PairAssessment["conclusion"]; reason: string; sources: FactSource[];
  visibility: FactVisibility; approval_token?: string };
export type FactPayload = ObservationPayload | NamedReviewPayload;
export type FactCommand = { command_id: string; idempotency_key: string; product_id: string; expected_revision: number;
  operation: FactOperation; payload: FactPayload; source_read_set: Read[] };
/** The installed host renderer must inspect actual material; this is a read-only display projection. */
export type FactBusinessReview = { title: string; sections: { title: string; rows: { label: string; value: string | null }[] }[];
  sources: FactSourceChoice[]; synthetic: boolean; effect: string; complete: boolean };
export type FactPrepared = { command: FactCommand; expires_at: string | null; write_tier: "T1" | "T2";
  named_decision: boolean; review: JsonObject };
export type FactReceipt = { id: string; operation: FactOperation; subject_id: string; subject_revision: number;
  subject_type: "capa_observation" | "capa_named_verification_review" };

const fields = (x: Record<string, unknown>, keys: string[]) => Object.keys(x).length === keys.length && keys.every(k => Object.hasOwn(x, k));
const text = (x: unknown, max = 2000): x is string => typeof x === "string" && x.trim().length > 0 && [...x].length <= max;
export const factSourceKey = (x: FactSource): string => JSON.stringify([x.id, x.revision, x.kind, x.position]);
export function validFactSource(x: unknown): x is FactSource {
  return record(x) && fields(x, ["id", "revision", "kind", "position"]) && uuid(x.id) && positive(x.revision) && x.kind === "artifact" &&
    typeof x.position === "string" && /^line:[1-9]\d*;quote_sha256:[0-9a-f]{64}$/.test(x.position);
}
const sources = (x: unknown, minimum = 1): x is FactSource[] => Array.isArray(x) && x.length >= minimum &&
  x.every(validFactSource) && new Set(x.map(factSourceKey)).size === x.length;
export function validFactEvent(x: unknown): x is FactEvent {
  return record(x) && fields(x, ["occurred_at", "original_timezone", "source", "effective_at"]) && x.effective_at === null && factInstant(x.occurred_at) !== null &&
    eventTimezone(x.original_timezone) !== null && validFactSource(x.source);
}
const conclusion = (x: unknown) => x === "applicable" || x === "not_applicable" || x === "unknown";
export const tokenlessFactPayload = (p: FactPayload): FactPayload => Object.fromEntries(Object.entries(p)
  .filter(([key]) => key !== "confirmation_token" && key !== "approval_token")) as FactPayload;
/** Compare parsed instants at Python datetime precision without rewriting original strings. */
export function factInstant(value: unknown): bigint | null {
  if (eventTime(value) === null || typeof value !== "string") return null;
  const fraction = value.match(/\.(\d+)(?:Z|[+-]\d\d:\d\d)$/)?.[1] ?? "";
  if (fraction.length > 6) return null;
  return BigInt(Date.parse(value)) * BigInt(1000) + BigInt(fraction.padEnd(6, "0").slice(3));
}
export function sameFactInstant(a: unknown, b: unknown): boolean {
  const one = factInstant(a), two = factInstant(b); return one !== null && two !== null && one === two;
}
const increasing = (a: unknown, b: unknown) => { const x = factInstant(a), y = factInstant(b); return x !== null && y !== null && x < y; };
const notAfter = (a: unknown, b: unknown) => { const x = factInstant(a), y = factInstant(b); return x !== null && y !== null && x <= y; };
/** Copy only a complete verified clock selection, keeping every original character. */
export function factRecordTiming(choice: FactRecordChoice): { observed_from: string; observed_until: string; at: FactEvent } | null {
  const { observed_from, observed_until, at } = choice;
  if (typeof observed_from !== "string" || typeof observed_until !== "string" || !validFactEvent(at) ||
      !increasing(observed_from, observed_until) || !notAfter(observed_until, at.occurred_at) ||
      !record(choice.record) || !notAfter(observed_from, choice.record.occurred_at) || !notAfter(choice.record.occurred_at, observed_until) ||
      !sources(choice.record.sources) || !choice.record.sources.some(ref => same(ref, at.source))) return null;
  return { observed_from, observed_until, at: { ...at, source: { ...at.source } } };
}
export function sameFactPayloadSemantics(a: unknown, b: FactPayload): boolean {
  if (!record(a)) return false;
  const normalized = (value: Record<string, unknown>): Record<string, unknown> => {
    const result = { ...value };
    for (const key of ["observed_from", "observed_until"]) if (Object.hasOwn(result, key)) result[key] = factInstant(result[key]);
    if (record(result.at)) result.at = { ...result.at, occurred_at: factInstant(result.at.occurred_at) };
    if (Array.isArray(result.records)) result.records = result.records.map(r => record(r) ? { ...r, occurred_at: factInstant(r.occurred_at) } : r);
    return result;
  };
  return same(normalized(a), normalized(tokenlessFactPayload(b) as unknown as Record<string, unknown>));
}
export function validFactPayload(op: FactOperation, value: unknown): value is FactPayload {
  if (!record(value) || !uuid(value.issue_id) || !positive(value.expected_issue_revision) || !uuid(value.capa_id) ||
      !validMaterial(value.rule) || !validFactEvent(value.at) || !sources(value.sources) || !text(value.reason) ||
      !["private", "category", "audience"].includes(String(value.visibility)) || !json(value)) return false;
  const tokenKey = op === observationOperation ? "confirmation_token" : "approval_token";
  if (Object.hasOwn(value, tokenKey) && (!text(value[tokenKey], 128) || String(value[tokenKey]).length < 20)) return false;
  const keys = op === observationOperation ? ["issue_id", "expected_issue_revision", "capa_id", "rule", "previous", "target_keys",
    "observed_from", "observed_until", "at", "records", "coverage_sources", "sources", "reason", "visibility"] :
    ["issue_id", "expected_issue_revision", "capa_id", "candidate", "rule", "observations", "at", "pair_applicability", "action_fulfillment", "conclusion", "reason", "sources", "visibility"];
  if (!fields(value, Object.hasOwn(value, tokenKey) ? [...keys, tokenKey] : keys)) return false;
  if (op === observationOperation) {
    const targets = value.target_keys, records = value.records;
    if (!Array.isArray(targets) || !Array.isArray(records)) return false;
    return (value.previous === null || validMaterial(value.previous)) && eventTime(value.observed_from) !== null && eventTime(value.observed_until) !== null &&
      increasing(value.observed_from, value.observed_until) && notAfter(value.observed_until, value.at.occurred_at) &&
      targets.length > 0 && targets.every(v => text(v)) &&
      new Set(targets).size === targets.length && sources(value.coverage_sources) &&
      records.length > 0 && records.every(r => record(r) && fields(r, ["target_key", "occurred_at", "original_timezone", "sources", "raw_material"]) &&
        text(r.target_key) && targets.includes(r.target_key) && eventTime(r.occurred_at) !== null && eventTimezone(r.original_timezone) !== null &&
        notAfter(value.observed_from, r.occurred_at) && notAfter(r.occurred_at, value.observed_until) &&
        sources(r.sources) && record(r.raw_material) && json(r.raw_material)) &&
      records.every((r, i) => !records.slice(0, i).some(old => same(r, old)));
  }
  return validMaterial(value.candidate) && value.candidate.revision === 1 && Array.isArray(value.observations) && value.observations.length > 0 &&
    value.observations.every(validMaterial) && new Set(value.observations.map(r => r.id)).size === value.observations.length &&
    conclusion(value.conclusion) && Array.isArray(value.pair_applicability) && value.pair_applicability.length > 0 && value.pair_applicability.every(p =>
      record(p) && fields(p, ["mapping", "method", "criterion", "conclusion", "reason", "sources"]) && record(p.mapping) && json(p.mapping) &&
      (p.method === null || validFactSource(p.method)) && (p.criterion === null || validFactSource(p.criterion)) && conclusion(p.conclusion) && text(p.reason) && sources(p.sources)) &&
    Array.isArray(value.action_fulfillment) && value.action_fulfillment.length > 0 && value.action_fulfillment.every(a => record(a) &&
      fields(a, ["action_id", "conclusion", "reason", "sources"]) && uuid(a.action_id) && conclusion(a.conclusion) && text(a.reason) && sources(a.sources)) &&
    new Set(value.action_fulfillment.map(a => record(a) ? a.action_id : null)).size === value.action_fulfillment.length;
}
export function validFactCommand(x: unknown): x is FactCommand {
  return record(x) && fields(x, ["command_id", "idempotency_key", "product_id", "expected_revision", "operation", "payload", "source_read_set"]) &&
    uuid(x.command_id) && uuid(x.idempotency_key) && uuid(x.product_id) && positive(x.expected_revision) &&
    (x.operation === observationOperation || x.operation === reviewOperation) && validFactPayload(x.operation, x.payload) && validReads(x.source_read_set);
}
export function factIdentity(host: FactHost): string | null {
  const b = host?.binding;
  return b && validScope(b.scope) && [b.caller_id, b.issue_id, b.capa_id].every(uuid) ?
    JSON.stringify([b.scope.tenant_id, b.scope.product_id, b.scope.project_id, b.caller_id, b.issue_id, b.capa_id]) : null;
}
export function validFactHost(h: FactHost): boolean {
  const b = h?.binding;
  if (h?.schema_version !== factWorkflowSchema || !factIdentity(h) || !b || !record(b.current_issue) || !uuid(b.current_issue.id) ||
      !positive(b.current_issue.revision) || !uuid(b.owner_id) || !text(b.purpose) || !["private", "category", "audience"].includes(b.visibility) ||
      !positive(h.product_revision) || !text(h.access_epoch) || h.effectiveness_enabled !== false || h.close_enabled !== false ||
      !validMissing(h.missing) || !Array.isArray(h.sources) || !h.sources.every(s => validFactSource(s.source) && text(s.title) && positive(s.line) &&
        text(s.quote, 20000) && s.source.position.startsWith(`line:${s.line};`) && ["private", "category", "audience"].includes(s.visibility)) ||
      new Set(h.sources.map(s => factSourceKey(s.source))).size !== h.sources.length || !Array.isArray(h.history) ||
      !h.history.every(r => validMaterial(r.ref) && ["rule", "observation", "review"].includes(r.kind) && text(r.label) && record(r.fact) && json(r.fact) && validMissing(r.missing) &&
        ["evaluated_current", "not_evaluated_historical", "unavailable"].includes(r.current_evaluation) && ["current", "needs_recheck", "unavailable"].includes(r.source_status)) ||
      (Object.hasOwn(h, "history_page") && (!record(h.history_page) || !fields(h.history_page, ["next_cursor"]) || !(h.history_page.next_cursor === null || typeof h.history_page.next_cursor === "string"))) ||
      !Array.isArray(h.rules) || !h.rules.every(r => validMaterial(r.ref) && text(r.label) && Array.isArray(r.target_keys) &&
        r.target_keys.length > 0 && r.target_keys.every(k => text(k)) && (r.previous === null || validMaterial(r.previous))) ||
      !(h.candidate === null || validMaterial(h.candidate)) ||
      (Object.hasOwn(h, "candidate_options") && (!Array.isArray(h.candidate_options) || !h.candidate_options.every(c => record(c) &&
        validMaterial(c.ref) && text(c.label) && Number.isSafeInteger(c.mapping_count) && c.mapping_count >= 0 &&
        ["private", "category", "audience"].includes(c.visibility)) || new Set(h.candidate_options.map(c => c.ref.id)).size !== h.candidate_options.length)) ||
      !Array.isArray(h.observations) || !h.observations.every(validMaterial) ||
      !Array.isArray(h.records) || !h.records.every(r => text(r.key) && text(r.label) && text(r.detail) && record(r.record) && json(r.record) &&
        ["private", "category", "audience"].includes(r.visibility) && (!["observed_from", "observed_until", "at"].some(k => Object.hasOwn(r, k)) || factRecordTiming(r) !== null)) ||
      !Array.isArray(h.pairs) || !h.pairs.every(p => text(p.key) && text(p.label) && record(p.mapping) && json(p.mapping)) ||
      !Array.isArray(h.actions) || !h.actions.every(a => uuid(a.action_id) && text(a.label))) return false;
  return [observationOperation, reviewOperation].every(op => {
    const c = h.operations?.[op]; return c && typeof c.allowed === "boolean" && typeof c.authority?.authorized === "boolean" &&
      (c.authority.qualified === null || typeof c.authority.qualified === "boolean") && typeof c.authority.synthetic === "boolean" &&
      ["verified", "not_verified", "not_required"].includes(c.independence) && validMissing(c.missing) && validReads(c.required_source_read_set) &&
      ["evaluated_current", "not_evaluated_historical", "unavailable"].includes(c.current_evaluation) && ["current", "needs_recheck", "unavailable"].includes(c.source_status);
  });
}
/** Actual scoped GET: no default candidate and no silent substitution of a fixed ref. */
export function factCandidateSelectionMatches(h: FactHost, productId: string, principalId: string, issueId: string,
  selected: MaterialRef | null): boolean {
  return validFactHost(h) && Array.isArray(h.candidate_options) && h.binding.scope.product_id === productId &&
    h.binding.caller_id === principalId && h.binding.issue_id === issueId && same(h.candidate, selected) &&
    (selected === null || h.candidate_options.some(c => same(c.ref, selected)));
}
/** Only an already validated, scope-matching original pending command restores a selection. */
export function factPendingCandidate(h: FactHost, command: unknown): MaterialRef | null {
  if (!validFactHost(h) || !validFactCommand(command) || command.operation !== reviewOperation || !("candidate" in command.payload) ||
      command.product_id !== h.binding.scope.product_id || command.payload.issue_id !== h.binding.issue_id ||
      command.payload.capa_id !== h.binding.capa_id) return null;
  return { ...command.payload.candidate };
}
export function factCanPrepare(h: FactHost, op: FactOperation): boolean {
  if (!validFactHost(h)) return false;
  const c = h.operations[op];
  return c.allowed && c.authority.authorized && c.authority.qualified === true && c.current_evaluation === "evaluated_current" && c.source_status === "current" &&
    (op !== reviewOperation || c.independence === "verified");
}
export const factHostBasis = (h: FactHost): string | null => validFactHost(h) ? JSON.stringify(h) : null;
export function sameFactCommand(a: FactCommand, b: FactCommand): boolean {
  return same({ ...a, payload: null }, { ...b, payload: null }) &&
    sameFactPayloadSemantics(tokenlessFactPayload(a.payload), b.payload);
}

const businessConclusion = (x: unknown): string | null => x === "applicable" ? "适用" : x === "not_applicable" ? "不适用" : x === "unknown" ? "尚不能确定" : null;
const businessText = (x: unknown): string | null => typeof x === "string" ? x : typeof x === "number" || typeof x === "boolean" ? String(x) : null;
/** Read the actual thirteen-key material. No conclusion or receipt is manufactured. */
export function readFactBusinessReview(host: FactHost, review: Record<string, unknown>, command: FactCommand): FactBusinessReview | null {
  if (!validFactHost(host) || !validFactCommand(command) || !record(review.binding) || !record(review.binding.body_material) ||
      !record(review.inspection) || !record(review.stable_anchor) || !record(review.authority_snapshot) || !record(review.policy_snapshot) ||
      !sameFactPayloadSemantics(review.payload_semantic, command.payload) || !same(review.required_source_read_set, command.source_read_set) ||
      review.current_issue_revision !== command.payload.expected_issue_revision) return null;
  const body = review.binding.body_material, p = tokenlessFactPayload(command.payload);
  if (!same(body.scope, host.binding.scope) || body.issue_id !== host.binding.issue_id || body.capa_id !== host.binding.capa_id ||
      body.purpose !== host.binding.purpose || body.owner_id !== host.binding.owner_id || body.visibility !== host.binding.visibility ||
      review.binding.current_issue_version_id !== host.binding.current_issue.id ||
      !same(body.rule, p.rule) || !record(body.at) || !sameFactInstant(body.at.occurred_at, p.at.occurred_at) ||
      !same({ ...body.at, occurred_at: null }, { ...p.at, occurred_at: null })) return null;
  const chosen = host.rules.find(r => same(r.ref, p.rule));
  if (!chosen) return null;
  const rawRefs: FactSource[] = [...p.sources, p.at.source];
  const sections: FactBusinessReview["sections"] = [{ title: "固定问题与用途", rows: [
    { label: "用途", value: host.binding.purpose }, { label: "本次核对的问题版本", value: `当前第 ${p.expected_issue_revision} 版` },
    { label: "受众", value: p.visibility === "private" ? "私人固定范围" : "品类共享固定范围" },
    { label: "采用的规则", value: `${chosen.label} · 第 ${p.rule.revision} 版` },
  ] }, { title: "实际事件与本人说明", rows: [
    { label: "实际发生时间", value: p.at.occurred_at }, { label: "事件原时区", value: p.at.original_timezone },
    { label: "本人办理原因", value: p.reason }, { label: "系统接收时间", value: "保存时由服务器记录，不作为实际发生时间" },
  ] }];
  const origin = review.stable_anchor.origin;
  if (!record(origin) || !record(origin.issue) || !record(origin.issue.capa) || !record(origin.ref) || !positive(origin.ref.revision) ||
      !Array.isArray(review.stable_anchor.failures) || !review.stable_anchor.failures.length || !Array.isArray(origin.issue.capa.actions)) return null;
  sections.push({ title: "原失败、根因与已完成整改", rows: [
    { label: "固定原问题版本", value: `原问题第 ${origin.ref.revision} 版，保留原历史，不替代当前办理版本` },
    { label: "具名根因", value: record(origin.issue.root_cause) ? businessText(origin.issue.root_cause.text) : null },
  ] });
  for (const entry of review.stable_anchor.failures) {
    if (!record(entry) || !record(entry.failure) || !record(entry.result) || !record(entry.result.verified) || !record(entry.result.verified.run) ||
        !Array.isArray(entry.result.verified.run.measurements)) return null;
    const failure = entry.failure;
    const original = entry.result.verified.run.measurements.filter(m => record(m) && m.id === failure.measurement_id);
    if (original.length !== 1 || !record(original[0])) return null;
    const m = original[0];
    sections.push({ title: "固定原失败测量", rows: [{ label: "原值", value: businessText(m.raw_value) },
      { label: "原单位", value: businessText(m.unit) }, { label: "原工况", value: businessText(m.conditions) },
      { label: "原环境", value: businessText(m.environment) }, { label: "原设备", value: businessText(m.equipment_label) },
      { label: "原观察时间", value: businessText(m.observed_at) }, { label: "原观察时区", value: businessText(m.observed_timezone) }] });
  }
  for (const action of origin.issue.capa.actions) {
    if (!record(action) || !record(action.completion) || !record(action.completion.at)) return null;
    sections.push({ title: "已固定的实际措施完成", rows: [{ label: "措施", value: businessText(action.text) },
      { label: "实际完成说明", value: businessText(action.completion.text) }, { label: "实际完成时间", value: businessText(action.completion.at.occurred_at) },
      { label: "完成事件原时区", value: businessText(action.completion.at.original_timezone) }] });
  }
  const fixedRule = host.history.find(h => h.kind === "rule" && same(h.ref, p.rule));
  if (!fixedRule || !record(fixedRule.fact.sampling)) return null;
  const sampling = fixedRule.fact.sampling;
  sections.push({ title: "实际固定规则与抽样要求", rows: [
    { label: "规则", value: fixedRule.label }, { label: "规则规定观察开始", value: businessText(sampling.observation_from) },
    { label: "规则规定观察截止", value: businessText(sampling.observation_until) }, { label: "规则要求最少记录", value: businessText(sampling.minimum_records) },
    { label: "具名复核要求", value: sampling.require_named_review === true ? "须具名独立专业复核" : null },
    { label: "实际新测试复核要求", value: typeof sampling.require_run_review === "boolean" ? sampling.require_run_review ? "规则要求" : "规则未要求" : null },
    { label: "实际处置要求", value: typeof sampling.require_disposition === "boolean" ? sampling.require_disposition ? "规则要求" : "规则未要求" : null },
  ] });
  if (command.operation === observationOperation && "records" in p) {
    const actualRecords = body.records;
    if (!sameFactInstant(body.observed_from, p.observed_from) || !sameFactInstant(body.observed_until, p.observed_until) || !Array.isArray(actualRecords) ||
        actualRecords.length !== p.records.length || !p.records.every((r, i) => record(actualRecords[i]) && Object.entries(r).every(([k, v]) =>
          k === "occurred_at" ? sameFactInstant(v, actualRecords[i][k]) : same(v, actualRecords[i][k])))) return null;
    sections.push({ title: "实际观察范围", rows: [
      { label: "观察开始", value: p.observed_from }, { label: "观察结束", value: p.observed_until },
      { label: "实际目标与记录", value: `${p.target_keys.length} 个已选目标、${p.records.length} 条固定原记录` },
      { label: "历史保留", value: p.previous ? `保留上一固定第 ${p.previous.revision} 版，追加新版本` : "建立首版固定观察事实" },
    ] });
    for (const r of p.records) {
      const choice = host.records.find(c => same(c.record, r));
      if (!choice) return null;
      const known = ["raw_value", "value", "unit", "conditions", "environment", "equipment_label", "note", "text"];
      sections.push({ title: choice.label, rows: [{ label: "实际原记录说明", value: choice.detail },
        { label: "记录发生时间", value: r.occurred_at }, { label: "记录原时区", value: r.original_timezone },
        ...known.filter(k => Object.hasOwn(r.raw_material, k)).map(k => ({ label: ({ raw_value: "原值", value: "原值", unit: "单位", conditions: "实际工况", environment: "实际环境", equipment_label: "实际设备", note: "原备注", text: "原事实说明" } as Record<string, string>)[k], value: businessText(r.raw_material[k]) })),
      ] });
      rawRefs.push(...r.sources);
    }
    rawRefs.push(...p.coverage_sources);
  } else if (command.operation === reviewOperation && "candidate" in p) {
    if (!same(body.candidate, p.candidate) || !same(body.observations, p.observations) || body.conclusion !== p.conclusion ||
        body.reviewer_id !== host.binding.caller_id || !Array.isArray(body.participants) || !body.participants.length ||
        !record(body.participant_owner_material) || !Array.isArray(body.pair_applicability) || !Array.isArray(body.action_fulfillment) ||
        body.pair_applicability.length !== p.pair_applicability.length || body.action_fulfillment.length !== p.action_fulfillment.length) return null;
    sections.push({ title: "具名复核范围", rows: [
      { label: "固定候选", value: `候选第 ${p.candidate.revision} 版，原固定失败不覆盖` },
      { label: "固定观察版本", value: p.observations.map(o => `第 ${o.revision} 版`).join("、") },
      { label: "本人总体专业结论", value: businessConclusion(p.conclusion) },
      { label: "实际参与者核对", value: `${body.participants.length} 名参与者，由服务器实际owner核对；界面不编辑参与者或独立资格` },
    ] });
    for (const [i, assessment] of p.pair_applicability.entries()) {
      const actual = body.pair_applicability[i];
      if (!record(actual) || !Object.entries(assessment).every(([k, v]) => same(v, actual[k]))) return null;
      const pair = host.pairs.find(c => same(c.mapping, assessment.mapping)); if (!pair) return null;
      sections.push({ title: pair.label, rows: [{ label: "原失败与实际复验对应", value: pair.detail },
        { label: "本项专业结论", value: businessConclusion(assessment.conclusion) }, { label: "本人结论说明", value: assessment.reason }] });
      rawRefs.push(...assessment.sources, ...(assessment.method ? [assessment.method] : []), ...(assessment.criterion ? [assessment.criterion] : []));
    }
    for (const [i, assessment] of p.action_fulfillment.entries()) {
      const actual = body.action_fulfillment[i];
      if (!record(actual) || !record(actual.action) || actual.action.action_id !== assessment.action_id || actual.conclusion !== assessment.conclusion || actual.reason !== assessment.reason) return null;
      const action = host.actions.find(c => c.action_id === assessment.action_id); if (!action) return null;
      sections.push({ title: action.label, rows: [{ label: "实际整改依据", value: action.detail },
        { label: "本项履行结论", value: businessConclusion(assessment.conclusion) }, { label: "本人结论说明", value: assessment.reason }] });
      rawRefs.push(...assessment.sources);
    }
  } else return null;
  const visible = [...new Map(rawRefs.map(ref => [factSourceKey(ref), ref])).values()].map(ref => host.sources.find(s => same(s.source, ref)));
  if (visible.some(s => !s)) return null;
  const currentAuthority = host.operations[command.operation];
  const policy = review.policy_snapshot;
  const inspection = review.inspection;
  const gaps = inspection.missing;
  if (!Array.isArray(gaps) || !gaps.every(m => typeof m === "string" || record(m) && text(m.detail))) return null;
  const gapLabels: Record<string, string> = { OBSERVATION_TARGETS_INCOMPLETE: "实际观察目标尚未覆盖规则要求的全部范围。",
    OBSERVATION_SAMPLING_INCOMPLETE: "实际原记录数量尚未达到规则抽样要求。", OBSERVATION_INTERVAL_INCOMPLETE: "实际观察区间尚未覆盖规则规定的完整观察期。" };
  const judgments = ["applicable", "independently_verified", "observation_complete"].filter(k => Object.hasOwn(inspection, k));
  sections.push({ title: "服务器实际核对与保留缺项", rows: [
    ...judgments.map(k => ({ label: ({ applicable: "实际适用性", independently_verified: "实际独立核验", observation_complete: "观察完整性" } as Record<string, string>)[k],
      value: inspection[k] === null ? "尚不能确定，保持未知" : inspection[k] === true ? "服务器已核对" : inspection[k] === false ? "服务器核对不满足" : null })),
    ...gaps.map(m => ({ label: "实际缺项", value: typeof m === "string" ? gapLabels[m] ?? "仍有来源或专业材料需核对，不能据本次保存作有效性决定。" : String(m.detail) })),
    { label: "本次核验与有效性", value: "本次只保存事实或具名专业结论；有效性与关闭均未办理" },
  ] });
  sections.push({ title: "当前专业职责、政策与缺项", rows: [
    { label: "专业办理资格", value: currentAuthority.authority.qualified === null ? "尚不能核对" : currentAuthority.authority.qualified ? "服务器已返回本操作当前资格" : "不满足当前专业资格" },
    { label: "独立核验", value: currentAuthority.independence === "verified" ? "由服务器核对独立资格" : currentAuthority.independence === "not_required" ? "本观察记录不作为独立复核" : "独立资格尚未核对" },
    ...currentAuthority.missing.map(m => ({ label: "实际缺项", value: m.detail })),
    ...["purpose", "method", "acceptance", "observation_until", "valid_until"].filter(k => Object.hasOwn(policy, k)).map(k => ({
      label: ({ purpose: "固定政策用途", method: "固定政策方法", acceptance: "固定政策接受准则", observation_until: "固定政策观察截止", valid_until: "固定政策有效截止" } as Record<string, string>)[k],
      value: businessText(policy[k]),
    })),
    { label: "有效性与关闭", value: "均未办理，不从本次保存或专业结论推定措施已有效" },
  ] });
  return { title: command.operation === observationOperation ? "核对本次实际观察事实" : "核对本次独立具名专业决定", sections,
    sources: visible as FactSourceChoice[], synthetic: body.nature === "synthetic" || currentAuthority.authority.synthetic,
    effect: command.operation === observationOperation ? "追加不可变观察记录与固定历史。观察完整性仍由实际规则及owner核对，未决定有效性或关闭。" :
      "保存本人具名的逐配对、逐措施及总体专业结论。结论未知保持未知，未决定措施有效、问题关闭或成品放行。", complete: true };
}
