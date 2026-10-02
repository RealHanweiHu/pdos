import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; protocolId: string }> };
export async function GET(_request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const { projectId, protocolId } = await context.params;
  if (!/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(protocolId)) return sessionError(400, "INVALID_TRIAL_ID", "请选择有效的原试运行登记");
  try {
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-trials/${encodeURIComponent(protocolId)}`, { method: "GET", headers: { Authorization: `Bearer ${token}` } }));
  } catch { return sessionError(503, "ISSUE_TRIAL_UNAVAILABLE", "原试运行登记暂不可用，请重试读取"); }
}
