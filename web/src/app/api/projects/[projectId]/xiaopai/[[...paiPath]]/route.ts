import { currentSessionToken, forwardJson, pdosApiFetch, readBoundedJson, sessionError, InvalidRequestBodyError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string; paiPath?: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
async function forward(method: "GET" | "POST", request: Request, context: Context) {
  const { projectId, paiPath: path = [] } = await context.params;
  const allowed = method === "GET" ? path.length === 0 : path.length === 1 && path[0] === "delegations" || path.length === 3 && uuid.test(path[1]) && (path[0] === "delegations" && path[2] === "state" || path[0] === "followups" && path[2] === "reply");
  if (!uuid.test(projectId) || !allowed) return sessionError(404, "XIAOPAI_NOT_FOUND", "入口不存在");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请重新登录");
  try {
    return forwardJson(await pdosApiFetch(`/api/projects/${projectId}/xiaopai${path.length ? `/${path.join("/")}` : ""}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(method === "POST" ? { "Content-Type": "application/json" } : {}) },
      body: method === "POST" ? JSON.stringify(await readBoundedJson(request, 16384)) : undefined,
    }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST_BODY", "内容过长或格式无效");
    return sessionError(503, "XIAOPAI_UNAVAILABLE", "小Pai暂时无法连接，请稍后查看已保存的委托");
  }
}
export const GET = (request: Request, context: Context) => forward("GET", request, context);
export const POST = (request: Request, context: Context) => forward("POST", request, context);
