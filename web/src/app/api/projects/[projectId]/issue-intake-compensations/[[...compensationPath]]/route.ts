import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string; compensationPath?: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
async function forward(method: "GET" | "POST", request: Request, context: Context) {
  const { projectId, compensationPath: path = [] } = await context.params;
  const bindingRoute = path.length === 3 && path[0] === "bindings" && uuid.test(path[1]) && (path[2] === "results" || method === "GET" && path[2] === "evidence");
  const valid = bindingRoute || (method === "GET" ? path.length === 1 && uuid.test(path[0]) : path.length === 0 || path.length === 1 && path[0] === "preview");
  if (!uuid.test(projectId) || !valid) return sessionError(404, "ISSUE_COMPENSATION_ROUTE_NOT_FOUND", "Compensation route not found");
  const token = await currentSessionToken(); if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  const query = new URLSearchParams();
  if (method === "GET" && bindingRoute) {
    const incoming = new URL(request.url).searchParams;
    for (const key of path[2] === "results" ? ["before_revision"] : ["search", "before_created_at", "before_id"]) {
      const value = incoming.get(key); if (value !== null) query.set(key, value);
    }
  }
  try {
    return forwardJson(await pdosApiFetch(`/api/projects/${projectId}/issue-intake-compensations${path.length ? `/${path.map(encodeURIComponent).join("/")}` : ""}${query.size ? `?${query}` : ""}`, { method, headers: { Authorization: `Bearer ${token}`, ...(method === "POST" ? { "Content-Type": "application/json" } : {}) }, body: method === "POST" ? JSON.stringify(await readBoundedJson(request, 8 * 1024 * 1024)) : undefined }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "本批内容过大或格式不完整，请分批办理");
    return sessionError(503, "ISSUE_COMPENSATION_UNAVAILABLE", "补偿办理暂不可用，请刷新查看原任务与办理回执");
  }
}
export const GET = (request: Request, context: Context) => forward("GET", request, context);
export const POST = (request: Request, context: Context) => forward("POST", request, context);
