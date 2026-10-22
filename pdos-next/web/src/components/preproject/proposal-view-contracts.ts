/** Source metadata is passed through from an ACL-filtered server projection. */
export type ProposalViewSource = Readonly<Record<string, unknown>>;

export type ProposalViewName = "positioning" | "spec-benchmark" | "feature-config" | "definition-maturity";

export const proposalViewNames: Record<ProposalViewName, string> = {
  positioning: "定位图", "spec-benchmark": "规格对标", "feature-config": "功能配置", "definition-maturity": "定义成熟度",
};

export type ProposalViewDocument = {
  proposal_id: string; revision: number; document_digest: string;
  submission_id: string | null; document_mode: string;
};
export type ViewSubjectRef = { type: string; id: string };
export type ViewSubject = ViewSubjectRef & {
  label: string; revision?: number; baseline_kind?: string; definition_id?: string;
  prices?: unknown[]; unmapped_features?: { item_id: string; text: string | null; availability?: string; source_refs: ProposalViewSource[]; reasons: string[] }[]; issues?: string[];
};
export type ViewObservation = {
  subject: ViewSubjectRef; observation_id: string; kind: string; key?: string | null; parameter?: string | null;
  value_type: string | null; value: string | boolean | null; lower?: string | null; upper?: string | null;
  text_value?: string | null; availability: string; nature: string | null; evidence_kind: string; evidence_label?: string;
  source_refs: ProposalViewSource[]; comparable: boolean; reasons: string[];
};
export type ViewComparisonGroup = {
  parameter_id: string; parameter_version: number;
  parameter: { key: string; name: string; value_type: string; direction?: string };
  unit: string | null; condition_note: string | null; test_conditions: unknown;
  observations: ViewObservation[]; sample_count: number; comparable_count: number;
  unknown_count: number; separation_reasons: string[];
};
export type ViewUnknown = { subject: ViewSubjectRef; reasons: string[]; label?: string; observation_id?: string; price_index?: number; source_refs?: ProposalViewSource[] };
export type ViewComparison = {
  engine_version: string; input_digest: string; subjects: ViewSubject[];
  groups: ViewComparisonGroup[]; unmapped: ViewObservation[]; unavailable: ViewUnknown[];
  unknown_count: number;
};
export type ViewPositioningGroup = {
  key: string; parameter_id: string; parameter_version: number; unit: string | null;
  condition_note: string | null; parameter?: ViewComparisonGroup["parameter"]; test_conditions?: unknown;
  price_context: { currency: string | null; basis: string | null; as_of: string | null;
    includes_tax: boolean | null; includes_shipping: boolean | null; channel: string | null; region: string | null };
  points: { subject: ViewSubjectRef; label: string; x: string; y: string; evidence_kind: string; nature?: string; source_refs: ProposalViewSource[] }[];
  sample_count: number;
};
export type ViewMaturityItem = {
  item_id: string; version: number; content: Record<string, unknown>;
  source_refs?: ProposalViewSource[]; blocker_reasons?: string[];
};
export type ViewMaturity = {
  spec_count: number; option_count: number;
  item_status_counts: Record<string, number>; availability_counts: Record<string, number>;
  submission_checks: { worth_it_present: boolean; alternative_or_reason_required: boolean };
  freeze_blockers: ViewMaturityItem[]; questions: ViewMaturityItem[]; guidance?: string;
};
type Envelope = ProposalViewDocument & { context_changes: unknown[]; engine_version: string; input_digest: string };
export type ProposalViewResponse = Envelope & (
  | { view: "spec-benchmark"; data: ViewComparison }
  | { view: "feature-config"; data: Pick<ViewComparison, "groups" | "unmapped" | "subjects"> & { unavailable?: ViewUnknown[] } }
  | { view: "positioning"; data: { groups: ViewPositioningGroup[]; unknowns: ViewUnknown[]; unmapped: ViewObservation[]; unknown_count: number; unavailable?: ViewUnknown[] } }
  | { view: "definition-maturity"; data: ViewMaturity }
);

export function matchesProposalDocument(result: ProposalViewDocument, document: ProposalViewDocument): boolean {
  return result.proposal_id === document.proposal_id && result.revision === document.revision
    && !!result.document_digest && result.document_digest === document.document_digest
    && result.submission_id === document.submission_id && result.document_mode === document.document_mode;
}

