import { currentSessionToken, forwardJson, pdosApiFetch, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; gateId: string }> };
export async function GET(request: Request, context: Context) {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请先登录");
  try {
    const { projectId, gateId } = await context.params;
    const query = new URLSearchParams();
    const before = new URL(request.url).searchParams.get("before");
    if (before) query.set("before", before);
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/gates/${encodeURIComponent(gateId)}/conditions${query.size ? `?${query}` : ""}`, { headers: { Authorization: `Bearer ${token}` } }));
  } catch {
    return sessionError(503, "GATE_SERVICE_UNAVAILABLE", "条件落实记录暂不可用，请稍后重试");
  }
}
