import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";
export async function GET(request: Request, context: { params: Promise<{ projectId: string; riskId: string; taskId: string }> }) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const { projectId, riskId, taskId } = await context.params;
  const source = new URL(request.url).searchParams, query = new URLSearchParams();
  for (const key of ["search", "before_created_at", "before_id"]) { const value = source.get(key); if (value) query.set(key, value); }
  try { return forwardJson(await pdosApiFetch(
    `/api/projects/${encodeURIComponent(projectId)}/risks/${encodeURIComponent(riskId)}/follow-up/${encodeURIComponent(taskId)}/results/evidence?${query}`,
    { headers: { Authorization: `Bearer ${token}` }, cache: "no-store" },
  )); } catch { return sessionError(503, "RISK_EVIDENCE_UNAVAILABLE", "风险处理证据暂不可用"); }
}
