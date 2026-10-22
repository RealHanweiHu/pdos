export type G0Decision = {
  id: string; outcome: string; rationale: string; receipt_id: string | null;
  decided_by: string; decided_at: string;
  product_id: string | null; variant_id: string | null; definition_id: string | null; project_id: string | null;
};
type Person = { id: string; name: string | null };
export type G0Handoff = {
  category_id: string; proposal_id: string;
  decision: { id: string; outcome: "approved"; receipt_id: string; signer: Person; decided_at: string; rationale: string };
  identity: { kind: "new_product" | "new_variant"; product: { id: string; name: string }; variant: { id: string; name: string; kind: string } | null };
  definition: { id: string; product_id: string; variant_id: string | null; title: string; revision: number; sealed: boolean; status: string };
  project: { id: string; name: string; product_id: string; owner: Person; definition_id: string; definition_revision: number };
  open_items: { id: string; project_id: string; g0_decision_id: string; kind: "task" | "risk"; title: string; owner: Person; due_date: string; status: string }[];
};
const record = (value: unknown): value is Record<string, unknown> => !!value && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const person = (value: unknown): value is Person => record(value) && text(value.id) && (value.name === null || typeof value.name === "string");
export function isG0Handoff(value: unknown, categoryId: string, proposalId: string, expected: G0Decision): value is G0Handoff {
  if (expected.outcome !== "approved" || ![expected.id, expected.receipt_id, expected.product_id,
    expected.project_id, expected.definition_id, expected.decided_by, expected.decided_at].every(text)) return false;
  if (!record(value) || value.category_id !== categoryId || value.proposal_id !== proposalId || !record(value.decision)
    || value.decision.id !== expected.id || value.decision.outcome !== "approved" || value.decision.receipt_id !== expected.receipt_id
    || !text(value.decision.receipt_id) || !person(value.decision.signer) || value.decision.signer.id !== expected.decided_by
    || value.decision.decided_at !== expected.decided_at || !text(value.decision.rationale)
    || !record(value.identity) || !record(value.identity.product) || value.identity.product.id !== expected.product_id || !text(value.identity.product.name)
    || !record(value.definition) || value.definition.id !== expected.definition_id || value.definition.product_id !== expected.product_id
    || value.definition.variant_id !== expected.variant_id || value.definition.revision !== 1 || value.definition.sealed !== true || !text(value.definition.title)
    || !record(value.project) || value.project.id !== expected.project_id || value.project.product_id !== expected.product_id
    || value.project.definition_id !== expected.definition_id || value.project.definition_revision !== 1 || !text(value.project.name) || !person(value.project.owner)
    || !Array.isArray(value.open_items)) return false;
  if (expected.variant_id ? value.identity.kind !== "new_variant" || !record(value.identity.variant)
    || value.identity.variant.id !== expected.variant_id || !text(value.identity.variant.name) || !["customer", "region", "configuration"].includes(String(value.identity.variant.kind))
    : value.identity.kind !== "new_product" || value.identity.variant !== null) return false;
  return value.open_items.every(item => record(item) && text(item.id) && item.project_id === expected.project_id
    && item.g0_decision_id === expected.id && ["task", "risk"].includes(String(item.kind)) && text(item.title)
    && person(item.owner) && typeof item.due_date === "string" && /^\d{4}-\d{2}-\d{2}$/.test(item.due_date) && text(item.status));
}
export function g0ProjectHref(categoryId: string, projectId: string) {
  return `/?${new URLSearchParams({ area: "cockpit", category: categoryId, project: projectId })}`;
}
