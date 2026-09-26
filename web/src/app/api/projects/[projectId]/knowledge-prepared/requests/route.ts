import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string }> };
export async function GET(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请先登录");
  const { projectId } = await context.params;
  const source = new URL(request.url).searchParams, query = new URLSearchParams();
  for (const key of ["context_kind", "context_entity_id", "before_created_at", "before_id"]) if (source.has(key)) query.set(key, source.get(key)!);
  try {
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/knowledge-prepared/requests?${query}`, { method: "GET", headers: { Authorization: `Bearer ${token}` } }));
  } catch { return sessionError(503, "KNOWLEDGE_REUSE_UNAVAILABLE", "历史请求暂不可读取，请重试"); }
}
