import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

export async function GET(request: Request, context: { params: Promise<{ projectId: string; riskId: string }> }) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const { projectId, riskId } = await context.params;
  const search = new URL(request.url).searchParams, query = new URLSearchParams();
  for (const key of ["kind", "offset"]) { const value = search.get(key); if (value) query.set(key, value); }
  try {
    return forwardJson(await pdosApiFetch(
      `/api/projects/${encodeURIComponent(projectId)}/risks/${encodeURIComponent(riskId)}/references?${query}`,
      { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
    ));
  } catch { return sessionError(503, "RISK_SERVICE_UNAVAILABLE", "风险业务引用暂不可用"); }
}
