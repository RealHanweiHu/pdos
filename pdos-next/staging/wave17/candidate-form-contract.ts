/** Staged form contract only. No public route, qualification or command producer. */
export const candidateFormSchema = "pdos-capa-candidate-form-v1" as const;

export type CandidateFixedRef = Readonly<{ id: string; revision: number }>;
export type CandidateDefinitionReference = Readonly<{
  artifact_id: string; expected_revision: number; line: number; quote: string;
}>;
export type CandidateFailurePairMapping = Readonly<{
  failure_id: string;
  run: Readonly<{ id: string; revision: number; kind: "verification_run"; key: null }>;
  sample_id: string;
  sample_revision: number;
  actual_configuration_id: string;
  actual_configuration_revision: number;
  item_id: string;
  measurement_id: string | null;
  projection_id: string | null;
  applicability_sources: readonly CandidateDefinitionReference[];
}>;
export type CandidateVisibility = "private" | "product";
/** Exactly the tokenless Python Payload fields. The host adds the common envelope later. */
export type CandidateFormPayload = Readonly<{
  issue_id: string;
  expected_issue_revision: number;
  capa_id: string;
  remediation_link_refs: readonly Readonly<{ id: string; revision: 1 }>[];
  mappings: readonly CandidateFailurePairMapping[];
  sources: readonly CandidateDefinitionReference[];
  reason: string;
  visibility: CandidateVisibility;
}>;
export type CandidateFormScope = Readonly<{
  tenant_id: string;
  product_id: string;
  project_id: string;
  principal_id: string;
  issue_id: string;
  current_issue: CandidateFixedRef;
  capa_id: string;
  failure_ids: readonly string[];
  visibility: CandidateVisibility;
  issue_label: string;
  capa_label: string;
  /** Traceability only. Never replaces current_issue.revision in the payload. */
  origin_issue: CandidateFixedRef | null;
}>;
export type CandidateLinkChoice = Readonly<{
  ref: Readonly<{ id: string; revision: 1 }>;
  label: string;
  detail: string;
  visibility: CandidateVisibility | null;
}>;
export type CandidateMappingChoice = Readonly<{
  mapping: CandidateFailurePairMapping;
  label: string;
  /** Actual host text only; this form neither computes nor rewrites values/clocks. */
  original_value: string | null;
  conditions: string | null;
  occurred_at: string | null;
  original_timezone: string | null;
  detail: string;
  visibility: CandidateVisibility | null;
}>;
export type CandidateSourceChoice = Readonly<{
  reference: CandidateDefinitionReference;
  title: string;
  visibility: CandidateVisibility | null;
}>;
export type CandidateMaterials = Readonly<{
  links: readonly CandidateLinkChoice[];
  mappings: readonly CandidateMappingChoice[];
  sources: readonly CandidateSourceChoice[];
}>;
export type CandidateFormSelection = Readonly<{
  links: readonly string[];
  mappings: readonly string[];
  sources: readonly string[];
  reason: string;
  visibility: CandidateVisibility;
}>;

const uuid = (value: string): boolean => typeof value === "string" &&
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(value);
const revision = (value: number): boolean => Number.isSafeInteger(value) && value > 0;
const text = (value: string, maximum = 2000): boolean => typeof value === "string" &&
  value.trim().length > 0 && [...value].length <= maximum;
const visibility = (value: unknown): boolean => value === "private" || value === "product";
const unique = (keys: readonly string[]): boolean => new Set(keys).size === keys.length;
const fixed = (ref: CandidateFixedRef): boolean => !!ref && uuid(ref.id) && revision(ref.revision);
const exactKeys = (value: object, keys: readonly string[]): boolean =>
  Object.keys(value).length === keys.length && keys.every(key => Object.hasOwn(value, key));
const sourceKeys = ["artifact_id", "expected_revision", "line", "quote"] as const;

