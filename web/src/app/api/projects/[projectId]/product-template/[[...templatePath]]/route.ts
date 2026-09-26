import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; templatePath?: string[] }> };
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[1-5][0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/i;
async function forward(method: "GET" | "POST", request: Request, context: Context) {
  const { projectId, templatePath = [] } = await context.params;
  const allowed = method === "GET" ? templatePath.length === 0 :
    (templatePath.length === 1 && templatePath[0] === "proposals") ||
    (templatePath.length === 3 && templatePath[0] === "versions" && uuid.test(templatePath[1] ?? "") && templatePath[2] === "decision");
  if (!allowed) return sessionError(404, "TEMPLATE_ROUTE_NOT_FOUND", "Template route not found");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = method === "GET" ? undefined : await readBoundedJson(request);
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/product-template${templatePath.length ? `/${templatePath.map(encodeURIComponent).join("/")}` : ""}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}),
    }));
  } catch (error) {
    return error instanceof InvalidRequestBodyError ? sessionError(400, "INVALID_REQUEST", "Valid JSON required") : sessionError(503, "TEMPLATE_UNAVAILABLE", "产品模板暂不可用");
  }
}
export function GET(request: Request, context: Context) { return forward("GET", request, context); }
export function POST(request: Request, context: Context) { return forward("POST", request, context); }
