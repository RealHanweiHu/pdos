import { currentSessionToken, forwardJson, pdosApiFetch, readBoundedJson, sessionError, InvalidRequestBodyError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; jobId: string; action: string }> };
async function proxy(request: Request, context: Context, method: "GET" | "POST") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请先登录");
  const { projectId, jobId, action } = await context.params;
  if (!["history", "resume"].includes(action) || method === "POST" && action !== "resume") return sessionError(404, "NOT_FOUND", "未找到办理入口");
  try {
    const query = new URLSearchParams();
    const source = new URL(request.url).searchParams;
    const key = action === "history" ? "before_id" : "request_id";
    if (source.has(key)) query.set(key, source.get(key)!);
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/knowledge-prepared/${encodeURIComponent(jobId)}/${action}${query.size ? `?${query}` : ""}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(method === "POST" ? { "Content-Type": "application/json" } : {}) },
      body: method === "POST" ? JSON.stringify(await readBoundedJson(request, 32_768)) : undefined,
    }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "请填写完整的恢复依据");
    return sessionError(503, "KNOWLEDGE_REUSE_UNAVAILABLE", "暂未取得准备记录，请稍后回查");
  }
}
export function GET(request: Request, context: Context) { return proxy(request, context, "GET"); }
export function POST(request: Request, context: Context) { return proxy(request, context, "POST"); }
