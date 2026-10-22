export type Location =
  | { kind: "line"; line: number; page?: null; sheet?: null; cell?: null }
  | { kind: "page"; page: number; line?: null; sheet?: null; cell?: null }
  | { kind: "cell"; sheet: string; cell: string; line?: null; page?: null };

export type Citation = {
  artifact_id: string; expected_revision: number; content_hash: string;
  derived_line: number; quote: string; location: Location;
  original_id?: string | null; original_version?: string | null; original_hash?: string | null;
};
export type SpecValue = {
  parameter: string; value_type: "number" | "range" | "text";
  value: string | null; lower: string | null; upper: string | null; text: string | null;
  unit: string | null; tolerance: string | null; test_conditions: string[];
  method: string | null; applicability: string | null; acceptance_criterion: string | null;
};
export type Observation = {
  id: string; key: string; kind: "spec" | "requirement" | "constraint" | "note";
  origin: "human_observation" | "ai_extraction" | "translation" | "customer_input";
  raw_text: string; statement: string; spec: SpecValue | null; sources: Citation[];
  accepted_requirement_id?: string | null;
};
export type StoredObservation = {
  observation: Observation;
  verification: { status: "verified" | "pending"; reason: string; accepted_requirement: boolean };
};
export type PackageItem = { category: string; source: Citation };
export type Research = {
  id: string; tenant_id: string; owner_id: string; audience: "private" | "category" | "audience";
  scope_id: string; revision: number; title: string; mode: "research" | "oem";
  questions: string[]; use_cases: string[]; items: PackageItem[]; observations: StoredObservation[];
};
export type CandidateRequest = {
  title: string;
  selections: { key: string; observation_id: string | null; reason: string }[];
  partial_reason: string | null; change_reason: string;
  parent_definition_id?: string | null; expected_parent_revision?: number | null;
};
export type DefinitionReference = { artifact_id: string; expected_revision: number; line: number; quote: string };
export type DefinitionSpec = Omit<SpecValue, "applicability"> & {
  key: string; availability: "known" | "unknown" | "conflicted" | "not_applicable";
  nature: "observed" | "extracted" | "computed" | "inferred" | "decided";
  state: "proposed" | "needs_confirmation"; owner_id: string | null;
  reason: string; sources: DefinitionReference[];
};
export type DefinitionCandidate = {
  research_id: string; research_revision: number; product_id: string; expected_product_revision: number;
  payload: {
    title: string; purpose: string; visibility: "private" | "category" | "audience";
    use_cases: string[]; requirements: string[]; constraints: string[]; unknowns: string[];
    exclusions: string[]; specs: DefinitionSpec[]; sources: DefinitionReference[];
    parent_definition_id: string | null; expected_parent_revision: number | null; change_reason: string;
  };
  provenance: {
    key: string; observations: StoredObservation[]; selected_id: string | null;
    actor_id: string; reason: string; maturity: "candidate" | "accepted_requirement";
  }[];
  conflicts: { key: string; observation_ids: string[]; reasons: string[] }[];
  missing_categories: string[]; omitted_keys: string[]; digest: string; effect: string;
};
export type SourceOption = { id: string; label: string; category: string; citation: Citation };
export type Context = {
  scopeLabel: string | null; productLabel: string | null; purpose: string | null;
  actorLabel: string; requiredCategories: string[];
  readiness: { start: boolean; import: boolean; preview: boolean };
  unavailableReason?: string;
};
export type Callbacks = {
  onStart?: (payload: { title: string; mode: "research" | "oem"; questions: string[]; use_cases: string[] }) => Promise<void>;
  onImport?: (researchId: string, expectedRevision: number, payload: { items: PackageItem[]; observations: Observation[] }) => Promise<void>;
  /** Opens the host's existing preview/confirmation; this component never consumes it. */
  onPreview?: (researchId: string, expectedRevision: number, request: CandidateRequest) => Promise<void>;
};

export function grouped(research: Research) {
  const result = new Map<string, StoredObservation[]>();
  for (const entry of research.observations) {
    const key = entry.observation.key;
    result.set(key, [...(result.get(key) ?? []), entry]);
  }
  return [...result.entries()].sort(([a], [b]) => a.localeCompare(b));
}
export function locationLabel(citation: Citation) {
  const location = citation.location;
  if (location.kind === "cell") return `${location.sheet} · ${location.cell}`;
  if (location.kind === "page") return `原件第 ${location.page} 页`;
  return `原文第 ${location.line} 行`;
}
export function rawSpec(value: SpecValue) {
  const main = value.value_type === "number" ? value.value : value.value_type === "range"
    ? `${value.lower ?? "未知"} ～ ${value.upper ?? "未知"}` : value.text;
  return `${main ?? "未知"} ${value.unit ?? "单位未知"}`;
}
export function selectionRequest(
  title: string, changeReason: string, partialReason: string,
  choices: Record<string, { included: boolean; observationId: string | null; reason: string }>,
): CandidateRequest {
  const selections = Object.entries(choices).filter(([, value]) => value.included)
    .map(([key, value]) => ({ key, observation_id: value.observationId, reason: value.reason }));
  if (title.trim().length < 2 || changeReason.trim().length < 3 || !selections.length)
    throw new Error("请填写定义标题、变更原因并选择至少一个组。");
  if (selections.some(value => value.reason.trim().length < 3))
    throw new Error("每个所选组都需要具名选择或待裁决的原因。");
  return { title, change_reason: changeReason, partial_reason: partialReason.trim() || null, selections };
}
