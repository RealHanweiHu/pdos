import { candidateHostBasis, type CandidateHost, type CandidateReview, type CandidateCommand } from "./candidate-workflow-state";
import { candidateLinkKey, candidateMappingKey, candidateSourceKey, validCandidateScope } from "./candidate-form-contract";
import { eventTime, json, positive, record, same, snapshot, uuid } from "./ui-contract";

export type CandidatePanelContext = { product: { id: string; revision: number }; principalId: string; issueId: string };
export type CandidateHistory = { id: string; revision: 1; reason: string; received_at: string; result: "indeterminate";
  applicable: null; independently_verified: null; observation_complete: null; receipt_id: string };
export type CandidatePanelData = { host: CandidateHost; candidates: CandidateHistory[]; history_page?: { next_cursor: string | null }; missing_pair_options: string;
  effectiveness_enabled: false; close_enabled: false };
export class CandidatePanelScopeError extends Error {
  constructor() { super("返回资料不属于当前型号、本人或选定问题，已停止展示与办理。"); }
}
const keys = (value: Record<string, unknown>, fields: string[]) =>
  Object.keys(value).length === fields.length && fields.every(field => Object.hasOwn(value, field));
const string = (value: unknown): value is string => typeof value === "string";
const nullableText = (value: unknown): value is string | null => value === null || string(value);
const array = (value: unknown): value is Record<string, unknown>[] => Array.isArray(value) && value.every(record);
export const candidatePanelScopeValid = (context: CandidatePanelContext) => uuid(context.product.id) &&
  positive(context.product.revision) && uuid(context.principalId) && uuid(context.issueId);

/** Runtime validation does not add capabilities, choices, original values or default clocks. */
export function normalizeCandidatePanel(value: unknown, context: CandidatePanelContext): CandidatePanelData {
  if (!candidatePanelScopeValid(context) || !record(value) || !record(value.host) || !record(value.host.scope))
    throw new CandidatePanelScopeError();
  const h = value.host, s = value.host.scope;
  if (s.product_id !== context.product.id || s.principal_id !== context.principalId || s.issue_id !== context.issueId)
    throw new CandidatePanelScopeError();
  if (!validCandidateScope(s as unknown as CandidateHost["scope"])) throw new CandidatePanelScopeError();
  if (!json(value) || !keys(value, ["host", "candidates", "missing_pair_options", "effectiveness_enabled", "close_enabled", ...(Object.hasOwn(value, "history_page") ? ["history_page"] : [])]) ||
      !keys(h, ["scope", "materials", "product_revision", "required_source_read_set", "allowed", "current_evaluation",
        "source_status", "authority", "missing", "allowProductVisibility", "accessEpoch"]) ||
      !keys(s, ["tenant_id", "product_id", "project_id", "principal_id", "issue_id", "current_issue", "capa_id",
        "failure_ids", "visibility", "issue_label", "capa_label", "origin_issue"]) ||
      !string(s.issue_label) || !string(s.capa_label) || !record(h.materials) ||
      !keys(h.materials, ["links", "mappings", "sources"]) || !array(h.materials.links) || !array(h.materials.mappings) ||
      !array(h.materials.sources) || !h.materials.links.every(row => keys(row, ["ref", "label", "detail", "visibility"]) && string(row.label) && string(row.detail)) ||
      !h.materials.mappings.every(row => keys(row, ["mapping", "label", "detail", "original_value", "conditions", "occurred_at", "original_timezone", "visibility"]) &&
        string(row.label) && string(row.detail) && nullableText(row.original_value) && nullableText(row.conditions) &&
        nullableText(row.occurred_at) && nullableText(row.original_timezone)) ||
      !h.materials.sources.every(row => keys(row, ["reference", "title", "visibility"]) && string(row.title)) ||
      !record(h.authority) || !keys(h.authority, ["authorized", "qualified", "synthetic"]) ||
      candidateHostBasis(h as unknown as CandidateHost) === null ||
      !array(value.candidates) || !value.candidates.every(row => keys(row, ["id", "revision", "reason", "received_at", "result",
        "applicable", "independently_verified", "observation_complete", "receipt_id"]) && uuid(row.id) && row.revision === 1 &&
        string(row.reason) && eventTime(row.received_at) !== null && uuid(row.receipt_id) && row.result === "indeterminate" &&
        row.applicable === null && row.independently_verified === null && row.observation_complete === null) ||
      new Set(value.candidates.map(row => row.id)).size !== value.candidates.length ||
      (Object.hasOwn(value, "history_page") && (!record(value.history_page) || !keys(value.history_page, ["next_cursor"]) || !nullableText(value.history_page.next_cursor))) ||
      !string(value.missing_pair_options) || value.effectiveness_enabled !== false || value.close_enabled !== false)
    throw new Error("候选范围、选项或固定未知状态不能完整核对，请重新读取当前事实。");
  if (Number(h.product_revision) < context.product.revision)
    throw new Error("型号当前版本与入口版本不一致，请先刷新上方当前事实，再读取候选。");
  return snapshot(value as unknown as CandidatePanelData);
}

