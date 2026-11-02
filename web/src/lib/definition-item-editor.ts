/** Business-only projection for the shared server SpecItem/Reference contract. */
import { numericShapeProblem, numericValueText } from "./spec-bound-values";

export type ItemReference = {
  type: "human" | "artifact" | "original" | "snapshot" | "knowledge" | "parameter" | "definition" | "claim";
  id: string; version: number; line?: number | null; quote?: string | null; statement?: string | null;
};
export type ItemContent = {
  key: string; parameter: string; parameter_id: string | null; parameter_version: number | null;
  value_type: "number" | "range" | "text" | "boolean" | "enum";
  value: string | null; lower: string | null; upper: string | null; tolerance: string | null;
  text_value: string | null; unit: string | null; condition_note: string | null;
  test_conditions: string[]; verification_method: string | null; acceptance_criterion: string | null;
  modality: "must" | "should" | "may" | "prohibited" | "unstated" | null;
  exceptions: Record<string, unknown>[]; applicable_variants: Record<string, unknown>[];
  nature: "observed" | "extracted" | "computed" | "inferred" | "decided";
  availability: "known" | "unknown" | "conflicted" | "not_applicable";
  item_status: "ai_draft" | "confirmed" | "expert_pending" | "unknown";
  owner_id: string | null; reason: string | null;
};
export type StoredItem = Partial<Omit<ItemContent, "value" | "lower" | "upper" | "tolerance">> & {
  key: string; parameter: string; value?: string | number | null; lower?: string | number | null;
  upper?: string | number | null; tolerance?: string | number | null;
  text?: string | null; method?: string | null; source_refs?: ItemReference[];
  sources?: { artifact_id: string; expected_revision: number; line: number; quote: string }[];
};
export type ItemWatermark = { item_id: string; item_version: number; row_id: string; key: string };
export const emptyItem = (): ItemContent => ({
  key: "", parameter: "", parameter_id: null, parameter_version: null, value_type: "number",
  value: null, lower: null, upper: null, tolerance: null, text_value: null, unit: null,
  condition_note: null, test_conditions: [], verification_method: null, acceptance_criterion: null,
  modality: null, exceptions: [], applicable_variants: [], nature: "decided", availability: "unknown",
  item_status: "unknown", owner_id: null, reason: null,
});
const decimal = (value: string | number | null | undefined) => value == null ? null : String(value);
export function projectItem(row: StoredItem): ItemContent {
  return {
    key: row.key, parameter: row.parameter, parameter_id: row.parameter_id ?? null,
    parameter_version: row.parameter_version ?? null, value_type: row.value_type ?? "number",
    value: decimal(row.value), lower: decimal(row.lower), upper: decimal(row.upper), tolerance: decimal(row.tolerance),
    text_value: row.text_value ?? row.text ?? null, unit: row.unit ?? null, condition_note: row.condition_note ?? null,
    test_conditions: [...row.test_conditions ?? []], verification_method: row.verification_method ?? row.method ?? null,
    acceptance_criterion: row.acceptance_criterion ?? null, modality: row.modality ?? null,
    exceptions: structuredClone(row.exceptions ?? []), applicable_variants: structuredClone(row.applicable_variants ?? []),
    nature: row.nature ?? "decided", availability: row.availability ?? "unknown", item_status: row.item_status ?? "unknown",
    owner_id: row.owner_id ?? null, reason: row.reason ?? null,
  };
}
export function projectReference(ref: ItemReference): ItemReference {
  return { type: ref.type, id: ref.id, version: ref.version, line: ref.line ?? null, quote: ref.quote ?? null, statement: ref.statement ?? null };
}
export function itemReferences(row: StoredItem): ItemReference[] {
  const refs = [...row.source_refs ?? [], ...(row.sources ?? []).map(ref => ({ type: "artifact" as const,
    id: ref.artifact_id, version: ref.expected_revision, line: ref.line, quote: ref.quote }))];
  return [...new Map(refs.map(ref => { const value = projectReference(ref); return [JSON.stringify(value), value]; })).values()];
}
export function itemSummary(content: ItemContent): string {
  if (content.availability !== "known") return ({ unknown: "未知", conflicted: "存在冲突", not_applicable: "不适用" })[content.availability];
  if (content.value_type === "boolean") return content.text_value === "true" ? "是" : content.text_value === "false" ? "否" : "未知";
  if (["text", "enum"].includes(content.value_type)) return content.text_value ?? "未知";
  const value = numericValueText(content.value, content.lower, content.upper);
  return `${value}${content.unit ? ` ${content.unit}` : ""}`;
}
export function itemProblem(content: ItemContent, refs: ItemReference[]): string | null {
  if (!content.key.trim() || !content.parameter.trim()) return "请填写条目标识和参数名称。";
  if (content.item_status === "confirmed" && !refs.length) return "确认条目前，请明确选择来源或填写本人具名陈述。";
  if (content.availability === "not_applicable" && !content.reason?.trim()) return "请说明不适用的原因。";
  if (content.availability === "known") {
    if (["number", "range"].includes(content.value_type)) {
      const problem = numericShapeProblem(content.value_type, content.value, content.lower, content.upper, content.text_value);
      if (problem) return problem;
    }
    if (["text", "enum", "boolean"].includes(content.value_type) && content.text_value == null) return "请填写或选择实际值。";
  }
  return null;
}
