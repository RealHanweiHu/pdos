import { currentSessionToken, forwardJson, InvalidRequestBodyError, pdosApiFetch, readBoundedJson, sessionError } from "@/lib/pdos-api";

type Context = { params: Promise<{ projectId: string; completionPath?: string[] }> };
type Method = "GET" | "PUT" | "POST";
const keys = new Set(["configuration", "bom", "manufacturing", "test_certification", "training", "residuals", "quality_follow_up"]);
async function forward(method: Method, request: Request, context: Context) {
  const { projectId, completionPath = [] } = await context.params;
  const [first, key, last] = completionPath;
  const allowed = (method === "GET" && (!completionPath.length || (completionPath.length === 3 && first === "handoff" && keys.has(key ?? "") && last === "history"))) ||
    (method === "PUT" && completionPath.length === 1 && first === "issue-policy") ||
    (first === "handoff" && keys.has(key ?? "") && ((method === "PUT" && completionPath.length === 2) || (method === "POST" && completionPath.length === 3 && last === "response")));
  if (!allowed) return sessionError(404, "COMPLETION_ROUTE_NOT_FOUND", "Completion route not found");
  const token = await currentSessionToken();
  if (!token) return sessionError(401, "INVALID_ACCESS_TOKEN", "Authentication required");
  try {
    const body = method === "GET" ? undefined : await readBoundedJson(request);
    return forwardJson(await pdosApiFetch(`/api/projects/${encodeURIComponent(projectId)}/completion${completionPath.length ? `/${completionPath.map(encodeURIComponent).join("/")}` : ""}${method === "GET" ? new URL(request.url).search : ""}`, {
      method, headers: { Authorization: `Bearer ${token}`, ...(body ? { "Content-Type": "application/json" } : {}) }, ...(body ? { body: JSON.stringify(body) } : {}),
    }));
  } catch (error) {
    return error instanceof InvalidRequestBodyError ? sessionError(400, "INVALID_REQUEST", "Valid JSON required") : sessionError(503, "COMPLETION_UNAVAILABLE", "结项清单暂不可用");
  }
}
export function GET(request: Request, context: Context) { return forward("GET", request, context); }
export function PUT(request: Request, context: Context) { return forward("PUT", request, context); }
export function POST(request: Request, context: Context) { return forward("POST", request, context); }
