import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string }> };
function positive(value: string): boolean { return /^[1-9][0-9]*$/.test(value) && Number.isSafeInteger(Number(value)); }

export async function GET(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const params = new URL(request.url).searchParams;
  const before = params.get("before");
  const limit = params.get("limit") ?? "20";
  if ((before !== null && !positive(before)) || !positive(limit) || Number(limit) > 20 || params.getAll("before").length > 1 || params.getAll("limit").length > 1) {
    return sessionError(400, "INVALID_SOURCE_CURSOR", "来源分页位置无效，请刷新后重试");
  }
  const query = new URLSearchParams({ limit });
  if (before !== null) query.set("before", before);
  try {
    const { projectId } = await context.params;
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/ai-issue-event-sources?${query}`, { method: "GET", headers: { Authorization: `Bearer ${token}` } }));
  } catch {
    return sessionError(503, "ISSUE_EVENT_SOURCES_UNAVAILABLE", "异常来源暂不可用，请稍后重试");
  }
}