export function candidateSourceKey(ref: CandidateDefinitionReference): string {
  return JSON.stringify([ref.artifact_id.toLowerCase(), ref.expected_revision, ref.line, ref.quote]);
}
export function candidateLinkKey(ref: CandidateFixedRef): string {
  return JSON.stringify([ref.id.toLowerCase(), ref.revision]);
}
export function candidateMappingKey(mapping: CandidateFailurePairMapping): string {
  return JSON.stringify([mapping.failure_id, mapping.run.id.toLowerCase(), mapping.sample_id.toLowerCase(), mapping.item_id]);
}
function validSource(ref: CandidateDefinitionReference): boolean {
  return !!ref && exactKeys(ref, sourceKeys) && uuid(ref.artifact_id) && revision(ref.expected_revision) &&
    revision(ref.line) && text(ref.quote, 4000);
}
function validMapping(mapping: CandidateFailurePairMapping, scope: CandidateFormScope): boolean {
  return !!mapping && exactKeys(mapping, ["failure_id", "run", "sample_id", "sample_revision",
    "actual_configuration_id", "actual_configuration_revision", "item_id", "measurement_id",
    "projection_id", "applicability_sources"]) && text(mapping.failure_id) &&
    scope.failure_ids.includes(mapping.failure_id) && fixed(mapping.run) &&
    exactKeys(mapping.run, ["id", "revision", "kind", "key"]) &&
    mapping.run.kind === "verification_run" && mapping.run.key === null &&
    uuid(mapping.sample_id) && revision(mapping.sample_revision) && uuid(mapping.actual_configuration_id) &&
    revision(mapping.actual_configuration_revision) && text(mapping.item_id, 120) &&
    (mapping.measurement_id === null || uuid(mapping.measurement_id)) &&
    (mapping.projection_id === null || uuid(mapping.projection_id)) &&
    Array.isArray(mapping.applicability_sources) && mapping.applicability_sources.length <= 20 &&
    mapping.applicability_sources.every(validSource) &&
    unique(mapping.applicability_sources.map(candidateSourceKey));
}
export function validCandidateScope(scope: CandidateFormScope | null): scope is CandidateFormScope {
  return !!scope && [scope.tenant_id, scope.product_id, scope.project_id, scope.principal_id,
    scope.issue_id, scope.capa_id].every(uuid) && fixed(scope.current_issue) &&
    (scope.origin_issue === null || fixed(scope.origin_issue)) && visibility(scope.visibility) &&
    Array.isArray(scope.failure_ids) && scope.failure_ids.length > 0 && scope.failure_ids.length <= 10000 &&
    scope.failure_ids.every(value => text(value)) && unique(scope.failure_ids);
}
export function validCandidateMaterials(scope: CandidateFormScope, materials: CandidateMaterials): boolean {
  return !!materials && Array.isArray(materials.links) && Array.isArray(materials.mappings) &&
    Array.isArray(materials.sources) &&
    materials.links.every(choice => !!choice && fixed(choice.ref) && choice.ref.revision === 1 &&
    exactKeys(choice.ref, ["id", "revision"]) && (choice.visibility === null || visibility(choice.visibility))) &&
    unique(materials.links.map(choice => candidateLinkKey(choice.ref))) &&
    materials.mappings.every(choice => !!choice && validMapping(choice.mapping, scope) &&
      (choice.visibility === null || visibility(choice.visibility))) &&
    unique(materials.mappings.map(choice => candidateMappingKey(choice.mapping))) &&
    materials.sources.every(choice => !!choice && validSource(choice.reference) &&
      (choice.visibility === null || visibility(choice.visibility))) &&
    unique(materials.sources.map(choice => candidateSourceKey(choice.reference)));
}

/** Sort object keys only. Arrays and exact source/value/time strings retain their meaning. */
export function candidateFormBasisKey(scope: CandidateFormScope, materials: CandidateMaterials): string {
  const stable = (value: unknown): unknown => Array.isArray(value) ? value.map(stable) :
    value !== null && typeof value === "object" ? Object.fromEntries(
      Object.entries(value).sort(([a], [b]) => a.localeCompare(b)).map(([key, item]) => [key, stable(item)]),
    ) : value;
  return JSON.stringify(stable({ schema_version: candidateFormSchema, scope, materials }));
}

/** Invalid/stale/duplicate choices never turn into a partially guessed payload. */
export function candidatePayload(scope: CandidateFormScope, materials: CandidateMaterials,
  selection: CandidateFormSelection, allowProductVisibility = false): CandidateFormPayload | null {
  if (!validCandidateScope(scope) || !validCandidateMaterials(scope, materials) ||
    !text(selection.reason) || !visibility(selection.visibility) || selection.links.length > 20 ||
    selection.mappings.length > 10000 || selection.sources.length > 20 ||
    !unique(selection.links) || !unique(selection.mappings) || !unique(selection.sources)) return null;
  const links = materials.links.filter(choice => selection.links.includes(candidateLinkKey(choice.ref)));
  const mappings = materials.mappings.filter(choice => selection.mappings.includes(candidateMappingKey(choice.mapping)));
  const sources = materials.sources.filter(choice => selection.sources.includes(candidateSourceKey(choice.reference)));
  if (links.length !== selection.links.length || mappings.length !== selection.mappings.length ||
    sources.length !== selection.sources.length) return null;
  if (selection.visibility === "product" && (allowProductVisibility !== true || scope.visibility !== "product" ||
    [...links, ...mappings, ...sources].some(choice => choice.visibility !== "product"))) return null;
  const cloneSource = (ref: CandidateDefinitionReference): CandidateDefinitionReference => ({
    artifact_id: ref.artifact_id, expected_revision: ref.expected_revision, line: ref.line, quote: ref.quote,
  });
  return {
    issue_id: scope.issue_id, expected_issue_revision: scope.current_issue.revision, capa_id: scope.capa_id,
    remediation_link_refs: links.map(choice => ({ id: choice.ref.id, revision: 1 })),
    mappings: mappings.map(({ mapping }) => ({
      failure_id: mapping.failure_id, run: { id: mapping.run.id, revision: mapping.run.revision,
        kind: "verification_run", key: null }, sample_id: mapping.sample_id, sample_revision: mapping.sample_revision,
      actual_configuration_id: mapping.actual_configuration_id,
      actual_configuration_revision: mapping.actual_configuration_revision, item_id: mapping.item_id,
      measurement_id: mapping.measurement_id, projection_id: mapping.projection_id,
      applicability_sources: mapping.applicability_sources.map(cloneSource),
    })),
    sources: sources.map(choice => cloneSource(choice.reference)), reason: selection.reason,
    visibility: selection.visibility,
  };
}
