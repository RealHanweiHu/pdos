export type SimilarHistoryCard = {
  kind: "issue" | "capa" | "change"; title: string; object_id: string; source_id: string; source_revision: number; is_current: boolean;
  status: string; category: string; project: string; reason: string; root_cause: string; containment: string[]; capa_actions: string[]; verification: string;
  differences: { field: string; status: "same" | "different" | "unknown"; current: string; candidate: string }[];
  can_prepare_merge: boolean; object_url: string | null; object_label: string;
};
type SimilarHistoryScope = { title: string; category_id: string; product_id: string; project_id: string };
export type SimilarHistoryAnchor = SimilarHistoryScope & (
  { issue_id: string; version_id: string; revision: number; kind?: "issue" }
  | { kind: "change"; change_id: string; version_id: string; revision: number }
);
export type SimilarHistoryView = {
  version: "similar-history/v1"; as_of: string; ranking_version: string; notice: string;
  anchor: SimilarHistoryAnchor;
  items: SimilarHistoryCard[]; coverage: { status: "current" | "partial"; notice: string | null };
};
export type SimilarHistorySuggestions = Omit<SimilarHistoryView, "anchor"> & {
  anchor: Omit<SimilarHistoryScope, "project_id"> & { kind: "issue_draft" | "change_draft"; project_id: string | null };
};
export type SimilarHistoryAction = "opened" | "not_relevant" | "merge_prepared";
export type SimilarHistoryFeedback = { version_id: string; candidate_kind: SimilarHistoryCard["kind"]; candidate_source_id: string; candidate_revision: number; action: SimilarHistoryAction; request_key: string };
export const uuid = (value: unknown): value is string => typeof value === "string" && /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/i.test(value);
export const similarHistoryPath = (productId: string, objectId: string, kind: "issue" | "change" = "issue") => `v1/products/${productId}/${kind === "change" ? "change-execution" : "quality-issues"}/${objectId}/similar-history`;
export function similarHistorySuggestionsPath(productId: string, kind: "issue" | "change", title: string, projectId?: string) {
  const query = new URLSearchParams({ kind, title: title.trim() });
  if (projectId) query.set("project_id", projectId);
  return `v1/products/${productId}/similar-history?${query}`;
}
export function validSimilarFeedback(value: unknown): value is SimilarHistoryFeedback {
  if (!value || typeof value !== "object" || Array.isArray(value)) return false;
  const body = value as Record<string, unknown>;
  return Object.keys(body).length === 6 && Object.keys(body).every(key => ["version_id", "candidate_kind", "candidate_source_id", "candidate_revision", "action", "request_key"].includes(key))
    && uuid(body.version_id) && uuid(body.candidate_source_id) && uuid(body.request_key)
    && typeof body.candidate_kind === "string" && ["issue", "capa", "change"].includes(body.candidate_kind)
    && typeof body.action === "string" && ["opened", "not_relevant", "merge_prepared"].includes(body.action)
    && typeof body.candidate_revision === "number" && Number.isSafeInteger(body.candidate_revision) && body.candidate_revision > 0 && body.candidate_revision <= 2147483647;
}