export const candidateReadCancelled = (error: unknown) => error !== null && typeof error === "object" && "code" in error &&
  (error.code === "READ_SUPERSEDED" || error.code === "READ_CANCELLED");
export const candidateReadError = (error: unknown) => error instanceof CandidatePanelScopeError ? error.message :
  "当前复验候选事实读取失败；尚未因本次读取发起操作。请重试读取，已有原请求仍按原请求恢复。";
type Object = Record<string, unknown>;
export type FailureReading = { identity: string; feature: string; raw_value: string | null; unit: string | null;
  conditions: string | null; environment: string | null; observed_at: string | null; observed_timezone: string | null;
  equipment_label: string | null;
  run_revision: number; sample_revision: number; configuration_revision: number; cavity: string | null;
  criterion: Object | null; method: Object; source: Object; sample_id: string; item_id: string };
export type CompletionReading = { id: string; kind: "corrective" | "preventive"; text: string; completed_text: string;
  occurred_at: string; original_timezone: string; executor_id: string };
export type CandidateBusinessReview = { title: string; purpose: string; origin_revision: number; current_revision: number;
  failures: FailureReading[]; actions: CompletionReading[]; root_cause: string; root_cause_at: string;
  requirement: { method: string; acceptance: string; observation_until: string };
  links: CandidateHost["materials"]["links"]; mappings: CandidateHost["materials"]["mappings"];
  sources: CandidateHost["materials"]["sources"]; missing: { code: string; detail: string }[];
  risk: string; independent_verification: boolean; policy_revision: number; policy_valid_until: string | null;
  roles: string[]; authority_valid_until: string | null; synthetic: boolean; output_readings: Object[];
  source_count: number; visibility: "private" | "category" | "audience"; reason: string };

