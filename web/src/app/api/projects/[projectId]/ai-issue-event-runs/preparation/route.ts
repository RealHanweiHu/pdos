import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string }> };
export async function GET(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const params = new URL(request.url).searchParams, event = params.get("event_row_id");
  if (event === null || params.getAll("event_row_id").length !== 1 || !/^[1-9][0-9]*$/.test(event) || !Number.isSafeInteger(Number(event))) return sessionError(400, "INVALID_EVENT", "请选择有效的异常来源");
  try {
    const { projectId } = await context.params;
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-event-runs/preparation?event_row_id=${event}`, { method: "GET", headers: { Authorization: `Bearer ${token}` } }));
  } catch { return sessionError(503, "ISSUE_EVENT_PREPARATION_UNAVAILABLE", "来源资料暂不可用，请稍后重试"); }
}
