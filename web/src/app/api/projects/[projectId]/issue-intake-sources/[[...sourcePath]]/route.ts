import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string; sourcePath?: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
async function forward(method: "GET" | "POST", request: Request, context: Context) {
  const { projectId, sourcePath: path = [] } = await context.params;
  const batchRoute = path[0] === "batches" && (method === "GET" ? (path.length === 2 || path.length === 3 && path[2] === "progress") && uuid.test(path[1]) : path.length === 1 || path.length === 2 && path[1] === "preview");
  const sourceRoute = uuid.test(path[0] ?? "") && (method === "GET" ? path.length === 1 || path.length === 2 && ["issue-options", "references"].includes(path[1]) : path.length === 2 && path[1] === "corrections");
  if (!uuid.test(projectId) || !(batchRoute || sourceRoute)) return sessionError(404, "ISSUE_SOURCE_ROUTE_NOT_FOUND", "Source route not found");
  const token = await currentSessionToken(); if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const query = new URLSearchParams(), incoming = new URL(request.url).searchParams;
    if (method === "GET") for (const key of path[2] === "progress" ? ["before_source_id", "before_issue_id"] : path[1] === "issue-options" ? ["search", "issue_id", "before_updated_at", "before_id"] : path[1] === "references" ? ["kind", "issue_id", "before_id", "before_issue_id", "before_path_id"] : ["before_revision"]) { const value = incoming.get(key); if (value) query.set(key, value); }
    return forwardJson(await pdosApiFetch(`/api/projects/${projectId}/issue-intake-sources/${path.map(encodeURIComponent).join("/")}${query.size ? `?${query}` : ""}`, { method, headers: { Authorization: `Bearer ${token}`, ...(method === "POST" ? { "Content-Type": "application/json" } : {}) }, body: method === "POST" ? JSON.stringify(await readBoundedJson(request, batchRoute ? 8 * 1024 * 1024 : 32768)) : undefined }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_REQUEST", "Source correction body is invalid");
    return sessionError(503, "ISSUE_SOURCE_UNAVAILABLE", "来源办理暂不可用，请刷新查询原回执");
  }
}
export const GET = (request: Request, context: Context) => forward("GET", request, context);
export const POST = (request: Request, context: Context) => forward("POST", request, context);
