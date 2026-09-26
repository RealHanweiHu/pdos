import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string; taskId: string; section: string }> };
export async function GET(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请先登录");
  const { projectId, taskId, section } = await context.params;
  if (!["residuals", "history"].includes(section)) return sessionError(404, "NOT_FOUND", "未找到记录");
  const source = new URL(request.url).searchParams, query = new URLSearchParams();
  for (const key of section === "history" ? ["before_revision"] : ["kind", "search", "after_id"]) if (source.has(key)) query.set(key, source.get(key)!);
  try {
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/takeover/${section}?${query}`, { method: "GET", headers: { Authorization: `Bearer ${token}` } }));
  } catch { return sessionError(503, "TAKEOVER_UNAVAILABLE", "资料暂不可读取，请重试"); }
}
