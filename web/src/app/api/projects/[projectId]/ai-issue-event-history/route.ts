import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string }> };
export async function GET(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const search = new URL(request.url).searchParams, event = search.get("event_row_id"), before = search.get("before_id");
  if (event === null || !/^[1-9][0-9]*$/.test(event) || !Number.isSafeInteger(Number(event)) || search.getAll("event_row_id").length !== 1 || search.getAll("before_id").length > 1 || (before !== null && !/^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i.test(before))) return sessionError(400, "INVALID_TRIGGER_CURSOR", "请选择有效的来源与触发历史位置");
  const query = new URLSearchParams({ event_row_id: event });
  if (before !== null) query.set("before_id", before);
  try {
    const { projectId } = await context.params;
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-event-history?${query}`, { method: "GET", headers: { Authorization: `Bearer ${token}` } }));
  } catch { return sessionError(503, "ISSUE_EVENT_HISTORY_UNAVAILABLE", "自动触发记录暂不可用，请稍后重试"); }
}
