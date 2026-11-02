import type { LocatedSource } from "@/lib/original-location";
import { numericValueText } from "./spec-bound-values";
import type { ItemReference, ItemWatermark } from "@/lib/definition-item-editor";
export type DefinitionSource = LocatedSource & { id: string; title: string; content: string; revision: number; visibility: string; status: string };
export type DefinitionReference = { artifact_id: string; expected_revision: number; line: number; quote: string };
export type DefinitionSpec = {
  key: string; parameter: string; value_type: "number" | "range" | "text";
  availability: "known" | "unknown" | "conflicted" | "not_applicable";
  value: string | null; lower: string | null; upper: string | null; text: string | null;
  unit: string | null; tolerance: string | null; test_conditions: string[]; method: string | null;
  acceptance_criterion: string | null; nature: "observed" | "extracted" | "computed" | "inferred" | "decided";
  state: "proposed" | "needs_confirmation"; owner_id: string | null; reason: string;
  sources: DefinitionReference[];
};
export type DefinitionPayload = {
  title: string; purpose: string; visibility: "private" | "category" | "audience";
  parent_definition_id: string | null; expected_parent_revision: number | null;
  use_cases: string[]; requirements: string[]; constraints: string[]; unknowns: string[];
  exclusions: string[]; sources: DefinitionReference[]; specs: DefinitionSpec[]; change_reason: string;
};
export type DefinitionReadSpec = Omit<DefinitionSpec, "value_type" | "state" | "reason"> & {
  value_type: "number" | "range" | "text" | "boolean" | "enum";
  state: "proposed" | "needs_confirmation"; reason: string | null;
  parameter_id: string | null; parameter_version: number | null; condition_note: string | null;
  modality: "must" | "should" | "may" | "prohibited" | "unstated" | null;
  exceptions: Record<string, unknown>[]; applicable_variants: Record<string, unknown>[];
  item_status: "ai_draft" | "confirmed" | "expert_pending" | "unknown";
  source_refs: ItemReference[]; origin: string; writer_id: string; run_id: string | null;
  confirmed_by: string | null; receipt_id: string | null;
};
export type DefinitionRevision = Omit<DefinitionPayload, "expected_parent_revision" | "sources" | "specs"> & {
  id: string; category_id: string; product_id: string; variant_id: string | null;
  owner_id: string; revision: number; status: "draft" | "published"; sealed: boolean; created_at: string;
  specs: DefinitionReadSpec[]; item_versions: ItemWatermark[];
  sources: (DefinitionReference & { title: string; status: string; spec_keys: string[] })[];
  source_status: "current" | "needs_recheck";
  differences: { path: string; before: unknown; after: unknown }[];
};
export type DefinitionList = { items: DefinitionRevision[]; has_more: boolean; unavailable_count: number };
export type DefinitionApi = <T>(path: string, body?: unknown) => Promise<T>;

// Display exact decimal strings without floating-point rounding, including PostgreSQL fixed scale.
export function decimalText(value: string | null | undefined): string {
  if (value === null || value === undefined || value === "") return "未知";
  const match = /^([+-]?)(\d*)(?:\.(\d*))?(?:[eE]([+-]?\d{1,4}))?$/.exec(value.trim());
  if (!match || (!match[2] && !match[3])) return value;
  const [, sign, whole = "", fraction = "", exponent = "0"] = match;
  let digits = whole + fraction;
  let point = whole.length + Number(exponent);
  if (point < 0) { digits = "0".repeat(-point) + digits; point = 0; }
  if (point > digits.length) digits += "0".repeat(point - digits.length);
  const integer = digits.slice(0, point).replace(/^0+(?=\d)/, "") || "0";
  const tail = digits.slice(point).replace(/0+$/, "");
  const text = tail ? `${integer}.${tail}` : integer;
  return text === "0" ? "0" : `${sign === "-" ? "-" : ""}${text}`;
}

export const referenceKey = (source: DefinitionReference) => JSON.stringify([source.artifact_id, source.expected_revision, source.line, source.quote]);
export const plainReference = ({ artifact_id, expected_revision, line, quote }: DefinitionReference): DefinitionReference => ({ artifact_id, expected_revision, line, quote });
// Match Python str.splitlines(), which the authority uses to verify exact line references.
export const sourceLines = (content: string) => content.split(/\r\n|[\n\r\v\f\u001c\u001d\u001e\u0085\u2028\u2029]/);
export const availabilityLabels = { known: "已知", unknown: "未知 / 待确认", conflicted: "存在冲突", not_applicable: "不适用（有依据）" };
export const natureLabels = { observed: "亲历观察", extracted: "原文抽取", computed: "确定性计算", inferred: "推断", decided: "人的取舍" };

export function specificationValue(spec: DefinitionSpec | DefinitionReadSpec): string {
  if (spec.availability !== "known") return availabilityLabels[spec.availability];
  if (spec.value_type === "boolean") return spec.text === "true" ? "是" : spec.text === "false" ? "否" : "未知";
  if (spec.value_type === "text" || spec.value_type === "enum") return spec.text ?? "未知";
  const value = numericValueText(spec.value, spec.lower, spec.upper, decimalText);
  return `${value}${spec.tolerance === null ? "" : ` ± ${decimalText(spec.tolerance)}`} ${spec.unit ?? ""}`;
}

export function isLatestDefinition(item: DefinitionRevision, items: DefinitionRevision[]): boolean {
  return !items.some(other => other.category_id === item.category_id && other.product_id === item.product_id
    && other.variant_id === item.variant_id && other.revision > item.revision);
}
