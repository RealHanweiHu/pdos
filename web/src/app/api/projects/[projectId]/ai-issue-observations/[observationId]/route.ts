import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; observationId: string }> };
export async function GET(_request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const { projectId, observationId } = await context.params;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(observationId)) return sessionError(400, "INVALID_OBSERVATION_ID", "请选择有效的原观察记录");
  try {
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-observations/${encodeURIComponent(observationId)}`, { method: "GET", headers: { Authorization: `Bearer ${token}` } }));
  } catch { return sessionError(503, "ISSUE_OBSERVATION_UNAVAILABLE", "原观察记录暂不可用，请重试读取"); }
}
