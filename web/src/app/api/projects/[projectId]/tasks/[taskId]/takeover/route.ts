import { currentSessionToken, forwardJson, pdosApiFetch, readBoundedJson, sessionError, InvalidRequestBodyError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string; taskId: string }> };
async function proxy(request: Request, context: Context, method: "GET" | "POST") {
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请先登录");
  const { projectId, taskId } = await context.params;
  const params = new URL(request.url).searchParams, query = new URLSearchParams();
  if (params.has("request_id")) query.set("request_id", params.get("request_id")!);
  try {
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/tasks/${encodeURIComponent(taskId)}/takeover${query.size ? `?${query}` : ""}`, { method, headers: { Authorization: `Bearer ${token}`, ...(method === "POST" ? { "Content-Type": "application/json" } : {}) }, body: method === "POST" ? JSON.stringify(await readBoundedJson(request, 262_144)) : undefined }));
  } catch (e) {
    if (e instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "请提交完整交接内容");
    return sessionError(503, "TAKEOVER_UNAVAILABLE", "暂未取得交接回执，请回查原请求");
  }
}
export function GET(request: Request, context: Context) { return proxy(request, context, "GET"); }
export function POST(request: Request, context: Context) { return proxy(request, context, "POST"); }