const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const strings = (value: unknown): value is string[] => Array.isArray(value) && value.every(item => typeof item === "string");
const records = (value: unknown): value is Record<string, unknown>[] => Array.isArray(value) && value.every(record);
const subject = (value: unknown) => record(value) && typeof value.id === "string" && typeof value.type === "string";
const count = (value: unknown) => typeof value === "number" && Number.isFinite(value) && value >= 0;
const observation = (value: Record<string, unknown>) => subject(value.subject) && typeof value.observation_id === "string"
  && typeof value.availability === "string" && typeof value.evidence_kind === "string"
  && typeof value.comparable === "boolean" && strings(value.reasons) && records(value.source_refs);
const comparisonGroup = (value: Record<string, unknown>) => record(value.parameter) && typeof value.parameter.name === "string"
  && count(value.parameter_version) && records(value.observations) && value.observations.every(observation)
  && count(value.sample_count) && count(value.comparable_count) && count(value.unknown_count) && strings(value.separation_reasons);
const unknowns = (value: unknown) => records(value) && value.every(item => subject(item.subject) && strings(item.reasons)
  && (item.label === undefined || typeof item.label === "string")
  && (item.observation_id === undefined || typeof item.observation_id === "string")
  && (item.price_index === undefined || (count(item.price_index) && Number.isInteger(item.price_index)))
  && (item.source_refs === undefined || records(item.source_refs)));
const maturityItem = (value: Record<string, unknown>) => typeof value.item_id === "string" && count(value.version) && record(value.content);

/** Transport completeness only: never derive comparability, mapping, counts or approval policy. */
export function isProposalViewResponse(value: unknown): value is ProposalViewResponse {
  if (!record(value) || !record(value.data) || typeof value.proposal_id !== "string"
    || !count(value.revision) || typeof value.document_digest !== "string" || !value.document_digest
    || !(value.submission_id === null || typeof value.submission_id === "string") || typeof value.document_mode !== "string"
    || typeof value.engine_version !== "string" || typeof value.input_digest !== "string" || !Array.isArray(value.context_changes)) return false;
  const data = value.data;
  if (data.unavailable !== undefined && !unknowns(data.unavailable)) return false;
  if (value.view === "definition-maturity") return count(data.spec_count) && count(data.option_count)
    && record(data.item_status_counts) && Object.values(data.item_status_counts).every(count)
    && record(data.availability_counts) && Object.values(data.availability_counts).every(count)
    && record(data.submission_checks) && typeof data.submission_checks.worth_it_present === "boolean"
    && typeof data.submission_checks.alternative_or_reason_required === "boolean"
    && records(data.freeze_blockers) && data.freeze_blockers.every(item => maturityItem(item) && strings(item.blocker_reasons) && (item.source_refs === undefined || records(item.source_refs)))
    && records(data.questions) && data.questions.every(maturityItem);
  if (!records(data.unmapped) || !data.unmapped.every(observation) || !records(data.groups)) return false;
  if (value.view === "positioning") return count(data.unknown_count) && unknowns(data.unknowns) && data.groups.every(group =>
    typeof group.key === "string" && count(group.parameter_version) && count(group.sample_count) && record(group.price_context)
    && ["includes_tax", "includes_shipping"].every(key => group.price_context && ((group.price_context as Record<string, unknown>)[key] === null || typeof (group.price_context as Record<string, unknown>)[key] === "boolean"))
    && records(group.points) && group.points.every(point => subject(point.subject) && typeof point.label === "string"
      && typeof point.x === "string" && typeof point.y === "string" && typeof point.evidence_kind === "string" && records(point.source_refs)));
  return ["spec-benchmark", "feature-config"].includes(String(value.view)) && records(data.subjects)
    && data.subjects.every(item => subject(item) && typeof item.label === "string"
      && (item.unmapped_features === undefined || (records(item.unmapped_features) && item.unmapped_features.every(feature => typeof feature.item_id === "string" && (feature.text === null || typeof feature.text === "string") && (feature.availability === undefined || typeof feature.availability === "string") && records(feature.source_refs) && strings(feature.reasons))))) && data.groups.every(comparisonGroup)
    && (value.view === "feature-config" || (unknowns(data.unavailable) && count(data.unknown_count)));
}