/** Business reading follows real anchor paths. Malformed/incomplete structures disable confirmation. */
export function candidateBusinessReview(review: CandidateReview, command: CandidateCommand, host: CandidateHost): CandidateBusinessReview | null {
  const anchor = review.stable_anchor, origin = anchor.origin, binding = review.binding, inspection = review.inspection;
  if (!record(origin) || !record(origin.ref) || !record(origin.issue) || !record(origin.scope) || !record(binding.basis) ||
      !record(inspection) || !array(anchor.failures) || !host.scope ||
      origin.issue_id !== host.scope.issue_id || origin.issue.id !== host.scope.issue_id ||
      !same(origin.ref.id, host.scope.origin_issue?.id) || origin.ref.revision !== host.scope.origin_issue?.revision ||
      origin.issue.revision !== origin.ref.revision || !positive(origin.ref.revision) ||
      !same(origin.scope, { tenant_id: host.scope.tenant_id, product_id: host.scope.product_id, project_id: host.scope.project_id }) ||
      !string(origin.issue.title) || !string(origin.purpose) || !record(origin.issue.capa) ||
      origin.issue.capa.id !== host.scope.capa_id || !record(origin.issue.root_cause) ||
      !string(origin.issue.root_cause.text) || eventTime(origin.issue.root_cause.at) === null ||
      !array(origin.issue.capa.actions) || !record(origin.issue.capa.requirement) ||
      !string(origin.issue.capa.requirement.method) || !string(origin.issue.capa.requirement.acceptance) ||
      eventTime(origin.issue.capa.requirement.observation_until) === null) return null;
  const failures: FailureReading[] = [];
  for (const proof of anchor.failures) {
    const f = proof.failure, r = proof.result;
    if (!record(f) || !record(r) || !record(r.verified) || !record(r.verified.run) || !record(f.coverage) ||
        !record(f.sample) || !record(f.sample.actual_configuration) || !array(r.verified.run.measurements) ||
        !array(r.verified.run.items) || !array(r.verified.run.computed_results) || !string(f.identity) ||
        !uuid(f.sample.id) || !positive(f.sample.revision) || !positive(f.sample.actual_configuration.revision) ||
        !positive(r.run_revision) || !record(f.source) || !record(f.method)) return null;
    const measurements = r.verified.run.measurements.filter(row => row.id === f.measurement_id);
    const coverage = f.coverage;
    const items = r.verified.run.items.filter(row => row.id === coverage.item_id);
    const results = r.verified.run.computed_results.filter(row => row.measurement_id === f.measurement_id &&
      same(row.coverage, f.coverage));
    if (measurements.length !== 1 || items.length !== 1 || results.length !== 1 || results[0].result !== "fail") return null;
    const m = measurements[0], item = items[0];
    if (!string(item.feature) || !nullableText(m.raw_value) || !nullableText(m.unit) || !nullableText(m.conditions) ||
        !nullableText(m.environment) || !nullableText(m.equipment_label) || !nullableText(m.observed_at) || !nullableText(m.observed_timezone) ||
        (m.observed_at !== null && eventTime(m.observed_at) === null) || !nullableText(f.sample.cavity) ||
        !(item.criterion === null || record(item.criterion)) || !string(f.coverage.item_id)) return null;
    failures.push({ identity: f.identity, feature: item.feature, raw_value: m.raw_value, unit: m.unit,
      conditions: m.conditions, environment: m.environment, observed_at: m.observed_at, observed_timezone: m.observed_timezone,
      equipment_label: m.equipment_label,
      run_revision: r.run_revision, sample_revision: f.sample.revision, configuration_revision: f.sample.actual_configuration.revision,
      cavity: f.sample.cavity, criterion: item.criterion, method: f.method, source: f.source,
      sample_id: f.sample.id, item_id: f.coverage.item_id });
  }
  if (!same([...failures.map(row => row.identity)].sort(), [...host.scope.failure_ids].sort())) return null;
  const actions: CompletionReading[] = [];
  for (const action of origin.issue.capa.actions) {
    if (!uuid(action.id) || !string(action.text) || !["corrective", "preventive"].includes(String(action.kind)) ||
        !record(action.completion) || !record(action.completion.at) || !uuid(action.executor_id) ||
        !string(action.completion.text) || eventTime(action.completion.at.occurred_at) === null ||
        !string(action.completion.at.original_timezone)) return null;
    actions.push({ id: action.id, kind: action.kind as CompletionReading["kind"], text: action.text,
      completed_text: action.completion.text, occurred_at: String(action.completion.at.occurred_at),
      original_timezone: action.completion.at.original_timezone, executor_id: action.executor_id });
  }
  const links = host.materials.links.filter(choice => command.payload.remediation_link_refs.some(ref => candidateLinkKey(ref) === candidateLinkKey(choice.ref)));
  const mappings = host.materials.mappings.filter(choice => command.payload.mappings.some(mapping => candidateMappingKey(mapping) === candidateMappingKey(choice.mapping)));
  const sources = host.materials.sources.filter(choice => command.payload.sources.some(ref => candidateSourceKey(ref) === candidateSourceKey(choice.reference)));
  const policy = review.policy_snapshot, authority = review.authority_snapshot;
  if (links.length !== command.payload.remediation_link_refs.length || mappings.length !== command.payload.mappings.length ||
      sources.length !== command.payload.sources.length || !array(inspection.missing) ||
      !inspection.missing.every(row => string(row.code) && string(row.detail)) || !array(inspection.outputs) ||
      inspection.observed_from !== null || inspection.observed_until !== null || typeof inspection.current !== "boolean" ||
      !record(inspection.capabilities) || inspection.capabilities.effectiveness_decide !== false || inspection.capabilities.issue_close !== false ||
      !["low", "medium", "high", "critical"].includes(String(policy.risk)) || !positive(policy.revision) ||
      typeof policy.independent_verification !== "boolean" ||
      !(policy.valid_until === null || eventTime(policy.valid_until) !== null) ||
      !Array.isArray(authority.roles) || !authority.roles.every(string) || authority.authorized !== true || authority.qualified !== true ||
      authority.subject_id !== host.scope.principal_id || authority.operation !== command.operation || authority.purpose !== origin.purpose ||
      !same(authority.scope, origin.scope) ||
      typeof authority.synthetic !== "boolean" ||
      !(authority.valid_until === null || eventTime(authority.valid_until) !== null)) return null;
  return { title: origin.issue.title, purpose: origin.purpose, origin_revision: origin.ref.revision,
    current_revision: review.current_issue_revision, failures, actions, root_cause: origin.issue.root_cause.text,
    root_cause_at: String(origin.issue.root_cause.at), requirement: { method: origin.issue.capa.requirement.method,
      acceptance: origin.issue.capa.requirement.acceptance, observation_until: String(origin.issue.capa.requirement.observation_until) },
    links, mappings, sources, missing: inspection.missing.map(row => ({ code: String(row.code), detail: String(row.detail) })),
    risk: String(policy.risk), independent_verification: policy.independent_verification, policy_revision: policy.revision,
    policy_valid_until: policy.valid_until === null ? null : String(policy.valid_until),
    roles: authority.roles,
    authority_valid_until: authority.valid_until === null ? null : String(authority.valid_until),
    synthetic: authority.synthetic || origin.nature === "synthetic" || policy.nature === "synthetic",
    output_readings: inspection.outputs, source_count: review.required_source_read_set.length,
    visibility: review.visibility, reason: command.payload.reason };
}
