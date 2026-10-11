import type { DefinitionPayload, DefinitionReference, DefinitionSpec } from "./product-view";

export type VariantOverrides = Partial<Pick<DefinitionPayload, "title" | "purpose" | "use_cases" | "requirements" | "constraints" | "unknowns" | "exclusions">> & { specs?: Omit<DefinitionSpec, "owner_id" | "state">[] };
export type VariantRevision = {
  id: string; revision: number; status: "draft"; visibility: "private" | "category" | "audience"; owner_id: string;
  parent_definition_id: string; parent_revision: number; previous_revision_id: string | null;
  effective_definition: DefinitionPayload; overrides: VariantOverrides; applicability: string[];
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
export function variantSpec(spec: DefinitionSpec): Omit<DefinitionSpec, "owner_id" | "state"> {
  const value: Partial<DefinitionSpec> = { ...spec };
  delete value.owner_id;
  delete value.state;
  return value as Omit<DefinitionSpec, "owner_id" | "state">;
}
