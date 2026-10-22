import { isLatestDefinition, plainReference, type DefinitionPayload, type DefinitionReadSpec, type DefinitionReference, type DefinitionRevision, type DefinitionSpec } from "./product-view";

export type VariantOverrides = Partial<Pick<DefinitionPayload, "title" | "purpose" | "use_cases" | "requirements" | "constraints" | "unknowns" | "exclusions">> & { specs?: Omit<DefinitionSpec, "owner_id" | "state">[] };
export type VariantRevision = {
  id: string; definition_id: string | null; revision: number; status: "draft"; visibility: "private" | "category" | "audience"; owner_id: string;
  parent_definition_id: string; parent_revision: number; previous_revision_id: string | null;
  effective_definition: Omit<DefinitionPayload, "specs"> & { specs: (DefinitionSpec | DefinitionReadSpec)[] }; overrides: VariantOverrides; applicability: string[];
  sources: DefinitionReference[]; choices: RebaseChoice[]; reason: string; created_at: string;
  source_status: "current" | "needs_recheck";
};
export type Variant = { id: string; name: string; kind: "customer" | "region" | "configuration"; visibility: "private" | "category" | "audience"; owner_id: string; revisions: VariantRevision[] };
export type VariantList = { items: Variant[]; has_more: boolean; unavailable_count: number };
export type ThreeWayChange = { path: string; old_parent: unknown; new_parent: unknown; current_child: unknown; category: "parent_only" | "child_only" | "same_change" | "conflict" };
export type VariantComparison = { variant_id: string; name: string; variant_revision: number; old_parent_id: string; old_parent_revision: number; new_parent_id: string; new_parent_revision: number; changes: ThreeWayChange[]; conflict_count: number; sources: DefinitionReference[]; required_source_read_set: { artifact_id: string; expected_revision: number }[] };
export type RebaseChoice = { path: string; selection: "parent" | "child"; reason: string };
export type DerivePayload = { name: string; kind: Variant["kind"]; applicability: string[]; parent_definition_id: string; expected_parent_revision: number; visibility: "private" | "category" | "audience"; overrides: VariantOverrides; sources: DefinitionReference[]; reason: string; confirmation_token?: string };
export type RebasePayload = { variant_id: string; expected_variant_revision: number; parent_definition_id: string; expected_parent_revision: number; choices: RebaseChoice[]; sources: DefinitionReference[]; reason: string; confirmation_token?: string };
export type VariantCommand = { command_id: string; idempotency_key: string; operation: "product.variant.derive" | "product.variant.rebase"; product_id: string; expected_revision: number; source_read_set: { artifact_id: string; expected_revision: number }[]; payload: DerivePayload | RebasePayload };
export type VariantPreview = { confirmation_token: string; parent_definition_id: string; parent_revision: number; variant_revision: number | null; visibility: string; applicability: string[]; before: DefinitionPayload | null; after: DefinitionPayload; changes: ThreeWayChange[]; reason: string; effect: string };
export const kindLabels = { customer: "客户范围", region: "地区范围", configuration: "配置范围" };
export const changeLabels = { parent_only: "只有父版变化", child_only: "只有派生覆盖", same_change: "父版与派生相同变化", conflict: "双方不同变化，需选择" };
export const fieldLabels: Record<string, string> = { title: "名称", purpose: "用途", use_cases: "使用场景", requirements: "要求", constraints: "约束", unknowns: "未知项", exclusions: "排除范围" };
const modernGuidance = "此定义包含完整规格或固定来源，不能使用旧版派生覆盖。请在定义条目中续版修订，或通过立项提案办理派生。";
export function nativeSpecBlocker(spec: DefinitionSpec | DefinitionReadSpec): string | null {
  if (!["number", "range", "text"].includes(spec.value_type)) return modernGuidance;
  const fields = spec as unknown as Record<string, unknown>;
  const defaults: Record<string, unknown> = { parameter_id: null, parameter_version: null, item_status: "unknown", condition_note: null,
    modality: null, exceptions: [], applicable_variants: [], source_refs: [], origin: "human", writer_id: null,
    run_id: null, confirmed_by: null, receipt_id: null, prepared_candidate_id: null };
  for (const [key, value] of Object.entries(defaults)) {
    const actual = fields[key];
    if (actual !== undefined && actual !== null && JSON.stringify(actual) !== JSON.stringify(value)) return modernGuidance;
  }
  if (!spec.reason || !spec.sources.length) return modernGuidance;
  return null;
}
export function nativeParentBlocker(parent: DefinitionRevision | undefined, definitions: DefinitionRevision[], product: { id: string; category_id?: string }): string | null {
  if (!parent || parent.product_id !== product.id || (product.category_id && parent.category_id !== product.category_id)) return "请先选择当前型号内可读的固定定义。";
  if (parent.sealed || parent.status !== "draft") return "已封存或已发布的定义保留只读比较；请在定义条目中续版，或通过立项提案办理派生。";
  if (!isLatestDefinition(parent, definitions)) return "请先选择同一派生范围的最新定义版本。";
  if (parent.source_status !== "current") return "固定来源待重新核对，暂不能办理派生。";
  return parent.specs.map(nativeSpecBlocker).find(Boolean) ?? null;
}
export function nativeRebaseBlocker(variant: Variant | undefined, parent: DefinitionRevision | undefined, definitions: DefinitionRevision[], product: { id: string; category_id?: string }): string | null {
  const current = variant?.revisions.reduce<VariantRevision | undefined>((latest, row) => !latest || row.revision > latest.revision ? row : latest, undefined);
  if (!current) return "请先选择实际派生版本。";
  if (current.definition_id) return "G0 立项派生仅在此查看三方差异；后续修改请通过项目内变更办理。";
  const parentIssue = nativeParentBlocker(parent, definitions, product);
  if (parentIssue) return parentIssue;
  if (parent!.revision <= current.parent_revision) return "比较可以查看同版；保存重核须选择较新的父定义。";
  const old = definitions.find(item => item.id === current.parent_definition_id);
  if (!old || old.product_id !== parent!.product_id || old.category_id !== parent!.category_id || old.variant_id !== parent!.variant_id) return "父定义谱系尚未核对，当前仅供比较。";
  if (old.sealed || old.status !== "draft") return "固定旧父已封存或发布，当前仅供比较；后续修改请通过立项提案或项目内变更办理。";
  if (old.source_status !== "current" || current.source_status === "needs_recheck") return "原派生来源待核对，当前不能保存重核。";
  return [...old.specs, ...current.effective_definition.specs].map(nativeSpecBlocker).find(Boolean) ?? null;
}
export function variantSpec(spec: DefinitionSpec | DefinitionReadSpec): Omit<DefinitionSpec, "owner_id" | "state"> {
  const issue = nativeSpecBlocker(spec);
  if (issue) throw new Error(issue);
  // NativeOverride accepts only these legacy business fields, never read-side provenance.
  return { key: spec.key, parameter: spec.parameter, value_type: spec.value_type as DefinitionSpec["value_type"],
    availability: spec.availability, value: spec.value, lower: spec.lower, upper: spec.upper, text: spec.text,
    unit: spec.unit, tolerance: spec.tolerance, test_conditions: [...spec.test_conditions], method: spec.method,
    acceptance_criterion: spec.acceptance_criterion, nature: spec.nature, reason: spec.reason!, sources: spec.sources.map(plainReference) };
}
