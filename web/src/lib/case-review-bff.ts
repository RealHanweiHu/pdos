import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";
export async function forwardCaseReview(request: Request, caseId: string, operation: "reviews" | "review-policies" | "review-materials" | "initial-plans", reviewId?: string, action?: "actions" | "signoffs" | "finalize") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  if (![caseId, ...(reviewId ? [reviewId] : [])].every((id) => /^[0-9a-f-]{36}$/i.test(id))) return sessionError(400, "INVALID_REQUEST", "Invalid object identifier");
  try {
    const target = operation === "reviews" && request.method === "GET" ? new URL(request.url).searchParams.get("review_id") : null;
    if (target && !/^[0-9a-f-]{36}$/i.test(target)) return sessionError(400, "INVALID_REQUEST", "Invalid review identifier");
    const query = operation === "initial-plans" ? `?options=${new URL(request.url).searchParams.get("options") === "true"}` : operation === "review-materials" ? `?${new URLSearchParams({ kind: new URL(request.url).searchParams.get("kind") ?? "specification", q: new URL(request.url).searchParams.get("q") ?? "" })}` : target ? `?review_id=${encodeURIComponent(target)}` : "";
    const body = request.method === "POST" ? JSON.stringify(await readBoundedJson(request)) : undefined;
    return forwardJson(await pdosApiFetch(`/api/development-cases/${caseId}/${operation}${reviewId ? `/${reviewId}/${action}` : ""}${query}`, { method: request.method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body }));
  } catch (error) {
    return sessionError(error instanceof InvalidRequestBodyError ? 400 : 503, "CASE_REVIEW_UNAVAILABLE", "Review request could not be completed");
  }
}
