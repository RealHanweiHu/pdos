import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

export async function GET(_request: Request, context: { params: Promise<{ projectId: string; requestId: string }> }) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const { projectId, requestId } = await context.params;
  try {
    return forwardJson(await pdosApiFetch(
      `/api/projects/${encodeURIComponent(projectId)}/risk-candidates/batches/${encodeURIComponent(requestId)}`,
      { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
    ));
  } catch {
    return sessionError(503, "RISK_SERVICE_UNAVAILABLE", "风险确认回执暂不可用");
  }
}
