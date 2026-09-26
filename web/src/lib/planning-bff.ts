import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";
export async function planningForward(request: Request, candidateId?: string, operation: "candidate" | "scenarios" | "responsibilities" | "reviews" = "scenarios", reviewId?: string) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  if (candidateId && !/^[0-9a-f-]{36}$/i.test(candidateId)) return sessionError(400, "INVALID_REQUEST", "Invalid candidate identifier");
  if (reviewId && !/^[0-9a-f-]{36}$/i.test(reviewId)) return sessionError(400, "INVALID_REQUEST", "Invalid review identifier");
  try {
    const body = request.method === "POST" ? JSON.stringify(await readBoundedJson(request)) : undefined;
    return forwardJson(await pdosApiFetch(candidateId ? `/api/initial-plans/${candidateId}${operation === "candidate" ? "" : `/${operation}${reviewId ? `/${reviewId}` : ""}`}` : "/api/planning/calendars", { method: request.method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body }));
  } catch (error) { return sessionError(error instanceof InvalidRequestBodyError ? 400 : 503, "PLANNING_UNAVAILABLE", "Planning request could not be completed"); }
}
