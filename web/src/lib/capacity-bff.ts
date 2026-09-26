import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

export async function resourceCapacityForward(request: Request, endpoint: "resources" | "capacities" | "checks" | "resource-priorities" | "portfolio-policies" | "portfolio-options" | "portfolio-comparisons" | "portfolio-preview" | "portfolio-selections" | "portfolio-selection-preview" | "portfolio-selection-decisions" | "portfolio-execution-preparations" | "portfolio-application-preview" | "portfolio-applications" | "portfolio-explanation-context" | "portfolio-explanation-runs" | "portfolio-health-policies" | "portfolio-health" | "portfolio-control-queue" | "portfolio-progress" | "executive-brief-context" | "executive-brief-history" | "executive-brief-runs" | "portfolio-progress-nodes" | "portfolio-forecast-history" | "portfolio-milestones" | "milestone-designations" | "milestone-designation-history" | "portfolio-milestone-history" | "portfolio-health-overview" | "portfolio-escalation-options" | "portfolio-escalation-preview" | "portfolio-escalation-requests" | "portfolio-escalation-replies" | "portfolio-escalations" | "portfolio-escalation-history" | "portfolio-materials" | "portfolio-material-detail" | "portfolio-opportunities" | "portfolio-case-reviews" | "portfolio-resources" | "portfolio-suppliers" | "portfolio-supplier-detail" | "portfolio-resource-detail", candidateId?: string, scenarioId?: string) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  if (endpoint === "checks" && [candidateId, scenarioId].some((id) => !id || !/^[0-9a-f-]{36}$/i.test(id))) return sessionError(400, "INVALID_REQUEST", "Invalid planning identifier");
  const path = endpoint === "checks" ? `/api/initial-plans/${candidateId}/scenarios/${scenarioId}/capacity-checks` : `/api/planning/${endpoint}${new URL(request.url).search}`;
  try {
    const body = request.method === "POST" ? JSON.stringify(await readBoundedJson(request)) : undefined;
    return forwardJson(await pdosApiFetch(path, { method: request.method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body }));
  } catch (error) {
    return sessionError(error instanceof InvalidRequestBodyError ? 400 : 503, "CAPACITY_UNAVAILABLE", "Resource capacity request could not be completed");
  }
}
