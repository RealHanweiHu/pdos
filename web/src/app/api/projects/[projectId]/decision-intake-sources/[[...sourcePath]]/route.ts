import { currentSessionToken, forwardJson, pdosApiFetch, readBoundedJson, sessionError, InvalidRequestBodyError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string; sourcePath?: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
async function forward(method: "GET" | "POST", request: Request, context: Context) {
  const { projectId, sourcePath = [] } = await context.params;
  if (!uuid.test(projectId) || !uuid.test(sourcePath[0] ?? "") || !(method === "GET" ? sourcePath.length === 1 || sourcePath.length === 2 && ["target-options", "amendments", "amendment-evidence"].includes(sourcePath[1] ?? "") : sourcePath.length === 2 && ["corrections", "amendments"].includes(sourcePath[1] ?? ""))) return sessionError(404, "SOURCE_ROUTE_NOT_FOUND", "来源办理入口不存在");
  const token = await currentSessionToken(); if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请先登录");
  try {
    const query = new URLSearchParams();
    if (method === "GET") for (const key of ["before_revision", "kind", "search", "target_id", "before_updated_at", "before_created_at", "before_id"]) { const value = new URL(request.url).searchParams.get(key); if (value) query.set(key, value); }
    const body = method === "POST" ? JSON.stringify(await readBoundedJson(request, sourcePath[1] === "amendments" ? 1024 * 1024 : 32768)) : undefined;
    return forwardJson(await pdosApiFetch(`/api/projects/${projectId}/decision-intake-sources/${sourcePath.map(encodeURIComponent).join("/")}${query.size ? `?${query}` : ""}`, { method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "请检查纠错资料长度与格式");
    return sessionError(503, "SOURCE_UNAVAILABLE", "来源办理暂不可用，请读取回执后继续");
  }
}
export const GET = (request: Request, context: Context) => forward("GET", request, context);
export const POST = (request: Request, context: Context) => forward("POST", request, context);
