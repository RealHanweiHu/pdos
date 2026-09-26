import { currentSessionToken, forwardJson, pdosApiFetch, readBoundedJson, sessionError, InvalidRequestBodyError } from "@/lib/pdos-api";
type Context = { params: Promise<{ projectId: string; intakePath?: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
async function forward(method: "GET" | "POST", request: Request, context: Context) {
  const { projectId, intakePath: path = [] } = await context.params;
  const shapes = method === "GET" ? [[], ["decision-work", "#", "references"], ["decision-batches", "#", "corrections"], ["decision-sources", "#", "batches"], ["decision-batches", "#", "progress"], ["work", "#", "results"], ["decision-work", "#"], ["sources"], ["work-sources"], ["sources", "#"], ["tasks"], ["proposals", "#"], ["proposals", "#", "earlier-work"]] : [["decision-batches", "#", "corrections"], ["work", "#", "results"], ["proposals"], ["proposals", "#", "apply"]];
  if (!uuid.test(projectId) || !shapes.some(shape => shape.length === path.length && shape.every((part, i) => part === "#" ? uuid.test(path[i]) : part === path[i]))) return sessionError(404, "INTAKE_NOT_FOUND", "现状导入入口不存在");
  const token = await currentSessionToken(); if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "请先登录");
  try {
    const query = new URLSearchParams();
    if (method === "GET") for (const key of ["before_path_id", "offset", "before_source_id", "before_decision_id", "before_binding_id", "expected_scope_digest", "target_id", "kind", "before_revision", "search", "before_id", "after_ordinal"]) { const value = new URL(request.url).searchParams.get(key); if (value) query.set(key, value); }
    const body = method === "POST" ? JSON.stringify(await readBoundedJson(request, 4 * 1024 * 1024)) : undefined;
    return forwardJson(await pdosApiFetch(`/api/projects/${projectId}/intake${path.length ? `/${path.map(encodeURIComponent).join("/")}` : ""}${query.size ? `?${query}` : ""}`, { method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, body }));
  } catch (error) {
    if (error instanceof InvalidRequestBodyError) return sessionError(400, "INVALID_INTAKE_BODY", "请检查资料长度与格式");
    return sessionError(503, "INTAKE_UNAVAILABLE", "现状导入暂不可用，请读取已保存版本或回执后继续");
  }
}
export const GET = (request: Request, context: Context) => forward("GET", request, context);
export const POST = (request: Request, context: Context) => forward("POST", request, context);
