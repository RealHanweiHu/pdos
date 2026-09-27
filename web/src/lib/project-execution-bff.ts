import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

export async function executionForward(request: Request, projectId: string, operation: "list" | "policies" | "requests" | "application" | "readiness" | "forecasts" | "forecast-capacity" | "commitments" | "commitment-policies" | "actual-corrections" | "nodes" | "scenarios" | "scenario-capacity" | "resource-schedules" | "resource-schedule-preparations" | "resource-reallocations" | "resource-reallocation-options" | "resource-reallocation-preview" | "resource-reallocation-decisions" | "resource-reallocation-applications" | "baseline-changes" | "baseline-policies" | "baseline-application" | "milestones" | "certifications" | "recertification" | "source-actual-corrections" | "cross-project-dependencies" | "cross-project-application" | "id-design" | "id-design-feedback" | "id-design-decision" | "id-freezes" | "id-freeze-decision" | "id-freeze-application" | "id-handoffs" | "id-handoff-response" | "id-revision-context" | "id-change-decision" | "id-change-branch" | "id-design-activation" | "id-checkpoints" | "id-responsibility", executionId?: string) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  if ([projectId, ...(executionId ? [executionId] : [])].some((id) => !/^[0-9a-f-]{36}$/i.test(id))) return sessionError(400, "INVALID_REQUEST", "Invalid execution identifier");
  try {
    const body = request.method === "POST" ? JSON.stringify(await readBoundedJson(request)) : undefined;
    const suffix = operation === "id-responsibility" ? `/id-design/revisions/${executionId}/responsibility` : operation === "id-checkpoints" ? `/id-design/checkpoints${executionId ? `/${executionId}` : ""}` : operation === "id-design-activation" ? `/id-design/freezes/${executionId}/activation` : operation === "id-change-branch" ? `/id-design/changes/${executionId}/revision` : operation === "id-change-decision" ? `/id-design/changes/${executionId}` : operation === "id-revision-context" ? `/id-design/revisions/${executionId}` : operation === "id-handoffs" ? "/id-design/handoffs" : operation === "id-handoff-response" ? `/id-design/handoffs/items/${executionId}` : operation === "id-freezes" ? "/id-design/freezes" : operation === "id-freeze-decision" ? `/id-design/freezes/${executionId}/decisions` : operation === "id-freeze-application" ? `/id-design/freezes/${executionId}/application` : operation === "id-design-feedback" ? `/id-design/revisions/${executionId}/feedback` : operation === "id-design-decision" ? `/id-design/feedback/${executionId}` : operation === "cross-project-application" ? `/cross-project-dependencies/${executionId}/application` : operation === "recertification" ? `/certifications/${executionId}/recertification` : operation === "baseline-application" ? `/baseline-changes/${executionId}/application` : operation === "baseline-policies" ? "/baseline-changes/policies" : operation === "resource-schedules" ? `/scenarios/${executionId}/resource-schedules` : operation === "scenario-capacity" ? `/scenarios/${executionId}/capacity-checks` : operation === "commitment-policies" ? "/commitments/policies" : operation === "forecast-capacity" ? `/forecasts/${executionId}/capacity-checks` : operation === "list" ? "" : `/${operation}${executionId ? `/${executionId}` : ""}`;
    const scheduleCursor = operation === "resource-schedules" && request.method === "GET" ? new URL(request.url).searchParams.get("before") : null;
    if (scheduleCursor !== null && !/^[0-9a-f-]{36}$/i.test(scheduleCursor)) return sessionError(400, "INVALID_CURSOR", "Invalid schedule cursor");
    const reallocationQuery = (operation === "resource-reallocations" || operation === "resource-reallocation-options") && request.method === "GET" ? new URL(request.url).search : "";
    const before = operation === "id-responsibility" && request.method === "GET" ? new URL(request.url).searchParams.get("before_id") : null;
    if (before !== null && !/^[1-9][0-9]{0,18}$/.test(before)) return sessionError(400, "INVALID_CURSOR", "Invalid responsibility cursor");
    const target = request.method === "GET" && (operation === "list" || operation === "baseline-changes" || operation === "scenarios") ? new URL(request.url).searchParams.get("target_id") : null;
    if (target !== null && !/^[0-9a-f-]{36}$/i.test(target)) return sessionError(400, "INVALID_TARGET", "Invalid application reference");
    const forecast = request.method === "GET" && operation === "forecasts" ? new URL(request.url).searchParams.get("record_id") : null;
    if (forecast !== null && !/^[0-9a-f-]{36}$/i.test(forecast)) return sessionError(400, "INVALID_FORECAST", "Invalid forecast reference");
    const forecastQuery = new URLSearchParams();
    if (request.method === "GET" && operation === "forecasts") {
      const params = new URL(request.url).searchParams;
      const cursor = params.get("before");
      const limit = params.get("limit");
      if (cursor !== null && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(cursor)) return sessionError(400, "INVALID_CURSOR", "Invalid forecast cursor");
      if (limit !== null && (!/^[1-9][0-9]?$/.test(limit) || Number(limit) > 50)) return sessionError(400, "INVALID_LIMIT", "Invalid forecast page size");
      if (forecast && cursor) return sessionError(400, "INVALID_CURSOR", "A fixed forecast cannot use a history cursor");
      if (forecast) forecastQuery.set("record_id", forecast);
      if (cursor) forecastQuery.set("before", cursor);
      if (limit) forecastQuery.set("limit", limit);
    }
    return forwardJson(await pdosApiFetch(`/api/projects/${projectId}/execution${suffix}${(forecastQuery.size ? `?${forecastQuery}` : "") || reallocationQuery || (scheduleCursor ? `?before=${scheduleCursor}` : before ? `?before_id=${before}` : target ? `?target_id=${target}` : forecast ? `?record_id=${forecast}` : "")}`, { method: request.method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body }));
  } catch (error) { return sessionError(error instanceof InvalidRequestBodyError ? 400 : 503, "EXECUTION_UNAVAILABLE", "执行申请暂不可用，请稍后重试"); }
}
