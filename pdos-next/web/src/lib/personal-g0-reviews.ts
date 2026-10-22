export type PersonalG0Review = {
  proposal_id: string; title: string; proposal_revision: number; status: "in_review";
  category: { id: string; name: string }; owner: { id: string; name?: string | null }; reviewer_id: string;
  submission: { id: string; revision: number; submitted_at: string; document_digest: string };
};
export type PersonalG0Page = {
  version: "personal-g0-reviews/v1"; principal_id: string; as_of: string;
  total_pending: number; items: PersonalG0Review[]; next_cursor: string | null;
};

export function personalG0Path(cursor: string | null = null) {
  return `v1/personal/g0-reviews?page_size=50${cursor ? `&cursor=${encodeURIComponent(cursor)}` : ""}`;
}
export function personalG0Href(review: PersonalG0Review) {
  return `/categories/${encodeURIComponent(review.category.id)}/proposals/${encodeURIComponent(review.proposal_id)}`;
}

const record = (value: unknown): value is Record<string, unknown> => value !== null && typeof value === "object" && !Array.isArray(value);
const text = (value: unknown): value is string => typeof value === "string" && value.length > 0;
const count = (value: unknown) => typeof value === "number" && Number.isSafeInteger(value) && value >= 0;
const revision = (value: unknown) => count(value) && Number(value) > 0;
const timestamp = (value: unknown) => text(value) && Number.isFinite(Date.parse(value));

/** Metadata only; the original proposal page owns every named G0 action. */
export function isPersonalG0Page(value: unknown, principalId: string): value is PersonalG0Page {
  return record(value) && value.version === "personal-g0-reviews/v1" && value.principal_id === principalId && timestamp(value.as_of)
    && count(value.total_pending) && (value.next_cursor === null || text(value.next_cursor)) && Array.isArray(value.items)
    && value.items.every(item => record(item)
      && text(item.proposal_id) && typeof item.title === "string" && revision(item.proposal_revision) && item.status === "in_review" && item.reviewer_id === principalId
      && record(item.category) && text(item.category.id) && typeof item.category.name === "string"
      && record(item.owner) && text(item.owner.id) && (item.owner.name === undefined || item.owner.name === null || typeof item.owner.name === "string")
      && record(item.submission) && text(item.submission.id) && revision(item.submission.revision) && timestamp(item.submission.submitted_at) && text(item.submission.document_digest));
}

/** A proposal has one current submission; repeated metadata replaces its card. */
export function mergePersonalG0(previous: readonly PersonalG0Review[], incoming: readonly PersonalG0Review[]) {
  const byProposal = new Map(previous.map(item => [item.proposal_id, item]));
  for (const item of incoming) byProposal.set(item.proposal_id, item);
  return [...byProposal.values()];
}
